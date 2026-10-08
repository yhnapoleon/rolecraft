/** Optional, non-terminal review in the existing feedback surface. */
import type { FeedbackNativeAdapter, ReviewDraft } from './index';
import type { ObjectRef } from '../workspace/contract-types';
import type { FeedbackLanguage } from './localization';

export function mountReviewControls(
  doc: Document,
  adapter: FeedbackNativeAdapter,
  language: FeedbackLanguage,
) {
  const t = (zh: string, en: string) => (language === 'en' ? en : zh);
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', cls = '') => {
    const n = doc.createElement(tag);
    n.textContent = text;
    n.className = cls;
    return n;
  };
  const key = (r: ObjectRef) =>
    [r.session_id, r.kind, r.object_id, r.version, r.config_version ?? ''].join(':');
  const empty: ReviewDraft = {
    subjects: [],
    purpose: '',
    question: '',
    decision: null,
    scope: [],
    followup_of: [],
  };
  let draft: ReviewDraft = empty;
  try {
    const saved = JSON.parse(adapter.readDraft('review-request')?.text ?? 'null');
    if (
      saved &&
      Array.isArray(saved.subjects) &&
      typeof saved.question === 'string' &&
      typeof saved.purpose === 'string' &&
      Array.isArray(saved.followup_of)
    )
      draft = { ...empty, ...saved };
  } catch {
    /* A damaged local draft must not create a request. */
  }
  let alive = true,
    saving: Promise<void> = Promise.resolve(),
    saveError = false;
  const element = el('section');
  element.setAttribute('aria-label', t('作品评审', 'Artifact review'));
  const form = el('details');
  form.append(el('summary', t('工作中先评审作品', 'Review artifacts while working')));
  form.append(
    el(
      'p',
      t(
        '选择已保存的确切版本，可以写明用途和想核对的问题。评审后仍能继续工作。',
        'Choose exact saved versions and optionally describe their purpose and your question. You can continue working after the review.',
      ),
      'muted',
    ),
  );
  const products = el('div');
  products.setAttribute('aria-label', t('评审的作品版本', 'Artifact versions to review'));
  const purpose = el('input', '', 'input');
  purpose.value = draft.purpose;
  purpose.placeholder = t(
    '例如：探索笔记、测试计划，也可以留空',
    'For example: exploration notes or a test plan; optional',
  );
  const question = el('textarea', '', 'textarea');
  question.rows = 3;
  question.value = draft.question;
  const decision = el('select', '', 'select');
  for (const [value, label] of [
    ['', t('未确定或与本次评审无关', 'Undecided or unrelated to this review')],
    ['launch', t('按方案推进', 'Proceed')],
    ['launch_narrow', t('缩小范围推进', 'Proceed with limited scope')],
    ['defer_with_conditions', t('满足条件后再推进', 'Defer until conditions are met')],
    ['no_go', t('停止这项方案', 'Do not proceed')],
  ]) {
    const o = el('option', label);
    o.value = value;
    decision.append(o);
  }
  decision.value = draft.decision ?? '';
  const field = (text: string, input: HTMLElement) => {
    const l = el('label', text, 'field');
    l.append(input);
    return l;
  };
  purpose.setAttribute('aria-label', t('作品用途（可留空）', 'Artifact purpose (optional)'));
  question.setAttribute('aria-label', t('想核对的问题（可留空）', 'Review question (optional)'));
  decision.setAttribute('aria-label', t('评审涉及的决定（可留空）', 'Review decision (optional)'));
  const followups = el('div');
  followups.setAttribute(
    'aria-label',
    t('关联已记录的异议或补证', 'Link recorded challenges or additional evidence'),
  );
  const status = el('p', '', 'muted');
  status.setAttribute('role', 'status');
  const error = el('p', '', 'inline-alert');
  error.setAttribute('role', 'alert');
  error.hidden = true;
  function save() {
    const copy = JSON.stringify(draft);
    saving = saving
      .then(() => adapter.keepDraft('review-request', { text: copy, evidence: [] }))
      .then(
        () => {
          saveError = false;
        },
        () => {
          saveError = true;
          if (alive) {
            error.textContent = t(
              '评审草稿尚未保存，请先保留文字。',
              'The review draft is not saved. Keep a copy of your text.',
            );
            error.hidden = false;
          }
        },
      );
    return saving;
  }
  purpose.addEventListener('input', () => {
    draft.purpose = purpose.value;
    void save();
  });
  question.addEventListener('input', () => {
    draft.question = question.value;
    void save();
  });
  decision.addEventListener('change', () => {
    draft.decision = decision.value || null;
    void save();
  });
  const submit = el('button', t('评审选中的版本', 'Review selected versions'), 'btn');
  submit.type = 'button';
  submit.addEventListener('click', () => {
    void (async () => {
      error.hidden = true;
      try {
        if (!draft.subjects.length)
          throw Error(t('请选择已保存的作品版本。', 'Select saved artifact versions.'));
        await saving;
        if (saveError)
          throw Error(
            t(
              '评审草稿尚未保存，请先保留文字。',
              'The review draft is not saved. Keep a copy of your text.',
            ),
          );
        await adapter.review!({
          ...structuredClone(draft),
          purpose: draft.purpose.trim() || 'undetermined',
        });
        if (alive) {
          status.textContent = t(
            '评审请求已记录。反馈就绪后会显示在下方，可以继续工作。',
            'Review recorded. Feedback will appear below when ready; you can continue working.',
          );
          form.open = false;
        }
      } catch (e) {
        if (alive) {
          error.textContent =
            e instanceof Error ? e.message : t('评审尚未确认。', 'The review is not confirmed.');
          error.hidden = false;
        }
      } finally {
        if (alive) render();
      }
    })();
  });
  form.append(
    products,
    field(t('作品用途（可留空）', 'Artifact purpose (optional)'), purpose),
    field(t('想核对的问题（可留空）', 'Review question (optional)'), question),
    field(t('评审涉及的决定（可留空）', 'Review decision (optional)'), decision),
    followups,
    submit,
  );
  const history = el('details');
  history.append(el('summary', t('查看评审与提交历史', 'Review and submission history')));
  const rows = el('div');
  history.append(rows);
  element.append(form, status, error, history);
  function render() {
    const s = adapter.snapshot(),
      disabled = s.busy || !!s.pending || s.status === 'submitted' || adapter.canReview === false;
    submit.disabled = disabled;
    purpose.disabled = question.disabled = decision.disabled = disabled;
    products.replaceChildren(
      ...s.products
        .filter((p) => !p.removed_at)
        .map((p) => {
          const ref: ObjectRef = {
            session_id: p.session_id,
            kind: 'product',
            object_id: p.product_id,
            version: p.version,
          };
          const row = el('label', '', 'field-row'),
            c = el('input');
          c.type = 'checkbox';
          c.disabled = disabled;
          c.checked = draft.subjects.some((r) => key(r) === key(ref));
          c.addEventListener('change', () => {
            draft.subjects = draft.subjects.filter((r) => key(r) !== key(ref));
            if (c.checked) draft.subjects.push(ref);
            void save();
          });
          row.append(c, el('span', `${p.title} · v${p.version}`));
          return row;
        }),
    );
    // Keep explicit older selections visible; never silently substitute the head.
    for (const ref of draft.subjects.filter(
      (r) => !s.products.some((p) => p.product_id === r.object_id && p.version === r.version),
    )) {
      const row = el(
        'p',
        t('已选历史版本', 'Selected historical version') +
          ' · ' +
          ref.object_id +
          ' · v' +
          ref.version,
      );
      const remove = el('button', t('取消选择', 'Deselect'), 'btn');
      remove.type = 'button';
      remove.disabled = disabled;
      remove.onclick = () => {
        draft.subjects = draft.subjects.filter((r) => key(r) !== key(ref));
        void save();
        render();
      };
      row.append(remove);
      products.append(row);
    }
    if (!followups.contains(doc.activeElement)) {
      followups.replaceChildren();
      const valid = (s.responses ?? []).filter((r) => r.feedback && r.session_id && r.version);
      if (valid.length)
        followups.append(
          el(
            'p',
            t(
              '可关联已记录的异议或补证；关联不代表问题已解决。',
              'You may link recorded challenges or evidence; linking does not resolve them.',
            ),
            'muted',
          ),
        );
      for (const r of valid) {
        const ref: ObjectRef = {
          session_id: r.session_id!,
          kind: 'feedback_response',
          object_id: r.id,
          version: r.version!,
        };
        const row = el('label', '', 'field-row'),
          c = el('input');
        c.type = 'checkbox';
        c.disabled = disabled;
        c.checked = draft.followup_of.some((x) => key(x) === key(ref));
        c.onchange = () => {
          draft.followup_of = draft.followup_of.filter((x) => key(x) !== key(ref));
          if (c.checked) draft.followup_of.push(ref);
          void save();
        };
        row.append(c, el('span', r.text));
        followups.append(row);
      }
    }
    rows.replaceChildren();
    if (s.reviewHistoryAvailable === false)
      rows.append(
        el(
          'p',
          t(
            '评审历史入口尚未就绪；这不表示没有过评审。',
            'Review history is not available yet; this does not mean no reviews occurred.',
          ),
          'muted',
        ),
      );
    for (const r of [...(s.reviews ?? [])].reverse()) {
      const item = el('article');
      item.append(
        el('h3', r.question || t('作品评审', 'Artifact review'), 'row-title'),
        el(
          'p',
          r.purpose === 'undetermined' ? t('用途待明确', 'Purpose not specified') : r.purpose,
        ),
      );
      for (const ref of r.subjects) {
        const b = el(
          'button',
          t('查看评审作品', 'View reviewed artifact') + ' · v' + ref.version,
          'btn',
        );
        b.type = 'button';
        b.onclick = () => adapter.openReference(ref);
        item.append(b);
      }
      const ready = s.reports.some(
        (f) =>
          f.subject.kind === 'review' &&
          f.subject.object_id === r.id &&
          f.subject.version === r.version,
      );
      item.append(
        el(
          'p',
          ready
            ? t('反馈已保存，见下方分段反馈。', 'Feedback is saved in the sections below.')
            : t('评审已保存，反馈尚未就绪。', 'Review saved; feedback is not ready yet.'),
          'muted',
        ),
      );
      rows.append(item);
    }
    const submissions = new Map((s.submissions ?? []).map((r) => [key(r.ref), r.ref]));
    for (const r of s.reports.filter((r) => r.subject.kind === 'submission'))
      submissions.set(key(r.subject), r.subject);
    if (s.submission) submissions.set(key(s.submission.ref), s.submission.ref);
    for (const ref of submissions.values()) {
      const b = el(
        'button',
        t('查看提交快照', 'View submission snapshot') + ' · ' + ref.object_id,
        'btn',
      );
      b.type = 'button';
      b.onclick = () => adapter.openReference(ref);
      rows.append(b);
    }
    history.hidden = !(s.reviews?.length || submissions.size || s.reviewHistoryAvailable === false);
  }
  render();
  return {
    element,
    render,
    destroy: () => {
      alive = false;
      element.remove();
    },
  };
}
