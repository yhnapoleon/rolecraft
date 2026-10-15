/**
 * One recorded approval decision as a card: the published rule sentence it applied, each
 * requested term's numbers and, for an over-ceiling rejection, a capped re-application, or the
 * pilot settings when no request can pass until the plan changes.
 * Everything shown comes from the decision's recorded assessment; nothing is re-judged here.
 */
import { T } from '../../app/i18n';
import { fallbackLabel, strategyLabel, workItemLabel } from '../../app/pilot-config';
import { resourceNames } from './decision-words';
import type { Totals } from './request-terms';
import type {
  BusinessDecision,
  BusinessRequest,
  EvidenceRefV2,
  _ApprovalTermCheck,
} from '../../contracts-v2';

export interface CardLine {
  ok: boolean;
  text: string;
}
export interface CardClause {
  ref: EvidenceRefV2;
  title: string;
  version: number;
  quote: string;
}
export interface DecisionCardModel {
  clauses: CardClause[];
  lines: CardLine[];
  /** Totals for "re-apply at the ceiling", or null when that would not help. */
  ceiling: Record<string, number> | null;
  /** A declined plan that no request can get through as it stands (it needs more than a ceiling,
   * lacks work its strategy requires or the required hand-off): what to change first, one
   * sentence each. The card then offers the settings instead of a capped re-application, which
   * would only be declined again. Empty otherwise. */
  replan: string[];
}
type Issue = NonNullable<_ApprovalTermCheck['issues']>[number];

const DAY = 'deadline_day';
// The request panel's names, which are also the recorded decisions' words.
const name = (resource: string) =>
  (resourceNames() as Record<string, string>)[resource] ?? resource;
/** Amounts after a label: "申请 7" / "申请第 7 天", "requested 7" / "requested day 7". */
const zh = (label: string, resource: string, n: number) =>
  resource === DAY ? `${label}第 ${n} 天` : `${label} ${n}`;
const en = (label: string, resource: string, n: number) =>
  resource === DAY ? `${label} day ${n}` : `${label} ${n}`;
const plain = (resource: string, n: number) =>
  resource === DAY ? T(`第 ${n} 天`, `day ${n}`) : String(n);

function requestPart(t: _ApprovalTermCheck, has: (i: Issue) => boolean) {
  const r = t.resource;
  const asked = T(zh('申请', r, t.requested), en('requested', r, t.requested));
  if (has('over_limit'))
    return T(
      `${asked}，${zh('超出上限', r, t.limit)}`,
      `${asked}, ${en('over the ceiling of', r, t.limit)}`,
    );
  if (has('below_current'))
    return T(
      `${asked}，${zh('比现有', r, t.current)}少`,
      `${asked}, ${en('below the current', r, t.current)}`,
    );
  if (has('no_increase')) return T(`${asked}，和现有一样`, `${asked}, the same as now`);
  return asked;
}

function needPart(t: _ApprovalTermCheck, has: (i: Issue) => boolean) {
  const r = t.resource;
  const day = r === DAY;
  const subject = day
    ? T(`计划第 ${t.needed} 天上线`, `the plan launches on day ${t.needed}`)
    : T(`方案需要 ${t.needed}`, `the plan needs ${t.needed}`);
  if (has('need_over_limit'))
    return T(
      `${subject}，${zh('超出上限', r, t.limit)}`,
      `${subject}, ${en('over the ceiling of', r, t.limit)}`,
    );
  if (has('no_shortfall'))
    return day
      ? T(`${subject}，现有期限已够`, `${subject}, within the current deadline`)
      : T(
          `方案只需 ${t.needed}，现有 ${t.current} 已够`,
          `the plan needs only ${t.needed}; ${t.current} is already allocated`,
        );
  if (has('insufficient')) return T(`${subject}，申请不够`, `${subject}, more than requested`);
  const gap = t.needed - t.current;
  if (gap <= 0) return null;
  return day
    ? T(
        `${subject}（比现有期限晚 ${gap} 天）`,
        `${subject} (${gap} days past the current deadline)`,
      )
    : T(`${subject}（缺口 ${gap}）`, `${subject} (shortfall ${gap})`);
}

/** The plan's own need is over the ceiling: what to change in the settings before asking again. */
function overCeilingNote(t: _ApprovalTermCheck) {
  const n = t.needed;
  const l = t.limit;
  if (t.resource === DAY)
    return T(
      `计划第 ${n} 天上线，上限第 ${l} 天：先把上线日提前到第 ${l} 天以内再申请`,
      `The plan launches on day ${n}, past the ceiling of day ${l}: move the launch to day ${l} or earlier before requesting`,
    );
  if (t.resource === 'capacity')
    return T(
      `试点 ${n} 人，上限 ${l}：先把试点人数降到 ${l} 以内再申请`,
      `The pilot has ${n} users, over the ceiling of ${l}: bring it down to ${l} or fewer before requesting`,
    );
  return T(
    `方案需要 ${n}，上限 ${l}：先把方案降到 ${l} 以内再申请`,
    `The plan needs ${n}, over the ceiling of ${l}: bring it down to ${l} or less before requesting`,
  );
}

/**
 * What the settings must change before any request can pass, from the recorded assessment of a
 * declined request: a plan over a ceiling, work its strategy requires, the required hand-off.
 * Asking at the ceiling would only be declined again (164 N1).
 */
function replanNotes(decision: BusinessDecision): string[] {
  const assessment = decision.assessment;
  if (decision.status !== 'rejected' || !assessment) return [];
  const notes = (assessment.terms ?? [])
    .filter((t) => t.issues?.includes('need_over_limit'))
    .map(overCeilingNote);
  const missing = (assessment.missing_work_items ?? []).map(workItemLabel);
  if (missing.length)
    notes.push(
      T(
        `方案缺少：${missing.join('、')}——先在设置里补上再申请`,
        `The plan is missing ${missing.join(', ')}: add ${missing.length > 1 ? 'them' : 'it'} in the settings before requesting`,
      ),
    );
  if (assessment.fallback_required)
    notes.push(
      T(
        `答不了或不确定时要${fallbackLabel('human')}——先在设置里选上再申请`,
        `Unanswered questions must go to a person: choose “${fallbackLabel('human')}” in the settings before requesting`,
      ),
    );
  return notes;
}

function termLine(t: _ApprovalTermCheck): CardLine {
  const r = t.resource;
  const issues = t.issues ?? [];
  const has = (issue: Issue) => issues.includes(issue);
  if (!issues.length)
    return {
      ok: true,
      text: T(
        `${name(r)}：${plain(r, t.current)} → ${plain(r, t.requested)}（${zh('方案需要', r, t.needed)} · ${zh('上限', r, t.limit)}）`,
        `${name(r)}: ${plain(r, t.current)} → ${plain(r, t.requested)} (${en('plan needs', r, t.needed)} · ${en('ceiling', r, t.limit)})`,
      ),
    };
  const parts = [requestPart(t, has), needPart(t, has)].filter((p): p is string => !!p);
  return {
    ok: false,
    text: T(`${name(t.resource)}：${parts.join('；')}`, `${name(t.resource)}: ${parts.join('; ')}`),
  };
}

/**
 * Over-ceiling terms capped and terms asked below the plan's need raised to it; terms with no
 * shortfall, no increase or a reduction dropped; terms the allocation in effect already reaches
 * dropped too. Only offered while a capped term is still left to ask for.
 */
function ceilingTerms(decision: BusinessDecision, current: Totals): Record<string, number> | null {
  if (decision.status !== 'rejected') return null;
  const result: Record<string, number> = {};
  let capped = false;
  for (const t of decision.assessment?.terms ?? []) {
    const found = t.issues ?? [];
    if (found.some((i) => i === 'no_shortfall' || i === 'no_increase' || i === 'below_current'))
      continue;
    const over = found.includes('over_limit');
    // A term asked below what the plan needs is filled with that need, which then fits the
    // ceiling; keeping it would be declined again (185 P2-1).
    const short = found.includes('insufficient') && !found.includes('need_over_limit');
    const value = over ? t.limit : short ? t.needed : t.requested;
    if (value <= (current[t.resource] ?? t.current)) continue;
    result[t.resource] = value;
    capped ||= over;
  }
  return capped ? result : null;
}

export function decisionCardModel(
  decision: BusinessDecision,
  request: BusinessRequest,
  titles: Readonly<Record<string, string>>,
  current: Totals = {},
): DecisionCardModel {
  const assessment = decision.assessment;
  const lines = (assessment?.terms ?? []).map(termLine);
  const missing = assessment?.missing_work_items ?? [];
  if (missing.length) {
    const strategy = strategyLabel(request.basis.config.update_strategy ?? 'daily');
    const items = missing.map(workItemLabel);
    lines.push({
      ok: false,
      text: T(
        `${strategy}策略还要安排：${items.join('、')}`,
        `Strategy “${strategy}” also needs: ${items.join(', ')}`,
      ),
    });
  }
  if (assessment?.fallback_required)
    lines.push({
      ok: false,
      text: T('答不了时要转人工确认', 'Unanswerable questions must go to a person'),
    });
  // Every rejection keeps a readable reason: when no line above explains it (an unreadable
  // citation, a missing reason, a resource outside the rules), the recorded sentence does.
  if (decision.status === 'rejected' && !lines.some((line) => !line.ok) && decision.reason)
    lines.push({ ok: false, text: decision.reason });
  const clauses = (assessment?.clauses ?? []).flatMap((ref) =>
    ref.quote
      ? [
          {
            ref,
            title:
              titles[`${ref.object_id}:${ref.version}`] ??
              T('经理发布的资源审批规则', "Manager's resource-approval rules"),
            version: ref.version,
            quote: ref.quote,
          },
        ]
      : [],
  );
  const replan = replanNotes(decision);
  return {
    clauses,
    lines,
    ceiling: replan.length ? null : ceilingTerms(decision, current),
    replan,
  };
}

export interface CardActions {
  open(ref: EvidenceRefV2): void;
  refill(terms: Readonly<Record<string, number>>): void;
}

function button(doc: Document, text: string, onClick?: () => void, label?: string) {
  const b = doc.createElement('button');
  b.type = 'button';
  b.className = 'btn small quiet';
  b.textContent = text;
  if (label) b.setAttribute('aria-label', label);
  if (onClick) b.addEventListener('click', onClick);
  return b;
}

function quote(doc: Document, clause: CardClause, actions: CardActions) {
  const text = doc.createElement('blockquote');
  text.className = 'rc-decision__quote';
  text.textContent = clause.quote;
  const open = button(
    doc,
    T('看原文', 'View source'),
    () => actions.open(clause.ref),
    T(`看《${clause.title}》原文`, `View “${clause.title}”`),
  );
  return [text, open];
}

/** The card's DOM. Buttons only open the source, fill the request form or open the pilot
 * settings; nothing is sent. */
export function renderDecisionCard(
  doc: Document,
  model: DecisionCardModel,
  actions: CardActions,
): HTMLElement {
  const card = doc.createElement('section');
  card.className = 'rc-decision';
  card.dataset.decisionCard = '';
  const [first, ...more] = model.clauses;
  if (first) {
    const basis = doc.createElement('p');
    basis.className = 'rc-decision__basis';
    basis.textContent = T(
      `依据《${first.title}》v${first.version}：`,
      `Per “${first.title}” v${first.version}:`,
    );
    card.append(basis, ...quote(doc, first, actions));
  }
  const list = doc.createElement('ul');
  list.className = 'rc-decision__lines';
  for (const line of model.lines) {
    const item = doc.createElement('li');
    item.className = line.ok ? 'ok' : 'bad';
    const mark = doc.createElement('span');
    mark.className = 'rc-decision__mark';
    mark.setAttribute('aria-hidden', 'true');
    mark.textContent = line.ok ? '✓' : '✕';
    const state = doc.createElement('span');
    state.className = 'sr-only';
    state.textContent = line.ok ? T('已满足：', 'Met: ') : T('未满足：', 'Not met: ');
    const text = doc.createElement('span');
    text.textContent = line.text;
    item.append(mark, state, text);
    list.append(item);
  }
  card.append(list);
  const ceiling = model.ceiling;
  if (ceiling)
    card.append(
      button(doc, T('按上限改申请', 'Re-apply at the ceiling'), () => actions.refill(ceiling)),
    );
  if (model.replan.length) {
    for (const note of model.replan) {
      const text = doc.createElement('p');
      text.className = 'rc-decision__replan';
      text.textContent = note;
      card.append(text);
    }
    // The workbench's own "config" action opens the pilot settings, as the pre-submission
    // card's "adjust settings" does.
    const settings = button(doc, T('调整设置', 'Adjust settings'));
    settings.dataset.action = 'config';
    card.append(settings);
  }
  if (more.length) {
    const details = doc.createElement('details');
    const summary = doc.createElement('summary');
    summary.textContent = T(`其他规则原文（${more.length}）`, `Other rule text (${more.length})`);
    details.append(summary, ...more.flatMap((clause) => quote(doc, clause, actions)));
    card.append(details);
  }
  return card;
}
