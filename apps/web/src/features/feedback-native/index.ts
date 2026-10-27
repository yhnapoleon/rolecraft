import {
  MODEL_ADVICE_STYLE,
  adviceRowLine,
  evaluationModelLine,
  updateRegisteredAdvice,
  type RegisteredAdvice,
  type AdviceFallback,
} from './model-advice';
import type { SubmissionRuleCheck, SubmitInput, _RuleScoreRange } from '../../contracts-v2';
/** Native DOM submission/review surface. Inject the shared client; no credentials,
 * queue, mutation journal, global navigation or React root is created here. */
import { mountReviewControls, isSubmitDecision } from './review-controls';
import { feedbackCopy, feedbackCount, feedbackText, type FeedbackLanguage } from './localization';
import {
  declaredPurpose,
  laterPurpose,
  purposePromptElement,
  purposeUnknown,
  reviewedAs,
  ruleItems,
  type PurposeChoice,
} from './short-summary';
import { evaluationVersionLine } from './evaluation-version';
import { renderDecisions } from './business-decisions';
import { sealReadOnly } from './read-only-notice';
import {
  disclosure,
  earlierSummary,
  feedbackItemsView,
  renderFeedbackItems,
  renderItemRow,
  type ItemRow,
} from './feedback-items';
import { decisionName } from './decision-cards';
import { criterionChecks, criterionLabels, criterionQuestions } from './criteria';
import { exactRefKey } from './exact-ref';
import { mountPresubmitCard, PRESUBMIT_STYLE, type SentenceResult } from './presubmit';
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
import {
  renderResultHead,
  renderResultSkeleton,
  type ResultGroup,
} from '../../screens/result/result-head';
import { renderColleagues } from '../../screens/result/by-colleague';
import {
  COLLEAGUE_NAMES,
  colleagueOf,
  type Colleague,
} from '../../screens/result/colleagues';
import { entranceFor, playEntrance, tickClock } from '../../screens/result/motion';
import { resultSeen } from '../../screens/result/seen';
import { createViewSwitch } from '../../screens/result/view-switch';
import '../../screens/result/deliver.css';
import type { ObjectRef, EvidenceRefV2, WorkProductVersion } from '../workspace/contract-types';
import { readCatalog, referenceLabel, type ReferenceCatalog } from '../../reference-catalog';
import type { EvidencePick } from '../../v4-host';
import { EVIDENCE_KINDS, evidenceSummary } from '../../evidence-picker';
import type { RecognitionRecord } from '../recognition-native/badge';
import { lensOn, onLensChange } from '../recognition-native/lens';
import { splitRecognitionPrefix } from '../recognition-native/prefix';
import type { FeedbackActivityCount, FeedbackReferenceCheck } from '../../contracts-v2';
import { renderBusinessSentences } from '../recognition-native/business-sentences';
import { recordedSentencePreview } from '../recognition-native/judgment-chain';
import { renderExplanationTag, renderSignals } from '../recognition-native/signals';

export type SelectedProduct = Pick<
  WorkProductVersion,
  'session_id' | 'product_id' | 'version' | 'title' | 'removed_at' | 'author'
> & { purpose?: string; content?: string };
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
        references: ({ verified_ref?: EvidenceRefV2 | null } & Partial<
          Pick<FeedbackReferenceCheck, 'valid_at_subject' | 'status'>
        >)[];
        /** Verified activity counts by kind (contract `VerifiedFactsSnapshot`; read only). */
        activity_totals?: Record<string, FeedbackActivityCount>;
        verified_source_count?: number | null;
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
  /** Read-only: names of work kept unsaved in this browser that the chosen versions do not
   * contain ("" when none). The panel warns before submitting; nothing is blocked. */
  unsavedWork?(products: ObjectRef[]): Promise<string>;
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
  if (state.pending)
    return T(
      '上一请求结果尚未确认，请先恢复。',
      'The previous request is unresolved. Recover its result first.',
    );
  if (state.busy && !state.submission)
    return T('正在等待服务端确认…', 'Waiting for server confirmation…');
  if (state.status !== 'submitted')
    return T(
      '可以继续工作，选择准备交付的版本。',
      'Continue your work and select versions for submission.',
    );
  const hasFeedback = state.reports.some((r) => r.subject.object_id === state.submission?.ref.object_id);
  if (hasFeedback)
    return state.busy ? T('正在读取反馈记录…', 'Reading feedback records…') : '';
  if (state.failedFeedback)
    return T('本次提交已保存，反馈尚未就绪。', 'Submission saved. Feedback is not ready yet.');
  if (state.feedbackPhase === 'running')
    return T('本次提交已保存，反馈正在生成…', 'Submission saved. Feedback is being generated…');
  if (state.feedbackPhase === 'queued')
    return T('本次提交已保存，正在等待评审…', 'Submission saved. Waiting for the reviewer…');
  return state.busy
    ? T('本次提交已保存，正在读取反馈…', 'Submission saved. Reading feedback…')
    : T('本次提交已保存，反馈尚未就绪。', 'Submission saved. Feedback is not ready yet.');
}

export function revisionVisible(state: FeedbackNativeState): boolean {
  // A restored browser may not have the failed request pointer. The saved submission
  // is enough to show the recovery path; pending work still disables the action below.
  return state.status === 'submitted';
}
export type FeedbackMountOptions = {
  surface?: 'all' | 'submission' | 'feedback';
  /** The result page (206): the stamped result sheet first, the detail by status or colleague. */
  layout?: 'result';
  /** AIPM practices: a "back to sheet" button under each criterion's basis (v2 spec §10 L3).
   * Without it the rows are unchanged. */
  backToSheet?: (criterion: string) => Node | null;
};

/** How the result page's detail is arranged; a per-viewer convenience kept in this browser. */
type DetailView = 'status' | 'colleague';
const DETAIL_VIEW = 'rolecraft.result.view';
function savedDetailView(): DetailView {
  try {
    return localStorage.getItem(DETAIL_VIEW) === 'colleague' ? 'colleague' : 'status';
  } catch {
    return 'status';
  }
}
function saveDetailView(view: DetailView) {
  try {
    localStorage.setItem(DETAIL_VIEW, view);
  } catch {
    // Not kept; it still applies on this page.
  }
}

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
  // Presentation only: the purpose choice survives re-renders, not reloads.
  // Open recognition chains per report, kept across redraws (lens toggles, refreshes).
  const purposeChoices = new Map<string, PurposeChoice>();
  let savedDrafts: Promise<void> = Promise.resolve();
  let draftError: unknown;
  // Confirmed challenges and supplements show at once, until the next read lists them.
  type ResponseKind = 'objection' | 'supplement';
  const recorded: { feedback: string; kind: ResponseKind; text: string }[] = [];
  const recordedForms = new Map<string, ResponseKind>();
  /** Beside a form, once the server confirms what it saved. */
  const savedText = (kind: ResponseKind) =>
    kind === 'objection'
      ? T(
          '已记下你的看法，仍待核验；这份反馈保持原样。',
          'Your view is saved. It still needs checking; this feedback stays as it is.',
        )
      : T(
          '已记下补充的依据，仍待核验；这份反馈保持原样。',
          'Your evidence is saved. It still needs checking; this feedback stays as it is.',
        );
  /** In the list of what was saved. */
  const recordedText = (kind: ResponseKind) =>
    kind === 'objection'
      ? T('你的看法 · 仍待核验', 'Your view · still to be checked')
      : T('补充的依据 · 仍待核验', 'Added evidence · still to be checked');
  // Presentation only: which rows, bases and notes are open, kept across redraws.
  const openKeys = new Set<string>();
  let detailView: DetailView = options.layout === 'result' ? savedDetailView() : 'status';
  // When this page last read the feedback (shown beside the refresh control).
  let readAt = Date.now();
  let readReports = '';
  const chevronNode = () => {
    const node = doc.createElement('span');
    node.className = 'fb-chev';
    node.setAttribute('aria-hidden', 'true');
    node.textContent = '›';
    return node;
  };
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
  // Unsaved worksheet text is not in the versions being submitted: say so above the button.
  const unsaved = el('p', '', 'inline-alert delivery-unsaved');
  unsaved.setAttribute('role', 'status');
  unsaved.hidden = true;
  let unsavedKey = '';
  function checkUnsaved() {
    const products = [...selected.values()];
    const key = JSON.stringify(products);
    if (!adapter.unsavedWork || adapter.snapshot().status !== 'active' || key === unsavedKey) return;
    unsavedKey = key;
    void adapter
      .unsavedWork(products)
      .then((names) => {
        if (destroyed || key !== unsavedKey) return;
        unsaved.textContent = names
          ? T(
              `${names} 还有没保存的文字，不在这次要交付的版本里。要交付它们，先回工作纸点「保存这一版」。`,
              `${names} ${names.includes(',') ? 'have' : 'has'} unsaved text that is not in the version you are submitting. To include it, go back to the sheet and press "Save version" first.`,
            )
          : '';
        unsaved.hidden = !names;
      })
      .catch(() => {
        unsaved.hidden = true;
      });
  }
  let submitting = false;
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
      // From the press until the result page takes over, the dialog holds still: the key turns to
      // its loading state (same width, same words) and nothing else in the panel redraws.
      submitting = true;
      submit.style.minWidth = `${submit.offsetWidth}px`;
      submit.dataset.state = 'loading';
      submit.setAttribute('aria-busy', 'true');
      submit.disabled = true;
      try {
        await adapter.submit({ decision, products });
      } catch (error) {
        submitting = false;
        delete submit.dataset.state;
        submit.removeAttribute('aria-busy');
        submit.style.minWidth = '';
        throw error;
      }
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
  // The dialog's middle column (206): the work as paper, read sentence by sentence by the lens.
  // Until the lens has read it, the chosen versions' text shows grey; with the lens closed, as
  // plain paper. The margin originals come with the lens's own rows.
  const reading = el('div', '', 'delivery-reading');
  reading.dataset.deliveryReading = '';
  const readingPaper = el('article', '', 'delivery-reading__paper');
  let readingKind: 'idle' | 'running' | 'ready' | 'failed' | 'disabled' | 'empty' = 'idle';
  function syncReading(kind = readingKind) {
    readingKind = kind;
    const lensRead = kind === 'ready';
    reading.dataset.state = kind;
    reading.dataset.lens = String(lensOn());
    readingPaper.hidden = lensRead;
    if (lensRead) return;
    // Waiting for the lens: the sentences are there, grey, before they are marked.
    readingPaper.dataset.pending = String(lensOn());
    const state = adapter.snapshot();
    const parts: Node[] = [];
    for (const ref of selected.values()) {
      const product = state.products.find(
        (p) => p.product_id === ref.object_id && p.version === ref.version,
      );
      if (!product) continue;
      const head = el('header', '', 'delivery-reading__head');
      head.append(
        el('h3', product.title || T('未命名作品', 'Untitled artifact'), 'delivery-reading__title'),
        el('span', versionLabel(product.version), 'delivery-reading__version'),
      );
      parts.push(head);
      for (const para of (product.content ?? '').split(/\n{2,}/)) {
        const text = para.replace(/^#+\s*/, '').trim();
        if (text) parts.push(el('p', text, 'delivery-reading__text'));
      }
    }
    if (!parts.length)
      parts.push(
        el(
          'p',
          T('选一个作品版本，它会显示在这里。', 'Choose a work version; it appears here.'),
          'delivery-reading__empty',
        ),
      );
    readingPaper.replaceChildren(...parts);
  }
  const preview = load
    ? mountPresubmitCard(doc, language, load, {
        recognize: adapter.previewRecognition?.bind(adapter),
        // The delivery dialog is the page: the preview is a section of it, so the work's
        // sentences sit on it directly as paper (dialog → work paper, no panel between).
        frame: 'flat',
        split: true,
        onReading: (kind) => syncReading(kind),
      })
    : undefined;
  if (preview) reading.append(preview.reading, readingPaper);
  // The latest version of the pilot decision is chosen when the dialog opens (decision 20).
  let defaulted = false;
  function defaultChoice(state: FeedbackNativeState) {
    // A choice remembered from an earlier opening wins, even an empty one.
    if (defaulted || !preview || selected.size || rememberedAtOpen || state.status !== 'active')
      return;
    const live = state.products.filter((p) => !p.removed_at);
    if (!live.length) return;
    defaulted = true;
    const latest = new Map<string, (typeof live)[number]>();
    for (const p of live) {
      const seen = latest.get(p.product_id);
      if (!seen || p.version > seen.version) latest.set(p.product_id, p);
    }
    const decisions = [...latest.values()].filter((p) => p.purpose === 'commitment');
    const chosen = decisions.length ? decisions : [...latest.values()].slice(-1);
    for (const p of chosen) {
      const ref: ObjectRef = {
        session_id: p.session_id,
        kind: 'product',
        object_id: p.product_id,
        version: p.version,
      };
      selected.set(key(ref), ref);
      selectedTitles.set(key(ref), p.title || T('未命名作品', 'Untitled artifact'));
    }
  }
  let restoring = preview ? adapter.rememberedChoice?.() : undefined;
  const rememberedAtOpen = !!restoring;
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
    syncSubmit();
    if (!preview) return;
    const state = adapter.snapshot();
    const open = state.status === 'active' && adapter.canPreview !== false;
    preview.element.hidden = !open;
    // The work stays on the page while it is being submitted: the dialog keeps its columns.
    syncReading();
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
        '交付会锁定所选版本，看完反馈可以修订，原交付和反馈都会留着。',
        'Submitting locks the versions you choose; you can revise after feedback, and the original stays on record.',
      ),
      'muted',
    ),
    el('p', T('要交付的版本', 'Version to submit'), 'delivery-label'),
    selection,
    selectedSummary,
    el('p', T('你的决定', 'Your decision'), 'delivery-label'),
    choice.element,
    ...(preview ? [preview.element] : []),
    unsaved,
    submit,
    recover,
    receipt,
    ...(preview ? [reading] : []),
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
  revisions.append(el('h2', T('修订', 'Revise')), revisionReason, revise);
  // One refresh control, as an icon beside the time this page last read the feedback.
  const refreshRow = el('p', '', 'fb-refresh');
  const updated = el('span', '', 'fb-refresh__time');
  const refresh = button('', async () => {
    await adapter.refresh();
    readAt = Date.now();
  });
  refresh.classList.add('icon', 'small', 'quiet');
  refresh.setAttribute('aria-label', feedbackCopy(language, 'refreshLabel'));
  refresh.title = feedbackCopy(language, 'refreshLabel');
  refresh.append(refreshIcon(doc), el('span', feedbackCopy(language, 'refresh'), 'sr-only'));
  refreshRow.append(updated, refresh);
  // The results cover sits first on the feedback page (it is never part of the submit panel).
  const coverHost = el('div', '', 'result-cover-host');
  let coverShown = '';
  let coverWaited = false;
  let ticker: (() => void) | undefined;
  root.append(failure);
  if (options.surface !== 'submission') root.append(coverHost);
  root.append(notice, failedNote, retryFeedback);
  if (options.surface !== 'feedback') root.append(submissions);
  if (options.surface === 'feedback') root.append(recover);
  if (options.surface !== 'submission')
    root.append(refreshRow, reports, responseHistory, revisions);
  const reviewControls =
    options.surface !== 'submission' && adapter.review
      ? mountReviewControls(doc, adapter, language)
      : undefined;
  // Getting a review and the list of deliveries and reviews follow the feedback.
  if (reviewControls) root.insertBefore(reviewControls.element, revisions);
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
  /** Sources as chips that open the exact cited text; a quoted passage follows its chip. */
  function chips(values: (ObjectRef | EvidenceRefV2)[]) {
    const row = el('div', '', 'fb-sources');
    for (const ref of values) {
      const name = nameOf(ref);
      const link = button(name.text, () => adapter.openReference(ref));
      link.className = 'chip';
      link.setAttribute('aria-label', name.label);
      link.dataset.referenceKind = ref.kind;
      link.dataset.referenceKey = key(ref);
      row.append(link);
      if ('quote' in ref && ref.quote) {
        if (language === 'en' && /[一-鿿]/u.test(ref.quote))
          row.append(el('small', 'Chinese source', 'muted'));
        row.append(el('blockquote', ref.quote));
      }
    }
    return row;
  }
  type Section = 'general' | 'verified_facts' | 'historical_responsibilities' | 'rule_items' | 'model_advice';
  /** The existing response form of one item (or of the whole report), opened by "补充依据" or
   * "我有不同看法"; its own summary is not shown, the two buttons are the way in. */
  function responseForm(report: Report, criterion?: string, section: Section = 'general') {
    const id = [report.id, report.version, section, criterion ?? ''].join(':');
    const draft = draftResponses.get(id) ?? adapter.readDraft(id) ?? { text: '', evidence: [] };
    draftResponses.set(id, draft);
    const form = el('details', '', 'fb-respond');
    form.dataset.responseId = id;
    form.append(el('summary', T('补充依据或提出不同看法', 'Add evidence or share a different view')));
    const body = el('textarea', '', 'textarea');
    body.rows = 3;
    body.value = draft.text;
    body.setAttribute('aria-label', T('你的看法或要补充的内容', 'Your view or what you are adding'));
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
    choose.classList.add('small');
    choose.disabled = !adapter.chooseEvidence;
    // What this form last recorded, shown beside it the moment the server confirms.
    const status = el('p', '', 'muted');
    status.setAttribute('role', 'status');
    const showRecorded = () => {
      const kind = recordedForms.get(id);
      status.textContent = kind ? savedText(kind) : '';
      status.hidden = !kind;
    };
    showRecorded();
    const send = (kind: ResponseKind) => async () => {
      if (!draft.text.trim())
        throw Error(
          T('请写下你的看法或要补充的内容。', 'Describe your view or the evidence you are adding.'),
        );
      if (kind === 'supplement' && !draft.evidence.length)
        throw Error(
          T(
            '补充依据需要先选择至少一处原始引用。',
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
    const objection = button(T('记下我的看法', 'Save my view'), send('objection'));
    const supplement = button(T('补上这些依据', 'Add this evidence'), send('supplement'));
    objection.dataset.responseAction = 'objection';
    supplement.dataset.responseAction = 'supplement';
    objection.classList.add('small');
    supplement.classList.add('small');
    objection.disabled = supplement.disabled =
      adapter.snapshot().busy || !!adapter.snapshot().pending || adapter.canRespond === false;
    const actions = el('div', '', 'fb-basis__actions');
    actions.append(choose, supplement, objection);
    form.append(body, evidence, actions, status);
    return form;
  }
  /** Open a response form for one intent, with the text box ready. */
  function openResponse(form: HTMLDetailsElement, intent: ResponseKind) {
    const opening = !form.open || form.dataset.intent !== intent;
    form.dataset.intent = intent;
    form.open = opening;
    if (opening) form.querySelector('textarea')?.focus({ preventScroll: true });
  }
  /** "补充依据" and "我有不同看法" for one form. */
  function responseButtons(form: HTMLDetailsElement) {
    const row = el('div', '', 'fb-basis__actions');
    const add = el('button', T('补充依据', 'Add evidence'), 'btn small');
    const differ = el('button', T('我有不同看法', 'I see it differently'), 'btn small quiet');
    for (const [node, intent] of [
      [add, 'supplement'],
      [differ, 'objection'],
    ] as const) {
      node.type = 'button';
      node.dataset.respondIntent = intent;
      node.setAttribute('aria-controls', form.dataset.responseId ?? '');
      node.addEventListener('click', () => openResponse(form, intent));
    }
    row.append(add, differ);
    return row;
  }
  const disclosures = { isOpen: (k: string) => openKeys.has(k), onToggle: (k: string, open: boolean) => (open ? openKeys.add(k) : openKeys.delete(k)) };
  /** This delivery's (or review's) decision, by the four names of the delivery panel. */
  function decisionOf(report: Report, review: ReviewRecord | undefined): string | null {
    if (report.subject.kind === 'review') return review?.decision ?? null;
    const state = adapter.snapshot();
    const own = (state.submissions ?? []).find(
      (s) => s.ref.object_id === report.subject.object_id && s.ref.version === report.subject.version,
    );
    if (own) return own.decision;
    const latest = state.submission;
    return latest && latest.ref.object_id === report.subject.object_id ? latest.decision : null;
  }
  /** The criteria of one report, item by item. Read-only for an earlier delivery: no responses,
   * no direct steps, no recognition reading. */
  function itemsSection(report: Report, review: ReviewRecord | undefined, readOnly: boolean) {
    const state = adapter.snapshot();
    const semantic = feedbackSemanticPresentation(report, state);
    const fallback = adviceFallback(report, state);
    const view = feedbackItemsView(report, {
      language,
      decision: decisionOf(report, review),
      kind: report.subject.kind,
      atSubmission: savedRuleCheck(report),
      adviceLine: adviceRowLine(report.model_advice, language, fallback),
      legacyAdvice: semantic.advice,
    });
    const scopeBasis = [...view.premises, ...report.next_options].map((text) => el('p', text));
    // The delivery this list belongs to, first on its line (an earlier one names it on its row).
    const subject = readOnly ? null : (chips([report.subject]).firstElementChild as HTMLElement | null);
    const lens = lensOn() && !readOnly;
    const after: Node[] = [];
    const sentencePreview = recordedSentencePreview(report.recognition ?? []);
    if (!readOnly && sentencePreview?.units?.length)
      after.push(renderBusinessSentences(doc, sentencePreview, language, `${report.id}:${report.version}`));
    if (lens) {
      // With the recognition lens open: this feedback's recognizer signals and the work sentence
      // by sentence, from the records stored with it. Closed: nothing.
      const general = (report.recognition ?? []).filter((record) => !recordCriterion(record));
      const box = el('section', '', 'fb-lens');
      // The sentence block below already counts the relation labels; no second chip for them.
      const lensChips = renderSignals(
        doc,
        general.filter(
          (record) => !(record.task === 'relation' && Array.isArray(record.outputs?.units)),
        ),
        language,
        { context: 'feedback', lens: true, cards: {} },
      );
      if (lensChips) box.append(lensChips);
      if (box.childElementCount) after.push(box);
    }
    const legacy = semantic.advice;
    const result = options.layout === 'result' && !readOnly;
    const rowHooks = {
      id: `${report.id}-${report.version}`,
      ...disclosures,
      action: (row: ItemRow) => {
        // The result page: a row not known yet goes to the colleague who would check it.
        const owner = result && row.mark === 'unknown' ? colleagueOf(row.criterion) : null;
        if (owner) return askButton(owner, row.name);
        if (readOnly || !row.action) return null;
        const go = el('button', row.action.label, 'btn small');
        go.type = 'button';
        go.dataset.action = row.action.tool;
        go.setAttribute('aria-label', `${row.action.label} · ${row.name}`);
        return go;
      },
      basis: (row: ItemRow) => {
        const nodes: Node[] = [];
        // R2.support: the registered model advice, as advice (never scored).
        if (row.criterion === 'R2.support' && showsAdviceBlock(report)) nodes.push(adviceBlock(report, lens));
        for (const item of legacy.filter((entry) => entry.criterion === row.criterion)) {
          // The reviewer's recognition prefix is never shown as text; the lens shows it as a tag.
          const split = splitRecognitionPrefix(item.explanation);
          if (lens) {
            const tag = renderExplanationTag(doc, split, language);
            if (tag) nodes.push(tag);
          }
          nodes.push(el('p', T('模型建议 · ', 'Model advice · ') + split.text, 'fb-basis__text'));
          if (item.citations.length) nodes.push(chips(item.citations));
          if (!readOnly) nodes.push(responseForm(report, item.criterion, 'model_advice'));
        }
        if (row.item.citations.length) {
          const sources = el('div', '', 'fb-basis__block');
          sources.append(el('p', T('依据', 'Sources'), 'fb-basis__label'), chips(row.item.citations));
          nodes.push(sources);
        }
        const sheet = options.backToSheet?.(row.criterion);
        if (sheet) nodes.push(sheet);
        if (row.weight) {
          const weight = el('p', row.weight, 'fb-weight');
          weight.dataset.criterionWeight = row.criterion;
          nodes.push(weight);
        }
        // Recognition signals of this criterion: nothing by default, chips in the lens.
        const signed = renderSignals(doc, criterionRecords(report, row.criterion), language, {
          context: 'criterion',
          lens,
          cards: {},
        });
        if (signed) nodes.push(signed);
        if (!readOnly) {
          const form = responseForm(report, row.criterion, 'rule_items');
          nodes.push(responseButtons(form), form);
        }
        return nodes;
      },
    };
    return renderFeedbackItems(doc, view, language, {
      ...rowHooks,
      scopeBasis,
      after,
      subject: subject ?? undefined,
      ...(result
        ? {
            unknownShown: 3,
            switcher: detailSwitch(),
            ...(detailView === 'colleague'
              ? { regrouped: () => renderColleagues(doc, view, language, rowHooks, askButton) }
              : {}),
          }
        : {}),
    });
  }
  /** By status · By colleague: the shell's segmented control; the choice redraws the detail. */
  let viewSwitch: ReturnType<typeof createViewSwitch> | undefined;
  function detailSwitch() {
    const props = {
      value: detailView,
      label: feedbackCopy(language, 'viewLabel'),
      items: [
        { value: 'status' as const, label: feedbackCopy(language, 'viewStatus') },
        { value: 'colleague' as const, label: feedbackCopy(language, 'viewColleague') },
      ],
      onChange: (value: DetailView) => {
        if (detailView === value) return;
        detailView = value;
        saveDetailView(value);
        // The list is not rebuilt while it holds focus (a form may be open); the switch is in it.
        const focused = doc.activeElement as HTMLElement | null;
        const inSwitch = !!focused && !!viewSwitch?.element.contains(focused);
        if (focused && reports.contains(focused)) focused.blur();
        render();
        if (inSwitch)
          viewSwitch?.element
            .querySelector<HTMLElement>('[data-state="on"], [aria-checked="true"]')
            ?.focus({ preventScroll: true });
      },
    };
    if (viewSwitch) viewSwitch.update(props);
    else viewSwitch = createViewSwitch(doc, props);
    return viewSwitch.element;
  }
  /** "Ask Chen": opens the right rail's conversation with that colleague (the shell's action). */
  function askButton(who: Colleague, about?: string) {
    const go = el('button', T(`问 ${COLLEAGUE_NAMES[who]}`, `Ask ${COLLEAGUE_NAMES[who]}`), 'btn small');
    go.type = 'button';
    go.dataset.action = 'chat';
    go.dataset.role = who;
    if (about) go.setAttribute('aria-label', `${go.textContent} · ${about}`);
    return go;
  }
  /** A reading on the result sheet: its group in the detail, by status. */
  function locate(group: ResultGroup) {
    if (detailView !== 'status') {
      detailView = 'status';
      saveDetailView('status');
      if (reports.contains(doc.activeElement)) (doc.activeElement as HTMLElement).blur();
      render();
    }
    const box = reports.querySelector<HTMLElement>(`[data-result-detail] [data-group="${group}"]`);
    const head = box?.querySelector<HTMLElement>('.fb-group__head');
    if (!box || !head) return;
    head.tabIndex = -1;
    box.scrollIntoView({ block: 'start', behavior: reduced() ? 'auto' : 'smooth' });
    head.focus({ preventScroll: true });
  }
  /** The registered model advice is shown unless only older-protocol advice items exist. */
  function showsAdviceBlock(report: Report) {
    return (
      !feedbackSemanticPresentation(report, adapter.snapshot()).advice.length ||
      report.model_advice !== undefined
    );
  }
  function adviceBlock(report: Report, lens: boolean) {
    const block = el('div');
    block.dataset.modelAdviceReport = report.id;
    updateRegisteredAdvice(
      block,
      report.model_advice,
      language,
      (ref) => adapter.openReference(ref),
      adviceFallback(report, adapter.snapshot()),
      nameOf,
      { lens, sessionId: report.subject.session_id },
    );
    return block;
  }
  /** What the feedback is based on: one line of counts, the stored sentences in Details. */
  function recordsSection(report: Report) {
    const box = el('section', '', 'fb-records');
    box.dataset.feedbackRecords = report.id;
    box.setAttribute('aria-label', feedbackCopy(language, 'recordsTitle'));
    const snapshots = report.verified_facts ?? [];
    const top = el('p', '', 'fb-records__top');
    top.append(el('span', feedbackCopy(language, 'recordsTitle'), 'fb-records__title'));
    if (!snapshots.length)
      top.append(el('span', feedbackCopy(language, 'recordsNotReady'), 'fb-records__counts'));
    for (const snapshot of snapshots) {
      const line = recordCounts(snapshot, language);
      const prefix =
        snapshots.length > 1 && snapshot.subject ? `${nameOf(snapshot.subject).text}：` : '';
      if (line) top.append(el('span', prefix + line, 'fb-records__counts'));
    }
    box.append(top);
    if (hasBusinessResponse(report)) box.append(renderDecisions(doc, report));
    // Past actions and commitments, only when there are some.
    const entries = (report.historical_responsibilities ?? []).flatMap((s) => s.entries);
    if (entries.length) {
      const history = el('div', '', 'fb-records__details');
      history.append(el('p', feedbackCopy(language, 'pastActions'), 'fb-basis__label'));
      for (const entry of entries) {
        history.append(el('p', entry.explanation));
        if (entry.sources.length) history.append(chips(entry.sources));
      }
      box.append(history);
    }
    const details = el('div', '', 'fb-records__details');
    details.id = `fb-records-${report.id}-${report.version}`.replace(/[^A-Za-z0-9_-]+/g, '-');
    for (const snapshot of snapshots) {
      if (snapshot.subject) details.append(chips([snapshot.subject]));
      details.append(
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
        ),
      );
      for (const text of snapshot.summary) details.append(el('p', text));
      const verified = snapshot.references.flatMap((x) => (x.verified_ref ? [x.verified_ref] : []));
      if (verified.length) details.append(chips(verified));
    }
    if (details.childElementCount) {
      const toggle = el('button', '', 'fb-scope__toggle');
      toggle.type = 'button';
      toggle.append(el('span', feedbackCopy(language, 'recordsDetails')), chevronNode());
      toggle.setAttribute('aria-controls', details.id);
      const wrap = el('div', '', 'fb-scope');
      wrap.append(toggle, details);
      box.append(wrap);
      disclosure(doc, toggle, details, `${report.id}:${report.version}:records`, disclosures, wrap);
    }
    return box;
  }
  function reportPanel(report: Report, role: 'latest' | 'earlier') {
    const review =
      report.subject.kind === 'review'
        ? adapter
            .snapshot()
            .reviews?.find(
              (r) => r.id === report.subject.object_id && r.version === report.subject.version,
            )
        : undefined;
    if (role === 'earlier') return earlierPanel(report, review);
    const panel = el('article', '', 'fb-report');
    panel.dataset.reportId = report.id;
    panel.append(
      el(
        'h2',
        report.subject.kind === 'review'
          ? T('作品评审反馈', 'Artifact review feedback')
          : feedbackCopy(language, 'itemsTitle'),
      ),
    );
    const purposeLine = reviewedAs(review, language);
    if (purposeLine) panel.append(el('p', purposeLine, 'muted'));
    if (report.subject.kind === 'review' && review) {
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
    // Workbench internals: kept with the report as hidden records, read in About.
    panel.append(
      evaluationVersionLine(doc, report, language),
      evaluationModelLine(doc, report.provenance, language, report.subject.session_id),
    );
    const id = `${report.id}:${report.version}`;
    const state = adapter.snapshot();
    const canReview = !!adapter.review && adapter.canReview !== false && state.status === 'active';
    const unknown = purposeUnknown(report, review);
    const later = unknown && review ? laterPurpose(review, state.reviews ?? []) : undefined;
    if (later)
      panel.append(
        el(
          'p',
          feedbackCopy(language, 'purposeChosen', { purpose: feedbackCopy(language, later) }),
          'muted',
        ),
      );
    else if (unknown) {
      panel.append(el('p', feedbackCopy(language, 'purposeUnknown', { n: ruleItems(report).length }), 'muted'));
      if (review && canReview)
        panel.append(
          purposePromptElement(doc, language, {
            name: `purpose-${id}`,
            selected: purposeChoices.get(id) ?? declaredPurpose(review.subjects, state.products),
            disabled: state.busy || !!state.pending,
            select: (purpose) => purposeChoices.set(id, purpose),
            submit: (purpose) => void reviewAgain(review, purpose),
          }),
        );
    }
    if (ruleItems(report).length) panel.append(itemsSection(report, review, false));
    else panel.append(el('p', feedbackCopy(language, 'noItems'), 'muted'));
    // Without an R2.support row (no criteria yet, or an older record), the advice still lives in
    // a closed "判断的证据支持" row of its own.
    if (!ruleItems(report).some((item) => item.criterion === 'R2.support') && showsAdviceBlock(report)) {
      const fallback = adviceFallback(report, adapter.snapshot());
      const said = adviceRowLine(report.model_advice, language, fallback);
      const alone = el('section', '', 'fb-group');
      alone.dataset.group = 'advice';
      const list = el('ul', '', 'fb-list');
      list.append(
        renderItemRow(
          doc,
          {
            criterion: 'R2.support',
            name: criterionLabels(language)['R2.support'] ?? '',
            mark: 'unknown',
            line: said?.text ?? criterionQuestions(language)['R2.support'] ?? '',
            ...(said?.tone === 'bad' ? { lineTone: 'bad' as const } : {}),
            ...(said?.waiting ? { lineWaits: true } : {}),
            checks: criterionChecks(language)['R2.support'],
            found: [],
            item: { criterion: 'R2.support', explanation: '', source: 'model_advice', label: 'INSUFFICIENT', citations: [] },
          },
          language,
          {
            id: `${report.id}-${report.version}`,
            ...disclosures,
            basis: () => [adviceBlock(report, lensOn())],
          },
        ),
      );
      alone.append(list);
      panel.append(alone);
    }
    panel.append(recordsSection(report));
    const general = responseForm(report);
    // The one honest line of the page, and a way to disagree with the feedback as a whole.
    const honest = el('p', '', 'fb-honest');
    const mark = el('span', '?', 'fb-mark');
    mark.setAttribute('aria-hidden', 'true');
    const differ = el('button', T('我有不同看法', 'I see it differently'), 'btn small quiet');
    differ.type = 'button';
    differ.dataset.respondIntent = 'objection';
    differ.addEventListener('click', () => openResponse(general, 'objection'));
    honest.append(mark, el('span', feedbackCopy(language, 'honest'), 'fb-honest__text'), differ);
    panel.append(honest, general);
    return panel;
  }
  /** An earlier delivery (or a review made before the latest delivery) in one line; opened, its
   * items as they were, read-only. */
  function earlierPanel(report: Report, review: ReviewRecord | undefined) {
    const panel = el('article', '', 'fb-earlier');
    panel.dataset.reportId = report.id;
    const head = el('h2', '', 'fb-earlier__head');
    const subject = chips([report.subject]).firstElementChild as HTMLElement | null;
    const view = feedbackItemsView(report, {
      language,
      decision: decisionOf(report, review),
      kind: report.subject.kind,
      atSubmission: savedRuleCheck(report),
    });
    const decision = decisionOf(report, review);
    const lead =
      report.subject.kind === 'review'
        ? (reviewedAs(review, language) ?? feedbackCopy(language, 'reviewRow'))
        : decision
          ? decisionName(decision, language)
          : '';
    const toggle = el('button', '', 'fb-earlier__toggle');
    toggle.type = 'button';
    toggle.append(
      el('span', [lead, earlierSummary(view, language)].filter(Boolean).join(' · '), 'fb-earlier__summary'),
      chevronNode(),
    );
    if (subject) head.append(subject);
    head.append(toggle);
    const body = el('div', '', 'fb-earlier__body');
    body.id = `fb-earlier-${report.id}-${report.version}`.replace(/[^A-Za-z0-9_-]+/g, '-');
    toggle.setAttribute('aria-controls', body.id);
    body.append(evaluationVersionLine(doc, report, language));
    if (ruleItems(report).length) body.append(itemsSection(report, review, true));
    panel.append(head, body);
    disclosure(doc, toggle, body, `${report.id}:${report.version}:earlier`, disclosures, panel);
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
  function syncSubmit() {
    const state = adapter.snapshot();
    const locked = state.status !== 'active' || state.busy || !!state.pending || adapter.canSubmit === false;
    choice.disabled = locked;
    submit.disabled = locked || !isSubmitDecision(choice.value) || !selected.size;
  }
  function renderSelected() {
    syncSubmit();
    checkUnsaved();
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
    form.dataset.intent = 'supplement';
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
    // The result page: until the records are read, the sheet's shape; the parts below wait.
    if (options.layout === 'result') {
      for (const part of [refreshRow, reviewControls?.element])
        if (part) part.hidden = !view || view.waiting;
      if (!view && state.busy) {
        if (coverShown !== 'skeleton') {
          coverShown = 'skeleton';
          coverHost.replaceChildren(renderResultSkeleton(doc, language));
        }
        return;
      }
    }
    const signature = JSON.stringify([
      view,
      !!actions?.supplement,
      !!actions?.revise,
      actions?.backToBoard,
      state.feedbackPhase,
      state.busy,
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
      const wait = {
        phase: state.feedbackPhase,
        reading: state.busy,
        seconds: waitSeconds(state),
        freshStamp: pressed !== undefined,
        pressElapsed: pressed,
      };
      const cover =
        view && actions
          ? options.layout === 'result'
            ? renderResultHead(doc, view, language, { ...actions, locate }, wait)
            : renderCover(doc, view, language, actions, wait)
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
      const arriving = !!cover && coverWaited && !view?.waiting;
      if (arriving && options.layout !== 'result') cover.classList.add('is-arriving');
      coverWaited = !!view?.waiting;
      coverHost.replaceChildren(...(cover ? [cover] : []));
      // The result page: rises as it takes over the desk, presses a fresh stamp, and rolls its
      // readings from 0 when they first show (on entry, or when the review arrives).
      if (options.layout === 'result' && cover && view) {
        const shown = state.submission?.ref.object_id ?? 'new';
        const entrance = entranceFor(
          doc,
          `${shown}:${view.waiting ? 'waiting' : 'ready'}`,
          view.waiting,
        );
        if (entrance)
          queueMicrotask(
            () =>
              void playEntrance(cover, { ...entrance, stamp: entrance.rise && pressed !== undefined }),
          );
        if (!view.waiting && state.submission) resultSeen(state.submission.ref.object_id);
      }
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
      ticker =
        options.layout === 'result'
          ? tickClock(coverHost, () => adapter.snapshot().feedbackSince)
          : (() => {
              const id = setInterval(() => {
                const clock = coverHost.querySelector<HTMLElement>('[data-elapsed]');
                const seconds = waitSeconds(adapter.snapshot());
                if (clock && seconds !== undefined)
                  clock.textContent = elapsedWords(seconds, language);
              }, 1000);
              return () => clearInterval(id);
            })();
    if (!waiting && ticker) {
      ticker();
      ticker = undefined;
    }
  }
  function render() {
    if (destroyed) return;
    // A delivery in flight: the dialog is left as it was pressed until the result page takes over.
    if (submitting && options.surface === 'submission') return;
    const state = adapter.snapshot();
    reviewControls?.render();
    failedNote.hidden = !state.failedFeedback;
    retryFeedback.hidden = !state.failedFeedback || !adapter.retry;
    retryFeedback.disabled = state.busy || adapter.canRetry === false;
    notice.textContent = feedbackNotice(state, language);
    if (options.surface !== 'submission') renderCoverNow(state);
    // With the cover shown, the status line stays for screen readers only; the cover says it.
    // In the delivery dialog the plain "keep working, choose versions" line is read, not shown:
    // the dialog opens with one sentence under its heading.
    const plainDelivery =
      options.surface === 'submission' &&
      state.status !== 'submitted' &&
      !state.busy &&
      !state.pending;
    notice.classList.toggle('sr-only', !!coverHost.firstElementChild || plainDelivery);
    restoreChoice(state);
    defaultChoice(state);
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
    syncSubmit();
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
      if (state.status === 'active') {
        const previous = el('details', '', 'delivery-previous');
        previous.append(el('summary', T('之前的交付 · ', 'Previous delivery · ') + snapshotHeading(state.submission.ref, catalog, language)));
        refs(previous, state.submission.products);
        receipt.append(previous);
      } else {
        receipt.append(el('h3', snapshotHeading(state.submission.ref, catalog, language)));
        refs(receipt, state.submission.products);
      }
    }
    // Keep active text editing in place; a focused disclosure must not prevent a new
    // report from arriving. Its stable control identity and openKeys survive the redraw.
    const reportFocus = reports.contains(doc.activeElement) ? doc.activeElement as HTMLElement : null;
    const editingResponse = reportFocus?.matches('textarea, input, select, [contenteditable="true"]');
    const focusReportId = reportFocus?.closest<HTMLElement>('[data-report-id]')?.dataset.reportId;
    const focusControls = reportFocus?.getAttribute('aria-controls');
    const focusText = reportFocus?.textContent;
    if (!editingResponse) {
      const expanded = new Set(
        [...reports.querySelectorAll<HTMLDetailsElement>('details[data-response-id][open]')].map(
          (n) => n.dataset.responseId,
        ),
      );
      const intents = new Map(
        [...reports.querySelectorAll<HTMLDetailsElement>('details[data-response-id]')].map(
          (n) => [n.dataset.responseId, n.dataset.intent],
        ),
      );
      const latest = state.submission?.ref;
      // The latest delivery's feedback in full; earlier deliveries (and, once something is
      // delivered, reviews made before) one line each.
      const roleOf = (report: Report): 'latest' | 'earlier' =>
        report.subject.kind === 'submission'
          ? !latest ||
            (report.subject.object_id === latest.object_id &&
              report.subject.version === latest.version)
            ? 'latest'
            : 'earlier'
          : latest
            ? 'earlier'
            : 'latest';
      const ordered = [...state.reports].sort(
        (a, b) => Number(roleOf(a) === 'earlier') - Number(roleOf(b) === 'earlier'),
      );
      const panels: Node[] = [];
      const earlier = ordered.filter((report) => roleOf(report) === 'earlier');
      for (const report of ordered) {
        if (report === earlier[0])
          panels.push(
            el(
              'h2',
              feedbackCopy(
                language,
                earlier.some((r) => r.subject.kind === 'review')
                  ? 'earlierDeliveriesAndReviews'
                  : 'earlierDeliveries',
              ),
              'fb-earlier-title',
            ),
          );
        panels.push(reportPanel(report, roleOf(report)));
      }
      reports.replaceChildren(...panels);
      for (const detail of reports.querySelectorAll<HTMLDetailsElement>(
        'details[data-response-id]',
      )) {
        detail.open = expanded.has(detail.dataset.responseId);
        const intent = intents.get(detail.dataset.responseId);
        if (intent) detail.dataset.intent = intent;
      }
      if (reportFocus) {
        const panel = [...reports.querySelectorAll<HTMLElement>('[data-report-id]')]
          .find((node) => node.dataset.reportId === focusReportId);
        const replacement = [...(panel ?? reports).querySelectorAll<HTMLElement>('button, summary, a')]
          .find((node) => focusControls
            ? node.getAttribute('aria-controls') === focusControls
            : node.tagName === reportFocus.tagName && node.textContent === focusText);
        replacement?.focus({ preventScroll: true });
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
        { lens: lensOn() && !node.closest('.fb-earlier'), sessionId: report?.subject.session_id },
      );
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
        el('h3', T('已记下的看法与补充依据', 'Saved views and added evidence')),
      );
      for (const response of listed)
        responseHistory.append(
          el('p', recordedText(response.kind)),
          el('blockquote', response.text),
        );
    }
    // On the result page the note waits for the result sheet (it is the page's last step).
    revisions.hidden = !revisionVisible(state);
    const round = state.submission
      ? state.references?.deliveries?.[state.submission.ref.object_id]
      : undefined;
    revisionReason.placeholder = Number.isFinite(round)
      ? T(
          `这次要补什么、改什么？第 ${round} 次交付和它的反馈都会保留。`,
          `What will you add or change? Delivery ${round} and its feedback stay on record.`,
        )
      : T(
          '这次要补什么、改什么？这次交付和它的反馈都会保留。',
          'What will you add or change? This delivery and its feedback stay on record.',
        );
    // The time beside the refresh control: when feedback last arrived or was read again here.
    const shownReports = state.reports.map((r) => `${r.id}:${r.version}`).join('|');
    if (shownReports !== readReports) {
      readReports = shownReports;
      readAt = Date.now();
    }
    updated.textContent = state.reports.length
      ? feedbackCopy(language, 'updatedAt', { time: clockTime(readAt, language) })
      : '';
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
  const unlens = onLensChange(() => {
    render();
  });
  // The topbar's "Revise" on the result page opens the revision note here.
  const onRevise = () => {
    if (options.surface !== 'submission') openRevision();
  };
  doc.addEventListener('rolecraft:result-revise', onRevise);
  render();
  return {
    refresh: () => act(() => adapter.refresh()),
    destroy: () => {
      destroyed = true;
      ticker?.();
      viewSwitch?.destroy();
      doc.removeEventListener('rolecraft:result-revise', onRevise);
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

/** Hours and minutes of a moment, as the page's clock shows it. */
function clockTime(at: number, language: FeedbackLanguage): string {
  return new Date(at).toLocaleTimeString(language === 'en' ? 'en-GB' : 'zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** The workbench's refresh glyph (art.js `refresh`), drawn as an element. */
function refreshIcon(doc: Document): SVGSVGElement {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = doc.createElementNS(ns, 'svg');
  svg.setAttribute('class', 'i i-sm');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  for (const d of ['M19.5 12a7.5 7.5 0 1 1-2.2-5.3', 'M19.5 4.5v4.2h-4.2']) {
    const path = doc.createElementNS(ns, 'path');
    path.setAttribute('d', d);
    svg.append(path);
  }
  return svg;
}

/** The stored empty default of the business response, in either language: nothing to show. */
const EMPTY_BUSINESS = new Set([
  '当前没有可核验的业务决定记录。',
  'No verifiable business decision record is currently available.',
]);
function hasBusinessResponse(report: Report): boolean {
  const text = report.business_response.trim();
  return !!text && !EMPTY_BUSINESS.has(text);
}

type Snapshot = NonNullable<Report['verified_facts']>[number];
const ACTIVITY: readonly [string, 'activityMaterial' | 'activityTest' | 'activityQuestion' | 'activityReply' | 'activityShown'][] = [
  ['material_read', 'activityMaterial'],
  ['test_run', 'activityTest'],
  ['question_sent', 'activityQuestion'],
  ['reply_received', 'activityReply'],
  ['learner_displayed', 'activityShown'],
];
/** One line of counts from the verified facts: what was read, run and asked, and the cited
 * sources, e.g. "读资料 9 次 · 测试 5 次 · 问同事 3 次 · 收到回复 3 条 · 引用资料 2 份（都是当时
 * 有效版本）". Only verified records are counted; completeness stays in Details. */
export function recordCounts(snapshot: Snapshot, language: FeedbackLanguage): string {
  const parts: string[] = [];
  for (const [kind, key] of ACTIVITY) {
    const total = snapshot.activity_totals?.[kind];
    const n = total?.verified_records ?? 0;
    if (n > 0) parts.push(feedbackCount(language, key, n));
  }
  const n = snapshot.verified_source_count ?? 0;
  if (n > 0) {
    const checked = snapshot.references.filter((ref) => ref.verified_ref);
    const expired = checked.filter((ref) => ref.valid_at_subject === false).length;
    const current = checked.filter((ref) => ref.valid_at_subject === true).length;
    parts.push(
      expired
        ? feedbackCopy(language, 'sourcesExpired', { n, expired })
        : current >= n
          ? feedbackCopy(
              language,
              n === 1 ? 'sourcesCurrentOne' : n === 2 ? 'sourcesCurrentTwo' : 'sourcesCurrent',
              { n },
            )
          : feedbackCount(language, 'sources', n),
    );
  }
  return parts.join(' · ');
}
