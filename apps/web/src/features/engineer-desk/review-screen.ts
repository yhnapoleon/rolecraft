/** The report screen: one signed review's regression report (the 190 report component), the way
 * back to the desk for another round, and this ticket's reviews in order. No "send to product":
 * that hand-back is not built, so it is not offered. */
import { T } from '../../app/i18n';
import {
  renderEngineerReport,
  engineerReportView,
  type EngineerReviewRecord,
} from '../engineer-report';
import { reviewViewOptions } from '../engineer-report/page';
import { failureText, type EngineerApi } from './api';
import { append, button, el, iconNode, workLang } from './dom';
import { clock, type TicketDetail } from './model';

export interface ReviewContext {
  readonly doc: Document;
  readonly caseTitle: string;
  readonly api: EngineerApi;
  navigate(route: 'engineer' | 'engineer-review', id?: string): void;
  remember(reviewId: string, ticketId: string): void;
  /** Point the page's back key at the desk of this review's ticket. */
  backTo(ticketId: string): void;
}

export class EngineerReviewScreen {
  readonly element: HTMLElement;
  private basisOpen = false;
  private entered = false;

  constructor(
    private readonly ctx: ReviewContext,
    private readonly reviewId: string,
  ) {
    this.element = el(ctx.doc, 'div', { class: 'ed ed-review' });
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

  destroy() {}

  private async load() {
    const doc = this.ctx.doc;
    let review: EngineerReviewRecord;
    let ticket: TicketDetail | null = null;
    try {
      review = await this.ctx.api.review(this.reviewId);
      this.ctx.remember(review.review_id, review.ticket_id);
      this.ctx.backTo(review.ticket_id);
      try {
        ticket = await this.ctx.api.ticket(review.ticket_id);
      } catch {
        ticket = null;
      }
    } catch (error) {
      this.element.replaceChildren(
        el(
          doc,
          'div',
          { class: 'ed-empty-state' },
          el(doc, 'p', { role: 'alert' }, failureText(error)),
        ),
      );
      return;
    }
    this.draw(review, ticket);
  }

  private draw(review: EngineerReviewRecord, ticket: TicketDetail | null) {
    const doc = this.ctx.doc;
    const language = T('zh', 'en') as 'zh' | 'en';
    const reviews = ticket?.reviews ?? [];
    const index = reviews.findIndex((r) => r.review_id === review.review_id);
    const again = button(
      doc,
      [iconNode(doc, 'refresh', 'i-xs'), T('再修一轮', 'Fix it again')],
      'btn primary',
      { id: 'ed-again' },
    );
    again.addEventListener('click', () => this.ctx.navigate('engineer', review.ticket_id));
    const left = ticket
      ? Math.max(0, ticket.review_budget.limit - ticket.review_budget.used)
      : null;
    const head = el(
      doc,
      'header',
      { class: 'ed-head ed-review__head' },
      el(
        doc,
        'p',
        { class: 'ed-hat' },
        el(doc, 'span', { class: 'ed-hat__role' }, T('工程师', 'Engineer')),
        el(doc, 'span', { class: 'ed-hat__case' }, this.ctx.caseTitle),
      ),
      ticket
        ? el(
            doc,
            'h1',
            {
              class: 'ed-title',
              id: 'ed-title',
              tabindex: '-1',
              lang: workLang(ticket.work_language),
            },
            ticket.title,
          )
        : el(
            doc,
            'h1',
            { class: 'ed-title', id: 'ed-title', tabindex: '-1' },
            T('复核报告', 'Review report'),
          ),
      el(
        doc,
        'div',
        { class: 'ed-review__bar' },
        el(
          doc,
          'p',
          { class: 'ed-facts' },
          index >= 0
            ? el(
                doc,
                'span',
                { class: 'ed-fact' },
                T(`第 ${index + 1} 次复核`, `Review ${index + 1}`),
              )
            : null,
          el(doc, 'span', { class: 'ed-fact' }, clock(review.signed_at)),
          left !== null
            ? el(
                doc,
                'span',
                { class: 'ed-fact' },
                T(`还剩 ${left} 次复核`, `${left} ${left === 1 ? 'review' : 'reviews'} left`),
              )
            : null,
        ),
        again,
      ),
    );
    const sheet = renderEngineerReport(
      doc,
      engineerReportView(review.report, reviewViewOptions(review, language)),
      {
        basisOpen: this.basisOpen,
        onBasisToggle: (open) => {
          this.basisOpen = open;
        },
      },
    );
    if (!this.entered) {
      sheet.classList.add('ed-review__enter');
      sheet.addEventListener('animationend', () => sheet.classList.remove('ed-review__enter'), {
        once: true,
      });
      this.entered = true;
    }
    const list =
      reviews.length > 1
        ? el(
            doc,
            'nav',
            { class: 'ed-reviews ed-review__list', 'aria-labelledby': 'ed-review-list-h' },
            el(
              doc,
              'h2',
              { class: 'ed-sec', id: 'ed-review-list-h' },
              T('这份委托的复核', 'Reviews of this ticket'),
            ),
            el(
              doc,
              'ol',
              { class: 'ed-review-list' },
              ...reviews.map((r, i) => {
                const current = r.review_id === review.review_id;
                const open = button(
                  doc,
                  [
                    el(
                      doc,
                      'span',
                      { class: 'ed-review-list__n' },
                      T(`第 ${i + 1} 次`, `Review ${i + 1}`),
                    ),
                    el(
                      doc,
                      'span',
                      { class: 'ed-review-list__s' },
                      r.status === 'incomplete'
                        ? T('复核未完成', 'Review incomplete')
                        : r.status === 'report_mismatch'
                          ? T('复核完成，自报不符', 'Reviewed, self-report differs')
                          : T('复核完成', 'Reviewed'),
                    ),
                    el(doc, 'time', { datetime: r.signed_at }, clock(r.signed_at)),
                    current
                      ? el(doc, 'span', { class: 'ed-review-list__here' }, T('正在看', 'Viewing'))
                      : iconNode(doc, 'chev', 'i-xs'),
                  ],
                  'ed-review-list__open',
                  { id: `ed-rl-${i}`, 'aria-current': current ? 'page' : null, disabled: current },
                );
                open.addEventListener('click', () =>
                  this.ctx.navigate('engineer-review', r.review_id),
                );
                return el(doc, 'li', {}, open);
              }),
            ),
          )
        : null;
    this.element.replaceChildren();
    append(this.element, head, el(doc, 'div', { class: 'ed-review__sheet' }, sheet), list);
  }
}
