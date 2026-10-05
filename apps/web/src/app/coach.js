// Scenario rules that read what actually happened (server events, tests, local work)
// and turn it into colleague reminders, feedback and priority advice. They are rules,
// not language understanding, and the UI labels them as such. Ported from the v2 engine
// and made bilingual; the backend has no equivalent yet (see the interface requirements).
import { T, when } from './i18n';
import { taskTitle } from './vocab.js';

const NAME = { manager: 'Priya', business: 'Mei', technical: 'Daniel' };
const capNumbers = (body, cap) => ((body || '').match(/(\d{2,5})\s*(?:人|名|位|people|users|staff|employees)(?![日天次时周月]|-?day)/gi) || []).map(x => parseInt(x, 10)).filter(n => n > cap);

export function facts(a, E) {
  const server = (a.events || []).filter(e => e.server);
  const policyEv = server.find(e => e.type === 'policy_updated');
  const policySeq = policyEv ? policyEv.seq : null;
  const tests = a.tests || [];
  const works = E.currentArtifacts(a);
  const reads = server.filter(e => e.type === 'material_read');
  const readIds = new Set(reads.map(e => e.detail && e.detail.materialId));
  const readPolicyNew = policySeq != null && reads.some(e => e.detail && e.detail.materialId === 'policy' && e.seq > policySeq);
  const approvals = server.filter(e => e.type === 'approve_request');
  const talked = role => (a.conversations[role] || []).some(m => m.role === 'user');
  const decision = works.find(w => E.intentOf((w.draft ? { ...w, ...w.draft } : w).purpose) === 'commit' && (w.draft ? w.draft.body : w.body).trim());
  return { server, policyEv, policySeq, tests, works, reads, readIds, readPolicyNew, approvals, talked, decision };
}

/** Colleague reminders. Recomputed from records; each key appears once and can be set aside. */
export function notes(a, E) {
  const f = facts(a, E); const out = [];
  const cap = a.world.capacity;
  const add = (role, kind, key, text, ref = {}) => out.push({ role, kind, key, text, taskId: ref.taskId || null, targetId: ref.targetId || null });
  if (f.decision) {
    const v = f.decision.draft ? { ...f.decision, ...f.decision.draft } : f.decision;
    const over = capNumbers(v.body, cap);
    if (over.length) add('manager', 'object', 'overcommit-' + f.decision.id, T(`你在「${v.title}」里写了 ${over[0]} 人，这次能给的容量是 ${cap} 人。写进承诺之前，先想想它靠什么成立。`, `Your “${v.title}” says ${over[0]} people; the capacity this time is ${cap}. Before you promise it, what makes it hold?`), { taskId: f.decision.taskId, targetId: f.decision.id });
    if (v.body.trim().length > 120 && !f.talked('business') && !f.readIds.has('business')) add('business', 'object', 'decision-without-needs', T('我看到你在写试点决定了。首批员工最常问什么，你还没和我确认过——范围是按什么定的？', 'I see you are writing the pilot decision. You have not checked with me what first users ask most. What is the scope based on?'), { taskId: f.decision.taskId, targetId: f.decision.id });
  }
  if (a.tasks.filter(t => t.priority === 'first').length >= 3) add('manager', 'help', 'too-many-first', T('三件事都标成先做了，等于没有先做。要我帮你一起看看哪件最影响下周的承诺吗？', 'Everything is “do first”, which means nothing is. Want to look together at what matters most for next week?'));
  if (f.policyEv) add('business', 'remind', 'policy-changed', T(`差旅政策刚出了 v${a.world.policyVersion}。员工会按新规定报销——助手现在答的是哪一版？`, `The travel policy just moved to v${a.world.policyVersion}. Staff will claim under the new rules. Which version is the assistant answering from?`));
  const stale = f.tests.filter(t => t.stale).at(-1);
  if (stale) add('technical', 'correct', 'stale-index', T(`「${stale.question}」那次回答引用的版本已经不是最新。索引不会自己追上源文档，测之前先看清楚是哪一版。`, `The answer to “${stale.question}” cited a version that was no longer current. The index does not catch up on its own; check which version you are testing.`), { taskId: stale.taskId });
  f.works.filter(w => w.source !== 'user' && w.adopted).forEach(w => {
    const linked = (w.evidence || []).some(ev => ev.type === 'test');
    if (!linked) add('technical', 'remind', 'adopt-' + w.id, T(`你采用了「${w.title}」。里面写到的测试还没真正跑过，要作为依据的话，先在测试台跑一遍。`, `You adopted “${w.title}”. The tests it mentions have not actually run. Run them on the test bench before you rely on them.`), { taskId: w.taskId, targetId: w.id });
  });
  const seen = a.noteSeen || (a.noteSeen = {});
  out.forEach(n => { if (!seen[n.key]) seen[n.key] = new Date().toISOString(); n.at = seen[n.key]; });
  return out.filter(n => !(a.acks || []).includes('note:' + n.key));
}

/** Observations for feedback and review: what is in the record, what was knowable then, why it matters. */
export function observations(a, E, scopeTaskId = null) {
  const f = facts(a, E); const out = [];
  const push = item => out.push(Object.assign({ refs: [], actions: [], taskId: null, basis: '', kind: '' }, item));
  const cfg = a.config || {}; const w = a.world;
  const policyTests = f.tests.filter(t => (t.citations || []).some(c => c.id === 'policy'));
  const stale = policyTests.filter(t => t.stale);
  const last = stale.at(-1);
  const contained = cfg.update === 'manual' || !(cfg.domains || []).includes('policy') || (cfg.fallback === 'human' && w.indexVersion < w.policyVersion);
  if (last && contained) push({ tone: 'good', title: T('发现旧答案后，你收住了风险', 'After seeing a stale answer, you contained the risk'), observed: T(`「${last.question}」拿到了旧版本的回答；之后政策问题不再由助手自动回答。`, `“${last.question}” got an answer from an old version; after that, policy questions were no longer answered automatically.`), basis: T(`测试时政策源已是 v${last.policyVersion}，助手引用的还是旧版本。`, `At test time the policy was v${last.policyVersion}; the assistant still cited an older one.`), why: T('员工不会按旧规定去报销。代价是政策问题要人工接住。', 'Staff will not claim under old rules. The cost is that people must handle policy questions.'), taskId: last.taskId, refs: [{ type: 'test', id: last.id, label: last.question }] });
  else if (last) push({ tone: 'check', title: T('有回答用的是旧版本', 'An answer used an old version'), observed: T(`「${last.question}」的回答引用的版本已经不是最新。`, `The answer to “${last.question}” cited a version that was no longer current.`), basis: T(`测试时政策源已是 v${last.policyVersion}${f.readPolicyNew ? '，你也打开过新版政策' : ''}。`, `At test time the policy was v${last.policyVersion}${f.readPolicyNew ? ', and you had opened the new version' : ''}.`), why: T('如果照这个配置上线，员工会拿到过期的答案。可以刷新索引后重测，或让政策问题转人工。', 'If this setup goes live, staff will get outdated answers. Refresh the index and test again, or route policy questions to people.'), taskId: last.taskId, actions: [{ label: T('同题重测', 'Run it again'), act: 'rerun', id: last.id }, { label: T('看试点设置', 'Open pilot settings'), act: 'config' }], refs: [{ type: 'test', id: last.id, label: last.question }] });
  if (f.policyEv) {
    const before = policyTests.filter(t => t.policyVersion < w.policyVersion);
    const after = policyTests.filter(t => t.policyVersion >= w.policyVersion);
    if (before.length && !after.length) push({ tone: 'check', title: T('政策变了，还没有重新测', 'The policy changed and has not been retested'), observed: T(`政策问答有 ${before.length} 次测试，都在政策更新之前。`, `${before.length} policy test(s), all before the update.`), basis: T(`那些测试当时的结果没有问题；变化发生${f.policyEv && a.eventTimes && a.eventTimes[f.policyEv.seq] ? '于' + when(a.eventTimes[f.policyEv.seq]) : '在之后'}。`, `Those results were fine at the time; the change came ${f.policyEv && a.eventTimes && a.eventTimes[f.policyEv.seq] ? when(a.eventTimes[f.policyEv.seq]) : 'afterwards'}.`), why: T('旧测试只说明旧条件下的表现，不能直接证明新条件下也成立。', 'Old tests describe the old conditions only.'), taskId: before.at(-1).taskId, actions: [{ label: T('用同一个问题重测', 'Ask the same question again'), act: 'rerun', id: before.at(-1).id }] });
  }
  if (f.decision) {
    const v = f.decision.draft ? { ...f.decision, ...f.decision.draft } : f.decision;
    const over = capNumbers(v.body, w.capacity);
    if (over.length) push({ tone: 'check', title: T('决定里的人数超出了容量', 'The decision exceeds capacity'), observed: T(`「${v.title}」写到 ${over[0]} 人，当前容量 ${w.capacity} 人。`, `“${v.title}” mentions ${over[0]} people; capacity is ${w.capacity}.`), basis: T('容量在委托和技术约束里都能看到。', 'Capacity is stated in the brief and the technical constraints.'), why: T('承诺超出容量，要么申请扩容并获批，要么缩小首批范围。', 'Either get more seats approved, or narrow the first group.'), taskId: f.decision.taskId, actions: [{ label: T('打开决定', 'Open the decision'), act: 'open-artifact', id: f.decision.id }, { label: T('申请资源', 'Request resources'), act: 'resources' }], refs: [{ type: 'artifact', id: f.decision.id, label: v.title }] });
    if (!f.talked('business') && !f.readIds.has('business')) push({ tone: 'unknown', title: T('看不到需求方面的依据', 'No evidence about user needs'), observed: T(`「${v.title}」选了范围，但记录里没有查看业务范围，也没有和 Mei 讨论。`, `“${v.title}” picks a scope, but the record shows no reading of the business scope and no talk with Mei.`), basis: T('需求材料一直可读；没读不代表你不了解。', 'The needs material was always available; not reading it does not mean you do not know.'), why: T('证据里看不到范围是按什么定的。可以引用依据，或者和 Mei 确认。', 'The record does not show what the scope rests on. Cite evidence or check with Mei.'), taskId: f.decision.taskId, actions: [{ label: T('看业务范围', 'Read the business scope'), act: 'material', id: 'business' }, { label: T('问 Mei', 'Ask Mei'), act: 'chat', role: 'business' }] });
  } else push({ tone: 'unknown', title: T('还没有成形的试点决定', 'No pilot decision yet'), observed: T('没有用途为“试点决定”且有内容的作品。', 'There is no piece of work marked “Pilot decision” with content.'), basis: T('其他作品是探索、计划或比较，不会被当作承诺。', 'Other work is exploration, planning or comparison and is not treated as a promise.'), why: T('交一份不完整的判断也可以——写清还不知道什么，本身就是信息。', 'An incomplete call is fine. Saying what you do not know is information too.'), actions: [{ label: T('写下现在的判断', 'Write the current call'), act: 'new-decision' }] });
  f.works.filter(x => x.source !== 'user' && x.adopted && !(x.evidence || []).some(ev => ev.type === 'test')).forEach(x => push({ tone: 'check', title: T('Agent 的作品还没关联测试', 'Agent work has no linked test'), observed: T(`你采用了 Agent 回传的「${x.title}」，它没有关联任何实际运行。`, `You adopted “${x.title}” from your agent; it is not linked to any real run.`), basis: T('采用说明你认可这份内容；回传里写的结论没有对应的运行记录。', 'Adopting shows you accept it; its claims have no matching runs.'), why: T('采用不等于成立。挑一条关键测试真正跑一次，再作为依据。', 'Adopting is not proving. Run one key test and cite it.'), taskId: x.taskId, actions: [{ label: T('去测试台', 'Open the test bench'), act: 'lab' }], refs: [{ type: 'artifact', id: x.id, label: x.title }] }));
  const seeds = new Set(['needs', 'policy', 'decision']);
  a.tasks.filter(t => !seeds.has(t.seed) && t.origin !== 'situation' && !t.parentTaskId).forEach(t => {
    const n = f.works.filter(x => x.taskId === t.id).length + f.tests.filter(r => r.taskId === t.id).length;
    if (n) push({ tone: 'good', kind: 'contribution', title: T('计划外的贡献：', 'Your own addition: ') + taskTitle(t), observed: T(`这件事不在最初的三件里，是你自己加的，下面有 ${n} 条作品或测试。`, `Not among the first three tasks; you added it, and it holds ${n} piece(s) of work or tests.`), basis: T('主动发现并处理没人交代的事，是这份工作的一部分。', 'Spotting work nobody assigned is part of the job.'), why: T('想一想：它改变了你后面的哪个判断？', 'Which later call did it change?'), taskId: t.id });
  });
  const approved = f.approvals.length;
  if (approved && cfg.update === 'realtime') push({ tone: 'good', title: T('资源到位后，你真的改了配置', 'Once resources arrived, you changed the setup'), observed: T('经理批准资源后，你用上了实时同步。', 'After the manager approved resources, you switched to real-time sync.'), basis: T('批准只改变条件；配置是你主动改的。', 'Approval only changes conditions; you changed the setup yourself.'), why: T('把“拿到资源”和“用上资源”分开，是很多人会漏的一步。', 'Getting resources and using them are different steps.') });
  return scopeTaskId ? out.filter(i => !i.taskId || i.taskId === scopeTaskId) : out;
}

/** Each colleague ranks the starting tasks from their own concerns. Never applied automatically. */
export function advice(a, role) {
  const plan = {
    manager: { order: ['decision', 'needs', 'policy'], why: T('我最关心你最后能承诺什么。先把决定的骨架写出来，缺什么再去补。', 'I care most about what you can promise. Sketch the decision first, then fill the gaps.') },
    business: { order: ['needs', 'policy', 'decision'], why: T('先弄清首批员工真正要问什么，不然测再多也可能测错方向。', 'Find out what first users actually ask, or you may test the wrong thing.') },
    technical: { order: ['policy', 'needs', 'decision'], why: T('政策会变，索引会滞后，这是最可能出事的地方。先测政策问答，再谈范围。', 'Policy changes and the index lags; that is where it breaks. Test policy answers first, then scope.') }
  }[role];
  const pr = ['first', 'next', 'later'];
  const items = plan.order.map((seed, i) => { const t = a.tasks.find(x => x.seed === seed); return t ? { taskId: t.id, priority: pr[i] } : null; }).filter(Boolean);
  const extra = a.tasks.filter(t => !items.some(i => i.taskId === t.id)).length;
  return { roleId: role, items, why: items.length ? plan.why + (extra ? T(' 你后来加的事，我没法替你排。', ' I cannot rank the tasks you added later.') : '') : T('我只能就最初的那几件事给建议。', 'I can only advise on the original tasks.'), name: NAME[role] };
}

/** Quick record checks for one piece of work: numbers and versions only. */
export function checks(a, E, work) {
  const out = []; const cfg = a.config || {}; const w = a.world;
  const cost = (cfg.workItems || []).reduce((n, k) => n + ({ scope: 1, fallback: 1, realtime: 5 }[k] || 0), 0) + (cfg.update === 'realtime' && !(cfg.workItems || []).includes('realtime') ? 5 : 0);
  if (work) out.push({ ok: true, text: T(`「${work.title}」v${work.revision} 已保存在本机`, `“${work.title}” v${work.revision} is saved on this device`) });
  if (a.backend && a.backend.configured) {
    out.push({ ok: cfg.participants <= w.capacity, text: T(`试点 ${cfg.participants} 人，容量 ${w.capacity} 人`, `${cfg.participants} users, capacity ${w.capacity}`) });
    out.push({ ok: cost <= w.devDays, text: T(`开发 ${cost} 人日，可用 ${w.devDays} 人日`, `${cost} person-days of work, ${w.devDays} available`) });
  } else out.push({ ok: false, text: T('还没有保存试点设置', 'Pilot settings not saved yet') });
  const latest = (a.tests || []).at(-1);
  if (!latest) out.push({ ok: false, text: T('还没有测试记录', 'No test runs yet') });
  else {
    out.push({ ok: true, text: T(`共 ${a.tests.length} 次测试，最近一次在配置 v${latest.configVersion} 下`, `${a.tests.length} test run(s); the latest used config v${latest.configVersion}`) });
    if (latest.configVersion !== a.configVersion || latest.policyVersion !== w.policyVersion) out.push({ ok: false, text: T('最近一次测试之后，配置或政策变过', 'Settings or policy changed after the latest test') });
  }
  return out;
}
