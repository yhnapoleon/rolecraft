/** S4 · The candidate settings as an instrument (plan §13.6c): a segmented control for one choice,
 * toggles for a set, an 8px instrument field for numbers. Native radios and checkboxes underneath,
 * so arrow keys move within a group and Tab stops once. A changed setting shows, in place,
 * `old (struck) → new`, the key's ink rule at its left, and a way to put that one back. */
import { T } from '../../../app/i18n';
import { agentBadge } from '../bits';
import { choiceText, fieldName, valueText } from '../copy';
import { mountIsland } from '../../../islands/mount';
import { Segmented } from '../../../ui-kit';
import { button, el } from '../dom';

/** Islands mounted in field rows, released when the rows are drawn again. */
const islands = new Map<HTMLElement, { destroy(): void }>();
export function releaseFieldIslands(scope: ParentNode) {
  for (const [host, island] of islands)
    if (scope.contains(host)) {
      island.destroy();
      islands.delete(host);
    }
}
import { parseField, type EditableField, type JsonValue } from '../model';

export interface FieldHooks {
  change(next: JsonValue): void;
  invalid(message: string): void;
  restore(): void;
}

const STEP_NUMBER = 0.05;
/** The segmented control lying down (one line) or standing up (a list of the same items). */
const ROW = 'ed-seg-track tw:max-w-full';
const STACK = 'ed-seg-track is-stacked tw:flex tw:flex-col tw:items-stretch tw:w-full';

export function fieldRow(
  doc: Document,
  field: EditableField,
  value: JsonValue | undefined,
  hooks: FieldHooks,
): HTMLElement {
  const name = field.field;
  const id = `ed-f-${name}`;
  const labelId = `${id}-label`;
  let control: HTMLElement;
  if (field.type === 'choice' || field.type === 'boolean') {
    // One choice: the kit's segmented control (an island; the ink thumb slides between items).
    const choices: readonly (string | boolean)[] =
      field.type === 'boolean' ? [true, false] : (field.choices ?? []);
    control = el(doc, 'div', { class: 'ed-seg-host', id: `${id}-seg` });
    const host = control;
    const props = {
      value: value === undefined || value === null ? '' : String(value),
      label: fieldName(name),
      size: 'md' as const,
      className: ROW,
      items: choices.map((choice) => ({
        value: String(choice),
        label:
          typeof choice === 'boolean' ? valueText(name, choice) : choiceText(name, String(choice)),
      })),
      onChange: (next: string) => hooks.change(field.type === 'boolean' ? next === 'true' : next),
    };
    const island = mountIsland(host, Segmented<string>, props);
    // A segmented control never wraps: when its items don't fit on one line it stands up as a
    // list of the same items (the kit's control, stacked), and lies down again when there is room.
    let natural = 0;
    let stacked = false;
    const fit = () => {
      const track = host.querySelector<HTMLElement>('.ed-seg-track');
      const room = host.clientWidth;
      if (!track || !room) return;
      if (!stacked) natural = track.scrollWidth;
      const stack = natural > room + 1;
      if (stack === stacked) return;
      stacked = stack;
      host.classList.toggle('is-stacked', stack);
      island.update({ ...props, className: stack ? STACK : ROW });
    };
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(fit);
    observer?.observe(host);
    // The island commits a moment after mounting: measure once it has.
    requestAnimationFrame(() => requestAnimationFrame(fit));
    islands.set(control, {
      destroy() {
        observer?.disconnect();
        island.destroy();
      },
    });
  } else if (field.type === 'set') {
    // Several at once: toggles on the same instrument track (native checkboxes).
    const choices: readonly (string | boolean)[] = field.choices ?? [];
    const multiple = true;
    control = el(doc, 'div', {
      class: `ed-seg${multiple ? ' is-multi' : ''}`,
      role: multiple ? 'group' : 'radiogroup',
      'aria-labelledby': labelId,
    });
    for (const choice of choices) {
      const key = String(choice);
      const checked = multiple
        ? Array.isArray(value) && value.map(String).includes(key)
        : value === choice;
      const input = el(doc, 'input', {
        type: multiple ? 'checkbox' : 'radio',
        name: id,
        value: key,
        id: `${id}-${key}`,
        checked,
      });
      input.addEventListener('change', () => {
        if (multiple) {
          const picked = [...control.querySelectorAll<HTMLInputElement>('input:checked')].map(
            (x) => x.value,
          );
          hooks.change((field.choices ?? []).filter((c) => picked.includes(c)));
        } else hooks.change(field.type === 'boolean' ? key === 'true' : key);
      });
      const cost = field.costs?.[key];
      control.append(
        el(
          doc,
          'label',
          { class: 'ed-seg__opt' },
          input,
          el(
            doc,
            'span',
            { class: 'ed-seg__face' },
            typeof choice === 'boolean' ? valueText(name, choice) : choiceText(name, key),
            cost !== undefined ? el(doc, 'small', {}, T(`${cost} 人日`, `${cost} pd`)) : null,
          ),
        ),
      );
    }
  } else if (field.type === 'text_list') {
    const area = el(doc, 'textarea', {
      class: 'ed-input ed-topics',
      id,
      rows: 2,
      'aria-labelledby': labelId,
      'aria-describedby': `${id}-error`,
      placeholder: T('每行一个主题', 'One topic per line'),
    });
    area.value = Array.isArray(value) ? value.join('\n') : '';
    area.addEventListener('input', () => {
      const parsed = parseField(field, area.value);
      if ('value' in parsed) hooks.change(parsed.value);
      else hooks.invalid(parsed.error);
    });
    control = area;
  } else {
    const input = el(doc, 'input', {
      class: 'ed-input ed-num',
      id,
      type: 'text',
      inputmode: field.type === 'integer' ? 'numeric' : 'decimal',
      'aria-labelledby': labelId,
      'aria-describedby': `${id}-error`,
      autocomplete: 'off',
      spellcheck: 'false',
    });
    input.value = value === null || value === undefined ? '' : String(value);
    const read = () => {
      const parsed = parseField(field, input.value);
      if ('value' in parsed) hooks.change(parsed.value);
      else hooks.invalid(parsed.error);
    };
    input.addEventListener('input', read);
    // Up and down nudge the value: ±0.05 for a score, ±1 for a whole number.
    input.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
      const n = Number(input.value);
      if (!Number.isFinite(n)) return;
      e.preventDefault();
      const step = field.type === 'integer' ? 1 : STEP_NUMBER;
      let next = n + (e.key === 'ArrowUp' ? step : -step);
      if (field.minimum !== undefined) next = Math.max(field.minimum, next);
      if (field.maximum !== undefined) next = Math.min(field.maximum, next);
      input.value = String(Math.round(next * 100) / 100);
      read();
    });
    control = input;
  }
  const restore = button(
    doc,
    T('恢复这一项', 'Put this back'),
    'ed-k is-ghost is-small ed-field__restore',
    {
      id: `${id}-restore`,
      'aria-label': T(
        `把「${fieldName(name)}」恢复为基线`,
        `Put “${fieldName(name)}” back to the baseline`,
      ),
    },
  );
  restore.addEventListener('click', () => hooks.restore());
  return el(
    doc,
    'div',
    { class: 'ed-field', 'data-field': name },
    el(
      doc,
      'div',
      { class: 'ed-field__label', id: labelId },
      el(doc, 'span', { class: 'ed-field__name' }, fieldName(name)),
      el(doc, 'code', { class: 'ed-key', lang: 'en' }, name),
    ),
    el(doc, 'p', { class: 'ed-field__diff', hidden: true }),
    control,
    el(doc, 'p', { class: 'ed-field__error', id: `${id}-error`, role: 'alert', hidden: true }),
    el(doc, 'div', { class: 'ed-field__tools', hidden: true }, restore),
  );
}

/** Show or clear a row's change mark: `baseline (struck) → candidate`, with the Agent's mark when
 * its trial or draft brought the value in. */
export function markField(
  row: HTMLElement,
  change: { before: JsonValue; after: JsonValue } | null,
  agentTitle: string | null,
  error: string,
) {
  const doc = row.ownerDocument;
  const name = row.dataset.field as string;
  row.classList.toggle('is-changed', !!change);
  const diff = row.querySelector<HTMLElement>('.ed-field__diff') as HTMLElement;
  const tools = row.querySelector<HTMLElement>('.ed-field__tools') as HTMLElement;
  diff.hidden = !change;
  tools.hidden = !change;
  const shown = change ? JSON.stringify([change, agentTitle]) : '';
  if (diff.dataset.shown !== shown) {
    diff.dataset.shown = shown;
    diff.replaceChildren();
    if (change)
      diff.append(
        el(doc, 'del', { class: 'ed-diff__was' }, valueText(name, change.before)),
        agentTitle ? agentBadge(doc, agentTitle) : '',
        el(doc, 'span', { class: 'ed-diff__arrow', 'aria-hidden': 'true' }, '→'),
        el(doc, 'span', { class: 'sr-only' }, T('改为', 'to')),
        el(doc, 'b', { class: 'ed-diff__now' }, valueText(name, change.after)),
      );
  }
  const problem = row.querySelector<HTMLElement>('.ed-field__error') as HTMLElement;
  problem.hidden = !error;
  if (problem.textContent !== error) problem.textContent = error;
  row.classList.toggle('has-error', !!error);
}
