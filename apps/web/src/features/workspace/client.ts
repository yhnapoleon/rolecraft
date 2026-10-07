import type { Command, ProductEdit, ProductCreate, WorkProductVersion, WorkspaceTask,
  ProductShare, TaskCreate, TaskPatch, TaskBatch, ShareCreate, ShareUpdate, VersionPoint, WorkspaceImport, ImportResult } from './contract-types';
import { JournalStore, browserCoordinator, emptyJournal, type Draft, type DraftBase, type Pending,
  type Journal, type LocalStorage, type JournalCoordinator, type RejectedRequest } from './journal';
export type { Draft, LocalStorage, JournalCoordinator } from './journal';

export type Transport = (path: string, body?: unknown, method?: string) => Promise<any>;
type Page<T> = { items: T[]; as_of: VersionPoint; next_cursor: number | null; shares?: ProductShare[]; sharing_complete?: boolean };
type EditIntent = { draft:Draft; base:DraftBase|null; token:string; parentToken?:string; writer:string };
const validPoint = (point: any): point is VersionPoint => point && ['business_seq','workspace_revision','storage_revision'].every(k => Number.isInteger(point[k]) && point[k] >= 0);
const same = (a: unknown,b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const safeId = (id:string) => { if (['__proto__','constructor','prototype'].includes(id)) throw Error('Invalid object identity'); };
export interface WorkspaceView {
  tasks: WorkspaceTask[]; products: WorkProductVersion[]; shares: Record<string, ProductShare[]>;
  asOf?: VersionPoint; journal: Journal; busy: boolean; localPending: number; storageError: boolean; error: string;
}
export function editOf(product: WorkProductVersion, draft: Draft): ProductEdit {
  return { ...draft, product_id: product.product_id, expected_head: product.version,
    legacy: product.legacy ?? null, removed: product.removed_at != null };
}
export function draftOf(product: WorkProductVersion): Draft {
  const { task, kind = 'text', purpose, title, content, structured_payload, evidence_refs, legacy, source_return_id } = product;
  return { task, kind, purpose, title, content, structured_payload, evidence_refs, legacy, source_return_id };
}

/** Credentials stay in transport. Local journal writes merge under an origin
 * Web Lock; pending network attempts use a separate cross-tab lock so typing
 * never waits for a server. Unknown outcomes keep their original request key.
 */
export class WorkspaceClient {
  private listeners = new Set<() => void>();
  private value: WorkspaceView;
  private journalStore: JournalStore;
  private localWrites: Promise<unknown> = Promise.resolve();
  private optimistic = new Map<string,EditIntent>();
  private writer: string;
  readonly key: string;
  constructor(readonly sessionId: string, storage: LocalStorage, private transport: Transport,
    private id: () => string = () => crypto.randomUUID(), options: { coordinator?:JournalCoordinator; writerId?:string } = {}) {
    this.writer = options.writerId ?? crypto.randomUUID();
    this.journalStore = new JournalStore(sessionId,storage,options.coordinator ?? browserCoordinator);
    this.key = this.journalStore.key;
    let journal=emptyJournal(sessionId), storageError=false;
    try { journal=this.journalStore.read(); } catch { storageError=true; }
    this.value = { tasks:[],products:[],shares:{},journal,busy:false,localPending:0,storageError,
      error:storageError ? '无法读取本地草稿；原存档已保留。' : '' };
  }
  snapshot = () => this.value;
  subscribe = (fn: () => void) => { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; };
  private emit(patch: Partial<WorkspaceView>) { this.value = { ...this.value,...patch }; this.listeners.forEach(fn => fn()); }
  private show(journal:Journal) {
    const view=structuredClone(journal);
    for (const [id,edit] of this.optimistic) {
      view.drafts[id]=edit.draft;view.draftBases[id]=edit.base;
      view.draftTokens[id]=edit.token;view.draftWriters[id]=edit.writer;
    }
    this.emit({journal:view});
  }
  private readJournal() {
    try { const journal=this.journalStore.read();this.show(journal);return journal; }
    catch(error) { this.emit({storageError:true,error:'无法读取本地记录；原存档已保留。'});throw error; }
  }
  private async transaction<T>(change:(latest:Journal)=>T) {
    if (this.value.storageError) throw Error('本机记录尚未保全，请保留本页文字。');
    try { const result=await this.journalStore.transaction(change);this.show(result.journal);return result.result; }
    catch(error) {
      // Domain refusals are safe aborted transactions, not storage failures.
      if (!(error instanceof JournalRefusal)) this.emit({storageError:true,error:'浏览器保存失败，请保留本页文字。'});
      else { this.readJournal();this.emit({error:error.message}); }
      throw error;
    }
  }
  private baseFor(id:string):DraftBase|null {
    if (Object.hasOwn(this.value.journal.drafts,id)) return this.value.journal.draftBases[id] ?? null;
    const product=this.value.products.find(p=>p.product_id===id);
    return product && this.value.asOf ? structuredClone({product,asOf:this.value.asOf}) : null;
  }
  keepDraft(id:string,draft:Draft):Promise<void> {
    safeId(id);
    const edit:EditIntent={draft:structuredClone(draft),base:this.baseFor(id),token:crypto.randomUUID(),
      parentToken:this.value.journal.draftTokens[id],writer:this.writer};
    this.optimistic.set(id,edit);this.show(this.value.journal);
    this.emit({localPending:this.value.localPending+1});
    const write=this.localWrites.then(async()=>{
      await this.transaction(journal=>{
        const priorToken=journal.draftTokens[id];
        const sameBranch=priorToken===edit.parentToken && journal.draftWriters[id]===this.writer;
        if (journal.drafts[id] && priorToken!==edit.parentToken) {
          const previous={draft:journal.drafts[id],base:journal.draftBases[id] ?? null,
            token:priorToken,writer:journal.draftWriters[id]};
          const alternatives=journal.alternatives[id] ?? [];
          if (!alternatives.some(a=>a.token===previous.token)) alternatives.push(previous);
          journal.alternatives[id]=alternatives;
        }
        journal.drafts[id]=edit.draft;journal.draftBases[id]=edit.base;
        journal.draftTokens[id]=edit.token;journal.draftWriters[id]=this.writer;
        journal.draftAncestors[id]=sameBranch ? [...(journal.draftAncestors[id] ?? []),priorToken].slice(-200) : [];
        if (journal.conflicts[id]) journal.conflicts[id].local=edit.draft;
      });
      if(this.optimistic.get(id)?.token===edit.token)this.optimistic.delete(id);
      this.readJournal();
    });
    // A failed save stays visible in optimistic memory, and future network
    // actions fail closed. Returning the promise lets callers await durability.
    this.localWrites=write.catch(()=>{});
    void write.catch(()=>{});
    const completion=write.finally(()=>this.emit({localPending:this.value.localPending-1}));
    void completion.catch(()=>{});return completion;
  }
  async flushLocal() { await this.localWrites;if(this.value.storageError)throw Error('本机保存未确认，尚未发送。');this.readJournal(); }
  private path(suffix:string) { return '/sessions/'+encodeURIComponent(this.sessionId)+suffix; }
  private async pages<T>(suffix:string):Promise<Page<T>> {
    const items:T[]=[];const shares:ProductShare[]=[];let sharingComplete:boolean|undefined;
    let cursor=0;let result:Page<T>;let point:VersionPoint|undefined;
    do {
      result=await this.transport(this.path(suffix+'?cursor='+cursor+'&limit=100'));
      if(!Array.isArray(result.items)||!validPoint(result.as_of)||result.items.some((x:any)=>x.session_id!==this.sessionId))throw Error('Invalid workspace response');
      if(point && !same(point,result.as_of))throw Error('分页读取期间工作区已变化，请重新读取。');
      point=result.as_of;items.push(...result.items);
      if(result.shares!==undefined){
        if(!Array.isArray(result.shares)||result.shares.some(s=>s.session_id!==this.sessionId||!s.product||s.product.session_id!==this.sessionId||!Number.isInteger(s.version)||s.version<1))throw Error('Invalid share projection');
        if(sharingComplete!==undefined && sharingComplete!==result.sharing_complete)throw Error('Invalid share projection');
        sharingComplete=result.sharing_complete;shares.push(...result.shares);
      }
      if(result.next_cursor!==null&&(!Number.isInteger(result.next_cursor)||result.next_cursor<=cursor))throw Error('Invalid cursor');
      cursor=result.next_cursor??0;
    }while(result.next_cursor!==null);
    return {...result,items,...(sharingComplete===undefined?{}:{shares,sharing_complete:sharingComplete})};
  }
  private markConflicts(journal:Journal,products:WorkProductVersion[]) {
    for(const [id,draft] of Object.entries(journal.drafts)) {
      const base=journal.draftBases[id],server=products.find(p=>p.product_id===id);
      if(!base || !server || server.version!==base.product.version) journal.conflicts[id]={local:draft,server,
        reason:base?'服务端已有更新，请先比较或另存。':'旧草稿没有可验证的基准，请先比较后确认。',
        baseVersion:base?.product.version??null,observedAt:base?.asOf.business_seq??null};
    }
  }
  async refresh() {
    await this.flushLocal();
    try {
      let tasks:Page<WorkspaceTask>|undefined,products:Page<WorkProductVersion>|undefined;
      for(let attempt=0;attempt<2;attempt++) {
        try {
          [tasks,products]=await Promise.all([this.pages<WorkspaceTask>('/work-items'),this.pages<WorkProductVersion>('/work-products')]);
          if(!same(tasks.as_of,products.as_of))throw Error('工作区已变化，请重新读取。');
          break;
        } catch(error) {
          if(attempt===1 || !(error instanceof Error) || !error.message.includes('工作区已变化'))throw error;
        }
      }
      if(!tasks||!products)throw Error('工作区读取尚未完成。');
      if(products.sharing_complete===false)throw Error('当前授权无法完整读取分享状态，请使用有完整作品权限的入口。');
      const projectedShares:Record<string,ProductShare[]>={};
      if(products.shares!==undefined){
        for(const product of products.items)projectedShares[product.product_id]=[];
        for(const share of products.shares){
          if(!Object.hasOwn(projectedShares,share.product.object_id))throw Error('Invalid share projection');
          projectedShares[share.product.object_id].push(share);
        }
      }
      this.emit({tasks:tasks.items,products:products.items,asOf:products.as_of,...(products.shares===undefined?{}:{shares:projectedShares})});
      const current=this.readJournal();const changed=structuredClone(current);this.markConflicts(changed,products.items);
      if(!same(changed.conflicts,current.conflicts))await this.transaction(latest=>this.markConflicts(latest,products.items));
    }catch(error){this.emit({error:error instanceof Error?error.message:String(error)});throw error;}
  }
  private command(operation:string,payload:object):Command {
    if(!this.value.asOf)throw Error('先读取服务端工作区。');
    return {schema_version:2,request_id:this.id(),expected_version:this.value.asOf.business_seq,
      expected_workspace_revision:this.value.asOf.workspace_revision,operation,payload:payload as Command['payload']};
  }
  async mutate(operation:string,suffix:string,payload:object,method='POST',draftId?:string,replaces?:string,expectedDraftToken?:string) {
    await this.flushLocal();
    if(this.value.busy)throw Error('上一请求仍在处理中。');
    const cmd=this.command(operation,payload);
    await this.transaction(journal=>{
      if(journal.pending)throw new JournalRefusal('先恢复上一请求或保全草稿。');
      const base=draftId?journal.draftBases[draftId]:undefined;
      if(draftId && (!base || Number(cmd.payload?.expected_head)!==base.product.version || journal.conflicts[draftId]))throw new JournalRefusal('草稿基准已变化，请先核对。');
      if(draftId && (!expectedDraftToken || journal.draftTokens[draftId]!==expectedDraftToken ||
        !same(editOf(base!.product,journal.drafts[draftId]),cmd.payload)))throw new JournalRefusal('准备发送期间有新输入，本次未发送；请重新核对草稿。');
      journal.pending={command:cmd,path:suffix,method,writer:this.writer,attempts:0,draftId,
        draft:draftId?structuredClone(journal.drafts[draftId]):undefined,draftToken:draftId?journal.draftTokens[draftId]:undefined,base};
      if(replaces && journal.rejected[replaces])journal.rejected[replaces].successor=cmd.request_id;
    });
    return this.retry(cmd.request_id);
  }
  async retry(requestId?:string):Promise<any> {
    await this.flushLocal();
    const expected=requestId??this.readJournal().pending?.command.request_id;
    if(!expected)throw Error('没有结果未知的请求。已拒绝请求请核对后重新提交。');
    return this.journalStore.network(async()=>{
      const pending=this.readJournal().pending;
      if(!pending || pending.command.request_id!==expected)throw new JournalRefusal('该请求已由其他标签页处理，请重新读取。');
      this.emit({busy:true,error:''});
      try {
        await this.transaction(journal=>{
          if(journal.pending?.command.request_id!==expected)throw new JournalRefusal('请求记录已变化，请重新读取。');
          journal.pending.attempts++;
        });
        let result:any;
        try { result=await this.transport(this.path(pending.path),pending.command,pending.method); }
        catch(error) {
          const status=(error as {status?:number})?.status;
          const explicitCode=(error as {code?:string}).code;
          // These HTTP contracts explicitly reject the attempted mutation. A
          // timeout/network/5xx/invalid success remains an UNKNOWN outcome.
          const definiteRejection = pending.attempts === 0
            ? status!==undefined && [400,401,403,404,409,422].includes(status)
            : status===409 && ['version_conflict','object_version_conflict','import_preview_stale'].includes(explicitCode??'');
          // Auth/validation failures after an earlier unknown attempt cannot
          // prove that the FIRST attempt did not execute. Keep its key pending.
          if(definiteRejection) {
            const code=(error as {code?:string}).code ?? (status===409?'version_conflict':'request_rejected');
            await this.transaction(journal=>{
              if(journal.pending?.command.request_id!==expected)throw new JournalRefusal('请求记录已变化，请重新读取。');
              journal.rejected[expected]={request:{...pending,attempts:pending.attempts+1},status:status!,code,
                nextAction:pending.command.operation==='workspace_imports' && pending.command.payload?.mode==='apply'?'repreview':
                  status===401||status===403?'reauthorize':status===409?'refresh':'edit'};
              delete journal.pending;
              if(pending.draftId && journal.drafts[pending.draftId])journal.conflicts[pending.draftId]={
                local:journal.drafts[pending.draftId],reason:'请求已被拒绝，文字保留，请核对后再提交。',
                baseVersion:pending.base?.product.version??null,observedAt:pending.base?.asOf.business_seq??null};
            });
            try{await this.refresh();}catch{/* Rejection remains durable even if refresh fails. */}
          }
          throw error;
        }
        if(!validPoint(result?.as_of)||(pending.draftId&&(result.object?.product_id!==pending.draftId||
          result.object?.session_id!==this.sessionId||result.object?.version!==Number(pending.command.payload?.expected_head)+1||
          result.object?.content!==pending.command.payload?.content)))throw Error('服务端结果尚未确认，保留原请求。');
        try {
          await this.transaction(journal=>{
            if(journal.pending?.command.request_id!==expected)throw new JournalRefusal('请求记录已变化，请重新读取。');
            const id=pending.draftId;
            const bound=id && pending.base && pending.draft && pending.draftToken &&
              pending.command.operation==='work_products.versions.create' &&
              same(editOf(pending.base.product,pending.draft),pending.command.payload);
            if(id && bound && journal.draftTokens[id]===pending.draftToken && same(journal.drafts[id],pending.draft)) {
              delete journal.drafts[id];delete journal.draftBases[id];delete journal.draftTokens[id];
              delete journal.draftWriters[id];delete journal.draftAncestors[id];delete journal.conflicts[id];
            } else if(id && bound && journal.draftWriters[id]===pending.writer &&
              (journal.draftAncestors[id]??[]).includes(pending.draftToken??'') &&
              journal.draftBases[id]?.product.version===pending.base?.product.version) {
              // Proven continuous edits on this writer can advance after its
              // own acknowledged save. Unrelated drafts never inherit the head.
              journal.draftBases[id]={product:result.object,asOf:result.as_of};delete journal.conflicts[id];
            }
            delete journal.pending;
          });
        }catch(error){throw new Error('服务端已返回，本地确认未保存；恢复后重试原请求。',{cause:error});}
        this.emit({asOf:result.as_of});
        try{await this.refresh();}catch{/* A failed follow-up read does not undo acknowledged success. */}
        return result;
      }catch(error){this.emit({error:error instanceof Error?error.message:String(error)});throw error;}
      finally{this.emit({busy:false});}
    });
  }
  createTask(input:TaskCreate){return this.mutate('work_items.create','/work-items',input);}
  patchTask(input:TaskPatch){return this.mutate('work_items.update','/work-items/'+encodeURIComponent(input.item_id),input,'PATCH');}
  batchTasks(input:TaskBatch){return this.mutate('work_items.batch','/work-items/batch',input);}
  createProduct(input:ProductCreate){return this.mutate('work_products.create','/work-products',input);}
  async save(product:WorkProductVersion) {
    await this.flushLocal();
    if(!this.value.journal.drafts[product.product_id])await this.keepDraft(product.product_id,draftOf(product));
    const journal=this.readJournal(),base=journal.draftBases[product.product_id];
    const server=this.value.products.find(p=>p.product_id===product.product_id);
    if(!base || !server || base.product.version!==server.version || journal.conflicts[product.product_id]) {
      await this.transaction(latest=>this.markConflicts(latest,this.value.products));
      throw Error('草稿基准与当前版本不一致，请先比较、合并或另存。');
    }
    return this.mutate('work_products.versions.create','/work-products/'+encodeURIComponent(product.product_id)+'/versions',
      editOf(base.product,journal.drafts[product.product_id]),'POST',product.product_id,undefined,journal.draftTokens[product.product_id]);
  }
  async confirmMerge(productId:string,merged:Draft,expectedHead:number,expectedDraftToken:string) {
    await this.refresh();
    const product=this.value.products.find(p=>p.product_id===productId);
    if(!product || product.version!==expectedHead)throw Error('服务端在核对期间又有变化，请重新比较。');
    await this.transaction(journal=>{
      if(journal.pending)throw new JournalRefusal('先确认上一请求的结果。');
      if(journal.draftTokens[productId]!==expectedDraftToken)throw new JournalRefusal('草稿在核对期间已变化，请重新比较。');
      const old={draft:journal.drafts[productId],base:journal.draftBases[productId],token:expectedDraftToken,writer:journal.draftWriters[productId]};
      journal.alternatives[productId]=[...(journal.alternatives[productId]??[]),old];
      journal.drafts[productId]=structuredClone(merged);journal.draftBases[productId]=structuredClone({product,asOf:this.value.asOf!});
      journal.draftTokens[productId]=crypto.randomUUID();journal.draftWriters[productId]=this.writer;
      journal.draftAncestors[productId]=[];delete journal.conflicts[productId];
    });
  }
  async saveCopy(productId:string) {
    await this.flushLocal();
    const journal=this.readJournal(),draft=journal.drafts[productId]??journal.conflicts[productId]?.local;
    const base=journal.draftBases[productId];
    if(!draft)throw Error('没有待另存的文字。');
    const refs=[...(draft.evidence_refs??[])];
    if(base)refs.push({session_id:this.sessionId,kind:'product',object_id:productId,version:base.product.version,observed_at_seq:base.asOf.business_seq});
    return this.createProduct({...draft,legacy:null,source_return_id:null,evidence_refs:refs});
  }
  async discardDraft(productId:string,expectedDraftToken:string) {
    await this.flushLocal();
    await this.transaction(journal=>{
      if(journal.pending?.draftId===productId)throw new JournalRefusal('先确认这份作品上一请求的结果。');
      if(journal.draftTokens[productId]!==expectedDraftToken)throw new JournalRefusal('草稿已有新输入，请重新核对后决定。');
      delete journal.drafts[productId];delete journal.draftBases[productId];delete journal.draftTokens[productId];
      delete journal.draftWriters[productId];delete journal.draftAncestors[productId];delete journal.conflicts[productId];
    });
  }
  async dismissRejected(requestId:string) {
    await this.transaction(journal=>{if(journal.rejected[requestId])journal.rejected[requestId].dismissed=true;});
  }
  async resubmitRejected(requestId:string) {
    await this.flushLocal();const rejected=this.readJournal().rejected[requestId];
    if(!rejected||rejected.successor)throw Error('该请求没有待重提的输入。');
    if(rejected.nextAction==='repreview')throw Error('导入必须先重新预览。');
    if(rejected.request.draftId)throw Error('作品修改须先比较草稿基准，再显式保存。');
    await this.refresh();
    // This explicit action changes the request key and global preconditions;
    // it NEVER rebases object expected_head/expected_revision or edits payload.
    const p=rejected.request;
    return this.mutate(p.command.operation,p.path,p.command.payload??{},p.method,undefined,requestId);
  }
  async repreviewRejectedImport(requestId:string) {
    await this.flushLocal();const rejected=this.readJournal().rejected[requestId];
    if(!rejected||rejected.nextAction!=='repreview')throw Error('没有待重新预览的导入。');
    await this.refresh();
    const input={...rejected.request.command.payload,mode:'preview',preview_storage_revision:null} as WorkspaceImport;
    return {input,preview:await this.previewImport(input)};
  }
  share(input:ShareCreate){return this.mutate('work_products.shares.create','/work-products/'+encodeURIComponent(input.product_id)+'/shares',input);}
  updateShare(input:ShareUpdate){return this.mutate('work_products.shares.change','/work-products/'+encodeURIComponent(input.product_id)+'/shares/'+encodeURIComponent(input.share_id),input,'POST');}
  async loadShares(productId:string){
    await this.refresh();
    if(Object.hasOwn(this.value.shares,productId))return this.value.shares[productId];
    const page=await this.pages<ProductShare>('/work-products/'+encodeURIComponent(productId)+'/shares');
    if(page.items.some(s=>!s.product||s.product.object_id!==productId||!Number.isInteger(s.product.version)||s.product.version<1))throw Error('Invalid share response');
    this.emit({shares:{...this.value.shares,[productId]:page.items}});return page.items;
  }
  adopt(product:WorkProductVersion){return this.mutate('work_products.adopt','/work-products/'+encodeURIComponent(product.product_id)+'/adoption',{product_id:product.product_id,product_version:product.version,expected_head:product.version,status:'adopted'});}
  async remove(product:WorkProductVersion,removed=true){
    await this.flushLocal();
    if(this.value.journal.drafts[product.product_id])throw Error('先保存或明确放弃草稿，再移除作品。');
    return this.mutate('work_products.versions.create','/work-products/'+encodeURIComponent(product.product_id)+'/versions',{...editOf(product,draftOf(product)),removed});
  }
  async previewImport(input:WorkspaceImport):Promise<ImportResult>{if(input.mode!=='preview')throw Error('先预览所选存档。');return this.transport(this.path('/workspace-imports'),this.command('workspace_imports',input),'POST');}
  applyImport(input:WorkspaceImport,preview:ImportResult,replaces?:string){if(input.package_id!==preview.package_id||preview.mode!=='preview')throw Error('导入包与预览不匹配。');return this.mutate('workspace_imports','/workspace-imports',{...input,mode:'apply',preview_storage_revision:preview.as_of.storage_revision},'POST',undefined,replaces);}
}
class JournalRefusal extends Error {}
