import type { Command, ProductCreate, VersionPoint, WorkspaceProductRead } from './contract-types';

export type Draft = ProductCreate;
export type DraftBase = { product: WorkspaceProductRead; asOf: VersionPoint };
export type Pending = { command: Command; path: string; method: string; writer: string;
  attempts: number; draftId?: string; draft?: Draft; draftToken?: string; base?: DraftBase | null };
export type Conflict = { local: Draft; server?: WorkspaceProductRead; reason: string;
  baseVersion: number | null; observedAt: number | null };
export type PreservedDraft = { draft: Draft; base: DraftBase | null; token: string; writer: string };
export type RejectedRequest = { request: Pending; status: number; code: string;
  nextAction: 'refresh' | 'repreview' | 'reauthorize' | 'edit'; successor?: string; dismissed?: boolean };
export type Journal = {
  schema: 2; sessionId: string; drafts: Record<string, Draft>;
  draftBases: Record<string, DraftBase | null>; draftTokens: Record<string, string>;
  draftWriters: Record<string, string>; draftAncestors: Record<string, string[]>;
  alternatives: Record<string, PreservedDraft[]>; pending?: Pending;
  conflicts: Record<string, Conflict>; rejected: Record<string, RejectedRequest>;
};
export type LocalStorage = Pick<Storage, 'getItem' | 'setItem'>;
export interface JournalCoordinator { exclusive<T>(name: string, body: () => T | Promise<T>): Promise<T> }

/** Native origin-wide locking is mandatory for browser writes. A page-only
 * mutex or a storage event is not a substitute for cross-tab coordination.
 */
export const browserCoordinator: JournalCoordinator = {
  async exclusive<T>(name: string, body: () => T | Promise<T>): Promise<T> {
    if (typeof navigator === 'undefined' || !navigator.locks?.request) {
      throw Error('当前环境无法安全协调多个标签页，请保留文字并使用支持 Web Locks 的浏览器。');
    }
    return navigator.locks.request(name, { mode: 'exclusive' }, body);
  },
};

const record = (v: unknown): v is Record<string, any> => !!v && typeof v === 'object' && !Array.isArray(v);
export function emptyJournal(sessionId: string): Journal {
  return { schema:2, sessionId, drafts:{}, draftBases:{}, draftTokens:{}, draftWriters:{},
    draftAncestors:{}, alternatives:{}, conflicts:{}, rejected:{} };
}
export function decodeJournal(raw: string | null, sessionId: string): Journal {
  if (!raw) return emptyJournal(sessionId);
  const value = JSON.parse(raw);
  if (![1,2].includes(value.schema) || value.sessionId !== sessionId || !record(value.drafts) || !record(value.conflicts)) throw Error('Invalid local journal');
  if (value.pending && (!value.pending.command?.request_id || !value.pending.path?.startsWith('/'))) throw Error('Invalid pending request');
  if (value.schema === 1) {
    // Keep the old source key untouched. Unknown bases must never be inferred
    // from a new server head. The user must compare/merge these older drafts.
    const migrated: Journal = { ...emptyJournal(sessionId), drafts:value.drafts, conflicts:value.conflicts };
    for (const id of Object.keys(value.drafts)) {
      migrated.draftBases[id] = null; migrated.draftTokens[id] = 'legacy:' + id;
      migrated.draftWriters[id] = 'legacy'; migrated.draftAncestors[id] = [];
    }
    if (value.pending) migrated.pending = { ...value.pending, writer:'legacy', base:null, attempts:1 };
    return migrated;
  }
  for (const key of ['draftBases','draftTokens','draftWriters','draftAncestors','alternatives','rejected']) {
    if (!record(value[key])) throw Error('Invalid local journal metadata');
  }
  for (const id of Object.keys(value.drafts)) {
    if (typeof value.draftTokens[id] !== 'string' || !(id in value.draftBases) || !Array.isArray(value.draftAncestors[id])) throw Error('Draft identity missing');
  }
  if(value.pending && (!Number.isInteger(value.pending.attempts) || value.pending.attempts<0))value.pending.attempts=1;
  return value;
}

export class JournalStore {
  readonly key: string;
  readonly legacyKey: string;
  constructor(readonly sessionId: string, private storage: LocalStorage, readonly coordinator: JournalCoordinator) {
    // New key prevents already-open draft1 clients from overwriting a v2
    // journal. Migration of the old key is read-only and the source is retained.
    this.key = 'rolecraft.workspace.feature.v2.journal2.' + sessionId;
    this.legacyKey = 'rolecraft.workspace.feature.v2.' + sessionId;
  }
  read(): Journal {
    return decodeJournal(this.storage.getItem(this.key) ?? this.storage.getItem(this.legacyKey), this.sessionId);
  }
  transaction<T>(change: (latest: Journal) => T): Promise<{ journal: Journal; result:T }> {
    return this.coordinator.exclusive(this.key + ':write', () => {
      const journal = this.read();
      const result = change(journal);
      // LocalStorage replaces this single value atomically. The origin lock
      // covers read/merge/write, so a stale instance cannot erase another tab.
      this.storage.setItem(this.key, JSON.stringify(journal));
      return { journal, result };
    });
  }
  network<T>(body: () => Promise<T>) { return this.coordinator.exclusive(this.key + ':network', body); }
}
