import type { V4HostAdapter, V4CommandResult, V4HostSnapshot } from '../../../v4-host';
import type {
  ObjectRef,
  ProductCreate,
  ProductEdit,
  WorkspaceProductRead,
  WorkspaceTask,
  ProductShare,
  VersionPoint,
  InvestigationPayload,
} from '../contract-types';

import { canonicalPurpose } from './form-values';
const object = (x: unknown): x is Record<string, any> =>
  !!x && typeof x === 'object' && !Array.isArray(x);
const integer = (x: unknown) => Number.isInteger(x) && Number(x) >= 0;
const point = (x: unknown): x is VersionPoint =>
  object(x) &&
  integer(x.business_seq) &&
  integer(x.workspace_revision) &&
  integer(x.storage_revision);
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
export const productRef = (p: WorkspaceProductRead): ObjectRef => ({
  session_id: p.session_id,
  kind: 'product',
  object_id: p.product_id,
  version: p.version,
});
export const taskRef = (t: WorkspaceTask): ObjectRef => ({
  session_id: t.session_id,
  kind: 'task',
  object_id: t.id,
  version: t.revision,
});
export const productInput = (p: WorkspaceProductRead): ProductCreate => ({
  kind: p.kind ?? 'text',
  title: p.title ?? '',
  content: p.content ?? '',
  purpose: canonicalPurpose(p.purpose ?? ''),
  task: p.task ?? null,
  structured_payload: structuredClone(p.structured_payload ?? null),
  evidence_refs: structuredClone(p.evidence_refs ?? []),
  legacy: structuredClone(p.legacy ?? null),
  source_return_id: p.source_return_id ?? null,
});
export type SlotDraft = {
  schema: 1;
  sessionId: string;
  productId: string;
  baseVersion: number;
  token: string;
  value: ProductCreate;
  status: 'dirty' | 'saved';
};
export type RequestPointer = {
  requestId: string;
  status: V4CommandResult['status'];
  sessionId: string;
  operation?: string;
  productId?: string;
  draftToken?: string;
};
type Page<T> = {
  items: T[];
  as_of: VersionPoint;
  next_cursor: number | null;
  shares?: ProductShare[];
  sharing_complete?: boolean;
};
export type SlotState = {
  tasks: WorkspaceTask[];
  products: WorkspaceProductRead[];
  shares: ProductShare[];
  sharingComplete: boolean;
  asOf: VersionPoint | null;
  loading: boolean;
  error: string;
  notice: string;
  receipt?: RequestPointer;
};

/** Only the owned DTO or the two frozen Gateway read shells are accepted.
 * No raw transport, credentials, Command construction or second journal. */
export function readPage<T>(
  raw: unknown,
  sessionId: string,
  kind: 'task' | 'product' | 'share',
): Page<T> {
  let v = raw;
  if (object(v) && v.schema_version === 2 && object(v.result)) v = v.result;
  if (object(v) && v.schema_version === 2 && object(v.result)) v = v.result;
  if (
    !object(v) ||
    !Array.isArray(v.items) ||
    !point(v.as_of) ||
    !(v.next_cursor == null || integer(v.next_cursor))
  )
    throw Error('invalid_workspace_page');
  for (const row of v.items) {
    if (!object(row) || row.session_id !== sessionId) throw Error('invalid_workspace_identity');
    if (
      kind === 'product' &&
      (!(typeof row.product_id === 'string') ||
        !integer(row.version) ||
        row.version < 1 ||
        typeof row.title !== 'string' ||
        typeof row.content !== 'string')
    )
      throw Error('invalid_product');
    if (
      kind === 'task' &&
      (typeof row.id !== 'string' ||
        !integer(row.revision) ||
        row.revision < 1 ||
        typeof row.title !== 'string')
    )
      throw Error('invalid_task');
    if (
      kind === 'share' &&
      (typeof row.id !== 'string' ||
        !integer(row.version) ||
        row.version < 1 ||
        !object(row.product) ||
        row.product.session_id !== sessionId ||
        !integer(row.product.version) ||
        row.product.version < 1)
    )
      throw Error('invalid_share');
  }
  if (v.shares !== undefined) {
    if (!Array.isArray(v.shares) || typeof v.sharing_complete !== 'boolean')
      throw Error('invalid_share_projection');
    readPage({ items: v.shares, as_of: v.as_of, next_cursor: null }, sessionId, 'share');
    if (v.sharing_complete === false && v.items.some((p: any) => p.visibility === 'private'))
      throw Error('incomplete_private_projection');
  }
  return { ...v, next_cursor: v.next_cursor ?? null } as Page<T>;
}
function mutationResult(raw: unknown, pointer: RequestPointer): Record<string, any> {
  if (!object(raw)) throw Error('unconfirmed_workspace_result');
  if (raw.read_only === true) {
    if (
      raw.session_id !== pointer.sessionId ||
      raw.request_id !== pointer.requestId ||
      raw.operation !== pointer.operation ||
      raw.status !== 'completed' ||
      !object(raw.response)
    )
      throw Error('wrong_recovered_result');
    raw = raw.response;
  }
  if (!object(raw)) throw Error('unconfirmed_workspace_result');
  if (object(raw.result) && point(raw.result.as_of)) return raw.result;
  if (point(raw.as_of)) return raw;
  throw Error('unconfirmed_workspace_result');
}

export class WorkspaceSlotController {
  state: SlotState = {
    tasks: [],
    products: [],
    shares: [],
    sharingComplete: false,
    asOf: null,
    loading: false,
    error: '',
    notice: '',
  };
  private epoch = 0;
  private disposed = false;
  private inFlight = false;
  private boundSession: string | null = null;
  private drafts = new Map<string, SlotDraft>();
  private writes: Promise<void> = Promise.resolve();
  constructor(
    readonly host: V4HostAdapter,
    private changed: () => void = () => {},
  ) {}
  private session() {
    const s = this.host.snapshot().session;
    if (!s || s.protocol !== 2) throw Error('v2_session_required');
    return s.sessionId;
  }
  private key(id: string, sid = this.session()) {
    return sid + ':product:' + id;
  }
  private receiptKey(sid = this.session()) {
    return sid + ':request-pointer';
  }
  private emit() {
    if (!this.disposed) this.changed();
  }
  snapshot() {
    return this.host.snapshot();
  }
  selected() {
    const ref = this.snapshot().currentProduct;
    return (
      ref &&
      this.state.products.find(
        (p) => p.product_id === ref.object_id && p.session_id === ref.session_id,
      )
    );
  }
  draft(p = this.selected()): SlotDraft | undefined {
    if (!p) return;
    const local = this.drafts.get(this.key(p.product_id, p.session_id));
    const stored = this.host.draft<SlotDraft>('workspace', this.key(p.product_id, p.session_id));
    const d = local ?? stored;
    return d?.schema === 1 &&
      d.status === 'dirty' &&
      d.sessionId === p.session_id &&
      d.productId === p.product_id
      ? d
      : undefined;
  }
  conflict(p = this.selected()) {
    return !!p && !!this.draft(p) && this.draft(p)!.baseVersion !== p.version;
  }
  can(operation: string) {
    const s = this.snapshot();
    return (
      s.session?.protocol === 2 &&
      s.state === 'active' &&
      !s.storageError &&
      s.available[operation] === true
    );
  }
  blocked() {
    const s = this.snapshot(),
      r = this.state.receipt;
    return (
      this.inFlight ||
      s.busy ||
      s.storageError ||
      (!!r && ['pending', 'unconfirmed', 'needs_context'].includes(r.status))
    );
  }
  private persist(key: string, value: SlotDraft) {
    this.drafts.set(key, value);
    this.emit();
    const write = this.writes
      .then(() => this.host.keepDraft('workspace', key, structuredClone(value)))
      .then(() => {
        if (value.status === 'saved' && this.drafts.get(key)?.token === value.token)
          this.drafts.delete(key);
      });
    this.writes = write.catch((error) => {
      this.state.error = 'draft_storage_failed';
      this.emit();
      throw error;
    });
    void this.writes.catch(() => {});
    return write;
  }
  async edit(patch: Partial<ProductCreate>) {
    const p = this.selected();
    if (!p || p.removed_at || !this.can('work_products.versions.create'))
      throw Error('editing_unavailable');
    const prior = this.draft(p);
    const value = { ...(prior?.value ?? productInput(p)), ...structuredClone(patch) };
    // Editing text never changes an existing kind or clears unrelated structured data.
    value.kind = p.kind ?? 'text';
    if (value.purpose !== undefined) value.purpose = canonicalPurpose(value.purpose);
    await this.persist(this.key(p.product_id), {
      schema: 1,
      sessionId: p.session_id,
      productId: p.product_id,
      baseVersion: prior?.baseVersion ?? p.version,
      token: crypto.randomUUID(),
      value,
      status: 'dirty',
    });
  }
  async editInvestigation(field: 'question' | 'review_focus' | 'review_note', value: string) {
    const p = this.selected();
    if (!p || p.kind !== 'investigation') throw Error('not_investigation');
    const payload = structuredClone(
      (this.draft(p)?.value.structured_payload ?? p.structured_payload) as InvestigationPayload,
    );
    if (!payload || payload.type !== 'investigation') throw Error('missing_investigation');
    if (field === 'review_focus' && !['index', 'source', 'uncertain', 'other'].includes(value))
      throw Error('invalid_focus');
    await this.edit({ structured_payload: { ...payload, [field]: value } });
  }
  async editBlock(id: string, text: string) {
    const p = this.selected();
    if (!p || p.kind !== 'investigation') throw Error('not_investigation');
    const payload = structuredClone(
      (this.draft(p)?.value.structured_payload ?? p.structured_payload) as InvestigationPayload,
    );
    if (!payload?.blocks?.some((b) => b.id === id)) throw Error('unknown_investigation_block');
    // Block and reference identities are preserved. No fabricated test outcome.
    await this.edit({
      structured_payload: {
        ...payload,
        blocks: payload.blocks.map((b) => (b.id === id ? { ...b, text } : b)),
      },
    });
  }
  async flush() {
    await this.writes;
    await this.host.flushDrafts();
  }
  private async pages<T>(
    operation: string,
    input: Record<string, unknown>,
    kind: 'task' | 'product' | 'share',
    sid: string,
  ) {
    const items: T[] = [],
      shares: ProductShare[] = [];
    let cursor = 0,
      at: VersionPoint | undefined,
      complete: boolean | undefined;
    const seen = new Map<string, string>(),
      shareSeen = new Map<string, string>();
    for (;;) {
      const page = readPage<T>(
        await this.host.query(operation, { ...input, cursor, limit: 100 }),
        sid,
        kind,
      );
      if (at && !same(at, page.as_of)) throw Error('workspace_changed_during_read');
      at = page.as_of;
      for (const item of page.items) {
        const x = item as any,
          key = (x.product_id ?? x.id) + ':' + (x.version ?? x.revision),
          serialized = JSON.stringify(x);
        if (seen.has(key) && seen.get(key) !== serialized) throw Error('inconsistent_page');
        if (!seen.has(key)) {
          seen.set(key, serialized);
          items.push(item);
        }
      }
      if (page.sharing_complete !== undefined) {
        if (complete !== undefined && complete !== page.sharing_complete)
          throw Error('inconsistent_share_scope');
        complete = page.sharing_complete;
      }
      for (const share of page.shares ?? []) {
        const serialized = JSON.stringify(share);
        if (shareSeen.has(share.id) && shareSeen.get(share.id) !== serialized)
          throw Error('inconsistent_share');
        if (!shareSeen.has(share.id)) {
          shareSeen.set(share.id, serialized);
          shares.push(share);
        }
      }
      if (page.next_cursor === null)
        return { items, shares, sharing_complete: complete, as_of: at };
      if (page.next_cursor <= cursor) throw Error('invalid_cursor');
      cursor = page.next_cursor;
    }
  }
  async refresh() {
    const sid = this.session(),
      epoch = ++this.epoch;
    this.state.loading = true;
    this.state.error = '';
    this.emit();
    try {
      const [tasks, products] = await Promise.all([
        this.pages<WorkspaceTask>('work_items.list', {}, 'task', sid),
        this.pages<WorkspaceProductRead>('work_products.list', {}, 'product', sid),
      ]);
      if (this.disposed || epoch !== this.epoch || this.snapshot().session?.sessionId !== sid)
        return;
      if (!same(tasks.as_of, products.as_of)) throw Error('workspace_changed_during_read');
      if (
        products.shares.some(
          (s) => !products.items.some((p) => p.product_id === s.product.object_id),
        )
      )
        throw Error('invalid_share_projection');
      this.state = {
        ...this.state,
        tasks: tasks.items,
        products: products.items,
        shares: products.shares,
        sharingComplete: products.sharing_complete === true,
        asOf: products.as_of,
        receipt: this.host.draft<RequestPointer>('workspace', this.receiptKey(sid)),
      };
    } catch (error) {
      if (epoch === this.epoch) {
        this.state.error = error instanceof Error ? error.message : 'workspace_read_failed';
        throw error;
      }
    } finally {
      if (epoch === this.epoch) {
        this.state.loading = false;
        this.emit();
      }
    }
  }
  async versions(id: string) {
    const sid = this.session(),
      page = await this.pages<WorkspaceProductRead>(
        'work_products.versions.list',
        { product_id: id },
        'product',
        sid,
      );
    if (page.items.some((p) => p.product_id !== id)) throw Error('wrong_product_history');
    if (this.snapshot().session?.sessionId !== sid) throw Error('session_changed');
    return page.items.sort((a, b) => b.version - a.version);
  }
  private async storePointer(pointer: RequestPointer) {
    await this.host.keepDraft('workspace', this.receiptKey(pointer.sessionId), pointer);
    if (this.snapshot().session?.sessionId === pointer.sessionId) {
      this.state.receipt = pointer;
      this.emit();
    }
  }
  private async confirm(result: V4CommandResult, pointer: RequestPointer) {
    await this.storePointer({
      ...pointer,
      status: result.status === 'confirmed' ? 'unconfirmed' : result.status,
    });
    if (result.status !== 'confirmed') return;
    const body = mutationResult(result.result, pointer),
      p = body.object;
    if (pointer.productId && pointer.draftToken) {
      const key = this.key(pointer.productId, pointer.sessionId),
        draft = this.drafts.get(key) ?? this.host.draft<SlotDraft>('workspace', key);
      if (
        !object(p) ||
        p.session_id !== pointer.sessionId ||
        p.product_id !== pointer.productId ||
        !integer(p.version)
      )
        throw Error('unconfirmed_saved_product');
      if (draft?.token === pointer.draftToken) {
        if (
          p.version <= draft.baseVersion ||
          !same(productInput(p as WorkspaceProductRead), {
            ...draft.value,
            ...(draft.value.purpose === undefined
              ? {}
              : { purpose: canonicalPurpose(draft.value.purpose) }),
          })
        )
          throw Error('unconfirmed_saved_content');
        await this.persist(key, { ...draft, baseVersion: p.version, status: 'saved' });
      }
    }
    this.state.error = '';
    await this.storePointer({ ...pointer, status: 'confirmed' });
    if (this.snapshot().session?.sessionId !== pointer.sessionId) return;
    await this.refresh();
  }
  selectConfirmedProduct(result: V4CommandResult) {
    const pointer = this.state.receipt;
    if (
      this.disposed ||
      result.status !== 'confirmed' ||
      !pointer ||
      pointer.requestId !== result.requestId ||
      pointer.sessionId !== this.snapshot().session?.sessionId
    )
      return;
    const product = mutationResult(result.result, pointer).object;
    if (
      object(product) &&
      product.session_id === pointer.sessionId &&
      typeof product.product_id === 'string' &&
      integer(product.version)
    )
      this.host.selectProduct(productRef(product as WorkspaceProductRead));
  }
  async command(operation: string, input: Record<string, unknown>, draft?: SlotDraft) {
    if (!this.can(operation) || this.blocked()) throw Error('action_unavailable');
    const sid = this.session();
    this.inFlight = true;
    this.state.error = '';
    this.emit();
    try {
      await this.flush();
      if (this.session() !== sid) throw Error('session_changed');
      const result = await this.host.command(operation, input);
      if (!result.requestId) throw Error('missing_host_request');
      const pointer: RequestPointer = {
        requestId: result.requestId,
        status: result.status,
        sessionId: sid,
        operation,
        ...(draft ? { productId: draft.productId, draftToken: draft.token } : {}),
      };
      await this.confirm(result, pointer);
      return result;
    } catch (error) {
      this.state.error = error instanceof Error ? error.message : 'workspace_action_failed';
      throw error;
    } finally {
      this.inFlight = false;
      this.emit();
    }
  }
  async save(reviewed?: { head: number; token: string }) {
    const p = this.selected();
    if (!p || p.removed_at) throw Error('editing_unavailable');
    let d = this.draft(p);
    if (!d) return;
    if (reviewed) {
      if (reviewed.head !== p.version || reviewed.token !== d.token)
        throw Error('comparison_changed');
      await this.refresh();
      const latest = this.selected();
      if (
        !latest ||
        latest.version !== reviewed.head ||
        this.draft(latest)?.token !== reviewed.token
      )
        throw Error('comparison_changed');
      d = { ...d, baseVersion: latest.version };
      await this.persist(this.key(p.product_id), d);
    }
    if (d.baseVersion !== this.selected()?.version) throw Error('draft_conflict');
    return this.command(
      'work_products.versions.create',
      {
        ...d.value,
        ...(d.value.purpose === undefined ? {} : { purpose: canonicalPurpose(d.value.purpose) }),
        product_id: p.product_id,
        expected_head: d.baseVersion,
        removed: false,
      } as ProductEdit,
      d,
    );
  }
  async create(input: ProductCreate) {
    return this.command('work_products.create', {
      ...input,
      ...(input.purpose === undefined ? {} : { purpose: canonicalPurpose(input.purpose) }),
    });
  }
  async saveCopy() {
    const p = this.selected(),
      d = this.draft(p);
    if (!p || !d) throw Error('no_draft');
    return this.create({ ...d.value, legacy: null, source_return_id: null });
  }
  share(role: string, question: string) {
    const p = this.selected();
    if (!p || p.removed_at || this.draft(p)) throw Error('save_before_sharing');
    return this.command('work_products.shares.create', {
      product_id: p.product_id,
      product_version: p.version,
      recipient_role: role,
      question,
      purpose: 'discussion',
    });
  }
  revoke(share: ProductShare) {
    return this.command('work_products.shares.change', {
      product_id: share.product.object_id,
      share_id: share.id,
      expected_revision: share.version,
      operation: 'revoke',
    });
  }
  remove(removed: boolean) {
    const p = this.selected();
    if (!p || this.draft(p)) throw Error('save_before_removing');
    return this.command('work_products.versions.create', {
      ...productInput(p),
      product_id: p.product_id,
      expected_head: p.version,
      removed,
    });
  }
  async recover(retry = false) {
    const p = this.state.receipt;
    if (!p || p.sessionId !== this.session() || this.inFlight) throw Error('no_host_request');
    this.inFlight = true;
    this.emit();
    try {
      const result = await (retry ? this.host.retry(p.requestId) : this.host.recover(p.requestId));
      if (!retry && result.requestId !== p.requestId) throw Error('wrong_recovered_request');
      await this.confirm(result, { ...p, requestId: result.requestId });
      return result;
    } finally {
      this.inFlight = false;
      this.emit();
    }
  }
  createTask(title: string, goal = '', priority = 0) {
    if (!title.trim()) throw Error('task_title_required');
    return this.command('work_items.create', { title: title.trim(), goal, priority });
  }
  saveTaskForm(input: {
    id: string;
    title: string;
    goal: string;
    priority: number;
    baseRevision?: number;
    split: string;
  }) {
    if (!input.id) return this.createTask(input.title, input.goal, input.priority);
    const task = this.state.tasks.find((t) => t.id === input.id);
    if (!input.baseRevision) throw Error('task_revision_missing');
    if (!task || task.revision !== input.baseRevision) throw Error('task_conflict');
    const update = {
      item_id: task.id,
      expected_revision: input.baseRevision,
      title: input.title.trim(),
      goal: input.goal,
      priority: input.priority,
    };
    if (!update.title) throw Error('task_title_required');
    if (input.split.trim())
      return this.command('work_items.batch', {
        updates: [update],
        creates: [{ title: input.split.trim(), parent: taskRef(task), priority: input.priority }],
      });
    return this.command('work_items.update', update);
  }
  patchTask(task: WorkspaceTask, patch: Partial<WorkspaceTask>) {
    return this.command('work_items.update', {
      item_id: task.id,
      expected_revision: task.revision,
      ...patch,
    });
  }
  moveTask(task: WorkspaceTask, direction: -1 | 1) {
    const siblings = this.state.tasks
      .filter((t) => t.status !== 'removed' && t.priority === task.priority)
      .sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || a.id.localeCompare(b.id));
    const index = siblings.findIndex((t) => t.id === task.id),
      other = index + direction;
    if (index < 0 || other < 0 || other >= siblings.length) return Promise.resolve();
    [siblings[index], siblings[other]] = [siblings[other], siblings[index]];
    return this.command('work_items.batch', {
      updates: siblings.map((t, order) => ({
        item_id: t.id,
        expected_revision: t.revision,
        order,
      })),
    });
  }
  update(snapshot: Readonly<V4HostSnapshot>) {
    const sid = snapshot.session?.protocol === 2 ? snapshot.session.sessionId : null;
    if (sid !== this.boundSession || snapshot.session?.protocol !== 2) {
      this.boundSession = sid;
      this.epoch++;
      this.state = {
        tasks: [],
        products: [],
        shares: [],
        sharingComplete: false,
        asOf: null,
        loading: false,
        error: '',
        notice: '',
      };
    }
    this.emit();
  }
  destroy() {
    this.disposed = true;
    this.epoch++;
  }
}
