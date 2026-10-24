/** "Hand to engineering" from the product manager's test bench: choose up to ten tests (those
 * citing an out-of-date version first, already chosen), open a ticket from them and put on the
 * engineer's hat. More than ten is stopped here, before anything is sent. */
import { T } from '../../app/i18n';
import { sheetDialog } from '../../sheet-dialog';
import { failureText, type EngineerApi } from './api';
import { el, button } from './dom';
import { handoverChoices, HANDOVER_LIMIT, type HandoverTest } from './model';

export interface HandoverContext {
  readonly api: EngineerApi;
  readonly tests: readonly HandoverTest[];
  /** Put on the engineer's hat at this ticket. */
  open(ticketId: string): void;
}

export function openHandover(ctx: HandoverContext): HTMLDialogElement {
  const dialog = sheetDialog(T('交给工程', 'Hand to engineering'), { className: 'ed-handover' });
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
    submit.textContent = n
      ? T(`交给工程（${n} 条）`, `Hand over ${n} ${n === 1 ? 'test' : 'tests'}`)
      : T('交给工程', 'Hand to engineering');
  }
  submit.addEventListener('click', async () => {
    if (!chosen.size || chosen.size > HANDOVER_LIMIT) return;
    submit.disabled = true;
    error.hidden = true;
    try {
      const ids = choices.filter((c) => chosen.has(c.id)).map((c) => c.id);
      const { ticket } = await ctx.api.createTicket({ from: 'tests', test_ids: ids });
      dialog.element.close();
      ctx.open(ticket.id);
    } catch (failure) {
      error.textContent = failureText(failure);
      error.hidden = false;
      sync();
    }
  });
  dialog.body.append(
    el(
      doc,
      'p',
      { class: 'ed-handover__lead' },
      T(
        '选要修的测试，引用过期版本的已经选上。',
        'Choose the tests to fix; those citing an out-of-date version are already chosen.',
      ),
    ),
    list,
    count,
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
