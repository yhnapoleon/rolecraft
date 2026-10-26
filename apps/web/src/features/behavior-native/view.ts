/** "Look back at your work" on the review page: GET /sessions/{id}/behavior as HTML. It states
 * what the learner did and which reference way of working it is closest to; it never scores.
 * Placement is decided by BEHAVIOR_PLACEMENT; with the recognition layer off it never shows. */
import { copyText, type CopyTable, type Language } from '../results-native/localization';
import './behavior.css';
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
  } | null;
  alignment: { missing: string[]; extra: string[]; swapped: string[][] };
  phases: { name: string; from_seq: number; to_seq: number }[];
  anomalies: { rule: string; score: number; at_seq: number }[];
  executor: { declared: string; predicted: string | null; confidence: number | null };
  recognizer: string;
  window?: { from_seq: number; to_seq: number; events?: number; turns?: number };
}

const zh = {
  title: '回看工作过程',
  lead: '沿着你做过的事，看看调查、测试和判断怎样衔接。',
  category: '机器学习 · 无监督 · 智能感知',
  method: 'DTW 对齐 / HMM 分阶段',
  steps: '本次可见动作',
  runnersUp: '其次接近：{names}',
  empty: '还没有可识别的步骤。',
  phases: '阶段',
  nearest: '最接近的工作方式：{name}',
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
  s_rush: '赶工直交',
  s_ask_heavy: '多问同事',
  s_unread_request: '未读先申请',
  s_policy_untested: '变化后未复测',
  s_revise_loop: '提交后修订',
  sym_read: '读 {x}',
  sym_read_title: '读《{x}》',
  sym_ask: '问 {x}',
  sym_test: '测 {x}',
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
  title: 'Look back at your work',
  lead: 'Follow the work you did: how investigation, testing and decisions fit together.',
  category: 'Machine learning · Unsupervised · Intelligent sensing',
  method: 'DTW alignment / HMM phases',
  steps: 'Actions visible in this session',
  runnersUp: 'Next closest: {names}',
  empty: 'No recognisable steps yet.',
  phases: 'Phases',
  nearest: 'Closest way of working: {name}',
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
  s_rush: 'Rushed submission',
  s_ask_heavy: 'Asks colleagues a lot',
  s_unread_request: 'Requests before reading',
  s_policy_untested: 'No retest after a change',
  s_revise_loop: 'Revises after submitting',
  sym_read: 'read {x}',
  sym_read_title: 'read “{x}”',
  sym_ask: 'ask {x}',
  sym_test: 'test {x}',
  sym_request: 'request {x}',
  sym_approved: 'approved',
  sym_denied: 'denied',
  sym_counter: 'counter-offer',
  sym_configure: 'configure',
  sym_refresh_index: 'refresh index',
  sym_submit: 'submit',
  sym_revise: 'revise',
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
    const role = (ROLE[l] as Record<string, string>)[a] ?? a;
    const intent =
      b && has(`i_${b}`) ? t(l, `i_${b}` as Key) : b?.replace('ask_', '').replace('seek_', '');
    return t(l, 'sym_ask', { x: role }) + (intent ? ` · ${intent}` : '');
  }
  if (head === 'read') {
    const name = a && materialName ? materialName(a) : '';
    // A step chip names the document by its short title ("经理委托", not the whole heading).
    const short = name.split(/[：:]/)[0].trim() || name;
    return name && name !== a
      ? t(l, 'sym_read_title', { x: short })
      : t(l, 'sym_read', { x: a ?? '' });
  }
  if (head === 'test')
    return t(l, 'sym_test', { x: a && has(`t_${a}`) ? t(l, `t_${a}` as Key) : (a ?? '') });
  if (head === 'request')
    return t(l, 'sym_request', { x: a && has(`r_${a}`) ? t(l, `r_${a}` as Key) : (a ?? '') });
  if (['approved', 'denied', 'counter', 'event'].includes(head)) return t(l, `sym_${head}` as Key);
  const key = `sym_${head}`;
  return has(key) ? t(l, key) : symbol;
}

export const strategyName = (s: string, l: Language) => (has(`s_${s}`) ? t(l, `s_${s}` as Key) : s);

export type BehaviorView = {
  title: string;
  lead: string;
  /** Course category, method and (when weights were missing) the rule fallback; lens only. */
  categories: { text: string; fallback: boolean }[];
  empty: string | null;
  phasesLabel: string;
  /** Each run of one phase: its share of the bar, its neutral style, and whether its name fits
   * inside it (narrow runs stay unlabelled; the legend under the bar names every phase). */
  phases: { name: string; steps: number; style: number; labelled: boolean }[];
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
/** Width the bar can count on in the review side column (narrowest layout, inside padding). */
const BAR_WIDTH = 280;
const labelWidth = (name: string, l: Language) => name.length * (l === 'zh' ? 11 : 6.4) + 12;

function phaseRuns(data: Behavior, l: Language) {
  const total = Math.max(1, data.sequence.length);
  const seen: string[] = [];
  const styleOf = (name: string) => {
    if (name in PHASE_ORDER) return PHASE_ORDER[name];
    if (!seen.includes(name)) seen.push(name);
    return seen.indexOf(name) % 4;
  };
  const phases = data.phases.map((p) => {
    const steps =
      data.sequence.filter((r) => r.seq >= p.from_seq && r.seq <= p.to_seq && r.phase === p.name)
        .length || 1;
    return {
      name: p.name,
      steps,
      style: styleOf(p.name),
      labelled: (steps / total) * BAR_WIDTH >= labelWidth(p.name, l),
    };
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
      ? strategy.top3.some(
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
    runnersUp:
      strategy && strategy.top3.length > 1
        ? t(l, 'runnersUp', {
            names: strategy.top3
              .filter((s) => s.distance > strategy.distance)
              .map((s) => strategyName(s.strategy, l))
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
export function behaviorHtml(
  data: Behavior | { enabled: false } | null | undefined,
  l: Language,
  options: { lens?: boolean; materialName?: (id: string) => string; stepsOpen?: boolean } = {},
) {
  const view = behaviorView(data, l, options);
  if (!view || !data || !('sequence' in data)) return '';
  const say = (zh: string, en: string) => (l === 'zh' ? zh : en);
  const fallback = data.recognizer.endsWith('@rule-fallback');
  const label = (symbol: string) => symbolLabel(symbol, l, options.materialName);
  const cats = view.categories
    .map(
      (c) => `<span class="rc-cat"${c.fallback ? ' data-fallback=""' : ''}>${esc(c.text)}</span>`,
    )
    .join('');
  const head = `<header class="br-head"><div><p class="br-kicker">${say('这次工作的记录', 'THE WORK BEHIND THE DELIVERY')}</p><h2>${esc(view.title)}</h2><p>${esc(view.lead)}</p></div><span class="br-total">${data.sequence.length}<small>${say('个可见动作', 'visible actions')}</small></span></header>`;
  if (view.empty) return `${head}<p>${esc(view.empty)}</p>`;
  const phaseDescription = (name: string) =>
    [
      say(
        '查资料、问同事，建立对问题的理解。',
        'Read sources and ask colleagues to understand the problem.',
      ),
      say(
        '通过测试和配置，检查想法是否成立。',
        'Test and configure to check whether an idea holds up.',
      ),
      say(
        '权衡限制，提出申请或交付决定。',
        'Weigh constraints, request resources or deliver a decision.',
      ),
      say('回到已做过的工作，继续修订和验证。', 'Return to earlier work to revise and verify it.'),
    ][PHASE_ORDER[name]] ??
    say('记录识别出的一个工作阶段。', 'A phase identified in this work record.');
  const bar = view.phases
    .map(
      (p) =>
        `<span class="rc-phase" data-style="${p.style}" style="flex:${p.steps}" title="${esc(p.name)}">${p.labelled ? esc(p.name) : ''}</span>`,
    )
    .join('');
  const legend = `<div class="rc-phase-legend">${view.legend.map((p) => `<p><i data-style="${p.style}" aria-hidden="true"></i><b>${esc(p.name)}</b><span>${phaseDescription(p.name)}</span></p>`).join('')}</div>`;
  const steps = (symbols: string[], reference = false) =>
    `<ol class="br-track">${symbols.map((symbol, i) => `<li><details class="br-action" data-phase="${reference ? '' : (PHASE_ORDER[data.sequence[i].phase ?? ''] ?? '')}"><summary><span class="br-step-no">${String(i + 1).padStart(2, '0')}</span><span>${esc(label(symbol))}</span></summary><p>${reference ? say('参考轨迹里的动作', 'Action in the reference trajectory') : `${esc(data.sequence[i].phase ?? say('阶段未记录', 'Phase not recorded'))} · ${say(`记录序号 ${data.sequence[i].seq}`, `Record sequence ${data.sequence[i].seq}`)}`}</p>${!reference && data.sequence[i].question ? `<blockquote>${esc(data.sequence[i].question ?? '')}</blockquote>` : ''}</details></li>`).join('')}</ol>`;
  const reference = data.strategy?.reference;
  const refTrack = reference?.sequence?.length
    ? `<section class="br-band br-band--reference"><h3>${say('最近参考轨迹', 'Nearest reference trajectory')} · ${esc(strategyName(reference.strategy, l))}</h3>${steps(reference.sequence, true)}</section>`
    : `<p class="br-unavailable">${say('这次没有可展示的参考轨迹。', 'No reference trajectory was returned for this session.')}</p>`;
  const difference = view.alignment.length
    ? view.alignment
        .map(
          (g) =>
            `<section><h4>${esc(g.label)}</h4><ul>${g.items.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></section>`,
        )
        .join('')
    : `<p>${say('记录没有列出动作数量或首次出现次序的差异。', 'No differences in action counts or first-occurrence order were recorded.')}</p>`;
  const window = data.window
    ? say(
        `本次读取范围：记录 ${data.window.from_seq}–${data.window.to_seq}。`,
        `This read covers records ${data.window.from_seq}–${data.window.to_seq}.`,
      )
    : say('本次响应没有记录起止范围。', 'This response did not record its window.');
  return `${head}<details class="rc-behavior__steps"${options.stepsOpen ? ' open' : ''}><summary>${say('展开过程与参考对照', 'Explore the process and reference')}</summary><div class="br-content">
    <p class="rc-behavior__origin">${say('本次可见动作 · 截至本次读取，含同事对话。', 'Visible actions up to this read, including colleague questions.')} ${window}</p>
    <h3>${say('工作怎样展开', 'How the work unfolded')} <small> · ${fallback ? say('按规则分阶段', 'Rule-based phases') : say('HMM 识别阶段', 'Phases identified by HMM')}</small></h3>
    <div class="rc-phasebar" aria-hidden="true">${bar}</div>${legend}
    <div class="br-bands"><section class="br-band"><h3>${esc(view.stepsLabel)}</h3>${steps(data.sequence.map((r) => r.symbol))}</section>${refTrack}</div>
    <p class="br-method">${fallback ? esc(view.noStrategy ?? '') : say('DTW 按动作序列寻找最近参考。两条时间带各按自身顺序排列；接口没有提供逐点对齐路径。', 'DTW finds the nearest reference by action sequence. Each track keeps its own order; no point-by-point alignment path was returned.')}</p>
    <p class="rc-behavior__nearest">${esc(view.nearest ?? view.noStrategy ?? '')}</p>
    ${data.strategy?.top3.some((s) => s.distance > (data.strategy?.distance ?? Infinity)) && view.runnersUp ? `<p>${esc(view.runnersUp)}</p>` : ''}
    ${data.strategy ? `<div class="br-differences">${difference}</div><p class="br-method">${say('差异按动作数量和首次出现的先后比较。参考轨迹来自预设脚本，不代表最佳路线。', 'Differences compare action counts and first-occurrence order. References are scripted examples, not a best route.')}</p>` : ''}
    ${view.order.length ? `<details class="br-order"><summary>${esc(view.orderLabel)}</summary><ul>${view.order.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></details>` : ''}
    ${options.lens ? `<p class="rc-behavior__cats">${cats}</p>` : ''}
    <p class="meta">${esc(view.executor)}</p></div></details>`;
}
