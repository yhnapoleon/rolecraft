/** Optional registered relation advice. This view never requests inference or changes scores. */
import type { ObjectRef } from '../workspace/contract-types';
import type { FeedbackLanguage } from './localization';
import { adviceCopy, type ModelAdviceCopyKey } from './model-advice-copy';
import { modelWaitNode } from '../../app/model-status';
import { noteAboutFact } from '../../app/about-facts';
import { renderMeter, sureMeter } from '../recognition-native/signals';

type Status = 'completed' | 'failed' | 'unavailable' | 'synthetic_mechanism_only';
type Relation = 'SUPPORTED' | 'CONTRADICTED' | 'INSUFFICIENT';
export type ModelDataset = {
  dataset_id: string;
  dataset_manifest_sha256: string;
  label_tiers: string[];
};
/** One registered fusion member; `alpha` is this member's weight (left 1−alpha, right alpha). */
export type ModelComponent = {
  role: 'left' | 'right';
  id: string;
  kind: string;
  model_revision: string;
  alpha: number | null;
};
export type ModelFusion = {
  alpha: number;
  evidence_threshold: number;
  fusion_gain_observed: boolean;
};
export type ModelRegistration = {
  id: string;
  model_revision: string;
  scope: 'synthetic_fixture' | 'external_candidate';
  quality_validated: false;
  kind?: string;
  dataset?: ModelDataset;
  components?: ModelComponent[];
  fusion?: ModelFusion;
  weights_stage?: string;
};
/** One sentence of the learner's work as the relation model saw it. */
export type AdviceUnit = {
  index: number;
  /** The work version the sentence came from, with its span. */
  subject: ObjectRef & { span_start: number; span_end: number };
  quote: string;
  status: 'completed' | 'abstained' | 'failed';
  label: Relation | null;
  evidence_ids: string[];
  citations: ObjectRef[];
  reason_code: string | null;
  /** Recognition layer: the relation confidence behind the label (0..1), when recorded. */
  confidence?: number | null;
};
export type AdviceCounts = Record<
  | 'supported'
  | 'contradicted'
  | 'insufficient'
  | 'abstained'
  | 'failed'
  | 'skipped_short'
  | 'over_budget',
  number
>;
export type RegisteredAdvice = {
  criterion: 'R2.support';
  status: Status;
  registration: ModelRegistration | null;
  label: Relation | null;
  evidence_ids: string[];
  citations: ObjectRef[];
  error_code: string | null;
  mode: 'advisory';
  affects_score: false;
  units?: AdviceUnit[];
  aggregation?: { policy: string; counts: AdviceCounts };
};
export type AdviceFallback = 'waiting' | 'pending' | 'unavailable' | 'failed';
type Row = Record<string, unknown>;
const row = (value: unknown): value is Row =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const fail = (): never => {
  throw Error('Invalid registered model advice');
};
const text = (value: unknown): string =>
  typeof value === 'string' && value.length > 0 ? value : fail();

const optional = (value: unknown): value is undefined | null =>
  value === undefined || value === null;
const fraction = (value: unknown): number =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1 ? value : fail();
const count = (value: unknown): number =>
  value === undefined
    ? 0
    : typeof value === 'number' && Number.isInteger(value) && value >= 0
      ? value
      : fail();

function dataset(value: unknown): ModelDataset {
  if (!row(value)) return fail();
  const tiers = value.label_tiers ?? [];
  if (!Array.isArray(tiers)) return fail();
  return {
    dataset_id: text(value.dataset_id),
    dataset_manifest_sha256: text(value.dataset_manifest_sha256),
    label_tiers: tiers.map(text),
  };
}
function fusion(value: unknown): ModelFusion {
  if (!row(value) || typeof value.fusion_gain_observed !== 'boolean') return fail();
  return {
    alpha: fraction(value.alpha),
    evidence_threshold: fraction(value.evidence_threshold),
    fusion_gain_observed: value.fusion_gain_observed,
  };
}
/** A fusion member's weight: left 1 − alpha, right alpha (145 fusion registration). */
const memberWeight = (role: 'left' | 'right', alpha: number) =>
  role === 'left' ? 1 - alpha : alpha;
const same = (a: number, b: number) => Math.abs(a - b) <= 1e-9;
function components(value: unknown, mix: ModelFusion | undefined): ModelComponent[] {
  if (!Array.isArray(value) || value.length !== 2) return fail();
  const members = value.map((member: unknown, index): ModelComponent => {
    const role = index === 0 ? 'left' : 'right';
    if (!row(member) || member.role !== role) return fail();
    const alpha = optional(member.alpha) ? null : fraction(member.alpha);
    if (alpha !== null && mix && !same(alpha, memberWeight(role, mix.alpha))) return fail();
    return {
      role,
      id: text(member.id),
      kind: text(member.kind),
      model_revision: text(member.model_revision),
      alpha,
    };
  });
  // Without the fusion record the two weights must still be one alpha's two shares.
  const [left, right] = members;
  if (left.alpha !== null && right.alpha !== null && !same(left.alpha + right.alpha, 1))
    return fail();
  return members;
}
function registration(value: unknown): ModelRegistration | null {
  if (value === null) return null;
  if (!row(value) || value.quality_validated !== false) return fail();
  const scope = value.scope;
  if (scope !== 'synthetic_fixture' && scope !== 'external_candidate') return fail();
  // Relation advice only; criterion registrations are not shown in this wave.
  if (
    (value.task_type !== undefined && value.task_type !== 'relation') ||
    !optional(value.criteria) ||
    !optional(value.rubric_version)
  )
    return fail();
  const identity: ModelRegistration = {
    id: text(value.id),
    model_revision: text(value.model_revision),
    scope,
    quality_validated: false,
  };
  if (!optional(value.kind)) identity.kind = text(value.kind);
  if (!optional(value.weights_stage)) identity.weights_stage = text(value.weights_stage);
  if (!optional(value.dataset)) identity.dataset = dataset(value.dataset);
  const mix = optional(value.fusion) ? undefined : fusion(value.fusion);
  if (mix) identity.fusion = mix;
  if (!optional(value.components)) identity.components = components(value.components, mix);
  return identity;
}
function citation(value: unknown, sessionId: string): ObjectRef {
  if (
    !row(value) ||
    value.session_id !== sessionId ||
    typeof value.version !== 'number' ||
    !Number.isInteger(value.version) ||
    value.version < 1
  )
    return fail();
  const config = value.config_version;
  if (
    config !== undefined &&
    config !== null &&
    (typeof config !== 'number' || !Number.isInteger(config) || config < 0)
  )
    return fail();
  return {
    session_id: sessionId,
    kind: text(value.kind),
    object_id: text(value.object_id),
    version: value.version,
    config_version: config,
  };
}
function status(value: unknown): Status {
  if (
    value === 'completed' ||
    value === 'failed' ||
    value === 'unavailable' ||
    value === 'synthetic_mechanism_only'
  )
    return value;
  return fail();
}
function relation(value: unknown): Relation | null {
  if (
    value === null ||
    value === 'SUPPORTED' ||
    value === 'CONTRADICTED' ||
    value === 'INSUFFICIENT'
  )
    return value;
  return fail();
}

function selected(ids: unknown, refs: unknown, sessionId: string) {
  if (!Array.isArray(ids) || !Array.isArray(refs)) return fail();
  const evidence = ids.map(text);
  const sources = refs.map((ref: unknown) => citation(ref, sessionId));
  if (new Set(evidence).size !== evidence.length || evidence.length !== sources.length)
    return fail();
  return { evidence, sources };
}
const UNIT_STATUSES = new Set(['completed', 'abstained', 'failed']);
function unit(value: unknown, sessionId: string): AdviceUnit {
  if (!row(value) || !row(value.subject)) return fail();
  const index = value.index;
  const start = value.subject.span_start;
  const end = value.subject.span_end;
  if (
    typeof index !== 'number' ||
    !Number.isInteger(index) ||
    index < 0 ||
    typeof start !== 'number' ||
    typeof end !== 'number' ||
    !Number.isInteger(start) ||
    !Number.isInteger(end) ||
    start < 0 ||
    end < start ||
    typeof value.status !== 'string' ||
    !UNIT_STATUSES.has(value.status)
  )
    return fail();
  const status = value.status as AdviceUnit['status'];
  const label = relation(value.label ?? null);
  const { evidence, sources } = selected(
    value.evidence_ids ?? [],
    value.citations ?? [],
    sessionId,
  );
  // Only a judged sentence has a label; an unlabelled one selects no evidence.
  if ((status === 'completed') !== (label !== null) || (label === null && evidence.length))
    return fail();
  const reason = value.reason_code ?? null;
  if (reason !== null && typeof reason !== 'string') return fail();
  return {
    index,
    subject: { ...citation(value.subject, sessionId), span_start: start, span_end: end },
    quote: text(value.subject.quote),
    status,
    label,
    evidence_ids: evidence,
    citations: sources,
    reason_code: reason,
    confidence:
      typeof value.confidence === 'number' && Number.isFinite(value.confidence)
        ? value.confidence
        : null,
  };
}
const COUNTED = ['supported', 'contradicted', 'insufficient', 'abstained', 'failed'] as const;
/** 148 `units.aggregate`: any judged CONTRADICTED sentence decides; SUPPORTED only when every
 * planned sentence was judged SUPPORTED and none was over budget; otherwise INSUFFICIENT. */
function workRelation(units: AdviceUnit[], counts: AdviceCounts): Relation | null {
  const judged = units.filter((entry) => entry.status === 'completed');
  if (!judged.length) return null;
  if (judged.some((entry) => entry.label === 'CONTRADICTED')) return 'CONTRADICTED';
  return judged.length === units.length &&
    judged.every((entry) => entry.label === 'SUPPORTED') &&
    counts.over_budget === 0
    ? 'SUPPORTED'
    : 'INSUFFICIENT';
}
function aggregation(value: unknown, units: AdviceUnit[]) {
  if (!row(value) || !row(value.counts)) return fail();
  const raw = value.counts;
  const counts: AdviceCounts = {
    supported: count(raw.supported),
    contradicted: count(raw.contradicted),
    insufficient: count(raw.insufficient),
    abstained: count(raw.abstained),
    failed: count(raw.failed),
    skipped_short: count(raw.skipped_short),
    over_budget: count(raw.over_budget),
  };
  // The counts must follow the sentences they summarize: labels by label, abstentions and
  // failures by status (as the feedback contract counts them).
  const observed: AdviceCounts = {
    ...counts,
    supported: 0,
    contradicted: 0,
    insufficient: 0,
    abstained: 0,
    failed: 0,
  };
  for (const entry of units) {
    if (entry.label === 'SUPPORTED') observed.supported++;
    if (entry.label === 'CONTRADICTED') observed.contradicted++;
    if (entry.label === 'INSUFFICIENT') observed.insufficient++;
    if (entry.status === 'abstained') observed.abstained++;
    if (entry.status === 'failed') observed.failed++;
  }
  if (COUNTED.some((name) => observed[name] !== counts[name])) return fail();
  return { policy: text(value.policy), counts };
}

function readAdviceItem(item: unknown, sessionId: string): RegisteredAdvice {
  if (
    !row(item) ||
    item.criterion !== 'R2.support' ||
    item.mode !== 'advisory' ||
    item.affects_score !== false ||
    (item.task_type !== undefined && item.task_type !== 'relation') ||
    !optional(item.reconciliation)
  )
    return fail();
  const identity = registration(item.registration);
  const state = status(item.status);
  const label = relation(item.label ?? null);
  const { evidence: ids, sources } = selected(item.evidence_ids, item.citations, sessionId);
  const error = item.error_code ?? null;
  if (error !== null && typeof error !== 'string') return fail();
  if (optional(item.units) !== optional(item.aggregation)) return fail();
  const units = optional(item.units)
    ? undefined
    : Array.isArray(item.units)
      ? item.units.map((entry: unknown) => unit(entry, sessionId))
      : fail();
  if (units && new Set(units.map((entry) => entry.index)).size !== units.length) return fail();
  const summary = units ? aggregation(item.aggregation, units) : undefined;
  // The work-level relation must be the one its sentences give (148's conservative rule).
  if (units && summary && label !== null && label !== workRelation(units, summary.counts))
    return fail();
  const labelled = label !== null || ids.length > 0 || units?.some((entry) => entry.label !== null);
  if (state === 'completed') {
    if (identity?.scope !== 'external_candidate' || label === null || error !== null) return fail();
  } else if (state === 'synthetic_mechanism_only') {
    // 2026-10-12 decision 2: a synthetic registration may show its mechanism labels and evidence.
    if (identity?.scope !== 'synthetic_fixture' || (label === null && ids.length)) return fail();
  } else if (labelled) return fail();
  const advice: RegisteredAdvice = {
    criterion: 'R2.support',
    status: state,
    registration: identity,
    label,
    evidence_ids: ids,
    citations: sources,
    error_code: error,
    mode: 'advisory',
    affects_score: false,
  };
  if (units && summary) {
    advice.units = [...units].sort((a, b) => a.index - b.index);
    advice.aggregation = summary;
  }
  return advice;
}

function invalidAdvice(): RegisteredAdvice {
  return {
    criterion: 'R2.support',
    status: 'unavailable',
    registration: null,
    label: null,
    evidence_ids: [],
    citations: [],
    error_code: 'model_prediction_invalid',
    mode: 'advisory',
    affects_score: false,
  };
}

export function readRegisteredAdvice(
  value: unknown,
  sessionId: string,
): RegisteredAdvice[] | undefined {
  if (value === undefined || value === null) return undefined;
  if (!Array.isArray(value)) return [invalidAdvice()];
  // Criterion advice (§8 follow-up) is not relation advice: skip it, never fail the block.
  const relationEntries = value.filter(
    (item: unknown) => !(row(item) && item.task_type === 'criterion'),
  );
  if (value.length && !relationEntries.length) return undefined;
  return relationEntries.map((item: unknown) => {
    try {
      return readAdviceItem(item, sessionId);
    } catch {
      return invalidAdvice();
    }
  });
}

/** Errors that mean the configured model did not run as registered. */
const failureCodes = new Set([
  'model_load_failed',
  'pretrained_encoder_dependencies_unavailable',
  'model_files_changed',
  'model_reference_invalid',
  'model_timeout',
  'model_infrastructure_failed',
  'model_prediction_invalid',
]);
const failedEntry = (entry: RegisteredAdvice) =>
  entry.status === 'failed' || failureCodes.has(entry.error_code ?? '');

function titleKey(
  advice: RegisteredAdvice[] | undefined,
  fallback: AdviceFallback,
): ModelAdviceCopyKey {
  const failed = advice?.filter(failedEntry) ?? [];
  if (failed.some((entry) => entry.error_code !== 'model_timeout')) return 'titleFailed';
  if (failed.length) return 'titleTimeout';
  if (!advice?.length && fallback === 'failed') return 'titleFailed';
  if (advice?.some((entry) => entry.error_code === 'all_units_abstained')) return 'titleAbstained';
  if (advice?.some((entry) => entry.status === 'synthetic_mechanism_only')) return 'titleSynthetic';
  if (advice?.some((entry) => entry.status === 'completed')) return 'titleCompleted';
  if (advice?.length || fallback === 'pending') return 'titlePending';
  return fallback === 'waiting' ? 'titleWaiting' : 'titleUnavailable';
}

/** The one-line state of the advice block, shown folded. */
export function registeredAdviceSummary(
  advice: RegisteredAdvice[] | undefined,
  language: FeedbackLanguage,
  fallback: AdviceFallback,
): string {
  return adviceCopy(language, titleKey(advice, fallback));
}

const TOO_LONG = 'unit_exceeds_encoder_limit';
/** A counted phrase; English says "1 contradicts" but "2 contradict". */
const counted = (language: FeedbackLanguage, key: ModelAdviceCopyKey, n: number) =>
  adviceCopy(language, (n === 1 ? `${key}One` : key) as ModelAdviceCopyKey, { n });
/** Non-zero sentence counts in a fixed order, in plain words (197 n4), e.g.
 * "1 句与材料矛盾 · 9 句太长，模型没有核查". */
export function adviceCountsText(entry: RegisteredAdvice, language: FeedbackLanguage) {
  if (!entry.units || !entry.aggregation) return undefined;
  const { counts } = entry.aggregation;
  const tooLong = entry.units.filter(
    (unit) => unit.status === 'abstained' && unit.reason_code === TOO_LONG,
  ).length;
  const parts: [ModelAdviceCopyKey, number][] = [
    ['countSupported', counts.supported],
    ['countContradicted', counts.contradicted],
    ['countInsufficient', counts.insufficient],
    ['countTooLong', tooLong],
    ['countAbstained', counts.abstained - tooLong],
    ['countFailed', counts.failed],
    ['countShort', counts.skipped_short],
    ['countOverBudget', counts.over_budget],
  ];
  const shown = parts.filter(([, n]) => n > 0).map(([key, n]) => counted(language, key, n));
  return shown.length ? shown.join(adviceCopy(language, 'countSeparator')) : undefined;
}
/** A result is shown only when it was produced; failures and abstentions are never adopted. */
const shownResult = (entry: RegisteredAdvice) =>
  (entry.status === 'completed' || entry.status === 'synthetic_mechanism_only') && entry.label
    ? entry.label
    : null;

/** The R2.support row's one line while it is closed: what the model said, never scored; red
 * only for a contradiction; "模型建议" with the grey mark while it waits for a model. Undefined
 * when there is no advice to speak of (the row then asks its question). */
export function adviceRowLine(
  advice: RegisteredAdvice[] | undefined,
  language: FeedbackLanguage,
  fallback: AdviceFallback,
): { text: string; tone: 'bad' | 'ink'; waiting?: true } | undefined {
  const key = titleKey(advice, fallback);
  // Waiting for a model: "模型建议" with the grey mark (frontend-style 3.6).
  if (key === 'titleWaiting') return { text: adviceCopy(language, key), tone: 'ink', waiting: true };
  if (!advice?.length && key === 'titleUnavailable') return undefined;
  const C = (k: ModelAdviceCopyKey, values?: Record<string, string | number>) =>
    adviceCopy(language, k, values);
  if (key === 'titleAbstained') return { text: C('rowAdvice', { what: C('rowAbstained') }), tone: 'ink' };
  if (key !== 'titleCompleted') return { text: C(key), tone: 'ink' };
  const lead = advice?.find((entry) => entry.units) ?? advice?.find((entry) => shownResult(entry));
  const result = lead && shownResult(lead);
  if (result === 'CONTRADICTED') {
    const n = lead?.units?.filter((unit) => unit.label === 'CONTRADICTED').length || 1;
    return { text: C('rowAdvice', { what: counted(language, 'countContradicted', n) }), tone: 'bad' };
  }
  if (result === 'SUPPORTED') return { text: C('rowAdvice', { what: C('rowSupported') }), tone: 'ink' };
  return { text: C('rowAdvice', { what: C('rowInsufficient') }), tone: 'ink' };
}

function failureKey(code: string | null): ModelAdviceCopyKey {
  switch (code) {
    case 'pretrained_encoder_dependencies_unavailable':
      return 'failDependencies';
    case 'model_files_changed':
      return 'failFilesChanged';
    case 'model_reference_invalid':
      return 'failReference';
    case 'evidence_unavailable':
      return 'failEvidence';
    case 'model_result_unconfirmed':
      return 'failUnconfirmed';
    case 'model_timeout':
      return 'failTimeout';
    case 'model_infrastructure_failed':
      return 'failInfrastructure';
    case 'claim_not_available':
      return 'failClaim';
    case 'model_prediction_invalid':
      return 'failInvalid';
    case 'model_load_failed':
      return 'failLoad';
    case 'all_units_abstained':
      return 'failAllAbstained';
    default:
      return 'failDefault';
  }
}
const KINDS: Record<string, ModelAdviceCopyKey> = {
  linear: 'kindLinear',
  probability_fusion: 'kindFusion',
  huggingface_encoder: 'kindEncoder',
  numpy_attention: 'kindAttention',
  legacy_character_mlp: 'kindLegacy',
  constant: 'kindConstant',
};
const TIERS: Record<string, ModelAdviceCopyKey> = {
  G0: 'tierG0',
  G1: 'tierG1',
  G2: 'tierG2',
  G2v: 'tierG2v',
};
const STAGES: Record<string, ModelAdviceCopyKey> = {
  supervised_finetuned: 'stageSupervised',
  pretrained_untrained_heads: 'stagePretrained',
};
const REFERENCE_KINDS: Record<string, ModelAdviceCopyKey> = {
  material: 'refMaterial',
  config: 'refConfig',
  product: 'refProduct',
  test: 'refTest',
  role_reply: 'refRoleReply',
  role_turn: 'refRoleTurn',
  event: 'refEvent',
};
const named = (
  table: Record<string, ModelAdviceCopyKey>,
  value: string,
  language: FeedbackLanguage,
) => (table[value] ? adviceCopy(language, table[value]) : value);
const number = (value: number) => String(Number(value.toFixed(4)));
// Long sentences are excerpted; the full sentence stays in the learner's own work.
const EXCERPT = 120;
const excerpt = (quote: string) => {
  const chars = Array.from(quote);
  return chars.length > EXCERPT ? `${chars.slice(0, EXCERPT).join('')}…` : quote;
};

/** Registration identity lines: model, type, revision, training data, weights and fusion. */
function identityLines(identity: ModelRegistration, language: FeedbackLanguage): string[] {
  const C = (key: ModelAdviceCopyKey, values?: Record<string, string | number>) =>
    adviceCopy(language, key, values);
  const lines = [C('model', { id: identity.id })];
  if (identity.kind) lines.push(C('kind', { kind: named(KINDS, identity.kind, language) }));
  lines.push(C('revision', { revision: identity.model_revision }));
  if (identity.dataset) {
    const parts = [identity.dataset.dataset_id];
    parts.push(...identity.dataset.label_tiers.map((tier) => named(TIERS, tier, language)));
    parts.push(
      C('datasetManifest', { sha: identity.dataset.dataset_manifest_sha256.slice(0, 12) }),
    );
    lines.push(C('dataset', { dataset: parts.join(' · ') }));
  }
  if (identity.weights_stage)
    lines.push(C('stage', { stage: named(STAGES, identity.weights_stage, language) }));
  for (const member of identity.components ?? []) {
    const weight =
      member.alpha ?? (identity.fusion && memberWeight(member.role, identity.fusion.alpha));
    lines.push(
      C(member.role === 'left' ? 'componentLeft' : 'componentRight', {
        id: member.id,
        kind: named(KINDS, member.kind, language),
        weight: weight === undefined || weight === null ? '—' : number(weight),
      }),
    );
  }
  if (identity.fusion) {
    lines.push(
      C('fusion', {
        alpha: number(identity.fusion.alpha),
        threshold: number(identity.fusion.evidence_threshold),
      }),
      C(identity.fusion.fusion_gain_observed ? 'fusionGain' : 'fusionNoGain'),
    );
  }
  return lines;
}

const RELATION_ORDER: Record<Relation, number> = { CONTRADICTED: 0, INSUFFICIENT: 1, SUPPORTED: 2 };

/** The advice block inside the R2.support row's basis (195, 2026-10-24): a heading line with the
 * state, the counts in plain words and the work-level conclusion; then only the sentences the
 * model labelled, contradictions first (too long and unjudged ones are counted, not listed); one
 * provenance line. Model identity goes to "⋯ → About this workspace"; it stays here as a hidden
 * record. Confidence is never a number: with the lens open it is the lens's short bar. */
export function updateRegisteredAdvice(
  container: HTMLElement,
  advice: RegisteredAdvice[] | undefined,
  language: FeedbackLanguage,
  openReference: (ref: ObjectRef) => void,
  fallback: AdviceFallback,
  /** The cited object's name and version, with a screen-reader label, when the host knows it. */
  nameOf?: (ref: ObjectRef) => { text: string; label: string },
  options: { lens?: boolean; sessionId?: string } = {},
): void {
  const doc = container.ownerDocument;
  const C = (key: ModelAdviceCopyKey, values?: Record<string, string | number>) =>
    adviceCopy(language, key, values);
  const element = <K extends keyof HTMLElementTagNameMap>(tag: K, content: string) => {
    const node = doc.createElement(tag);
    node.textContent = content;
    return node;
  };
  const marked = <K extends keyof HTMLElementTagNameMap>(tag: K, content: string, mark: string) => {
    const node = element(tag, content);
    node.setAttribute(mark, '');
    return node;
  };
  let block = container.querySelector<HTMLElement>('[data-model-advice]');
  if (!block) {
    block = element('div', '');
    block.dataset.modelAdvice = 'true';
    block.className = 'model-advice';
    block.tabIndex = -1;
    const head = element('div', '');
    head.className = 'model-advice__head';
    head.setAttribute('data-model-advice-head', '');
    const body = element('div', '');
    body.className = 'model-advice__body';
    body.setAttribute('data-model-advice-body', '');
    block.append(head, body);
    container.replaceChildren(block);
  }
  const head = block.querySelector<HTMLElement>('[data-model-advice-head]');
  const body = block.querySelector<HTMLElement>('[data-model-advice-body]');
  if (!head || !body) throw Error('Invalid model advice view');
  const focused = body.contains(doc.activeElement);
  const focusKey =
    doc.activeElement instanceof HTMLElement
      ? doc.activeElement.dataset.modelReferenceKey
      : undefined;
  const title = marked(
    'span',
    registeredAdviceSummary(advice, language, fallback),
    'data-model-advice-title',
  );
  // Waiting for a model is the grey mark beside "Model advice"; the body says what is shown now.
  if (titleKey(advice, fallback) === 'titleWaiting') title.append(modelWaitNode(doc, '', language));
  const headline: HTMLElement[] = [title];
  if (advice?.some((entry) => entry.registration?.scope === 'synthetic_fixture'))
    headline.push(marked('span', C('syntheticNotice'), 'data-model-advice-notice'));
  // 2026-10-12 decision 5: sentences first; the work-level conclusion follows, quieter.
  const lead = advice?.find((entry) => entry.units);
  const counts = lead && adviceCountsText(lead, language);
  if (counts) headline.push(marked('span', counts, 'data-model-advice-counts'));
  const conclusion = lead && shownResult(lead);
  if (conclusion)
    headline.push(marked('span', C(`conclusion${conclusion}`), 'data-model-advice-conclusion'));
  head.replaceChildren(...headline);
  const reference = (source: ObjectRef, key: string) => {
    const kind = REFERENCE_KINDS[source.kind];
    const name = nameOf?.(source);
    const button = element(
      'button',
      name?.text ??
        `${kind ? C(kind) : C('refOther')} ${source.object_id} · ${C('refVersion', { n: source.version })}`,
    );
    if (name) button.setAttribute('aria-label', name.label);
    button.type = 'button';
    button.className = 'chip';
    button.dataset.modelReference = JSON.stringify(source);
    button.dataset.modelReferenceKey = key + JSON.stringify(source);
    button.addEventListener('click', () => openReference(source));
    return button;
  };
  const rows: HTMLElement[] = [];
  for (const [position, entry] of (advice ?? []).entries()) {
    const section = element('section', '');
    section.dataset.modelAdviceEntry = String(position);
    const result = shownResult(entry);
    const adopted = entry.status === 'completed' || entry.status === 'synthetic_mechanism_only';
    // Why nothing was adopted comes first; the labelled sentences follow.
    // When every sentence went unjudged, the count line above already says why.
    const counted = entry.error_code === 'all_units_abstained' && !!adviceCountsText(entry, language);
    if (entry.error_code && entry.error_code !== 'synthetic_mechanism_only') {
      if (!counted) section.append(element('p', C(failureKey(entry.error_code))));
      if (!result) section.append(element('p', C('notAdopted')));
    }
    if (entry.units) {
      const labelled = adopted
        ? entry.units
            .filter((unit) => unit.label !== null)
            .sort(
              (a, b) =>
                RELATION_ORDER[a.label as Relation] - RELATION_ORDER[b.label as Relation] ||
                a.index - b.index,
            )
        : [];
      if (labelled.length) {
        const list = element('ol', '');
        list.setAttribute('data-model-units', '');
        for (const unit of labelled) {
          const item = element('li', '');
          item.dataset.modelUnit = String(unit.index);
          item.dataset.unitStatus = unit.status;
          item.dataset.unitLabel = unit.label ?? '';
          const line = element('div', '');
          line.setAttribute('data-unit-line', '');
          const tag = marked('span', C(`label${unit.label as Relation}`), 'data-unit-result');
          tag.dataset.tone = unit.label ?? '';
          line.append(tag);
          // The lens shows how sure the model was as its short bar; never a decimal.
          if (options.lens && typeof unit.confidence === 'number')
            line.append(renderMeter(doc, sureMeter(unit.confidence, language)));
          // The same object cited twice (two passages of one document) is one source here.
          const cited = new Set<string>();
          for (const [index, source] of unit.citations.entries()) {
            const same = JSON.stringify([source.kind, source.object_id, source.version, source.config_version ?? null]);
            if (cited.has(same)) continue;
            cited.add(same);
            line.append(reference(source, `${position}:${unit.index}:${index}:`));
          }
          item.append(element('blockquote', excerpt(unit.quote)), line);
          list.append(item);
        }
        section.append(list);
      }
      const note = element('div', '');
      note.setAttribute('data-model-units-note', '');
      note.append(element('p', C('unitsPolicy')));
      section.append(note);
    } else {
      if (result) section.append(element('p', C('relation', { label: C(`label${result}`) })));
      for (const [index, source] of entry.citations.entries())
        section.append(reference(source, `${position}:work:${index}:`));
    }
    if (entry.registration) {
      if (entry.registration.scope === 'external_candidate')
        section.append(marked('p', C('externalNotice'), 'data-model-advice-provenance'));
      // Identity is a workbench internal: kept here as a hidden record, read in About.
      const identity = element('div', '');
      identity.setAttribute('data-model-identity', '');
      identity.hidden = true;
      const lines = identityLines(entry.registration, language);
      for (const text of lines) identity.append(element('p', text));
      section.append(identity);
      noteAboutFact(options.sessionId, `relation-model:${position}`, {
        label: C('aboutRelationModel'),
        value: lines.join(C('countSeparator')),
      });
    }
    rows.push(section);
  }
  if (!rows.length)
    rows.push(element('p', C(fallback === 'waiting' ? 'emptyWaiting' : 'emptyUnavailable')));
  body.replaceChildren(...rows);
  if (focused) {
    const target = [
      ...body.querySelectorAll<HTMLButtonElement>('button[data-model-reference]'),
    ].find((button) => button.dataset.modelReferenceKey === focusKey);
    (target ?? block).focus();
  }
}

type RecordedProvenance = {
  provider?: unknown;
  model?: unknown;
  support_model?: unknown;
} | null;
const recordedName = (value: unknown) => {
  if (!row(value) || typeof value.provider !== 'string' || typeof value.model !== 'string')
    return undefined;
  if (value.provider === 'not_configured' || value.model === 'not_configured') return null;
  if (!value.provider || !value.model || value.model === 'not_recorded') return undefined;
  return `${value.provider} · ${value.model}`;
};
/** The evaluation (Judge) model recorded with this feedback, and the support model when it
 * was configured apart. Read from the stored provenance only; never a configured default. */
export function evaluationModelText(
  provenance: RecordedProvenance | undefined,
  language: FeedbackLanguage,
): string {
  const judge = recordedName(provenance);
  const parts = [
    judge === null
      ? adviceCopy(language, 'evaluationNotConnected')
      : judge === undefined
        ? adviceCopy(language, 'evaluationNotRecorded')
        : adviceCopy(language, 'evaluationModel', { name: judge }),
  ];
  const support = row(provenance) ? recordedName(provenance.support_model) : undefined;
  if (support) parts.push(adviceCopy(language, 'supportModel', { name: support }));
  return parts.join(adviceCopy(language, 'countSeparator'));
}
/** The evaluation model as a value for "⋯ → About this workspace". */
export function evaluationModelValue(
  provenance: RecordedProvenance | undefined,
  language: FeedbackLanguage,
): string {
  const judge = recordedName(provenance);
  const parts = [
    judge === null
      ? adviceCopy(language, 'valueNotConnected')
      : judge === undefined
        ? adviceCopy(language, 'valueNotRecorded')
        : judge,
  ];
  const support = row(provenance) ? recordedName(provenance.support_model) : undefined;
  if (support) parts.push(adviceCopy(language, 'supportModel', { name: support }));
  return parts.join(adviceCopy(language, 'countSeparator'));
}
/** The recorded evaluation model: a workbench internal, kept with the report as a hidden record
 * and noted for "⋯ → About this workspace" (195, 2026-10-24). */
export function evaluationModelLine(
  doc: Document,
  provenance: RecordedProvenance | undefined,
  language: FeedbackLanguage,
  sessionId?: string,
): HTMLElement {
  const line = doc.createElement('p');
  line.className = 'muted';
  line.dataset.evaluationModel = '';
  line.textContent = evaluationModelText(provenance, language);
  line.hidden = true;
  noteAboutFact(sessionId, 'evaluation-model', {
    label: adviceCopy(language, 'aboutEvaluationModel'),
    value: evaluationModelValue(provenance, language),
  });
  return line;
}

/** Layout of the advice block; colours come from the workbench tokens, so dark mode follows. */
export const MODEL_ADVICE_STYLE =
  '.native-feedback .model-advice{display:grid;gap:8px;padding:12px 14px;border-radius:var(--r-md);background:var(--fill)}' +
  '.native-feedback .model-advice:focus{outline:none}' +
  '.native-feedback [data-model-advice-head]{display:grid;gap:2px}' +
  '.native-feedback [data-model-advice-title]{color:var(--ink-2);font-size:12px;font-weight:600}' +
  '.native-feedback [data-model-advice-notice],.native-feedback [data-model-advice-conclusion],.native-feedback [data-model-advice-counts]{font-size:13px;line-height:1.5}' +
  '.native-feedback [data-model-advice-counts]{color:var(--ink-2)}' +
  '.native-feedback [data-model-advice-notice]{color:var(--ink-2)}' +
  '.native-feedback [data-model-advice-conclusion]{color:var(--ink-3)}' +
  '.native-feedback [data-model-advice-body]{display:grid;gap:8px}' +
  '.native-feedback [data-model-advice-body] section{display:grid;gap:6px;margin:0}' +
  '.native-feedback [data-model-advice-body] p{margin:0;color:var(--ink-2);font-size:13px;line-height:1.5}' +
  '.native-feedback [data-model-units]{list-style:none;display:grid;gap:10px;margin:2px 0;padding:0}' +
  '.native-feedback [data-model-unit] blockquote{margin:0;padding:0;border:0;color:var(--ink);font:400 14.5px/1.6 var(--serif)}' +
  '.native-feedback [data-unit-line]{display:flex;flex-wrap:wrap;align-items:center;gap:4px 8px;margin-top:4px}' +
  '.native-feedback [data-unit-result]{display:inline-flex;align-items:center;min-height:20px;padding:1px 8px;border-radius:var(--r-pill);background:var(--fill-2);color:var(--ink-2);font-size:11.5px;font-weight:600;white-space:nowrap}' +
  '.native-feedback [data-unit-result][data-tone="CONTRADICTED"]{background:var(--bad-tint);color:var(--bad)}' +
  '.native-feedback [data-unit-result][data-tone="SUPPORTED"]{background:var(--good-tint);color:var(--good)}' +
  '.native-feedback [data-unit-result][data-tone="INSUFFICIENT"]{background:transparent;outline:1px dashed var(--ink-4);outline-offset:-1px;color:var(--ink-3)}' +
  '.native-feedback [data-model-advice] .chip{margin:0}' +
  '.native-feedback [data-model-advice-body] [data-model-units-note] p,.native-feedback [data-model-advice-body] p[data-model-advice-provenance]{color:var(--ink-3);font-size:12px;line-height:1.5}';
