/** W04's original v4 colleague slot. The host supplies thread/composer and canonical role ID. */
import type { V4SlotContext, V4SlotHandle, V4HostSnapshot, V4CommandResult } from '../../v4-host';
import type { ObjectRef } from '../../contracts-v2';
import { T } from '../../app/i18n';
import {
  mountConversation,
  type RoleId,
  type RolesNativeAdapter,
  type RolesView,
  type TurnStatus,
} from './index';
import {
  object,
  body,
  commandBody,
  session,
  ref,
  timeline,
  recipientShares,
  requestRefs,
  rememberRequest,
} from './v4-data';

const roles: RoleId[] = ['supervisor', 'business_lead', 'tech_lead'];
const errorText = () =>
  T(
    '操作尚未确认，文字已保留。请使用原请求恢复。',
    'The operation is unconfirmed. Your text is retained; recover the original request.',
  );

export function mount(context: V4SlotContext): V4SlotHandle {
  const { host, nodes } = context;
  const initial = host.snapshot().session;
  if (!initial || initial.protocol !== 2) return { update() {}, destroy() {} };
  const sid = initial.sessionId;
  const thread = nodes.thread;
  const composer = nodes.composer;
  const input = composer?.querySelector<HTMLTextAreaElement>('#chat-input');
  const selected = thread?.dataset.roleId as RoleId;
  if (!thread || !(composer instanceof HTMLFormElement) || !input || !roles.includes(selected)) {
    host.announce(
      T(
        '同事插槽缺少确切角色或原输入框。',
        'The colleague slot is missing its bound role or original composer.',
      ),
      'error',
    );
    const prevent = (event: Event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
    };
    composer?.addEventListener('submit', prevent);
    if (thread) {
      const note = thread.ownerDocument.createElement('p');
      note.className = 'meta';
      note.textContent = T(
        '同事上下文尚未就绪，输入已保留。',
        'Colleague context is not ready; your input is retained.',
      );
      thread.replaceChildren(note);
    }
    return {
      update() {},
      destroy() {
        composer?.removeEventListener('submit', prevent);
      },
    };
  }
  const inputNode = input;
  const form = composer;
  const draftKey = 'question:' + selected;
  let destroyed = false,
    busy = false,
    unknownDispatch = false,
    readTicket = 0;
  let pending = host.draft<string | null>('roles', 'pendingRequestId') || undefined;
  let inputRevision = 0,
    knownFailure = false;
  let roleMode: RolesView['mode'] = 'unavailable';
  const confirmations = new Map<string, V4CommandResult>();
  const adopted = new Set<string>();
  const submittedVersions = new Map<string, number>();
  const requestForTurn = new Map<string, V4CommandResult>();
  const replyForTurn = new Map<string, ObjectRef>();
  const fail = () => {
    if (!destroyed)
      host.announce(
        knownFailure
          ? T(
              '本次处理未成功，原文字仍保留。',
              'This operation failed; the original text is retained.',
            )
          : errorText(),
        'error',
      );
  };
  const writable = () =>
    !destroyed &&
    !busy &&
    !unknownDispatch &&
    !pending &&
    !host.snapshot().busy &&
    !host.snapshot().storageError &&
    host.snapshot().state === 'active' &&
    !!host.snapshot().available['turns.create'] &&
    roleMode !== 'unavailable';
  const buttons = () =>
    Array.from(form.querySelectorAll<HTMLButtonElement>('button[type="submit"]'));
  function updateControls() {
    for (const b of buttons()) b.disabled = !writable();
  }
  const save = async () => {
    session(host, sid);
    await host.keepDraft('roles', draftKey, inputNode.value);
  };
  const onInput = (event: Event) => {
    event.stopImmediatePropagation();
    ++inputRevision;
    void save().catch(fail);
  };
  const saved = host.draft<string>('roles', draftKey);
  if (typeof saved === 'string' && !inputNode.value && document.activeElement !== inputNode)
    inputNode.value = saved;

  const admitted = (result: V4CommandResult) => {
    const data = commandBody(result);
    if (!data.turn || typeof data.question !== 'string' || !roles.includes(data.role_id))
      return false;
    ref(data.turn, sid, 'role_turn');
    return true;
  };
  async function accepted(incoming: V4CommandResult) {
    const result = confirmations.get(incoming.requestId) ?? incoming;
    const data = commandBody(result);
    if (result.status === 'confirmed' || admitted(result)) {
      confirmations.set(result.requestId, result);
      if (!adopted.has(result.requestId)) {
        adopted.add(result.requestId);
        const revision = submittedVersions.get(result.requestId) ?? 0;
        if (
          !destroyed &&
          inputRevision === revision &&
          data.question === inputNode.value &&
          data.role_id === selected
        ) {
          await host.keepDraft('roles', draftKey, '');
          if (!destroyed && inputRevision === revision && data.question === inputNode.value)
            inputNode.value = '';
        }
      }
      if (pending === result.requestId) {
        pending = undefined;
        await host.keepDraft('roles', 'pendingRequestId', null);
      }
      unknownDispatch = false;
      knownFailure = false;
    } else if (result.status === 'unconfirmed' || result.status === 'pending') {
      pending = result.requestId;
      await host.keepDraft('roles', 'pendingRequestId', pending);
    } else {
      if (pending === result.requestId) {
        pending = undefined;
        await host.keepDraft('roles', 'pendingRequestId', null);
      }
      unknownDispatch = false;
      knownFailure = result.status === 'failed';
    }
    updateControls();
  }
  async function recover() {
    if (!pending) throw Error('Use the host original-request recovery');
    const result = await host.recover(pending);
    session(host, sid);
    await accepted(result);
    if (result.status !== 'confirmed') throw Error('Original request remains unresolved');
  }
  let reading: Promise<RolesView> | undefined;
  let readAgain = false;
  const readOnce = async (): Promise<RolesView> => {
    const ticket = ++readTicket;
    const s = session(host, sid);
    const publicData = await timeline(host, sid);
    const statuses = new Map<string, V4CommandResult>();
    let unresolved: string | undefined;
    for (const id of new Set([...requestRefs(host, 'roles'), ...(pending ? [pending] : [])])) {
      try {
        const result = await host.recover(id);
        const data = commandBody(result);
        if (result.status === 'confirmed' || admitted(result)) confirmations.set(id, result);
        if (pending === id) await accepted(result);
        if (data.turn) {
          const turn = ref(data.turn, sid, 'role_turn');
          statuses.set(turn.object_id, result);
        }
        if (result.status === 'unconfirmed' || (result.status === 'pending' && !admitted(result)))
          unresolved = id;
      } catch {
        unresolved = id;
      }
    }
    session(host, sid);
    if (ticket === readTicket) {
      pending = unresolved;
      requestForTurn.clear();
      for (const [id, result] of statuses) requestForTurn.set(id, result);
    }
    const replies = publicData.rows.filter((r) => r.ref.kind === 'role_reply');
    const displays = publicData.rows.filter((r) => r.ref.kind === 'role_display');
    const titles = publicData.data.workspace?.material_titles ?? {};
    const turns = publicData.rows
      .filter((r) => r.ref.kind === 'role_turn')
      .map((row) => {
        const request = row.content;
        const source = object(request.input);
        if (!roles.includes(source.role_id) || typeof source.text !== 'string')
          throw Error('Invalid public question');
        const reply = replies.find(
          (r) => ref(r.content.request, sid, 'role_turn').object_id === row.ref.object_id,
        );
        if (
          reply &&
          (reply.content.role_id !== source.role_id ||
            typeof reply.content.text !== 'string' ||
            reply.content.question !== source.text)
        )
          throw Error('Reply binding mismatch');
        if (reply && ticket === readTicket) replyForTurn.set(row.ref.object_id, reply.ref);
        const result = statuses.get(row.ref.object_id);
        const raw = result ? body(result.result ?? {}) : {};
        const job = Array.isArray(raw.jobs) ? raw.jobs[0] : undefined;
        const jobStatus = job?.status ?? (result ? commandBody(result).status : undefined);
        let status: TurnStatus = reply ? 'completed' : 'unknown';
        if (
          !reply &&
          ['queued', 'running', 'failed', 'needs_context', 'paused', 'cancelled'].includes(
            jobStatus,
          )
        )
          status = jobStatus;
        else if (!reply && result?.status === 'failed') status = 'failed';
        else if (!reply && result?.status === 'needs_context') status = 'needs_context';
        const materials = Object.entries(titles).flatMap(([key, title]) => {
          const split = key.lastIndexOf(':');
          const version = Number(key.slice(split + 1));
          const id = key.slice(0, split);
          return typeof title === 'string' &&
            split > 0 &&
            Number.isInteger(version) &&
            version > 0 &&
            reply?.content.text.includes('[' + title + ' · v' + version + ']')
            ? [{ id, title, version }]
            : [];
        });
        return {
          id: row.ref.object_id,
          roleId: source.role_id,
          question: source.text,
          status,
          reply: reply?.content.text,
          materials,
          omissionCount:
            reply &&
            Number.isInteger(reply.content.omission_count) &&
            reply.content.omission_count > 0
              ? Number(reply.content.omission_count)
              : 0,
          stale: materials.some((material) => {
            const current = publicData.data.workspace?.source_versions?.[material.id];
            return typeof current === 'number' && current > material.version;
          }),
          canRecordDisplay:
            !!host.snapshot().available['turns.display'] &&
            !pending &&
            !unknownDispatch &&
            !host.snapshot().storageError,
          displayRecorded:
            !!reply &&
            displays.some(
              (d) =>
                ref(d.content.reply, sid, 'role_reply').object_id === reply.ref.object_id &&
                d.content.reply.version === reply.ref.version,
            ),
          canRetry: status === 'failed' && !!result && !!host.snapshot().available['jobs.refresh'],
          canRefresh:
            status === 'needs_context' && !!result && !!host.snapshot().available['jobs.refresh'],
          explanation:
            status === 'unknown'
              ? T(
                  '处理状态尚待确认，原问题已保留。',
                  'Processing status is not yet confirmed; the original question is retained.',
                )
              : undefined,
        };
      });
    const state = host.snapshot();
    const mode =
      publicData.data.role_mode ??
      { waiting_model: 'local_reference', model: 'model', unavailable: 'unavailable' }[
        state.semantic?.roles ?? 'unavailable'
      ];
    if (ticket === readTicket)
      roleMode = ['local_reference', 'model', 'unavailable'].includes(mode) ? mode : 'unavailable';
    updateControls();
    return {
      sessionId: sid,
      workLanguage: s.workLanguage,
      mode: ['local_reference', 'model', 'unavailable'].includes(mode) ? mode : 'unavailable',
      colleagues: roles.map((id) => ({
        id,
        name:
          id === 'supervisor'
            ? T('经理', 'Manager')
            : id === 'business_lead'
              ? T('陈敏', 'Chen Min')
              : T('技术负责人', 'Technical lead'),
        available: mode !== 'unavailable',
      })),
      turns,
      canSend: writable(),
      unconfirmed: !!pending || unknownDispatch,
      restriction:
        state.state === 'active'
          ? undefined
          : T(
              '当前练习只读，原问题与回复保留。',
              'This session is read-only; original questions and replies are retained.',
            ),
    };
  };
  const adapter: RolesNativeAdapter = {
    read() {
      return (reading ??= (async () => {
        let next: RolesView;
        // A timeline update can arrive while the prior read is still in flight.
        // Finish with a fresh read instead of painting that stale reply forever.
        do {
          readAgain = false;
          next = await readOnce();
        } while (readAgain && !destroyed);
        return next;
      })().finally(() => {
        reading = undefined;
      }));
    },
    async send({ roleId, text }) {
      if (roleId !== selected || !writable()) throw Error('Colleague command unavailable');
      const submittedRevision = inputRevision;
      const task = host.snapshot().currentTask;
      busy = true;
      knownFailure = false;
      updateControls();
      let result: V4CommandResult | undefined;
      let dispatchStarted = false;
      try {
        await save();
        await host.flushDrafts();
        session(host, sid);
        const shares = await recipientShares(host, sid, roleId);
        dispatchStarted = true;
        result = await host.command('turns.create', {
          role_id: roleId,
          text,
          shares,
          ...(task ? { task: ref(task, sid, 'task') } : {}),
        });
        submittedVersions.set(result.requestId, submittedRevision);
        if (['pending', 'unconfirmed'].includes(result.status) && !admitted(result)) {
          pending = result.requestId;
          await host.keepDraft('roles', 'pendingRequestId', pending);
        }
        await rememberRequest(host, 'roles', result);
        await accepted(result);
        if (result.status !== 'confirmed' && !admitted(result))
          throw Error('Original request is unresolved');
      } catch (error) {
        unknownDispatch = dispatchStarted && !result;
        if (
          result &&
          ['pending', 'unconfirmed'].includes(result.status) &&
          !confirmations.has(result.requestId)
        )
          pending = result.requestId;
        knownFailure = result?.status === 'failed';
        throw error;
      } finally {
        busy = false;
        updateControls();
      }
    },
    recover,
    async retry(turnId) {
      const original = requestForTurn.get(turnId);
      if (!original) throw Error('Original request missing');
      const result = await host.retry(original.requestId);
      await rememberRequest(host, 'roles', result);
      await accepted(result);
    },
    async refreshContext(turnId) {
      return adapter.retry!(turnId);
    },
    openMaterial(material) {
      return host.openReference(
        ref(
          { session_id: sid, kind: 'material', object_id: material.id, version: material.version },
          sid,
          'material',
        ),
      );
    },
    async recordDisplay(turnId) {
      const reference = replyForTurn.get(turnId);
      if (!reference || !host.snapshot().available['turns.display']) return;
      const result = await host.command('turns.display', { ref: reference });
      await rememberRequest(host, 'roles', result);
      if (result.status !== 'confirmed') {
        if (['pending', 'unconfirmed'].includes(result.status)) pending = result.requestId;
        throw Error('Display receipt unconfirmed');
      }
    },
  };
  thread.replaceChildren(); // The assigned history surface is owned by this v2 slot.
  const view = mountConversation(thread, adapter, selected);
  const onSubmit = (event: Event) => {
    event.preventDefault();
    event.stopImmediatePropagation();
    const typed = inputNode.value;
    if (!typed.trim() || !writable()) return;
    // A quoted test sits outside the editable box; it is sent once, ahead of the person's own words.
    const quote =
      form.closest('.chat')?.querySelector<HTMLElement>('.chat-quote')?.dataset.quote || '';
    const text = quote ? quote + '\n' + typed : typed;
    if (text.length > 4000) {
      host.announce(
        T(
          '引用加上问题超过 4000 字，请缩短问题或移除引用。',
          'The quote plus your question is over 4,000 characters. Shorten it or remove the quote.',
        ),
        'error',
      );
      return;
    }
    void adapter
      .send({ roleId: selected, text })
      .then(() => {
        if (quote && !destroyed)
          form.dispatchEvent(
            new CustomEvent('rolecraft:quote-sent', {
              bubbles: true,
              detail: { roleId: selected },
            }),
          );
      })
      .catch(fail)
      .finally(() => {
        void Promise.resolve(reading)
          .catch(() => {})
          .then(() => {
            if (!destroyed) return view.refresh();
          });
      });
  };
  form.addEventListener('submit', onSubmit);
  inputNode.addEventListener('input', onInput);
  function update(snapshot: Readonly<V4HostSnapshot>) {
    if (destroyed) return;
    if (snapshot.session?.sessionId !== sid || snapshot.session.protocol !== 2) {
      destroy();
      return;
    }
    updateControls();
    // Both the host subscription and V4Mounts call update. Recovery emits too,
    // but an unchanged snapshot/request set is not new dialogue evidence.
    const key = readSignal(snapshot);
    if (key === lastSnapshot) return;
    lastSnapshot = key;
    if (reading) readAgain = true;
    void view.refresh().catch(fail);
  }
  const readSignal = (snapshot: Readonly<V4HostSnapshot>) =>
    JSON.stringify([snapshot, requestRefs(host, 'roles'), pending]);
  let lastSnapshot = readSignal(host.snapshot());
  const unsubscribe = host.subscribe(() => update(host.snapshot()));
  function destroy() {
    if (destroyed) return;
    destroyed = true;
    ++readTicket;
    unsubscribe();
    form.removeEventListener('submit', onSubmit);
    inputNode.removeEventListener('input', onInput);
    view.destroy();
  }
  updateControls();
  return { update, destroy };
}
export default mount;
