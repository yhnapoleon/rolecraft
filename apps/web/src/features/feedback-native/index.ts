import { feedbackCoverageText } from './coverage';
import {
  MODEL_ADVICE_STYLE,
  evaluationModelLine,
  updateRegisteredAdvice,
  type RegisteredAdvice,
  type AdviceFallback,
} from './model-advice';
import type { SubmissionRuleCheck, SubmitInput, _RuleScoreRange } from '../../contracts-v2';
/** Native DOM submission/review surface. Inject the shared client; no credentials,
 * queue, mutation journal, global navigation or React root is created here. */
import { mountReviewControls, isSubmitDecision } from './review-controls';
import { feedbackText, type FeedbackLanguage } from './localization';
import {
  declaredPurpose,
  feedbackShortResult,
  reviewedAs,
  ruleItems,
  type PurposeChoice,
} from './short-summary';
import { evaluationVersionLine } from './evaluation-version';
import { itemDetail, renderRuleLines, ruleLines } from './rule-lines';
import { renderDecisions } from './business-decisions';
import { criterionWeightText } from './score-range';
import { sealReadOnly } from './read-only-notice';
import { criterionLabels } from './criteria';
import { exactRefKey } from './exact-ref';
import {
  mountPresubmitCard,
  PRESUBMIT_STYLE,
  submissionFactLine,
  type SentenceResult,
} from './presubmit';
import {
  attachmentLine,
  attachmentSlip,
  snapshotHeading,
  submitLabel,
  versionWords,
} from './delivery';
import { mountDecisionCards } from './decision-cards';
import {
  coverView,
  deliveryNote,
  elapsedWords,
  rememberDelivery,
  renderCover,
  STAMP_PRESS_MS,
} from './result-cover';
import type { ObjectRef, EvidenceRefV2, WorkProductVersion } from '../workspace/contract-types';
import { readCatalog, referenceLabel, type ReferenceCatalog } from '../../reference-catalog';
import type { EvidencePick } from '../../v4-host';
import { EVIDENCE_KINDS, evidenceSummary } from '../../evidence-picker';
import type { RecognitionRecord } from '../recognition-native/badge';
import { lensOn, onLensChange } from '../recognition-native/lens';
import { splitRecognitionPrefix } from '../recognition-native/prefix';
import { renderSentenceLens } from '../recognition-native/sentences';
import { renderExplanationTag, renderSignals } from '../recognition-native/signals';

export type SelectedProduct = Pick<
  WorkProductVersion,
  'session_id' | 'product_id' | 'version' | 'title' | 'removed_at' | 'author'
> & { purpose?: string };
type Item = {
  applicability?: 'applicable' | 'not_applicable' | 'undetermined' | 'unknown';
  criterion: string;
  explanation: string;
  source: string;
  label: string;
  rule_bound?: { lower: string; upper: string } | null;
  citations: EvidenceRefV2[];
};
export type FeedbackSemanticStatus = 'waiting_for_model' | 'available' | 'pending' | 'failed';
export type Report = {
  model_advice?: RegisteredAdvice[];
  /** Recognizer records that shaped this feedback (relation, decision, arbiter, ...). */
  recognition?: RecognitionRecord[];
  semantic_status?: FeedbackSemanticStatus;
  id: string;
  version: number;
  subject: ObjectRef;
  items: Item[];
  rule_items?: Item[] | null;
  verified_facts?:
    | {
        subject?: ObjectRef;
        status?: 'verified' | 'partial' | 'unknown';
        summary: string[];
        references: { verified_ref?: EvidenceRefV2 | null }[];
      }[]
    | null;
  historical_responsibilities?:
    | { entries: { criterion: string; explanation: string; sources: EvidenceRefV2[] }[] }[]
    | null;
  business_response: string;
  next_options: string[];
  /** Recorded with the feedback from the installed rubric weights; absent for earlier rubrics. */
  score_range?: _RuleScoreRange | null;
  read_projection?: 'partial' | null;
  /** Stored with the feedback; provider and model name the Judge slot that produced it. */
  provenance?: {
    evaluation_version?: string;
    provider?: unknown;
    model?: unknown;
    support_model?: unknown;
  } | null;
};
export type ReviewRecord = {
  id: string;
  version: number;
  session_id: string;
  subjects: ObjectRef[];
  purpose: string;
  question: string;
  decision: string | null;
  followup_of: ObjectRef[];
};
export type ReviewDraft = {
  subjects: ObjectRef[];
  purpose: string;
  question: string;
  decision: SubmitInput['decision'] | null;
  scope: string[];
  followup_of: ObjectRef[];
};
export interface FeedbackNativeState {
  /** Fixed session language supplied by the shared adapter; never browser locale. */
  workLanguage?: FeedbackLanguage;
  /** UI preference only; stored feedback keeps its original language. */
  uiLanguage?: FeedbackLanguage;
  products: SelectedProduct[];
  reviews?: ReviewRecord[];
  reviewHistoryAvailable?: boolean;
  submission?: { ref: ObjectRef; products: ObjectRef[]; decision: string } | null;
  submissions?: { ref: ObjectRef; products: ObjectRef[]; decision: string }[];
  reports: Report[];
  responses?: {
    id: string;
    version?: number;
    session_id?: string;
    feedback?: ObjectRef;
    kind: 'objection' | 'supplement';
    text: string;
  }[];
  /** Names for cited objects (documents, test runs, work, deliveries), from the timeline read. */
  references?: ReferenceCatalog;
  /** Feedback slot status only. Never copy a colleague/role mode here. */
  semanticStatus?: FeedbackSemanticStatus;
  /** Legacy adapter field; intentionally ignored by semantic rendering. */
  modelMode?: 'placeholder' | 'provider';
  status: 'active' | 'paused' | 'submitted';
  busy: boolean;
  pending?: boolean;
  /** Presentation only; request identity and recovery remain in the host journal. */
  awaitingFeedback?: boolean;
  /** The records point the shown products and submissions were read at. */
  point?: string;
  failedFeedback?: boolean;
  /** Presentation only: the feedback job's stage as the server reports it while it is written. */
  feedbackPhase?: 'queued' | 'running';
  /** When the wait for this delivery's feedback began (ms since epoch), for the seconds shown. */
  feedbackSince?: number;
  /** When each delivery was made, by submission id: the server's time where its records carry
   * one, else the moment this browser delivered it. Absent for deliveries made elsewhere. */
  submittedAt?: Readonly<Record<string, string>>;
  error?: string;
}
/** The exact versions and decision a person chooses to submit. */
export type SubmitChoice = { decision: SubmitInput['decision']; products: ObjectRef[] };
/** What the submission panel shows as chosen, including no decision yet. */
export type RememberedChoice = { decision: string; products: ObjectRef[] };
export interface FeedbackNativeAdapter {
  snapshot(): FeedbackNativeState;
  subscribe(callback: () => void): () => void;
  review?(input: ReviewDraft): Promise<unknown>;
  submit(input: SubmitChoice): Promise<unknown>;
  /** Read-only: the rule items submitting this choice now would give. Nothing is saved. */
  previewSubmission?(input: SubmitChoice): Promise<SubmissionRuleCheck>;
  /** Read-only, recognition layer: the sentence labels of the same choice, computed after the
   * rule check (slower; nothing when the layer is off). */
  previewRecognition?(input: SubmitChoice): Promise<SentenceResult>;
  /** Read-only: a saved submission checked again at its own point. */
  submissionRuleCheck?(submission: ObjectRef): Promise<SubmissionRuleCheck>;
  canPreview?: boolean;
  /** Presentation only: the panel's last choice, kept in this page's memory, never stored. */
  rememberChoice?(choice: RememberedChoice | null): void;
  rememberedChoice?(): RememberedChoice | undefined;
  respond(input: {
    feedback_id: string;
    feedback_version: number;
    kind: 'objection' | 'supplement';
    section:
      | 'general'
      | 'verified_facts'
      | 'historical_responsibilities'
      | 'rule_items'
      | 'model_advice';
    criterion?: string;
    text: string;
    evidence: EvidenceRefV2[];
  }): Promise<unknown>;
  beginRevision(input: { parent_submission: ObjectRef; reason: string }): Promise<unknown>;
  refresh(): Promise<unknown>;
  recover?(): Promise<unknown>;
  retry?(): Promise<unknown>;
  canRetry?: boolean;
  openReference(ref: ObjectRef | EvidenceRefV2): void;
  chooseEvidence?(pick?: EvidencePick): Promise<EvidenceRefV2[]>;
  readDraft(key: string): { text: string; evidence: EvidenceRefV2[] } | undefined;
  keepDraft(key: string, draft: { text: string; evidence: EvidenceRefV2[] }): Promise<void>;
  canReview?: boolean;
  canSubmit?: boolean;
  canRespond?: boolean;
}

export function feedbackSemanticPresentation(
  report: Pick<Report, 'semantic_status' | 'items'>,
  state: Pick<FeedbackNativeState, 'semanticStatus' | 'modelMode'>,
) {
  const status = report.semantic_status ?? state.semanticStatus;
  const advice =
    status === 'waiting_for_model'
      ? []
      : report.items.filter((item) => item.source === 'model_advice');
  return {
    status,
    advice,
    waitingForModel:
      status === 'waiting_for_model' || (status === undefined && advice.length === 0),
  };
}

function adviceFallback(report: Report | undefined, state: FeedbackNativeState): AdviceFallback {
  if (!report) return 'unavailable';
  const semantic = feedbackSemanticPresentation(report, state);
  if (semantic.status === 'failed') return 'failed';
  return semantic.waitingForModel ? 'waiting' : 'pending';
}

export { criterionLabels };
/** The status line: until the latest submission has feedback, it is being generated (the job is
 * queued or running); a failed job says not ready, and its own note offers a new request. */
export function feedbackNotice(state: FeedbackNativeState, language: FeedbackLanguage): string {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  // Once the delivery is saved, reading the records again is not a new confirmation: while its
  // feedback is still being generated the line keeps saying so (164 N10).
  const generating =
    state.status === 'submitted' &&
    !!state.submission &&
    !state.pending &&
    !state.failedFeedback &&
    !state.reports.some((r) => r.subject.object_id === state.submission?.ref.object_id);
  if (state.busy && !generating)
    return T('正在等待服务端确认…', 'Waiting for server confirmation…');
  if (state.pending)
    return T(
      '上一请求结果尚未确认，请先恢复。',
      'The previous request is unresolved. Recover its result first.',
    );
  if (state.status !== 'submitted')
    return T(
      '可以继续工作，选择准备交付的版本。',
      'Continue your work and select versions for submission.',
    );
  if (state.reports.some((r) => r.subject.object_id === state.submission?.ref.object_id))
    return T(
      '本次提交已保存，可以看反馈、提出异议或开始修订。',
      'Submission saved. Review feedback, raise a challenge or start revising.',
    );
  return state.failedFeedback
    ? T('本次提交已保存，反馈尚未就绪。', 'Submission saved. Feedback is not ready yet.')
    : T('本次提交已保存，反馈正在生成…', 'Submission saved. Feedback is being generated…');
}
export type FeedbackMountOptions = { surface?: 'all' | 'submission' | 'feedback' };

export function mountNativeFeedback(
  host: HTMLElement,
  adapter: FeedbackNativeAdapter,
  options: FeedbackMountOptions = {},
) {
  const doc = host.ownerDocument;
  const language = adapter.snapshot().uiLanguage ?? adapter.snapshot().workLanguage ?? 'zh';
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  const versionLabel = (n: number) => versionWords(n, language);
  const reduced = () =>
    doc.defaultView?.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', cls = '') => {
    const n = doc.createElement(tag);
    n.textContent = text;
    n.className = cls || (tag === 'h2' ? 'group-title' : tag === 'h3' ? 'row-title' : '');
    return n;
  };
  let destroyed = false;
  const selected = new Map<string, ObjectRef>();
  const selectedTitles = new Map<string, string>();
  const draftResponses = new Map<string, { text: string; evidence: EvidenceRefV2[] }>();
  // Presentation only: disclosure and purpose choice survive re-renders, not reloads.
  const openResults = new Set<string>();
  // Open recognition chains per report, kept across redraws (lens toggles, refreshes).
  const lensChains = new Map<string, Set<number>>();
  let playReading = false;
  const purposeChoices = new Map<string, PurposeChoice>();
  let savedDrafts: Promise<void> = Promise.resolve();
  let draftError: unknown;
  // Confirmed challenges and supplements show at once, until the next read lists them.
  type ResponseKind = 'objection' | 'supplement';
  const recorded: { feedback: string; kind: ResponseKind; text: string }[] = [];
  const recordedForms = new Map<string, ResponseKind>();
  const recordedText = (kind: ResponseKind) =>
    (kind === 'objection'
      ? T('异议已记录', 'Challenge recorded')
      : T('补证已记录', 'Additional evidence recorded')) +
    T(' · 等待核验', ' · Awaiting verification');
  const persist = (key: string, draft: { text: string; evidence: EvidenceRefV2[] }) => {
    const value = structuredClone(draft);
    savedDrafts = savedDrafts
      .then(() => adapter.keepDraft(key, value))
      .catch((error) => {
        draftError = error;
        failure.textContent = T(
          '本机保存未确认，请保留本页文字。',
          'Local saving is not confirmed. Keep the text on this page.',
        );
        failure.hidden = false;
      });
    return savedDrafts;
  };
  const key = exactRefKey;
  const root = el('section', '', 'native-feedback');
  root.setAttribute('aria-label', T('交付与反馈', 'Submission and feedback'));
  root.lang = language;
  const hiddenStyle = doc.createElement('style');
  hiddenStyle.textContent =
    '.native-feedback [hidden]{display:none!important}.native-feedback{min-width:0;overflow-wrap:anywhere}.native-feedback section,.native-feedback article{min-width:0}.native-feedback>section,.native-feedback article>section{margin-block:20px}.native-feedback .btn{white-space:normal;height:auto;min-height:34px;max-width:100%;margin:3px 5px 3px 0}.native-feedback .field-row{display:flex;align-items:flex-start;gap:8px;margin:8px 0}.native-feedback .field-row input{flex:none;margin-top:5px}.native-feedback blockquote{margin:10px 0;padding:8px 12px;border-inline-start:2px solid var(--line);color:var(--ink-2)}.native-feedback .group-title{margin-block:20px 10px}.native-feedback .row-title{margin-block:14px 8px}.native-feedback p{line-height:1.6}.native-feedback .textarea,.native-feedback .select{max-width:100%}.native-feedback [data-score-range]{color:var(--ink-2,#4b505b);font-size:13.5px;font-weight:600}' +
    MODEL_ADVICE_STYLE +
    PRESUBMIT_STYLE;
  root.append(hiddenStyle);
  const notice = el('p', '', 'muted');
  notice.setAttribute('role', 'status');
  notice.setAttribute('aria-live', 'polite');
  let lastReadError: string | undefined;
  const failure = el('p', '', 'inline-alert');
  failure.setAttribute('role', 'alert');
  failure.hidden = true;
  const submissions = el('section');
  submissions.append(el('h2', T('确认这次交付', 'Confirm this submission')));
  const selectedSummary = el('div');
  selectedSummary.setAttribute('aria-label', T('本次将提交的版本', 'Versions to submit'));
  const selection = el('div');
  selection.setAttribute('aria-label', T('选择确切作品版本', 'Select exact artifact versions'));
  selection.className = 'delivery-versions';
  // The four decisions as paper options; a choice re-runs the pre-submission preview.
  const choice = mountDecisionCards(doc, language, () => syncPreview());
  const receipt = el('div');
  const responseHistory = el('section');
  const reports = el('div');
  reports.setAttribute('aria-label', T('分段反馈', 'Feedback sections'));
  const revisions = el('section');
  const revisionReason = el('textarea', '', 'textarea');
  revisionReason.rows = 3;
  revisionReason.setAttribute('aria-label', T('这次准备怎样修订', 'What will you revise?'));
  revisionReason.placeholder = T(
    '保留上次提交，说明这次准备补充或调整什么。',
    'Keep the previous submission and describe what you will add or change.',
  );
  revisionReason.value = adapter.readDraft('revision')?.text ?? '';
  revisionReason.addEventListener('input', () => {
    void persist('revision', { text: revisionReason.value, evidence: [] });
  });
  const button = (text: string, action: () => Promise<unknown> | void, primary = false) => {
    const n = el('button', text, 'btn' + (primary ? ' primary' : ''));
    n.type = 'button';
    n.addEventListener('click', () => {
      void act(action);
    });
    return n;
  };
  async function act(action: () => Promise<unknown> | void) {
    failure.hidden = true;
    try {
      await action();
    } catch (error) {
      if (!destroyed) {
        failure.textContent =
          error instanceof Error
            ? error.message
            : T(
                '操作尚未确认，你填写的内容仍保留。',
                'The action is not confirmed. Your text is retained.',
              );
        failure.hidden = false;
      }
    } finally {
      if (!destroyed) render();
    }
  }
  const submit = button(
    T('提交选中的版本', 'Submit selected versions'),
    async () => {
      if (!isSubmitDecision(choice.value))
        throw Error(
          T(
            '请明确本次决定。停止或暂缓也可以交付。',
            'Specify your decision. You can also submit a no-go or deferral.',
          ),
        );
      if (!selected.size)
        throw Error(T('请选择这次要交付的作品版本。', 'Select the artifact versions to submit.'));
      const decision = choice.value;
      const products = [...selected.values()];
      const at = new Date().toISOString();
      await adapter.submit({ decision, products });
      adapter.rememberChoice?.(null);
      // The decision, the moment and the versions are known here: the results page opens on its
      // cover at once and stamps it while the records are read back.
      rememberDelivery({
        sessionId: products[0]?.session_id ?? '',
        decision,
        at,
        products: products.map((ref) => {
          const shown = adapter
            .snapshot()
            .products.find((p) => p.product_id === ref.object_id && p.version === ref.version);
          return {
            ref,
            title: shown?.title ?? selectedTitles.get(key(ref)) ?? '',
            purpose: shown?.purpose,
          };
        }),
      });
      root.dispatchEvent(
        new CustomEvent('rolecraft:delivered', { bubbles: true, detail: { decision } }),
      );
    },
    true,
  );
  // Tests and scripts find the delivery's own button by this mark, whatever it says.
  submit.dataset.deliverySubmit = '';
  submit.classList.add('delivery-submit');
  // Pre-submission preview (2026-10-14): read-only, right above the submit button.
  const load =
    options.surface !== 'feedback' ? adapter.previewSubmission?.bind(adapter) : undefined;
  const preview = load
    ? mountPresubmitCard(doc, language, load, {
        recognize: adapter.previewRecognition?.bind(adapter),
        // The delivery dialog is the page: the preview is a section of it, so the work's
        // sentences sit on it directly as paper (dialog → work paper, no panel between).
        frame: 'flat',
      })
    : undefined;
  let restoring = preview ? adapter.rememberedChoice?.() : undefined;
  /** Put back the choice made before the panel was last closed, once its versions are listed. */
  function restoreChoice(state: FeedbackNativeState) {
    if (!restoring || !state.products.length) return;
    for (const ref of restoring.products) {
      const product = state.products.find(
        (p) => p.product_id === ref.object_id && p.version === ref.version && !p.removed_at,
      );
      if (!product) continue;
      selected.set(key(ref), ref);
      selectedTitles.set(key(ref), product.title || T('未命名作品', 'Untitled artifact'));
    }
    if (isSubmitDecision(restoring.decision) && !choice.value) choice.value = restoring.decision;
    restoring = undefined;
  }
  /** Preview the current choice; remember it for this page while the panel is open. */
  function syncPreview() {
    if (!preview) return;
    const state = adapter.snapshot();
    const open = state.status === 'active' && adapter.canPreview !== false;
    preview.element.hidden = !open;
    if (open && !restoring)
      adapter.rememberChoice?.({ decision: choice.value, products: [...selected.values()] });
    preview.update(
      open && isSubmitDecision(choice.value) && selected.size
        ? { decision: choice.value, products: [...selected.values()], point: state.point }
        : null,
    );
  }
  const retryFeedback = button(T('重新请求反馈', 'Request feedback again'), () =>
    adapter.retry?.(),
  );
  const failedNote = el(
    'p',
    T(
      '这次反馈没有完成。原提交仍保留，没有自动重试；你可以主动重新请求。',
      'This feedback did not complete. The submission is retained and no retry was made automatically. You can request it again.',
    ),
    'muted',
  );
  const recover = button(T('确认上一请求', 'Check the previous request'), () =>
    adapter.recover?.(),
  );
  submissions.classList.add('delivery-paper');
  submissions.append(
    el(
      'p',
      T(
        '提交会保留这些确切版本。反馈后可进入修订，原提交与原反馈继续保留。',
        'Submission preserves these exact versions. You can revise after feedback; the original submission and feedback remain available.',
      ),
      'muted',
    ),
    selection,
    selectedSummary,
    choice.element,
    ...(preview ? [preview.element] : []),
    submit,
    recover,
    receipt,
  );
  const revise = button(T('开始修订', 'Start a revision'), async () => {
    const current = adapter.snapshot().submission;
    if (!current) return;
    if (!revisionReason.value.trim())
      throw Error(T('请写下本次修订的方向。', 'Describe the direction of this revision.'));
    await savedDrafts;
    if (draftError)
      throw Error(
        T(
          '修订说明尚未保存，请先保留文字。',
          'The revision note is not saved. Keep a copy of your text.',
        ),
      );
    const reason = revisionReason.value;
    await adapter.beginRevision({ parent_submission: current.ref, reason });
    // Back to the board, with where to pick the work up: the unmet items of this delivery.
    root.dispatchEvent(
      new CustomEvent('rolecraft:revision-started', {
        bubbles: true,
        detail: revisionStart(adapter.snapshot(), current, language, reason),
      }),
    );
  });
  revisions.append(el('h2', T('接着修订', 'Continue revising')), revisionReason, revise);
  const refresh = button(T('查看最新反馈', 'Refresh feedback'), () => adapter.refresh());
  // The results cover sits first on the feedback page (it is never part of the submit panel).
  const coverHost = el('div', '', 'result-cover-host');
  let coverShown = '';
  let coverWaited = false;
  let ticker: ReturnType<typeof setInterval> | undefined;
  root.append(failure);
  if (options.surface !== 'submission') root.append(coverHost);
  root.append(notice, failedNote, retryFeedback);
  if (options.surface !== 'feedback') root.append(submissions);
  if (options.surface === 'feedback') root.append(recover);
  if (options.surface !== 'submission') root.append(refresh, reports, responseHistory, revisions);
  const reviewControls =
    options.surface !== 'submission' && adapter.review
      ? mountReviewControls(doc, adapter, language)
      : undefined;
  if (reviewControls) root.insertBefore(reviewControls.element, reports);
  host.replaceChildren(root);
  // The object's own name and version; the full name, with the action, for screen readers.
  const nameOf = (ref: ObjectRef | EvidenceRefV2) =>
    referenceLabel(ref, adapter.snapshot().references ?? readCatalog(null), language);
  function refs(parent: HTMLElement, values: (ObjectRef | EvidenceRefV2)[]) {
    const row = el('div');
    for (const ref of values) {
      const name = nameOf(ref);
      const link = button(name.text, () => adapter.openReference(ref));
      link.setAttribute('aria-label', name.label);
      link.dataset.referenceKind = ref.kind;
      // Lets the reader return focus here even after the panel rebuilds this button.
      link.dataset.referenceKey = key(ref);
      row.append(link);
      if ('quote' in ref && ref.quote) {
        if (language === 'en' && /[\u4e00-\u9fff]/u.test(ref.quote))
          row.append(el('small', 'Chinese source', 'muted'));
        row.append(el('blockquote', ref.quote));
      }
    }
    parent.append(row);
  }
  function responseForm(
    report: Report,
    criterion?: string,
    section:
      | 'general'
      | 'verified_facts'
      | 'historical_responsibilities'
      | 'rule_items'
      | 'model_advice' = 'general',
  ) {
    const id = [report.id, report.version, section, criterion ?? ''].join(':');
    const draft = draftResponses.get(id) ?? adapter.readDraft(id) ?? { text: '', evidence: [] };
    draftResponses.set(id, draft);
    const form = el('details');
    form.dataset.responseId = id;
    form.append(el('summary', T('提出异议或补充依据', 'Challenge or supplement the evidence')));
    const body = el('textarea', '', 'textarea');
    body.rows = 3;
    body.value = draft.text;
    body.setAttribute('aria-label', T('异议或补证内容', 'Challenge or additional evidence'));
    body.addEventListener('input', () => {
      draft.text = body.value;
      void persist(id, draft);
    });
    const evidence = el('p', evidenceSummary(draft.evidence), 'muted');
    const choose = button(T('选择依据', 'Choose evidence'), async () => {
      if (adapter.chooseEvidence) {
        draft.evidence = await adapter.chooseEvidence({
          kinds: EVIDENCE_KINDS,
          selected: draft.evidence,
        });
        await persist(id, draft);
        evidence.textContent = evidenceSummary(draft.evidence);
      }
    });
    choose.disabled = !adapter.chooseEvidence;
    // What this form last recorded, shown beside it the moment the server confirms.
    const status = el('p', '', 'muted');
    status.setAttribute('role', 'status');
    const showRecorded = () => {
      const kind = recordedForms.get(id);
      status.textContent = kind ? recordedText(kind) : '';
      status.hidden = !kind;
    };
    showRecorded();
    const send = (kind: ResponseKind) => async () => {
      if (!draft.text.trim())
        throw Error(
          T('请写下具体的异议或补充内容。', 'Describe your challenge or additional evidence.'),
        );
      if (kind === 'supplement' && !draft.evidence.length)
        throw Error(
          T(
            '补证需要先选择至少一处原始引用。',
            'Choose at least one original reference before submitting evidence.',
          ),
        );
      await savedDrafts;
      if (draftError)
        throw Error(
          T(
            '回应草稿尚未保存，请先保留文字。',
            'The response draft is not saved. Keep a copy of your text.',
          ),
        );
      const text = draft.text;
      await adapter.respond({
        feedback_id: report.id,
        feedback_version: report.version,
        kind,
        section,
        criterion,
        text,
        evidence: draft.evidence,
      });
      recorded.push({ feedback: report.id, kind, text });
      recordedForms.set(id, kind);
      showRecorded();
      draft.text = '';
      draft.evidence = [];
      await persist(id, draft);
      body.value = '';
      evidence.textContent = evidenceSummary([]);
    };
    const objection = button(T('记录异议', 'Record a challenge'), send('objection'));
    const supplement = button(T('提交补证', 'Submit additional evidence'), send('supplement'));
    objection.dataset.responseAction = 'objection';
    supplement.dataset.responseAction = 'supplement';
    objection.disabled = supplement.disabled =
      adapter.snapshot().busy || !!adapter.snapshot().pending || adapter.canRespond === false;
    form.append(
      body,
      evidence,
      choose,
      objection,
      supplement,
      status,
      el(
        'p',
        T(
          '记录关联后仍等待核验，不会自动改写原反馈或认定异议已解决。',
          'Linked records still await verification. They do not rewrite earlier feedback or automatically resolve a challenge.',
        ),
        'muted',
      ),
    );
    return form;
  }
  function reportPanel(report: Report) {
    const latest = adapter.snapshot().submission?.ref;
    const current =
      report.subject.kind === 'submission' &&
      (!latest ||
        (report.subject.object_id === latest.object_id &&
          report.subject.version === latest.version));
    const panel = el('article');
    panel.append(
      el(
        'h2',
        report.subject.kind === 'review'
          ? T('作品评审反馈', 'Artifact review feedback')
          : current
            ? T('最近提交的反馈', 'Latest submission feedback')
            : T('此前提交的反馈', 'Earlier submission feedback'),
      ),
    );
    const review =
      report.subject.kind === 'review'
        ? adapter
            .snapshot()
            .reviews?.find(
              (r) => r.id === report.subject.object_id && r.version === report.subject.version,
            )
        : undefined;
    const purposeLine = reviewedAs(review, language);
    if (purposeLine) panel.append(el('p', purposeLine, 'muted'));
    // A submission reads "第 N 次交付", like every other reference to it.
    refs(panel, [report.subject]);
    panel.append(evaluationVersionLine(doc, report, language));
    if (report.subject.kind === 'review') {
      if (review) {
        panel.append(
          el(
            'p',
            review.question ||
              T(
                '按作品形成时的信息评审。',
                'Reviewed against information available when the artifact was formed.',
              ),
            'muted',
          ),
        );
        refs(panel, review.subjects);
      }
    }
    // Detail stays as it was; it is folded behind the short result below.
    const body: Node[] = [];
    const facts = el('section');
    facts.append(el('h3', T('你做过的工作与依据', 'Your recorded work and evidence')));
    if (!report.verified_facts?.length)
      facts.append(
        el(
          'p',
          T(
            '事实记录还未就绪，不能据此判断你没有调查。',
            'Fact records are not ready. This does not show that you did no investigation.',
          ),
          'muted',
        ),
      );
    for (const snapshot of report.verified_facts ?? []) {
      if (snapshot.subject) refs(facts, [snapshot.subject]);
      facts.append(
        el(
          'p',
          snapshot.status === 'verified'
            ? T('规则核实', 'Verified by rules')
            : snapshot.status === 'partial'
              ? T(
                  '部分依据已核实，缺少的记录仍待核验',
                  'Some evidence is verified; missing records remain unverified',
                )
              : T('记录待核验', 'Records awaiting verification'),
          'muted',
        ),
      );
      for (const text of snapshot.summary.slice(0, 3)) facts.append(el('p', text));
      if (snapshot.summary.length > 3) {
        const details = el('details');
        details.append(el('summary', T('查看核实明细', 'View verification details')));
        for (const text of snapshot.summary.slice(3)) details.append(el('p', text));
        facts.append(details);
      }
      refs(
        facts,
        snapshot.references.flatMap((x) => (x.verified_ref ? [x.verified_ref] : [])),
      );
    }
    body.push(facts);
    const history = el('section');
    history.append(el('h3', T('历史行动与承诺', 'Past actions and commitments')));
    for (const snapshot of report.historical_responsibilities ?? [])
      for (const entry of snapshot.entries) {
        history.append(el('p', entry.explanation));
        refs(history, entry.sources);
      }
    if (!report.historical_responsibilities?.some((s) => s.entries.length))
      history.append(
        el(
          'p',
          T(
            '当前没有可展示的历史责任结论。',
            'No historical responsibility finding is currently available.',
          ),
          'muted',
        ),
      );
    body.push(history);
    const criteria = criterionLabels(language);
    const lines = ruleLines(ruleItems(report), criteria, language);
    const atSubmission = savedRuleCheck(report);
    const notApplicable = el('details');
    notApplicable.append(
      el('summary', T('查看本次未适用的验收项', 'View criteria not applicable to this submission')),
    );
    let inactive = 0;
    for (const item of ruleItems(report)) {
      const section = el('section');
      section.append(
        el('h3', criteria[item.criterion] ?? T('具体反馈项', 'Feedback criterion')),
        el(
          'p',
          item.source === 'verified_rule'
            ? T('规则核实', 'Verified by rules')
            : T('等待核验', 'Awaiting verification'),
          'muted',
        ),
        el('p', splitRecognitionPrefix(itemDetail(item, lines.premises)).text, 'rule-detail'),
      );
      // Recognition signals of this criterion: nothing by default, chips in the lens.
      const signed = renderSignals(doc, criterionRecords(report, item.criterion), language, {
        context: 'criterion',
        lens: lensOn(),
      });
      if (signed) section.append(signed);
      // 164 F17: the versions behind an unmet item, from the same rules at submission.
      const fact = submissionFactLine(item, atSubmission, report.rule_items, language);
      if (fact) {
        const line = el('p', fact);
        line.dataset.ruleFact = item.criterion;
        section.append(line);
      }
      if (item.rule_bound) {
        const labels: Record<string, string> = {
          NOT_MET: T('未满足', 'Not met'),
          PARTIAL: T('部分满足', 'Partially met'),
          MET: T('满足', 'Met'),
        };
        section.append(
          el(
            'p',
            item.rule_bound.lower === item.rule_bound.upper
              ? T('规则确定：', 'Rule finding: ') +
                  (labels[item.rule_bound.lower] ?? item.rule_bound.lower)
              : T('规则已核实范围：', 'Verified rule interval: ') +
                  (labels[item.rule_bound.lower] ?? item.rule_bound.lower) +
                  '—' +
                  (labels[item.rule_bound.upper] ?? item.rule_bound.upper) +
                  T(
                    '；范围内的具体判断仍待核验。',
                    '; the exact judgment within this interval remains unverified.',
                  ),
            'muted',
          ),
        );
      }
      const weight = criterionWeightText(report, item.criterion, language);
      if (weight) {
        const line = el('p', weight, 'muted');
        line.dataset.criterionWeight = item.criterion;
        section.append(line);
      }
      refs(section, item.citations);
      section.append(responseForm(report, item.criterion, 'rule_items'));
      if (item.label === 'NOT_APPLICABLE') {
        notApplicable.append(section);
        inactive++;
      } else body.push(section);
    }
    if (inactive) body.push(notApplicable);
    const coverage = el(
      'p',
      feedbackCoverageText(
        report,
        feedbackSemanticPresentation(report, adapter.snapshot()).advice,
        language,
      ),
      'muted',
    );
    coverage.dataset.feedbackCoverage = report.id;
    body.push(coverage);
    const semantic = el('section');
    semantic.append(
      el('h3', T('理由与证据的支持关系', 'Support between reasoning and evidence')),
      evaluationModelLine(doc, report.provenance, language),
    );
    // With the recognition lens open: this feedback's recognizer signals and the work sentence
    // by sentence, from the records stored with it. Closed: nothing.
    if (lensOn()) {
      const general = (report.recognition ?? []).filter((record) => !recordCriterion(record));
      // The sentence block below already counts the relation labels; no second chip for them.
      const chips = renderSignals(
        doc,
        general.filter((record) => !(record.task === 'relation' && Array.isArray(record.outputs?.units))),
        language,
        { context: 'feedback', lens: true },
      );
      if (chips) semantic.append(chips);
      if (general.some((record) => record.task === 'relation' && Array.isArray(record.outputs?.units))) {
        const key = `${report.id}:${report.version}`;
        if (!lensChains.has(key)) lensChains.set(key, new Set());
        semantic.append(
          renderSentenceLens(doc, {
            records: report.recognition ?? [],
            language,
            open: lensChains.get(key),
            play: playReading,
          }),
        );
      }
    }
    const { advice } = feedbackSemanticPresentation(report, adapter.snapshot());
    if (!advice.length || report.model_advice !== undefined) {
      const block = el('div');
      block.dataset.modelAdviceReport = report.id;
      semantic.append(block);
      updateRegisteredAdvice(
        block,
        report.model_advice,
        language,
        (ref) => adapter.openReference(ref),
        adviceFallback(report, adapter.snapshot()),
        nameOf,
      );
    }
    for (const item of advice) {
      // The reviewer's recognition prefix is never shown as text; the lens shows it as a tag.
      const split = splitRecognitionPrefix(item.explanation);
      if (lensOn()) {
        const tag = renderExplanationTag(doc, split, language);
        if (tag) semantic.append(tag);
      }
      semantic.append(el('p', T('模型建议 · ', 'Model advice · ') + split.text));
      refs(semantic, item.citations);
      semantic.append(responseForm(report, item.criterion, 'model_advice'));
    }
    for (const text of report.next_options) body.push(el('p', text, 'muted'));
    const id = `${report.id}:${report.version}`;
    const state = adapter.snapshot();
    const canReview = !!adapter.review && adapter.canReview !== false && state.status === 'active';
    panel.append(
      feedbackShortResult(doc, {
        report,
        language,
        review,
        reviews: state.reviews,
        semantic,
        lines: renderRuleLines(doc, lines, language),
        body,
        open: openResults.has(id),
        onToggle: (open) => {
          if (open) openResults.add(id);
          else openResults.delete(id);
        },
        prompt:
          review && canReview
            ? {
                name: `purpose-${id}`,
                selected:
                  purposeChoices.get(id) ?? declaredPurpose(review.subjects, state.products),
                disabled: state.busy || !!state.pending,
                select: (purpose) => purposeChoices.set(id, purpose),
                submit: (purpose) => void reviewAgain(review, purpose),
              }
            : undefined,
      }).element,
      renderDecisions(doc, report),
      responseForm(report),
    );
    return panel;
  }
  /** A saved submission checked again at its own point, read once per submission; null until
   * it arrives, or when it fails. Its arrival redraws the reports. */
  const savedChecks = new Map<string, SubmissionRuleCheck | null>();
  function savedRuleCheck(report: Report): SubmissionRuleCheck | null {
    const check = adapter.submissionRuleCheck?.bind(adapter);
    if (report.subject.kind !== 'submission' || !check || adapter.canPreview === false) return null;
    const id = key(report.subject);
    if (!savedChecks.has(id)) {
      savedChecks.set(id, null);
      check(report.subject)
        .then(
          (found) => savedChecks.set(id, found),
          () => savedChecks.set(id, null),
        )
        .finally(() => {
          if (!destroyed) render();
        });
    }
    return savedChecks.get(id) ?? null;
  }
  /** Same versions and question, now with the purpose the learner chose. */
  async function reviewAgain(review: ReviewRecord, purpose: PurposeChoice) {
    const request = adapter.review;
    if (!request) return;
    // Leave the panel first so the next render can list the new review.
    notice.tabIndex = -1;
    notice.focus({ preventScroll: true });
    await act(() =>
      request({
        subjects: structuredClone(review.subjects),
        purpose,
        question: review.question,
        decision: review.decision && isSubmitDecision(review.decision) ? review.decision : null,
        scope: [],
        followup_of: [],
      }),
    );
  }
  function renderSelected() {
    // The button says what it will do: which version, or how many.
    submit.textContent = submitLabel([...selected.values()], language);
    selectedSummary.replaceChildren(
      ...[...selected].map(([id, ref]) => {
        const row = el('p');
        row.append(
          el(
            'span',
            `${T('将提交：', 'To submit: ')}${selectedTitles.get(id)} · ${versionLabel(ref.version)} `,
          ),
        );
        row.append(
          button(T('查看', 'View'), () => adapter.openReference(ref)),
          button(T('取消选择', 'Deselect'), () => {
            selected.delete(id);
            render();
          }),
        );
        return row;
      }),
    );
  }
  /** The general response form of the latest delivery's feedback, opened, with focus in it. */
  function openSupplement() {
    const latest = reports.querySelector<HTMLElement>(':scope > article');
    const form = latest
      ? [...latest.querySelectorAll<HTMLDetailsElement>(':scope > details[data-response-id]')].at(-1)
      : undefined;
    if (!form) return;
    form.open = true;
    form.scrollIntoView({ block: 'center', behavior: reduced() ? 'auto' : 'smooth' });
    form.querySelector('textarea')?.focus({ preventScroll: true });
  }
  function openRevision() {
    revisions.scrollIntoView({ block: 'center', behavior: reduced() ? 'auto' : 'smooth' });
    revisionReason.focus({ preventScroll: true });
  }
  const waitSeconds = (state: FeedbackNativeState) =>
    state.feedbackSince ? (Date.now() - state.feedbackSince) / 1000 : undefined;
  function renderCoverNow(state: FeedbackNativeState) {
    const note = deliveryNote();
    const view = coverView(state, language, note);
    // Not tied to reads in flight, so the step does not flicker while records refresh; the
    // revision control itself still refuses while a request is busy.
    const canRevise =
      state.status === 'submitted' && !state.readOnly && !state.awaitingFeedback && !state.pending;
    const actions = view && {
      openReference: (ref: ObjectRef) => adapter.openReference(ref),
      ...(!view.waiting && adapter.canRespond !== false && !state.readOnly
        ? { supplement: openSupplement }
        : {}),
      ...(canRevise ? { revise: openRevision } : {}),
      backToBoard: state.status === 'active',
      practise: !view.waiting,
    };
    const signature = JSON.stringify([
      view,
      !!actions?.supplement,
      !!actions?.revise,
      actions?.backToBoard,
      state.feedbackPhase,
      !!state.feedbackSince,
    ]);
    if (signature !== coverShown) {
      // A focused control in the cover keeps focus across the redraw: the same control when it
      // is still there, else the cover's heading (for example when the feedback arrives).
      const focused = coverHost.contains(doc.activeElement)
        ? (doc.activeElement as HTMLElement)
        : null;
      const same = focused && {
        action: focused.dataset.action,
        text: focused.textContent,
      };
      coverShown = signature;
      // The stamp of a delivery just made here is pressed once. The page may be drawn again
      // while it presses; each drawing picks the press up where it is (never restarts it).
      let pressed: number | undefined;
      if (
        note &&
        !reduced() &&
        (!state.submission || state.submission.ref.session_id === note.sessionId)
      ) {
        note.pressedAt ??= Date.now();
        const elapsed = Date.now() - note.pressedAt;
        if (elapsed < STAMP_PRESS_MS) pressed = elapsed;
      }
      const cover =
        view && actions
          ? renderCover(doc, view, language, actions, {
              phase: state.feedbackPhase,
              seconds: waitSeconds(state),
              freshStamp: pressed !== undefined,
              pressElapsed: pressed,
            })
          : null;
      // A redraw keeps the stamp already on the page, so a press in progress is never restarted.
      const before = coverHost.querySelector<HTMLElement>('[data-delivery-stamp]');
      const after = cover?.querySelector<HTMLElement>('[data-delivery-stamp]');
      if (before && after) {
        // Same element, new words (the time may arrive with the record): a press keeps going.
        before.replaceChildren(...after.childNodes);
        after.replaceWith(before);
      }
      // The feedback arriving after a wait is a change in the world: its parts settle in once.
      if (cover && coverWaited && !view?.waiting) cover.classList.add('is-arriving');
      coverWaited = !!view?.waiting;
      coverHost.replaceChildren(...(cover ? [cover] : []));
      if (same && cover) {
        const again = [...cover.querySelectorAll<HTMLElement>('button')].find((node) =>
          same.action ? node.dataset.action === same.action : node.textContent === same.text,
        );
        const title = cover.querySelector<HTMLElement>('.result-cover__title');
        if (title) title.tabIndex = -1;
        (again ?? title)?.focus({ preventScroll: true });
      }
    }
    // Real seconds tick while the feedback is written; nothing else moves.
    const waiting = !!view?.waiting && !view.failed && !!state.feedbackSince;
    if (waiting && !ticker)
      ticker = setInterval(() => {
        const clock = coverHost.querySelector<HTMLElement>('[data-elapsed]');
        const seconds = waitSeconds(adapter.snapshot());
        if (clock && seconds !== undefined) clock.textContent = elapsedWords(seconds, language);
      }, 1000);
    if (!waiting && ticker) {
      clearInterval(ticker);
      ticker = undefined;
    }
  }
  function render() {
    if (destroyed) return;
    const state = adapter.snapshot();
    reviewControls?.render();
    failedNote.hidden = !state.failedFeedback;
    retryFeedback.hidden = !state.failedFeedback || !adapter.retry;
    retryFeedback.disabled = state.busy || adapter.canRetry === false;
    notice.textContent = feedbackNotice(state, language);
    if (options.surface !== 'submission') renderCoverNow(state);
    // With the cover shown, the status line stays for screen readers only; the cover says it.
    notice.classList.toggle('sr-only', !!coverHost.firstElementChild);
    restoreChoice(state);
    selection.replaceChildren(
      ...state.products.map((product) => {
        const ref: ObjectRef = {
          session_id: product.session_id,
          kind: 'product',
          object_id: product.product_id,
          version: product.version,
        };
        const id = key(ref);
        const row = el('label', '', 'field-row');
        const checkbox = el('input');
        checkbox.type = 'checkbox';
        checkbox.checked = selected.has(id);
        checkbox.disabled = state.status !== 'active' || state.busy || !!product.removed_at;
        checkbox.addEventListener('change', () => {
          if (checkbox.checked) {
            selected.set(id, ref);
            selectedTitles.set(id, product.title || T('未命名作品', 'Untitled artifact'));
          } else selected.delete(id);
          renderSelected();
          syncPreview();
        });
        // Each version reads like an attachment slip: 《标题》 · 第 N 版 · 用途.
        row.classList.add('delivery-attachment');
        const slip = el('span', '', 'delivery-attachment__slip');
        slip.append(attachmentSlip(doc, product, language));
        if (product.author.kind === 'external_agent')
          slip.append(el('span', T('Agent 制作', 'Made by an Agent'), 'delivery-attachment__by'));
        const view = button(T('查看', 'View'), () => adapter.openReference(ref));
        view.classList.add('quiet', 'small', 'delivery-attachment__view');
        view.setAttribute('aria-label', T('查看 ', 'View ') + attachmentLine(product, language));
        row.append(checkbox, slip, view);
        return row;
      }),
    );
    renderSelected();
    // The attachment slips above already show and open each chosen version.
    selectedSummary.hidden = true;
    if (state.status === 'submitted' && state.submission) choice.value = state.submission.decision;
    submit.disabled =
      state.status !== 'active' || state.busy || !!state.pending || adapter.canSubmit === false;
    choice.disabled = submit.disabled;
    // While feedback is written the cover reads its progress by itself; the manual check stays
    // for an unconfirmed request only (one refresh control is enough).
    recover.hidden =
      (!state.pending && !state.awaitingFeedback) ||
      !adapter.recover ||
      (!state.pending && !!coverHost.firstElementChild);
    recover.disabled = state.busy;
    recover.textContent = state.awaitingFeedback
      ? T('查看反馈进度', 'Check feedback progress')
      : T('确认上一请求', 'Check the previous request');
    receipt.replaceChildren();
    if (state.submission) {
      // The delivery and each exact version it saved, by the names evidence buttons use.
      const catalog = state.references ?? readCatalog(null);
      receipt.append(el('h3', snapshotHeading(state.submission.ref, catalog, language)));
      refs(receipt, state.submission.products);
    }
    // Do not rebuild the response editor while it holds focus. Its content is
    // retained in the per-report draft even when the shared client refreshes.
    if (!reports.contains(doc.activeElement)) {
      const expandedModels = new Set(
        [...reports.querySelectorAll<HTMLElement>('[data-model-advice-report]')]
          .filter((node) => node.querySelector<HTMLDetailsElement>('[data-model-advice]')?.open)
          .map((node) => node.dataset.modelAdviceReport),
      );
      const expanded = new Set(
        [...reports.querySelectorAll<HTMLDetailsElement>('details[data-response-id][open]')].map(
          (n) => n.dataset.responseId,
        ),
      );
      reports.replaceChildren(
        ...[...state.reports]
          .sort(
            (a, b) =>
              Number(b.subject.object_id === state.submission?.ref.object_id) -
              Number(a.subject.object_id === state.submission?.ref.object_id),
          )
          .map(reportPanel),
      );
      for (const detail of reports.querySelectorAll<HTMLDetailsElement>(
        'details[data-response-id]',
      ))
        detail.open = expanded.has(detail.dataset.responseId);
      for (const node of reports.querySelectorAll<HTMLElement>('[data-model-advice-report]')) {
        const detail = node.querySelector<HTMLDetailsElement>('[data-model-advice]');
        if (detail) detail.open = expandedModels.has(node.dataset.modelAdviceReport);
      }
    }
    // Model references must reflect current permissions even while this report holds focus.
    for (const node of reports.querySelectorAll<HTMLElement>('[data-model-advice-report]')) {
      const report = state.reports.find((entry) => entry.id === node.dataset.modelAdviceReport);
      updateRegisteredAdvice(
        node,
        report?.model_advice,
        language,
        (ref) => adapter.openReference(ref),
        adviceFallback(report, state),
        nameOf,
      );
    }
    for (const node of reports.querySelectorAll<HTMLElement>('[data-feedback-coverage]')) {
      const report = state.reports.find((entry) => entry.id === node.dataset.feedbackCoverage);
      node.textContent = report
        ? feedbackCoverageText(report, feedbackSemanticPresentation(report, state).advice, language)
        : '';
    }
    // Preserve the focused editor, but never preserve stale request permissions.
    for (const action of reports.querySelectorAll<HTMLButtonElement>(
      'button[data-response-action]',
    ))
      action.disabled = state.busy || !!state.pending || adapter.canRespond === false;
    responseHistory.replaceChildren();
    // Confirmed records the last read does not list yet, so nothing waits for a refresh.
    const unlisted = recorded.filter(
      (echo) =>
        !state.responses?.some(
          (response) =>
            response.kind === echo.kind &&
            response.text === echo.text &&
            response.feedback?.object_id === echo.feedback,
        ),
    );
    const listed = [...(state.responses ?? []), ...unlisted];
    if (listed.length) {
      responseHistory.append(
        el('h3', T('已记录的异议与补证', 'Recorded challenges and additional evidence')),
      );
      for (const response of listed)
        responseHistory.append(
          el('p', recordedText(response.kind)),
          el('blockquote', response.text),
        );
    }
    revisions.hidden = state.status !== 'submitted';
    revise.disabled =
      state.busy || !!state.pending || !!state.awaitingFeedback || !state.submission;
    reports.hidden = !!state.error && !state.reports.length;
    submissions.hidden = !!state.error && !state.products.length;
    if (state.error) {
      failure.textContent = state.error;
      failure.hidden = false;
    } else if (lastReadError && failure.textContent === lastReadError) {
      failure.hidden = true;
      failure.textContent = '';
    }
    lastReadError = state.error;
    sealReadOnly(
      { notice, reports, revisions, failedNote, retry: retryFeedback },
      state.readOnly === true,
      language,
    );
    syncPreview();
  }
  const unsubscribe = adapter.subscribe(render);
  // Opening the lens plays the reading once; later redraws (reads, polls) show it at rest.
  const unlens = onLensChange((on) => {
    playReading = on;
    render();
    playReading = false;
  });
  render();
  return {
    refresh: () => act(() => adapter.refresh()),
    destroy: () => {
      destroyed = true;
      clearInterval(ticker);
      unsubscribe();
      unlens();
      reviewControls?.destroy();
      preview?.destroy();
      root.remove();
    },
  };
}

export { mountNativeFeedback as mount };

/** The criterion a recognition record speaks to (arbiter and criterion-level records). */
function recordCriterion(record: RecognitionRecord): string | null {
  const value = record.outputs?.criterion;
  return typeof value === 'string' ? value : null;
}

function criterionRecords(report: Report, criterion: string): RecognitionRecord[] {
  return (report.recognition ?? []).filter((record) => recordCriterion(record) === criterion);
}

/** What "Start a revision" hands the board: the delivery's number, its unmet items by name, the
 * versions it delivered and the person's own words for the revision. */
export function revisionStart(
  state: FeedbackNativeState,
  submission: { ref: ObjectRef; products: ObjectRef[] },
  language: FeedbackLanguage,
  reason: string,
) {
  const view = coverView({ ...state, submission: { ...submission, decision: '' } }, language);
  return {
    delivery: view?.delivery,
    unmet: view?.unmet.map((row) => row.name) ?? [],
    products: submission.products.map((ref) => ref.object_id),
    reason: reason.trim(),
  };
}
