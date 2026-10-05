'use strict';
// Run: npm run test:workbench
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { runInThisContext } = require('node:vm');
// Execute the browser's IIFE in this realm so strict assertions keep working.
// The explicit module object exposes its existing CommonJS test entry point.
const engineModule = { exports: {} };
const source = readFileSync(resolve(__dirname, '../public/workbench-engine.js'), 'utf8');
runInThisContext('(function(module) {\n' + source + '\n})')(engineModule);
const E = engineModule.exports;
let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log('PASS ' + name); }
  catch (error) { console.error('FAIL ' + name); throw error; }
}
function start(id = 'pilot') { const s = E.newState(); const a = E.createAttempt(s, id); return { s, a }; }
function work(a, extra = {}) { return E.createArtifact(a, { taskId: a.tasks[0].id, title: '目前的判断', purpose: '探索笔记', body: '我尚不知道是否值得上线，先留下问题。', ...extra }); }

test('任务自由创建和改优先级，不改其他任务或制造必经关卡', () => {
  const { a } = start();
  const priorities = a.tasks.map(t => t.priority);
  assert.deepEqual(priorities, ['next', 'next', 'next']);
  assert.deepEqual(a.tasks.map(t => t.title), ['确认首批员工的使用需求', '回应政策问答的开放请求', '形成可执行的试点决定']);
  const task = E.addTask(a, { title: '质疑试点必要性', note: '先确认是不是值得做', priority: 'later' });
  E.updateTask(a, task.id, { priority: 'first', status: 'working' });
  assert.equal(task.priority, 'first');
  assert.equal(task.status, 'working');
  assert.deepEqual(a.tasks.slice(0, 3).map(t => t.priority), priorities);
  assert.equal(a.tests.length, 0);
  assert.throws(() => E.updateTask(a, task.id, { priority: 'urgent' }), /优先级/);
});

test('允许自由作品和未知判断；保存才产生版本，原版本留在事件记录', () => {
  const { a } = start();
  const artifact = work(a, { purpose: '自由作品', body: '也许不需要上线。' });
  assert.equal(artifact.revision, 1);
  E.saveArtifact(a, artifact.id, { body: artifact.body });
  assert.equal(artifact.revision, 1);
  E.saveArtifact(a, artifact.id, { body: '我想先和用户讨论，再决定。' });
  assert.equal(artifact.revision, 2);
  const saved = a.events.find(e => e.type === 'artifact_saved');
  assert.equal(saved.detail.previous.body, '也许不需要上线。');
  assert.throws(() => work(a, { purpose: '固定能力过关' }), /用途/);
});

test('实时配置先保留草案；申请、获批、应用互不冒充', () => {
  const { a } = start();
  const result = E.updateConfig(a, { update: 'realtime' });
  assert.equal(result.applied, false);
  assert.equal(a.config.update, 'daily');
  assert.equal(a.configDraft.update, 'realtime');
  assert.equal(a.configVersion, 1);
  const request = E.requestResources(a, '实时同步需要 5 人日，请增加投入并延后试点。');
  assert.equal(a.world.devDays, 3);
  assert.equal(request.status, 'pending');
  E.resolveResources(a, request.id);
  assert.equal(a.world.devDays, 6);
  assert.equal(a.world.deadline, 10);
  assert.equal(a.config.update, 'daily');
  assert.equal(E.updateConfig(a, { update: 'realtime' }).applied, true);
  assert.equal(a.config.update, 'realtime');
  assert.equal(a.configDraft, null);
  const eventCount = a.events.length;
  E.resolveResources(a, request.id);
  assert.equal(a.events.length, eventCount);
  assert.equal(a.world.devDays, 6);
  assert.throws(() => E.requestResources(a, ' '), /申请理由/);
});

test('容量不足时保留实际配置；手动更新模式合法', () => {
  const { a } = start('capacity');
  assert.equal(a.world.capacity, 15);
  assert.equal(E.updateConfig(a, { participants: 40 }).applied, false);
  assert.equal(a.config.participants, 15);
  assert.equal(E.updateConfig(a, { participants: 12, update: 'manual' }).applied, true);
  assert.equal(a.config.participants, 12);
  assert.equal(a.config.update, 'manual');
  assert.throws(() => E.updateConfig(a, { participants: 0 }), /人数/);
  assert.throws(() => E.updateConfig(a, { domains: ['secret'] }), /知识范围/);
});

test('源文件更新与索引分离；日期提醒不能修好旧答案', () => {
  const { a } = start();
  const first = E.runTest(a, { question: '住宿报销的上限是多少？' });
  assert.match(first.answer, /500/);
  assert.equal(first.expectation, '');
  E.triggerPolicyUpdate(a);
  assert.equal(a.world.policyVersion, 2);
  assert.equal(a.world.indexVersion, 1);
  E.updateConfig(a, { fallback: 'date' });
  const stale = E.runTest(a, { question: '住宿报销的上限是多少？', expectation: '查到最新标准' });
  assert.match(stale.answer, /500/);
  assert.equal(stale.citations[0].version, 1);
  assert.equal(stale.policyVersion, 2);
  assert(E.review(a).observations.some(o => o.title === '该次回答引用了较旧政策' && o.status === 'check'));
  assert.equal(E.refreshIndex(a), true);
  const fresh = E.runTest(a, { question: '住宿报销的上限是多少？' });
  assert.match(fresh.answer, /400/);
  assert.equal(fresh.citations[0].version, 2);
  assert.equal(first.citations[0].version, 1);
  assert.equal(E.refreshIndex(a), false);
  assert.equal(E.triggerPolicyUpdate(a), false);
});

test('范围与人工兜底实际改变规则模拟回答；不会编造新来源', () => {
  const { a } = start();
  E.triggerPolicyUpdate(a);
  E.updateConfig(a, { fallback: 'human' });
  const handoff = E.runTest(a, { question: '差旅住宿上限？' });
  assert.match(handoff.answer, /转交/);
  assert.equal(handoff.citations.length, 0);
  E.updateConfig(a, { domains: ['faq'], fallback: 'none' });
  const excluded = E.runTest(a, { question: '差旅住宿上限？' });
  assert.match(excluded.answer, /未纳入/);
  assert.equal(excluded.citations.length, 0);
  const faq = E.runTest(a, { question: '会议室怎么预约？' });
  assert.equal(faq.citations[0].id, 'faq');
  const unknown = E.runTest(a, { question: '蓝色天空为什么不是绿色？' });
  assert.equal(unknown.citations.length, 0);
  assert.match(unknown.answer, /没有足够/);
});

test('获批并应用实时同步后，明确场景更新会更新索引', () => {
  const { a } = start();
  E.resolveResources(a, E.requestResources(a, '申请实时同步资源').id);
  E.updateConfig(a, { update: 'realtime' });
  E.triggerPolicyUpdate(a);
  assert.equal(a.world.indexVersion, 2);
  assert.match(E.runTest(a, { question: '差旅住宿标准？' }).answer, /400/);
});

test('三位同事记录各自多轮历史、展示已知约束且不自动改变优先级', () => {
  const { a } = start();
  const priorities = a.tasks.map(t => t.priority);
  const manager = E.reply(a, 'manager', '容量和开发资源是多少？', a.tasks[0].id);
  assert.equal(manager.role, 'assistant');
  assert.match(manager.text, /30 人/);
  assert.match(manager.text, /3 人日/);
  E.reply(a, 'manager', '我该先做什么？', a.tasks[0].id);
  const business = E.reply(a, 'business', '开发资源有多少？');
  assert.match(business.text, /经理或技术负责人/);
  assert.equal(a.conversations.manager.length, 4);
  assert.equal(a.conversations.business.length, 2);
  assert.equal(a.conversations.technical.length, 0);
  assert.deepEqual(a.tasks.map(t => t.priority), priorities);
  assert.equal(a.conversations.manager[0].taskId, a.tasks[0].id);
  assert.throws(() => E.reply(a, 'secret', '问题'), /同事/);
});

test('评审只核对可核实规则，语义始终待核；无评分、无能力通过判断', () => {
  const { a } = start();
  const artifact = work(a, { body: '已经全部成功！满分上线。' });
  const result = E.review(a, artifact.id);
  assert.equal(result.score, undefined);
  assert.equal(result.passed, undefined);
  assert(result.observations.some(o => o.status === 'pending' && /情境化/.test(o.title)));
  assert(result.observations.some(o => o.status === 'pending' && /测试/.test(o.title)));
  E.runTest(a, { question: '会议室怎么预约？' });
  E.updateConfig(a, { participants: 15 });
  assert(E.review(a).observations.some(o => o.title === '最近测试与当前条件不同'));
  assert(result.observations.every(o => Array.isArray(o.evidenceIds)));
});

test('任务包只含可用公开内容；Markdown与JSON回传需要单独采用', () => {
  const { a } = start();
  E.readMaterial(a, 'business');
  const pkg = E.preparePackage(a, a.tasks[0].id);
  assert.deepEqual(pkg.materials.map(m => m.id), ['brief', 'business']);
  assert.equal(pkg.world, undefined);
  assert.equal(pkg.conversations, undefined);
  assert.equal(pkg.gold, undefined);
  pkg.task.title = '试图修改原任务';
  assert.notEqual(a.tasks[0].title, pkg.task.title);
  const imported = E.validateImported('# 首批需求的假设\n\n我需要进一步确认。');
  assert.equal(imported.title, '首批需求的假设');
  const artifact = E.createArtifact(a, { ...imported, taskId: a.tasks[0].id, adopted: false });
  assert.equal(artifact.adopted, false);
  assert.equal(a.tests.length, 0);
  E.adoptArtifact(a, artifact.id);
  assert.equal(artifact.adopted, true);
  assert.equal(a.tests.length, 0);
  const json = E.validateImported(JSON.stringify({ artifact: { title: '测试建议', purpose: '测试计划', body: '先验证使用场景。' } }));
  assert.equal(json.purpose, '测试计划');
  assert.equal(json.source, 'external-agent');
});

test('回传输入边界防原型污染、无限嵌套及超长内容', () => {
  assert.throws(() => E.validateImported('{"__proto__":{"polluted":true},"title":"a","body":"b"}'), /不支持/);
  assert.throws(() => E.validateImported('{"artifact":{"title":"a","body":"b","constructor":{"polluted":true}}}'), /不支持/);
  assert.equal({}.polluted, undefined);
  assert.throws(() => E.validateImported('x'.repeat(100001)), /长度限制/);
  assert.throws(() => E.validateImported('{broken'), /JSON/);
  assert.throws(() => E.validateImported('[]'), /对象/);
  assert.throws(() => E.validateImported('{"title":"空正文","body":""}'), /正文/);
  const nested = { title: 'a', body: 'b' }; let n = nested;
  for (let i = 0; i < 25; i++) { n.child = {}; n = n.child; }
  assert.throws(() => E.validateImported(JSON.stringify(nested)), /层级/);
});

test('证据必须来自本轮实际材料或记录，证据对象不能改写运行结果', () => {
  const { a } = start();
  const artifact = work(a);
  const run = E.runTest(a, { question: '会议室怎么预约？' });
  E.addEvidence(a, artifact.id, { id: run.id, title: '会议室测试', version: 1 });
  E.addEvidence(a, artifact.id, { id: run.id, title: '会议室测试', version: 1 });
  assert.equal(artifact.evidence.length, 1);
  assert.throws(() => E.addEvidence(a, artifact.id, { id: 'invented-pass', title: '伪造通过记录' }), /不属于/);
  assert.throws(() => E.addEvidence(a, artifact.id, JSON.parse('{"id":"policy","__proto__":{}}')), /不支持/);
});

test('提交快照深冻结并隔离引用；修改与关联修订保留原交付', () => {
  const { a } = start();
  const artifact = work(a);
  const run = E.runTest(a, { question: '住宿上限？' });
  E.addEvidence(a, artifact.id, { id: run.id, title: '政策测试' });
  const snapshot = E.submit(a);
  assert.equal(snapshot.review.observations.at(-1).status, 'pending');
  assert.equal(Object.isFrozen(snapshot.artifacts[0]), true);
  assert.throws(() => { snapshot.artifacts[0].body = '篡改快照'; }, TypeError);
  E.saveArtifact(a, artifact.id, { body: '提交后仍能修改工作区' });
  assert.notEqual(snapshot.artifacts[0].body, artifact.body);
  E.triggerPolicyUpdate(a);
  assert.equal(snapshot.world.policyVersion, 1);
  const revised = E.revise(a, snapshot.id);
  assert.equal(a.parentSubmissionId, snapshot.id);
  assert.notEqual(revised[0].id, artifact.id);
  assert.equal(revised[0].parentArtifactId, artifact.id);
  assert.equal(revised[0].body, snapshot.artifacts[0].body);
  assert.equal(a.world.policyVersion, 2);
  E.saveArtifact(a, revised[0].id, { body: '下一版本补充了新的判断' });
  const next = E.submit(a);
  assert.equal(next.parentSubmissionId, snapshot.id);
  assert.equal(snapshot.artifacts[0].revision, 1);
  assert.equal(a.submissions.length, 2);
});

test('空白或仅回传未采用作品可以记录尝试，评审证据不足；多个练习完全隔离', () => {
  const { s, a } = start();
  const empty = E.submit(a);
  assert.equal(empty.artifacts.length, 0);
  assert(empty.review.observations.some(o => o.title === '尚无可评价的已采用作品' && o.status === 'pending'));
  work(a, { source: 'external-agent', adopted: false });
  const unadopted = E.submit(a);
  assert.equal(unadopted.artifacts.length, 0);
  assert(unadopted.review.observations.some(o => o.title === '尚无可评价的已采用作品' && o.status === 'pending'));
  assert.equal(unadopted.review.score, undefined);
  const b = E.createAttempt(s, 'urgent');
  E.triggerPolicyUpdate(b);
  E.updateTask(b, b.tasks[0].id, { title: '我自己的路径' });
  assert.equal(a.world.policyVersion, 1);
  assert.equal(a.world.deadline, 7);
  assert.equal(b.world.deadline, 3);
  assert.equal(a.artifacts.length, 1);
  assert.equal(b.artifacts.length, 0);
  assert.notEqual(a.tasks[0].title, b.tasks[0].title);
  assert.equal(E.getAttempt(s), b);
  s.activeId = a.id;
  assert.equal(E.getAttempt(s), a);
  assert.throws(() => E.createAttempt(s, 'nonexistent'), /案例/);
});

test('政策转人工独立于兜底开关，仍允许正常办公问答', () => {
  const { a } = start();
  assert.equal(E.updateConfig(a, { update: 'manual', fallback: 'none' }).applied, true);
  const policy = E.runTest(a, { question: '住宿报销上限？' });
  assert.match(policy.answer, /转交业务负责人/);
  assert.doesNotMatch(policy.answer, /SGD 500/);
  assert.equal(policy.citations.length, 0);
  const faq = E.runTest(a, { question: '会议室怎么预约？' });
  assert.equal(faq.citations[0].id, 'faq');
});

test('工作项成本按 1/1/5 合计；实时方式不能通过漏勾工作项绕过资源门槛', () => {
  const { a } = start();
  assert.equal(E.updateConfig(a, { workItems: ['scope', 'fallback'] }).applied, true);
  assert.equal(E.updateConfig(a, { update: 'realtime', workItems: [] }).applied, false);
  assert.equal(a.config.update, 'daily');
  assert.equal(E.updateConfig(a, { update: 'daily', workItems: ['realtime'] }).applied, false);
  E.resolveResources(a, E.requestResources(a, '增加实时同步资源').id);
  assert.equal(E.updateConfig(a, { update: 'realtime', workItems: ['scope', 'fallback', 'realtime'] }).applied, false);
  assert.match(a.events.at(-1).text, /7 人日/);
  assert.equal(E.updateConfig(a, { update: 'realtime', workItems: ['scope', 'realtime', 'realtime'] }).applied, true);
  assert.deepEqual(a.config.workItems, ['scope', 'realtime']);
  assert(E.review(a).observations.some(o => o.title === '工作项与资源' && o.status === 'confirmed' && /6 人日/.test(o.text)));
  assert.throws(() => E.updateConfig(a, { workItems: ['free-unlimited'] }), /工作项/);
});

test('范围为空或人数超过容量仍保存草案；尝试快照保存草案且隔离引用', () => {
  const { a } = start('capacity');
  assert.equal(a.config.participants, 15);
  assert.equal(E.updateConfig(a, { participants: 30, domains: [] }).applied, false);
  assert.equal(a.config.participants, 15);
  assert.deepEqual(a.config.domains, ['faq', 'policy']);
  assert.equal(a.configDraft.participants, 30);
  assert.deepEqual(a.configDraft.domains, []);
  const snapshot = E.submit(a);
  assert.equal(snapshot.configDraft.participants, 30);
  assert.deepEqual(snapshot.configDraft.domains, []);
  assert(snapshot.review.observations.some(o => o.title === '存在尚未应用的配置草案' && o.status === 'check'));
  assert(snapshot.review.observations.some(o => o.title === '尚无可评价的已采用作品' && o.status === 'pending'));
  E.updateConfig(a, { participants: 10, domains: ['faq'] });
  assert.equal(a.configDraft, null);
  assert.equal(snapshot.configDraft.participants, 30);
  assert.equal(Object.isFrozen(snapshot.configDraft), true);
});

test('JSON 存档恢复后，交付快照重新冻结；材料随条件变更更新版本', () => {
  const { s, a } = start();
  work(a);
  E.submit(a);
  const restored = JSON.parse(JSON.stringify(s));
  const current = E.getAttempt(restored);
  E.addTask(current, { title: '恢复后继续', priority: 'next' });
  assert.equal(Object.isFrozen(current.submissions[0].artifacts[0]), true);
  const initialTechnical = E.getMaterials(current).find(m => m.id === 'technical');
  E.triggerPolicyUpdate(current);
  const changedTechnical = E.getMaterials(current).find(m => m.id === 'technical');
  assert(changedTechnical.version > initialTechnical.version);
  E.resolveResources(current, E.requestResources(current, '增加开发量').id);
  const brief = E.getMaterials(current).find(m => m.id === 'brief');
  assert.equal(brief.version, 2);
  assert.match(brief.body, /10 个业务日/);
});

test('两份作品关联修订后，提交与任务包只包含两份当前版本', () => {
  const { a } = start();
  const first = work(a, { title: '需求判断', body: '原需求判断' });
  const second = work(a, { title: '试点决定', purpose: '试点决定', body: '原试点决定' });
  const initial = E.submit(a);
  const revised = E.revise(a, initial.id);
  E.saveArtifact(a, revised[0].id, { body: '更新后的需求判断' });
  E.saveArtifact(a, revised[1].id, { body: '更新后的试点决定' });
  assert.equal(a.artifacts.length, 4);
  assert.equal(E.currentArtifacts(a).length, 2);
  assert.deepEqual(E.currentArtifacts(a).map(item => item.id), revised.map(item => item.id));
  const current = E.submit(a);
  assert.equal(current.artifacts.length, 2);
  assert.deepEqual(current.artifacts.map(item => item.body), ['更新后的需求判断', '更新后的试点决定']);
  assert.deepEqual(E.preparePackage(a).artifacts.map(item => item.id), revised.map(item => item.id));
  const reviewed = E.review(a).observations.find(o => o.title === '当前作品版本已确定');
  assert.deepEqual(reviewed.evidenceIds, revised.map(item => item.id));
  const historical = E.review(a, first.id).observations.find(o => o.title === '作品版本已保存');
  assert.deepEqual(historical.evidenceIds, [first.id]);
  assert.equal(first.body, '原需求判断');
  assert.equal(second.body, '原试点决定');
  assert.equal(initial.artifacts[0].body, '原需求判断');
});

test('重复从旧快照分支，只采用最新分支；历史及来源标识完整保留', () => {
  const { a } = start();
  work(a, { title: '试点决定', body: '原始决定' });
  const initial = E.submit(a);
  const branchOne = E.revise(a, initial.id);
  E.saveArtifact(a, branchOne[0].id, { body: '第一条修订分支' });
  const branchTwo = E.revise(a, initial.id);
  E.saveArtifact(a, branchTwo[0].id, { body: '第二条修订分支' });
  assert.notEqual(branchOne[0].revisionBranchId, branchTwo[0].revisionBranchId);
  assert.equal(branchOne[0].sourceSubmissionId, initial.id);
  assert.equal(branchTwo[0].sourceSubmissionId, initial.id);
  assert.equal(a.artifacts.length, 3);
  assert.equal(E.currentArtifacts(a).length, 1);
  assert.equal(E.currentArtifacts(a)[0].id, branchTwo[0].id);
  E.saveArtifact(a, branchOne[0].id, { body: '编辑历史不自动切换当前分支' });
  assert.equal(E.currentArtifacts(a)[0].id, branchTwo[0].id);
  const current = E.submit(a);
  assert.equal(current.artifacts.length, 1);
  assert.equal(current.artifacts[0].body, '第二条修订分支');
  const nextChain = E.revise(a, current.id);
  assert.equal(E.currentArtifacts(a).length, 1);
  assert.equal(E.currentArtifacts(a)[0].id, nextChain[0].id);
  assert.equal(nextChain[0].parentArtifactId, branchTwo[0].id);
  assert.equal(initial.artifacts[0].body, '原始决定');
});

test('待检查外部作品不进入当前版本集合，单独采用后才进入', () => {
  const { a } = start();
  const userWork = work(a);
  const pending = work(a, { title: '外部分析', source: 'external-agent', adopted: false });
  assert.deepEqual(E.currentArtifacts(a).map(item => item.id), [userWork.id]);
  assert.deepEqual(E.preparePackage(a).artifacts.map(item => item.id), [userWork.id]);
  E.adoptArtifact(a, pending.id);
  assert.deepEqual(E.currentArtifacts(a).map(item => item.id), [userWork.id, pending.id]);
  const restored = JSON.parse(JSON.stringify(a));
  assert.deepEqual(E.currentArtifacts(restored).map(item => item.id), [userWork.id, pending.id]);
});

// ---- 2026-10-05（016）新增：岗位层、业务匹配、同事主动意见、优先级、回传与反馈样例 ----
test('岗位层：产品经理可进入，工程师标为稍后开放且没有案例', () => {
  const pm = E.careers.find(c => c.id === 'pm'); const eng = E.careers.find(c => c.id === 'engineer');
  assert.equal(pm.status, 'open'); assert.deepEqual(pm.cases, ['pilot', 'urgent', 'capacity']);
  assert.equal(eng.status, 'later'); assert.deepEqual(eng.cases, []);
});

test('业务描述只匹配审核过的情境，说明沿用与不照搬的部分', () => {
  assert.equal(E.matchBusiness('').status, 'empty');
  assert.equal(E.matchBusiness('给电商用户推荐商品').status, 'none');
  assert.equal(E.matchBusiness('chrome 插件 for three teams').status, 'none');
  assert.equal(E.matchBusiness('给外部客户做一个知识助手问答，先上线').status, 'partial');
  assert(!E.matchBusiness('门店员工想先查排班的知识助手').adopted.some(x => /试点/.test(x)));
  const m = E.matchBusiness('我们 HR 收到员工重复的差旅政策问题，想先给 200 人试点知识助手');
  assert.equal(m.status, 'matched'); assert.equal(m.template, 'pilot');
  assert(m.adopted.length >= 2); assert(m.notModeled.some(x => /30 人/.test(x)));
  const { s } = start(); const a = E.createAttempt(s, 'pilot', { intake: m });
  assert.equal(a.intake.template, 'pilot'); assert.equal(a.world.capacity, 30);
});

test('进入案例不伪造阅读记录；委托总随任务包交出', () => {
  const { a } = start();
  assert(!a.events.some(e => e.type === 'material_read'));
  assert.deepEqual(E.preparePackage(a, a.tasks[0].id).materials.map(m => m.id), ['brief']);
});

test('同事主动意见按场景规则触发、带类型、每个触发只出现一次', () => {
  const { a } = start();
  const w = E.createArtifact(a, { taskId: a.tasks[2].id, title: '笔记', purpose: '探索笔记', body: '' });
  E.saveArtifact(a, w.id, { body: '先给 50 人开放，下周上线再说，政策和办公都上。需要 40 人日以外的支持。' + '首批范围先按部门划分，之后再看反馈调整，重点是能尽快用起来，让大家先体验一下再说，其余细节后面补。'.repeat(2) });
  assert.equal((a.nudges || []).length, 0, '探索笔记不当作承诺核对');
  E.saveArtifact(a, w.id, { purpose: '试点决定' });
  assert(a.nudges.some(n => n.roleId === 'manager' && n.kind === 'object' && /50 人/.test(n.text)));
  assert(!a.nudges.some(n => /40 人/.test(n.text)), '“40 人日”不是人数');
  assert(a.nudges.some(n => n.roleId === 'business' && n.kind === 'object'));
  E.saveArtifact(a, w.id, { body: '先给 60 人开放，下周上线再说，政策和办公都上。' });
  assert.equal(a.nudges.filter(n => n.key === 'overcommit-' + w.id).length, 1);
  E.triggerPolicyUpdate(a);
  assert(a.nudges.some(n => n.key === 'policy-v2' && n.kind === 'remind'));
  assert(a.conversations.business.some(m => m.proactive));
  const n = a.nudges[0]; E.respondNudge(a, n.id, 'later'); assert.equal(n.status, 'later'); assert.equal(n.read, true);
});

test('三位同事给出不同的优先级建议，采用可撤销，从不自动应用', () => {
  const { a } = start();
  const sugs = ['manager', 'business', 'technical'].map(r => E.suggestPriorities(a, r));
  assert.deepEqual(a.tasks.map(t => t.priority), ['next', 'next', 'next']);
  const firsts = sugs.map(s => s.items.find(i => i.priority === 'first').title);
  assert.equal(new Set(firsts).size, 3);
  const before = E.applySuggestion(a, sugs[2]);
  assert.equal(a.tasks[0].priority, 'first');
  E.restoreOrder(a, before);
  assert.deepEqual(a.tasks.map(t => t.priority), ['next', 'next', 'next']);
});

test('移动事项记录优先级与位置；三件都标先做时经理提出帮助', () => {
  const { a } = start();
  const id = a.tasks[2].id; const before = E.moveTask(a, id, { priority: 'first' });
  assert.equal(a.tasks[0].id, id); assert.equal(a.tasks[0].priority, 'first');
  E.moveTask(a, a.tasks[1].id, { priority: 'first' }); E.moveTask(a, a.tasks[2].id, { priority: 'first' });
  assert(a.nudges.some(n => n.key === 'too-many-first' && n.kind === 'help'));
  E.restoreOrder(a, before); assert.equal(a.tasks.find(t => t.id === id).priority, 'next');
});

test('Agent 回传：同一 requestId 不重复导入，采用与验证分别记录', () => {
  const { a } = start();
  const pkg = E.preparePackage(a, a.tasks[0].id, { record: true });
  const text = JSON.stringify({ requestId: pkg.requestId, artifact: { title: '测试计划', purpose: '测试计划', body: '两条都通过了。' } });
  const r = E.importReturn(a, text, a.tasks[0].id);
  assert.equal(r.duplicate, false); assert.equal(r.artifact.adopted, false);
  assert.equal(E.importReturn(a, text).duplicate, true);
  E.adoptArtifact(a, r.artifact.id);
  let p = E.agentProgress(a, r.artifact); assert.deepEqual([p.exported, p.returned, p.adopted, p.linked], [true, true, true, false]);
  const run = E.runTest(a, { question: '会议室怎么预约？' });
  E.addEvidence(a, r.artifact.id, { id: run.id, type: 'test', version: run.configVersion });
  p = E.agentProgress(a, r.artifact); assert.equal(p.linked, true); assert.equal(p.linkedRuns, 1);
});

test('第三次业务操作后政策按场景规则更新；演示与场景来源分开记录', () => {
  const { a } = start();
  E.runTest(a, { question: '会议室怎么预约？' }); E.runTest(a, { question: '会议室怎么预约？' });
  assert.equal(E.maybeTriggerEvents(a), false); assert.equal(a.world.policyVersion, 1);
  E.requestResources(a, '需要实时同步');
  assert.equal(E.maybeTriggerEvents(a), true); assert.equal(a.world.policyVersion, 2);
  assert.equal(a.events.find(e => e.type === 'policy_updated').detail.source, 'scenario');
  assert.equal(E.maybeTriggerEvents(a), false);
});

test('样本反馈只基于记录：分清当时可知，识别计划外贡献，不打分', () => {
  const { a } = start();
  const t = E.addTask(a, { title: '问清政策多久变一次' });
  E.createArtifact(a, { taskId: t.id, title: '变化频率', body: '每月一次' });
  const early = E.runTest(a, { question: '差旅住宿上限？', taskId: a.tasks[1].id });
  E.triggerPolicyUpdate(a);
  const c = E.coach(a);
  assert(c.items.some(i => i.kind === 'contribution' && i.taskId === t.id));
  const stale = c.items.find(i => i.title === '政策变了，还没有重新测');
  assert(stale && /当时的结果没有问题/.test(stale.basis), '变化前的测试不被倒扣');
  assert(!c.items.some(i => i.title === '有回答用的是旧政策'), early.id);
  assert(c.items.every(i => !('score' in i)) && /不打分/.test(c.label));
  const d = E.createArtifact(a, { taskId: a.tasks[2].id, title: '决定', purpose: '试点决定', body: '面向全员开放。' });
  assert(!E.coach(a).items.some(i => i.title === '决定里的人数超出了容量'), '不凭“全员”等关键词判断');
  E.saveArtifact(a, d.id, { body: '首批 45 人。' });
  assert(E.coach(a).items.some(i => i.title === '决定里的人数超出了容量'));
});

test('知识助手只回答模拟范围内的问题，范围外如实说明', () => {
  const { a } = start();
  const leave = E.runTest(a, { question: '公司年假政策是什么？' });
  assert.equal(leave.citations.length, 0); assert.match(leave.answer, /没有足够/);
  const hotel = E.runTest(a, { question: '出差住酒店最多报多少？', taskId: a.tasks[1].id });
  assert.equal(hotel.citations[0].id, 'policy'); assert.equal(hotel.taskId, a.tasks[1].id);
});

test('含糊的资源申请由经理追问而不是直接批准', () => {
  const { a } = start();
  const r = E.requestResources(a, '啊');
  E.resolveResources(a, r.id);
  assert.equal(r.status, 'needs-info'); assert.equal(a.world.devDays, 3);
  assert(a.nudges.some(n => n.roleId === 'manager' && n.key === 'needs-info-' + r.id));
});

test('先交付再修订时，场景变化在修订开始时发生；快照保留同事意见', () => {
  const { a } = start();
  E.createArtifact(a, { taskId: a.tasks[2].id, title: '决定', purpose: '试点决定', body: '先给 20 人。' });
  E.triggerPolicyUpdate && null;
  const sub = E.submit(a);
  assert.equal(E.maybeTriggerEvents(a), false);
  E.revise(a, sub.id);
  assert.equal(E.maybeTriggerEvents(a), true); assert.equal(a.world.policyVersion, 2);
  const sub2 = E.submit(a);
  assert(Array.isArray(sub2.nudges) && sub2.nudges.some(n => n.key === 'policy-v2'));
});

test('复盘描述先后顺序与当时的世界变化，不评判对错', () => {
  const { a } = start();
  E.createArtifact(a, { taskId: a.tasks[2].id, title: '草稿', body: '先写决定' });
  E.runTest(a, { question: '差旅住宿上限？', taskId: a.tasks[1].id });
  E.triggerPolicyUpdate(a);
  const item = E.coach(a).items.find(i => i.kind === 'order');
  assert(item && /最先动手的是「形成可执行的试点决定」/.test(item.observed));
  assert(/政策更新前，你已经在处理政策问答/.test(item.basis));
  assert(/没有标准答案/.test(item.why));
});

test('改名后同事如实说明建议范围，空建议不能被采用', () => {
  const { a } = start();
  a.tasks.forEach((t, i) => E.updateTask(a, t.id, { title: '事项 ' + i }));
  const s = E.suggestPriorities(a, 'manager');
  assert.equal(s.items.length, 3, '靠稳定的种子标识匹配');
  const b = start().a; b.tasks.forEach(t => { delete t.seed; E.updateTask(b, t.id, { title: '别的事 ' + t.id.slice(-3) }); });
  const empty = E.suggestPriorities(b, 'manager');
  assert.equal(empty.items.length, 0); assert.match(empty.why, /只能就最初/);
  assert.throws(() => E.applySuggestion(b, empty), /没有覆盖/);
});

test('交付后继续改过的作品：修订可选从当前版继续，版本号只增不减', () => {
  const { a } = start();
  const d = E.createArtifact(a, { taskId: a.tasks[2].id, title: '决定', purpose: '试点决定', body: '交付时的内容' });
  const sub = E.submit(a);
  E.saveArtifact(a, d.id, { body: '交付后继续改的内容' });
  assert.deepEqual(E.laterEdits(a, sub.id).map(x => [x.snapshotRevision, x.currentRevision]), [[1, 2]]);
  const fromSnap = E.revise(a, sub.id);
  assert.equal(fromSnap[0].revision, 3); assert.equal(fromSnap[0].body, '交付时的内容');
  const fromCur = E.revise(a, sub.id, { basis: 'current' });
  assert.equal(fromCur[0].body, '交付时的内容', '当前链头已是上一次修订');
  assert(fromCur[0].revision > fromSnap[0].revision);
  assert(fromCur[0].adoptedAt, '修订副本保留采用时间');
});

test('旧存档缺字段时补全默认值，种子事项补上稳定标识', () => {
  const { a } = start();
  const old = JSON.parse(JSON.stringify(a));
  delete old.nudges; delete old.exports; delete old.acks; delete old.disputes; old.tasks.forEach(t => delete t.seed);
  E.normalizeAttempt(old);
  assert.deepEqual([old.nudges, old.exports, old.acks, old.disputes].map(Array.isArray), [true, true, true, true]);
  assert.deepEqual(old.tasks.map(t => t.seed), ['needs', 'policy', 'decision']);
  assert.throws(() => E.normalizeAttempt({ id: 'x', tasks: [] }), /场景条件/);
});

console.log('\n' + passed + ' 个状态行为回归通过。范围：本地规则与记录隔离；不验证模型、后端、真人学习效果或浏览器视觉。');
