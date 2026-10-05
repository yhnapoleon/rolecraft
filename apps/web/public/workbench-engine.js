(function (root) {
  'use strict';

  // Local prototype rules only. No network calls, language model or hidden answer key.
  const VERSION = 1;
  const PURPOSES = ['探索笔记', '测试计划', '方案比较', '试点决定', '自由作品'];
  // Purpose doubles as intent: only a formal decision is checked as a commitment.
  const INTENTS = { '探索笔记': 'explore', '自由作品': 'explore', '方案比较': 'option', '测试计划': 'plan', '试点决定': 'commit' };
  const intentOf = purpose => INTENTS[purpose] || 'explore';
  const PRIORITIES = ['first', 'next', 'later'];
  const TEST_SET_LIMITS = Object.freeze({ cases: 20, question: 4000, intent: 2000, expectation: 2000 });
  const INVESTIGATION_LIMITS = Object.freeze({ blocks: 8, question: 1000, noteTitle: 120, noteText: 2000, testIds: 4, label: 80 });
  const WORK_COSTS = { scope: 1, fallback: 1, realtime: 5 };
  const scenarios = [
    { id: 'pilot', title: '知识助手，准备好试点了吗？', kicker: 'AI 产品经理 · 主案例', description: '接手一个即将开放的内部知识助手，决定先服务谁、开放什么，以及如何保障。', duration: '约 20–30 分钟 · 可随时暂停', capacity: 30, deadline: 7 },
    { id: 'urgent', title: '演示提前之后', kicker: '条件变化 · 时间取舍', description: '同样的业务责任，演示提前到三天后。重新考虑范围、证据与承诺。', duration: '约 15–25 分钟 · 可随时暂停', capacity: 30, deadline: 3 },
    { id: 'capacity', title: '先让谁用起来？', kicker: '条件变化 · 使用范围', description: '可用容量缩至 15 人。重新理解首批需求，作出有依据的范围选择。', duration: '约 15–25 分钟 · 可随时暂停', capacity: 15, deadline: 7 }
  ];
  const roles = [
    { id: 'manager', name: '经理', person: 'Priya', initials: '经', job: '目标、资源与优先级', color: 'purple' },
    { id: 'business', name: '业务负责人', person: 'Mei', initials: '业', job: '需求、流程与政策', color: 'amber' },
    { id: 'technical', name: '技术负责人', person: 'Daniel', initials: '技', job: '系统、证据与实现', color: 'blue' }
  ];
  // Career is the first layer. Only the PM path has supported cases; the engineer
  // path is listed as a later path and never opens placeholder content.
  const careers = [
    { id: 'pm', name: 'AI 产品经理', status: 'open', summary: '判断一个 AI 功能该不该上线、先给谁用、怎样保障，并为这个决定负责。', work: ['弄清需求和约束', '亲手测试 AI 助手', '和三位同事协商', '交付有依据的决定'], cases: ['pilot', 'urgent', 'capacity'] },
    { id: 'engineer', name: 'AI 应用工程师', status: 'later', summary: '复现检索与回答问题，修改代码或配置，用可复现的测试证明修复。', work: ['复现问题', '定位检索与证据缺陷', '修改并回归测试', '说明取舍'], cases: [] }
  ];
  let counter = 0;
  const now = () => new Date().toISOString();
  const uid = prefix => prefix + '-' + Date.now().toString(36) + '-' + (++counter).toString(36) + '-' + Math.random().toString(36).slice(2, 9);
  const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const clone = value => JSON.parse(JSON.stringify(value));
  function object(value, label) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error((label || '输入') + '必须是对象');
    return value;
  }
  function str(value, label, max, empty) {
    if (typeof value !== 'string') throw new Error(label + '必须是文字');
    const result = value.trim();
    if ((!empty && !result) || result.length > (max || 10000)) throw new Error(label + '为空或超过长度限制');
    return result;
  }
  function choice(value, values, label) {
    if (!values.includes(value)) throw new Error(label + '无效');
    return value;
  }
  function attempt(a) {
    object(a, '练习');
    if (!a.id || !Array.isArray(a.tasks) || !Array.isArray(a.artifacts) || !a.world || !Array.isArray(a.events)) throw new Error('练习记录无效');
    // JSON/localStorage round-trips drop Object.freeze; restore snapshot immutability.
    if (Array.isArray(a.submissions)) a.submissions.forEach(deepFreeze);
    return a;
  }
  function state(s) {
    object(s, '存档');
    if (s.version !== VERSION || !Array.isArray(s.attempts)) throw new Error('存档版本无效');
    return s;
  }
  function find(items, id, label) {
    const found = items.find(item => item.id === id);
    if (!found) throw new Error((label || '记录') + '不存在');
    return found;
  }
  function safeJSON(value, max) {
    const seen = new Set();
    function inspect(item, depth) {
      if (depth > 20) throw new Error('内容层级过深');
      if (!item || typeof item !== 'object') return;
      if (seen.has(item)) throw new Error('内容不能有循环引用');
      seen.add(item);
      for (const key of Object.keys(item)) {
        if (['__proto__', 'constructor', 'prototype'].includes(key)) throw new Error('内容包含不支持的字段');
        inspect(item[key], depth + 1);
      }
      seen.delete(item);
    }
    inspect(value, 0);
    const serialized = JSON.stringify(value);
    if (!serialized || serialized.length > (max || 100000)) throw new Error('内容超过长度限制');
    return JSON.parse(serialized);
  }
  function deepFreeze(value) {
    if (value && typeof value === 'object' && !Object.isFrozen(value)) {
      Object.values(value).forEach(deepFreeze);
      Object.freeze(value);
    }
    return value;
  }
  function configCost(config) {
    const items = new Set(config.workItems);
    if (config.update === 'realtime') items.add('realtime');
    return Array.from(items).reduce((total, item) => total + WORK_COSTS[item], 0);
  }
  function log(a, type, text, detail) {
    attempt(a);
    const event = { id: uid('event'), type: str(type, '事件类型', 60), text: str(text, '事件说明', 5000), createdAt: now() };
    if (detail !== undefined) event.detail = safeJSON(detail, type === 'artifact_saved' ? 600000 : 100000);
    a.events.push(event);
    return event;
  }
  function newState() { return { version: VERSION, activeId: null, attempts: [], casePriorities: { pilot: 'first', urgent: 'next', capacity: 'later' } }; }
  function getAttempt(s) { state(s); return s.attempts.find(a => a.id === s.activeId) || null; }
  function createAttempt(s, scenarioId, options) {
    state(s);
    const scenario = find(scenarios, scenarioId, '案例');
    const intake = options && options.intake ? safeJSON(options.intake, 20000) : null;
    const a = {
      id: uid('attempt'), scenarioId, title: scenario.title, createdAt: now(), selectedTaskId: null,
      tasks: [], artifacts: [], config: { participants: Math.min(20, scenario.capacity), domains: ['faq', 'policy'], update: 'daily', fallback: 'none', workItems: [] },
      configDraft: null, configVersion: 1,
      world: { capacity: scenario.capacity, devDays: 3, deadline: scenario.deadline, policyVersion: 1, indexVersion: 1 },
      tests: [], conversations: { manager: [], business: [], technical: [] }, events: [], requests: [], submissions: [], parentSubmissionId: null,
      career: 'pm', intake, nudges: []
    };
    [
      { title: '确认首批员工的使用需求', note: '业务团队希望首批员工查找办公流程和差旅政策；具体范围与优先级需要你判断。', priority: 'next', seed: 'needs' },
      { title: '回应政策问答的开放请求', note: '业务团队希望试点支持政策查询。请判断如何回应这个请求，以及需要哪些依据。', priority: 'next', seed: 'policy' },
      { title: '形成可执行的试点决定', note: '经理希望了解可以承诺什么、需要什么条件，以及何时调整或暂停。', priority: 'next', seed: 'decision' }
    ].forEach(input => { const t = addTask(a, input); t.seed = input.seed; });
    a.selectedTaskId = a.tasks[0].id;
    log(a, 'attempt_created', '已进入案例；事项由你安排，可以随时暂停。', { scenarioId });
    if (options && options.parentAttemptId) a.parentAttemptId = String(options.parentAttemptId).slice(0, 160);
    s.attempts.push(a);
    s.activeId = a.id;
    return a;
  }
  function addTask(a, input) {
    attempt(a); object(input, '事项');
    const task = { id: uid('task'), title: str(input.title, '事项名称', 120), note: str(input.note === undefined ? '' : input.note, '事项说明', 5000, true), priority: choice(input.priority || 'next', PRIORITIES, '优先级'), status: 'open', createdAt: now() };
    a.tasks.push(task);
    log(a, 'task_added', '新增事项：' + task.title, { taskId: task.id });
    return task;
  }
  function updateTask(a, id, patch) {
    attempt(a); object(patch, '事项修改');
    const task = find(a.tasks, id, '事项');
    const clean = {};
    if (own(patch, 'title')) clean.title = str(patch.title, '事项名称', 120);
    if (own(patch, 'note')) clean.note = str(patch.note, '事项说明', 5000, true);
    if (own(patch, 'priority')) clean.priority = choice(patch.priority, PRIORITIES, '优先级');
    if (own(patch, 'status')) clean.status = choice(patch.status, ['open', 'working', 'done'], '事项状态');
    Object.assign(task, clean);
    log(a, 'task_updated', '更新事项：' + task.title, { taskId: id, changes: clean });
    return task;
  }
  function allowedKeys(value, keys, label) {
    object(value, label);
    const unexpected = Object.keys(value).find(key => !keys.includes(key));
    if (unexpected) throw new Error((label || '内容') + '包含不支持的字段：' + unexpected);
  }
  function plainTestText(value, label, max, empty) {
    const text = str(value, label, max, empty);
    if (/<\s*\/?\s*(script|iframe|object|embed|style)\b|javascript\s*:|```\s*(javascript|js|html)\b/i.test(text)) throw new Error(label + '不能包含可执行脚本或页面');
    return text;
  }
  function testRefs(refs) {
    if (refs === undefined) return [];
    if (!Array.isArray(refs) || refs.length > 20) throw new Error('测试依据最多 20 项');
    const out = [];
    for (const ref of refs) {
      allowedKeys(ref, ['id', 'version'], '测试依据');
      const id = str(ref.id, '资料 ID', 160);
      if (!Number.isSafeInteger(ref.version) || ref.version < 1) throw new Error('资料版本必须是正整数');
      if (!out.some(x => x.id === id && x.version === ref.version)) out.push({ id, version: ref.version });
    }
    return out;
  }
  function testCaseContent(row, empty) {
    object(row, '测试行');
    return {
      question: plainTestText(row.question === undefined && empty ? '' : row.question, '测试问题', TEST_SET_LIMITS.question, empty),
      intent: plainTestText(row.intent === undefined && empty ? '' : row.intent, '验证目的', TEST_SET_LIMITS.intent, empty),
      expectation: plainTestText(row.expectation === undefined ? '' : row.expectation, '预期表现', TEST_SET_LIMITS.expectation, true),
      refs: testRefs(row.refs)
    };
  }
  function visibleMaterials(a) { return a.backend ? (a.backend.materials || []) : getMaterials(a); }
  function assertTestRefs(a, cases, scope) {
    const materials = scope || visibleMaterials(a);
    for (const row of cases) for (const ref of row.refs || []) {
      if (!materials.some(m => m.id === ref.id && m.version === ref.version)) throw new Error('测试依据不属于可用资料或任务包版本：' + ref.id + ' v' + ref.version);
    }
  }
  function testSetSummary(work) {
    const rows = Array.isArray(work.cases) ? work.cases : [];
    return rows.map((row, i) => '### ' + (i + 1) + '. ' + (row.question || '待填写问题') + '\n\n验证目的：' + (row.intent || '待补充') + (row.expectation ? '\n\n预期表现（待验证）：' + row.expectation : '') + ((row.refs || []).length ? '\n\n资料：' + row.refs.map(ref => ref.id + '@v' + ref.version).join('；') : '')).join('\n\n');
  }
  function investigationBlockContent(block, local = false, empty = false) {
    object(block, '调查模块');
    const identity = local ? ['id', 'revision'] : [];
    switch (block.type) {
      case 'note': {
        allowedKeys(block, [...identity, 'type', 'title', 'text'], '分析模块');
        const value = { type: 'note', text: plainTestText(block.text, '分析内容', INVESTIGATION_LIMITS.noteText, empty) };
        if (block.title !== undefined) value.title = plainTestText(block.title, '模块标题', INVESTIGATION_LIMITS.noteTitle, true);
        return value;
      }
      case 'test_compare': {
        allowedKeys(block, [...identity, 'type', 'testIds'], '测试对照模块');
        if (!Array.isArray(block.testIds) || !block.testIds.length || block.testIds.length > INVESTIGATION_LIMITS.testIds) throw new Error('测试对照需要 1–4 个实际测试 ID');
        const testIds = block.testIds.map(id => str(id, '测试 ID', 160));
        if (new Set(testIds).size !== testIds.length) throw new Error('测试对照中的 ID 不能重复');
        return { type: 'test_compare', testIds };
      }
      case 'source_check': {
        allowedKeys(block, [...identity, 'type', 'testId', 'material'], '来源核对模块');
        if (block.material === undefined) throw new Error('来源核对需要明确的资料与版本');
        return { type: 'source_check', testId: str(block.testId, '测试 ID', 160), material: testRefs([block.material])[0] };
      }
      case 'retest': {
        allowedKeys(block, [...identity, 'type', 'testId', 'label'], '重测模块');
        const value = { type: 'retest', testId: str(block.testId, '测试 ID', 160) };
        if (block.label !== undefined) value.label = plainTestText(block.label, '重测标签', INVESTIGATION_LIMITS.label, true);
        return value;
      }
      default: throw new Error('不支持的调查模块类型');
    }
  }
  function investigationBlocks(blocks, local = false, empty = false) {
    if (!Array.isArray(blocks) || !blocks.length || blocks.length > INVESTIGATION_LIMITS.blocks) throw new Error('调查视图需要 1–8 个模块');
    return blocks.map(block => investigationBlockContent(block, local, empty));
  }
  function investigationReferences(work) {
    const testIds = []; const materials = [];
    const view = work.draft ? { ...work, ...work.draft } : work;
    for (const block of view.blocks || []) {
      const ids = block.type === 'test_compare' ? block.testIds : ['source_check', 'retest'].includes(block.type) ? [block.testId] : [];
      for (const id of ids || []) if (!testIds.includes(id)) testIds.push(id);
      if (block.type === 'source_check' && !materials.some(m => m.id === block.material.id && m.version === block.material.version)) materials.push(clone(block.material));
    }
    return { testIds, materials };
  }
  function assertInvestigationRefs(a, blocks, scope) {
    const refs = investigationReferences({ blocks });
    for (const id of refs.testIds) {
      if (!a.tests.some(test => test.id === id)) throw new Error('调查引用的测试不在当前会话真实记录中：' + id);
      if (scope && !(scope.tests || []).some(test => test.id === id)) throw new Error('调查引用的测试不在本次任务包中：' + id);
    }
    const materials = scope ? scope.materials || [] : visibleMaterials(a);
    for (const ref of refs.materials) {
      if (!visibleMaterials(a).some(material => material.id === ref.id)) throw new Error('调查资料在当前会话不可读：' + ref.id);
      if (!materials.some(material => material.id === ref.id && material.version === ref.version)) throw new Error('调查资料不属于可用资料或任务包版本：' + ref.id + ' v' + ref.version);
    }
    for (const block of blocks) if (block.type === 'source_check') {
      const test = a.tests.find(item => item.id === block.testId);
      if (!(test.citations || []).some(cite => (cite.id || cite.material_id) === block.material.id)) throw new Error('来源核对的资料必须是该次测试实际引用的资料');
    }
  }
  function investigationSummary(work) {
    const sections = ['## 调查问题\n\n' + (work.question || '待明确')];
    for (const block of work.blocks || []) {
      if (block.type === 'note') sections.push('### ' + (block.title || '分析') + '\n\n' + block.text);
      if (block.type === 'test_compare') sections.push('### 测试对照\n\n实际运行：' + block.testIds.join('；'));
      if (block.type === 'source_check') sections.push('### 来源核对\n\n测试 ' + block.testId + ' 的实际引用，对照资料 ' + block.material.id + '@v' + block.material.version + '。');
      if (block.type === 'retest') sections.push('### ' + (block.label || '同题重测') + '\n\n待用户操作：按测试 ' + block.testId + ' 的问题重新运行；本模块不代表已经执行。');
    }
    return sections.join('\n\n');
  }
  function artifactSnapshot(artifact) {
    const result = { revision: artifact.revision, title: artifact.title, purpose: artifact.purpose, body: artifact.body, evidence: clone(artifact.evidence || []) };
    if (artifact.kind) result.kind = artifact.kind;
    if (artifact.kind === 'test_set') result.cases = clone(artifact.cases);
    if (artifact.kind === 'investigation') { result.question = artifact.question; result.blocks = clone(artifact.blocks); }
    if (artifact.ruleOrigin !== undefined) result.ruleOrigin = artifact.ruleOrigin;
    return safeJSON(result, 500000);
  }
  function recordArtifactChange(a, artifact, previous) {
    artifact.revision += 1;
    artifact.updatedAt = now();
    log(a, 'artifact_saved', '保存作品 v' + artifact.revision + '：' + artifact.title, { artifactId: artifact.id, revision: artifact.revision, previous });
  }
  function assertArtifactPresent(artifact) {
    if (artifact.removedAt) throw new Error('作品已移除，请先从“已移除作品”恢复');
    return artifact;
  }
  function assertLifecycleWritable(a) {
    const status = (a.backend && a.backend.status) || a.world.status || 'active';
    if (status !== 'active') throw new Error(status === 'paused' ? '练习已暂停，恢复后才能移除或还原作品' : '这次练习只读，不能移除或还原作品');
  }
  function removeArtifact(a, id) {
    attempt(a); assertLifecycleWritable(a);
    const artifact = find(a.artifacts, id, '作品');
    if (artifact.removedAt) return artifact;
    const removedAt = now();
    log(a, 'artifact_removed', '移除作品：' + artifact.title, { artifactId: id, revision: artifact.revision, removedAt });
    artifact.removedAt = removedAt;
    return artifact;
  }
  function restoreArtifact(a, id) {
    attempt(a); assertLifecycleWritable(a);
    const artifact = find(a.artifacts, id, '作品');
    if (!artifact.removedAt) return artifact;
    log(a, 'artifact_restored', '恢复作品：' + artifact.title, { artifactId: id, revision: artifact.revision, removedAt: artifact.removedAt });
    artifact.removedAt = null;
    return artifact;
  }
  function createArtifact(a, input, options) {
    attempt(a); object(input, '作品');
    const taskId = input.taskId == null ? null : find(a.tasks, input.taskId, '关联事项').id;
    const adopted = input.adopted === undefined ? true : input.adopted;
    if (typeof adopted !== 'boolean') throw new Error('采用状态无效');
    const stamp = now();
    if (input.kind !== undefined && !['text', 'test_set', 'investigation'].includes(input.kind)) throw new Error('不支持的作品类型');
    const artifact = { id: uid('artifact'), taskId, title: str(input.title, '作品名称', 160), purpose: choice(input.purpose || (input.kind === 'test_set' ? '测试计划' : input.kind === 'investigation' ? '探索笔记' : '自由作品'), PURPOSES, '作品用途'), body: ['test_set', 'investigation'].includes(input.kind) ? '' : str(input.body === undefined ? '' : input.body, '作品正文', 50000, true), source: str(input.source === undefined ? 'user' : input.source, '作品来源', 100), adopted, adoptedAt: adopted ? stamp : null, revision: 1, createdAt: stamp, updatedAt: stamp, evidence: [] };
    if (input.kind === 'text') artifact.kind = 'text';
    if (input.kind === 'test_set') {
      if (!Array.isArray(input.cases) || input.cases.length > TEST_SET_LIMITS.cases) throw new Error('测试作品最多 20 行');
      artifact.kind = 'test_set';
      artifact.cases = input.cases.map(row => ({ id: uid('case'), revision: 1, ...testCaseContent(row, true) }));
      assertTestRefs(a, artifact.cases, options && options.referenceScope);
      artifact.body = testSetSummary(artifact);
    }
    if (input.kind === 'investigation') {
      artifact.kind = 'investigation';
      artifact.question = plainTestText(input.question, '调查问题', INVESTIGATION_LIMITS.question);
      artifact.blocks = investigationBlocks(input.blocks).map(block => ({ id: uid('block'), revision: 1, ...block }));
      assertInvestigationRefs(a, artifact.blocks, options && options.investigationScope);
      artifact.body = investigationSummary(artifact);
      if (input.ruleOrigin !== undefined) {
        if (artifact.source !== 'user') throw new Error('规则来源只能由本地应用记录');
        artifact.ruleOrigin = input.ruleOrigin === true ? true : str(input.ruleOrigin, '规则来源', 120);
      }
    }
    a.artifacts.push(artifact);
    log(a, 'artifact_created', '创建作品：' + artifact.title, { artifactId: artifact.id, source: artifact.source, adopted });
    return artifact;
  }
  function saveArtifact(a, id, input) {
    attempt(a); object(input, '作品修改');
    const artifact = assertArtifactPresent(find(a.artifacts, id, '作品'));
    if (own(input, 'kind') && input.kind !== artifact.kind) throw new Error('不能通过保存改变作品类型');
    if (own(input, 'cases') && artifact.kind !== 'test_set') throw new Error('普通作品不能保存测试行');
    if ((own(input, 'question') || own(input, 'blocks')) && artifact.kind !== 'investigation') throw new Error('这份作品不能保存调查模块');
    const next = {
      title: own(input, 'title') ? str(input.title, '作品名称', 160) : artifact.title,
      purpose: own(input, 'purpose') ? choice(input.purpose, PURPOSES, '作品用途') : artifact.purpose,
      body: ['test_set', 'investigation'].includes(artifact.kind) ? artifact.body : own(input, 'body') ? str(input.body, '作品正文', 50000, true) : artifact.body
    };
    if (artifact.kind === 'test_set') {
      const rows = own(input, 'cases') ? input.cases : artifact.cases;
      if (!Array.isArray(rows) || rows.length > TEST_SET_LIMITS.cases) throw new Error('测试作品最多 20 行');
      const seen = new Set();
      next.cases = rows.map(row => {
        allowedKeys(row, ['id', 'revision', 'question', 'intent', 'expectation', 'refs'], '测试行');
        const old = row.id ? artifact.cases.find(c => c.id === row.id) : null;
        if (row.id && !old) throw new Error('测试行不属于这份作品');
        if (old && seen.has(old.id)) throw new Error('测试行 ID 重复');
        if (old) seen.add(old.id);
        const content = testCaseContent(row, true);
        if (!old || JSON.stringify(content.refs) !== JSON.stringify(old.refs)) assertTestRefs(a, [content]);
        const changed = !old || JSON.stringify(content) !== JSON.stringify(testCaseContent(old, true));
        return { id: old ? old.id : uid('case'), revision: old ? old.revision + (changed ? 1 : 0) : 1, ...content };
      });
      next.body = testSetSummary(next);
    }
    if (artifact.kind === 'investigation') {
      next.question = own(input, 'question') ? plainTestText(input.question, '调查问题', INVESTIGATION_LIMITS.question, true) : artifact.question;
      const blocks = own(input, 'blocks') ? input.blocks : artifact.blocks;
      const content = investigationBlocks(blocks, true, true); const seen = new Set();
      next.blocks = blocks.map((block, index) => {
        const old = block.id ? artifact.blocks.find(item => item.id === block.id) : null;
        if (block.id && !old) throw new Error('调查模块不属于这份作品');
        if (old && seen.has(old.id)) throw new Error('调查模块 ID 重复');
        if (old) seen.add(old.id);
        const changed = !old || JSON.stringify(content[index]) !== JSON.stringify(investigationBlockContent(old, true, true));
        if (changed) assertInvestigationRefs(a, [content[index]]);
        return { id: old ? old.id : uid('block'), revision: old ? old.revision + (changed ? 1 : 0) : 1, ...content[index] };
      });
      next.body = investigationSummary(next);
    }
    if (next.title === artifact.title && next.purpose === artifact.purpose && next.body === artifact.body && (!next.cases || JSON.stringify(next.cases) === JSON.stringify(artifact.cases)) && (!next.blocks || (next.question === artifact.question && JSON.stringify(next.blocks) === JSON.stringify(artifact.blocks)))) return artifact;
    const previous = artifactSnapshot(artifact);
    const becameDecision = next.purpose !== artifact.purpose && intentOf(next.purpose) === 'commit';
    Object.assign(artifact, next);
    // Colleagues react when work becomes a commitment, not on every keystroke save.
    if (becameDecision) checkCommitment(a, artifact);
    recordArtifactChange(a, artifact, previous);
    return artifact;
  }
  function moveInvestigationBlock(a, workId, blockId, beforeId) {
    attempt(a); assertLifecycleWritable(a);
    const work = assertArtifactPresent(find(a.artifacts, workId, '作品'));
    if (work.kind !== 'investigation') throw new Error('这份作品不是调查视图');
    const block = find(work.blocks, blockId, '调查模块');
    if (beforeId) find(work.blocks, beforeId, '目标模块');
    if (beforeId === blockId) return work;
    const blocks = work.blocks.filter(item => item.id !== blockId);
    const position = beforeId ? blocks.findIndex(item => item.id === beforeId) : blocks.length;
    blocks.splice(position, 0, block);
    return saveArtifact(a, workId, { blocks });
  }
  function testWork(a, workId) {
    attempt(a); const work = assertArtifactPresent(find(a.artifacts, workId, '作品'));
    if (work.kind !== 'test_set') throw new Error('这份作品不是测试作品');
    return work;
  }
  function updateTestCase(a, workId, caseId, patch) {
    const work = testWork(a, workId); find(work.cases, caseId, '测试行');
    allowedKeys(patch, ['question', 'intent', 'expectation', 'refs'], '测试行修改');
    const rows = work.cases.map(row => row.id === caseId ? { ...row, ...patch } : row);
    if (own(patch, 'refs')) assertTestRefs(a, [testCaseContent(rows.find(row => row.id === caseId), true)]);
    return saveArtifact(a, workId, { cases: rows });
  }
  function addTestCase(a, workId, input = {}) {
    const work = testWork(a, workId);
    allowedKeys(input, ['question', 'intent', 'expectation', 'refs'], '测试行');
    const row = testCaseContent(input, true); assertTestRefs(a, [row]);
    saveArtifact(a, workId, { cases: [...work.cases, row] });
    return work.cases[work.cases.length - 1];
  }
  function removeTestCase(a, workId, caseId) {
    const work = testWork(a, workId); find(work.cases, caseId, '测试行');
    return saveArtifact(a, workId, { cases: work.cases.filter(row => row.id !== caseId) });
  }
  function restoreTestCase(a, workId, caseId) {
    const work = testWork(a, workId); str(caseId, '测试行 ID', 160);
    if (work.cases.some(row => row.id === caseId)) return work;
    if (work.cases.length >= TEST_SET_LIMITS.cases) throw new Error('测试作品最多 20 行，无法恢复');
    // Restoration only accepts an identity. Content comes from this work's own
    // saved history, so undo cannot import a foreign row or manufacture a run.
    const event = a.events.slice().reverse().find(item => item.type === 'artifact_saved' && item.detail && item.detail.artifactId === workId && item.detail.previous && item.detail.previous.kind === 'test_set' && Array.isArray(item.detail.previous.cases) && item.detail.previous.cases.some(row => row.id === caseId));
    if (!event) throw new Error('这份作品的历史中没有可恢复的测试行');
    const oldRows = event.detail.previous.cases;
    const index = oldRows.findIndex(row => row.id === caseId);
    const old = oldRows[index];
    if (!Number.isSafeInteger(old.revision) || old.revision < 1) throw new Error('历史测试行版本无效');
    const restored = { id: caseId, revision: old.revision, ...testCaseContent(old, true) };
    const previous = artifactSnapshot(work);
    // Keep surviving neighbours in order; unrelated subsequent edits survive.
    const next = oldRows.slice(index + 1).find(row => work.cases.some(current => current.id === row.id));
    const preceding = oldRows.slice(0, index).reverse().find(row => work.cases.some(current => current.id === row.id));
    const position = next ? work.cases.findIndex(row => row.id === next.id) : preceding ? work.cases.findIndex(row => row.id === preceding.id) + 1 : Math.min(index, work.cases.length);
    work.cases.splice(position, 0, restored);
    work.body = testSetSummary(work);
    recordArtifactChange(a, work, previous);
    log(a, 'test_case_restored', '恢复测试问题：' + (restored.question || '待填写问题'), { artifactId: workId, caseId, caseRevision: restored.revision, revision: work.revision });
    return work;
  }
  function adoptArtifact(a, id) {
    attempt(a);
    const artifact = assertArtifactPresent(find(a.artifacts, id, '作品'));
    if (!artifact.adopted) {
      artifact.adopted = true;
      artifact.updatedAt = now();
      artifact.adoptedAt = artifact.updatedAt;
      if (artifact.source !== 'user' && !(artifact.kind === 'investigation' && investigationLinkedRunIds(a, artifact).length)) nudge(a, 'technical', '你采用了「' + artifact.title + '」。里面写到的测试还没有真正跑过，要作为依据的话，先在助手测试里跑一遍。', { kind: 'remind', key: 'adopt-' + id, targetId: id, taskId: artifact.taskId });
      log(a, 'artifact_adopted', '已采用回传作品：' + artifact.title + '；内容仍需检查和验证。', { artifactId: id });
    }
    return artifact;
  }
  function currentArtifacts(a) {
    attempt(a);
    const byId = new Map(a.artifacts.map(item => [item.id, item]));
    const latestByChain = new Map();
    for (const item of a.artifacts) {
      if (!item.adopted) continue;
      let ancestor = item;
      let chainId = item.id;
      const seen = new Set([item.id]);
      while (ancestor.parentArtifactId) {
        chainId = ancestor.parentArtifactId;
        if (seen.has(chainId)) throw new Error('作品修订链存在循环');
        seen.add(chainId);
        ancestor = byId.get(chainId);
        if (!ancestor) break;
      }
      // Append order is the explicit branch order. Editing an old retained work
      // never silently makes it the current branch again. Pending imports are
      // excluded and cannot supersede an adopted work.
      latestByChain.set(chainId, item);
    }
    // A removed chain head still supersedes its ancestors. Filtering before
    // selecting the head would silently resurrect an older adopted version.
    return Array.from(latestByChain.values()).filter(item => !item.removedAt);
  }
  function addEvidence(a, artifactId, evidenceObject) {
    attempt(a); object(evidenceObject, '证据');
    const artifact = assertArtifactPresent(find(a.artifacts, artifactId, '作品'));
    const evidence = safeJSON(evidenceObject, 30000);
    if (!evidence.id) throw new Error('证据需要记录 ID');
    str(evidence.id, '证据 ID', 160);
    const validIds = new Set([...a.tests.map(x => x.id), ...a.events.map(x => x.id), ...visibleMaterials(a).map(x => x.id)]);
    if (!validIds.has(evidence.id)) throw new Error('证据不属于当前练习的可读材料或记录');
    if (!artifact.evidence.some(item => item.id === evidence.id && item.version === evidence.version)) {
      const previous = artifactSnapshot(artifact);
      artifact.evidence.push(evidence);
      recordArtifactChange(a, artifact, previous);
      log(a, 'evidence_added', '作品关联了证据：' + (evidence.title || evidence.id), { artifactId, evidenceId: evidence.id });
    }
    return evidence;
  }
  function getMaterials(a) {
    attempt(a);
    const approved = a.requests.some(r => r.status === 'approved');
    return [
      { id: 'brief', title: '经理的试点委托', version: approved ? 2 : 1, body: '希望在 ' + a.world.deadline + ' 个业务日内开放知识助手试点。请决定先服务谁、开放什么、需要什么保障，以及怎样观察效果和何时暂停。可以提出有条件延期或缩小范围，并说明依据。这是场景中的业务条件，练习没有倒计时。' },
      { id: 'business', title: '首批使用需求', version: 1, body: '业务团队希望首批员工能查找办公流程和差旅政策。办公流程较稳定，政策会发生变化。请明确哪些人和问题纳入试点，并保留无法确认时的人工处理路径。这里尚未给出完整的需求优先级或成功指标，需要你形成判断。' },
      { id: 'policy', title: '差旅住宿政策', version: a.world.policyVersion, body: '国内差旅住宿报销上限为每晚 SGD ' + (a.world.policyVersion === 1 ? '500' : '400') + '。超出部分需按审批流程另行确认。当前来源版本 v' + a.world.policyVersion + '。知识助手索引版本与源文件可能不同。' },
      { id: 'technical', title: '系统与资源说明', version: a.world.policyVersion + a.world.indexVersion - 1 + Number(approved), body: '当前试点容量 ' + a.world.capacity + ' 人，可用开发资源 ' + a.world.devDays + ' 人日。范围控制、人工兜底工作项各需 1 人日，实时同步需 5 人日。每日索引更新可能滞后 24 小时；政策转人工模式会将政策问题交由人工处理。当前索引 v' + a.world.indexVersion + '，政策源 v' + a.world.policyVersion + '。申请获批和配置实际应用分别记录；添加日期提醒不会更新索引。' },
      { id: 'faq', title: '办公流程 FAQ', version: 1, body: '会议室可以在内部日历中预约；设备和账号问题提交 IT 服务台。办公流程 FAQ 在本案例中保持 v1。知识助手的原型回答采用固定规则，不能代表真实 RAG 或模型质量。' }
    ];
  }
  function readMaterial(a, id) {
    const material = find(getMaterials(a), id, '材料');
    log(a, 'material_read', '查看材料：' + material.title + ' v' + material.version, { materialId: id, version: material.version });
    return material;
  }
  function runTest(a, input) {
    attempt(a); object(input, '测试');
    const question = str(input.question, '测试问题', 5000);
    const expectation = str(input.expectation === undefined ? '' : input.expectation, '测试预期', 5000, true);
    const isPolicy = /差旅|出差|住宿|酒店|hotel|travel|accommodation|lodging/i.test(question) || (/报销|上限|额度|reimburse|expense/i.test(question) && !/年假|假期|加班|社保|公积金|leave|overtime/i.test(question));
    const isFaq = /会议|办公|账号|帐号|设备|预约|密码|IT|office|room|account|equipment/i.test(question);
    let answer; let citations = [];
    if (isPolicy && a.config.update === 'manual') {
      answer = '当前采用政策转人工模式。请将差旅政策问题转交业务负责人核对，本次不提供自动金额结论。';
    } else if (isPolicy && !a.config.domains.includes('policy')) {
      answer = a.config.fallback === 'human' ? '政策问答未纳入本次试点。请将这个问题转交业务负责人进行人工确认。' : '政策问答未纳入本次试点，助手暂不回答这个问题。';
    } else if (isPolicy && a.config.fallback === 'human' && a.world.indexVersion < a.world.policyVersion) {
      answer = '当前政策索引与来源版本不同。请转交业务负责人核对最新政策，本次不提供金额结论。';
    } else if (isPolicy) {
      answer = '国内差旅住宿报销上限为每晚 SGD ' + (a.world.indexVersion === 1 ? '500' : '400') + '；超出部分需要另行审批。';
      citations = [{ id: 'policy', title: '差旅住宿政策', version: a.world.indexVersion }];
      if (a.config.fallback === 'date') answer += ' 请注意引用版本日期；日期提醒本身不会更新索引。';
    } else if (isFaq && a.config.domains.includes('faq')) {
      answer = '会议室可在内部日历中预约；设备或账号问题请提交 IT 服务台。';
      citations = [{ id: 'faq', title: '办公流程 FAQ', version: 1 }];
    } else {
      answer = a.config.fallback === 'human' ? '当前可用资料不足以回答，请转交人工进一步确认。' : '本原型没有足够的资料回答这类问题：这里只模拟了差旅住宿政策和办公流程 FAQ。可以换个问题，或向同事查证。';
    }
    const taskId = input.taskId && a.tasks.some(t => t.id === input.taskId) ? input.taskId : null;
    const run = { id: uid('test'), question, expectation, answer, citations, taskId, config: clone(a.config), configVersion: a.configVersion, policyVersion: a.world.policyVersion, indexVersion: a.world.indexVersion, createdAt: now(), mode: 'simulated' };
    a.tests.push(run);
    if (citations.some(c => c.id === 'policy' && c.version < a.world.policyVersion)) nudge(a, 'technical', '刚才那次回答引用的是索引 v' + a.world.indexVersion + '，政策源已经是 v' + a.world.policyVersion + '。每日更新最多滞后 24 小时；可以刷新索引，或者先把政策问题转人工。', { kind: 'correct', key: 'stale-index', targetId: run.id, taskId: run.taskId || taskByTitle(a, '政策') });
    log(a, 'test_run', '完成一次规则模拟测试；结果需由你解释。', { testId: run.id, configVersion: run.configVersion, policyVersion: run.policyVersion, indexVersion: run.indexVersion });
    return run;
  }
  function updateConfig(a, patch) {
    attempt(a); object(patch, '配置');
    const next = clone(a.configDraft || a.config);
    if (own(patch, 'participants')) {
      if (!Number.isInteger(patch.participants) || patch.participants < 1 || patch.participants > 10000) throw new Error('试点人数须为 1–10000 的整数');
      next.participants = patch.participants;
    }
    if (own(patch, 'domains')) {
      if (!Array.isArray(patch.domains) || patch.domains.length > 2) throw new Error('知识范围无效');
      next.domains = [...new Set(patch.domains.map(d => choice(d, ['faq', 'policy'], '知识范围')))];
    }
    if (own(patch, 'update')) next.update = choice(patch.update, ['daily', 'realtime', 'manual'], '更新方式');
    if (own(patch, 'fallback')) next.fallback = choice(patch.fallback, ['none', 'human', 'date'], '兜底方式');
    if (own(patch, 'workItems')) {
      if (!Array.isArray(patch.workItems) || patch.workItems.length > 30) throw new Error('工作项过多');
      next.workItems = [...new Set(patch.workItems.map(item => choice(item, Object.keys(WORK_COSTS), '工作项')))];
    }
    a.configDraft = clone(next);
    const reasons = [];
    if (next.participants > a.world.capacity) reasons.push('试点人数 ' + next.participants + ' 超过当前容量 ' + a.world.capacity);
    if (!next.domains.length) reasons.push('尚未选择可开放的知识范围');
    const cost = configCost(next);
    if (cost > a.world.devDays) reasons.push('所选工作与更新方式合计需要 ' + cost + ' 人日，当前仅有 ' + a.world.devDays + ' 人日');
    if (reasons.length) {
      const reason = reasons.join('；') + '。已保留草案，正在使用的配置未变。';
      if (cost > a.world.devDays) nudge(a, 'technical', '这套配置要 ' + cost + ' 人日，我们只有 ' + a.world.devDays + ' 人日。要么请经理批资源，要么换一种更新方式。', { kind: 'correct', key: 'cost-over-' + a.world.devDays });
      if (next.participants > a.world.capacity) nudge(a, 'manager', a.world.capacity + ' 人是这次能给的容量。想放 ' + next.participants + ' 人，先说清楚多出来的人靠什么撑住。', { kind: 'object', key: 'capacity-over-' + a.world.capacity });
      log(a, 'config_draft', reason, { draft: next, applied: false });
      return { applied: false, reason, config: clone(a.config) };
    }
    const changed = JSON.stringify(a.config) !== JSON.stringify(next);
    a.config = clone(next);
    a.configDraft = null;
    if (changed) a.configVersion++;
    if (a.config.update === 'realtime') a.world.indexVersion = a.world.policyVersion;
    log(a, 'config_applied', '配置 v' + a.configVersion + ' 已在规则模拟中应用；可以重新测试。', { applied: true, configVersion: a.configVersion, config: next });
    return { applied: true, reason: '配置已应用；需要重新测试才能检查回答结果。', config: clone(a.config) };
  }
  function refreshIndex(a) {
    attempt(a);
    if (a.world.indexVersion === a.world.policyVersion) return false;
    a.world.indexVersion = a.world.policyVersion;
    log(a, 'index_refreshed', '已模拟一次索引刷新：当前索引 v' + a.world.indexVersion + '。已有测试保持原记录。', { indexVersion: a.world.indexVersion });
    return true;
  }
  function triggerPolicyUpdate(a, source) {
    attempt(a);
    if (a.world.policyVersion >= 2) return false;
    a.world.policyVersion = 2;
    if (a.config.update === 'realtime') a.world.indexVersion = 2;
    nudge(a, 'business', '差旅政策刚改了：住宿上限从每晚 500 降到 400。员工要是按旧答案订酒店，超出的部分报不了。你的试点里，政策问答还照原计划开放吗？', { kind: 'remind', key: 'policy-v2', taskId: taskByTitle(a, '政策') });
    log(a, 'policy_updated', (source === 'scenario' ? '场景变化' : '演示控制') + '：政策源更新为 v2，住宿上限改为 SGD 400。', { policyVersion: 2, indexVersion: a.world.indexVersion, mode: 'simulated', source: source === 'scenario' ? 'scenario' : 'demo' });
    return true;
  }
  function requestResources(a, reason) {
    attempt(a);
    const request = { id: uid('request'), reason: str(reason, '申请理由', 5000), status: 'pending', createdAt: now(), mode: 'simulated' };
    a.requests.push(request);
    log(a, 'resource_requested', '已提出资源申请，等待场景审批；条件尚未改变。', { requestId: request.id });
    return request;
  }
  function resolveResources(a, requestId) {
    attempt(a);
    const request = find(a.requests, requestId, '申请');
    if (request.status !== 'pending') return request;
    if (!/人日|资源|开发|延期|期限|时间|同步|容量|兜底|人工|\d/.test(request.reason)) {
      request.status = 'needs-info';
      request.resolvedAt = now();
      request.result = '经理需要你说明要多少资源、用来做什么。';
      nudge(a, 'manager', '这个申请我还批不了：你要多少资源、用来做什么？说清楚我再看。', { kind: 'object', key: 'needs-info-' + requestId });
      log(a, 'resource_question', request.result, { requestId });
      return request;
    }
    request.status = 'approved';
    request.resolvedAt = now();
    request.result = '按原型审批规则批准：可用开发量调整至 6 人日，业务期限调整至 10 天。配置仍需另外应用。';
    a.world.devDays = 6;
    a.world.deadline = 10;
    nudge(a, 'manager', '批了：开发资源加到 6 人日，期限放到第 10 天。配置要你自己去改，改完记得重测。', { kind: 'help', key: 'approved-' + requestId });
    log(a, 'resource_approved', request.result, { requestId, mode: 'simulated', devDays: 6, deadline: 10 });
    return request;
  }
  function reply(a, roleId, text, taskId) {
    attempt(a); find(roles, roleId, '同事');
    const content = str(text, '消息', 5000);
    if (taskId != null) find(a.tasks, taskId, '关联事项');
    const history = a.conversations[roleId];
    const userMessage = { id: uid('message'), role: 'user', content, text: content, taskId: taskId || null, createdAt: now(), mode: 'simulated' };
    history.push(userMessage);
    let response;
    const resourceQuestion = /资源|人日|实时|容量|人数|延期|期限|时间|开发|capacity|resource|deadline/i.test(content);
    const policyQuestion = /政策|差旅|报销|住宿|更新|索引|policy|index/i.test(content);
    const priorityQuestion = /优先|先做|怎么开始|不知道|没头绪|顺序|priority|first/i.test(content);
    if (roleId === 'manager') {
      if (resourceQuestion) response = '当前容量为 ' + a.world.capacity + ' 人，可用开发资源 ' + a.world.devDays + ' 人日，业务期限为 ' + a.world.deadline + ' 天。实时同步需要 5 人日。需要增加资源或调整期限时，请提交具体理由；这段对话本身不会批准申请。';
      else if (priorityQuestion) response = '可以先选一个最影响当前承诺的未知点。我关心你准备向谁提供什么价值，以及承诺靠什么成立。你可以先试用，也可以先查需求；优先级由你决定。';
      else response = '我负责业务目标与资源安排。当前需要你形成有依据的试点决定，明确服务对象、范围、保障与暂停条件。可以缩小范围或提出延期。请指出希望我确认的具体目标或约束；我无法仅凭这条信息判断整份方案是否成立。';
    } else if (roleId === 'business') {
      if (policyQuestion) response = '当前政策源是 v' + a.world.policyVersion + '，差旅住宿上限为每晚 SGD ' + (a.world.policyVersion === 1 ? '500' : '400') + '。请查看政策原文及助手引用的版本；我关心用户是否会因此作出错误决定。技术同步状况请向技术负责人确认。';
      else if (resourceQuestion) response = '我掌握首批员工的办公流程和差旅政策需求；技术容量及开发资源请向经理或技术负责人确认。对我而言，需要先说明选定用户要解决什么问题。';
      else response = '首批员工希望查询办公流程和差旅政策。办公流程较稳定，政策会变化。我关心实际问题是否得到可靠处理，无法确认时用户还能找谁。你可以带一个具体使用问题来讨论，当前没有完整需求排序可以直接套用。';
    } else {
      if (policyQuestion) response = '当前政策源 v' + a.world.policyVersion + '，助手索引 v' + a.world.indexVersion + '。每日更新可能滞后 24 小时；标注日期不会刷新索引。可以查看一次实际模拟测试的引用版本，或在演示控制中模拟索引刷新，再比较结果。';
      else if (resourceQuestion) response = '当前容量 ' + a.world.capacity + ' 人，可用开发资源 ' + a.world.devDays + ' 人日。实时同步需要 5 人日；资源未满足时，系统只保留配置草案。经理批准资源后仍要应用配置并重测。';
      else response = '我可以解释系统约束和已有运行记录。你可以提供具体问题、回答或测试 ID，检查配置与引用版本。当前知识助手和同事回复均为规则模拟；开放语义、真实模型质量和业务优先级需要进一步验证。';
    }
    const message = { id: uid('message'), role: 'assistant', roleId, content: response, text: response, taskId: taskId || null, createdAt: now(), mode: 'simulated' };
    history.push(message);
    log(a, 'colleague_replied', find(roles, roleId).name + '给出了规则模拟回复。', { roleId, messageId: message.id, taskId: taskId || null });
    return message;
  }
  function review(a, artifactId) {
    attempt(a);
    const artifact = artifactId == null ? null : find(a.artifacts, artifactId, '作品');
    const works = artifact ? [artifact] : currentArtifacts(a);
    const observations = [];
    const add = (status, title, text, evidenceIds) => observations.push({ status, title, text, evidenceIds: evidenceIds || [] });
    if (artifact) add('confirmed', '作品版本已保存', artifact.title + ' · v' + artifact.revision + ' · ' + artifact.purpose + (artifact.adopted ? '；采用状态已记录。' : '；外部回传尚未采用。'), [artifact.id]);
    if (!artifact && works.length) add('confirmed', '当前作品版本已确定', works.map(item => item.title + ' v' + item.revision).join('；') + '。每条修订链只纳入最新的已采用工作版本，历史版本仍可单独查看。', works.map(item => item.id));
    if (!works.some(item => item.adopted && item.body.trim())) add('pending', '尚无可评价的已采用作品', '本次尝试可以记录，但目前没有有内容且已采用的作品，无法判断试点决定的理由或交付质量。');
    add(a.config.participants <= a.world.capacity ? 'confirmed' : 'check', '试点人数与容量', '当前配置 ' + a.config.participants + ' 人，可用容量 ' + a.world.capacity + ' 人。这里只核对数值，不判断选人是否合理。');
    if (a.configDraft) add('check', '存在尚未应用的配置草案', '草案没有改变实际使用的配置，请查看资源或容量限制。');
    add(configCost(a.config) <= a.world.devDays ? 'confirmed' : 'check', '工作项与资源', '当前已应用工作与更新方式需要 ' + configCost(a.config) + ' 人日，可用开发资源 ' + a.world.devDays + ' 人日。这里只核对明确的场景成本。');
    if (a.config.update === 'realtime') add(a.world.devDays >= 5 ? 'confirmed' : 'check', '实时同步资源', '实时同步需要 5 人日，当前可用 ' + a.world.devDays + ' 人日。');
    const latest = a.tests[a.tests.length - 1];
    if (!latest) add('pending', '尚无测试记录', '还没有可用执行证据，无法判断助手是否支持你的决定。');
    else {
      add('confirmed', '测试运行已留痕', '已保存 ' + a.tests.length + ' 次规则模拟测试。记录可核对问题、回答、引用和当时配置；不代表答案已通过语义评审。', [latest.id]);
      if (latest.configVersion !== a.configVersion || latest.policyVersion !== a.world.policyVersion || latest.indexVersion !== a.world.indexVersion) add('check', '最近测试与当前条件不同', '最近测试使用配置 v' + latest.configVersion + '、政策源 v' + latest.policyVersion + '、索引 v' + latest.indexVersion + '。当前为配置 v' + a.configVersion + '、政策源 v' + a.world.policyVersion + '、索引 v' + a.world.indexVersion + '；需要判断是否重测。', [latest.id]);
      if (latest.citations.some(c => c.id === 'policy' && c.version < latest.policyVersion)) add('check', '该次回答引用了较旧政策', '此测试发生时，引用版本低于当时有效政策源版本。请检查这一差异对判断的影响。', [latest.id]);
    }
    add('pending', '判断质量仍需情境化评审', '此原型不会根据关键词或字数给能力打分。用户意图、作品推理、需求覆盖和个人理解，需要结合完整情境与经过验证的 Judge 或人工评阅。', artifact ? [artifact.id] : []);
    const result = { observations, summary: '规则检查已完成；语义判断与训练效果尚未验证。没有总分或通过／失败结论。' };
    log(a, 'review_requested', '请求评审：返回可核对的记录与待确认项。', { artifactId: artifactId || null, result });
    return result;
  }
  function submit(a) {
    attempt(a);
    const reviewResult = review(a);
    const snapshot = deepFreeze(clone({ id: uid('submission'), createdAt: now(), parentId: a.parentSubmissionId, parentSubmissionId: a.parentSubmissionId, title: a.title, scenarioId: a.scenarioId, tasks: a.tasks, artifacts: currentArtifacts(a), config: a.config, configDraft: a.configDraft, configVersion: a.configVersion, world: a.world, tests: a.tests, conversations: a.conversations, nudges: a.nudges || [], acks: a.acks || [], events: a.events, requests: a.requests, review: reviewResult }));
    a.submissions.push(snapshot);
    log(a, 'submitted', '已保存交付快照 ' + a.submissions.length + '，工作区可继续修改。', { submissionId: snapshot.id, parentId: snapshot.parentId });
    return snapshot;
  }
  function chainRoot(a, artifact) {
    const byId = new Map(a.artifacts.map(item => [item.id, item]));
    let node = artifact; const seen = new Set();
    while (node && node.parentArtifactId && byId.has(node.parentArtifactId) && !seen.has(node.id)) { seen.add(node.id); node = byId.get(node.parentArtifactId); }
    return node ? node.id : artifact.id;
  }
  // Work that changed after a submission; revising from the snapshot would otherwise hide it.
  function laterEdits(a, submissionId) {
    attempt(a);
    const snapshot = find(a.submissions, submissionId, '交付快照');
    const latest = currentArtifacts(a);
    return snapshot.artifacts.map(item => {
      const head = latest.find(x => chainRoot(a, x) === chainRoot(a, a.artifacts.find(y => y.id === item.id) || item));
      // Revisions only move forward, so a higher head revision means later work (independent of clock resolution).
      return head && head.revision > item.revision && head.body !== item.body ? { title: head.title, snapshotRevision: item.revision, currentRevision: head.revision } : null;
    }).filter(Boolean);
  }
  function revise(a, submissionId, options) {
    attempt(a);
    const snapshot = find(a.submissions, submissionId, '交付快照');
    const fromCurrent = options && options.basis === 'current';
    const latest = currentArtifacts(a);
    // A revision branches the submitted works. Current world and execution records stay current.
    const branchId = uid('revision');
    const revisions = snapshot.artifacts.map(item => {
      const live = a.artifacts.find(y => y.id === item.id);
      const root = chainRoot(a, live || item);
      const head = latest.find(x => chainRoot(a, x) === root);
      const chainMax = Math.max(item.revision, ...a.artifacts.filter(x => chainRoot(a, x) === root).map(x => x.revision));
      const base = fromCurrent && head ? head : item;
      const stamp = now();
      return { ...clone(base), id: uid('artifact'), revision: chainMax + 1, createdAt: stamp, updatedAt: stamp, adopted: true, adoptedAt: stamp, parentArtifactId: fromCurrent && head ? head.id : item.id, sourceSubmissionId: snapshot.id, revisionBranchId: branchId };
    });
    a.artifacts.push(...revisions);
    a.parentSubmissionId = snapshot.id;
    log(a, 'revision_started', '从交付快照创建关联修订' + (fromCurrent ? '（以交付后的当前版本为起点）' : '') + '，原快照与当前其他作品均保留。', { submissionId, basis: fromCurrent ? 'current' : 'snapshot', artifactIds: revisions.map(item => item.id) });
    return revisions;
  }
  // Older saves may miss fields added later; fill them so every view can render.
  function normalizeAttempt(a) {
    object(a, '练习');
    a.tasks = Array.isArray(a.tasks) ? a.tasks : [];
    a.artifacts = Array.isArray(a.artifacts) ? a.artifacts : [];
    a.artifacts.forEach(x => {
      if (x.removedAt === undefined) x.removedAt = null;
      if (!Array.isArray(x.evidence)) x.evidence = [];
      if (typeof x.body !== 'string') x.body = '';
      if (x.kind === 'test_set') {
        if (!Array.isArray(x.cases) || x.cases.length > TEST_SET_LIMITS.cases) throw new Error('测试作品存档无效');
        const ids = new Set();
        x.cases = x.cases.map(row => {
          const id = str(row.id, '测试行 ID', 160);
          if (ids.has(id) || !Number.isSafeInteger(row.revision) || row.revision < 1) throw new Error('测试行身份或版本无效');
          ids.add(id);
          return { id, revision: row.revision, ...testCaseContent(row, true) };
        });
        x.body = testSetSummary(x);
      }
      if (x.kind === 'investigation') {
        x.question = plainTestText(x.question, '调查问题', INVESTIGATION_LIMITS.question, true);
        const content = investigationBlocks(x.blocks, true, true); const ids = new Set();
        x.blocks = x.blocks.map((block, index) => {
          const id = str(block.id, '调查模块 ID', 160);
          if (ids.has(id) || !Number.isSafeInteger(block.revision) || block.revision < 1) throw new Error('调查模块身份或版本无效');
          ids.add(id);
          return { id, revision: block.revision, ...content[index] };
        });
        x.body = investigationSummary(x);
      }
    });
    a.tests = Array.isArray(a.tests) ? a.tests : [];
    a.events = Array.isArray(a.events) ? a.events : [];
    a.requests = Array.isArray(a.requests) ? a.requests : [];
    a.submissions = Array.isArray(a.submissions) ? a.submissions : [];
    a.nudges = Array.isArray(a.nudges) ? a.nudges : [];
    a.exports = Array.isArray(a.exports) ? a.exports : [];
    a.acks = Array.isArray(a.acks) ? a.acks : [];
    a.disputes = Array.isArray(a.disputes) ? a.disputes : [];
    a.conversations = a.conversations && typeof a.conversations === 'object' ? a.conversations : {};
    roles.forEach(r => { if (!Array.isArray(a.conversations[r.id])) a.conversations[r.id] = []; });
    if (!a.world || typeof a.world !== 'object') throw new Error('练习记录缺少场景条件');
    if (!a.config || typeof a.config !== 'object') throw new Error('练习记录缺少配置');
    const seeds = { '确认首批员工的使用需求': 'needs', '回应政策问答的开放请求': 'policy', '形成可执行的试点决定': 'decision' };
    a.tasks.forEach(t => { if (!t.seed && seeds[t.title]) t.seed = seeds[t.title]; });
    return a;
  }
  // Proactive colleague notes. Each note is attached to the work it concerns and
  // fires once per key. Triggers are explicit scenario rules, not language understanding.
  function taskByTitle(a, fragment) {
    const key = { '政策': 'policy', '需求': 'needs', '决定': 'decision' }[fragment];
    const task = a.tasks.find(t => key && t.seed === key) || a.tasks.find(t => !t.seed && t.title.includes(fragment));
    return task ? task.id : null;
  }
  function nudge(a, roleId, text, ref) {
    attempt(a); find(roles, roleId, '同事');
    if (!Array.isArray(a.nudges)) a.nudges = [];
    const key = str(ref.key, '意见标识', 160);
    if (a.nudges.some(n => n.key === key)) return null;
    const note = { id: uid('nudge'), roleId, kind: ['remind', 'object', 'correct', 'help'].includes(ref.kind) ? ref.kind : 'remind', text: str(text, '同事意见', 2000), key, taskId: ref.taskId || null, targetId: ref.targetId || null, createdAt: now(), read: false, status: 'open', mode: 'simulated' };
    a.nudges.push(note);
    a.conversations[roleId].push({ id: uid('message'), role: 'assistant', roleId, content: note.text, text: note.text, taskId: note.taskId, createdAt: note.createdAt, mode: 'simulated', proactive: true, kind: note.kind, nudgeId: note.id });
    log(a, 'colleague_nudged', find(roles, roleId).name + '主动提出了一条意见。', { nudgeId: note.id, roleId, key });
    return note;
  }
  function markNudgesRead(a, roleId) {
    attempt(a);
    (a.nudges || []).forEach(n => { if (!roleId || n.roleId === roleId) n.read = true; });
  }
  function respondNudge(a, id, action) {
    attempt(a);
    const note = find(a.nudges || [], id, '同事意见');
    note.read = true;
    note.status = choice(action, ['replied', 'later', 'dismissed'], '处理方式');
    log(a, 'nudge_' + note.status, '处理了' + find(roles, note.roleId).name + '的意见。', { nudgeId: id });
    return note;
  }
  function overCapacity(body, capacity) {
    return ((body || '').match(/(\d{2,5})\s*(?:人|名|位)(?!日|天|次|小时|周|月|时)/g) || []).map(x => parseInt(x, 10)).filter(n => n > capacity);
  }
  function checkCommitment(a, artifact) {
    if (intentOf(artifact.purpose) !== 'commit') return;
    const numbers = overCapacity(artifact.body, a.world.capacity);
    if (numbers.length) nudge(a, 'manager', '你在「' + artifact.title + '」里写了 ' + numbers[0] + ' 人，这次能给的容量是 ' + a.world.capacity + ' 人。写进承诺之前，先想想它靠什么成立。', { kind: 'object', key: 'overcommit-' + artifact.id, targetId: artifact.id, taskId: artifact.taskId });
    const talked = a.conversations.business.some(m => m.role === 'user');
    const read = a.events.some(e => e.type === 'material_read' && e.detail && e.detail.materialId === 'business');
    if (artifact.body.trim().length > 120 && !talked && !read) nudge(a, 'business', '我看到你在写试点决定了。首批员工最常问什么，你还没和我确认过——范围是按什么定的？', { kind: 'object', key: 'decision-without-needs', targetId: artifact.id, taskId: artifact.taskId });
  }
  // Each colleague prioritises from their own context; suggestions are never applied automatically.
  function suggestPriorities(a, roleId) {
    attempt(a); find(roles, roleId, '同事');
    const plan = {
      manager: { first: '决定', next: '需求', later: '政策', why: '我最关心你最后能承诺什么。先把决定的骨架写出来，缺什么再去补。' },
      business: { first: '需求', next: '政策', later: '决定', why: '先弄清首批员工真正要问什么，不然测再多也可能测错方向。' },
      technical: { first: '政策', next: '需求', later: '决定', why: '政策会变，索引会滞后，这是最可能出事的地方。先测政策问答，再谈范围。' }
    }[roleId];
    const keyOf = { '决定': 'decision', '需求': 'needs', '政策': 'policy' };
    const pick = fragment => a.tasks.find(t => t.seed === keyOf[fragment]) || a.tasks.find(t => !t.seed && t.title.includes(fragment));
    const items = [['first', plan.first], ['next', plan.next], ['later', plan.later]].map(([priority, fragment]) => { const t = pick(fragment); return t ? { taskId: t.id, title: t.title, priority } : null; }).filter(Boolean);
    const uncovered = a.tasks.filter(t => !items.some(i => i.taskId === t.id)).length;
    const why = items.length ? plan.why + (uncovered ? ' 你后来加的事，我没法替你排。' : '') : '我只能就最初交给你的那几件事给建议，现在的事项我说不准，你自己排。';
    log(a, 'priority_suggested', find(roles, roleId).name + '给出了自己的优先级建议；是否采用由你决定。', { roleId, items });
    return { roleId, why, items };
  }
  function applySuggestion(a, suggestion) {
    attempt(a); object(suggestion, '建议');
    if (!suggestion.items || !suggestion.items.length) throw new Error('这条建议没有覆盖任何事项');
    const before = a.tasks.map(t => ({ id: t.id, priority: t.priority }));
    suggestion.items.forEach(item => { const t = a.tasks.find(x => x.id === item.taskId); if (t) t.priority = choice(item.priority, PRIORITIES, '优先级'); });
    const order = { first: 0, next: 1, later: 2 };
    a.tasks.sort((x, y) => order[x.priority] - order[y.priority]);
    log(a, 'priority_adopted', '你采用了' + find(roles, suggestion.roleId).name + '的优先级建议。', { roleId: suggestion.roleId });
    return before;
  }
  function splitTask(a, id, title) {
    attempt(a);
    const parent = find(a.tasks, id, '事项');
    const child = addTask(a, { title, note: '从「' + parent.title + '」拆出。', priority: parent.priority });
    child.parentTaskId = parent.id;
    const at = a.tasks.indexOf(child); a.tasks.splice(at, 1); a.tasks.splice(a.tasks.indexOf(parent) + 1, 0, child);
    return child;
  }
  // Business description is matched against the one supported template; it never
  // invents a company or changes facts and evaluation sources.
  function matchBusiness(text) {
    const raw = typeof text === 'string' ? text.trim() : '';
    if (!raw) return { status: 'empty' };
    const find1 = re => { const m = raw.match(re); return m ? m[0] : null; };
    const topic = find1(/知识助手|知识库|问答|FAQ|政策查询|查政策|内部助手|knowledge (?:base|assistant)|Q&A/i);
    const internal = find1(/员工|同事|内部|行政|人事|\bHR\b|\bstaff\b|\binternal\b|\bemployees?\b/i);
    const external = find1(/外部客户|顾客|消费者|买家|\bcustomers?\b|\bshoppers?\b/i);
    const other = find1(/推荐|排序|广告|\brecommend/i);
    if (!topic && !/政策/.test(raw)) return { status: 'none', text: raw.slice(0, 2000) };
    const adopted = []; const notModeled = [];
    if (internal) adopted.push('使用者是内部员工（你写了“' + internal + '”）');
    const policy = find1(/差旅|报销|政策|\bpolicy\b/i); if (policy) adopted.push('要回答会变化的政策（你写了“' + policy + '”）');
    const pilot = find1(/试点|小范围|一部分人|先给|\bpilot\b|\btrial\b/i); if (pilot) adopted.push('先做小范围试点（你写了“' + pilot + '”）');
    const week = find1(/一周|下周|7 ?天|\bnext week\b/i); if (week) adopted.push('一周左右的上线期望（你写了“' + week + '”）');
    if (external) notModeled.push('面向外部客户（你写了“' + external + '”）：本情境只覆盖内部员工');
    if (other) notModeled.push('“' + other + '”类功能：本情境只覆盖知识问答');
    const scale = find1(/\d{2,}\s*(?:人|名|位)(?!日|天)/); if (scale) notModeled.push('你写的规模“' + scale + '”：本情境沿用 30 人容量');
    if (!adopted.length) adopted.push('一个知识助手的上线决定');
    const status = external || other ? 'partial' : 'matched';
    return { status, template: 'pilot', text: raw.slice(0, 2000), adopted, notModeled };
  }
  // Coaching samples: every observation is derived from recorded facts (versions,
  // counts, records, timing). They show the shape of contextual feedback — what was
  // seen, what could be known then, why it matters, what to try — without judging
  // reasoning quality, inferring ability, or producing a score.
  const SEED_TASKS = ['确认首批员工的使用需求', '回应政策问答的开放请求', '形成可执行的试点决定'];
  function coach(a, snapshot) {
    const src = snapshot || a;
    const out = [];
    const tests = src.tests || [];
    const events = src.events || [];
    const tasks = src.tasks || [];
    const works = snapshot ? snapshot.artifacts : currentArtifacts(a);
    const cap = src.world.capacity;
    const fmt = iso => { const d = new Date(iso); return isNaN(d) ? '' : String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };
    const policyAt = events.find(e => e.type === 'policy_updated');
    const nudgeAt = key => (src.nudges || []).find(n => n.key === key);
    const readV2 = policyAt && events.some(e => e.type === 'material_read' && e.detail && e.detail.materialId === 'policy' && e.detail.version >= 2);
    const taskOf = fragment => { const t = tasks.find(x => x.title.includes(fragment)); return t ? t.id : null; };
    const push = item => out.push(Object.assign({ provenance: 'rule', refs: [], actions: [], taskId: null, basis: '' }, item));
    const policyTests = tests.filter(t => t.citations.some(c => c.id === 'policy'));
    const stale = policyTests.filter(t => t.citations.some(c => c.version < t.policyVersion));
    const safe = src.config && (src.config.update === 'manual' || !src.config.domains.includes('policy') || (src.config.fallback === 'human' && src.world.indexVersion < src.world.policyVersion));
    const lastStale = stale[stale.length - 1];
    if (lastStale && safe) push({ tone: 'good', title: '发现旧答案后，你收住了风险', observed: '「' + lastStale.question + '」拿到了旧政策金额；之后政策问题不再由助手自动回答。', basis: '测试时政策源已是 v' + lastStale.policyVersion + '，助手索引还是 v' + lastStale.citations[0].version + '。', why: '员工不会按旧金额去订酒店。代价是政策问答暂时不能自动化，这个取舍值得写进决定。', actions: [{ label: '写进决定', act: 'open-decision' }], refs: [{ type: 'test', id: lastStale.id, label: '测试：' + lastStale.question }], taskId: lastStale.taskId || taskOf('政策') });
    else if (lastStale) {
      const n = nudgeAt('stale-index');
      push({ tone: 'check', title: '有回答用的是旧政策', observed: '「' + lastStale.question + '」的回答引用索引 v' + lastStale.citations[0].version + '，金额是旧的。', basis: '测试时政策源已是 v' + lastStale.policyVersion + (readV2 ? '，你也打开过 v2 政策' : '') + (n ? '；Daniel 在 ' + fmt(n.createdAt) + ' 提醒过索引滞后' : '') + '。', why: '如果试点照常开放政策问答，员工会拿到过期金额。记录里还看不到你怎么处理这一点。', actions: [{ label: '刷新索引后重测', act: 'rerun', id: lastStale.id }, { label: '改为政策转人工', act: 'config' }, { label: '问 Daniel', act: 'chat', role: 'technical' }], refs: [{ type: 'test', id: lastStale.id, label: '测试：' + lastStale.question }], taskId: lastStale.taskId || taskOf('政策') });
    }
    if (policyAt) {
      // Each run records the policy version in force, so ordering does not depend on clock resolution.
      const before = policyTests.filter(t => t.policyVersion < 2);
      const after = policyTests.filter(t => t.policyVersion >= 2);
      if (before.length && !after.length) push({ tone: 'check', title: '政策变了，还没有重新测', observed: '政策问答有 ' + before.length + ' 次测试，都在政策更新之前。', basis: '那些测试当时的结果没有问题；变化发生在 ' + fmt(policyAt.createdAt) + '，之后没有新的政策测试。', why: '旧测试只能说明旧条件下的表现，不能直接支持现在的决定。', actions: [{ label: '用同一个问题重测', act: 'rerun', id: before[before.length - 1].id }], refs: [{ type: 'event', id: policyAt.id, label: '政策更新' }], taskId: taskOf('政策') });
    }
    const decision = works.find(w => intentOf(w.purpose) === 'commit' && w.body.trim());
    const over = decision && overCapacity(decision.body, cap);
    if (over && over.length) push({ tone: 'check', title: '决定里的人数超出了容量', observed: '「' + decision.title + '」写到 ' + over[0] + ' 人，当前容量 ' + cap + ' 人。', basis: '容量在委托和系统说明里都能看到' + ((src.requests || []).some(r => r.status === 'approved') ? '；获批的申请只增加了开发资源，没有增加容量' : '') + '。', why: '承诺需要有条件支撑。可以缩小首批范围，或把扩容写成有条件的下一步。', actions: [{ label: '打开决定', act: 'open-artifact', id: decision.id }, { label: '问 Priya', act: 'chat', role: 'manager' }], refs: [{ type: 'artifact', id: decision.id, label: decision.title }], taskId: decision.taskId });
    works.filter(w => w.source !== 'user' && w.adopted).forEach(w => {
      const adoptedAt = w.adoptedAt || (events.find(e => e.type === 'artifact_adopted' && e.detail && e.detail.artifactId === w.id) || {}).createdAt || '';
      const linked = w.kind === 'investigation' ? investigationLinkedRunIds(src, w).length > 0 : (w.evidence || []).some(ev => ev.type === 'test' && tests.some(t => t.id === ev.id && t.createdAt >= adoptedAt));
      if (!linked) push({ tone: 'check', title: 'Agent 的作品还没关联测试', observed: '你采用了 Agent 回传的「' + w.title + '」，它没有关联任何实际运行。', basis: '采用说明你认可这份内容；回传正文里的结论没有对应的运行记录。', why: '采用不等于成立。挑一条关键测试真正跑一次，再作为依据。', actions: [{ label: '去测一条', act: 'lab' }], refs: [{ type: 'artifact', id: w.id, label: w.title }], taskId: w.taskId });
    });
    const talkedBusiness = ((src.conversations && src.conversations.business) || []).some(m => m.role === 'user');
    const readNeeds = events.some(e => e.type === 'material_read' && e.detail && e.detail.materialId === 'business');
    if (decision && !talkedBusiness && !readNeeds) push({ tone: 'unknown', title: '看不到需求方面的依据', observed: '「' + decision.title + '」选了范围，但记录里没有查看首批需求，也没有和 Mei 讨论。', basis: '需求材料一直可读；没有读不代表你不了解。', why: '证据里看不到范围是按什么定的。可以引用依据，或者和 Mei 确认一次。', actions: [{ label: '看首批需求', act: 'material', id: 'business' }, { label: '问 Mei', act: 'chat', role: 'business' }], refs: [{ type: 'artifact', id: decision.id, label: decision.title }], taskId: decision.taskId });
    if (!decision) push({ tone: 'unknown', title: '还没有成形的试点决定', observed: '没有用途为「试点决定」且有内容的作品。', basis: '其他作品的用途是探索、计划或比较，不会被当作承诺来核对。', why: '交一份不完整的判断也可以——写清还不知道什么，本身就是信息。', actions: [{ label: '写下现在的判断', act: 'new-decision' }], refs: [], taskId: taskOf('决定') });
    tasks.filter(t => !t.seed && !SEED_TASKS.includes(t.title) && !t.parentTaskId && t.origin !== 'situation').forEach(t => {
      const n = works.filter(w => w.taskId === t.id).length + tests.filter(r => r.taskId === t.id).length;
      if (n) push({ tone: 'good', kind: 'contribution', title: '计划外的贡献：' + t.title, observed: '这件事不在最初的三件里，是你自己加的，下面有 ' + n + ' 条作品或测试。', basis: '主动发现并处理没人交代的事，是这份工作的一部分。', why: '复盘时可以想一想：它改变了你后面的哪个判断？', actions: [], refs: [], taskId: t.id });
    });
    // Order and trade-off: describe what was touched first and what the world did meanwhile; no "right order".
    const touch = new Map();
    events.forEach((e, index) => { const d = e.detail || {}; let id = null;
      if (e.type === 'test_run') { const r = tests.find(x => x.id === d.testId); id = r && r.taskId; }
      if (e.type === 'artifact_created' || e.type === 'artifact_saved') { const w = (src.artifacts || []).concat(works).find(x => x.id === d.artifactId); id = w && w.taskId; }
      if (id && !touch.has(id)) touch.set(id, index); });
    // Map insertion follows the event log, so the order does not depend on clock resolution.
    const order = [...touch.keys()].map(id => tasks.find(t => t.id === id)).filter(Boolean);
    if (order.length) {
      const untouched = tasks.filter(t => !touch.has(t.id));
      const policyTask = tasks.find(t => t.seed === 'policy' || t.title.includes('政策'));
      const policyFirst = policyTask ? touch.get(policyTask.id) : undefined;
      const policyIndex = policyAt ? events.indexOf(policyAt) : -1;
      const basis = policyAt ? (policyFirst !== undefined && policyFirst < policyIndex ? '政策更新前，你已经在处理政策问答。' : '政策更新时，你还没开始处理政策问答。') : '这一轮没有发生政策变化。';
      push({ tone: 'unknown', kind: 'order', title: '你的先后顺序', observed: '最先动手的是「' + order[0].title + '」' + (order[1] ? '，接着是「' + order[1].title + '」' : '') + (untouched.length ? '；「' + untouched.map(t => t.title).join('」「') + '」没有动过' : '') + '。', basis, why: '顺序没有标准答案。值得想的是：先做的那件事让你更早知道了什么，又让你错过了什么。', actions: [], refs: [], taskId: null });
    }
    const approved = (src.requests || []).find(r => r.status === 'approved');
    if (approved && src.config && src.config.update === 'realtime') push({ tone: 'good', title: '资源到位后，你真的改了配置', observed: '经理批准资源后，你应用了实时同步。', basis: '批准只改变条件；配置是你主动做的变更。', why: '把“拿到资源”和“用上资源”分开，是很多人会漏的一步。', actions: [], refs: [{ type: 'request', id: approved.id, label: '资源申请' }], taskId: taskOf('政策') });
    return { items: out, label: '规则示意：根据已发生的记录生成，不是 LLM 评审，不打分。' };
  }
  function checkFocus(a) {
    attempt(a);
    if (a.tasks.filter(t => t.priority === 'first').length >= 3) return nudge(a, 'manager', '三件事都标成先做了，等于没有先做。要我帮你一起看看哪件最影响下周的承诺吗？', { kind: 'help', key: 'too-many-first' });
    return null;
  }
  // The commission is handed to the user, so it always travels with the package.
  // Other materials travel only after the user opened them. Options narrow the scope.
  function buildReturnGuide(requestId) {
    const request = requestId ? { requestId } : {};
    const textReturnFormat = { schemaVersion: 1, returnId: '为本次回传生成新的唯一标识', ...request, artifact: { kind: 'text', title: '作品标题', purpose: '自由作品', body: 'Markdown 正文' } };
    const testSetReturnFormat = { schemaVersion: 1, returnId: '为本次回传生成新的唯一标识', ...request, artifact: { kind: 'test_set', title: '待验证的测试计划', purpose: '测试计划', cases: [{ question: '根据当前事项提出一个实际问题', intent: '说明这个问题要验证什么', expectation: '可选：明确待验证的预期，不能假装已通过', refs: [] }] } };
    const investigationReturnFormat = { schemaVersion: 1, returnId: '为本次回传生成新的唯一标识', ...request, artifact: { kind: 'investigation', title: '整理一次有依据的调查', purpose: '探索笔记', question: '当前真正需要弄清的问题', blocks: [{ type: 'note', title: '调查思路', text: '说明尚未确认的解释或需要检查的条件' }, { type: 'test_compare', testIds: ['替换为本包tests中的实际ID'] }, { type: 'source_check', testId: '替换为本包tests中的实际ID', material: { id: '替换为该测试确实引用、且本包materials提供的ID', version: 1 } }, { type: 'retest', testId: '替换为本包tests中的实际ID', label: '用相同问题再检查' }] } };
    return {
      instructions: '仅用本任务包提供的资料和作品协助工作。根据问题选择 text、test_set 或 investigation；不必每次都生成表格，信息不足时说明缺口。test_set 是等待用户实际运行的测试计划；investigation 由你选择和排序 1–8 个 note、test_compare、source_check、retest 模块，可以省略或重复模块类型，不是固定页面模板。test_compare 仅引用本包 tests 的 1–4 个不同实际 ID。source_check 的资料 ID 必须属于该测试实际引用，目标 version 取本包 materials 的明确版本，可以不同于旧引用版本。retest 仅提出重测已有问题，不表示已经运行。示例中的占位 ID、版本必须替换，资料不足时省略相应模块。returnId 是本次回传独有标识，修改后使用新的 returnId，requestId 保持原任务包标识。不得回传答案正文、运行结果、通过状态、脚本、HTML 或 API 地址；实际内容由应用按有效 ID 读取。refs 仅引用本包 materials 的 id 和 version。问题/目的/预期是待验证计划；回传不会自动采用、运行、审批或改变场景。',
      supportedKinds: ['text', 'test_set', 'investigation'], limits: clone(TEST_SET_LIMITS), investigationLimits: clone(INVESTIGATION_LIMITS),
      returnFormat: testSetReturnFormat, textReturnFormat, investigationReturnFormat,
      returnFormats: { text: textReturnFormat, test_set: testSetReturnFormat, investigation: investigationReturnFormat },
      plainTextReturnFormat: { ...request, artifact: { title: '作品标题', purpose: '自由作品', body: 'Markdown 正文；也可以直接返回 Markdown' } }
    };
  }
  function captureInputSnapshot(a, scope) {
    const opts = scope || {};
    const snapshot = {
      artifacts: (opts.artifacts || []).map(work => {
        const content = work.draft ? { ...work, ...work.draft } : work;
        const item = { artifactId: work.id, revision: work.revision, title: content.title, purpose: content.purpose, body: content.kind === 'test_set' ? testSetSummary(content) : content.kind === 'investigation' ? investigationSummary(content) : content.body };
        if (content.kind) item.kind = content.kind;
        if (content.kind === 'test_set') item.cases = clone(content.cases);
        if (content.kind === 'investigation') { item.question = content.question; item.blocks = clone(content.blocks); }
        if (work.draft) item.draft = clone(work.draft);
        return item;
      }),
      materials: (opts.materials || []).map(m => ({ id: m.id, version: m.version })),
      tests: (opts.tests || []).map(t => ({ id: t.id, configVersion: t.configVersion, policyVersion: t.policyVersion, indexVersion: t.indexVersion, asOfSeq: t.asOfSeq })),
      configVersion: a.configVersion, config: clone(a.config), policyVersion: a.world.policyVersion, indexVersion: a.world.indexVersion
    };
    if (a.backend && a.backend.version !== undefined) snapshot.worldVersion = a.backend.version;
    return clone(snapshot);
  }
  function changedInputs(a, exp) {
    if (!exp) return [];
    const snapshot = exp.inputSnapshot;
    if (!snapshot) return (exp.inputVersions || []).filter(v => { const cur = a.artifacts.find(x => x.id === v.artifactId); return !cur || cur.removedAt || cur.revision > v.revision; });
    const changes = [];
    for (const item of snapshot.artifacts || []) {
      const cur = a.artifacts.find(x => x.id === item.artifactId && !x.removedAt);
      const current = cur ? captureInputSnapshot(a, { artifacts: [cur] }).artifacts[0] : null;
      if (JSON.stringify(current) !== JSON.stringify(item)) changes.push({ kind: 'artifact', artifactId: item.artifactId, revision: item.revision, currentRevision: cur ? cur.revision : null });
    }
    for (const ref of snapshot.materials || []) {
      const current = visibleMaterials(a).find(m => m.id === ref.id);
      if (!current || current.version !== ref.version) changes.push({ kind: 'material', id: ref.id, version: ref.version, currentVersion: current ? current.version : null });
    }
    if (snapshot.configVersion !== a.configVersion || JSON.stringify(snapshot.config) !== JSON.stringify(a.config)) changes.push({ kind: 'config', version: snapshot.configVersion, currentVersion: a.configVersion });
    for (const key of ['policyVersion', 'indexVersion']) if (snapshot[key] !== a.world[key]) changes.push({ kind: key, version: snapshot[key], currentVersion: a.world[key] });
    return changes;
  }
  function preparePackage(a, taskId, scope) {
    attempt(a);
    const opts = scope && typeof scope === 'object' ? scope : {};
    const task = taskId == null ? null : find(a.tasks, taskId, '事项');
    const readIds = new Set(['brief', ...a.events.filter(event => event.type === 'material_read').map(event => event.detail.materialId)]);
    let materials = getMaterials(a).filter(material => readIds.has(material.id));
    if (Array.isArray(opts.materialIds)) materials = materials.filter(m => opts.materialIds.includes(m.id));
    let relevant = currentArtifacts(a).filter(item => !task || item.taskId === task.id);
    if (Array.isArray(opts.artifactIds)) relevant = relevant.filter(x => opts.artifactIds.includes(x.id));
    let tests = a.tests;
    if (Array.isArray(opts.testIds)) tests = tests.filter(t => opts.testIds.includes(t.id));
    const requestId = opts.requestId || uid('request');
    const inputVersions = relevant.map(x => ({ artifactId: x.id, revision: x.revision }));
    const inputSnapshot = captureInputSnapshot(a, { artifacts: relevant, materials, tests });
    const pkg = clone({ schema: 'practice-task-package/v1', requestId, exportedAt: now(), mode: 'local-prototype', scenario: { id: a.scenarioId, title: a.title }, task: task || null, materials, artifacts: relevant, tests, inputVersions, inputSnapshot, ...buildReturnGuide(requestId) });
    if (opts.record) {
      if (!Array.isArray(a.exports)) a.exports = [];
      a.exports.push({ requestId, taskId: task ? task.id : null, inputVersions, inputSnapshot: clone(inputSnapshot), createdAt: pkg.exportedAt });
      log(a, 'package_exported', '导出了任务包，等待你的 Agent 回传。', { requestId, taskId: task ? task.id : null });
    }
    return pkg;
  }
  // New return IDs identify immutable inbound payloads. A changed return is a new
  // pending candidate, never an implicit overwrite of an adopted work.
  function importReturn(a, text, taskId) {
    attempt(a);
    const data = validateImported(text);
    const exp = data.requestId ? (a.exports || []).find(x => x.requestId === data.requestId) : null;
    if (taskId != null) find(a.tasks, taskId, '关联事项');
    if (data.requestId && !exp && data.returnId) throw new Error('找不到对应任务包；请核对 requestId，或移除该字段作为未关联回传导入');
    if (exp && exp.taskId && taskId && exp.taskId !== taskId) throw new Error('回传所属事项与任务包不一致，请在原事项导入');
    const payload = JSON.stringify(data);
    const existing = data.returnId ? a.artifacts.find(x => x.returnId === data.returnId) : data.requestId ? a.artifacts.find(x => !x.returnId && x.requestId === data.requestId) : null;
    if (existing) {
      if (data.returnId && existing.returnPayload !== payload) throw new Error('同一 returnId 对应不同内容，请使用新的回传标识');
      if (taskId && existing.taskId !== taskId) throw new Error('重复回传已属于其他事项');
      return { duplicate: true, removed: !!existing.removedAt, artifact: existing, staleInputs: existing.staleInputs || [] };
    }
    if (data.kind === 'test_set') assertTestRefs(a, data.cases, exp && exp.inputSnapshot ? exp.inputSnapshot.materials : undefined);
    if (data.kind === 'investigation') {
      if (exp && !exp.inputSnapshot) throw new Error('任务包未记录调查证据范围，请重新导出任务包');
      assertInvestigationRefs(a, data.blocks, exp ? exp.inputSnapshot : undefined);
    }
    const staleInputs = changedInputs(a, exp);
    const artifact = createArtifact(a, { taskId: taskId || (exp && exp.taskId) || null, title: data.title, purpose: data.purpose, body: data.body, kind: data.kind, cases: data.cases, question: data.question, blocks: data.blocks, source: 'external-agent', adopted: false }, { referenceScope: exp && exp.inputSnapshot ? exp.inputSnapshot.materials : undefined, investigationScope: exp ? exp.inputSnapshot : undefined });
    if (data.requestId) artifact.requestId = data.requestId;
    if (data.returnId) { artifact.returnId = data.returnId; artifact.returnPayload = payload; }
    if (exp && exp.inputSnapshot) artifact.inputSnapshot = clone(exp.inputSnapshot);
    artifact.packageLinked = !!exp;
    const earlier = data.returnId && data.requestId ? a.artifacts.filter(x => x.id !== artifact.id && x.requestId === data.requestId).at(-1) : null;
    if (earlier) artifact.previousReturnId = earlier.returnId || earlier.id;
    artifact.staleInputs = staleInputs;
    return { duplicate: false, artifact, staleInputs };
  }
  function investigationLinkedRunIds(a, artifact) {
    const current = currentArtifacts(a).find(work => work.id === artifact.id && work.kind === 'investigation');
    if (!current) return [];
    // Only saved, adopted structure counts. A draft or a removed/replaced block
    // cannot make a previous run evidence for the current investigation.
    const tests = a.tests || [];
    const ids = new Set(investigationReferences({ blocks: current.blocks }).testIds.filter(id => tests.some(test => test.id === id)));
    for (const test of tests) {
      if (test.investigationId !== current.id) continue;
      const block = (current.blocks || []).find(item => item.type === 'retest' && item.id === test.blockId && item.revision === test.blockRevision && item.testId === test.baselineRunId);
      if (block && tests.some(baseline => baseline.id === block.testId)) ids.add(test.id);
    }
    return [...ids];
  }
  function agentProgress(a, artifact) {
    attempt(a);
    if (!artifact || artifact.source === 'user') return null;
    const adoptedAt = artifact.adoptedAt || (a.events.find(e => e.type === 'artifact_adopted' && e.detail && e.detail.artifactId === artifact.id) || {}).createdAt;
    const linkedRuns = artifact.kind === 'investigation' ? investigationLinkedRunIds(a, artifact).length : adoptedAt ? artifact.evidence.filter(ev => ev.type === 'test' && a.tests.some(t => t.id === ev.id && t.createdAt >= adoptedAt)).length : 0;
    const exported = (a.exports || []).some(x => artifact.requestId ? x.requestId === artifact.requestId : (x.taskId === artifact.taskId && x.createdAt <= artifact.createdAt));
    return { exported, returned: true, adopted: !!artifact.adopted, linked: linkedRuns > 0, linkedRuns, verified: artifact.kind === 'investigation' ? false : linkedRuns > 0 };
  }
  // Ordering is a user act: it is logged, carries the new priority, and can be undone.
  function moveTask(a, id, to) {
    attempt(a); object(to, '移动');
    const before = a.tasks.map(t => ({ id: t.id, priority: t.priority }));
    const from = a.tasks.findIndex(t => t.id === id);
    if (from < 0) throw new Error('事项不存在');
    const [task] = a.tasks.splice(from, 1);
    if (own(to, 'priority')) task.priority = choice(to.priority, PRIORITIES, '优先级');
    let index = own(to, 'beforeId') && to.beforeId ? a.tasks.findIndex(t => t.id === to.beforeId) : -1;
    if (index < 0) {
      // Append to the end of its priority group.
      const order = { first: 0, next: 1, later: 2 };
      index = a.tasks.findIndex(t => order[t.priority] > order[task.priority]);
      if (index < 0) index = a.tasks.length;
    }
    a.tasks.splice(index, 0, task);
    log(a, 'task_moved', '调整了「' + task.title + '」的位置' + (own(to, 'priority') ? '，优先级为' + { first: '先做', next: '随后', later: '暂放' }[task.priority] : '') + '。', { taskId: id, priority: task.priority });
    checkFocus(a);
    return before;
  }
  function restoreOrder(a, before) {
    attempt(a);
    const map = new Map(a.tasks.map(t => [t.id, t]));
    const restored = before.map(x => { const t = map.get(x.id); if (t) t.priority = x.priority; return t; }).filter(Boolean);
    const extra = a.tasks.filter(t => !before.some(x => x.id === t.id));
    a.tasks.splice(0, a.tasks.length, ...restored, ...extra);
    log(a, 'task_moved', '撤销了上一次调整。');
  }
  // Scenario rule mirrored from the backend: the third business action changes the world.
  function maybeTriggerEvents(a) {
    attempt(a);
    if (a.world.policyVersion >= 2) return false;
    const counted = a.events.filter(e => ['test_run', 'config_applied', 'config_draft', 'resource_requested', 'artifact_adopted'].includes(e.type)).length;
    const revising = a.events.some(e => e.type === 'revision_started');
    if (counted < 3 && !revising) return false;
    return triggerPolicyUpdate(a, 'scenario');
  }
  function validateImported(text) {
    const raw = str(text, '回传内容', 100000);
    let parsed;
    const fenced = raw.match(/^```(?:json)?\s*\n([\s\S]*?)\n```$/i);
    const candidate = fenced ? fenced[1].trim() : raw;
    if (/^[\[{]/.test(candidate)) {
      try { parsed = JSON.parse(candidate); } catch (_) { throw new Error('JSON 格式无法解析，请检查格式或直接粘贴 Markdown'); }
      parsed = safeJSON(parsed);
      object(parsed, '回传内容');
      const artifact = own(parsed, 'artifact') ? parsed.artifact : parsed;
      object(artifact, '回传作品');
      if (own(artifact, 'kind') || own(parsed, 'schemaVersion') || own(parsed, 'returnId')) {
        allowedKeys(parsed, ['schemaVersion', 'returnId', 'requestId', 'artifact'], '回传信封');
        if (parsed.schemaVersion !== 1) throw new Error('不支持的回传格式版本');
        const returnId = str(parsed.returnId, '回传标识 returnId', 160);
        if (artifact.kind === 'text') {
          allowedKeys(artifact, ['kind', 'title', 'purpose', 'body'], '文字作品');
          const result = { schemaVersion: 1, returnId, kind: 'text', title: plainTestText(artifact.title, '作品标题', 160), purpose: choice(artifact.purpose || '自由作品', PURPOSES, '作品用途'), body: plainTestText(artifact.body, '作品正文', 50000), source: 'external-agent' };
          if (parsed.requestId !== undefined) result.requestId = str(parsed.requestId, '任务包 requestId', 160);
          return result;
        }
        if (artifact.kind === 'investigation') {
          allowedKeys(artifact, ['kind', 'title', 'purpose', 'question', 'blocks'], '调查作品');
          if (artifact.purpose !== undefined && artifact.purpose !== '探索笔记') throw new Error('调查作品用途必须是探索笔记');
          const result = { schemaVersion: 1, returnId, kind: 'investigation', title: plainTestText(artifact.title, '作品标题', 160), purpose: '探索笔记', question: plainTestText(artifact.question, '调查问题', INVESTIGATION_LIMITS.question), blocks: investigationBlocks(artifact.blocks), source: 'external-agent' };
          result.body = investigationSummary(result);
          if (parsed.requestId !== undefined) result.requestId = str(parsed.requestId, '任务包 requestId', 160);
          return result;
        }
        allowedKeys(artifact, ['kind', 'title', 'purpose', 'body', 'cases'], '测试作品');
        if (artifact.kind !== 'test_set') throw new Error('不支持的作品类型');
        if (artifact.purpose !== undefined && artifact.purpose !== '测试计划') throw new Error('测试作品用途必须是测试计划');
        if (!Array.isArray(artifact.cases) || !artifact.cases.length || artifact.cases.length > TEST_SET_LIMITS.cases) throw new Error('导入的测试作品需要 1–20 行');
        const agentSummary = artifact.body === undefined ? undefined : plainTestText(artifact.body, '作品摘要', 50000, true);
        const cases = artifact.cases.map(row => { allowedKeys(row, ['question', 'intent', 'expectation', 'refs'], '测试行'); return testCaseContent(row, false); });
        const result = { schemaVersion: 1, returnId, kind: 'test_set', title: plainTestText(artifact.title, '作品标题', 160), purpose: '测试计划', cases, body: testSetSummary({ cases }), source: 'external-agent' };
        if (agentSummary !== undefined) result.agentSummary = agentSummary;
        if (parsed.requestId !== undefined) result.requestId = str(parsed.requestId, '任务包 requestId', 160);
        return result;
      }
      if (['cases', 'blocks', 'results', 'result', 'testRunId', 'passed', 'script', 'html', 'api', 'url'].some(key => own(artifact, key) || own(parsed, key))) throw new Error('结构化作品需要支持的版本化格式，不能带入执行结果');
      if (own(parsed, 'artifact')) {
        allowedKeys(parsed, ['requestId', 'artifact'], '普通回传信封');
        allowedKeys(artifact, ['title', 'purpose', 'body'], '普通回传作品');
      } else allowedKeys(parsed, ['title', 'purpose', 'body', 'requestId'], '普通回传作品');
      const result = { title: str(artifact.title, '作品标题', 160), purpose: choice(artifact.purpose || '自由作品', PURPOSES, '作品用途'), body: str(artifact.body, '作品正文', 50000), source: 'external-agent' };
      if (typeof parsed.requestId === 'string' && parsed.requestId.trim()) result.requestId = parsed.requestId.trim().slice(0, 160);
      return result;
    }
    if (raw.length > 50000) throw new Error('作品正文超过 50000 字符');
    const heading = raw.match(/^#{1,6}\s+(.+)$/m);
    return { title: heading ? heading[1].trim().slice(0, 160) : '外部 Agent 回传作品', purpose: '自由作品', body: raw, source: 'external-agent' };
  }

  const api = { VERSION, TEST_SET_LIMITS, INVESTIGATION_LIMITS, scenarios: deepFreeze(scenarios), roles: deepFreeze(roles), careers: deepFreeze(careers), PURPOSES: Object.freeze(PURPOSES), intentOf, matchBusiness, nudge, markNudgesRead, respondNudge, suggestPriorities, applySuggestion, splitTask, coach, checkFocus, checkCommitment, importReturn, laterEdits, normalizeAttempt, agentProgress, moveTask, restoreOrder, maybeTriggerEvents, newState, createAttempt, getAttempt, addTask, updateTask, createArtifact, saveArtifact, removeArtifact, restoreArtifact, updateTestCase, addTestCase, removeTestCase, restoreTestCase, testSetSummary, investigationSummary, investigationReferences, moveInvestigationBlock, adoptArtifact, currentArtifacts, addEvidence, readMaterial, getMaterials, runTest, updateConfig, refreshIndex, triggerPolicyUpdate, requestResources, resolveResources, reply, review, submit, revise, log, preparePackage, buildReturnGuide, captureInputSnapshot, validateImported };
  root.PracticeEngine = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
