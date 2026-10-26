/** S6–S7 · The sign-off sheet (plan §13.8–13.9). The draft lies on paper: what actually changed
 * beside what the description says changed, each in its own order and never marked as matching
 * or not (that is the person's to see). Signing is held: the signature line draws for a second
 * under the pointer (a key press draws it in 400ms); then an ink stamp lands. While the review
 * runs the sheet stays, and says so. */
import { T } from '../../../app/i18n';
import { countNode, diffList, key, setBusy, setCount, squares } from '../bits';
import { agentNode, el, workLang } from '../dom';
import { holdToSign, type HoldKind } from '../hold';
import { move, reducedMotion } from '../motion';
import { clock, settingsDiff, signSheet, type Mark, type TicketDetail } from '../model';
// The shared stamp (206): the same double-ruled stamp as the result page, in ink.
import { createStamp, pressStamp } from '../../../shared/stamp/stamp';

const claimedSquares = (doc: Document, marks: readonly Mark[]) => {
  const node = squares(doc, marks);
  node.classList.add('is-claimed');
  return node;
};

/** Who wrote the draft, from the draft itself or, once signed, the review's record of it. */
const byAgent = (kind: string | undefined) =>
  kind === 'external_agent' || kind === 'reference_agent';

/** The draft on paper (everything above the impact note). */
export function sheetBody(doc: Document, ticket: TicketDetail): HTMLElement {
  const draft = ticket.latest_draft as NonNullable<TicketDetail['latest_draft']>;
  const sheet = signSheet(draft);
  const review = ticket.reviews.find((r) => r.draft_id === draft.id);
  const agent = review?.draft_executor ? byAgent(review.draft_executor.kind) : sheet.agent;
  const lang = workLang(ticket.work_language);
  const actual = settingsDiff(ticket.baseline_config, draft.changes, ticket.editable_fields);
  const claims = sheet.claims;
  const passed = claims.filter((c) => draft.claimed_results[c.id] === 'pass').length;
  return el(
    doc,
    'div',
    { class: 'ed-sheet__body' },
    el(
      doc,
      'p',
      { class: 'ed-sheet__byline' },
      agent ? agentNode(doc) : null,
      el(
        doc,
        'span',
        {},
        T(
          `${agent ? '草稿来自你的 Agent' : '草稿由你起草'} · ${sheet.time}`,
          `${agent ? 'Draft from your agent' : 'Drafted by you'} · ${sheet.time}`,
        ),
      ),
      agent && !review
        ? el(
            doc,
            'span',
            { class: 'ed-sheet__check' },
            T('签字前对照实际改动', 'Check the actual change before you sign'),
          )
        : null,
    ),
    el(
      doc,
      'div',
      { class: 'ed-compare' },
      el(
        doc,
        'section',
        { class: 'ed-compare__col', 'aria-labelledby': 'ed-actual-h' },
        el(
          doc,
          'h4',
          { class: 'ed-label', id: 'ed-actual-h', tabindex: '-1' },
          T('实际改动', 'What actually changed'),
        ),
        actual.length
          ? diffList(doc, actual)
          : el(
              doc,
              'p',
              { class: 'ed-meta' },
              T('和基线相同，没有改动。', 'Same as the baseline; nothing changed.'),
            ),
      ),
      el(
        doc,
        'section',
        { class: 'ed-compare__col', 'aria-labelledby': 'ed-stated-h' },
        el(
          doc,
          'h4',
          { class: 'ed-label', id: 'ed-stated-h' },
          T('说明里写的改动', 'What the description says'),
        ),
        sheet.stated.length
          ? el(
              doc,
              'ul',
              { class: 'ed-diff' },
              ...sheet.stated.map((c) =>
                el(
                  doc,
                  'li',
                  { class: 'ed-diff__row' },
                  el(doc, 'span', { class: 'ed-diff__name' }, c.name),
                  el(
                    doc,
                    'span',
                    { class: 'ed-diff__values' },
                    el(doc, 'del', { class: 'ed-diff__was' }, c.before),
                    el(doc, 'span', { class: 'ed-diff__arrow', 'aria-hidden': 'true' }, '→'),
                    el(doc, 'b', { class: 'ed-diff__now' }, c.after),
                  ),
                  c.reason ? el(doc, 'span', { class: 'ed-diff__reason', lang }, c.reason) : null,
                ),
              ),
            )
          : el(doc, 'p', { class: 'ed-meta' }, T('没有逐条写改动。', 'No change is stated.')),
      ),
    ),
    sheet.explanation
      ? el(doc, 'blockquote', { class: 'ed-sheet__explain', lang }, sheet.explanation)
      : null,
    draft.code
      ? el(
          doc,
          'p',
          { class: 'ed-sheet__code' },
          el(doc, 'span', { class: 'ed-label' }, T('附带代码', 'Code handed in')),
          el(
            doc,
            'span',
            {},
            T(
              `公开用例 ${draft.code.counts.passed}/${draft.code.counts.total}，隐藏用例 ${draft.code.hidden.passed}/${draft.code.hidden.total}（平台在隔离进程里实测）`,
              `public cases ${draft.code.counts.passed}/${draft.code.counts.total}, hidden ${draft.code.hidden.passed}/${draft.code.hidden.total} (run by the platform in an isolated process)`,
            ),
          ),
          el(doc, 'code', { class: 'ed-key', lang: 'en' }, draft.code.code_sha256.slice(0, 12)),
        )
      : null,
    el(
      doc,
      'p',
      { class: 'ed-sheet__claims' },
      claims.length
        ? [
            // A self-report is not checked yet: ink outlines, never green (green means it holds).
            claimedSquares(
              doc,
              claims.map(
                (c): Mark =>
                  draft.claimed_results[c.id] === 'pass'
                    ? 'good'
                    : draft.claimed_results[c.id] === 'fail'
                      ? 'ink'
                      : 'unknown',
              ),
            ),
            el(
              doc,
              'span',
              {},
              T(
                `自报：公开 ${passed}/${claims.length} 通过`,
                `Self-report: public ${passed}/${claims.length} passed`,
              ),
            ),
          ]
        : el(doc, 'span', { class: 'ed-meta' }, T('没有附自报结果', 'No self-report attached')),
    ),
    sheet.unresolved.length
      ? el(
          doc,
          'div',
          { class: 'ed-sheet__unresolved' },
          el(doc, 'h4', { class: 'ed-label' }, T('未修复项', 'Unresolved')),
          el(
            doc,
            'ul',
            {},
            ...sheet.unresolved.map((u) =>
              el(
                doc,
                'li',
                {},
                el(doc, 'span', { lang }, u.description),
                u.probes ? el(doc, 'code', { class: 'ed-key' }, u.probes) : null,
              ),
            ),
          ),
        )
      : null,
  );
}

export interface SignatureState {
  /** Reviews left on this ticket. */
  readonly left: number;
  /** Whether the latest draft can be signed now; otherwise why not. */
  readonly can: boolean;
  readonly reason: string;
  /** The latest draft is already signed: the stamp shows, with its time and its review. */
  readonly signedAt?: string;
  readonly signedReview?: string;
  readonly exhausted: boolean;
}

const reviewsWord = (n: number) => (n === 1 ? ' review left' : ' reviews left');

/** The signature block at the foot of the sheet: a ruled line, "You" at its left end, the reviews
 * left and the held key at its right. Signed, the ink stamp lands on the left end of the line. */
export class Signature {
  readonly element: HTMLElement;
  private readonly ink: HTMLElement;
  private readonly mark: HTMLElement;
  private readonly hint: HTMLElement;
  private readonly status: HTMLElement;
  private readonly meta: HTMLElement;
  private readonly leftCount: HTMLElement;
  private readonly leftWord: HTMLElement;
  readonly key: HTMLButtonElement;
  private readonly hold;
  private state: SignatureState | null = null;
  private running = false;
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor(
    private readonly doc: Document,
    private readonly hooks: {
      /** A reason not to sign now (impact note missing), or '' to go ahead. */
      precheck(): string;
      sign(): void;
      openReview(id: string): void;
      /** The hold was let go early: the sheet may redraw what it held back. */
      released(): void;
    },
  ) {
    this.ink = el(doc, 'span', { class: 'ed-signature__ink', 'aria-hidden': 'true' });
    this.mark = el(doc, 'span', {
      class: 'ed-signature__stamp',
      'aria-hidden': 'true',
      hidden: true,
    });
    this.hint = el(
      doc,
      'p',
      { class: 'ed-signature__hint', hidden: true },
      T('按住，直到签名线画完', 'Keep holding until the line is drawn'),
    );
    this.status = el(doc, 'p', { class: 'ed-signature__status', role: 'status', hidden: true });
    this.leftCount = countNode(doc, 0, 'ed-count');
    this.leftWord = el(doc, 'span', {});
    this.meta = el(
      doc,
      'span',
      { class: 'ed-signature__meta' },
      T('只能由你签 · 还剩 ', 'Only you can sign · '),
      this.leftCount,
      this.leftWord,
    );
    this.key = key(
      doc,
      T('按住签字', 'Hold to sign'),
      'primary',
      { id: 'ed-sign', class: 'ed-hold' },
      'edit',
    );
    this.hold = holdToSign({
      onStart: (kind, ms) => this.start(kind, ms),
      onCancel: (first) => this.cancel(first),
      onComplete: () => this.complete(),
    });
    const press = (kind: HoldKind) => {
      const problem = this.hooks.precheck();
      if (problem) return;
      this.hold.press(kind);
    };
    this.key.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || this.key.disabled) return;
      this.key.setPointerCapture?.(e.pointerId);
      press('pointer');
    });
    for (const type of ['pointerup', 'pointercancel', 'lostpointercapture'])
      this.key.addEventListener(type, () => this.hold.release());
    this.key.addEventListener('keydown', (e) => {
      if ((e.key === 'Enter' || e.key === ' ') && !e.repeat && !this.key.disabled) {
        e.preventDefault();
        press('keyboard');
      }
    });
    // A click alone (no hold) does nothing: the hold is the confirmation.
    this.key.addEventListener('click', (e) => e.preventDefault());
    this.element = el(
      doc,
      'div',
      { class: 'ed-signature' },
      el(doc, 'div', { class: 'ed-signature__line' }, this.ink, this.mark),
      el(
        doc,
        'div',
        { class: 'ed-signature__row' },
        el(doc, 'span', { class: 'ed-signature__who' }, T('你', 'You')),
        el(doc, 'div', { class: 'ed-signature__end' }, this.meta, this.key),
      ),
      this.hint,
      this.status,
    );
  }

  /** The line is being held (pointer down, or the 400ms of a key press). */
  holding(): boolean {
    return this.hold.state() === 'holding';
  }

  /** Reviews left, rolling when the number changes (it drops the moment the stamp lands). */
  setLeft(left: number) {
    setCount(this.leftCount, Math.max(0, left));
    this.leftWord.textContent = T(' 次复核', reviewsWord(left));
  }

  update(state: SignatureState) {
    this.state = state;
    const doc = this.doc;
    if (this.running) return;
    this.setLeft(state.left);
    if (state.signedAt) {
      this.showStamp(state.signedAt, false);
      this.key.hidden = false;
      this.key.disabled = true;
      (this.key.querySelector('.ed-k__label') as HTMLElement).textContent = T('已签', 'Signed');
      this.key.setAttribute('aria-label', T('已签', 'Signed'));
      this.status.hidden = !state.signedReview;
      if (state.signedReview) {
        const open = key(
          doc,
          T('看这次复核的报告', 'See this review’s report'),
          'ghost',
          { id: 'ed-signed-report' },
          'chev',
        );
        open.addEventListener('click', () => this.hooks.openReview(state.signedReview as string));
        this.status.replaceChildren(open);
        this.status.dataset.kind = 'link';
      }
      return;
    }
    this.mark.hidden = true;
    this.element.classList.remove('is-stamped');
    this.ink.classList.remove('is-held', 'is-signed');
    (this.key.querySelector('.ed-k__label') as HTMLElement).textContent = T(
      '按住签字',
      'Hold to sign',
    );
    this.key.setAttribute(
      'aria-label',
      T(
        `按住签字提交复核，只能由你签，还剩 ${state.left} 次复核`,
        `Hold to sign and submit for review. Only you can sign; ${state.left}${reviewsWord(state.left)}`,
      ),
    );
    this.key.hidden = state.exhausted;
    this.key.disabled = !state.can;
    if (state.reason) this.key.setAttribute('aria-describedby', 'ed-sign-reason');
    else this.key.removeAttribute('aria-describedby');
    this.status.id = 'ed-sign-reason';
    this.status.hidden = !state.reason;
    this.status.dataset.kind = 'reason';
    this.status.textContent = state.reason;
  }

  private start(kind: HoldKind, ms: number) {
    this.hint.hidden = true;
    this.key.classList.add('is-holding');
    // Signature moment (exception to transform/opacity): the line draws with clip-path.
    this.ink.style.transition = reducedMotion()
      ? 'none'
      : `clip-path ${ms}ms ${kind === 'keyboard' ? 'var(--ease-out)' : 'linear'}`;
    this.ink.classList.add('is-held');
  }

  private cancel(first: boolean) {
    this.key.classList.remove('is-holding');
    this.ink.style.transition = 'clip-path 200ms var(--ease-out)';
    this.ink.classList.remove('is-held');
    if (first) this.hint.hidden = false;
    this.hooks.released();
  }

  private complete() {
    this.key.classList.remove('is-holding');
    this.ink.classList.add('is-signed');
    this.running = true;
    this.hooks.sign();
  }

  /** The stamp lands on the left end of the line (pressed only when it is signed now). The time
   * is on the stamp, nowhere else on the line. */
  showStamp(at: string, animate: boolean) {
    this.mark.hidden = false;
    this.element.classList.add('is-stamped');
    this.ink.classList.add('is-held', 'is-signed');
    this.ink.style.transition = 'none';
    const stamp = createStamp(this.doc, {
      kicker: T('已签', 'Signed'),
      text: T('你', 'You'),
      when: clock(at),
      tone: 'ink',
      size: 'md',
      hidden: animate,
    });
    this.mark.replaceChildren(stamp);
    if (!animate) return;
    void pressStamp(stamp);
    // The paper gives 1px under the press.
    if (!reducedMotion())
      move(
        this.element.closest('.ed-sheet'),
        { transform: ['translateY(0)', 'translateY(1px)', 'translateY(0)'] },
        { duration: 0.16, delay: 0.12 },
      );
  }

  /** Signed: the stamp, one review fewer, then the review running line (a quiet shimmer; the
   * seconds after 3s are for the eye only, so readers hear the start and the end). */
  startReview(at: string, counts: { publicCount: number; hidden: number | null; left: number }) {
    this.running = true;
    this.showStamp(at, true);
    this.setLeft(counts.left);
    this.key.disabled = true;
    (this.key.querySelector('.ed-k__label') as HTMLElement).textContent = T('已签', 'Signed');
    this.key.setAttribute('aria-label', T('已签', 'Signed'));
    this.key.removeAttribute('aria-describedby');
    const started = Date.now();
    this.status.hidden = false;
    this.status.dataset.kind = 'running';
    const secs = el(this.doc, 'span', { class: 'ed-signature__secs', 'aria-hidden': 'true' });
    this.status.replaceChildren(
      el(
        this.doc,
        'span',
        { class: 'ed-shimmer' },
        counts.hidden === null
          ? T(
              `复核在跑 · 公开 ${counts.publicCount} 条 · 隐藏检查`,
              `Review running · ${counts.publicCount} public · hidden checks`,
            )
          : T(
              `复核在跑 · 公开 ${counts.publicCount} 条 · 隐藏 ${counts.hidden} 条`,
              `Review running · ${counts.publicCount} public · ${counts.hidden} hidden`,
            ),
      ),
      secs,
    );
    this.timer = setInterval(() => {
      const s = Math.round((Date.now() - started) / 1000);
      if (s > 3) secs.textContent = ` · 0:${String(s).padStart(2, '0')}`;
    }, 1000);
  }

  finished() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.status.replaceChildren(T('复核完成', 'Review done'));
  }

  failed(message: string) {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.running = false;
    setBusy(this.key, false);
    this.mark.hidden = true;
    this.element.classList.remove('is-stamped');
    this.ink.style.transition = 'clip-path 200ms var(--ease-out)';
    this.ink.classList.remove('is-held', 'is-signed');
    this.hold.reset();
    if (this.state) this.update(this.state);
    if (message) {
      this.status.hidden = false;
      this.status.dataset.kind = 'error';
      this.status.textContent = message;
    }
  }

  /** For the shared-element hand-off to the report's headline. */
  stampElement() {
    return this.mark;
  }

  release() {
    this.running = false;
    setBusy(this.key, false);
    this.hold.reset();
  }
}
