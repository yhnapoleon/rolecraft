/** Native DOM submission/review surface. Inject the shared client; no credentials,
 * queue, mutation journal, global navigation or React root is created here. */
import type { ObjectRef, EvidenceRefV2, WorkProductVersion } from '../workspace/contract-types';

type SelectedProduct = Pick<WorkProductVersion,'session_id'|'product_id'|'version'|'title'|'removed_at'|'author'>;
type Item = { criterion: string; explanation: string; source: string; label: string; rule_bound?:{lower:string;upper:string}|null; citations: EvidenceRefV2[] };
type Report = {
  id: string; version: number; subject: ObjectRef; items: Item[]; rule_items?: Item[] | null;
  verified_facts?: { status?:'verified'|'partial'|'unknown'; summary: string[]; references: {verified_ref?:EvidenceRefV2|null}[] }[] | null;
  historical_responsibilities?: {entries:{criterion:string;explanation:string;sources:EvidenceRefV2[]}[]}[] | null;
  business_response: string; next_options: string[];
};
export interface FeedbackNativeState {
  products: SelectedProduct[];
  submission?: {ref:ObjectRef;products:ObjectRef[];decision:string} | null;
  reports: Report[];
  responses?:{id:string;kind:'objection'|'supplement';text:string}[];
  modelMode: 'placeholder'|'provider';
  status: 'active'|'paused'|'submitted';
  busy: boolean;
  pending?: boolean;
  error?: string;
}
export interface FeedbackNativeAdapter {
  snapshot(): FeedbackNativeState;
  subscribe(callback:()=>void):()=>void;
  submit(input:{decision:string;products:ObjectRef[]}):Promise<unknown>;
  respond(input:{feedback_id:string;feedback_version:number;kind:'objection'|'supplement';section:'general'|'verified_facts'|'historical_responsibilities'|'rule_items'|'model_advice';criterion?:string;text:string;evidence:EvidenceRefV2[]}):Promise<unknown>;
  beginRevision(input:{parent_submission:ObjectRef;reason:string}):Promise<unknown>;
  refresh():Promise<unknown>;
  recover?():Promise<unknown>;
  openReference(ref:ObjectRef|EvidenceRefV2):void;
  chooseEvidence?():Promise<EvidenceRefV2[]>;
  readDraft(key:string):{text:string;evidence:EvidenceRefV2[]} | undefined;
  keepDraft(key:string,draft:{text:string;evidence:EvidenceRefV2[]}):Promise<void>;
  canSubmit?:boolean;
  canRespond?:boolean;
}

export function mountNativeFeedback(host:HTMLElement,adapter:FeedbackNativeAdapter) {
  const doc=host.ownerDocument;
  const el=<K extends keyof HTMLElementTagNameMap>(tag:K,text='',cls='')=>{const n=doc.createElement(tag);n.textContent=text;n.className=cls;return n;};
  let destroyed=false;const selected=new Map<string,ObjectRef>();const selectedTitles=new Map<string,string>();const draftResponses=new Map<string,{text:string;evidence:EvidenceRefV2[]}>();
  let savedDrafts:Promise<void>=Promise.resolve();
  let draftError:unknown;
  const persist=(key:string,draft:{text:string;evidence:EvidenceRefV2[]})=>{
    const value=structuredClone(draft);
    savedDrafts=savedDrafts.then(()=>adapter.keepDraft(key,value)).catch(error=>{draftError=error;failure.textContent='本机保存未确认，请保留本页文字。';failure.hidden=false;});
    return savedDrafts;
  };
  const key=(ref:ObjectRef)=>[ref.session_id,ref.kind,ref.object_id,ref.version,ref.config_version??''].join(':');
  const root=el('section','','native-feedback');root.setAttribute('aria-label','交付与反馈');
  const hiddenStyle=doc.createElement('style');hiddenStyle.textContent='.native-feedback [hidden]{display:none!important}';root.append(hiddenStyle);
  const notice=el('p','','muted');notice.setAttribute('role','status');notice.setAttribute('aria-live','polite');
  const failure=el('p','','inline-alert');failure.setAttribute('role','alert');failure.hidden=true;
  const submissions=el('section');submissions.append(el('h2','确认这次交付'));
  const selectedSummary=el('div');selectedSummary.setAttribute('aria-label','本次将提交的版本');
  const selection=el('div');selection.setAttribute('aria-label','选择确切作品版本');
  const choice=el('select','','select');choice.setAttribute('aria-label','本次决定');
  for(const [value,text] of [['','请选择本次决定'],['launch','按方案推进'],['launch_narrow','缩小范围推进'],['defer_with_conditions','满足条件后再推进'],['no_go','停止这项方案']]){const option=el('option',text);option.value=value;choice.append(option);}
  const receipt=el('div');const responseHistory=el('section');const reports=el('div');reports.setAttribute('aria-label','分段反馈');
  const revisions=el('section');const revisionReason=el('textarea','','textarea');revisionReason.rows=3;revisionReason.setAttribute('aria-label','这次准备怎样修订');revisionReason.placeholder='保留上次提交，说明这次准备补充或调整什么。';
  revisionReason.value=adapter.readDraft('revision')?.text??'';
  revisionReason.addEventListener('input',()=>{void persist('revision',{text:revisionReason.value,evidence:[]});});
  const button=(text:string,action:()=>Promise<unknown>|void,primary=false)=>{const n=el('button',text,'btn'+(primary?' primary':''));n.type='button';n.addEventListener('click',()=>{void act(action);});return n;};
  async function act(action:()=>Promise<unknown>|void) {
    failure.hidden=true;
    try {await action();}
    catch(error){if(!destroyed){failure.textContent=error instanceof Error?error.message:'操作尚未确认，你填写的内容仍保留。';failure.hidden=false;}}
    finally{if(!destroyed)render();}
  }
  const submit=button('提交选中的版本',async()=>{
    if(!choice.value)throw Error('请明确本次决定。停止或暂缓也可以交付。');
    if(!selected.size)throw Error('请选择这次要交付的作品版本。');
    await adapter.submit({decision:choice.value,products:[...selected.values()]});
  },true);
  const recover=button('确认上一请求',()=>adapter.recover?.());
  submissions.append(el('p','提交会保留这些确切版本。反馈后可进入修订，原提交与原反馈继续保留。','muted'),selection,selectedSummary,choice,submit,recover,receipt);
  const revise=button('开始修订',async()=>{const current=adapter.snapshot().submission;if(!current)return;if(!revisionReason.value.trim())throw Error('请写下本次修订的方向。');await savedDrafts;if(draftError)throw Error('修订说明尚未保存，请先保留文字。');await adapter.beginRevision({parent_submission:current.ref,reason:revisionReason.value});});
  revisions.append(el('h2','接着修订'),revisionReason,revise);
  const refresh=button('查看最新反馈',()=>adapter.refresh());
  root.append(failure,notice,submissions,refresh,reports,responseHistory,revisions);host.replaceChildren(root);
  function refs(parent:HTMLElement,values:(ObjectRef|EvidenceRefV2)[]) {
    const names:Record<string,string>={product:'作品',material:'材料',test:'测试',role_reply:'同事回复',role_turn:'问题',submission:'提交记录',review:'评审记录',event:'历史记录'};
    const row=el('div');for(const ref of values){const link=button(`${names[ref.kind]??'依据'} · 第 ${ref.version} 版`,()=>adapter.openReference(ref));row.append(link);if('quote' in ref && ref.quote)row.append(el('blockquote',ref.quote));}parent.append(row);
  }
  function responseForm(report:Report,criterion?:string,section:'general'|'verified_facts'|'historical_responsibilities'|'rule_items'|'model_advice'='general') {
    const id=[report.id,report.version,section,criterion??''].join(':');
    let draft=draftResponses.get(id);if(!draft){draft=adapter.readDraft(id)??{text:'',evidence:[]};draftResponses.set(id,draft);}
    const form=el('details');form.append(el('summary','提出异议或补充依据'));
    const body=el('textarea','','textarea');body.rows=3;body.value=draft.text;body.setAttribute('aria-label','异议或补证内容');
    body.addEventListener('input',()=>{draft!.text=body.value;void persist(id,draft!);});
    const evidence=el('p','','muted');evidence.textContent=draft.evidence.length?`已选 ${draft.evidence.length} 处原始引用`:'补证引用尚未选择';
    const choose=button('选择已获准的原始引用',async()=>{if(adapter.chooseEvidence){draft!.evidence=await adapter.chooseEvidence();await persist(id,draft!);evidence.textContent=`已选 ${draft!.evidence.length} 处原始引用`;}});choose.disabled=!adapter.chooseEvidence;
    const send=(kind:'objection'|'supplement')=>async()=>{
      if(!draft!.text.trim())throw Error('请写下具体的异议或补充内容。');
      await savedDrafts;if(draftError)throw Error('回应草稿尚未保存，请先保留文字。');
      await adapter.respond({feedback_id:report.id,feedback_version:report.version,kind,section,criterion,text:draft!.text,evidence:draft!.evidence});
      draft!.text='';draft!.evidence=[];await persist(id,draft!);body.value='';evidence.textContent='补证引用尚未选择';
    };
    const objection=button('记录异议',send('objection'));const supplement=button('提交补证',send('supplement'));
    objection.disabled=supplement.disabled=adapter.snapshot().busy || !!adapter.snapshot().pending || adapter.canRespond===false;
    form.append(body,evidence,choose,objection,supplement,el('p','记录关联后仍等待核验，不会自动改写原反馈或认定异议已解决。','muted'));
    return form;
  }
  function reportPanel(report:Report) {
    const latest=adapter.snapshot().submission?.ref;const current=!latest||(report.subject.object_id===latest.object_id && report.subject.version===latest.version);
    const panel=el('article');panel.append(el('h2',current?'最近提交的反馈':'此前提交的反馈'));refs(panel,[report.subject]);
    const facts=el('section');facts.append(el('h3','你做过的工作与依据'));
    if(!report.verified_facts?.length)facts.append(el('p','事实记录还未就绪，不能据此判断你没有调查。','muted'));
    for(const snapshot of report.verified_facts??[]){facts.append(el('p',snapshot.status==='verified'?'规则核实':snapshot.status==='partial'?'部分依据已核实，缺少的记录仍待核验':'记录待核验','muted'));for(const text of snapshot.summary.slice(0,3))facts.append(el('p',text));if(snapshot.summary.length>3){const details=el('details');details.append(el('summary','查看核实明细'));for(const text of snapshot.summary.slice(3))details.append(el('p',text));facts.append(details);}refs(facts,snapshot.references.flatMap(x=>x.verified_ref?[x.verified_ref]:[]));}
    panel.append(facts);
    const history=el('section');history.append(el('h3','历史行动与承诺'));
    for(const snapshot of report.historical_responsibilities??[])for(const entry of snapshot.entries){history.append(el('p',entry.explanation));refs(history,entry.sources);}
    if(!report.historical_responsibilities?.some(s=>s.entries.length))history.append(el('p','当前没有可展示的历史责任结论。','muted'));
    panel.append(history);
    const criteria:Record<string,string>={'R1.target':'目标用户与业务目标','R1.metrics':'指标与验收口径','R2.support':'判断的证据支持','R2.unknowns':'事实与待确认事项','R2.failure_analysis':'失败案例与原因分析','R4.staleness_test':'政策更新后的复测','R5.impact':'变更影响','R5.adjustment':'实际调整与复测','R6.consistency':'作品与配置一致性','R6.operations':'后续运行安排','R6.alternatives':'替代方案与取舍','R3.capacity':'人数与容量','R3.resources':'资源与时间','R4.functional_tests':'实际测试','R6.comparison':'方案比较','decision.rationale':'决定依据','decision.follow_up':'后续安排','result.claims':'已完成事项的声明'};
    const notApplicable=el('details');notApplicable.append(el('summary','查看本次未适用的验收项'));
    let inactive=0;
    for(const item of report.rule_items??report.items.filter(i=>i.source==='verified_rule')){
      const section=el('section');section.append(el('h3',criteria[item.criterion]??'具体反馈项'),el('p',item.source==='verified_rule'?'规则核实':'等待核验','muted'),el('p',item.explanation));if(item.rule_bound){const labels:Record<string,string>={NOT_MET:'未满足',PARTIAL:'部分满足',MET:'满足'};section.append(el('p',item.rule_bound.lower===item.rule_bound.upper?'规则确定：'+(labels[item.rule_bound.lower]??item.rule_bound.lower):'规则已核实范围：'+(labels[item.rule_bound.lower]??item.rule_bound.lower)+'—'+(labels[item.rule_bound.upper]??item.rule_bound.upper)+'；范围内的具体判断仍待核验。','muted'));}refs(section,item.citations);section.append(responseForm(report,item.criterion,'rule_items'));
      if(item.label==='NOT_APPLICABLE'){notApplicable.append(section);inactive++;}else panel.append(section);
    }
    if(inactive)panel.append(notApplicable);
    const semantic=el('section');semantic.append(el('h3','理由与证据的支持关系'));
    const advice=adapter.snapshot().modelMode==='provider'?report.items.filter(i=>i.source==='model_advice'):[];
    if(!advice.length)semantic.append(el('p',adapter.snapshot().modelMode==='provider'?'支持关系仍待核验；当前没有已完成的模型建议。':'等待模型接入。当前只展示已核事实与规则，不对理由是否合理作模板判断。','muted'));
    for(const item of advice){semantic.append(el('p','模型建议 · '+item.explanation));refs(semantic,item.citations);semantic.append(responseForm(report,item.criterion,'model_advice'));}
    panel.append(semantic);
    panel.append(el('p',report.business_response));for(const text of report.next_options)panel.append(el('p',text,'muted'));
    panel.append(responseForm(report));return panel;
  }
  function renderSelected(){
    selectedSummary.replaceChildren(...[...selected].map(([id,ref])=>{const row=el('p');row.append(el('span',`将提交：${selectedTitles.get(id)} · 第 ${ref.version} 版 `));row.append(button('查看',()=>adapter.openReference(ref)),button('取消选择',()=>{selected.delete(id);render();}));return row;}));
  }
  function render(){
    if(destroyed)return;const state=adapter.snapshot();
    notice.textContent=state.busy?'正在等待服务端确认…':state.pending?'上一请求结果尚未确认，请先恢复。':state.status==='submitted'?(state.reports.some(r=>r.subject.object_id===state.submission?.ref.object_id)?'本次提交已保存，可以看反馈、提出异议或开始修订。':'本次提交已保存，反馈正在准备。'):'可以继续工作，选择准备交付的版本。';
    selection.replaceChildren(...state.products.map(product=>{
      const ref:ObjectRef={session_id:product.session_id,kind:'product',object_id:product.product_id,version:product.version};const id=key(ref);
      const row=el('label','','field-row');const checkbox=el('input');checkbox.type='checkbox';checkbox.checked=selected.has(id);
      checkbox.disabled=state.status!=='active'||state.busy||!!product.removed_at;
      checkbox.addEventListener('change',()=>{if(checkbox.checked){selected.set(id,ref);selectedTitles.set(id,product.title||'未命名作品');}else selected.delete(id);renderSelected();});
      row.append(checkbox,el('span',`${product.title||'未命名作品'} · 第 ${product.version} 版${product.author.kind==='external_agent'?' · Agent制作':''}`));return row;
    }));
    renderSelected();selectedSummary.hidden=state.status==='submitted';
    if(state.status==='submitted' && state.submission)choice.value=state.submission.decision;
    submit.disabled=state.status!=='active'||state.busy||!!state.pending||adapter.canSubmit===false;choice.disabled=submit.disabled;
    recover.hidden=!state.pending || !adapter.recover;recover.disabled=state.busy;
    receipt.replaceChildren();if(state.submission){receipt.append(el('h3','已保存的提交快照'));refs(receipt,state.submission.products);}
    // Do not rebuild the response editor while it holds focus. Its content is
    // retained in the per-report draft even when the shared client refreshes.
    if(!reports.contains(doc.activeElement))reports.replaceChildren(...[...state.reports].sort((a,b)=>Number(b.subject.object_id===state.submission?.ref.object_id)-Number(a.subject.object_id===state.submission?.ref.object_id)).map(reportPanel));
    responseHistory.replaceChildren();if(state.responses?.length){responseHistory.append(el('h3','已记录的异议与补证'));for(const response of state.responses){responseHistory.append(el('p',(response.kind==='objection'?'异议已记录':'补证已记录')+' · 等待核验'),el('blockquote',response.text));}}
    revisions.hidden=state.status!=='submitted';revise.disabled=state.busy||!!state.pending||!state.submission;
    if(state.error){failure.textContent=state.error;failure.hidden=false;}
  }
  const unsubscribe=adapter.subscribe(render);render();
  return {refresh:()=>act(()=>adapter.refresh()),destroy:()=>{destroyed=true;unsubscribe();root.remove();}};
}

export { mountNativeFeedback as mount };
