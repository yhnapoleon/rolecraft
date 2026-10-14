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
import { criterionWeightText } from './score-range';
import { sealReadOnly } from './read-only-notice';
import { criterionLabels } from './criteria';
import { exactRefKey } from './exact-ref';
import { mountPresubmitCard, PRESUBMIT_STYLE, submissionFactLine } from './presubmit';
import type { ObjectRef, EvidenceRefV2, WorkProductVersion } from '../workspace/contract-types';

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
  chooseEvidence?(): Promise<EvidenceRefV2[]>;
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
export type FeedbackMountOptions = { surface?: 'all' | 'submission' | 'feedback' };

export function mountNativeFeedback(
  host: HTMLElement,
  adapter: FeedbackNativeAdapter,
  options: FeedbackMountOptions = {},
) {
  const doc = host.ownerDocument;
  const language = adapter.snapshot().uiLanguage ?? adapter.snapshot().workLanguage ?? 'zh';
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  const versionLabel = (n: number) => (language === 'en' ? 'v' + n : '第 ' + n + ' 版');
  const selectedRefs = (n: number) =>
    language === 'en' ? `${n} original references selected` : `已选 ${n} 处原始引用`;
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
  const purposeChoices = new Map<string, PurposeChoice>();
  let savedDrafts: Promise<void> = Promise.resolve();
  let draftError: unknown;
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
  const choice = el('select', '', 'select');
  choice.setAttribute('aria-label', T('本次决定', 'Your decision'));
  for (const [value, text] of [
    ['', T('请选择本次决定', 'Choose a decision')],
    ['launch', T('按方案推进', 'Proceed with the proposal')],
    ['launch_narrow', T('缩小范围推进', 'Proceed with a limited scope')],
    ['defer_with_conditions', T('满足条件后再推进', 'Defer until conditions are met')],
    ['no_go', T('停止这项方案', 'Do not proceed with this proposal')],
  ]) {
    const option = el('option', text);
    option.value = value;
    choice.append(option);
  }
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
      await adapter.submit({ decision: choice.value, products: [...selected.values()] });
      adapter.rememberChoice?.(null);
    },
    true,
  );
  // Pre-submission preview (2026-10-14): read-only, right above the submit button.
  const load =
    options.surface !== 'feedback' ? adapter.previewSubmission?.bind(adapter) : undefined;
  const preview = load ? mountPresubmitCard(doc, language, load) : undefined;
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
  choice.addEventListener('change', syncPreview);
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
    choice,
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
    await adapter.beginRevision({ parent_submission: current.ref, reason: revisionReason.value });
  });
  revisions.append(el('h2', T('接着修订', 'Continue revising')), revisionReason, revise);
  const refresh = button(T('查看最新反馈', 'Refresh feedback'), () => adapter.refresh());
  root.append(failure, notice, failedNote, retryFeedback);
  if (options.surface !== 'feedback') root.append(submissions);
  if (options.surface === 'feedback') root.append(recover);
  if (options.surface !== 'submission') root.append(refresh, reports, responseHistory, revisions);
  const reviewControls =
    options.surface !== 'submission' && adapter.review
      ? mountReviewControls(doc, adapter, language)
      : undefined;
  if (reviewControls) root.insertBefore(reviewControls.element, reports);
  host.replaceChildren(root);
  function refs(parent: HTMLElement, values: (ObjectRef | EvidenceRefV2)[]) {
    const names: Record<string, string> = {
      product: T('作品', 'Artifact'),
      material: T('材料', 'Material'),
      test: T('测试', 'Test'),
      role_reply: T('同事回复', 'Colleague reply'),
      role_turn: T('问题', 'Question'),
      submission: T('提交记录', 'Submission'),
      review: T('评审记录', 'Review'),
      event: T('历史记录', 'History'),
    };
    const row = el('div');
    for (const ref of values) {
      const link = button(
        `${names[ref.kind] ?? T('依据', 'Evidence')} · ${versionLabel(ref.version)}`,
        () => adapter.openReference(ref),
      );
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
    let draft = draftResponses.get(id);
    if (!draft) {
      draft = adapter.readDraft(id) ?? { text: '', evidence: [] };
      draftResponses.set(id, draft);
    }
    const form = el('details');
    form.dataset.responseId = id;
    form.append(el('summary', T('提出异议或补充依据', 'Challenge or supplement the evidence')));
    const body = el('textarea', '', 'textarea');
    body.rows = 3;
    body.value = draft.text;
    body.setAttribute('aria-label', T('异议或补证内容', 'Challenge or additional evidence'));
    body.addEventListener('input', () => {
      draft!.text = body.value;
      void persist(id, draft!);
    });
    const evidence = el('p', '', 'muted');
    evidence.textContent = draft.evidence.length
      ? selectedRefs(draft.evidence.length)
      : T('补证引用尚未选择', 'No supporting references selected');
    const choose = button(
      T('选择已获准的原始引用', 'Choose authorized original references'),
      async () => {
        if (adapter.chooseEvidence) {
          draft!.evidence = await adapter.chooseEvidence();
          await persist(id, draft!);
          evidence.textContent = selectedRefs(draft!.evidence.length);
        }
      },
    );
    choose.disabled = !adapter.chooseEvidence;
    const send = (kind: 'objection' | 'supplement') => async () => {
      if (!draft!.text.trim())
        throw Error(
          T('请写下具体的异议或补充内容。', 'Describe your challenge or additional evidence.'),
        );
      await savedDrafts;
      if (draftError)
        throw Error(
          T(
            '回应草稿尚未保存，请先保留文字。',
            'The response draft is not saved. Keep a copy of your text.',
          ),
        );
      await adapter.respond({
        feedback_id: report.id,
        feedback_version: report.version,
        kind,
        section,
        criterion,
        text: draft!.text,
        evidence: draft!.evidence,
      });
      draft!.text = '';
      draft!.evidence = [];
      await persist(id, draft!);
      body.value = '';
      evidence.textContent = T('补证引用尚未选择', 'No supporting references selected');
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
        el('p', item.explanation),
      );
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
      );
    }
    for (const item of advice) {
      semantic.append(el('p', T('模型建议 · ', 'Model advice · ') + item.explanation));
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
      el('p', report.business_response),
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
  function render() {
    if (destroyed) return;
    const state = adapter.snapshot();
    reviewControls?.render();
    failedNote.hidden = !state.failedFeedback;
    retryFeedback.hidden = !state.failedFeedback || !adapter.retry;
    retryFeedback.disabled = state.busy || adapter.canRetry === false;
    notice.textContent = state.busy
      ? T('正在等待服务端确认…', 'Waiting for server confirmation…')
      : state.pending
        ? T(
            '上一请求结果尚未确认，请先恢复。',
            'The previous request is unresolved. Recover its result first.',
          )
        : state.status === 'submitted'
          ? state.reports.some((r) => r.subject.object_id === state.submission?.ref.object_id)
            ? T(
                '本次提交已保存，可以看反馈、提出异议或开始修订。',
                'Submission saved. Review feedback, raise a challenge or start revising.',
              )
            : T('本次提交已保存，反馈尚未就绪。', 'Submission saved. Feedback is not ready yet.')
          : T(
              '可以继续工作，选择准备交付的版本。',
              'Continue your work and select versions for submission.',
            );
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
        row.append(
          checkbox,
          el(
            'span',
            `${product.title || T('未命名作品', 'Untitled artifact')} · ${versionLabel(product.version)}${product.author.kind === 'external_agent' ? T(' · Agent制作', ' · Created by an Agent') : ''}`,
          ),
        );
        return row;
      }),
    );
    renderSelected();
    selectedSummary.hidden = state.status === 'submitted';
    if (state.status === 'submitted' && state.submission) choice.value = state.submission.decision;
    submit.disabled =
      state.status !== 'active' || state.busy || !!state.pending || adapter.canSubmit === false;
    choice.disabled = submit.disabled;
    recover.hidden = (!state.pending && !state.awaitingFeedback) || !adapter.recover;
    recover.disabled = state.busy;
    recover.textContent = state.awaitingFeedback
      ? T('查看反馈进度', 'Check feedback progress')
      : T('确认上一请求', 'Check the previous request');
    receipt.replaceChildren();
    if (state.submission) {
      receipt.append(el('h3', T('已保存的提交快照', 'Saved submission snapshot')));
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
    if (state.responses?.length) {
      responseHistory.append(
        el('h3', T('已记录的异议与补证', 'Recorded challenges and additional evidence')),
      );
      for (const response of state.responses) {
        responseHistory.append(
          el(
            'p',
            (response.kind === 'objection'
              ? T('异议已记录', 'Challenge recorded')
              : T('补证已记录', 'Additional evidence recorded')) +
              T(' · 等待核验', ' · Awaiting verification'),
          ),
          el('blockquote', response.text),
        );
      }
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
  render();
  return {
    refresh: () => act(() => adapter.refresh()),
    destroy: () => {
      destroyed = true;
      unsubscribe();
      reviewControls?.destroy();
      preview?.destroy();
      root.remove();
    },
  };
}

export { mountNativeFeedback as mount };
