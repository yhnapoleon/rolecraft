import type { V4HostAdapter, V4CommandResult } from '../../../v4-host';
import type { WorkspaceSlotController } from './slot-controller';
import { canonicalPurpose, taskPriority } from './form-values';

export type FormDraft = {
  schema: 1;
  token: string;
  values: Record<string, string>;
  baseRevision?: number;
  requestId?: string;
  requestToken?: string;
  saved?: boolean;
};
export function confirmedFormDraft(current: FormDraft | undefined, sent: FormDraft) {
  const changed = !!current && current.token !== sent.token;
  return {
    changed,
    draft: changed
      ? { ...current!, requestId: undefined, requestToken: undefined }
      : { ...sent, saved: true, requestId: undefined, requestToken: undefined },
  };
}
/** Bind the existing v4 form and its external submit button; create no new modal. */
export function bindWorkspaceForm(
  kind: 'task' | 'product',
  form: HTMLFormElement,
  host: V4HostAdapter,
  controller: WorkspaceSlotController,
) {
  const sid = host.snapshot().session?.sessionId,
    id = kind === 'task' ? (form.dataset.id ?? '') : '';
  const key = sid + ':' + kind + '-form:' + id,
    T = (zh: string, en: string) => (host.snapshot().uiLanguage === 'en' ? en : zh);
  const fields =
    kind === 'task'
      ? ['title', 'note', 'priority', 'split']
      : ['title', 'purpose', 'taskId', 'content', 'kind'];
  let stopped = false,
    pending = false;
  const capturedRevision = Number(form.dataset.revision);
  const selected = host.snapshot().currentTask;
  const baseRevision = id
    ? Number.isSafeInteger(capturedRevision) && capturedRevision > 0
      ? capturedRevision
      : selected?.object_id === id
        ? selected.version
        : undefined
    : undefined;
  let draft = host.draft<FormDraft>('workspace', key);
  const active = () => !stopped && host.snapshot().session?.sessionId === sid;
  const status = form.ownerDocument.createElement('p');
  status.className = 'w03-slot-content';
  status.setAttribute('role', 'status');
  form.append(status);
  const recover = form.ownerDocument.createElement('button');
  recover.type = 'button';
  recover.className = 'btn quiet small w03-slot-content';
  form.append(recover);
  const values = () => {
    const data = new FormData(form);
    return Object.fromEntries(
      fields.filter((n) => data.has(n)).map((n) => [n, String(data.get(n) ?? '')]),
    );
  };
  if (draft?.schema === 1 && !draft.saved) {
    for (const [name, value] of Object.entries(draft.values)) {
      for (const field of form.querySelectorAll<
        HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
      >('[name]')) {
        if (field.name !== name) continue;
        if (
          field instanceof form.ownerDocument.defaultView!.HTMLInputElement &&
          field.type === 'radio'
        )
          field.checked = field.value === value;
        else field.value = value;
      }
    }
  } else draft = undefined;
  const keep = async () => {
    if (!active()) return;
    draft = {
      schema: 1,
      token: crypto.randomUUID(),
      values: values(),
      baseRevision: draft?.baseRevision ?? baseRevision,
      requestId: draft?.requestId,
      requestToken: draft?.requestToken,
    };
    await host.keepDraft('workspace', key, draft);
  };
  const typed = (event: Event) => {
    event.stopPropagation();
    void keep().catch(() => {
      status.textContent = T(
        '本机保存未确认，请保留文字。',
        'Local saving is unconfirmed. Keep your text.',
      );
    });
  };
  const confirmed = async (result: V4CommandResult, sent: FormDraft) => {
    if (!active()) return;
    const confirmation = confirmedFormDraft(draft, sent),
      changed = confirmation.changed;
    draft = confirmation.draft;
    await host.keepDraft('workspace', key, draft);
    status.textContent = changed
      ? T(
          '此前输入已保存；新增文字仍为草稿。',
          'Earlier input was saved; your newer text remains a draft.',
        )
      : T('已保存到工作区', 'Saved to workspace');
    if (kind === 'product' && !changed) controller.selectConfirmedProduct(result);
    form.dispatchEvent(
      new CustomEvent('w03:form-confirmed', {
        bubbles: true,
        detail: { form: kind, requestId: result.requestId, changedWhileWaiting: changed },
      }),
    );
  };
  const submit = async (event: Event) => {
    event.preventDefault();
    event.stopImmediatePropagation();
    if (!active() || pending) return;
    pending = true;
    status.textContent = '';
    try {
      await keep();
      await controller.flush();
      const sent = structuredClone(draft!),
        v = sent.values;
      let result;
      if (kind === 'task')
        result = await controller.saveTaskForm({
          id,
          title: v.title ?? '',
          goal: v.note ?? '',
          priority: taskPriority(v.priority ?? 'next'),
          baseRevision: sent.baseRevision,
          split: v.split ?? '',
        });
      else {
        const ref = v.taskId
          ? controller.state.tasks.find((t) => t.id === v.taskId && t.status !== 'removed')
          : undefined;
        if (v.taskId && !ref) throw Error('task_not_available');
        result = await controller.create({
          kind: 'text',
          title: v.title ?? '',
          purpose: canonicalPurpose(v.purpose ?? 'exploration'),
          content: v.content ?? '',
          task: ref
            ? { session_id: ref.session_id, kind: 'task', object_id: ref.id, version: ref.revision }
            : null,
        });
      }
      if (!active()) return;
      if (result.status === 'confirmed') await confirmed(result, sent);
      else {
        draft = { ...draft!, requestId: result.requestId, requestToken: sent.token };
        await host.keepDraft('workspace', key, draft);
        status.textContent = T(
          '请求结果待确认；文字已保留。',
          'The request result is pending; your text is retained.',
        );
      }
    } catch (error) {
      const code = error instanceof Error ? error.message : '';
      status.textContent =
        code === 'task_revision_missing'
          ? T(
              '原事项版本未提供；文字已保留，请重新打开事项。',
              'The original task version is missing. Your text is retained; reopen the task.',
            )
          : code === 'task_conflict'
            ? T(
                '事项已有新版本；文字已保留，请比较后再保存。',
                'The task has a newer version. Your text is retained; compare before saving.',
              )
            : T(
                '保存未完成；文字和选择已保留。',
                'Saving did not complete; your text and choices are retained.',
              );
    } finally {
      pending = false;
      update();
    }
  };
  const readResult = async () => {
    if (
      !active() ||
      pending ||
      !draft?.requestId ||
      controller.state.receipt?.requestId !== draft.requestId
    )
      return;
    pending = true;
    const sent = { ...structuredClone(draft), token: draft.requestToken ?? draft.token };
    try {
      const result = await controller.recover();
      if (result.status === 'confirmed') await confirmed(result, sent);
      else
        status.textContent = T(
          '原请求尚未完成，未重发。',
          'The original request is not complete. It was not resent.',
        );
    } catch {
      status.textContent = T(
        '暂未取得原请求结果；文字已保留。',
        'The original result is unavailable; your text is retained.',
      );
    } finally {
      pending = false;
      update();
    }
  };
  function update() {
    if (!active()) return;
    recover.textContent = T('查看原请求结果', 'Check original request result');
    recover.hidden = !draft?.requestId || draft.saved === true;
    recover.disabled = pending || host.snapshot().busy;
    // Includes v4's external <button form="task-form" type="submit">.
    for (const control of Array.from(form.elements))
      if (
        control instanceof form.ownerDocument.defaultView!.HTMLButtonElement &&
        control.type === 'submit'
      )
        control.disabled =
          pending ||
          controller.blocked() ||
          !controller.can(
            kind === 'task'
              ? id
                ? 'work_items.update'
                : 'work_items.create'
              : 'work_products.create',
          );
  }
  form.addEventListener('input', typed);
  form.addEventListener('change', typed);
  form.addEventListener('submit', submit);
  recover.addEventListener('click', readResult);
  update();
  return {
    update,
    destroy: () => {
      stopped = true;
      form.removeEventListener('input', typed);
      form.removeEventListener('change', typed);
      form.removeEventListener('submit', submit);
      recover.removeEventListener('click', readResult);
      status.remove();
      recover.remove();
    },
  };
}
