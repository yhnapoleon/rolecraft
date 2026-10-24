/** S6 · Drafting by hand (191's manual mode, kept): the explanation, each change with its reason,
 * an optional self-report (all public checks or none, fillable from the latest trial), unresolved
 * items. The draft's settings are the candidate's. */
import { T } from '../../../app/i18n';
import { key } from '../bits';
import { choiceText, fieldName, valueText } from '../copy';
import { button, el, iconNode } from '../dom';
import {
  claimsFromTrial,
  draftTextLength,
  DRAFT_TEXT_LIMIT,
  UNRESOLVED_LIMIT,
  type DraftInput,
  type Experiment,
  type JsonValue,
  type Outcome,
  type Settings,
  type TicketDetail,
} from '../model';

export type StatementRow = { field: string; before: JsonValue; after: JsonValue; reason: string };
export interface DraftForm {
  explanation: string;
  statements: StatementRow[];
  claimsOn: boolean;
  claims: Record<string, Outcome | ''>;
  unresolved: { description: string; probes: string[] }[];
}

export function newDraftForm(ticket: TicketDetail, changes: Settings): DraftForm {
  return {
    explanation: '',
    statements: Object.entries(changes).map(([field, after]) => ({
      field,
      before: ticket.baseline_config[field],
      after,
      reason: '',
    })),
    claimsOn: false,
    claims: Object.fromEntries(ticket.public_probes.map((p) => [p.id, ''])),
    unresolved: [],
  };
}

export function draftInput(form: DraftForm, changes: Settings): DraftInput {
  return {
    changes,
    explanation: form.explanation.trim(),
    change_statements: form.statements.map((s) => ({ ...s, reason: s.reason.trim() })),
    claimed_results: form.claimsOn
      ? (Object.fromEntries(Object.entries(form.claims).filter(([, v]) => v)) as Record<
          string,
          Outcome
        >)
      : {},
    unresolved: form.unresolved.map((u) => ({
      description: u.description.trim(),
      probe_ids: u.probes,
    })),
  };
}

export interface ComposeContext {
  readonly doc: Document;
  readonly ticket: TicketDetail;
  readonly form: DraftForm;
  readonly changes: Settings;
  readonly latestTrial: Experiment | undefined;
  readonly busy: boolean;
  readonly errors: readonly string[];
  redraw(focusId?: string): void;
  cancel(): void;
  save(): void;
}

export function composeForm(ctx: ComposeContext): HTMLElement {
  const { doc, ticket: t, form } = ctx;
  const fields = new Map(t.editable_fields.map((f) => [f.field, f]));
  const counter = el(doc, 'span', { class: 'ed-compose__count', 'aria-live': 'polite' });
  const recount = () => {
    const n = draftTextLength(draftInput(form, ctx.changes));
    counter.textContent = T(
      `已写 ${n}/${DRAFT_TEXT_LIMIT} 字`,
      `${n}/${DRAFT_TEXT_LIMIT} characters`,
    );
    counter.dataset.over = String(n > DRAFT_TEXT_LIMIT);
  };
  const changes = Object.keys(ctx.changes);
  const explanation = el(doc, 'textarea', {
    class: 'ed-input',
    id: 'ed-draft-explanation',
    rows: 3,
  });
  explanation.value = form.explanation;
  explanation.addEventListener('input', () => {
    form.explanation = explanation.value;
    recount();
  });
  const statementRow = (s: StatementRow, i: number) => {
    const field = fields.get(s.field);
    const valueControl = (which: 'before' | 'after') => {
      const id = `ed-st-${i}-${which}`;
      const label = which === 'before' ? T('改前', 'Before') : T('改后', 'After');
      const set = (v: JsonValue) => {
        s[which] = v;
        recount();
      };
      if (field && (field.type === 'choice' || field.type === 'boolean')) {
        const select = el(doc, 'select', {
          class: 'ed-input ed-st__value',
          id,
          'aria-label': `${fieldName(s.field)} · ${label}`,
        });
        const options: (string | boolean)[] =
          field.type === 'boolean' ? [true, false] : [...(field.choices ?? [])];
        for (const o of options)
          select.append(
            el(
              doc,
              'option',
              { value: String(o), selected: s[which] === o },
              typeof o === 'boolean' ? valueText(s.field, o) : choiceText(s.field, o),
            ),
          );
        select.addEventListener('change', () =>
          set(field.type === 'boolean' ? select.value === 'true' : select.value),
        );
        return select;
      }
      if (field && (field.type === 'integer' || field.type === 'number')) {
        const input = el(doc, 'input', {
          class: 'ed-input ed-st__value',
          id,
          inputmode: 'decimal',
          'aria-label': `${fieldName(s.field)} · ${label}`,
          autocomplete: 'off',
        });
        input.value = s[which] === null || s[which] === undefined ? '' : String(s[which]);
        input.addEventListener('input', () => {
          const n = Number(input.value.trim());
          set(input.value.trim() !== '' && Number.isFinite(n) ? n : input.value);
        });
        return input;
      }
      return el(doc, 'span', { class: 'ed-st__fixed', id }, valueText(s.field, s[which]));
    };
    const reason = el(doc, 'input', {
      class: 'ed-input',
      id: `ed-st-${i}-reason`,
      maxlength: 500,
      placeholder: T('为什么这样改', 'Why this change'),
      'aria-label': `${fieldName(s.field)} · ${T('理由', 'Reason')}`,
      autocomplete: 'off',
    });
    reason.value = s.reason;
    reason.addEventListener('input', () => {
      s.reason = reason.value;
      recount();
    });
    const remove = button(
      doc,
      [
        iconNode(doc, 'x', 'i-xs'),
        el(
          doc,
          'span',
          { class: 'sr-only' },
          T(`不写「${fieldName(s.field)}」这一条`, `Leave out “${fieldName(s.field)}”`),
        ),
      ],
      'ed-k is-ghost is-icon',
      { id: `ed-st-${i}-remove` },
    );
    remove.addEventListener('click', () => {
      form.statements.splice(i, 1);
      ctx.redraw(
        form.statements.length
          ? `ed-st-${Math.min(i, form.statements.length - 1)}-reason`
          : 'ed-draft-explanation',
      );
    });
    return el(
      doc,
      'li',
      { class: 'ed-st' },
      el(doc, 'span', { class: 'ed-st__name' }, fieldName(s.field)),
      el(
        doc,
        'span',
        { class: 'ed-st__values' },
        valueControl('before'),
        el(doc, 'span', { class: 'ed-diff__arrow', 'aria-hidden': 'true' }, '→'),
        valueControl('after'),
      ),
      reason,
      remove,
    );
  };
  const claimsOn = el(doc, 'input', {
    type: 'checkbox',
    id: 'ed-claims-on',
    checked: form.claimsOn,
  });
  const fill = key(doc, T('用最近一次试跑结果填', 'Fill from the latest trial'), 'ghost', {
    id: 'ed-claims-fill',
    disabled: !ctx.latestTrial,
  });
  fill.addEventListener('click', () => {
    const claims = ctx.latestTrial
      ? claimsFromTrial(
          ctx.latestTrial,
          t.public_probes.map((p) => p.id),
        )
      : null;
    if (!claims) return;
    form.claimsOn = true;
    form.claims = claims;
    ctx.redraw('ed-claims-fill');
  });
  claimsOn.addEventListener('change', () => {
    form.claimsOn = claimsOn.checked;
    ctx.redraw('ed-claims-on');
  });
  const outcomeText = {
    pass: T('通过', 'Passed'),
    fail: T('未通过', 'Did not pass'),
    error: T('执行出错', 'Run failed'),
  };
  const claimRows = form.claimsOn
    ? el(
        doc,
        'ul',
        { class: 'ed-claim-picks' },
        ...t.public_probes.map((p) => {
          const select = el(
            doc,
            'select',
            {
              class: 'ed-input',
              id: `ed-claim-${p.id}`,
              'aria-label': `${p.id} · ${T('自报结果', 'Self-reported result')}`,
            },
            el(doc, 'option', { value: '', selected: !form.claims[p.id] }, T('未填', 'Not set')),
            ...(['pass', 'fail', 'error'] as const).map((o) =>
              el(doc, 'option', { value: o, selected: form.claims[p.id] === o }, outcomeText[o]),
            ),
          );
          select.addEventListener('change', () => {
            form.claims[p.id] = select.value as Outcome | '';
          });
          return el(
            doc,
            'li',
            {},
            el(doc, 'label', { class: 'ed-key', for: `ed-claim-${p.id}` }, p.id),
            select,
          );
        }),
      )
    : null;
  const unresolvedRows = form.unresolved.map((u, i) => {
    const text = el(doc, 'input', {
      class: 'ed-input',
      id: `ed-un-${i}`,
      maxlength: 1000,
      placeholder: T('还没修好的问题', 'What is still not fixed'),
      'aria-label': T(`未修复项 ${i + 1}`, `Unresolved item ${i + 1}`),
      autocomplete: 'off',
    });
    text.value = u.description;
    text.addEventListener('input', () => {
      u.description = text.value;
      recount();
    });
    const probes = el(
      doc,
      'div',
      {
        class: 'ed-seg is-multi ed-un__probes',
        role: 'group',
        'aria-label': T('涉及的公开检查', 'Public checks involved'),
      },
      ...t.public_probes.map((p) => {
        const box = el(doc, 'input', {
          type: 'checkbox',
          id: `ed-un-${i}-${p.id}`,
          value: p.id,
          checked: u.probes.includes(p.id),
        });
        box.addEventListener('change', () => {
          u.probes = t.public_probes
            .map((x) => x.id)
            .filter((id) => (id === p.id ? box.checked : u.probes.includes(id)));
        });
        return el(
          doc,
          'label',
          { class: 'ed-seg__opt' },
          box,
          el(doc, 'span', { class: 'ed-seg__face', lang: 'en' }, p.id),
        );
      }),
    );
    const remove = button(
      doc,
      [
        iconNode(doc, 'x', 'i-xs'),
        el(doc, 'span', { class: 'sr-only' }, T('删去这一条', 'Remove this item')),
      ],
      'ed-k is-ghost is-icon',
      { id: `ed-un-${i}-remove` },
    );
    remove.addEventListener('click', () => {
      form.unresolved.splice(i, 1);
      ctx.redraw('ed-un-add');
    });
    return el(doc, 'li', { class: 'ed-un' }, text, probes, remove);
  });
  const add = key(
    doc,
    T('添加一条未修复项', 'Add an unresolved item'),
    'ghost',
    {
      id: 'ed-un-add',
      disabled: form.unresolved.length >= UNRESOLVED_LIMIT,
    },
    'plus',
  );
  add.addEventListener('click', () => {
    form.unresolved.push({ description: '', probes: [] });
    ctx.redraw(`ed-un-${form.unresolved.length - 1}`);
  });
  const cancel = key(doc, T('取消', 'Cancel'), 'ghost', { id: 'ed-draft-cancel' });
  cancel.addEventListener('click', () => ctx.cancel());
  const save = key(
    doc,
    T('保存草稿', 'Save the draft'),
    'secondary',
    { id: 'ed-draft-save' },
    'save',
  );
  if (ctx.busy) {
    save.disabled = true;
    save.setAttribute('aria-busy', 'true');
    save.classList.add('is-busy');
  }
  save.addEventListener('click', () => ctx.save());
  const view = el(
    doc,
    'div',
    { class: 'ed-compose' },
    el(
      doc,
      'p',
      { class: 'ed-compose__from' },
      changes.length
        ? T('草稿的设置取自你的候选：', 'The draft takes its settings from your candidate: ') +
            changes.map((f) => fieldName(f)).join(T('、', ', '))
        : T(
            '候选和基线相同，草稿不会改任何设置。',
            'The candidate matches the baseline, so the draft changes nothing.',
          ),
    ),
    el(doc, 'label', { class: 'ed-label', for: 'ed-draft-explanation' }, T('说明', 'Explanation')),
    explanation,
    el(
      doc,
      'div',
      { class: 'ed-compose__block' },
      el(doc, 'h4', { class: 'ed-label' }, T('逐条变更', 'Changes, one by one')),
      form.statements.length
        ? el(doc, 'ol', { class: 'ed-st-list' }, ...form.statements.map(statementRow))
        : el(doc, 'p', { class: 'ed-meta' }, T('没有要写的变更。', 'No changes to state.')),
    ),
    el(
      doc,
      'div',
      { class: 'ed-compose__block' },
      el(
        doc,
        'div',
        { class: 'ed-compose__row' },
        el(
          doc,
          'label',
          { class: 'ed-check', for: 'ed-claims-on' },
          claimsOn,
          el(doc, 'span', {}, T('附上自报结果', 'Attach a self-report')),
        ),
        fill,
      ),
      claimRows,
    ),
    el(
      doc,
      'div',
      { class: 'ed-compose__block' },
      el(doc, 'h4', { class: 'ed-label' }, T('未修复项', 'Unresolved')),
      unresolvedRows.length ? el(doc, 'ol', { class: 'ed-un-list' }, ...unresolvedRows) : null,
      add,
    ),
    ctx.errors.length
      ? el(
          doc,
          'ul',
          { class: 'ed-error ed-compose__errors', role: 'alert' },
          ...ctx.errors.map((e) => el(doc, 'li', {}, e)),
        )
      : null,
    el(doc, 'div', { class: 'ed-compose__keys' }, counter, cancel, save),
  );
  recount();
  return view;
}
