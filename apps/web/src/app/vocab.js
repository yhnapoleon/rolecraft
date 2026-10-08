// Product vocabulary in both languages. Server-owned text (materials, colleague
// replies, feedback reasons) is not translated here; it is shown as the backend sends it.
import { T, locale } from './i18n';

export const PRI = p => ({ first: T('先做', 'Do first'), next: T('随后', 'Up next'), later: T('暂放', 'Later') })[p] || p;
export const STATUS = s => ({ open: T('待处理', 'Open'), working: T('正在做', 'In progress'), done: T('已处理', 'Done') })[s] || s;
export const ROLE_TITLE = r => ({ manager: T('经理', 'Manager'), business: T('业务负责人', 'Business lead'), technical: T('技术负责人', 'Technical lead') })[r];
export const KNOWS = r => ({
  manager: T('目标、资源和先后顺序；能批准申请', 'Goals, resources and priorities; approves requests'),
  business: T('首批员工的需求、业务流程和政策', 'What first users need, how the business runs, policy'),
  technical: T('系统限制、索引和测试证据', 'System limits, indexing and test evidence')
})[r];
export const OPENER = r => ({
  manager: T('目标、资源、先做什么，都可以找经理谈。', 'Talk to the manager about goals, resources and what comes first.'),
  business: T('首批员工真正要问什么、政策怎么变，陈敏最清楚。', 'Chen Min knows what first users actually ask and how policy changes.'),
  technical: T('系统能做什么、索引多久更新、测试说明了什么，问技术负责人。', 'Ask the technical lead what the system can do, how fresh the index is and what a test shows.')
})[r];

export const CASE = id => ({
  pilot: {
    title: T('知识助手，准备好试点了吗？', 'Is the knowledge assistant ready for a pilot?'),
    quote: T('我希望第一批同事下周就能用上知识助手。先服务谁、开放什么、要什么保障，你来定方案，也告诉我什么情况下该暂停。', 'I want our first colleagues using the knowledge assistant next week. Who it serves first, what it covers and what safeguards it needs is your call. Tell me when we should pause, too.'),
    change: '', minutes: T('20–30 分钟', '20–30 min')
  },
  urgent: {
    title: T('试点提前到第 5 天', 'The pilot moves up to day 5'),
    quote: T('试点要提前到第 5 天启动。还是同一个试点：哪些能承诺、哪些先收着，你来定。', 'The pilot has to start by day 5. Same pilot: you decide what we can promise and what waits.'),
    change: T('上线从第 7 天提前到第 5 天', 'Launch moves from day 7 to day 5'), minutes: T('15–25 分钟', '15–25 min')
  },
  capacity: {
    title: T('容量只剩 15 人', 'Only 15 seats this time'),
    quote: T('平台这次只能给 15 个名额。先让谁用起来、开放什么，你来定。', 'The platform can only give us 15 seats this time. You decide who goes first and what we open.'),
    change: T('容量从 30 人降到 15 人', 'Capacity drops from 30 to 15 seats'), minutes: T('15–25 分钟', '15–25 min')
  }
})[id] || { title: id, quote: '', change: '', minutes: '' };

export const SEEDS = {
  needs: { zh: ['确认首批员工的使用需求', '业务团队希望首批员工查找办公流程和差旅政策；具体范围与优先级需要你判断。'], en: ['Find out what the first users need', 'The business team wants first users to look up office processes and travel policy. Scope and priority are yours to judge.'] },
  policy: { zh: ['回应政策问答的开放请求', '业务团队希望试点支持政策查询。请判断如何回应这个请求，以及需要哪些依据。'], en: ['Answer the request to open policy Q&A', 'The business team wants the pilot to answer policy questions. Decide how to respond and what evidence you need.'] },
  decision: { zh: ['形成可执行的试点决定', '经理希望了解可以承诺什么、需要什么条件，以及何时调整或暂停。'], en: ['Shape a pilot decision you can act on', 'Your manager wants to know what can be promised, under which conditions, and when to adjust or pause.'] }
};
export const SEED_KEYS = ['needs', 'policy', 'decision'];
const SITUATION = { zh: ['处理政策更新的影响', '差旅政策出了新版本。判断哪些测试、配置和承诺受影响。'], en: ['Handle the policy update', 'The travel policy has a new version. Work out which tests, settings and promises it affects.'] };
export const situationTask = () => ({ title: T(SITUATION.zh[0], SITUATION.en[0]), note: T(SITUATION.zh[1], SITUATION.en[1]) });
const pairOf = t => (t.seed && SEEDS[t.seed]) || (t.origin === 'situation' ? SITUATION : null);
const pick = (pair, i) => (locale() === 'en' ? pair.en[i] : pair.zh[i]);
/** Starting tasks follow the interface language until the user renames them. */
export const taskTitle = t => { const p = pairOf(t); return p && [p.zh[0], p.en[0]].includes(t.title) ? pick(p, 0) : t.title; };
export const taskNote = t => { const p = pairOf(t); return p && [p.zh[1], p.en[1]].includes(t.note) ? pick(p, 1) : (t.note || ''); };
export const seedText = key => pick(SEEDS[key], 0);

// Purposes are stored in the engine's Chinese values; only the label changes.
const PURPOSE_EN = { '探索笔记': 'Exploration note', '测试计划': 'Test plan', '方案比较': 'Option comparison', '试点决定': 'Pilot decision', '自由作品': 'Free-form' };
const V2_PURPOSES = { exploration: ['探索笔记','Exploration note'], test_plan: ['测试计划','Test plan'], option: ['方案比较','Option comparison'], commitment: ['试点决定','Pilot decision'], free_form: ['自由作品','Free-form'] };
export const purposeLabel = p => V2_PURPOSES[p] ? T(...V2_PURPOSES[p]) : (locale() === 'en' ? PURPOSE_EN[p] || p : p);
export const purposeFromLabel = label => Object.keys(PURPOSE_EN).find(k => k === label || PURPOSE_EN[k].toLowerCase() === String(label).toLowerCase()) || label;
export const INTENT_HINT = i => ({
  explore: T('探索：想到什么写什么', 'Exploring: write what you think'),
  option: T('备选：比较几种做法', 'Options: weigh a few approaches'),
  plan: T('计划：安排怎样验证', 'Plan: how you will check'),
  commit: T('决定：准备交付的结论', 'Decision: the call you intend to submit')
})[i];

export const UPDATE = k => ({ daily: T('每日索引', 'Daily index'), realtime: T('实时同步', 'Real-time sync'), manual: T('政策转人工', 'Route policy to people') })[k] || k;
export const FALLBACK = k => ({ none: T('暂不安排', 'None'), human: T('转人工确认', 'Hand off to a person') })[k] || k;
export const DOMAIN = k => ({ faq: T('办公 FAQ', 'Office FAQ'), policy: T('差旅政策', 'Travel policy'), onboarding: T('入职指引', 'Onboarding'), policy_travel: T('差旅政策', 'Travel policy'), policy_meal: T('餐费政策', 'Meal policy'), policy_leave: T('请假政策', 'Leave policy') })[k] || k;
export const WORK_ITEM = k => ({ scope: T('知识范围过滤', 'Scope filter'), fallback: T('人工入口', 'Human hand-off'), realtime: T('实时同步', 'Real-time sync') })[k] || k;
export const WORK_COST = { scope: 1, fallback: 1, realtime: 5 };

const MATERIAL_EN = { brief: 'Pilot brief', technical: 'Technical constraints', business: 'Business scope and acceptance', faq: 'Office FAQ', policy: 'Travel policy', approval_process: 'Change requests', tech_private: 'Tech lead notes' };
export const materialTitle = m => (locale() === 'en' ? MATERIAL_EN[m.id] || m.title : String(m.title || m.id).replace(/(初始版|更新版)$/, ''));

export const CRITERIA = {
  'R1.target': ['目标与用户范围', 'Goal and users'],
  'R1.metrics': ['成功指标', 'Success metrics'],
  'R2.support': ['事实与证据', 'Facts and evidence'],
  'R2.unknowns': ['未证实的结论', 'Unproven claims'],
  'R3.capacity': ['人数与容量', 'Participants and capacity'],
  'R3.resources': ['资源和期限', 'Resources and deadline'],
  'R4.functional_tests': ['实际功能测试', 'Functional tests'],
  'R4.staleness_test': ['政策变化测试', 'Policy change test'],
  'R5.impact': ['变化的影响', 'Impact of the change'],
  'R5.adjustment': ['方案与配置调整', 'Plan and settings adjusted'],
  'R6.consistency': ['方案与配置一致', 'Plan matches settings'],
  'R6.operations': ['观察与退出安排', 'Monitoring and exit']
};
export const criterionName = id => (CRITERIA[id] ? T(CRITERIA[id][0], CRITERIA[id][1]) : id);
export const LABEL = l => ({ MET: T('已满足', 'Met'), PARTIAL: T('部分满足', 'Partly met'), NOT_MET: T('未满足', 'Not met'), INSUFFICIENT: T('证据不足', 'Not enough evidence'), NOT_APPLICABLE: T('不适用', 'Not applicable') })[l] || l;

export const FIELDS = ['goal', 'owner', 'metrics', 'observation_window', 'exit_condition', 'rationale'];
export const FIELD = k => ({
  goal: T('业务目标与用户范围', 'Goal and users'),
  owner: T('负责人', 'Owner'),
  metrics: T('成功指标', 'Success metrics'),
  observation_window: T('观察窗口', 'Observation window'),
  exit_condition: T('退出条件', 'Exit conditions'),
  rationale: T('方案、作品与依据', 'Plan, work and evidence')
})[k] || k;
export const FIELD_HINT = k => ({
  goal: T('先服务谁，解决什么问题', 'Who it serves first, and what problem it solves'),
  owner: T('谁对试点负责', 'Who is accountable for the pilot'),
  metrics: T('怎样算有效，怎么统计', 'What counts as working, and how you will measure it'),
  observation_window: T('观察多久、何时复盘', 'How long you will watch, and when you review'),
  exit_condition: T('出现什么情况就调整或暂停', 'What makes you adjust or pause'),
  rationale: T('你的方案、关键作品和依据', 'Your plan, key work and the evidence behind it')
})[k] || '';

// Engine messages are Chinese; show an English equivalent when one is known.
const ERR_EN = {
  'JSON 格式无法解析，请检查格式或直接粘贴 Markdown': 'That JSON could not be read. Check the format or paste Markdown instead.',
  '事项不存在': 'That task no longer exists.',
  '作品正文超过 50000 字符': 'The text is longer than 50,000 characters.',
  '内容超过长度限制': 'The content is too long.',
  '证据不属于当前练习的可读材料或记录': 'That evidence is not part of this practice.',
  '试点人数须为 1–10000 的整数': 'Participants must be a whole number from 1 to 10,000.',
  '回传内容为空或超过长度限制': 'The returned content is empty or too long.',
  '作品名称为空或超过长度限制': 'The title is empty or too long.',
  '事项名称为空或超过长度限制': 'The task name is empty or too long.'
};
export const errText = err => {
  const m = (err && err.message) || String(err || '');
  return locale() === 'en' ? (ERR_EN[m] || m) : m;
};
