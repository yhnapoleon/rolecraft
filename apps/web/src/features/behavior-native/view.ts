/** "Your behaviour pattern" on the review page: GET /sessions/{id}/behavior as HTML. It states
 * what the learner did and which reference way of working it is closest to; it never scores.
 * Placement is decided by BEHAVIOR_PLACEMENT; with the recognition layer off it never shows. */
import { copyText, type CopyTable, type Language } from '../results-native/localization';
import './behavior.css';
import { personName } from '../../app/people.js';

/** Where the section appears: 'lens' = only with the recognition lens open (user decision
 * 2026-10-24); 'default' = also in the learner's default view, without course labels. */
export const BEHAVIOR_PLACEMENT: 'lens' | 'default' = 'lens';

export interface BehaviorRow {
  seq: number;
  symbol: string;
  phase?: string;
}
export interface Behavior {
  /** False when the recognition layer is off (the read then carries nothing else). */
  enabled?: boolean;
  sequence: BehaviorRow[];
  strategy: { nearest: string; distance: number; top3: { strategy: string; distance: number }[] } | null;
  alignment: { missing: string[]; extra: string[]; swapped: string[][] };
  phases: { name: string; from_seq: number; to_seq: number }[];
  anomalies: { rule: string; score: number; at_seq: number }[];
  executor: { declared: string; predicted: string | null; confidence: number | null };
  recognizer: string;
}

const zh = {
  title: '你的行为模式',
  lead: '这次练习的每一步，和几种参考做法对齐比较。只描述做法，不计分。',
  category: '机器学习 · 无监督 · 智能感知',
  method: 'DTW 对齐 / HMM 分阶段',
  steps: '你做了这些步骤',
  runnersUp: '其次接近：{names}',
  empty: '还没有可识别的步骤。',
  phases: '阶段',
  nearest: '最接近的工作方式：{name}',
  noStrategy: '这一局按规则划分阶段，行为模型未加载，还认不出你接近哪种工作方式。',
  missing: '参考做法里有、你没做的',
  extra: '你多做的',
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
  s_thorough: '规范 A：先读后问再测',
  s_request_first: '规范 B：先申请后配置',
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
  title: 'Your behaviour pattern',
  lead: 'Every step of this practice, aligned with reference ways of working. Descriptive only, never scored.',
  category: 'Machine learning · Unsupervised · Intelligent sensing',
  method: 'DTW alignment / HMM phases',
  steps: 'The steps you took',
  runnersUp: 'Next closest: {names}',
  empty: 'No recognisable steps yet.',
  phases: 'Phases',
  nearest: 'Closest way of working: {name}',
  noStrategy: 'Phases are set by rules this time. The behaviour model isn’t loaded, so your way of working isn’t matched yet.',
  missing: 'In the reference, not done by you',
  extra: 'Done in addition',
  swapped: 'Order opposite to the reference',
  anomalies: 'Step orders the rules flagged',
  none: 'The rules flagged no step order.',
  executor: 'These steps were taken by {declared}.',
  fallback: 'Rule fallback',
  human: 'you',
  own_agent: 'your agent',
  reference_agent: 'reference agent',
  rule_policy_update_untested_submit: 'Submitted without testing again after things changed (a notice or an index refresh)',
  rule_request_before_technical: 'Requested resources before reading the technical material',
  rule_configured_before_approval: 'Configured to the requested numbers before the request was approved',
  rule_repeated_submit_same_config: 'Submitted again with an unchanged configuration',
  s_thorough: 'Standard A: read, ask, then test',
  s_request_first: 'Standard B: request, then configure',
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
  v.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c);

// Colleagues by name (app/people.js), the same in both languages.
const ROLE = {
  zh: { supervisor: personName('supervisor'), tech_lead: personName('tech_lead'), business_lead: personName('business_lead') },
  en: { supervisor: personName('supervisor'), tech_lead: personName('tech_lead'), business_lead: personName('business_lead') },
} as const;

export function symbolLabel(symbol: string, l: Language, materialName?: (id: string) => string) {
  const [head, a, b] = symbol.split(':');
  if (head === 'ask') {
    const role = (ROLE[l] as Record<string, string>)[a] ?? a;
    const intent = b && has(`i_${b}`) ? t(l, `i_${b}` as Key) : b?.replace('ask_', '').replace('seek_', '');
    return t(l, 'sym_ask', { x: role }) + (intent ? ` · ${intent}` : '');
  }
  if (head === 'read') {
    const name = a && materialName ? materialName(a) : '';
    // A step chip names the document by its short title ("经理委托", not the whole heading).
    const short = name.split(/[：:]/)[0].trim() || name;
    return name && name !== a ? t(l, 'sym_read_title', { x: short }) : t(l, 'sym_read', { x: a ?? '' });
  }
  if (head === 'test') return t(l, 'sym_test', { x: a && has(`t_${a}`) ? t(l, `t_${a}` as Key) : (a ?? '') });
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
  探索: 0, 测试: 1, 决策: 2, 调整: 3, explore: 0, test: 1, decide: 2, adjust: 3,
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
      data.sequence.filter((r) => r.seq >= p.from_seq && r.seq <= p.to_seq && r.phase === p.name).length || 1;
    return { name: p.name, steps, style: styleOf(p.name), labelled: (steps / total) * BAR_WIDTH >= labelWidth(p.name, l) };
  });
  const legend = [...new Map(phases.map((p) => [p.name, { name: p.name, style: p.style }])).values()].sort(
    (a, b) => a.style - b.style,
  );
  return { phases, legend };
}

/** What the section says, as data; null when it does not show (layer off, or placement). */
export function behaviorView(
  data: Behavior | { enabled: false } | null | undefined,
  l: Language,
  options: { lens?: boolean; materialName?: (id: string) => string } = {},
): BehaviorView | null {
  if (!data || data.enabled === false || !('sequence' in data)) return null;
  const lens = !!options.lens;
  if (BEHAVIOR_PLACEMENT === 'lens' && !lens) return null;
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
    nearest: strategy ? t(l, 'nearest', { name: strategyName(strategy.nearest, l) }) : null,
    runnersUp:
      strategy && strategy.top3.length > 1
        ? t(l, 'runnersUp', {
            names: strategy.top3
              .slice(1)
              .map((s) => strategyName(s.strategy, l))
              .join(l === 'zh' ? '、' : ', '),
          })
        : null,
    noStrategy: strategy ? null : t(l, 'noStrategy'),
    alignment: [
      { label: t(l, 'missing'), items: data.alignment.missing.map(label) },
      { label: t(l, 'extra'), items: data.alignment.extra.map(label) },
      { label: t(l, 'swapped'), items: data.alignment.swapped.map(([a, b]) => `${label(a)} ⇄ ${label(b)}`) },
    ].filter((group) => group.items.length),
    orderLabel: t(l, 'anomalies'),
    order: data.anomalies.map((a) => (has(`rule_${a.rule}`) ? t(l, `rule_${a.rule}` as Key) : a.rule)),
    orderNone: data.anomalies.length ? null : t(l, 'none'),
    executor: t(l, 'executor', {
      declared: has(data.executor.declared) ? t(l, data.executor.declared as Key) : data.executor.declared,
    }),
  };
}

/** The section as HTML for the review page (ui.js); '' when it does not show. */
export function behaviorHtml(
  data: Behavior | { enabled: false } | null | undefined,
  l: Language,
  options: { lens?: boolean; materialName?: (id: string) => string } = {},
) {
  const view = behaviorView(data, l, options);
  if (!view) return '';
  const cats = view.categories.length
    ? `<p class="rc-behavior__cats">${view.categories
        .map((c) => `<span class="rc-cat"${c.fallback ? ' data-fallback=""' : ''}>${esc(c.text)}</span>`)
        .join('')}</p>`
    : '';
  const head = `<h2>${esc(view.title)}</h2>${cats}<p class="meta">${esc(view.lead)}</p>`;
  if (view.empty) return `${head}<p class="meta">${esc(view.empty)}</p>`;
  const bar = view.phases
    .map(
      (p) =>
        `<span class="rc-phase" data-style="${p.style}" style="flex:${p.steps}" title="${esc(p.name)}">${p.labelled ? esc(p.name) : ''}</span>`,
    )
    .join('');
  const legend = `<p class="rc-phase-legend">${view.legend
    .map((p) => `<span><i data-style="${p.style}" aria-hidden="true"></i>${esc(p.name)}</span>`)
    .join('')}</p>`;
  const strategy = view.nearest
    ? `<p class="rc-behavior__nearest">${esc(view.nearest)}</p>${view.runnersUp ? `<p class="meta">${esc(view.runnersUp)}</p>` : ''}`
    : `<p class="meta">${esc(view.noStrategy ?? '')}</p>`;
  const alignment = view.alignment
    .map(
      (group) =>
        `<p class="rc-align-label">${esc(group.label)}</p><ul class="rc-align">${group.items.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>`,
    )
    .join('');
  const order = view.order.length
    ? `<ul class="rc-anomalies">${view.order.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>`
    : `<p class="meta">${esc(view.orderNone ?? '')}</p>`;
  return `${head}
    <p class="rc-align-label">${esc(view.phasesLabel)}</p>
    <div class="rc-phasebar" aria-hidden="true">${bar}</div>
    ${legend}
    <p class="rc-align-label">${esc(view.stepsLabel)}</p>
    <ol class="rc-steps-row">${view.steps.map((s) => `<li>${esc(s)}</li>`).join('')}</ol>
    ${strategy}${alignment}
    <p class="rc-align-label">${esc(view.orderLabel)}</p>${order}
    <p class="meta">${esc(view.executor)}</p>`;
}
