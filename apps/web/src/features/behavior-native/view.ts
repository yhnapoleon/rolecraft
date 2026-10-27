/** "Work review" on the review page: GET /sessions/{id}/behavior as HTML. It states
 * what the learner did and which reference way of working it is closest to; it never scores.
 * Placement is decided by BEHAVIOR_PLACEMENT; with the recognition layer off it never shows. */
import { copyText, type CopyTable, type Language } from '../results-native/localization';
import './behavior.css';
import { behaviorInsights } from './insights';
import { inspectorEntryHtml, methodsHtml } from '../recognition-native/record-inspector';
import { personName } from '../../app/people.js';

/** 262: a normal result-page entry; course categories remain in the lens. */
export const BEHAVIOR_PLACEMENT: 'lens' | 'default' = 'default';

export interface BehaviorRow {
  seq: number;
  symbol: string;
  phase?: string;
  event_id?: string;
  question?: string;
}
export interface Behavior {
  /** False when the recognition layer is off (the read then carries nothing else). */
  enabled?: boolean;
  sequence: BehaviorRow[];
  strategy: {
    nearest: string;
    distance: number;
    top3: { strategy: string; distance: number }[];
    reference?: { id: string; index: number; strategy: string; sequence: string[] };
    /** DTW warping path to the nearest reference only: own step i matched to reference step j. */
    path?: { i: number; j: number; cost: number }[];
  } | null;
  alignment: { missing: string[]; extra: string[]; swapped: string[][] };
  phases: { name: string; from_seq: number; to_seq: number }[];
  anomalies: { rule: string; score: number; at_seq: number }[];
  executor: { declared: string; predicted: string | null; confidence: number | null };
  recognizer: string;
  window?: { from_seq: number; to_seq: number; events?: number; turns?: number };
}

const zh = {
  title: '工作回放',
  lead: '沿着你做过的事，看看调查、测试和判断怎样衔接。',
  category: '机器学习 · 无监督 · 智能感知',
  method: 'DTW 对齐 / HMM 分阶段',
  steps: '本次可见动作',
  runnersUp: '其次接近：{names}',
  empty: '还没有可识别的步骤。',
  phases: '阶段',
  nearest: '选中的参考做法：{name}',
  noStrategy: '这一局按规则划分阶段，行为模型未加载，还认不出你接近哪种工作方式。',
  missing: '参考轨迹中更多的动作',
  extra: '本次记录中更多的动作',
  swapped: '顺序与参考相反',
  anomalies: '规则标出的步骤顺序',
  none: '规则没有标出步骤顺序。',
  executor: '做这些步骤的：{declared}',
  fallback: '规则回退',
  human: '你',
  own_agent: '你的 Agent',
  reference_agent: '参考 Agent',
  rule_policy_update_untested_submit: '情况变了（通知或索引刷新）之后，没有再测就提交了',
  rule_request_before_technical: '还没读技术材料就先申请了资源',
  rule_configured_before_approval: '申请还没批下来就按申请的数配置了',
  rule_repeated_submit_same_config: '配置没变就重复提交',
  s_thorough: '先读后问再测',
  s_request_first: '先申请后配置',
  s_test_heavy: '测试密集',
  s_rush: '较少动作后提交',
  s_ask_heavy: '多问同事',
  s_unread_request: '先申请再补资料',
  s_policy_untested: '变化后直接提交',
  s_revise_loop: '提交后修订',
  sym_read: '读 {x}',
  sym_read_title: '读《{x}》',
  sym_ask: '问 {x}',
  sym_test: '测试{x}',
  sym_request: '申请 {x}',
  sym_approved: '获批',
  sym_denied: '被拒',
  sym_counter: '还价',
  sym_configure: '配置',
  sym_refresh_index: '刷新索引',
  sym_submit: '提交',
  sym_revise: '修订',
  sym_event: '通知',
  t_normal: '普通问题',
  t_policy: '政策问题',
  t_oos: '范围外问题',
  r_capacity: '容量',
  r_resources: '资源',
  i_ask_limit: '上限',
  i_ask_resource: '资源',
  i_ask_process: '流程',
  i_seek_approval: '求批准',
  i_other: '其他',
} as const;
const en: Record<keyof typeof zh, string> = {
  title: 'Work review',
  lead: 'Follow the work you did: how investigation, testing and decisions fit together.',
  category: 'Machine learning · Unsupervised · Intelligent sensing',
  method: 'DTW alignment / HMM phases',
  steps: 'Actions visible in this session',
  runnersUp: 'Next closest: {names}',
  empty: 'No recognisable steps yet.',
  phases: 'Phases',
  nearest: 'Selected reference approach: {name}',
  noStrategy:
    'Phases are set by rules this time. The behaviour model isn’t loaded, so your way of working isn’t matched yet.',
  missing: 'More frequent in the reference',
  extra: 'More frequent in your record',
  swapped: 'Order opposite to the reference',
  anomalies: 'Step orders the rules flagged',
  none: 'The rules flagged no step order.',
  executor: 'These steps were taken by {declared}.',
  fallback: 'Rule fallback',
  human: 'you',
  own_agent: 'your agent',
  reference_agent: 'reference agent',
  rule_policy_update_untested_submit:
    'Submitted without testing again after things changed (a notice or an index refresh)',
  rule_request_before_technical: 'Requested resources before reading the technical material',
  rule_configured_before_approval:
    'Configured to the requested numbers before the request was approved',
  rule_repeated_submit_same_config: 'Submitted again with an unchanged configuration',
  s_thorough: 'Read, ask, then test',
  s_request_first: 'Request, then configure',
  s_test_heavy: 'Test-heavy',
  s_rush: 'Fewer actions before submitting',
  s_ask_heavy: 'Asks colleagues a lot',
  s_unread_request: 'Request, then read sources',
  s_policy_untested: 'Submit after a change',
  s_revise_loop: 'Revises after submitting',
  sym_read: 'read {x}',
  sym_read_title: 'Read “{x}”',
  sym_ask: 'ask {x}',
  sym_test: 'Tested {x}',
  sym_request: 'request {x}',
  sym_approved: 'approved',
  sym_denied: 'denied',
  sym_counter: 'counter-offer',
  sym_configure: 'Configured the pilot',
  sym_refresh_index: 'Refreshed the index',
  sym_submit: 'Submitted',
  sym_revise: 'Started a revision',
  sym_event: 'notice',
  t_normal: 'a regular question',
  t_policy: 'a policy question',
  t_oos: 'an out-of-scope question',
  r_capacity: 'capacity',
  r_resources: 'resources',
  i_ask_limit: 'a limit',
  i_ask_resource: 'resources',
  i_ask_process: 'the process',
  i_seek_approval: 'approval',
  i_other: 'other',
};
type Key = keyof typeof zh;
const COPY: CopyTable<Key> = { zh, en };
const t = (l: Language, k: Key, v: Record<string, string | number> = {}) => copyText(COPY, l, k, v);
const has = (k: string): k is Key => k in zh;

const esc = (v: string) =>
  v.replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c,
  );

// Colleagues by name (app/people.js), the same in both languages.
const ROLE = {
  zh: {
    supervisor: personName('supervisor'),
    tech_lead: personName('tech_lead'),
    business_lead: personName('business_lead'),
  },
  en: {
    supervisor: personName('supervisor'),
    tech_lead: personName('tech_lead'),
    business_lead: personName('business_lead'),
  },
} as const;

export function symbolLabel(symbol: string, l: Language, materialName?: (id: string) => string) {
  const [head, a, b] = symbol.split(':');
  if (head === 'ask') {
    const role = (ROLE[l] as Record<string, string>)[a] ?? (l === 'zh' ? '同事' : 'a colleague');
    const subjects: Record<string, [string, string]> = {
      ask_limit: ['限制', 'limits'], ask_resource: ['资源', 'resources'],
      ask_process: ['流程', 'the process'], seek_approval: ['批准', 'approval'],
    };
    const subject = subjects[b];
    return l === 'zh' ? subject ? `向 ${role} 询问${subject[0]}` : `向 ${role} 提问` : subject ? `Asked ${role} about ${subject[1]}` : `Asked ${role} a question`;
  }
  if (head === 'read') {
    const name = a && materialName ? materialName(a) : '';
    // A step chip names the document by its short title ("经理委托", not the whole heading).
    const short = name.split(/[：:]/)[0].trim() || name;
    return name && name !== a
      ? t(l, 'sym_read_title', { x: short })
      : l === 'zh'
        ? '读了一份资料'
        : 'Read a source';
  }
  if (head === 'test')
    return t(l, 'sym_test', { x: a && has(`t_${a}`) ? t(l, `t_${a}` as Key) : (a ?? '') });
  if (head === 'request')
    return t(l, 'sym_request', { x: a && has(`r_${a}`) ? t(l, `r_${a}` as Key) : (a ?? '') });
  if (['approved', 'denied', 'counter', 'event'].includes(head)) return t(l, `sym_${head}` as Key);
  const key = `sym_${head}`;
  return has(key) ? t(l, key) : l === 'zh' ? '一条未命名动作' : 'An unnamed action';
}

export const strategyName = (s: string, l: Language) => (has(`s_${s}`) ? t(l, `s_${s}` as Key) : s);

export type BehaviorView = {
  title: string;
  lead: string;
  /** Course category, method and (when weights were missing) the rule fallback; lens only. */
  categories: { text: string; fallback: boolean }[];
  empty: string | null;
  phasesLabel: string;
  /** Recorded phase runs; label fitting happens after layout using the actual font. */
  phases: { name: string; steps: number; style: number; from: number; to: number }[];
  legend: { name: string; style: number }[];
  stepsLabel: string;
  steps: string[];
  nearest: string | null;
  runnersUp: string | null;
  noStrategy: string | null;
  alignment: { label: string; items: string[] }[];
  orderLabel: string;
  order: string[];
  orderNone: string | null;
  executor: string;
};

/** The four phases in their working order; each has one neutral style (0–3). */
const PHASE_ORDER: Record<string, number> = {
  探索: 0,
  测试: 1,
  决策: 2,
  调整: 3,
  explore: 0,
  test: 1,
  decide: 2,
  adjust: 3,
};
const phaseName = (name: string, l: Language) => {
  const index = PHASE_ORDER[name];
  return (
    (l === 'zh'
      ? ['探索', '测试', '决策', '调整']
      : ['Exploration', 'Testing', 'Decision', 'Revision'])[index] ?? name
  );
};
/** Measure the actual font outside this pure fitting decision. */
export const phaseLabelFits = (segmentWidth: number, textWidth: number) =>
  segmentWidth >= textWidth + 12;
const counts = (symbols: string[]) => [
  ...symbols.reduce(
    (map, symbol) => map.set(symbol, (map.get(symbol) ?? 0) + 1),
    new Map<string, number>(),
  ),
];

function phaseRuns(data: Behavior, l: Language) {
  const seen: string[] = [];
  const styleOf = (name: string) => {
    if (name in PHASE_ORDER) return PHASE_ORDER[name];
    if (!seen.includes(name)) seen.push(name);
    return seen.indexOf(name) % 4;
  };
  const phases: BehaviorView['phases'] = [];
  data.sequence.forEach((row, index) => {
    if (
      !row.phase ||
      !data.phases.some((p) => p.name === row.phase && row.seq >= p.from_seq && row.seq <= p.to_seq)
    )
      return;
    const name = phaseName(row.phase, l),
      previous = phases.at(-1);
    if (previous && previous.name === name && previous.to === index - 1) {
      previous.steps++;
      previous.to = index;
    } else phases.push({ name, steps: 1, style: styleOf(row.phase), from: index, to: index });
  });
  const legend = [
    ...new Map(phases.map((p) => [p.name, { name: p.name, style: p.style }])).values(),
  ].sort((a, b) => a.style - b.style);
  return { phases, legend };
}

/** What the section says, as data; null when it does not show (layer off, or placement). */
export function behaviorView(
  data: Behavior | { enabled: false } | null | undefined,
  l: Language,
  options: { lens?: boolean; materialName?: (id: string) => string; stepsOpen?: boolean } = {},
): BehaviorView | null {
  if (!data || data.enabled === false || !('sequence' in data)) return null;
  const lens = !!options.lens;

  const fallback = data.recognizer.endsWith('@rule-fallback');
  const label = (symbol: string) => symbolLabel(symbol, l, options.materialName);
  const strategy = data.strategy;
  return {
    title: t(l, 'title'),
    lead: t(l, 'lead'),
    categories: lens
      ? [
          { text: t(l, 'category'), fallback: false },
          { text: t(l, 'method'), fallback: false },
          ...(fallback ? [{ text: t(l, 'fallback'), fallback: true }] : []),
        ]
      : [],
    empty: data.sequence.length ? null : t(l, 'empty'),
    phasesLabel: `${t(l, 'phases')} · ${data.sequence.length}`,
    ...phaseRuns(data, l),
    stepsLabel: t(l, 'steps'),
    steps: data.sequence.map((r) => label(r.symbol)),
    nearest: strategy
      ? strategy.top3.filter((s) => s.distance === strategy.distance).length > 1 ||
        strategy.top3.some(
          (s) => s.strategy !== strategy.nearest && s.distance === strategy.distance,
        )
        ? (l === 'zh' ? '同样接近：' : 'Equally close: ') +
          [
            ...new Set([
              strategy.nearest,
              ...strategy.top3
                .filter((s) => s.distance === strategy.distance)
                .map((s) => s.strategy),
            ]),
          ]
            .map((s) => strategyName(s, l))
            .join(l === 'zh' ? '、' : ', ')
        : t(l, 'nearest', { name: strategyName(strategy.nearest, l) })
      : null,
    runnersUp: strategy?.top3.some((s) => s.distance > strategy.distance)
      ? t(l, 'runnersUp', {
          names: counts(
            strategy.top3.filter((s) => s.distance > strategy.distance).map((s) => s.strategy),
          )
            .map(
              ([name, count]) =>
                `${strategyName(name, l)}${count > 1 ? (l === 'zh' ? `（${count} 条参考）` : ` (${count} references)`) : ''}`,
            )
            .join(l === 'zh' ? '、' : ', '),
        })
      : null,
    noStrategy: strategy ? null : t(l, 'noStrategy'),
    alignment: [
      { label: t(l, 'missing'), items: data.alignment.missing.map(label) },
      { label: t(l, 'extra'), items: data.alignment.extra.map(label) },
      {
        label: t(l, 'swapped'),
        items: data.alignment.swapped.map(([a, b]) => `${label(a)} ⇄ ${label(b)}`),
      },
    ].filter((group) => group.items.length),
    orderLabel: t(l, 'anomalies'),
    order: data.anomalies.map((a) =>
      has(`rule_${a.rule}`) ? t(l, `rule_${a.rule}` as Key) : a.rule,
    ),
    orderNone: data.anomalies.length ? null : t(l, 'none'),
    executor: t(l, 'executor', {
      declared: has(data.executor.declared)
        ? t(l, data.executor.declared as Key)
        : data.executor.declared,
    }),
  };
}

/** One response, two ordered tracks. Alignment is a count/order summary, not a DTW path. */
/** The recorded DTW path as one row per matched pair: line style and words carry the cost
 * (0 same action, 0.5 same kind on another object, 1 different action). A repeated own step
 * means the reference did more there; a repeated reference step means you did (dtw_path).
 * Empty when there is no path, no reference, or the path does not fit both sequences. */
export function alignmentHtml(
  data: Behavior,
  l: Language,
  label: (symbol: string) => string,
) {
  const say = (zh: string, en: string) => (l === 'zh' ? zh : en);
  const path = data.strategy?.path,
    reference = data.strategy?.reference?.sequence;
  if (!Array.isArray(path) || !path.length || !reference) return '';
  const fits = path.every(
    (p, k) =>
      Number.isInteger(p.i) &&
      Number.isInteger(p.j) &&
      p.i >= 0 &&
      p.j >= 0 &&
      p.i < data.sequence.length &&
      p.j < reference.length &&
      [0, 0.5, 1].includes(p.cost) &&
      (k === 0 || (p.i - path[k - 1].i <= 1 && p.j - path[k - 1].j <= 1 && p.i + p.j > path[k - 1].i + path[k - 1].j)),
  );
  if (!fits) return `<p>${say('对齐路径和动作记录对不上，这里不画出。', 'The alignment path does not match the action records, so it is not drawn.')}</p>`;
  const cost = {
    0: say('同一动作', 'Same action'),
    0.5: say('同类动作，对象不同', 'Same kind, different object'),
    1: say('不同', 'Different'),
  } as Record<number, string>;
  const step = (n: number, symbol: string) =>
    `<span class="br-step-no">${String(n + 1).padStart(2, '0')}</span><span>${esc(label(symbol))}</span>`;
  const rows = path
    .map((p, k) => {
      const previous = path[k - 1];
      const repeat = previous && previous.i === p.i ? 'reference' : previous && previous.j === p.j ? 'own' : '';
      const extra = repeat === 'reference' ? say('参考多做了', 'Reference did more') : repeat === 'own' ? say('你多做了', 'You did more') : '';
      return `<li class="br-align-row" data-cost="${p.cost}"${repeat ? ` data-repeat="${repeat}"` : ''}><span class="br-align-own"${repeat === 'reference' ? ' data-again="true"' : ''}>${step(p.i, data.sequence[p.i].symbol)}</span><span class="br-align-link" aria-hidden="true"></span><span class="br-align-ref"${repeat === 'own' ? ' data-again="true"' : ''}><span class="br-align-to">${say('参考', 'Reference')}</span>${step(p.j, reference[p.j])}</span><span class="br-align-note"><span class="br-align-cost">${cost[p.cost]}</span>${extra ? `<span class="br-align-extra">${extra}</span>` : ''}</span></li>`;
    })
    .join('');
  const differ = path.filter((p) => p.cost === 1).length;
  const caption = say(
    `本局与参考的逐步对应：${path.length} 对，其中 ${differ} 对动作不同`,
    `Step-by-step match with the reference: ${path.length} ${path.length === 1 ? 'pair' : 'pairs'}, ${differ} with different actions`,
  );
  return `<figure class="br-align"><figcaption>${caption}</figcaption><p class="br-align-key">${say('DTW 对齐路径，只对最接近的那条参考。实线：同一动作；虚线：同类动作、对象不同；粗线并标「不同」：动作不同。', 'DTW alignment path, for the nearest reference only. Solid line: same action; dashed: same kind, different object; heavy line marked “Different”: different actions.')}</p><div class="br-align-cols" aria-hidden="true"><span>${say('本局', 'This session')}</span><span></span><span>${say('参考', 'Reference')}</span><span></span></div><ol class="br-align-rows" tabindex="0" aria-label="${esc(caption)}">${rows}</ol></figure>`;
}

export function behaviorHtml(
  data: Behavior | { enabled: false } | null | undefined,
  l: Language,
  options: { lens?: boolean; materialName?: (id: string) => string; stepsOpen?: boolean } = {},
) {
  const say = (zh: string, en: string) => (l === 'zh' ? zh : en);
  if (data?.enabled === false)
    return `<details><summary>${say('这次未生成工作回放', 'No work review was generated this time')}</summary><p>${say('本次未启用过程识别。', 'Work-process recognition was not enabled.')}</p></details>`;
  const view = behaviorView(data, l, options);
  if (!view || !data || !('sequence' in data)) return '';
  const fallback = data.recognizer.endsWith('@rule-fallback'),
    label = (s: string) => symbolLabel(s, l, options.materialName);
  const { valid, suggestions } = behaviorInsights(data, l);
  const symbols = data.sequence.map((r) => r.symbol),
    reference = data.strategy?.reference;
  const groups: { symbols: string[]; start: number }[] = [];
  symbols.forEach((s, i) => {
    const last = groups.at(-1);
    if (last && s.startsWith('read:') && last.symbols.every((x) => x.startsWith('read:')))
      last.symbols.push(s);
    else groups.push({ symbols: [s], start: i });
  });
  const actionKinds: [string, string, string, string][] = [
    ['read', '阅读', 'read', 'reads'], ['ask', '提问', 'question', 'questions'], ['test', '测试', 'test', 'tests'],
    ['request', '申请', 'request', 'requests'], ['configure', '配置', 'configuration', 'configurations'],
    ['submit', '提交', 'submission', 'submissions'], ['revise', '修订', 'revision', 'revisions'],
  ];
  const headline = actionKinds.map(([kind, zh, singular, plural]) => {
    const n = symbols.filter(s => s.split(':')[0] === kind).length;
    return n ? say(`${zh} ${n} 次`, `${n} ${n === 1 ? singular : plural}`) : '';
  }).filter(Boolean).join(' · ');
  const head = `<header class="br-head"><div><h2>${say('工作回放', 'Work review')}</h2><p>${esc(headline || say('本次读取还没有已命名的动作。', 'No named actions were returned.'))}</p></div><span class="br-total">${symbols.length}<small>${say('个可见动作', symbols.length === 1 ? 'visible action' : 'visible actions')}</small></span></header>`;
  if (!symbols.length) return head;
  const bar = `<rc-phase-timeline><div class="rc-phasebar" aria-hidden="true">${view.phases.map((p) => `<span class="rc-phase" data-style="${p.style}" style="flex:${p.steps}"></span>`).join('')}</div><div class="rc-phase-labels">${view.phases.map((p, i) => `<button type="button" class="rc-phase-label" style="--phase-steps:${p.steps}" data-from="${p.from}" data-to="${p.to}" data-style="${p.style}" aria-pressed="false" aria-label="${i + 1}. ${esc(p.name)}"><span class="rc-phase-name">${esc(p.name)}</span><span class="rc-phase-number" aria-hidden="true">${i + 1}</span></button>`).join('')}</div></rc-phase-timeline>`;
  const legend = `<div class="rc-phase-legend">${view.phases.map((p, i) => `<span><i data-style="${p.style}" aria-hidden="true"></i>${i + 1} · ${esc(p.name)}</span>`).join('')}</div>`;
  const steps = (items: string[], ref = false, start = 0) =>
    `<ol class="br-track">${items
      .map((s, i) => {
        const pos = i + start,
          row = data.sequence[pos];
        return `<li><details class="br-action"${ref ? '' : ` data-seq="${pos}" data-phase="${PHASE_ORDER[row.phase ?? ''] ?? ''}"`}><summary><span class="br-step-no">${String(pos + 1).padStart(2, '0')}</span><span>${esc(label(s))}</span><span class="br-action-plus" aria-hidden="true">+</span></summary><p>${ref ? say('参考做法里的动作', 'Action in the reference approach') : (row.phase ? phaseName(row.phase, l) : say('阶段未记录', 'Phase not recorded'))}</p>${!ref && row.question ? `<blockquote>${esc(row.question)}</blockquote>` : ''}</details></li>`;
      })
      .join('')}</ol>`;
  const own = groups
    .map((g) =>
      g.symbols.length > 1
        ? `<details class="br-read-group"><summary>${say(`读了 ${g.symbols.length} 份资料`, `Read ${g.symbols.length} sources`)} <span>${say('展开资料记录', 'See which sources')} +</span></summary>${steps(g.symbols, false, g.start)}</details>`
        : steps(g.symbols, false, g.start),
    )
    .join('');
  const ownCounts = new Map(counts(symbols));
  const refCounts = reference ? new Map(counts(reference.sequence)) : null;
  const differences = [
    ...[...new Set([...data.alignment.missing, ...data.alignment.extra])].map(s => {
      const ownCount = ownCounts.get(s) ?? 0;
      const refCount = refCounts?.get(s) ?? 0;
      const object = s === 'test:normal' ? say('日常问题测试', 'Everyday-question tests') : label(s);
      return refCounts
        ? say(`${object}：本次 ${ownCount} 次，参考 ${refCount} 次`, `${object}: this record ${ownCount} ${ownCount === 1 ? 'time' : 'times'}, reference ${refCount} ${refCount === 1 ? 'time' : 'times'}`)
        : say(`${object}：本次 ${ownCount} 次；参考动作记录未提供，无法核对次数。`, `${object}: this record ${ownCount} ${ownCount === 1 ? 'time' : 'times'}; reference actions were not provided, so their count cannot be checked.`);
    }),
    ...data.alignment.swapped.map(([a, b]) =>
      say(
        `这两类动作的首次出现顺序不同：${label(a)}／${label(b)}`,
        `These actions first appeared in a different order: ${label(a)} / ${label(b)}`,
      ),
    ),
  ];
  const referenceHtml = `<details class="br-reference"><summary>${say('查看参考做法与全部差异', 'Explore the reference and all differences')}</summary><p>${esc(view.nearest ?? say('这次没有可对照的参考做法。', 'No reference approach is available for this record.'))}</p>${reference ? steps(reference.sequence, true) : `<p>${say('这次没有可对照的参考做法。', 'No reference approach is available for this record.')}</p>`}${!valid && reference ? `<p>${say('差异记录待核对', 'Difference records need checking')}</p>` : ''}<ul>${differences.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></details>`;
  const ideas = `<section class="br-ideas"><h3>${say('换个做法看看', 'Something to try next time')}</h3><p class="br-method">${say('参考做法来自预设脚本，供你挑选，不代表最佳路线。', 'These scripted examples offer ideas to try. They are not a best-practice benchmark.')}</p>${suggestions.map((s) => `<article class="br-idea"><h4>${esc(s.title)}</h4><p>${esc(s.observation)}</p><p>${esc(s.practice)}</p>${s.action === 'test' ? `<a class="ec-tech" href="#/bench">${esc(s.label ?? '')} →</a>` : s.action ? `<button type="button" class="ec-tech" data-action="chat" data-role="${s.action}">${esc(s.label ?? '')} →</button>` : ''}</article>`).join('')}${!suggestions.length ? `<p>${say(!data.window ? '本次未记录起止范围，先保留动作事实。' : !valid && reference ? '差异记录待核对，先保留两份动作记录。' : !reference ? '这次没有可对照的参考做法。' : '当前没有可展示的重点练法。', !data.window ? 'The covered range was not recorded; the actions remain available.' : !valid && reference ? 'Difference records need checking; both action lists remain available.' : !reference ? 'No reference approach is available for this record.' : 'There are no highlighted suggestions for this record.')}</p>` : ''}${referenceHtml}</section>`;
  const window = data.window
    ? say(
        `读取范围：记录 ${data.window.from_seq}–${data.window.to_seq}${typeof data.window.events === 'number' ? `，${data.window.events} 条事件` : ''}${typeof data.window.turns === 'number' ? `，${data.window.turns} 次提问` : ''}。`,
        `Read window: records ${data.window.from_seq}–${data.window.to_seq}${typeof data.window.events === 'number' ? `, ${data.window.events} ${data.window.events === 1 ? 'event' : 'events'}` : ''}${typeof data.window.turns === 'number' ? `, ${data.window.turns} ${data.window.turns === 1 ? 'question' : 'questions'}` : ''}.`,
      )
    : say(
        '本次读取的动作；起止范围未记录。',
        'Actions in this response; the read window was not recorded.',
      );
  const eventCount = data.window?.events;
  const turnCount = data.window?.turns;
  const origin = say(`本次可见的 ${symbols.length} 个动作`, `${symbols.length} visible ${symbols.length === 1 ? 'action' : 'actions'} in this record`) +
    (typeof eventCount === 'number' && typeof turnCount === 'number'
      ? say(`，来自 ${eventCount} 条操作记录和 ${turnCount} 次提问。`, `, from ${eventCount} operation ${eventCount === 1 ? 'record' : 'records'} and ${turnCount} ${turnCount === 1 ? 'question' : 'questions'}.`)
      : say('；操作记录和提问的数量未完整记录。', '; operation and question counts were not fully recorded.'));
  const record = `<p>${fallback ? say('阶段按动作类型整理；本次为规则回退。', 'Phases were grouped by action type using a rule fallback.') : data.recognizer ? say('本次用 HMM 解码工作阶段，用 DTW 匹配参考做法。', 'HMM decoded work phases; DTW matched reference approaches.') : say('实际方法未记录。', 'The actual method was not recorded.')}</p><p>${say('阶段是模型对上下文的划分，动作名称保持原样。', 'Phases interpret the action context; action names stay unchanged.')}</p><table class="jc-table"><caption>${say('返回的参考记录', 'Returned reference records')}</caption><tbody>${(data.strategy?.top3 ?? []).map((s) => `<tr><th>${esc(strategyName(s.strategy, l))}</th><td>${Number.isFinite(s.distance) ? s.distance.toFixed(3) : esc(String(s.distance))}</td></tr>`).join('')}</tbody></table><details><summary>${say('查看距离完整精度', 'View full distance precision')}</summary><ol>${(data.strategy?.top3 ?? []).map(s => `<li>${esc(strategyName(s.strategy, l))} · ${esc(String(s.distance))}</li>`).join('')}</ol></details><p>${say('距离越小，动作序列越接近；距离不是概率。', 'A smaller distance means a closer action sequence; it is not a probability.')}</p>${alignmentHtml(data, l, label) || `<p>${say('只记录了动作数量和首次顺序差异，没有逐步对应记录。', 'Only action counts and first-occurrence differences were recorded, not a step-by-step alignment.')}</p>`}<p>${window}</p><p>${say('执行来源声明', 'Declared execution source')}：${esc(({human:say('本人','the learner'),own_agent:say('本人 Agent','own Agent'),reference_agent:say('参考 Agent','reference Agent')} as Record<string,string>)[data.executor.declared] ?? say('未说明','not recorded'))}</p><details><summary>${say('查看原始差异记录', 'View raw difference records')}</summary><pre>${esc(JSON.stringify(data.alignment, null, 2))}</pre></details><details><summary>${say('查看原始动作记录','View recorded action symbols')}</summary><ol>${data.sequence.map(row=>`<li>${say('记录序号', 'Record sequence')} ${row.seq} · ${esc(row.symbol)}${row.question?`<blockquote>${esc(row.question)}</blockquote>`:''}</li>`).join('')}</ol></details>${data.anomalies.length ? `<details><summary>${say('查看规则记录', 'View rule records')}</summary><ul>${data.anomalies.map((a) => `<li>${esc(a.rule)} · ${a.at_seq} · ${a.score}</li>`).join('')}</ul></details>` : ''}`;
  return `${head}<details class="rc-behavior__steps"${options.stepsOpen ? ' open' : ''}><summary>${say('展开工作回放', 'Explore the work review')}</summary><div class="br-content"><section class="br-phases" aria-label="${fallback ? say('按动作类型整理的阶段', 'Phases grouped by action type') : say('识别出的工作阶段', 'Recognised work phases')}"><p class="br-method">${say('按动作顺序，不表示耗时；点阶段查看动作。', 'Action order, not duration. Select a phase.')}</p>${bar}${legend}</section><div class="br-layout">${ideas}<section class="br-own"><h3>${say('这次做过的事', 'Your recorded actions')}</h3>${own}</section></div><footer><p class="rc-behavior__origin">${origin} ${say('范围之外做过什么，单凭这份记录无法判断。', 'This record cannot tell us what happened beyond the visible actions.')}</p>${inspectorEntryHtml(say('阶段来自识别，练法来自参考对照', 'Recognised phases, suggestions from reference comparisons'), record, methodsHtml(l, 'behavior'), l)}</footer></div></details>`;
}

if (typeof customElements !== 'undefined' && !customElements.get('rc-phase-timeline')) {
  customElements.define(
    'rc-phase-timeline',
    class extends HTMLElement {
      resize?: ResizeObserver;
      connectedCallback() {
        queueMicrotask(() => {
          if (!this.isConnected) return;
          const buttons = [...this.querySelectorAll<HTMLButtonElement>('.rc-phase-label')];
          const segments = [...this.querySelectorAll<HTMLElement>('.rc-phase')];
          const measureLayout = () => {
            if (!this.clientWidth) return;
            const compact = segments.some((e) => e.getBoundingClientRect().width < 44);
            this.dataset.compact = String(compact);
            buttons.forEach((button, i) => {
              const name = button.querySelector<HTMLElement>('.rc-phase-name');
              if (!name) return;
              button.dataset.labelled = String(
                !compact &&
                  phaseLabelFits(segments[i].getBoundingClientRect().width, name.scrollWidth),
              );
            });
          };
          for (const button of buttons)
            button.onclick = () => {
              const selected = button.getAttribute('aria-pressed') !== 'true';
              buttons.forEach((b) => {
                b.setAttribute('aria-pressed', String(selected && b === button));
              });
              const scope = this.closest('.br-content');
              scope?.querySelectorAll<HTMLElement>('.br-action[data-seq]').forEach((action) => {
                const seq = Number(action.dataset.seq);
                action.dataset.selected = String(
                  selected &&
                    seq >= Number(button.dataset.from) &&
                    seq <= Number(button.dataset.to) &&
                    action.dataset.phase === button.dataset.style,
                );
                if (action.dataset.selected === 'true') {
                  const group = action.closest<HTMLDetailsElement>('.br-read-group');
                  if (group) group.open = true;
                }
              });
            };
          measureLayout();
          this.ownerDocument.fonts?.ready.then(() => {
            if (this.isConnected) measureLayout();
          });
          if (typeof ResizeObserver !== 'undefined') {
            this.resize = new ResizeObserver(measureLayout);
            this.resize.observe(this);
          }
        });
      }
      disconnectedCallback() {
        this.resize?.disconnect();
      }
    },
  );
}
