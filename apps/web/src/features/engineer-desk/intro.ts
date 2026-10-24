/** S1 · "Same practice, second hat" (plan §13.3): shown the first time a practice puts on the
 * engineer's hat. One sheet of paper: who you are now, what came over from the product side, the
 * three steps, and the one rule about signing. "Take the ticket" flies the problem into Daniel's
 * ticket on the desk (shared element `ticket-target`). */
import { T } from '../../app/i18n';
import { failureText, type EngineerApi } from './api';
import { chip, key, setBusy } from './bits';
import { el, iconNode, workLang } from './dom';
import { setHat, setLastTicket } from '../../shell';
import { engineerLocal, updateEngineerLocal, type HatOrigin } from './local-state';
import type { TicketDetail } from './model';
import { arrive, drawLine, move, spring } from './motion';
import { fixNeed, type PracticeFacts } from './need';
import { targetSlip } from './slip';

export interface IntroContext {
  readonly doc: Document;
  readonly sessionId: string;
  readonly api: EngineerApi;
  /** A ticket already read (the same one the desk will show). */
  readonly ticket: TicketDetail | null;
  take(ticket: TicketDetail): void;
  backToProduct(): void;
  home(): void;
  keep(ticket: TicketDetail): void;
  /** The practice's facts now (policy, index, warning setting): is there anything to fix? */
  facts(): PracticeFacts;
  /** Nothing to fix here (189): the "nothing to fix" screen in this one's place. */
  nothing(): void;
}

export class IntroScreen {
  readonly element: HTMLElement;
  private readonly origin: HatOrigin;
  private busy = false;
  /** The situation's ticket opened before the delivery, once read (revise only). */
  private earlier: TicketDetail | null = null;

  /** `revise`: the practice is delivered; taking the ticket first opens a revision (the delivery
   * and its feedback stay), because opening the ticket puts the pilot live again. */
  constructor(
    private readonly ctx: IntroContext,
    private readonly ticketId: string | null,
    private readonly revise = false,
  ) {
    this.origin = engineerLocal(ctx.sessionId).origin ?? 'same';
    this.element = el(ctx.doc, 'div', { class: 'ed ed-intro' });
    this.draw(ctx.ticket, '');
    this.enter();
    if (!ctx.ticket && !revise) void this.load();
    if (!ctx.ticket && revise) void this.loadExisting();
  }

  /** Delivered practice: a ticket opened before the delivery is read (reading opens nothing). */
  private async loadExisting() {
    try {
      const seeded = (await this.ctx.api.tickets()).find((t) => t.source === 'seeded');
      if (!seeded || this.busy) return;
      const ticket = await this.ctx.api.ticket(seeded.id);
      this.ctx.keep(ticket);
      this.earlier = ticket;
      if (!this.busy) this.draw(ticket, '');
    } catch {
      /* The situation's own words stay on the slip. */
    }
  }

  /** Delivered practice: revision → ticket → the engineer's hat → the desk. */
  private async reviseAndTake() {
    if (this.busy) return;
    // Judged before the revision opens (189): no revision for a practice with nothing to fix.
    if (fixNeed(this.ctx.facts(), (this.earlier ?? this.ctx.ticket)?.target_tests[0]) === 'clear') {
      this.ctx.nothing();
      return;
    }
    this.busy = true;
    this.draw(null, '');
    try {
      const api = this.ctx.api;
      if ((await api.status()) === 'submitted') {
        const parent = await api.latestSubmission();
        if (!parent) throw new Error('no submission');
        await api.beginRevision(parent, T('接手工程委托', 'Taking the engineering ticket'));
      }
      const { ticket } = await api.createTicket({ from: 'seeded' });
      this.ctx.keep(ticket);
      setHat(this.ctx.sessionId, 'engineer');
      updateEngineerLocal(this.ctx.sessionId, { introSeen: true });
      setLastTicket(this.ctx.sessionId, ticket.id);
      this.busy = false;
      this.ctx.take(ticket);
    } catch (error) {
      this.busy = false;
      this.draw(null, failureText(error));
      (this.ctx.doc.getElementById('ed-intro-take') as HTMLElement | null)?.focus();
    }
  }

  destroy() {}

  private async load() {
    try {
      const ticket = await this.ctx.api.ticket(this.ticketId as string);
      this.ctx.keep(ticket);
      this.draw(ticket, '');
    } catch (error) {
      this.draw(null, failureText(error));
    }
  }

  private draw(ticket: TicketDetail | null, error: string) {
    const doc = this.ctx.doc;
    const lead = this.revise
      ? T(
          '这一局已经交付。要接手工程委托，先开一轮修订：你的交付记录和反馈都会保留，修好以后可以带着复核报告重新交付。',
          'This practice is delivered. To take the engineering ticket, open a revision first: your delivery and feedback stay. Once it’s fixed you can deliver again with the review report.',
        )
      : {
          handover: T(
            '刚才你是产品经理，测出知识助手答错了。现在换你来修：只改支持的设置，改好由你签字，再交回产品经理。两边的进度都在，顶栏随时切回去。',
            'A moment ago you were the product manager and caught the assistant answering wrong. Now you fix it: change only supported settings, sign it yourself, then hand it back to product. Both sides keep their progress; switch back any time in the top bar.',
          ),
          new: T(
            '这一局里，产品经理正在决定知识助手能不能试点，测试时发现了一个问题，交给你来修。你也可以随时在顶栏切到产品经理那边看看。',
            'In this practice, the product manager is deciding whether the knowledge assistant is ready for a pilot. Testing turned up a problem, and it’s yours to fix. You can switch to the product manager’s side in the top bar any time.',
          ),
          same: T(
            '产品经理那边的进度都在。现在换你来修：只改支持的设置，改好由你签字，再交回产品经理。顶栏随时切回去。',
            'Your product-manager progress is all still there. Now you fix it: change only supported settings, sign it yourself, then hand it back to product. Switch back any time in the top bar.',
          ),
        }[this.origin];
    // One structure for every way in (G12): question · the assistant's recorded answer · what is
    // wrong with it · the amber tag when the index lags. Skeleton while the ticket is read.
    const pending = !ticket && !this.revise;
    const slip = pending ? null : targetSlip(ticket);
    const lang = workLang(ticket?.work_language ?? (T('zh', 'en') as 'zh' | 'en'));
    const target = el(
      doc,
      'figure',
      { class: 'ed-intro__target', 'data-vt': 'ticket-target' },
      el(doc, 'figcaption', { class: 'ed-mini' }, T('要修的', 'To fix')),
      slip
        ? [
            el(doc, 'p', { class: 'ed-intro__q', lang }, slip.query),
            // The sentence with the number the person checks (500), never cut through.
            slip.quote
              ? el(
                  doc,
                  'blockquote',
                  {
                    class: 'ed-intro__quote',
                    lang,
                    title: ticket?.target_tests[0]?.answer_summary ?? '',
                  },
                  slip.quote,
                )
              : null,
            el(
              doc,
              'p',
              { class: 'ed-intro__why' },
              slip.wrong,
              slip.more
                ? el(
                    doc,
                    'span',
                    { class: 'ed-meta' },
                    T(` · 委托里还有 ${slip.more} 条`, ` · ${slip.more} more in the ticket`),
                  )
                : null,
            ),
            slip.stale ? chip(doc, [iconNode(doc, 'stale', 'i-xs'), slip.stale], 'warn') : null,
          ]
        : error
          ? el(doc, 'p', { class: 'ed-error', role: 'alert' }, error)
          : [
              el(doc, 'span', { class: 'ed-skel ed-skel--q' }),
              el(doc, 'span', { class: 'ed-skel' }),
              el(doc, 'span', { class: 'ed-skel ed-skel--short' }),
            ],
    );
    const steps = el(
      doc,
      'ol',
      { class: 'ed-intro__steps' },
      ...[
        [T('复现', 'Reproduce'), T('确认问题还在', 'Make sure it’s still broken')],
        [T('修复与试跑', 'Fix & trial'), T('只改根因', 'Change only the root cause')],
        [T('签字', 'Sign off'), T('你为改动负责', 'You vouch for the change')],
      ].map(([name, what], i) =>
        el(
          doc,
          'li',
          {},
          el(doc, 'span', { class: 'ed-intro__n' }, `0${i + 1}`),
          el(doc, 'b', {}, name),
          el(doc, 'span', {}, what),
        ),
      ),
    );
    const rule = el(
      doc,
      'div',
      { class: 'ed-intro__sign' },
      el(
        doc,
        'p',
        { class: 'ed-intro__rule' },
        el(doc, 'span', { class: 'ed-intro__line' }),
        el(doc, 'span', { class: 'ed-mini' }, T('只能由你签', 'Only you sign')),
      ),
      el(
        doc,
        'p',
        { class: 'ed-intro__note' },
        T(
          '签字表示你看过实际改了什么，并为它负责。你的 Agent 可以帮你做，不能替你签。',
          'Signing means you’ve seen what actually changed and you vouch for it. Your agent can help with the work; it can’t sign for you.',
        ),
      ),
    );
    const take = key(
      doc,
      this.revise
        ? error
          ? T('重试', 'Try again')
          : T('开始修订并接手', 'Open a revision and take the ticket')
        : error
          ? T('回首页', 'Back home')
          : T('接下这份委托', 'Take the ticket'),
      'primary',
      { id: 'ed-intro-take', disabled: this.revise ? this.busy : !ticket && !error },
    );
    if (this.revise && this.busy) setBusy(take, true);
    take.addEventListener('click', () => {
      if (this.revise) {
        void this.reviseAndTake();
        return;
      }
      if (error) {
        this.ctx.home();
        return;
      }
      if (!ticket) return;
      updateEngineerLocal(this.ctx.sessionId, { introSeen: true });
      this.ctx.take(ticket);
    });
    const back = this.revise
      ? key(doc, T('留在产品经理', 'Stay as product manager'), 'ghost', { id: 'ed-intro-back' })
      : this.origin !== 'new'
        ? key(doc, T('先回产品经理', 'Back to product for now'), 'ghost', { id: 'ed-intro-back' })
        : null;
    back?.addEventListener('click', () => this.ctx.backToProduct());
    const paper = el(
      doc,
      'article',
      { class: 'ed-intro__paper', 'aria-labelledby': 'ed-title' },
      el(
        doc,
        'p',
        { class: 'ed-eyebrow' },
        T('同一局练习，换一顶帽子', 'Same practice, second hat'),
      ),
      el(
        doc,
        'h1',
        { class: 'ed-intro__title', id: 'ed-title', tabindex: '-1' },
        T('你现在是工程师', 'You’re the engineer now'),
      ),
      el(doc, 'p', { class: 'ed-intro__lead' }, lead),
      target,
      this.revise && error ? el(doc, 'p', { class: 'ed-error', role: 'alert' }, error) : null,
      steps,
      rule,
      el(
        doc,
        'footer',
        { class: 'ed-intro__keys' },
        back ?? el(doc, 'span', {}),
        el(
          doc,
          'div',
          { class: 'ed-intro__go' },
          (!ticket && !error && !this.revise) || this.busy
            ? el(doc, 'span', { class: 'ed-meta' }, T('正在准备委托…', 'Preparing the ticket…'))
            : null,
          take,
        ),
      ),
    );
    const focused = this.element.contains(doc.activeElement) ? doc.activeElement?.id : null;
    this.element.replaceChildren(paper);
    if (focused) doc.getElementById(focused)?.focus();
  }

  /** Once a practice: the paper rises, the three parts follow 60ms apart, the line draws. */
  private enter() {
    const paper = this.element.querySelector('.ed-intro__paper');
    move(
      paper,
      { opacity: [0, 1], transform: ['translateY(12px)', 'translateY(0)'] },
      { duration: 0.52, ease: spring },
    );
    const parts = ['.ed-intro__target', '.ed-intro__steps', '.ed-intro__sign'];
    parts.forEach((sel, i) => {
      arrive(this.element.querySelector(sel), 6, { delay: 0.12 + i * 0.06 });
    });
    drawLine(this.element.querySelector('.ed-intro__line'), 360, 0.3);
  }
}
