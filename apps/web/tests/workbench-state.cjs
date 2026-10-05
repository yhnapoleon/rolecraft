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
  assert.equal(snapshot.artifacts[0].revision, 2, '引用也形成作品版本');
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

function testReturn(extra = {}) {
  return { schemaVersion: 1, returnId: 'return-one', artifact: { kind: 'test_set', title: '政策问答验证', purpose: '测试计划', cases: [{ question: '住宿上限是多少？', intent: '检查回答使用的政策版本', expectation: '有可追溯的引用', refs: [] }] }, ...extra };
}

test('结构化回传只产生待检查作品；问题、目的、预期与真实运行分开', () => {
  const { a } = start(); const data = testReturn();
  data.artifact.body = 'Agent 的摘要不会冒充执行结果';
  const preview = E.validateImported(JSON.stringify(data));
  assert.equal(preview.kind, 'test_set'); assert.equal(preview.cases[0].id, undefined);
  assert.match(preview.body, /预期表现（待验证）/);
  assert(!preview.body.includes(data.artifact.body));
  const result = E.importReturn(a, JSON.stringify(data), a.tasks[1].id);
  const x = result.artifact;
  assert.equal(x.adopted, false); assert.equal(x.kind, 'test_set'); assert.equal(x.revision, 1);
  assert.equal(x.cases[0].revision, 1); assert.match(x.cases[0].id, /^case-/);
  assert.equal(a.tests.length, 0); assert.equal(x.packageLinked, false);
  const id = x.cases[0].id; E.adoptArtifact(a, x.id);
  assert.equal(x.cases[0].id, id); assert.equal(a.tests.length, 0);
});

test('测试作品严格拒绝未知格式、身份、结果与可执行内容', () => {
  for (const patch of [{ kind: 'html' }, { results: [] }, { testRunId: 'fake' }, { script: 'alert(1)' }, { cases: [{ id: 'external-id', question: 'q', intent: 'why' }] }, { cases: [{ question: '<script>alert(1)</script>', intent: 'why' }] }, { cases: [{ question: 'q', intent: 'why', passed: true }] }]) {
    const value = testReturn(); Object.assign(value.artifact, patch);
    assert.throws(() => E.validateImported(JSON.stringify(value)));
  }
  assert.throws(() => E.validateImported(JSON.stringify(testReturn({ schemaVersion: 2 }))), /版本/);
  assert.throws(() => E.validateImported(JSON.stringify(testReturn({ returnId: '' }))), /returnId/);
  assert.throws(() => E.validateImported(JSON.stringify(testReturn({ tool: 'run' }))), /不支持/);
  assert.throws(() => E.validateImported(JSON.stringify({ title: 'fake', body: 'body', cases: [] })), /格式/);
  assert.throws(() => E.validateImported(JSON.stringify({ artifact: { title: 'fake', body: 'body' }, results: ['passed'] })), /格式/);
  assert.equal(E.validateImported('# old\ntext').kind, undefined);
  assert.equal(E.validateImported('{"title":"old","body":"text"}').body, 'text');
});

test('测试作品限制输入规模；不静默截断问题、预期和资料版本', () => {
  const value = testReturn();
  for (const [field, max] of [['question', 4000], ['intent', 2000], ['expectation', 2000]]) {
    const row = { question: 'q', intent: 'i', [field]: 'a'.repeat(max) };
    value.artifact.cases = [row]; assert.equal(E.validateImported(JSON.stringify(value)).cases[0][field].length, max);
    row[field] += 'a'; assert.throws(() => E.validateImported(JSON.stringify(value)), /长度限制/);
  }
  value.artifact.cases = []; assert.throws(() => E.validateImported(JSON.stringify(value)), /1–20/);
  value.artifact.cases = Array.from({ length: 21 }, () => ({ question: 'q', intent: 'i' }));
  assert.throws(() => E.validateImported(JSON.stringify(value)), /1–20/);
  value.artifact.cases = [{ question: 'q', intent: 'i', refs: [{ id: 'policy', version: 0 }] }];
  assert.throws(() => E.validateImported(JSON.stringify(value)), /正整数/);
});

test('returnId 对规范化回传幂等；内容冲突拒绝；同任务包可有独立修正版', () => {
  const { a } = start(); const pkg = E.preparePackage(a, a.tasks[1].id, { record: true });
  const data = testReturn({ requestId: pkg.requestId }); const text = JSON.stringify(data);
  const x = E.importReturn(a, text).artifact;
  E.updateTestCase(a, x.id, x.cases[0].id, { intent: '用户已改过' });
  assert.equal(E.importReturn(a, text).artifact.id, x.id); assert.equal(E.importReturn(a, text).duplicate, true);
  const changed = testReturn({ requestId: pkg.requestId }); changed.artifact.cases[0].question = '另一问题';
  assert.throws(() => E.importReturn(a, JSON.stringify(changed)), /同一 returnId/);
  const summaryChange = testReturn({ requestId: pkg.requestId }); summaryChange.artifact.body = '新摘要';
  assert.throws(() => E.importReturn(a, JSON.stringify(summaryChange)), /同一 returnId/);
  changed.returnId = 'return-two';
  const next = E.importReturn(a, JSON.stringify(changed)).artifact;
  assert.notEqual(next.id, x.id); assert.equal(next.adopted, false); assert.equal(next.previousReturnId, 'return-one');
  assert.equal(x.cases[0].intent, '用户已改过');
  assert.notEqual(x.cases[0].id, next.cases[0].id);
});

test('回传必须匹配已导出任务包与事项，材料引用只来自该包', () => {
  const { a } = start(); const pkg = E.preparePackage(a, a.tasks[1].id, { record: true });
  const data = testReturn({ requestId: pkg.requestId });
  assert.throws(() => E.importReturn(a, JSON.stringify(data), a.tasks[0].id), /事项/);
  assert.throws(() => E.importReturn(a, JSON.stringify({ ...data, requestId: 'not-exported' })), /任务包/);
  data.artifact.cases[0].refs = [{ id: 'policy', version: 1 }];
  assert.throws(() => E.importReturn(a, JSON.stringify(data)), /任务包版本/);
  data.artifact.cases[0].refs = [{ id: 'brief', version: 1 }];
  const x = E.importReturn(a, JSON.stringify(data)).artifact;
  assert.equal(x.taskId, a.tasks[1].id); assert.equal(x.packageLinked, true);
  assert.deepEqual(x.cases[0].refs, [{ id: 'brief', version: 1 }]);
  assert.throws(() => E.importReturn(a, JSON.stringify(data), a.tasks[0].id), /事项/);
  const unlinked = testReturn({ returnId: 'unlinked' }); unlinked.artifact.cases[0].refs = [{ id: 'tech_private', version: 1 }];
  assert.throws(() => E.importReturn(a, JSON.stringify(unlinked), a.tasks[1].id), /依据/);
});

test('行编辑、增删与保存维护稳定身份及完整历史；空草稿可保存', () => {
  const { a } = start(); const x = E.importReturn(a, JSON.stringify(testReturn()), a.tasks[1].id).artifact;
  const id = x.cases[0].id; const before = JSON.parse(JSON.stringify(x.cases));
  E.updateTestCase(a, x.id, id, { question: '' });
  assert.equal(x.revision, 2); assert.equal(x.cases[0].revision, 2); assert.equal(x.cases[0].question, '');
  assert.deepEqual(a.events.findLast(e => e.type === 'artifact_saved').detail.previous.cases, before);
  E.updateTestCase(a, x.id, id, { question: '' }); assert.equal(x.revision, 2);
  const added = E.addTestCase(a, x.id); assert.equal(x.revision, 3); assert.equal(added.revision, 1); assert.equal(added.question, '');
  E.saveArtifact(a, x.id, { title: '新的标题', body: '不能覆盖派生正文' });
  assert.equal(x.revision, 4); assert.equal(x.cases[0].id, id); assert.equal(x.cases[0].revision, 2);
  assert.equal(x.body, E.testSetSummary(x)); assert(!x.body.includes('不能覆盖'));
  const draftRows = JSON.parse(JSON.stringify(x.cases)); draftRows[0].expectation = '草稿的新预期';
  E.saveArtifact(a, x.id, { cases: draftRows });
  assert.equal(x.revision, 5); assert.equal(x.cases[0].revision, 3); assert.match(x.body, /草稿的新预期/);
  E.removeTestCase(a, x.id, added.id); assert.equal(x.revision, 6);
  E.removeTestCase(a, x.id, id); assert.equal(x.revision, 7); assert.equal(x.body, '');
  assert.throws(() => E.updateTestCase(a, x.id, 'not-here', { intent: 'i' }), /不存在/);
});

test('行身份和版本由本地维护；失败编辑不部分改写作品', () => {
  const { a } = start(); const x = E.importReturn(a, JSON.stringify(testReturn()), a.tasks[1].id).artifact;
  const before = JSON.stringify(x);
  assert.throws(() => E.updateTestCase(a, x.id, x.cases[0].id, { revision: 999 }), /不支持/);
  assert.throws(() => E.saveArtifact(a, x.id, { cases: [{ ...x.cases[0], id: 'foreign' }] }), /不属于/);
  assert.throws(() => E.saveArtifact(a, x.id, { cases: [x.cases[0], x.cases[0]] }), /重复/);
  assert.throws(() => E.saveArtifact(a, x.id, { cases: [{ ...x.cases[0], refs: [{ id: 'fake', version: 1 }] }] }), /依据/);
  assert.throws(() => E.addTestCase(a, x.id, { question: 'q', intent: 'i', result: 'passed' }), /不支持/);
  assert.equal(JSON.stringify(x), before);
  E.saveArtifact(a, x.id, { cases: [{ ...x.cases[0], revision: 999 }] }); assert.equal(x.cases[0].revision, 1);
});

test('任务包包含实际草稿快照和可选结构说明；导出不创建运行或泄露私有字段', () => {
  const { a } = start(); const w = work(a); w.draft = { title: '草稿标题', purpose: w.purpose, body: '尚未commit的内容' };
  a.token = 'DO-NOT-EXPORT'; a.privateFact = 'hidden';
  const pkg = E.preparePackage(a, a.tasks[0].id, { record: true });
  assert.equal(pkg.inputSnapshot.artifacts[0].body, '尚未commit的内容');
  assert.equal(pkg.inputSnapshot.artifacts[0].revision, w.revision);
  assert.equal(pkg.returnFormat.artifact.kind, 'test_set'); assert.equal(pkg.returnFormat.schemaVersion, 1);
  assert(pkg.supportedKinds.includes('text')); assert.match(pkg.instructions, /不必每次/);
  assert(!JSON.stringify(pkg).includes('DO-NOT-EXPORT')); assert(!JSON.stringify(pkg).includes('privateFact'));
  pkg.inputSnapshot.artifacts[0].body = '外部改变'; assert.notEqual(a.exports[0].inputSnapshot.artifacts[0].body, '外部改变');
  assert.equal(a.tests.length, 0);
});

test('旧依据可以保留但标明变化；过期检查覆盖编辑中草稿、材料与配置', () => {
  const { a } = start(); E.readMaterial(a, 'policy');
  const w = work(a, { taskId: a.tasks[1].id }); w.draft = { title: w.title, purpose: w.purpose, body: '导出草稿' };
  const pkg = E.preparePackage(a, a.tasks[1].id, { record: true });
  w.draft.body = '导出之后继续改'; E.triggerPolicyUpdate(a); E.updateConfig(a, { participants: 12 });
  const data = testReturn({ requestId: pkg.requestId }); data.artifact.cases[0].refs = [{ id: 'policy', version: 1 }];
  const result = E.importReturn(a, JSON.stringify(data));
  assert(result.staleInputs.some(x => x.kind === 'artifact'));
  assert(result.staleInputs.some(x => x.kind === 'material' && x.id === 'policy'));
  assert(result.staleInputs.some(x => x.kind === 'config'));
  assert.equal(result.artifact.cases[0].refs[0].version, 1);
  E.saveArtifact(a, result.artifact.id, { title: '仍保留旧引用的标题' });
  assert.equal(result.artifact.cases[0].refs[0].version, 1);
});

test('连接版引用校验使用实际可见材料；引用新增形成版本且保留完整结构', () => {
  const { a } = start(); const x = E.importReturn(a, JSON.stringify(testReturn()), a.tasks[1].id).artifact;
  a.backend = { materials: [{ id: 'actual_doc', version: 3, body: '真实后端正文' }] };
  E.addEvidence(a, x.id, { type: 'material', id: 'actual_doc', version: 3, body: '真实后端正文' });
  assert.equal(x.revision, 2); assert.equal(x.cases[0].revision, 1);
  const previous = a.events.findLast(e => e.type === 'artifact_saved').detail.previous;
  assert.equal(previous.kind, 'test_set'); assert.equal(previous.cases[0].id, x.cases[0].id); assert.deepEqual(previous.evidence, []);
  E.addEvidence(a, x.id, { type: 'material', id: 'actual_doc', version: 3 }); assert.equal(x.revision, 2);
  assert.throws(() => E.addEvidence(a, x.id, { type: 'material', id: 'policy', version: 1 }), /不属于/);
});

test('结构化作品JSON恢复保留本地行身份；派生摘要和旧Markdown兼容', () => {
  const { a } = start(); const old = work(a); const x = E.importReturn(a, JSON.stringify(testReturn()), a.tasks[1].id).artifact;
  const restored = JSON.parse(JSON.stringify(a)); restored.artifacts.find(w => w.id === x.id).body = '损坏的派生摘要';
  E.normalizeAttempt(restored);
  const rx = restored.artifacts.find(w => w.id === x.id);
  assert.equal(rx.cases[0].id, x.cases[0].id); assert.equal(rx.body, E.testSetSummary(rx));
  assert.equal(restored.artifacts.find(w => w.id === old.id).body, old.body);
  rx.cases[0].id = ''; assert.throws(() => E.normalizeAttempt(restored), /测试行 ID/);
});

test('删除测试行后安全撤销：原身份、修订和位置恢复，其他编辑与运行关联保留', () => {
  const { a } = start(); const x = E.importReturn(a, JSON.stringify(testReturn()), a.tasks[1].id).artifact;
  const first = x.cases[0];
  const middle = E.addTestCase(a, x.id, { question: '会议室怎么预约？', intent: '检查稳定知识' });
  const last = E.addTestCase(a, x.id, { question: '未知问题怎样处理？', intent: '检查兜底' });
  E.updateTestCase(a, x.id, middle.id, { expectation: '应有依据或明确兜底' });
  const original = JSON.parse(JSON.stringify(x.cases.find(row => row.id === middle.id)));
  const runBinding = { workId: x.id, workRevision: x.revision, caseId: original.id, caseRevision: original.revision, caseSnapshot: JSON.parse(JSON.stringify(original)), testRunId: 'recorded-server-run' };
  a.tests.push({ id: runBinding.testRunId, taskId: x.taskId, question: original.question, configVersion: a.configVersion, answer: 'fixture' });
  E.addEvidence(a, x.id, { id: runBinding.testRunId, version: a.configVersion, type: 'test', caseId: original.id, caseRevision: original.revision });
  const evidence = JSON.parse(JSON.stringify(x.evidence));
  E.removeTestCase(a, x.id, middle.id);
  E.saveArtifact(a, x.id, { title: '删除后改过的标题' });
  const beforeRestore = x.revision;
  const previousHistory = JSON.stringify(a.events.findLast(e => e.type === 'artifact_saved').detail.previous);
  const returned = E.restoreTestCase(a, x.id, middle.id);
  assert.equal(returned, x); assert.equal(x.revision, beforeRestore + 1);
  assert.deepEqual(x.cases.map(row => row.id), [first.id, middle.id, last.id]);
  assert.deepEqual(x.cases[1], original); assert.equal(x.title, '删除后改过的标题');
  assert.equal(runBinding.caseId, x.cases[1].id); assert.equal(runBinding.caseRevision, x.cases[1].revision);
  assert.deepEqual(runBinding.caseSnapshot, x.cases[1]); assert.deepEqual(x.evidence, evidence);
  assert.equal(a.tests.length, 1); assert.equal(x.body, E.testSetSummary(x));
  assert.equal(JSON.stringify(a.events.filter(e => e.type === 'artifact_saved').at(-2).detail.previous), previousHistory);
  const revision = x.revision; const events = a.events.length;
  E.restoreTestCase(a, x.id, middle.id); assert.equal(x.revision, revision); assert.equal(a.events.length, events);
});

test('撤销只能读取本作品历史，拒绝跨作品、未知身份和超过行数限制', () => {
  const { a } = start(); const x = E.importReturn(a, JSON.stringify(testReturn()), a.tasks[1].id).artifact;
  const y = E.importReturn(a, JSON.stringify(testReturn({ returnId: 'second-work' })), a.tasks[1].id).artifact;
  const removed = x.cases[0].id; E.removeTestCase(a, x.id, removed);
  assert.throws(() => E.restoreTestCase(a, y.id, removed), /历史/);
  assert.throws(() => E.restoreTestCase(a, x.id, { id: removed }), /文字/);
  assert.throws(() => E.restoreTestCase(a, x.id, 'invented'), /历史/);
  for (let i = 0; i < 20; i++) E.addTestCase(a, x.id);
  const before = JSON.stringify(x);
  assert.throws(() => E.restoreTestCase(a, x.id, removed), /20 行/);
  assert.equal(JSON.stringify(x), before);
});

test('删除与恢复经过JSON存档后仍使用最新历史修订，不回退到更早问题内容', () => {
  const { a } = start(); const x = E.importReturn(a, JSON.stringify(testReturn()), a.tasks[1].id).artifact;
  const id = x.cases[0].id;
  E.removeTestCase(a, x.id, id); E.restoreTestCase(a, x.id, id);
  E.updateTestCase(a, x.id, id, { question: '最新的政策问题' });
  const expected = JSON.parse(JSON.stringify(x.cases[0])); E.removeTestCase(a, x.id, id);
  const restored = JSON.parse(JSON.stringify(a)); E.normalizeAttempt(restored);
  const work = E.restoreTestCase(restored, x.id, id);
  assert.deepEqual(work.cases[0], expected); assert.equal(work.cases[0].revision, 2);
  E.updateTestCase(restored, x.id, id, { intent: '恢复后继续编辑' });
  assert.equal(work.cases[0].revision, 3);
});

test('待检查MD作品可编辑保存，不需要先采用；移除恢复保留草稿与原采用状态', () => {
  const { a } = start(); const x = E.importReturn(a, '# 随手导入\n\n需要继续改', a.tasks[0].id).artifact;
  assert.equal(x.adopted, false);
  E.saveArtifact(a, x.id, { title: '已编辑的标题', body: '保存后的正文' });
  assert.equal(x.revision, 2); assert.equal(x.adopted, false);
  x.draft = { title: x.title, purpose: x.purpose, body: '尚在编辑的草稿' };
  const before = JSON.parse(JSON.stringify(x)); const count = a.artifacts.length;
  assert.equal(E.removeArtifact(a, x.id), x); assert(x.removedAt);
  assert.equal(a.artifacts.length, count); assert.equal(x.revision, before.revision);
  assert.deepEqual(x.draft, before.draft); assert.equal(x.adoptedAt, before.adoptedAt);
  const events = a.events.length; E.removeArtifact(a, x.id); assert.equal(a.events.length, events);
  assert.equal(E.restoreArtifact(a, x.id), x); assert.equal(x.removedAt, null);
  assert.equal(x.adopted, false); assert.equal(x.id, before.id); assert.deepEqual(x.draft, before.draft);
  assert.equal(x.body, before.body); assert.equal(x.revision, before.revision);
  const restoredEvents = a.events.length; E.restoreArtifact(a, x.id); assert.equal(a.events.length, restoredEvents);
  assert.deepEqual(a.events.slice(-2).map(e => e.type), ['artifact_removed', 'artifact_restored']);
});

test('移除当前链头不会复活旧版；导出与新交付排除它，旧快照保持不变', () => {
  const { a } = start(); const original = work(a, { title: '原始作品' });
  const snapshot = E.submit(a); const frozen = JSON.stringify(snapshot);
  const latest = E.revise(a, snapshot.id)[0]; E.saveArtifact(a, latest.id, { body: '新的当前版本' });
  E.removeArtifact(a, latest.id);
  assert.equal(E.currentArtifacts(a).length, 0);
  assert.equal(E.preparePackage(a).artifacts.length, 0);
  assert.equal(E.submit(a).artifacts.length, 0);
  assert.equal(JSON.stringify(snapshot), frozen); assert.equal(original.body, '我尚不知道是否值得上线，先留下问题。');
  assert(Object.isFrozen(snapshot.artifacts[0]));
  E.restoreArtifact(a, latest.id);
  assert.deepEqual(E.currentArtifacts(a).map(x => x.id), [latest.id]);
  assert.deepEqual(E.preparePackage(a).artifacts.map(x => x.id), [latest.id]);
  assert.equal(JSON.stringify(snapshot), frozen);
});

test('移除作品后拒绝编辑、采用、引用和行操作；恢复原行及运行关联', () => {
  const { a } = start(); const x = E.importReturn(a, JSON.stringify(testReturn()), a.tasks[1].id).artifact;
  E.adoptArtifact(a, x.id);
  const row = x.cases[0]; const rowBefore = JSON.parse(JSON.stringify(row));
  a.tests.push({ id: 'preserved-run', workId: x.id, caseId: row.id, caseRevision: row.revision, configVersion: 1, answer: 'fixture' });
  E.addEvidence(a, x.id, { type: 'test', id: 'preserved-run', version: 1 });
  const revision = x.revision; const evidence = JSON.parse(JSON.stringify(x.evidence));
  E.removeArtifact(a, x.id);
  const frozenRemoved = JSON.stringify(x);
  for (const fn of [() => E.saveArtifact(a, x.id, { body: 'change' }), () => E.adoptArtifact(a, x.id), () => E.addEvidence(a, x.id, { id: 'preserved-run', version: 1 }), () => E.updateTestCase(a, x.id, row.id, { intent: 'change' }), () => E.addTestCase(a, x.id), () => E.removeTestCase(a, x.id, row.id), () => E.restoreTestCase(a, x.id, row.id)]) assert.throws(fn, /已移除/);
  assert.equal(JSON.stringify(x), frozenRemoved);
  E.restoreArtifact(a, x.id);
  assert.equal(x.revision, revision); assert.deepEqual(x.cases[0], rowBefore); assert.deepEqual(x.evidence, evidence);
  assert.equal(a.tests[0].workId, x.id); assert.equal(a.tests[0].caseId, x.cases[0].id);
  assert.equal(a.tests[0].caseRevision, x.cases[0].revision); assert.equal(x.adopted, true);
});

test('移除回传仍参与去重，不自动恢复，也不创建第二份作品', () => {
  const { a } = start(); const pkg = E.preparePackage(a, a.tasks[1].id, { record: true });
  const text = JSON.stringify(testReturn({ requestId: pkg.requestId }));
  const x = E.importReturn(a, text).artifact; E.removeArtifact(a, x.id);
  const count = a.artifacts.length; const events = a.events.length;
  const duplicate = E.importReturn(a, text);
  assert.equal(duplicate.duplicate, true); assert.equal(duplicate.removed, true); assert.equal(duplicate.artifact, x);
  assert.equal(a.artifacts.length, count); assert.equal(a.events.length, events); assert(x.removedAt);
  const changed = testReturn({ requestId: pkg.requestId }); changed.artifact.title = '冲突内容';
  assert.throws(() => E.importReturn(a, JSON.stringify(changed)), /同一 returnId/);
  E.restoreArtifact(a, x.id); assert.equal(E.importReturn(a, text).removed, false);
  const legacyPkg = E.preparePackage(a, a.tasks[0].id, { record: true });
  const legacyText = JSON.stringify({ requestId: legacyPkg.requestId, artifact: { title: '旧格式', body: '文字' } });
  const legacy = E.importReturn(a, legacyText).artifact; E.removeArtifact(a, legacy.id);
  assert.equal(E.importReturn(a, legacyText).removed, true);
});

test('暂停和已提交的连接版拒绝移除与恢复；离线demo仍允许提交后继续编辑', () => {
  const { a } = start(); const x = work(a);
  for (const status of ['paused', 'submitted']) {
    a.backend = { status };
    const before = JSON.stringify(x), events = a.events.length;
    assert.throws(() => E.removeArtifact(a, x.id), /暂停|只读/);
    assert.equal(JSON.stringify(x), before); assert.equal(a.events.length, events);
  }
  a.backend.status = 'active'; E.removeArtifact(a, x.id);
  for (const status of ['paused', 'submitted']) {
    a.backend.status = status;
    assert.throws(() => E.restoreArtifact(a, x.id), /暂停|只读/); assert(x.removedAt);
  }
  a.backend.status = 'active'; E.restoreArtifact(a, x.id);
  delete a.backend; E.submit(a); E.saveArtifact(a, x.id, { body: 'demo原有提交后编辑' });
  E.removeArtifact(a, x.id); E.restoreArtifact(a, x.id); assert.equal(x.body, 'demo原有提交后编辑');
});

test('旧存档与移除标记可恢复；生成期间移除输入作品会提示依据变化', () => {
  const { a } = start(); const x = work(a); assert.equal(x.removedAt, undefined);
  const pkg = E.preparePackage(a, x.taskId, { record: true });
  E.removeArtifact(a, x.id); const removedAt = x.removedAt;
  const restored = JSON.parse(JSON.stringify(a)); E.normalizeAttempt(restored);
  assert.equal(restored.artifacts[0].removedAt, removedAt); assert.equal(E.currentArtifacts(restored).length, 0);
  const result = E.importReturn(restored, JSON.stringify(testReturn({ requestId: pkg.requestId })));
  assert(result.staleInputs.some(item => item.kind === 'artifact' && item.artifactId === x.id));
  E.restoreArtifact(restored, x.id); assert.equal(E.currentArtifacts(restored)[0].id, x.id);
  const old = JSON.parse(JSON.stringify(a)); delete old.artifacts[0].removedAt;
  E.normalizeAttempt(old); assert.equal(old.artifacts[0].removedAt, null); assert.equal(E.currentArtifacts(old)[0].id, x.id);
});

function investigationStart() {
  const { a } = start();
  a.world.policyVersion = 2;
  a.backend = { status: 'active', version: 3, materials: [{ id: 'policy', version: 2, title: '政策', body: 'fixture current policy' }, { id: 'faq', version: 1, title: '办公问答', body: 'fixture faq' }] };
  // Fixtures represent already returned records. The engine must never execute
  // a test or turn these descriptions into new results during import.
  a.tests = [
    { id: 'run-old', question: '住宿上限？', answer: 'fixture old answer', citations: [{ id: 'policy', version: 1 }], configVersion: 1, policyVersion: 2, indexVersion: 1, asOfSeq: 2 },
    { id: 'run-new', question: '住宿上限？', answer: 'fixture new answer', citations: [{ id: 'policy', version: 2 }], configVersion: 1, policyVersion: 2, indexVersion: 2, asOfSeq: 3 },
    { id: 'run-faq', question: '会议室？', answer: 'fixture faq answer', citations: [{ id: 'faq', version: 1 }], configVersion: 1, policyVersion: 2, indexVersion: 2, asOfSeq: 4 }
  ];
  return a;
}
function investigationReturn(extra = {}) {
  return { schemaVersion: 1, returnId: 'investigation-one', artifact: { kind: 'investigation', title: '政策回答调查', purpose: '探索笔记', question: '同一个问题为什么回答变了？', blocks: [{ type: 'source_check', testId: 'run-old', material: { id: 'policy', version: 2 } }, { type: 'note', title: '待查解释', text: '版本差异可能解释结果，仍需核对。' }, { type: 'test_compare', testIds: ['run-new', 'run-old'] }, { type: 'retest', testId: 'run-new', label: '再检查一次' }] }, ...extra };
}

test('调查关联只统计当前已采用结构中的真实记录与对应重测，去重且不当作结论验证', () => {
  const a = investigationStart();
  const x = E.importReturn(a, JSON.stringify(investigationReturn()), a.tasks[1].id).artifact;
  assert.equal(E.agentProgress(a, x).linkedRuns, 0, '尚未采用不计');
  E.adoptArtifact(a, x.id);
  assert.equal(E.agentProgress(a, x).linkedRuns, 2, '已有历史测试不要求采用后重新运行');
  assert.equal(E.agentProgress(a, x).verified, false, '关联记录不证明结论');
  assert(!a.nudges.some(n => n.key === 'adopt-' + x.id), '不再生成调查没有实际测试的错误提醒');

  const retest = x.blocks.find(block => block.type === 'retest');
  const run = { ...a.tests.find(t => t.id === retest.testId), id: 'investigation-retest', investigationId: x.id, blockId: retest.id, blockRevision: retest.revision, baselineRunId: retest.testId };
  a.tests.push(run, { ...run }, { ...run, id: 'wrong-block', blockId: 'missing' }, { ...run, id: 'old-block-version', blockRevision: 0 });
  x.evidence.push({ id: run.id, type: 'test' }, { id: 'nonexistent', type: 'test' });
  assert.equal(E.agentProgress(a, x).linkedRuns, 3, '实际重测计入，重复和无效身份不计');
  assert(!E.coach(a).items.some(i => i.title === 'Agent 的作品还没关联测试' && i.refs.some(r => r.id === x.id)));

  // Exercise the actual bilingual frontend rules with deterministic text helpers.
  const coachModule = { exports: {} };
  const coachSource = readFileSync(resolve(__dirname, '../src/app/coach.js'), 'utf8').replace(/^import .*;\n/gm, '').replace(/^export /gm, '');
  runInThisContext('(function(module,T,when,taskTitle){\n' + coachSource + '\nmodule.exports={notes,observations};})')(coachModule, zh => zh, () => '', task => task.title);
  const C = coachModule.exports;
  assert(!C.notes(a, E).some(n => n.key === 'adopt-' + x.id));
  assert(!C.observations(a, E).some(i => i.title === 'Agent 的作品还没关联测试' && i.refs.some(r => r.id === x.id)));

  const note = x.blocks.find(block => block.type === 'note');
  x.draft = { blocks: [note] };
  assert.equal(E.agentProgress(a, x).linkedRuns, 3, '未保存草稿不替代已采用结构');
  delete x.draft;
  E.saveArtifact(a, x.id, { blocks: [note] });
  assert.equal(E.agentProgress(a, x).linkedRuns, 0, '移除引用和重测入口后不再计旧关联');
  x.blocks = [{ id: 'bad-ref', revision: 1, type: 'test_compare', testIds: ['nonexistent'] }];
  assert.equal(E.agentProgress(a, x).linkedRuns, 0, '伪造引用不计');
  assert(C.notes(a, E).some(n => n.key === 'adopt-' + x.id));
  assert(C.observations(a, E).some(i => i.title === 'Agent 的作品还没关联测试' && i.refs.some(r => r.id === x.id)));
  x.blocks = [{ id: 'real-ref', revision: 1, type: 'test_compare', testIds: ['run-old'] }];
  E.removeArtifact(a, x.id);
  assert.equal(E.agentProgress(a, x).linkedRuns, 0, '移除作品不计');
  E.restoreArtifact(a, x.id);
  const replacement = E.createArtifact(a, { kind: 'investigation', title: '新修订', question: '继续调查', blocks: [{ type: 'note', text: '当前没有引用' }], source: 'external-agent' });
  replacement.parentArtifactId = x.id;
  assert.equal(E.agentProgress(a, x).linkedRuns, 0, '被后续已采用作品取代的旧版本不计');
});

test('调查回传保留Agent模块选择与顺序，ID由应用生成，不伪造任何运行内容', () => {
  const a = investigationStart(); const data = investigationReturn();
  const preview = E.validateImported(JSON.stringify(data));
  assert.equal(preview.kind, 'investigation'); assert.equal(preview.blocks[0].id, undefined);
  const before = JSON.stringify(a.tests); const x = E.importReturn(a, JSON.stringify(data), a.tasks[1].id).artifact;
  assert.equal(x.adopted, false); assert.equal(x.question, data.artifact.question);
  assert.deepEqual(x.blocks.map(block => block.type), data.artifact.blocks.map(block => block.type));
  assert(x.blocks.every(block => block.id.startsWith('block-') && block.revision === 1));
  assert.equal(new Set(x.blocks.map(block => block.id)).size, 4);
  assert.equal(JSON.stringify(a.tests), before); assert.equal(x.body, E.investigationSummary(x));
  assert(!x.body.includes('fixture old answer')); assert.match(x.body, /不代表已经执行/);
  const noteOnly = investigationReturn({ returnId: 'note-only' }); noteOnly.artifact.blocks = [{ type: 'note', text: '当前证据不足。' }];
  assert.equal(E.importReturn(a, JSON.stringify(noteOnly)).artifact.blocks.length, 1);
});

test('调查模块拒绝外部身份、伪造结果、脚本与不支持结构，且不自动变成普通文字', () => {
  const invalid = [
    { type: 'note', text: 'note', id: 'foreign-id' },
    { type: 'note', text: '<script>alert(1)</script>' },
    { type: 'test_compare', testIds: ['run-old'], answers: ['fake answer'] },
    { type: 'source_check', testId: 'run-old', material: { id: 'policy', version: 2, body: 'fake policy' } },
    { type: 'retest', testId: 'run-old', passed: true },
    { type: 'retest', testId: 'run-old', url: '/tests' },
    { type: 'raw_html', html: '<div>fake</div>' }
  ];
  for (const block of invalid) {
    const data = investigationReturn(); data.artifact.blocks = [block];
    assert.throws(() => E.validateImported(JSON.stringify(data)));
  }
  const fakeBody = investigationReturn(); fakeBody.artifact.body = 'fake result';
  assert.throws(() => E.validateImported(JSON.stringify(fakeBody)), /不支持/);
  const rule = investigationReturn(); rule.artifact.ruleOrigin = true;
  assert.throws(() => E.validateImported(JSON.stringify(rule)), /不支持/);
  const wrongPurpose = investigationReturn(); wrongPurpose.artifact.purpose = '试点决定';
  assert.throws(() => E.validateImported(JSON.stringify(wrongPurpose)), /用途/);
});

test('调查限制块数、文本长度与重复测试ID，单条实际测试也可展示', () => {
  const data = investigationReturn(); data.artifact.blocks = [{ type: 'test_compare', testIds: ['run-old'] }];
  assert.equal(E.validateImported(JSON.stringify(data)).blocks.length, 1);
  data.artifact.blocks[0].testIds = ['run-old', 'run-old']; assert.throws(() => E.validateImported(JSON.stringify(data)), /重复/);
  data.artifact.blocks[0].testIds = ['1', '2', '3', '4', '5']; assert.throws(() => E.validateImported(JSON.stringify(data)), /1–4/);
  data.artifact.blocks = []; assert.throws(() => E.validateImported(JSON.stringify(data)), /1–8/);
  data.artifact.blocks = Array.from({ length: 9 }, () => ({ type: 'note', text: 'n' })); assert.throws(() => E.validateImported(JSON.stringify(data)), /1–8/);
  data.artifact.blocks = [{ type: 'note', text: 'n'.repeat(2001) }]; assert.throws(() => E.validateImported(JSON.stringify(data)), /长度限制/);
  data.artifact.blocks = [{ type: 'note', title: 'n'.repeat(121), text: 'n' }]; assert.throws(() => E.validateImported(JSON.stringify(data)), /长度限制/);
  data.artifact.blocks = [{ type: 'retest', testId: 'run-old', label: 'n'.repeat(81) }]; assert.throws(() => E.validateImported(JSON.stringify(data)), /长度限制/);
  data.artifact.blocks = [{ type: 'note', text: 'n' }]; data.artifact.question = 'q'.repeat(1001); assert.throws(() => E.validateImported(JSON.stringify(data)), /长度限制/);
});

test('调查证据校验实际记录和包范围，来源核对允许目标版本不同但拒绝无关资料', () => {
  const a = investigationStart(); E.readMaterial(a, 'policy');
  const pkg = E.preparePackage(a, a.tasks[1].id, { record: true, testIds: ['run-old', 'run-new'] });
  const data = investigationReturn({ requestId: pkg.requestId });
  const x = E.importReturn(a, JSON.stringify(data)).artifact;
  assert.equal(x.blocks[0].material.version, 2); assert.equal(a.tests[0].citations[0].version, 1);
  const outside = investigationReturn({ requestId: pkg.requestId, returnId: 'outside' }); outside.artifact.blocks = [{ type: 'retest', testId: 'run-faq' }];
  assert.throws(() => E.importReturn(a, JSON.stringify(outside)), /任务包/);
  outside.artifact.blocks = [{ type: 'retest', testId: 'invented-test' }]; assert.throws(() => E.importReturn(a, JSON.stringify(outside)), /真实记录/);
  outside.artifact.blocks = [{ type: 'source_check', testId: 'run-old', material: { id: 'policy', version: 99 } }]; assert.throws(() => E.importReturn(a, JSON.stringify(outside)), /版本/);
  const unrelated = investigationReturn({ returnId: 'unrelated' }); unrelated.artifact.blocks = [{ type: 'source_check', testId: 'run-old', material: { id: 'faq', version: 1 } }];
  assert.throws(() => E.importReturn(a, JSON.stringify(unrelated)), /实际引用/);
  // A snapshot records permission to refer to v2, not a claim that its body is
  // still cached. The live resolver must obtain that exact historical body.
  a.backend.materials[0].version = 3;
  const historical = investigationReturn({ requestId: pkg.requestId, returnId: 'historical' });
  const hist = E.importReturn(a, JSON.stringify(historical));
  assert.equal(hist.artifact.blocks[0].material.version, 2); assert(hist.staleInputs.some(item => item.kind === 'material'));
  assert(!ownKey(hist.artifact.blocks[0].material, 'body'));
  const unavailable = investigationReturn({ returnId: 'unavailable-without-package' });
  assert.throws(() => E.importReturn(a, JSON.stringify(unavailable)), /版本/);
  const savedMaterials = a.backend.materials; a.backend.materials = [];
  assert.throws(() => E.importReturn(a, JSON.stringify({ ...historical, returnId: 'no-longer-readable' })), /不可读/);
  a.backend.materials = savedMaterials;
  const notActuallyHere = investigationReturn({ requestId: pkg.requestId, returnId: 'missing-real' });
  a.tests = a.tests.filter(test => test.id !== 'run-old');
  assert.throws(() => E.importReturn(a, JSON.stringify(notActuallyHere)), /真实记录/);
});
function ownKey(value, key) { return Object.prototype.hasOwnProperty.call(value, key); }

test('调查排序只改变作品版本；修改模块内容增加块版本并保存原结构', () => {
  const a = investigationStart(); const x = E.importReturn(a, JSON.stringify(investigationReturn()), a.tasks[1].id).artifact;
  const ids = x.blocks.map(block => block.id); const before = JSON.parse(JSON.stringify(x.blocks));
  E.moveInvestigationBlock(a, x.id, ids[3], ids[0]);
  assert.equal(x.revision, 2); assert.deepEqual(x.blocks.map(block => block.id), [ids[3], ids[0], ids[1], ids[2]]);
  assert(x.blocks.every(block => block.revision === 1));
  assert.deepEqual(a.events.findLast(event => event.type === 'artifact_saved').detail.previous.blocks, before);
  const moved = x.revision; E.moveInvestigationBlock(a, x.id, ids[3], ids[0]); assert.equal(x.revision, moved);
  const blocks = JSON.parse(JSON.stringify(x.blocks)); blocks.find(block => block.type === 'note').text = '用户修正了这条推测';
  E.saveArtifact(a, x.id, { title: '新标题', question: '新调查问题', blocks, body: '不可替换派生摘要' });
  assert.equal(x.revision, 3); assert.equal(x.blocks.find(block => block.type === 'note').revision, 2);
  assert(x.blocks.filter(block => block.type !== 'note').every(block => block.revision === 1));
  assert.equal(x.question, '新调查问题'); assert.match(x.body, /用户修正/); assert(!x.body.includes('不可替换'));
  const unchanged = JSON.stringify(x);
  assert.throws(() => E.moveInvestigationBlock(a, x.id, 'foreign-id'), /不存在/);
  assert.throws(() => E.saveArtifact(a, x.id, { blocks: [{ ...x.blocks[0], id: 'foreign-id' }] }), /不属于/);
  assert.throws(() => E.saveArtifact(a, x.id, { blocks: [x.blocks[0], x.blocks[0]] }), /重复/);
  assert.equal(JSON.stringify(x), unchanged);
});

test('调查输入快照保留question、blocks与草稿，JSON恢复和历史提交不漂移', () => {
  const a = investigationStart(); const x = E.importReturn(a, JSON.stringify(investigationReturn()), a.tasks[1].id).artifact;
  E.adoptArtifact(a, x.id);
  const draftBlocks = JSON.parse(JSON.stringify(x.blocks)); draftBlocks[1].text = '尚未提交的分析';
  x.draft = { title: x.title, purpose: x.purpose, question: '草稿问题', blocks: draftBlocks };
  const snapshot = E.captureInputSnapshot(a, { artifacts: [x], materials: a.backend.materials, tests: a.tests });
  assert.equal(snapshot.artifacts[0].question, '草稿问题'); assert.equal(snapshot.artifacts[0].blocks[1].text, '尚未提交的分析');
  assert.match(snapshot.artifacts[0].body, /尚未提交的分析/); assert.equal(snapshot.artifacts[0].blocks[0].id, x.blocks[0].id);
  const originalDraftBlocks = x.draft.blocks; x.draft.blocks = [{ type: 'retest', testId: 'run-faq' }];
  assert.deepEqual(E.investigationReferences(x).testIds, ['run-faq']); x.draft.blocks = originalDraftBlocks;
  delete x.draft;
  const submitted = E.submit(a); const frozen = JSON.stringify(submitted);
  const copy = JSON.parse(JSON.stringify(a)); copy.artifacts[0].body = '损坏的摘要'; E.normalizeAttempt(copy);
  assert.equal(copy.artifacts[0].body, E.investigationSummary(copy.artifacts[0]));
  assert.deepEqual(copy.artifacts[0].blocks, x.blocks);
  E.moveInvestigationBlock(a, x.id, x.blocks[0].id); assert.equal(JSON.stringify(submitted), frozen);
  assert(Object.isFrozen(submitted.artifacts[0].blocks));
});

test('规则起始调查只接受真实引用，本地来源标记与引用收集不混作Agent生成', () => {
  const a = investigationStart(); const input = investigationReturn().artifact;
  const x = E.createArtifact(a, { ...input, source: 'user', adopted: true, ruleOrigin: true, taskId: a.tasks[1].id });
  assert.equal(x.source, 'user'); assert.equal(x.ruleOrigin, true); assert.equal(x.adopted, true);
  const refs = E.investigationReferences(x);
  assert.deepEqual(refs.testIds, ['run-old', 'run-new']); assert.deepEqual(refs.materials, [{ id: 'policy', version: 2 }]);
  refs.materials[0].version = 99; assert.equal(x.blocks[0].material.version, 2);
  assert.throws(() => E.createArtifact(a, { ...input, blocks: [{ type: 'retest', testId: 'fake' }] }), /真实记录/);
  assert.throws(() => E.createArtifact(a, { ...input, source: 'external-agent', ruleOrigin: true }), /本地应用/);
  const guide = E.buildReturnGuide('pkg');
  assert.deepEqual(guide.supportedKinds, ['text', 'test_set', 'investigation']);
  assert.equal(guide.returnFormat.artifact.kind, 'test_set'); assert.equal(guide.returnFormats.investigation.artifact.kind, 'investigation');
  assert.match(guide.instructions, /选择和排序/);
});

test('调查继承回传幂等和可恢复移除，保留块身份与顺序，不生成额外测试', () => {
  const a = investigationStart(); E.readMaterial(a, 'policy');
  const pkg = E.preparePackage(a, a.tasks[1].id, { record: true });
  const text = JSON.stringify(investigationReturn({ requestId: pkg.requestId }));
  const x = E.importReturn(a, text).artifact; const blocks = JSON.parse(JSON.stringify(x.blocks)); const tests = JSON.stringify(a.tests);
  assert.equal(E.importReturn(a, text).duplicate, true);
  E.removeArtifact(a, x.id); assert.equal(E.importReturn(a, text).removed, true);
  assert.throws(() => E.moveInvestigationBlock(a, x.id, blocks[0].id), /已移除/);
  assert.throws(() => E.saveArtifact(a, x.id, { question: '不能改' }), /已移除/);
  E.restoreArtifact(a, x.id); assert.deepEqual(x.blocks, blocks); assert.equal(x.revision, 1);
  a.backend.status = 'paused'; assert.throws(() => E.moveInvestigationBlock(a, x.id, blocks[0].id), /暂停/);
  a.backend.status = 'active';
  const changed = investigationReturn({ requestId: pkg.requestId }); changed.artifact.blocks.reverse(); assert.throws(() => E.importReturn(a, JSON.stringify(changed)), /同一 returnId/);
  changed.returnId = 'investigation-revised'; const revised = E.importReturn(a, JSON.stringify(changed)).artifact;
  assert.notEqual(revised.id, x.id); assert.equal(revised.adopted, false); assert.equal(revised.previousReturnId, x.returnId);
  assert.equal(JSON.stringify(a.tests), tests);
});

test('新版text信封兼容普通编辑和幂等；旧Markdown与legacy JSON不改变', () => {
  const { a } = start();
  const data = { schemaVersion: 1, returnId: 'text-one', artifact: { kind: 'text', title: '普通分析', purpose: '探索笔记', body: '这里只需要文字。' } };
  const x = E.importReturn(a, JSON.stringify(data), a.tasks[0].id).artifact;
  assert.equal(x.kind, 'text'); assert.equal(x.adopted, false); assert.equal(x.body, data.artifact.body);
  E.saveArtifact(a, x.id, { body: '用户直接修改' }); assert.equal(x.body, '用户直接修改');
  assert.equal(E.importReturn(a, JSON.stringify(data)).artifact, x);
  assert.throws(() => E.validateImported(JSON.stringify({ ...data, artifact: { ...data.artifact, blocks: [] } })), /不支持/);
  assert.equal(E.validateImported('# Markdown\n原来的写法').kind, undefined);
  assert.equal(E.validateImported('{"title":"legacy","body":"原来的JSON"}').body, '原来的JSON');
});

console.log('\n' + passed + ' 个状态行为回归通过。范围：本地规则与记录隔离；不验证模型、后端、真人学习效果或浏览器视觉。');
