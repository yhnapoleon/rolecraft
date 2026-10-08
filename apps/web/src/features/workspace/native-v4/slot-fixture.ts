/** Development-only adapter fixture. No HTTP, model, credentials or persistence claim.
 * Tests the slot's DOM behavior while the shared host implementation is pending. */
import { mount } from './v4-slot';
import type { V4HostAdapter, V4HostSnapshot, V4CommandResult } from '../../../v4-host';
import type {
  WorkspaceProductRead,
  WorkspaceTask,
  ProductShare,
  ObjectRef,
} from '../contract-types';
import { productInput, productRef } from './slot-controller';

export function mountSlotFixture(container: HTMLElement) {
  const doc = container.ownerDocument;
  const seed = (id: string, content: string): WorkspaceProductRead => ({
    session_id: 'slot-fixture',
    product_id: id,
    version: 1,
    kind: 'text',
    title: 'Slot test product',
    purpose: 'exploration',
    content,
    content_hash: 'f'.repeat(64),
    cycle: { session_id: 'slot-fixture', kind: 'cycle', object_id: 'cycle', version: 1 },
    author: { id: 'learner', kind: 'human' },
    executor: { id: 'learner', kind: 'human' },
    created_at: '2026-10-07T00:00:00Z',
    visibility: 'private',
  });
  let products = [seed('product-1', 'Saved version one')],
    tasks: WorkspaceTask[] = [],
    shares: ProductShare[] = [],
    history = structuredClone(products),
    seq = 1,
    loseNext = false;
  let snapshot: V4HostSnapshot = {
    session: {
      protocol: 2,
      sessionId: 'slot-fixture',
      workLanguage: 'zh',
      scenarioHash: 'controlled-slot-fixture',
    },
    uiLanguage: 'zh',
    state: 'active',
    asOf: { business_seq: 0, workspace_revision: 1, storage_revision: 1 },
    currentTask: null,
    currentProduct: productRef(products[0]),
    busy: false,
    storageError: false,
    available: Object.fromEntries(
      [
        'work_items.list',
        'work_items.create',
        'work_items.update',
        'work_items.batch',
        'work_products.list',
        'work_products.create',
        'work_products.versions.list',
        'work_products.versions.create',
        'work_products.shares.create',
        'work_products.shares.change',
        'work_products.adopt',
      ].map((k) => [k, true]),
    ),
  };
  const drafts = new Map<string, unknown>(),
    records = new Map<string, V4CommandResult>(),
    listeners = new Set<() => void>();
  const counts = { commands: 0, recovers: 0, retries: 0, selections: 0 };
  const emit = () => {
    for (const f of listeners) f();
    counter.textContent =
      'Fixture only — commands: ' +
      counts.commands +
      ', recover reads: ' +
      counts.recovers +
      ', retries: ' +
      counts.retries;
  };
  const advance = () => {
    seq++;
    snapshot = {
      ...snapshot,
      asOf: { business_seq: 0, workspace_revision: seq, storage_revision: seq },
    };
  };
  const project = (p: WorkspaceProductRead): WorkspaceProductRead => ({
    ...p,
    visibility: shares.some(
      (s) =>
        s.product.object_id === p.product_id && s.product.version === p.version && !s.revoked_at,
    )
      ? 'shared'
      : 'private',
  });
  const host: V4HostAdapter = {
    snapshot: () => snapshot,
    subscribe: (fn: () => void) => {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
    query: async (op: string, input: Readonly<Record<string, unknown>> = {}) => {
      const page = { schema_version: 2, as_of: snapshot.asOf, next_cursor: null };
      if (op === 'work_items.list')
        return {
          ...page,
          items: structuredClone(
            tasks.sort(
              (a, b) => (a.priority ?? 0) - (b.priority ?? 0) || (a.order ?? 0) - (b.order ?? 0),
            ),
          ),
        };
      if (op === 'work_products.versions.list')
        return {
          ...page,
          items: history.filter((p) => p.product_id === input.product_id).map(project),
          shares: structuredClone(shares.filter((s) => s.product.object_id === input.product_id)),
          sharing_complete: true,
        };
      if (op === 'work_products.list')
        return {
          ...page,
          items: products.map(project),
          shares: structuredClone(shares),
          sharing_complete: true,
        };
      throw Error('fixture_query_unavailable');
    },
    command: async (
      op: string,
      input: Readonly<Record<string, unknown>>,
    ): Promise<V4CommandResult> => {
      counts.commands++;
      let result: any;
      if (op === 'work_products.versions.create') {
        const old = products.find((p) => p.product_id === input.product_id);
        if (!old || old.version !== input.expected_head) throw Error('object_version_conflict');
        const next = {
          ...old,
          ...input,
          version: old.version + 1,
          removed_at: input.removed ? '2026-10-07T00:00:00Z' : null,
        } as WorkspaceProductRead;
        products = products.map((p) => (p === old ? next : p));
        history.push(structuredClone(next));
        result = next;
        if (next.removed_at)
          shares = shares.map((s) =>
            s.product.object_id === next.product_id && !s.revoked_at
              ? { ...s, version: s.version + 1, revoked_at: snapshot.asOf! }
              : s,
          );
      } else if (op === 'work_products.create') {
        result = { ...seed('product-' + (products.length + 1), ''), ...input };
        products.push(result);
        history.push(structuredClone(result));
      } else if (op === 'work_products.shares.create') {
        result = {
          id: 'share-' + (shares.length + 1),
          session_id: 'slot-fixture',
          version: 1,
          product: {
            session_id: 'slot-fixture',
            kind: 'product',
            object_id: input.product_id,
            version: input.product_version,
          },
          recipient_role: input.recipient_role,
          question: input.question,
          purpose: input.purpose,
          shared_at: snapshot.asOf,
          revoked_at: null,
        };
        shares.push(result);
      } else if (op === 'work_products.shares.change') {
        const old = shares.find((s) => s.id === input.share_id);
        if (!old || old.version !== input.expected_revision) throw Error('object_version_conflict');
        result = { ...old, version: old.version + 1, revoked_at: snapshot.asOf };
        shares = shares.map((s) => (s === old ? result : s));
      } else if (op === 'work_items.create') {
        result = {
          id: 'task-' + (tasks.length + 1),
          session_id: 'slot-fixture',
          revision: 1,
          title: input.title,
          goal: input.goal,
          priority: input.priority ?? 0,
          order: tasks.length,
          status: 'open',
          created_at: '2026-10-07T00:00:00Z',
          updated_at: '2026-10-07T00:00:00Z',
        };
        tasks.push(result);
      } else if (op === 'work_items.update' || op === 'work_items.batch') {
        const updates =
          op === 'work_items.batch' ? (input.updates as Record<string, unknown>[]) : [input];
        for (const patch of updates) {
          const old = tasks.find((t) => t.id === patch.item_id);
          if (!old || old.revision !== patch.expected_revision)
            throw Error('object_version_conflict');
        }
        for (const create of op === 'work_items.batch'
          ? ((input.creates ?? []) as Record<string, unknown>[])
          : [])
          tasks.push({
            id: 'task-' + (tasks.length + 1),
            session_id: 'slot-fixture',
            revision: 1,
            title: String(create.title),
            goal: String(create.goal ?? ''),
            priority: Number(create.priority ?? 0),
            order: tasks.length,
            status: 'open',
            parent: create.parent as ObjectRef,
            created_at: '2026-10-07T00:00:00Z',
            updated_at: '2026-10-07T00:00:00Z',
          });
        for (const patch of updates)
          tasks = tasks.map((t) =>
            t.id === patch.item_id
              ? ({ ...t, ...patch, revision: t.revision + 1 } as WorkspaceTask)
              : t,
          );
        result = tasks;
      } else if (op === 'work_products.adopt') {
        products = products.map((p) =>
          p.product_id === input.product_id ? { ...p, adoption: { status: 'adopted' } } : p,
        );
        result = products.find((p) => p.product_id === input.product_id);
      } else throw Error('fixture_command_unavailable');
      syncFormChoices();
      advance();
      const requestId = 'fixture-request-' + counts.commands;
      const confirmed: V4CommandResult = {
        requestId,
        status: 'confirmed',
        result: { object: result, as_of: snapshot.asOf },
      };
      records.set(requestId, confirmed);
      emit();
      if (loseNext) {
        loseNext = false;
        return { requestId, status: 'unconfirmed', result: null };
      }
      return confirmed;
    },
    recover: async (id: string): Promise<V4CommandResult> => {
      counts.recovers++;
      emit();
      const r = records.get(id);
      if (!r) throw Error('unknown_fixture_request');
      return structuredClone(r);
    },
    retry: async (id: string): Promise<V4CommandResult> => {
      counts.retries++;
      emit();
      throw Error('This fixture never needs a fresh attempt: recover ' + id);
    },
    draft: <T>(_slot: string, key: string) => drafts.get(key) as T | undefined,
    keepDraft: async <T>(_slot: string, key: string, value: T) => {
      drafts.set(key, structuredClone(value));
      emit();
    },
    flushDrafts: async () => {},
    openReference: async (ref: ObjectRef) => {
      announcement.textContent = 'Exact reference: ' + ref.object_id + ' v' + ref.version;
    },
    chooseEvidence: async () => [],
    selectTask: (ref: ObjectRef) => {
      snapshot = { ...snapshot, currentTask: ref };
      emit();
    },
    selectProduct: (ref: ObjectRef) => {
      counts.selections++;
      snapshot = { ...snapshot, currentProduct: ref };
      emit();
    },
    announce: (message: string, kind?: 'status' | 'error') => {
      announcement.textContent = message;
      announcement.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    },
  };
  container.innerHTML =
    '<p class="inline-alert">插槽开发夹具 · 合成 host 响应 · 无 HTTP/worker/模型调用 · 不代表正式 v4 验收</p><div data-fixture-controls></div><p data-fixture-count></p><p data-fixture-announcement role="status"></p><article class="paper editor"><input id="editor-title" class="editor-title" aria-label="作品标题"><div class="editor-meta"><select data-purpose aria-label="作品用途"><option value="探索笔记">探索笔记</option><option value="测试计划">测试计划</option><option value="试点决定">试点决定</option></select><span data-save></span></div><textarea id="editor-body" class="editor-body" aria-label="作品正文" rows="8"></textarea><div data-slot-actions></div><div data-slot-shares></div><div data-slot-versions></div></article><div class="field-row"><input data-task-title aria-label="新增事项名称"><input data-task-goal aria-label="事项目标"><button type="button" data-new-task>新增事项</button></div><ol class="cards" data-task-list></ol><div class="field-row"><input data-new-title aria-label="新作品标题"><select data-new-kind aria-label="新作品形式"><option value="text">普通文字</option><option value="plan">计划模板</option></select><textarea data-new-body aria-label="新作品正文"></textarea><button type="button" data-new-product>保存新作品</button></div>';
  const controls = container.querySelector<HTMLElement>('[data-fixture-controls]')!,
    counter = container.querySelector<HTMLElement>('[data-fixture-count]')!,
    announcement = container.querySelector<HTMLElement>('[data-fixture-announcement]')!;
  const q = (s: string) => container.querySelector<HTMLElement>(s)!;
  const nodes: Record<string, HTMLElement> = {
    title: q('#editor-title'),
    body: q('#editor-body'),
    purpose: q('[data-purpose]'),
    saveStatus: q('[data-save]'),
    actions: q('[data-slot-actions]'),
    sharing: q('[data-slot-shares]'),
    versions: q('[data-slot-versions]'),
    taskTitle: q('[data-task-title]'),
    taskGoal: q('[data-task-goal]'),
    newTask: q('[data-new-task]'),
    taskList: q('[data-task-list]'),
    newTitle: q('[data-new-title]'),
    newKind: q('[data-new-kind]'),
    newBody: q('[data-new-body]'),
    newProduct: q('[data-new-product]'),
  };
  if (new URLSearchParams(location.search).get('forms') === '1') {
    q('[data-task-title]').parentElement?.remove();
    q('[data-new-title]').parentElement?.remove();
    container.insertAdjacentHTML(
      'beforeend',
      '<form id="task-form" data-form="task" data-id="" class="stack"><label>事项名称<input name="title" aria-label="表单事项名称" required></label><label>补充<textarea name="note" aria-label="表单补充"></textarea></label><fieldset><legend>表单优先级</legend><label><input type="radio" name="priority" value="first">先做</label><label><input type="radio" name="priority" value="next" checked>随后</label><label><input type="radio" name="priority" value="later">暂放</label></fieldset><label>拆出新事<input name="split" aria-label="拆出新事"></label></form><button type="submit" form="task-form">确认事项表单</button><form id="artifact-form" data-form="artifact" class="stack"><label>作品名称<input name="title" aria-label="表单作品名称" required></label><fieldset><legend>用途单选组</legend><label><input type="radio" name="purpose" value="探索笔记" checked>探索笔记</label><label><input type="radio" name="purpose" value="试点决定">试点决定</label></fieldset><label>归属事项<select name="taskId" aria-label="表单归属事项" required></select></label></form><button type="submit" form="artifact-form">确认作品表单</button>',
    );
    nodes.taskForm = q('#task-form');
    nodes.productForm = q('#artifact-form');
  }
  function syncFormChoices() {
    const select = container.querySelector<HTMLSelectElement>('#artifact-form [name=taskId]');
    if (!select) return;
    const previous = select.value;
    select.replaceChildren(
      ...tasks.map((t) => {
        const o = doc.createElement('option');
        o.value = t.id;
        o.textContent = t.title;
        return o;
      }),
    );
    if (tasks.some((t) => t.id === previous)) select.value = previous;
  }
  let slot = mount({ host, nodes });
  const control = (label: string, action: () => void) => {
    const button = doc.createElement('button');
    button.type = 'button';
    button.className = 'btn quiet small';
    button.textContent = label;
    button.onclick = action;
    controls.append(button);
  };
  control('编辑首件事项', () => {
    const t = tasks[0],
      form = nodes.taskForm as HTMLFormElement;
    if (!t || !form) return;
    slot.destroy();
    form.dataset.id = t.id;
    form.dataset.revision = String(t.revision);
    (form.elements.namedItem('title') as HTMLInputElement).value = t.title;
    (form.elements.namedItem('note') as HTMLInputElement).value = t.goal ?? '';
    for (const radio of form.querySelectorAll<HTMLInputElement>('[name=priority]'))
      radio.checked = radio.value === ['first', 'next', 'later'][t.priority ?? 0];
    (form.elements.namedItem('split') as HTMLInputElement).value = '';
    slot = mount({ host, nodes });
  });
  control('English', () => {
    snapshot = { ...snapshot, uiLanguage: 'en' };
    emit();
  });
  control('中文', () => {
    snapshot = { ...snapshot, uiLanguage: 'zh' };
    emit();
  });
  control('远端保存新版本', () => {
    const p = products.find((p) => p.product_id === snapshot.currentProduct?.object_id)!;
    const next = {
      ...p,
      version: p.version + 1,
      title: 'Remote saved title',
      content: 'Remote saved content',
    };
    products = products.map((x) => (x === p ? next : x));
    history.push(structuredClone(next));
    advance();
    emit();
  });
  control('下次响应丢失', () => {
    loseNext = true;
    announcement.textContent = 'Fixture will save once, then return an unconfirmed result.';
  });
  control('卸载再挂载', () => {
    slot.destroy();
    slot = mount({ host, nodes });
  });
  control('检查夹具记录', () => {
    announcement.textContent = JSON.stringify({
      counts,
      versions: history.map((p) => ({
        id: p.product_id,
        version: p.version,
        content: p.content,
        purpose: p.purpose,
        task: p.task,
      })),
      shares: shares.map((s) => ({ version: s.product.version, revoked: !!s.revoked_at })),
      tasks: tasks.map((t) => ({
        id: t.id,
        title: t.title,
        order: t.order,
        status: t.status,
        priority: t.priority,
        revision: t.revision,
        parent: t.parent,
      })),
    });
  });
  emit();
  return () => slot.destroy();
}
