/** S8 · A review's report (plan §13.10): the regression report component (190/191, reviewed),
 * headed by which review this is; from the second review on, how it compares with the one before;
 * a note when the change touched more settings than its description listed; and the actions:
 * all clear → back to the product manager (ink), otherwise fix it again (ink), with the other
 * offered too. Below, this ticket's reviews in order. */
import { T } from '../../app/i18n';
import { roleOf } from '../../shell';
import {
  engineerReportView,
  renderEngineerReport,
  type EngineerReviewRecord,
} from '../engineer-report';
import { reviewViewOptions } from '../engineer-report/page';
import { failureText, type EngineerApi } from './api';
import { engineerHatTitle } from './copy';
import { countNode, key, setBusy, setCount } from './bits';
import { append, el, workLang } from './dom';
import { reviewResult } from './hand-back';
import { clock, nextAfterReview, type TicketDetail } from './model';
import { arrive, byKeyboard, reducedMotion } from './motion';
import { ticketTask } from './steps/ticket';
import { deskStage, handBack, publishReview } from './wire';

export interface ReviewContext {
  readonly doc: Document;
  readonly sessionId: string;
  readonly api: EngineerApi;
  /** Already read (the review just signed): drawn at once, so the stamp can fly to the headline. */
  readonly cached: { record: EngineerReviewRecord; ticket: TicketDetail } | null;
  navigate(route: 'engineer' | 'engineer-review' | 'work', id?: string): void;
  remember(reviewId: string, ticketId: string): void;
  title(short: string): void;
}

type Outcome = {
  clean: boolean;
  newFailures: number;
  fixed: number;
  passed: number;
  total: number;
};

function outcomeOf(record: EngineerReviewRecord, language: 'zh' | 'en'): Outcome {
  const view = engineerReportView(record.report, reviewViewOptions(record, language));
  const results = record.report.public_results;
  return {
    clean: nextAfterReview(view) === 'board',
    newFailures: record.report.hidden_comparison?.new_failures ?? 0,
    fixed: record.report.hidden_comparison?.fixed ?? 0,
    passed: results.filter((r) => r.result === 'pass').length,
    total: results.length,
  };
}

export class EngineerReviewScreen {
  readonly element: HTMLElement;
  private basisOpen = false;
  private entered = false;
  private readonly records = new Map<string, EngineerReviewRecord>();

  constructor(
    private readonly ctx: ReviewContext,
    private readonly reviewId: string,
  ) {
    this.element = el(ctx.doc, 'div', { class: 'ed ed-review' });
    if (ctx.cached && ctx.cached.record.review_id === reviewId) {
      this.records.set(reviewId, ctx.cached.record);
      this.ctx.remember(reviewId, ctx.cached.record.ticket_id);
      this.draw(ctx.cached.record, ctx.cached.ticket);
      void this.loadOthers(ctx.cached.ticket);
    } else {
      this.element.append(
        el(
          ctx.doc,
          'p',
          { class: 'ed-loading', role: 'status' },
          T('正在读取报告…', 'Loading the report…'),
        ),
      );
      void this.load();
    }
  }

  destroy() {}

  private async load() {
    const doc = this.ctx.doc;
    try {
      const review = await this.ctx.api.review(this.reviewId);
      this.records.set(review.review_id, review);
      this.ctx.remember(review.review_id, review.ticket_id);
      const ticket = await this.ctx.api.ticket(review.ticket_id).catch(() => null);
      this.draw(review, ticket);
      if (ticket) void this.loadOthers(ticket);
    } catch (error) {
      const retry = key(doc, T('重试', 'Try again'), 'ghost', {}, 'refresh');
      retry.addEventListener('click', () => {
        this.element.replaceChildren(
          el(
            doc,
            'p',
            { class: 'ed-loading', role: 'status' },
            T('正在读取报告…', 'Loading the report…'),
          ),
        );
        void this.load();
      });
      this.element.replaceChildren(
        el(
          doc,
          'div',
          { class: 'ed-empty-state' },
          el(doc, 'p', { role: 'alert' }, failureText(error)),
          retry,
        ),
      );
    }
  }

  /** The other reviews of this ticket: for the comparison and the marks in the list. */
  private async loadOthers(ticket: TicketDetail) {
    const missing = ticket.reviews.filter((r) => !this.records.has(r.review_id));
    if (!missing.length) return;
    await Promise.all(
      missing.map((r) =>
        this.ctx.api
          .review(r.review_id)
          .then((rec) => this.records.set(rec.review_id, rec))
          .catch(() => {}),
      ),
    );
    const record = this.records.get(this.reviewId);
    if (record) this.draw(record, ticket, true);
  }

  private draw(review: EngineerReviewRecord, ticket: TicketDetail | null, again = false) {
    const doc = this.ctx.doc;
    const language = T('zh', 'en') as 'zh' | 'en';
    const reviews = ticket?.reviews ?? [];
    const index = reviews.findIndex((r) => r.review_id === review.review_id);
    const view = engineerReportView(review.report, reviewViewOptions(review, language));
    const now = outcomeOf(review, language);
    const result = reviewResult(review, language);
    publishReview(review.review_id, {
      ticketId: review.ticket_id,
      outcome: now.clean ? 'clean' : 'regressed',
      newFailures: result.newFailures,
      result,
      source: ticket?.source,
    });
    if (ticket) this.ctx.title(engineerHatTitle(ticket));
    // Reviews left after this one (an older report says what was left then).
    const left =
      ticket && index >= 0 ? Math.max(0, ticket.review_budget.limit - (index + 1)) : null;
    const fromAgent =
      review.draft_executor?.kind === 'external_agent' ||
      review.draft_executor?.kind === 'reference_agent';
    const task = ticket ? ticketTask(ticket).title : T('复核报告', 'Review report');

    // The actions: what to do next leads. The one ink key is the top bar's whenever it shows one
    // (the desk's stage is known: it follows this review once read); without it, after a reload
    // straight onto a report, the report's own key takes the ink.
    const inBar = !!deskStage(this.ctx.sessionId).primary;
    const lead = inBar ? 'secondary' : 'primary';
    const again_ = key(
      doc,
      T('再修一轮', 'Fix it again'),
      now.clean ? 'secondary' : lead,
      { id: 'ed-again' },
      'refresh',
    );
    again_.addEventListener('click', () =>
      this.ctx.navigate('engineer', `${review.ticket_id}?step=fix`),
    );
    const back = key(
      doc,
      // An engineer's practice hands the report to Grace (phase 2); she may return it.
      roleOf(this.ctx.sessionId) === 'engineer'
        ? T('交回 Grace', 'Hand to Grace')
        : now.clean
          ? T('交回产品经理', 'Back to the product manager')
          : T('先交回产品经理', 'Hand back anyway'),
      now.clean ? lead : 'secondary',
      { id: 'ed-hand-back' },
    );
    back.addEventListener('click', () => {
      setBusy(back, true);
      back.disabled = true;
      (back.querySelector('.ed-k__label') as HTMLElement).textContent = T(
        '正在交回…',
        'Handing back…',
      );
      handBack(this.ctx.sessionId, review.review_id);
      // Grace answers by rule in the same request; the key comes back for another try.
      if (roleOf(this.ctx.sessionId) === 'engineer')
        setTimeout(() => {
          setBusy(back, false);
          back.disabled = false;
          (back.querySelector('.ed-k__label') as HTMLElement).textContent = T(
            '交回 Grace',
            'Hand to Grace',
          );
        }, 1500);
    });
    const sheetKey = key(doc, T('看签字单', 'See the sign-off sheet'), 'ghost', {
      id: 'ed-see-sheet',
    });
    sheetKey.addEventListener('click', () =>
      this.ctx.navigate('engineer', `${review.ticket_id}?step=signoff`),
    );
    const actions = el(
      doc,
      'div',
      { class: 'ed-review__actions' },
      ...(now.clean ? [back, again_] : [again_, back]),
      sheetKey,
    );

    const head = el(
      doc,
      'header',
      { class: 'ed-review__head' },
      el(
        doc,
        'h1',
        { class: 'ed-review__title', id: 'ed-title', tabindex: '-1' },
        el(
          doc,
          'span',
          {
            class: 'ed-review__task',
            lang: ticket ? workLang(T('zh', 'en') as 'zh' | 'en') : null,
          },
          task,
        ),
        el(
          doc,
          'span',
          { class: 'ed-eyebrow' },
          [
            index >= 0 ? T(`第 ${index + 1} 次复核`, `Review ${index + 1}`) : '',
            clock(review.signed_at),
            left !== null ? T(`还剩 ${left} 次`, `${left} left`) : '',
            fromAgent ? T('草稿来自你的 Agent', 'Draft from your agent') : '',
          ]
            .filter(Boolean)
            .join(' · '),
        ),
      ),
      actions,
    );

    // Compared with the review before (from the second one on).
    const prevSummary = index > 0 ? reviews[index - 1] : null;
    const prev = prevSummary ? this.records.get(prevSummary.review_id) : undefined;
    let compare: HTMLElement | null = null;
    const rolls: [Element, number][] = [];
    if (prev) {
      const before = outcomeOf(prev, language);
      const group = (
        label: string,
        from: number,
        to: number,
        better: 'down' | 'up',
        suffix = '',
      ) => {
        const count = countNode(doc, from);
        rolls.push([count, to]);
        const delta = to === from ? 0 : to < from === (better === 'down') ? 1 : -1;
        return el(
          doc,
          'li',
          { class: 'ed-compare-row__item', 'data-delta': String(delta) },
          el(doc, 'span', { class: 'ed-mini' }, label),
          el(
            doc,
            'span',
            { class: 'ed-compare-row__nums' },
            el(doc, 'span', { class: 'ed-compare-row__was' }, `${from}${suffix}`),
            el(doc, 'span', { class: 'ed-diff__arrow', 'aria-hidden': 'true' }, '→'),
            el(doc, 'b', {}, count, suffix),
            delta > 0
              ? el(
                  doc,
                  'span',
                  {
                    class: 'ed-compare-row__mark',
                    'data-tone': 'good',
                    'aria-label': T('变好', 'better'),
                  },
                  '✓',
                )
              : delta < 0
                ? el(
                    doc,
                    'span',
                    {
                      class: 'ed-compare-row__mark',
                      'data-tone': 'warn',
                      'aria-label': T('变差', 'worse'),
                    },
                    '↓',
                  )
                : null,
          ),
        );
      };
      compare = el(
        doc,
        'section',
        { class: 'ed-compare-row', 'aria-labelledby': 'ed-compare-h' },
        el(
          doc,
          'h2',
          { class: 'ed-label', id: 'ed-compare-h' },
          T(`和第 ${index} 次复核相比`, `Compared with review ${index}`),
        ),
        el(
          doc,
          'ul',
          {},
          group(T('新增失败', 'New failures'), before.newFailures, now.newFailures, 'down'),
          group(T('隐藏修好', 'Hidden fixed'), before.fixed, now.fixed, 'up'),
          group(T('公开通过', 'Public passed'), before.passed, now.passed, 'up', `/${now.total}`),
        ),
      );
    }

    // When something new fails and the change touched more than its description says.
    const draft = ticket?.latest_draft?.id === review.draft_id ? ticket.latest_draft : null;
    const actual = draft ? Object.keys(draft.changes).length : 0;
    const stated = draft ? draft.change_statements.length : 0;
    let note: HTMLElement | null = null;
    if (now.newFailures > 0 && draft && actual > stated) {
      const look = key(doc, T('对照签字单', 'Compare on the sign-off sheet'), 'ghost', {}, 'chev');
      look.addEventListener('click', () =>
        this.ctx.navigate('engineer', `${review.ticket_id}?step=signoff`),
      );
      note = el(
        doc,
        'aside',
        { class: 'ed-note' },
        el(
          doc,
          'p',
          {},
          T(
            `这次的实际改动有 ${actual} 处，说明里写了 ${stated} 处。`,
            `This change touches ${actual} settings; the description lists ${stated}.`,
          ),
        ),
        look,
      );
    }

    const sheet = renderEngineerReport(doc, view, {
      basisOpen: this.basisOpen,
      onBasisToggle: (open) => {
        this.basisOpen = open;
      },
    });
    // The code handed in with the signed draft, right after the hidden checks.
    const code = review.code;
    if (code) {
      const part = el(
        doc,
        'section',
        { class: 'er-section er-section--code', 'aria-labelledby': 'er-code-h' },
        el(
          doc,
          'div',
          { class: 'er-section__head' },
          el(
            doc,
            'h3',
            { class: 'er-section__title', id: 'er-code-h' },
            T('附带代码', 'Code handed in'),
          ),
          el(
            doc,
            'span',
            { class: 'er-section__aside' },
            T(
              `公开 ${code.counts.passed}/${code.counts.total} · 隐藏 ${code.hidden.passed}/${code.hidden.total}`,
              `public ${code.counts.passed}/${code.counts.total} · hidden ${code.hidden.passed}/${code.hidden.total}`,
            ),
          ),
        ),
        el(
          doc,
          'p',
          { class: 'er-note' },
          T(
            '金额由这段代码从现行条款里抽取；平台在隔离进程里重跑了公开和隐藏用例。代码指纹 ',
            'The amount is extracted by this code from the clause in force; the platform re-ran the public and hidden cases in an isolated process. Code fingerprint ',
          ),
          el(doc, 'code', { lang: 'en' }, code.code_sha256.slice(0, 12)),
        ),
      );
      const hidden = sheet.querySelector('.er-section--hidden');
      if (hidden) hidden.after(part);
      else sheet.append(part);
    }

    const list =
      reviews.length > 1
        ? el(
            doc,
            'nav',
            { class: 'ed-review__list', 'aria-labelledby': 'ed-review-list-h' },
            el(
              doc,
              'h2',
              { class: 'ed-label', id: 'ed-review-list-h' },
              T('这份委托的复核', 'Reviews of this ticket'),
            ),
            el(
              doc,
              'ol',
              {},
              ...reviews.map((r, i) => {
                const current = r.review_id === review.review_id;
                const rec = this.records.get(r.review_id);
                const o = rec ? outcomeOf(rec, language) : null;
                const open = el(
                  doc,
                  'button',
                  {
                    type: 'button',
                    class: 'ed-review__item',
                    id: `ed-rl-${i}`,
                    'aria-current': current ? 'page' : null,
                    disabled: current,
                  },
                  el(
                    doc,
                    'span',
                    { class: 'ed-review__n' },
                    T(`第 ${i + 1} 次`, `Review ${i + 1}`),
                  ),
                  el(doc, 'time', { datetime: r.signed_at }, clock(r.signed_at)),
                  el(
                    doc,
                    'span',
                    {
                      class: 'ed-review__mark',
                      'data-tone': o ? (o.clean ? 'good' : 'warn') : 'unknown',
                    },
                    o ? (o.clean ? '✓' : '↓') : '',
                  ),
                  el(
                    doc,
                    'span',
                    { class: 'ed-review__state' },
                    current
                      ? T('正在看', 'Viewing')
                      : o
                        ? o.clean
                          ? T('全过', 'All clear')
                          : T(
                              `新增 ${o.newFailures} 处失败`,
                              `${o.newFailures} new ${o.newFailures === 1 ? 'failure' : 'failures'}`,
                            )
                        : '',
                  ),
                );
                open.addEventListener('click', () =>
                  this.ctx.navigate('engineer-review', r.review_id),
                );
                return el(doc, 'li', {}, open);
              }),
            ),
          )
        : null;

    const focused = this.element.contains(doc.activeElement) ? doc.activeElement?.id : null;
    this.element.replaceChildren();
    // Under the headline: what the hidden checks also fixed (all clear), then how this compares
    // with the review before, then the note.
    const verdict = sheet.querySelector('.er-verdict');
    if (now.clean && now.fixed > 0)
      sheet
        .querySelector('.er-verdict__body')
        ?.append(
          el(
            doc,
            'p',
            { class: 'ed-review__also' },
            el(
              doc,
              'span',
              { class: 'ed-compare-row__mark', 'data-tone': 'good', 'aria-hidden': 'true' },
              '✓',
            ),
            T(`隐藏检查另修好 ${now.fixed} 处`, `The hidden checks also fixed ${now.fixed}`),
          ),
        );
    if (verdict) verdict.after(...[compare, note].filter((n): n is HTMLElement => !!n));
    append(this.element, head, el(doc, 'div', { class: 'ed-review__sheet' }, sheet), list);
    if (focused) doc.getElementById(focused)?.focus({ preventScroll: true });

    // The headline mark settles first; the numbers roll 200ms after it, the note comes last.
    const first = !this.entered;
    this.entered = true;
    const reduce = reducedMotion() || byKeyboard();
    if (first && !reduce && !again) arrive(sheet, 8, { duration: 0.28 });
    const delay = again || reduce ? 0 : 720;
    setTimeout(() => {
      for (const [node, to] of rolls) setCount(node, to);
    }, delay);
    if (note && first && !reduce) arrive(note, 4, { delay: 0.9 });
  }
}
