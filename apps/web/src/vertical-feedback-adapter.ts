import type { FeedbackNativeAdapter, FeedbackNativeState } from './features/feedback-native';
import type { EvidenceRefV2 } from './features/workspace/contract-types';
import type { VerticalClient, Ref } from './vertical-client';

export function feedbackAdapter(
  client: VerticalClient,
  open: (ref: Ref) => Promise<void>,
  choose: () => Promise<EvidenceRefV2[]>,
): FeedbackNativeAdapter {
  let state: FeedbackNativeState = {
    products: [],
    reports: [],
    responses: [],
    modelMode: 'placeholder',
    status: 'active',
    busy: false,
  };
  const listeners = new Set<() => void>();
  let off: (() => void) | undefined, reading: Promise<void> | undefined;
  const emit = () => listeners.forEach((fn) => fn());
  let pendingId = client.draft('feedback-pending');
  const poll = (id: string) => {
    void client
      .wait(id)
      .then(async (result) => {
        if (result.status === 'failed')
          state = { ...state, error: '反馈处理未完成，提交与原作品已保存。请保留本次记录。' };
        await refresh();
      })
      .catch(() => {
        state = { ...state, error: '后台结果尚未读回；原提交已保留，请查看最新反馈。' };
        emit();
      });
  };
  async function refresh() {
    if (reading) return reading;
    reading = (async () => {
      await client.refresh(false);
      await client.workspace.refresh();
      const submissions = (await client.page('/submissions')).items;
      const lists = await Promise.all(
        submissions.map((s: any) => client.page('/feedback/' + encodeURIComponent(s.id))),
      );
      const reports = lists.flatMap((p: any) => p.items);
      const responses = (
        await Promise.all(
          reports.map((f: any) =>
            client.page('/feedback/' + encodeURIComponent(f.id) + '/responses'),
          ),
        )
      ).flatMap((p: any) => p.items);
      const latest = submissions.at(-1);
      state = {
        ...state,
        products: client.workspace.snapshot().products,
        reports,
        responses,
        status: client.state.status,
        modelMode: client.timeline.role_mode === 'model' ? 'provider' : 'placeholder',
        submission: latest
          ? {
              ref: client.ref('submission', latest.id, latest.version) as any,
              products: latest.products,
              decision: latest.decision,
            }
          : null,
        pending: !!pendingId,
      };
      emit();
    })()
      .catch((error) => {
        state = { ...state, error: error instanceof Error ? error.message : '反馈读取未完成' };
        emit();
        throw error;
      })
      .finally(() => {
        reading = undefined;
      });
    return reading;
  }
  async function write(path: string, operation: string, payload: any) {
    if (pendingId) throw Error('先恢复上一请求的结果。');
    const id = crypto.randomUUID();
    state = { ...state, busy: true, error: '' };
    emit();
    try {
      client.keep('feedback-pending', id);
      pendingId = id;
      const result = await client.command(path, operation, payload, id);
      pendingId = '';
      client.keep('feedback-pending', '');
      if (operation === 'submissions.create') poll(id);
      await refresh();
      return result;
    } catch (error) {
      const journal = client.storage.getItem(client.requestKey(id));
      if (!journal || JSON.parse(journal).status === 'rejected') {
        pendingId = '';
        client.keep('feedback-pending', '');
      }
      state = { ...state, pending: !!pendingId };
      throw error;
    } finally {
      state = { ...state, busy: false };
      emit();
    }
  }
  return {
    snapshot: () => state,
    subscribe(callback) {
      listeners.add(callback);
      if (!off)
        off = client.subscribe(() => {
          void refresh().catch(() => {});
        });
      return () => {
        listeners.delete(callback);
        if (!listeners.size) {
          off?.();
          off = undefined;
        }
      };
    },
    submit(input) {
      const config = client.timeline.workspace?.config;
      return write('/submissions', 'submissions.create', {
        ...input,
        config: config
          ? {
              ...client.ref('config', config.id, config.version),
              config_version: config.config_version,
            }
          : null,
      });
    },
    respond(input) {
      return write(
        '/feedback/' + encodeURIComponent(input.feedback_id) + '/responses',
        'feedback.responses.create',
        input,
      );
    },
    beginRevision(input) {
      return write('/revision-cycles', 'begin_revision', input);
    },
    refresh,
    async recover() {
      if (!pendingId) return;
      const id = pendingId;
      const result = await client.recover(id);
      pendingId = '';
      client.keep('feedback-pending', '');
      if (result.status === 'pending') poll(id);
      await refresh();
    },
    openReference(ref) {
      void open(ref as Ref);
    },
    chooseEvidence: choose,
    readDraft(key) {
      const raw = client.draft('feedback-draft-' + key);
      return raw ? JSON.parse(raw) : undefined;
    },
    async keepDraft(key, draft) {
      client.keep('feedback-draft-' + key, JSON.stringify(draft));
    },
  };
}

export function chooseEvidence(client: VerticalClient): Promise<EvidenceRefV2[]> {
  const values: any[] = JSON.parse(client.draft('evidence-cache', '[]'));
  return new Promise((resolve) => {
    const dialog = document.createElement('dialog');
    dialog.className = 'v2-evidence-dialog';
    const title = document.createElement('h2');
    title.textContent = '选择原始引用';
    dialog.append(title);
    const hint = document.createElement('p');
    hint.textContent = values.length
      ? '下面是你已打开材料的确切原文片段。补证保存后仍待核验。'
      : '先打开一份材料，再回到这里选择原文。';
    dialog.append(hint);
    const selected = new Set<number>();
    values.forEach((ref, index) => {
      const label = document.createElement('label'),
        input = document.createElement('input'),
        text = document.createElement('span');
      input.type = 'checkbox';
      input.onchange = () => {
        if (input.checked) selected.add(index);
        else selected.delete(index);
      };
      text.textContent =
        (client.timeline.workspace?.material_titles?.[ref.object_id + ':' + ref.version] ||
          '材料') +
        ' · v' +
        ref.version +
        '：' +
        ref.quote;
      label.append(input, text);
      dialog.append(label);
    });
    const save = document.createElement('button');
    save.className = 'btn primary';
    save.textContent = '使用所选原文';
    save.onclick = () => {
      dialog.close();
      dialog.remove();
      resolve([...selected].map((i) => values[i]));
    };
    const cancel = document.createElement('button');
    cancel.className = 'btn';
    cancel.textContent = '取消';
    cancel.onclick = () => {
      dialog.close();
      dialog.remove();
      resolve([]);
    };
    dialog.append(save, cancel);
    dialog.addEventListener(
      'cancel',
      () => {
        dialog.remove();
        resolve([]);
      },
      { once: true },
    );
    document.body.append(dialog);
    dialog.showModal();
  });
}
