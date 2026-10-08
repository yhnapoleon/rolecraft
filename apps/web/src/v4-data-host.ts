import { T } from './app/i18n';
import { ApiError } from './api';
import { createGatewayTransport, type GatewayCredentials, type GatewayTransport } from './gateway-transport';
import type { Command, ObjectRef, EvidenceRefV2, VersionPoint } from './contracts-v2';
import type { V4CommandResult, V4HostAdapter, V4HostSnapshot, V4SessionBinding, V4SlotId, WorkLanguage } from './v4-host';
import { readRoute, commandRoute, type Route } from './v4-operations';

type Input = Readonly<Record<string, unknown>>;
type V2Binding = Extract<V4SessionBinding, { protocol: 2 }>;
export type JournalEntry = {
  command: Command; route: Route; input: Input; operation: string; createdAt: string;
  outcome: V4CommandResult; previousRequestId?: string;
  /** Token-free record of an auth control-plane request; recovered by replaying the same command. */
  controlPlane?: true;
};
export interface V4LocalRecord {
  schema: 2; sessionId: string;
  requests: Record<string, JournalEntry>;
  drafts: Partial<Record<V4SlotId, Record<string, unknown>>>;
  currentTask: ObjectRef | null; currentProduct: ObjectRef | null;
}
export interface V4HostPorts {
  /** Bound to LiveWorkbench's credential repository, never exposed to a slot. */
  credentials(): GatewayCredentials;
  binding: V2Binding;
  storage: Pick<Storage, 'getItem' | 'setItem'>;
  uiLanguage(): WorkLanguage;
  openReference(ref: ObjectRef | EvidenceRefV2): Promise<void>;
  chooseEvidence(): Promise<readonly EvidenceRefV2[]>;
  announce(message: string, kind?: 'status' | 'error'): void;
  fetcher?: typeof fetch;
  didRead?(operation: string, value: any, input: Input): void;
  didSelect?(kind: 'currentTask' | 'currentProduct', ref: ObjectRef): void;
  /** Native Web Lock in production, injectable for deterministic tests. */
  exclusive?<T>(name: string, action: () => Promise<T>): Promise<T>;
}
const obj = (value: unknown): value is Record<string, any> => !!value && typeof value === 'object' && !Array.isArray(value);
const point = (value: unknown): value is VersionPoint => obj(value) && ['business_seq', 'workspace_revision', 'storage_revision'].every(k => Number.isSafeInteger(value[k]) && value[k] >= 0);
const unconfirmed = () => new ApiError('The result is unconfirmed; recover the original request.', 0, 'response_unconfirmed');
const copy = <T>(value: T): T => structuredClone(value);

/** The sole v2 command/draft journal used by every native v4 slot.
 * Construction, refresh and recovery are read-only on the server. */
export class V4DataHost implements V4HostAdapter {
  private readonly raw: GatewayTransport;
  private readonly key: string;
  private readonly listeners = new Set<() => void>();
  private busy = false;
  private storageError = false;
  private local: V4LocalRecord;
  private context: any;
  private contextKey = '';
  private readonly unsavedDrafts = new Map<string, { slot: V4SlotId; key: string; value: unknown }>();
  // The secret of the delegation issued on this page lives only in memory, for a one-time
  // connection-config download. It never enters the request journal, drafts or storage.
  private issued: { delegationId: string; token: string; label: string; issuedAt: string } | null = null;
  constructor(private readonly ports: V4HostPorts) {
    this.key = 'rolecraft.v4.session.' + ports.binding.sessionId;
    this.raw = createGatewayTransport(() => {
      const credentials = ports.credentials();
      if (credentials.sessionId !== ports.binding.sessionId) throw new ApiError('Session changed', 409, 'session_binding_mismatch');
      return credentials;
    }, ports.fetcher);
    this.local = { schema: 2, sessionId: ports.binding.sessionId, requests: {}, drafts: {}, currentTask: null, currentProduct: null };
    this.reload();
  }
  private path(suffix: string) { return '/sessions/' + encodeURIComponent(this.ports.binding.sessionId) + suffix; }
  private reload() {
    try {
      const saved = this.ports.storage.getItem(this.key);
      if (saved) {
        const value = JSON.parse(saved);
        if (value.schema !== 2 || value.sessionId !== this.ports.binding.sessionId || !obj(value.requests) || !obj(value.drafts)) throw Error('Invalid host record');
        for (const [id, entry] of Object.entries(value.requests) as [string, JournalEntry][]) {
          if (entry.command?.request_id !== id || !obj(entry.input) || !obj(entry.outcome) || entry.outcome.requestId !== id) throw Error('Invalid journal');
        }
        this.local = value;
      }
      for (const { slot, key, value } of this.unsavedDrafts.values()) this.local.drafts[slot] = { ...this.local.drafts[slot], [key]: copy(value) };
      this.storageError = false;
    } catch { this.storageError = true; }
  }
  private save() {
    try { this.ports.storage.setItem(this.key, JSON.stringify(this.local)); this.storageError = false; }
    catch { this.storageError = true; this.emit(); throw new ApiError('Browser storage is unavailable; keep this page open.', 0, 'storage_unavailable'); }
  }
  private exclusive<T>(action: () => Promise<T>): Promise<T> {
    const name = this.key;
    if (this.ports.exclusive) return this.ports.exclusive(name, action);
    if (!globalThis.navigator?.locks) return Promise.reject(new ApiError('Browser coordination is unavailable', 503, 'storage_lock_unavailable'));
    return navigator.locks.request(name, action);
  }
  private emit() { for (const listener of this.listeners) listener(); }
  subscribe(changed: () => void) { this.listeners.add(changed); return () => { this.listeners.delete(changed); }; }
  snapshot(): Readonly<V4HostSnapshot> {
    return copy({ session: this.ports.binding, uiLanguage: this.ports.uiLanguage(),
      state: this.context?.read_only && this.context?.state?.status !== 'submitted' ? 'paused' : this.context?.state?.status ?? 'unavailable', asOf: this.context?.as_of ?? null,
      currentTask: this.local.currentTask, currentProduct: this.local.currentProduct,
      busy: this.busy, storageError: this.storageError,
      available: { ...this.context?.available, 'delegations.create': this.context?.available?.['delegations.create'] === true,
        'delegations.revoke': this.context?.available?.['delegations.revoke'] === true, 'delegations.list': this.context?.available?.['delegations.create'] === true },
      semantic: this.context?.semantic ?? { roles: 'unavailable', feedback: 'unavailable', assistant: 'unavailable' },
    });
  }
  async query(operation: string, input: Input = {}): Promise<unknown> {
    if (input.session_id != null && input.session_id !== this.ports.binding.sessionId) throw new ApiError('Reference belongs to another session', 404, 'session_binding_mismatch');
    if (operation === 'workspace_imports') {
      if (input.mode !== 'preview') throw new ApiError('Only an import preview is a query', 400, 'invalid_read');
      const state: any = await this.query('session.read');
      if (!point(state)) throw unconfirmed();
      const preview: any = await this.raw(this.path('/workspace-imports'), { schema_version: 2, request_id: crypto.randomUUID(),
        expected_version: state.business_seq, expected_workspace_revision: state.workspace_revision, operation: 'workspace_imports', payload: copy(input) });
      if (preview.result?.mode !== 'preview' || preview.result?.applied !== false || preview.result?.package_id !== input.package_id || !point(preview.result?.as_of)) throw unconfirmed();
      return preview.result;
    }
    const result: any = await this.raw(this.path(readRoute(operation, input)));
    if (operation === 'delegations.list' && Array.isArray(result?.result?.result?.items)) {
      // Grants carry no label; show the name the person gave on this browser.
      const labels = this.agentLabels();
      for (const row of result.result.result.items) if (row && typeof row.id === 'string' && labels[row.id]) row.agent_label = labels[row.id];
    }
    if (operation === 'session.read') return result.state;
    if (operation === 'objects.read') return result;
    if (operation === 'observation' && obj(result.result) && Array.isArray(result.result.visible_sources)) return result.result;
    if (!obj(result.result) || !obj(result.result.result)) throw unconfirmed();
    const value = result.result.result;
    if (operation === 'workbench.read') {
      if (!point(value.as_of) || value.session?.sessionId !== this.ports.binding.sessionId ||
          value.session.workLanguage !== this.ports.binding.workLanguage || value.session.scenarioHash !== this.ports.binding.scenarioHash ||
          !['active', 'paused', 'submitted'].includes(value.state?.status) || !obj(value.available) || !obj(value.semantic)) throw unconfirmed();
      // The workbench polls this read. Notify slots only when it changed, so an idle poll never rebuilds
      // a control the person is pressing or has focused.
      const key = JSON.stringify(value);
      if (key !== this.contextKey) { this.contextKey = key; this.context = copy(value); this.emit(); }
    }
    this.ports.didRead?.(operation, copy(value), input);
    return value;
  }
  async command(operation: string, input: Input): Promise<V4CommandResult> {
    // Service-mode control plane: the create response carries a private secret. Only a token-free
    // request record is journaled, and only the token-free outcome is returned to the slot.
    if (operation === 'delegations.create' || operation === 'delegations.revoke') return this.exclusive(() => this.delegate(operation, copy(input)));
    return this.exclusive(() => this.send(operation, copy(input)));
  }
  /**
   * Auth control plane (service mode). The server does not journal these requests, but issuance is
   * deterministic per request_id: replaying the identical command returns the same grant and never
   * creates a second one. The host therefore keeps a token-free journal entry and recovers by replaying
   * that exact command. The secret is returned only to memory, never to the journal, drafts or storage.
   */
  private async delegate(operation: string, input: Input, existingRequestId?: string): Promise<V4CommandResult> {
    // Never send a secret-bearing request unless the server advertises this control-plane operation.
    if (this.context?.available?.[operation] !== true) throw new ApiError('Agent control plane is not available on this server', 503, 'delegation_host_not_ready');
    this.reload();
    if (this.storageError) throw new ApiError('Keep the original browser data', 0, 'storage_unavailable');
    if (this.context?.read_only) throw new ApiError(T('这个练习目前只读。', 'This practice is read-only.'), 409, 'session_read_only');
    if (!existingRequestId && Object.values(this.local.requests).some(e => e.outcome.status === 'unconfirmed')) throw new ApiError('Recover the original request first', 409, 'request_unconfirmed');
    this.busy = true; this.emit();
    try {
      // reload() replaces the journal objects. Resolve the original request from that
      // current journal, so its recovered outcome is the one save() persists.
      let entry = existingRequestId ? this.local.requests[existingRequestId] : undefined;
      if (existingRequestId && !entry) throw new ApiError('Unknown request', 404, 'request_not_found');
      if (!entry) {
        const route = commandRoute(operation, input);
        let state: any;
        // Nothing has been sent yet: a failed pre-read is a definitive "not sent", never an unknown outcome.
        try { state = await this.query('session.read'); } catch { state = null; }
        if (state?.session_id !== this.ports.binding.sessionId || !point(state)) {
          return { requestId: crypto.randomUUID(), status: 'failed', result: { code: 'not_sent', definitive: true } } as V4CommandResult;
        }
        const requestId = crypto.randomUUID();
        const command: Command = { schema_version: 2, request_id: requestId, expected_version: state.business_seq,
          expected_workspace_revision: state.workspace_revision, operation: route.action, payload: copy(input) };
        entry = { command, route, input, operation, createdAt: new Date().toISOString(), controlPlane: true,
          outcome: { requestId, status: 'unconfirmed', result: null } };
        this.local.requests[requestId] = entry;
        try { this.save(); } catch (error) { delete this.local.requests[requestId]; throw error; }
      }
      const requestId = entry.command.request_id;
      let response: any;
      try { response = await this.raw(this.path(entry.route.path), entry.command, entry.route.method); }
      catch (error) {
        // A 4xx is a rejection before any change; anything else may follow a committed grant.
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
          entry.outcome = { requestId, status: 'failed', result: { code: error.code, message: error.message, definitive: true } };
        } else {
          this.ports.announce(T('授权请求结果未确认；可用“核对原请求结果”按原请求号核对，不会重复签发。', 'The access request is unconfirmed. Check the original request; it is replayed with the same ID and never issues a second grant.'), 'error');
        }
        this.save(); return copy(entry.outcome);
      }
      // Gateway envelope: { result: { schema_version, result: { delegation, token } } }.
      const result: any = copy(obj(response?.result?.result) ? response.result.result : response?.result ?? {});
      if (operation === 'delegations.create') {
        const token = result.token; delete result.token;
        if (typeof token === 'string' && typeof result.delegation?.id === 'string') {
          this.issued = { delegationId: result.delegation.id, token, label: String(entry.input.agent_label ?? ''), issuedAt: new Date().toISOString() };
          this.rememberAgentLabel(result.delegation.id, String(entry.input.agent_label ?? ''));
          if (typeof document !== 'undefined') document.dispatchEvent(new CustomEvent('rolecraft:delegation-issued', { detail: { delegationId: result.delegation.id } }));
        }
      } else if (this.issued?.delegationId === entry.input.delegation_id) { this.issued = null; if (typeof document !== 'undefined') document.dispatchEvent(new CustomEvent('rolecraft:delegation-issued', { detail: null })); }
      entry.outcome = { requestId, status: 'confirmed', result };
      this.save();
      return copy(entry.outcome);
    } finally { this.busy = false; this.emit(); }
  }
  /** One-time private connection config for the delegation issued on this page. */
  private agentLabels(): Record<string, string> {
    try { const value = JSON.parse(this.ports.storage.getItem('rolecraft.v4.agent-labels.' + this.ports.binding.sessionId) ?? '{}'); return value && typeof value === 'object' ? value : {}; }
    catch { return {}; }
  }
  private rememberAgentLabel(id: string, label: string) {
    if (!label) return;
    try { this.ports.storage.setItem('rolecraft.v4.agent-labels.' + this.ports.binding.sessionId, JSON.stringify({ ...this.agentLabels(), [id]: label.slice(0, 64) })); }
    catch { /* A label is a convenience; the grant itself is already confirmed by the server. */ }
  }
  issuedDelegation() { return this.issued ? { delegationId: this.issued.delegationId, label: this.issued.label, issuedAt: this.issued.issuedAt } : null; }
  takeConnectionConfig(apiUrl: string) {
    if (!this.issued) return null;
    const config = { api_url: apiUrl, session_id: this.ports.binding.sessionId, token: this.issued.token };
    this.issued = null; if (typeof document !== 'undefined') document.dispatchEvent(new CustomEvent('rolecraft:delegation-issued', { detail: null }));
    return config;
  }
  private async send(operation: string, input: Input, previousRequestId?: string): Promise<V4CommandResult> {
    this.reload();
    if (this.storageError) throw new ApiError('Keep the original browser data', 0, 'storage_unavailable');
    // A model job may run independently, but an ambiguous write must be resolved first.
    if (Object.values(this.local.requests).some(e => e.outcome.status === 'unconfirmed')) throw new ApiError('Recover the original request first', 409, 'request_unconfirmed');
    for (const key of ['token', 'request_id', 'expected_version', 'expected_workspace_revision', 'command']) {
      if (Object.hasOwn(input, key)) throw new ApiError('Only business input is accepted', 400, 'invalid_command_input');
    }
    if (this.context?.read_only) throw new ApiError(T('这个练习使用旧版场景，目前只读。你可以查看原记录，或开始新的练习。', 'This practice uses an earlier scenario and is read-only. View its records or start a new practice.'),409,'scenario_read_only');
    const route = commandRoute(operation, input);
    this.busy = true; this.emit();
    try {
      const state: any = await this.query('session.read');
      if (state?.session_id !== this.ports.binding.sessionId || !point(state)) throw unconfirmed();
      const requestId = crypto.randomUUID();
      const command: Command = { schema_version: 2, request_id: requestId, expected_version: state.business_seq,
        expected_workspace_revision: state.workspace_revision, operation: route.action, payload: copy(input) };
      const entry: JournalEntry = { command, route, input, operation, createdAt: new Date().toISOString(), previousRequestId,
        outcome: { requestId, status: 'unconfirmed', result: null } };
      this.local.requests[requestId] = entry;
      try { this.save(); } // No POST is allowed unless the exact envelope is durable.
      catch (error) { delete this.local.requests[requestId]; throw error; }
      try {
        const response: any = await this.raw(this.path(route.path), command, route.method);
        if (response.boundary?.request_id !== requestId || response.state?.session_id !== this.ports.binding.sessionId || !point(response.state)) throw unconfirmed();
        entry.outcome = { requestId, status: response.result?.feedback_status === 'queued' || response.result?.status === 'queued' || response.jobs?.length ? 'pending' : 'confirmed', result: response.result };
        this.save();
      } catch (error) {
        // 5xx, network loss and invalid bodies can follow a committed write.
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
          entry.outcome = { requestId, status: 'failed', result: { code: error.code, message: error.message } };
          this.save();
        }
        // The caller always receives the journal ID, including ambiguous responses.
        this.ports.announce(error instanceof Error ? error.message : 'Request unconfirmed', 'error');
      }
      if (entry.outcome.status !== 'unconfirmed') {
        try { await this.query('workbench.read'); } catch { /* The committed outcome remains authoritative. */ }
      }
      this.emit();
      return copy(entry.outcome);
    } finally { this.busy = false; this.emit(); }
  }
  async reflectSelection(task: ObjectRef | null, product: ObjectRef | null) {
    if (task) this.checkRef(task); if (product) this.checkRef(product);
    await this.exclusive(async () => {
      this.reload();
      if (this.storageError) throw new ApiError('Keep the original browser data', 0, 'storage_unavailable');
      if (JSON.stringify([this.local.currentTask,this.local.currentProduct]) === JSON.stringify([task,product])) return;
      this.local.currentTask = copy(task); this.local.currentProduct = copy(product); this.save(); this.emit();
    });
  }
  hasUnpersistedDrafts() { return this.storageError || this.unsavedDrafts.size > 0; }
  async ensureFeedbackPointer() {
    if(this.local.drafts.feedback?.['last-request']!==undefined)return;
    const last=Object.values(this.local.requests).filter(r=>['submissions.create','reviews.create','feedback.create'].includes(r.operation)).sort((a,b)=>a.createdAt.localeCompare(b.createdAt)).at(-1);
    if(last)await this.keepDraft('feedback','last-request',{requestId:last.outcome.requestId,status:last.outcome.status});
  }
  pendingRequests(options: { readOnly?: boolean } = {}) { return Object.values(this.local.requests).filter(e => (!options.readOnly || !e.controlPlane) && ['pending', 'unconfirmed'].includes(e.outcome.status)).map(e => copy(e.outcome)); }
  async recover(requestId: string): Promise<V4CommandResult> {
    return this.exclusive(async () => {
      this.reload();
      const entry = this.local.requests[requestId];
      if (!entry) throw new ApiError('Unknown request', 404, 'request_not_found');
      if (entry.controlPlane) return this.delegate(entry.operation, entry.input, requestId);
      if (this.storageError) throw new ApiError('Keep the original browser data', 0, 'storage_unavailable');
      let response: any;
      try { response = await this.raw(this.path('/requests/' + encodeURIComponent(requestId))); }
      catch (error) {
        if (error instanceof ApiError && error.status === 404 && error.code === 'request_not_found') {
          entry.outcome = { requestId, status: 'failed', result: { code: 'request_not_found', serverAbsent: true } };
          this.save(); this.emit(); return copy(entry.outcome);
        }
        throw error;
      }
      if (response.session_id !== this.ports.binding.sessionId || response.request_id !== requestId || response.operation !== entry.command.operation || response.read_only !== true) throw unconfirmed();
      const statuses: Record<string, V4CommandResult['status']> = { completed: 'confirmed', pending: 'pending', failed: 'failed', needs_context: 'needs_context', unresolved: 'unconfirmed' };
      if (!statuses[response.status]) throw unconfirmed();
      entry.outcome = { requestId, status: statuses[response.status], result: response };
      this.save(); this.emit();
      return copy(entry.outcome);
    });
  }
  async retry(requestId: string): Promise<V4CommandResult> {
    // Always inspect the persisted server result. Never replay a lost POST automatically.
    if (this.local.requests[requestId]?.controlPlane) return this.recover(requestId);
    const recovered = await this.recover(requestId);
    if (!['failed', 'needs_context'].includes(recovered.status)) throw new ApiError('Request is not retryable', 409, 'retry_not_available');
    const response = recovered.result as any;
    if (response?.serverAbsent === true) {
      const original = copy(this.local.requests[requestId]);
      return this.exclusive(() => this.send(original.operation, original.input, requestId));
    }
    const jobs = (response.jobs ?? []).filter((j: any) => ['failed', 'needs_context'].includes(j.status));
    if (jobs.length !== 1) throw new ApiError('No unique retryable job', 409, 'retry_not_available');
    return this.exclusive(() => this.send('jobs.refresh', { job_id: jobs[0].job_id }, requestId));
  }
  draft<T>(slot: V4SlotId, key: string): T | undefined { return copy(this.local.drafts[slot]?.[key] as T | undefined); }
  async keepDraft<T>(slot: V4SlotId, key: string, value: T): Promise<void> {
    const saved = copy(value), draftId = JSON.stringify([slot, key]);
    this.unsavedDrafts.set(draftId, { slot, key, value: saved });
    this.local.drafts[slot] = { ...this.local.drafts[slot], [key]: saved };
    return this.exclusive(async () => {
      this.reload();
      if (this.storageError) throw new ApiError('Keep the original browser data', 0, 'storage_unavailable');
      this.save(); this.unsavedDrafts.clear();
    });
  }
  async flushDrafts() {
    await this.exclusive(async () => {
      this.reload();
      if (this.storageError) throw new ApiError('Draft storage is unavailable', 0, 'storage_unavailable');
      if (this.unsavedDrafts.size) { this.save(); this.unsavedDrafts.clear(); }
    });
  }
  openReference(ref: ObjectRef | EvidenceRefV2) { this.checkRef(ref); return this.ports.openReference(copy(ref)); }
  chooseEvidence() { return this.ports.chooseEvidence(); }
  private checkRef(ref: ObjectRef) {
    if (ref.session_id !== this.ports.binding.sessionId) throw new ApiError('Reference belongs to another session', 404, 'session_binding_mismatch');
  }
  private select(kind: 'currentTask' | 'currentProduct', ref: ObjectRef) {
    this.checkRef(ref);
    if (JSON.stringify(this.local[kind]) === JSON.stringify(ref)) return;
    void this.exclusive(async () => { this.reload(); if (this.storageError) throw new ApiError('Selection storage is unavailable', 0, 'storage_unavailable'); this.local[kind] = copy(ref); this.save(); this.emit(); this.ports.didSelect?.(kind, copy(ref)); })
      .catch(error => this.ports.announce(error.message, 'error'));
  }
  selectTask(ref: ObjectRef) { this.select('currentTask', ref); }
  selectProduct(ref: ObjectRef) { this.select('currentProduct', ref); }
  announce(message: string, kind?: 'status' | 'error') { this.ports.announce(message, kind); }
}
