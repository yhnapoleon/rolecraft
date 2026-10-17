/** "Your behaviour pattern" on the review page: GET /sessions/{id}/behavior as HTML. */
import { copyText, type CopyTable, type Language } from '../results-native/localization';
import './behavior.css';

export interface BehaviorRow {
  seq: number;
  symbol: string;
  phase?: string;
}
export interface Behavior {
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
  lead: '把这次练习的每一步变成一串符号，和参考做法对齐比较。只描述做法，不计分。',
  empty: '还没有可识别的步骤。',
  phases: '阶段',
  nearest: '最接近的做法：{name}（DTW 距离 {d}）',
  noStrategy: '最接近的做法：轨迹识别器未加载，暂只按规则分阶段',
  missing: '参考做法里有、你没做的',
  extra: '你多做的',
  swapped: '顺序与参考相反',
  anomalies: '值得复盘的地方',
  none: '没有发现规则异常。',
  executor: '执行者：{declared}',
  fallback: '规则回退 · 权重未加载',
  human: '本人',
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
  sym_ask: '问{x}',
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
} as const;
const en: Record<keyof typeof zh, string> = {
  title: 'Your behaviour pattern',
  lead: 'Every step of this practice as a symbol sequence, aligned with reference ways of working. Descriptive only, never scored.',
  empty: 'No recognisable steps yet.',
  phases: 'Phases',
  nearest: 'Closest way of working: {name} (DTW distance {d})',
  noStrategy: 'Closest way of working: trajectory recognizer not loaded; phases by rule only',
  missing: 'In the reference, not done by you',
  extra: 'Done in addition',
  swapped: 'Order opposite to the reference',
  anomalies: 'Worth reviewing',
  none: 'No rule anomalies found.',
  executor: 'Executor: {declared}',
  fallback: 'rule fallback · weights not loaded',
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
};
type Key = keyof typeof zh;
const COPY: CopyTable<Key> = { zh, en };
const t = (l: Language, k: Key, v: Record<string, string | number> = {}) => copyText(COPY, l, k, v);
const has = (k: string): k is Key => k in zh;

const esc = (v: string) =>
  v.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c);

const ROLE = {
  zh: { supervisor: '经理', tech_lead: '技术负责人', business_lead: '业务负责人' },
  en: { supervisor: 'manager', tech_lead: 'tech lead', business_lead: 'business lead' },
} as const;

export function symbolLabel(symbol: string, l: Language) {
  const [head, a, b] = symbol.split(':');
  if (head === 'ask') {
    const role = (ROLE[l] as Record<string, string>)[a] ?? a;
    return t(l, 'sym_ask', { x: role }) + (b ? ` · ${b.replace('ask_', '').replace('seek_', '')}` : '');
  }
  if (['read', 'test', 'request'].includes(head)) return t(l, `sym_${head}` as Key, { x: a ?? '' });
  if (['approved', 'denied', 'counter', 'event'].includes(head)) return t(l, `sym_${head}` as Key);
  const key = `sym_${head}`;
  return has(key) ? t(l, key) : symbol;
}

const strategyName = (s: string, l: Language) => (has(`s_${s}`) ? t(l, `s_${s}` as Key) : s);
const PHASE_INDEX: Record<string, number> = {
  探索: 0, 测试: 1, 决策: 2, 调整: 3, explore: 0, test: 1, decide: 2, adjust: 3,
};

export function behaviorHtml(data: Behavior | null | undefined, l: Language) {
  if (!data) return '';
  const fallback = data.recognizer.endsWith('@rule-fallback');
  const head = `<h2>${t(l, 'title')}</h2><p class="meta">${t(l, 'lead')}</p>`;
  if (!data.sequence.length) return `${head}<p class="meta">${t(l, 'empty')}</p>`;
  const total = data.sequence.length;
  const bar = data.phases
    .map((p) => {
      const steps = data.sequence.filter((r) => r.seq >= p.from_seq && r.seq <= p.to_seq && r.phase === p.name).length || 1;
      return `<span class="rc-phase" data-phase="${PHASE_INDEX[p.name] ?? 0}" style="flex:${steps}" title="${esc(p.name)}">${esc(p.name)}</span>`;
    })
    .join('');
  const chips = data.sequence
    .map((r) => `<li data-phase="${PHASE_INDEX[r.phase ?? ''] ?? 0}">${esc(symbolLabel(r.symbol, l))}</li>`)
    .join('');
  const strategy = data.strategy
    ? `<p>${esc(t(l, 'nearest', { name: strategyName(data.strategy.nearest, l), d: data.strategy.distance.toFixed(2) }))}</p>`
    : `<p class="meta">${t(l, 'noStrategy')}</p>`;
  const list = (key: Key, items: string[]) =>
    items.length
      ? `<p class="rc-align-label">${t(l, key)}</p><ul class="rc-align">${items.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>`
      : '';
  const alignment =
    list('missing', data.alignment.missing.map((s) => symbolLabel(s, l))) +
    list('extra', data.alignment.extra.map((s) => symbolLabel(s, l))) +
    list('swapped', data.alignment.swapped.map(([a, b]) => `${symbolLabel(a, l)} ⇄ ${symbolLabel(b, l)}`));
  const anomalies = data.anomalies.length
    ? `<ul class="rc-anomalies">${data.anomalies
        .map((a) => `<li>${esc(has(`rule_${a.rule}`) ? t(l, `rule_${a.rule}` as Key) : a.rule)}</li>`)
        .join('')}</ul>`
    : `<p class="meta">${t(l, 'none')}</p>`;
  const executor = t(l, 'executor', {
    declared: has(data.executor.declared) ? t(l, data.executor.declared as Key) : data.executor.declared,
  });
  return `${head}
    <p class="rc-badges"><span class="rc-badge" data-task="behavior"${fallback ? ' data-fallback=""' : ''} title="${esc(data.recognizer)}">${esc(data.recognizer)}${fallback ? ` · ${t(l, 'fallback')}` : ''}</span></p>
    <p class="rc-align-label">${t(l, 'phases')} · ${total}</p>
    <div class="rc-phasebar">${bar}</div>
    <ol class="rc-steps">${chips}</ol>
    ${strategy}${alignment}
    <p class="rc-align-label">${t(l, 'anomalies')}</p>${anomalies}
    <p class="meta">${esc(executor)}</p>`;
}
