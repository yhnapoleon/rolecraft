/** "Hand to engineering" from the product manager's test bench: choose up to ten tests (those
 * citing an out-of-date version first, already chosen), open a ticket from them and put on the
 * engineer's hat. More than ten is stopped here, before anything is sent. */
import { T } from '../../app/i18n';
import { sheetDialog } from '../../sheet-dialog';
import { failureText, type EngineerApi } from './api';
import { el, button } from './dom';
import { handoverChoices, HANDOVER_LIMIT, type HandoverTest, type TicketDetail } from './model';

export interface HandoverContext {
  readonly api: EngineerApi;
  readonly tests: readonly HandoverTest[];
  /** Put on the engineer's hat at this ticket. */
  open(ticketId: string): void;
  /** A product manager's practice: Daniel takes the tests instead (phase 2). */
  readonly colleague?: {
    readonly taskId: string | null;
    done(ticket: TicketDetail): void;
  };
}

export function openHandover(ctx: HandoverContext): HTMLDialogElement {
  const daniel = ctx.colleague;
  const dialog = sheetDialog(
    daniel ? T('交给 Daniel', 'Hand to Daniel') : T('交给工程', 'Hand to engineering'),
    { className: 'ed-handover' },
  );
  const doc = dialog.element.ownerDocument;
  const choices = handoverChoices(ctx.tests);
  const chosen = new Set(choices.filter((c) => c.chosen).map((c) => c.id));
  const count = el(doc, 'p', { class: 'ed-handover__count', 'aria-live': 'polite' });
  const error = el(doc, 'p', { class: 'ed-error', role: 'alert', hidden: true });
  const submit = button(doc, '', 'btn primary', { id: 'ed-handover-submit' });
  const cancel = button(doc, T('取消', 'Cancel'), 'btn quiet');
  cancel.addEventListener('click', () => dialog.element.close());
  const boxes: HTMLInputElement[] = [];
  const list = el(
    doc,
    'ul',
    { class: 'ed-handover__list' },
    ...choices.map((c, i) => {
      const box = el(doc, 'input', {
        type: 'checkbox',
        id: `ed-ho-${i}`,
        value: c.id,
        checked: chosen.has(c.id),
      });
      boxes.push(box);
      box.addEventListener('change', () => {
        if (box.checked) chosen.add(c.id);
        else chosen.delete(c.id);
        sync();
      });
      return el(
        doc,
        'li',
        {},
        el(
          doc,
          'label',
          { class: 'ed-handover__item', for: `ed-ho-${i}` },
          box,
          el(
            doc,
            'span',
            { class: 'ed-handover__text' },
            el(doc, 'span', { class: 'ed-handover__q' }, c.question),
            c.flag ? el(doc, 'span', { class: 'ed-handover__flag' }, c.flag) : null,
            c.answer ? el(doc, 'span', { class: 'ed-handover__a' }, c.answer) : null,
          ),
        ),
      );
    }),
  );
  function sync() {
    const n = chosen.size;
    const full = n >= HANDOVER_LIMIT;
    for (const box of boxes) box.disabled = !box.checked && full;
    count.textContent = full
      ? T(
          `已选满 ${HANDOVER_LIMIT} 条；要换一条，先取消一条。`,
          `${HANDOVER_LIMIT} chosen, the most at once. Clear one to choose another.`,
        )
      : T(`已选 ${n} 条，最多 ${HANDOVER_LIMIT} 条。`, `${n} chosen, up to ${HANDOVER_LIMIT}.`);
    count.dataset.full = String(full);
    submit.disabled = n === 0;
    submit.textContent = daniel
      ? n
        ? T(`交给 Daniel（${n} 条）`, `Hand ${n} ${n === 1 ? 'test' : 'tests'} to Daniel`)
        : T('交给 Daniel', 'Hand to Daniel')
      : n
        ? T(`交给工程（${n} 条）`, `Hand over ${n} ${n === 1 ? 'test' : 'tests'}`)
        : T('交给工程', 'Hand to engineering');
  }
  submit.addEventListener('click', async () => {
    if (!chosen.size || chosen.size > HANDOVER_LIMIT) return;
    submit.disabled = true;
    error.hidden = true;
    const ids = choices.filter((c) => chosen.has(c.id)).map((c) => c.id);
    if (daniel) {
      // One request runs his whole orchestration; until it answers the page says only that he is
      // on it. No step-by-step animation: the steps are shown afterwards from what he did.
      list.hidden = true;
      count.hidden = true;
      cancel.disabled = true;
      waiting.hidden = false;
      try {
        const { ticket } = await ctx.api.createTicket({
          from: 'tests',
          test_ids: ids,
          assignee: 'colleague',
          task_id: daniel.taskId,
        });
        dialog.element.close();
        daniel.done(ticket);
      } catch (failure) {
        waiting.hidden = true;
        list.hidden = false;
        count.hidden = false;
        cancel.disabled = false;
        error.textContent = failureText(failure);
        error.hidden = false;
        sync();
      }
      return;
    }
    try {
      const { ticket } = await ctx.api.createTicket({ from: 'tests', test_ids: ids });
      dialog.element.close();
      ctx.open(ticket.id);
    } catch (failure) {
      error.textContent = failureText(failure);
      error.hidden = false;
      sync();
    }
  });
  const waiting = el(
    doc,
    'p',
    { class: 'ed-handover__waiting', role: 'status', hidden: true },
    el(doc, 'span', { class: 'ed-handover__spin', 'aria-hidden': 'true' }),
    T('Daniel 正在处理（规则编排）', 'Daniel is working on it (rule orchestration)'),
  );
  dialog.body.append(
    el(
      doc,
      'p',
      { class: 'ed-handover__lead' },
      daniel
        ? T(
            '选要修的测试，引用过期版本的已经选上。Daniel（技术负责人，AI 同事）按规则复现、试修并签字复核，报告交回这件事；用不用由你决定。',
            'Choose the tests to fix; those citing an out-of-date version are already chosen. Daniel (technical lead, AI colleague) reproduces, tries fixes and signs a review by rule; the report comes back to this item, and you decide whether to use it.',
          )
        : T(
            '选要修的测试，引用过期版本的已经选上。',
            'Choose the tests to fix; those citing an out-of-date version are already chosen.',
          ),
    ),
    list,
    count,
    waiting,
    error,
  );
  dialog.foot.append(cancel, submit);
  sync();
  dialog.element.showModal();
  // The title takes the first focus, so nothing looks chosen yet; Tab moves on from there.
  dialog.heading.tabIndex = -1;
  dialog.heading.focus();
  return dialog.element;
}
