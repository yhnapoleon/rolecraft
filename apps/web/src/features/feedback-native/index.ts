/** Native DOM submission/review surface. Inject the shared client; no credentials,
 * queue, mutation journal, global navigation or React root is created here. */
import {mountReviewControls} from './review-controls';
import {feedbackText,type FeedbackLanguage} from './localization';
import type { ObjectRef, EvidenceRefV2, WorkProductVersion } from '../workspace/contract-types';

export type SelectedProduct = Pick<WorkProductVersion,'session_id'|'product_id'|'version'|'title'|'removed_at'|'author'>;
type Item = { criterion: string; explanation: string; source: string; label: string; rule_bound?:{lower:string;upper:string}|null; citations: EvidenceRefV2[] };
export type FeedbackSemanticStatus = 'waiting_for_model' | 'available' | 'pending' | 'failed';
export type Report = {
  semantic_status?: FeedbackSemanticStatus;
  id: string; version: number; subject: ObjectRef; items: Item[]; rule_items?: Item[] | null;
  verified_facts?: { subject?:ObjectRef; status?:'verified'|'partial'|'unknown'; summary: string[]; references: {verified_ref?:EvidenceRefV2|null}[] }[] | null;
  historical_responsibilities?: {entries:{criterion:string;explanation:string;sources:EvidenceRefV2[]}[]}[] | null;
  business_response: string; next_options: string[];
};
export type ReviewRecord = {id:string;version:number;session_id:string;subjects:ObjectRef[];purpose:string;question:string;decision:string|null;followup_of:ObjectRef[]};
export type ReviewDraft = {subjects:ObjectRef[];purpose:string;question:string;decision:string|null;scope:string[];followup_of:ObjectRef[]};
export interface FeedbackNativeState {
  /** Fixed session language supplied by the shared adapter; never browser locale. */
  workLanguage?: FeedbackLanguage;
  /** UI preference only; stored feedback keeps its original language. */
  uiLanguage?: FeedbackLanguage;
  products: SelectedProduct[];
  reviews?: ReviewRecord[];
  reviewHistoryAvailable?:boolean;
  submission?: {ref:ObjectRef;products:ObjectRef[];decision:string} | null;
  submissions?: {ref:ObjectRef;products:ObjectRef[];decision:string}[];
  reports: Report[];
  responses?:{id:string;version?:number;session_id?:string;feedback?:ObjectRef;kind:'objection'|'supplement';text:string}[];
  /** Feedback slot status only. Never copy a colleague/role mode here. */
  semanticStatus?: FeedbackSemanticStatus;
  /** Legacy adapter field; intentionally ignored by semantic rendering. */
  modelMode?: 'placeholder'|'provider';
  status: 'active'|'paused'|'submitted';
  busy: boolean;
  pending?: boolean;
  /** Presentation only; request identity and recovery remain in the host journal. */
  awaitingFeedback?: boolean;
  error?: string;
}
export interface FeedbackNativeAdapter {
  snapshot(): FeedbackNativeState;
  subscribe(callback:()=>void):()=>void;
  review?(input:ReviewDraft):Promise<unknown>;
  submit(input:{decision:string;products:ObjectRef[]}):Promise<unknown>;
  respond(input:{feedback_id:string;feedback_version:number;kind:'objection'|'supplement';section:'general'|'verified_facts'|'historical_responsibilities'|'rule_items'|'model_advice';criterion?:string;text:string;evidence:EvidenceRefV2[]}):Promise<unknown>;
  beginRevision(input:{parent_submission:ObjectRef;reason:string}):Promise<unknown>;
  refresh():Promise<unknown>;
  recover?():Promise<unknown>;
  openReference(ref:ObjectRef|EvidenceRefV2):void;
  chooseEvidence?():Promise<EvidenceRefV2[]>;
  readDraft(key:string):{text:string;evidence:EvidenceRefV2[]} | undefined;
  keepDraft(key:string,draft:{text:string;evidence:EvidenceRefV2[]}):Promise<void>;
  canReview?:boolean;
  canSubmit?:boolean;
  canRespond?:boolean;
}

export function feedbackSemanticPresentation(report:Pick<Report,'semantic_status'|'items'>,state:Pick<FeedbackNativeState,'semanticStatus'|'modelMode'>) {
  const status=report.semantic_status??state.semanticStatus;
  const advice=status==='waiting_for_model'?[]:report.items.filter(item=>item.source==='model_advice');
  return {status,advice,waitingForModel:status==='waiting_for_model'||(status===undefined&&advice.length===0)};
}

export type FeedbackMountOptions = {surface?:'all'|'submission'|'feedback'};

export function mountNativeFeedback(host:HTMLElement,adapter:FeedbackNativeAdapter,options:FeedbackMountOptions={}) {
  const doc=host.ownerDocument;
  const language=adapter.snapshot().uiLanguage??adapter.snapshot().workLanguage??'zh';
  const T=(zh:string,en:string)=>feedbackText(language,zh,en);
  const versionLabel=(n:number)=>language==='en'?'v'+n:'第 '+n+' 版';
  const selectedRefs=(n:number)=>language==='en'?`${n} original references selected`:`已选 ${n} 处原始引用`;
  const el=<K extends keyof HTMLElementTagNameMap>(tag:K,text='',cls='')=>{const n=doc.createElement(tag);n.textContent=text;n.className=cls||(tag==='h2'?'group-title':tag==='h3'?'row-title':'');return n;};
  let destroyed=false;const selected=new Map<string,ObjectRef>();const selectedTitles=new Map<string,string>();const draftResponses=new Map<string,{text:string;evidence:EvidenceRefV2[]}>();
  let savedDrafts:Promise<void>=Promise.resolve();
  let draftError:unknown;
  const persist=(key:string,draft:{text:string;evidence:EvidenceRefV2[]})=>{
    const value=structuredClone(draft);
    savedDrafts=savedDrafts.then(()=>adapter.keepDraft(key,value)).catch(error=>{draftError=error;failure.textContent=T("本机保存未确认，请保留本页文字。","Local saving is not confirmed. Keep the text on this page.");failure.hidden=false;});
    return savedDrafts;
  };
  const key=(ref:ObjectRef)=>[ref.session_id,ref.kind,ref.object_id,ref.version,ref.config_version??''].join(':');
  const root=el('section','','native-feedback');root.setAttribute('aria-label',T("交付与反馈","Submission and feedback"));root.lang=language;
  const hiddenStyle=doc.createElement('style');hiddenStyle.textContent='.native-feedback [hidden]{display:none!important}.native-feedback{min-width:0;overflow-wrap:anywhere}.native-feedback section,.native-feedback article{min-width:0}.native-feedback>section,.native-feedback article>section{margin-block:20px}.native-feedback .btn{white-space:normal;height:auto;min-height:34px;max-width:100%;margin:3px 5px 3px 0}.native-feedback .field-row{display:flex;align-items:flex-start;gap:8px;margin:8px 0}.native-feedback .field-row input{flex:none;margin-top:5px}.native-feedback blockquote{margin:10px 0;padding:8px 12px;border-inline-start:2px solid var(--line);color:var(--ink-2)}.native-feedback .group-title{margin-block:20px 10px}.native-feedback .row-title{margin-block:14px 8px}.native-feedback p{line-height:1.6}.native-feedback .textarea,.native-feedback .select{max-width:100%}';root.append(hiddenStyle);
  const notice=el('p','','muted');notice.setAttribute('role','status');notice.setAttribute('aria-live','polite');
  const failure=el('p','','inline-alert');failure.setAttribute('role','alert');failure.hidden=true;
  const submissions=el('section');submissions.append(el('h2',T("确认这次交付","Confirm this submission")));
  const selectedSummary=el('div');selectedSummary.setAttribute('aria-label',T("本次将提交的版本","Versions to submit"));
  const selection=el('div');selection.setAttribute('aria-label',T("选择确切作品版本","Select exact artifact versions"));
  const choice=el('select','','select');choice.setAttribute('aria-label',T("本次决定","Your decision"));
  for(const [value,text] of [['',T("请选择本次决定","Choose a decision")],['launch',T("按方案推进","Proceed with the proposal")],['launch_narrow',T("缩小范围推进","Proceed with a limited scope")],['defer_with_conditions',T("满足条件后再推进","Defer until conditions are met")],['no_go',T("停止这项方案","Do not proceed with this proposal")]]){const option=el('option',text);option.value=value;choice.append(option);}
  const receipt=el('div');const responseHistory=el('section');const reports=el('div');reports.setAttribute('aria-label',T("分段反馈","Feedback sections"));
  const revisions=el('section');const revisionReason=el('textarea','','textarea');revisionReason.rows=3;revisionReason.setAttribute('aria-label',T("这次准备怎样修订","What will you revise?"));revisionReason.placeholder=T("保留上次提交，说明这次准备补充或调整什么。","Keep the previous submission and describe what you will add or change.");
  revisionReason.value=adapter.readDraft('revision')?.text??'';
  revisionReason.addEventListener('input',()=>{void persist('revision',{text:revisionReason.value,evidence:[]});});
  const button=(text:string,action:()=>Promise<unknown>|void,primary=false)=>{const n=el('button',text,'btn'+(primary?' primary':''));n.type='button';n.addEventListener('click',()=>{void act(action);});return n;};
  async function act(action:()=>Promise<unknown>|void) {
    failure.hidden=true;
    try {await action();}
    catch(error){if(!destroyed){failure.textContent=error instanceof Error?error.message:T("操作尚未确认，你填写的内容仍保留。","The action is not confirmed. Your text is retained.");failure.hidden=false;}}
    finally{if(!destroyed)render();}
  }
  const submit=button(T("提交选中的版本","Submit selected versions"),async()=>{
    if(!choice.value)throw Error(T("请明确本次决定。停止或暂缓也可以交付。","Specify your decision. You can also submit a no-go or deferral."));
    if(!selected.size)throw Error(T("请选择这次要交付的作品版本。","Select the artifact versions to submit."));
    await adapter.submit({decision:choice.value,products:[...selected.values()]});
  },true);
  const recover=button(T("确认上一请求","Check the previous request"),()=>adapter.recover?.());
  submissions.append(el('p',T("提交会保留这些确切版本。反馈后可进入修订，原提交与原反馈继续保留。","Submission preserves these exact versions. You can revise after feedback; the original submission and feedback remain available."),'muted'),selection,selectedSummary,choice,submit,recover,receipt);
  const revise=button(T("开始修订","Start a revision"),async()=>{const current=adapter.snapshot().submission;if(!current)return;if(!revisionReason.value.trim())throw Error(T("请写下本次修订的方向。","Describe the direction of this revision."));await savedDrafts;if(draftError)throw Error(T("修订说明尚未保存，请先保留文字。","The revision note is not saved. Keep a copy of your text."));await adapter.beginRevision({parent_submission:current.ref,reason:revisionReason.value});});
  revisions.append(el('h2',T("接着修订","Continue revising")),revisionReason,revise);
  const refresh=button(T("查看最新反馈","Refresh feedback"),()=>adapter.refresh());
  root.append(failure,notice);
  if(options.surface!=='feedback')root.append(submissions);
  if(options.surface==='feedback')root.append(recover);
  if(options.surface!=='submission')root.append(refresh,reports,responseHistory,revisions);
  const reviewControls=options.surface!=='submission'&&adapter.review?mountReviewControls(doc,adapter,language):undefined;
  if(reviewControls)root.insertBefore(reviewControls.element,reports);
  host.replaceChildren(root);
  function refs(parent:HTMLElement,values:(ObjectRef|EvidenceRefV2)[]) {
    const names:Record<string,string>={product:T("作品","Artifact"),material:T("材料","Material"),test:T("测试","Test"),role_reply:T("同事回复","Colleague reply"),role_turn:T("问题","Question"),submission:T("提交记录","Submission"),review:T("评审记录","Review"),event:T("历史记录","History")};
    const row=el('div');for(const ref of values){const link=button(`${names[ref.kind]??T("依据","Evidence")} · ${versionLabel(ref.version)}`,()=>adapter.openReference(ref));row.append(link);if('quote' in ref && ref.quote){if(language==='en'&&/[\u4e00-\u9fff]/u.test(ref.quote))row.append(el('small','Chinese source','muted'));row.append(el('blockquote',ref.quote));}}parent.append(row);
  }
  function responseForm(report:Report,criterion?:string,section:'general'|'verified_facts'|'historical_responsibilities'|'rule_items'|'model_advice'='general') {
    const id=[report.id,report.version,section,criterion??''].join(':');
    let draft=draftResponses.get(id);if(!draft){draft=adapter.readDraft(id)??{text:'',evidence:[]};draftResponses.set(id,draft);}
    const form=el('details');form.append(el('summary',T("提出异议或补充依据","Challenge or supplement the evidence")));
    const body=el('textarea','','textarea');body.rows=3;body.value=draft.text;body.setAttribute('aria-label',T("异议或补证内容","Challenge or additional evidence"));
    body.addEventListener('input',()=>{draft!.text=body.value;void persist(id,draft!);});
    const evidence=el('p','','muted');evidence.textContent=draft.evidence.length?selectedRefs(draft.evidence.length):T("补证引用尚未选择","No supporting references selected");
    const choose=button(T("选择已获准的原始引用","Choose authorized original references"),async()=>{if(adapter.chooseEvidence){draft!.evidence=await adapter.chooseEvidence();await persist(id,draft!);evidence.textContent=selectedRefs(draft!.evidence.length);}});choose.disabled=!adapter.chooseEvidence;
    const send=(kind:'objection'|'supplement')=>async()=>{
      if(!draft!.text.trim())throw Error(T("请写下具体的异议或补充内容。","Describe your challenge or additional evidence."));
      await savedDrafts;if(draftError)throw Error(T("回应草稿尚未保存，请先保留文字。","The response draft is not saved. Keep a copy of your text."));
      await adapter.respond({feedback_id:report.id,feedback_version:report.version,kind,section,criterion,text:draft!.text,evidence:draft!.evidence});
      draft!.text='';draft!.evidence=[];await persist(id,draft!);body.value='';evidence.textContent=T("补证引用尚未选择","No supporting references selected");
    };
    const objection=button(T("记录异议","Record a challenge"),send('objection'));const supplement=button(T("提交补证","Submit additional evidence"),send('supplement'));
    objection.disabled=supplement.disabled=adapter.snapshot().busy || !!adapter.snapshot().pending || adapter.canRespond===false;
    form.append(body,evidence,choose,objection,supplement,el('p',T("记录关联后仍等待核验，不会自动改写原反馈或认定异议已解决。","Linked records still await verification. They do not rewrite earlier feedback or automatically resolve a challenge."),'muted'));
    return form;
  }
  function reportPanel(report:Report) {
    const latest=adapter.snapshot().submission?.ref;const current=report.subject.kind==='submission'&&(!latest||(report.subject.object_id===latest.object_id && report.subject.version===latest.version));
    const panel=el('article');panel.append(el('h2',report.subject.kind==='review'?T("作品评审反馈","Artifact review feedback"):current?T("最近提交的反馈","Latest submission feedback"):T("此前提交的反馈","Earlier submission feedback")));refs(panel,[report.subject]);
    if(report.subject.kind==='review'){const review=adapter.snapshot().reviews?.find(r=>r.id===report.subject.object_id&&r.version===report.subject.version);if(review){panel.append(el('p',review.question||T('按作品形成时的信息评审。','Reviewed against information available when the artifact was formed.'),'muted'));refs(panel,review.subjects);}}
    const facts=el('section');facts.append(el('h3',T("你做过的工作与依据","Your recorded work and evidence")));
    if(!report.verified_facts?.length)facts.append(el('p',T("事实记录还未就绪，不能据此判断你没有调查。","Fact records are not ready. This does not show that you did no investigation."),'muted'));
    for(const snapshot of report.verified_facts??[]){if(snapshot.subject)refs(facts,[snapshot.subject]);facts.append(el('p',snapshot.status==='verified'?T("规则核实","Verified by rules"):snapshot.status==='partial'?T("部分依据已核实，缺少的记录仍待核验","Some evidence is verified; missing records remain unverified"):T("记录待核验","Records awaiting verification"),'muted'));for(const text of snapshot.summary.slice(0,3))facts.append(el('p',text));if(snapshot.summary.length>3){const details=el('details');details.append(el('summary',T("查看核实明细","View verification details")));for(const text of snapshot.summary.slice(3))details.append(el('p',text));facts.append(details);}refs(facts,snapshot.references.flatMap(x=>x.verified_ref?[x.verified_ref]:[]));}
    panel.append(facts);
    const history=el('section');history.append(el('h3',T("历史行动与承诺","Past actions and commitments")));
    for(const snapshot of report.historical_responsibilities??[])for(const entry of snapshot.entries){history.append(el('p',entry.explanation));refs(history,entry.sources);}
    if(!report.historical_responsibilities?.some(s=>s.entries.length))history.append(el('p',T("当前没有可展示的历史责任结论。","No historical responsibility finding is currently available."),'muted'));
    panel.append(history);
    const criteria:Record<string,string>={'R1.target':T("目标用户与业务目标","Target users and business goals"),'R1.metrics':T("指标与验收口径","Metrics and acceptance criteria"),'R2.support':T("判断的证据支持","Evidence supporting judgments"),'R2.unknowns':T("事实与待确认事项","Facts and unresolved questions"),'R2.failure_analysis':T("失败案例与原因分析","Failure cases and analysis"),'R4.staleness_test':T("政策更新后的复测","Retesting after policy changes"),'R5.impact':T("变更影响","Impact of changes"),'R5.adjustment':T("实际调整与复测","Actual adjustments and retesting"),'R6.consistency':T("作品与配置一致性","Consistency of artifacts and configuration"),'R6.operations':T("后续运行安排","Operational follow-up"),'R6.alternatives':T("替代方案与取舍","Alternatives and trade-offs"),'R3.capacity':T("人数与容量","Participants and capacity"),'R3.resources':T("资源与时间","Resources and timing"),'R4.functional_tests':T("实际测试","Actual tests"),'R6.comparison':T("方案比较","Option comparison"),'decision.rationale':T("决定依据","Basis for the decision"),'decision.follow_up':T("后续安排","Follow-up"),'result.claims':T("已完成事项的声明","Completion claims")};
    const notApplicable=el('details');notApplicable.append(el('summary',T("查看本次未适用的验收项","View criteria not applicable to this submission")));
    let inactive=0;
    for(const item of report.rule_items??report.items.filter(i=>i.source==='verified_rule')){
      const section=el('section');section.append(el('h3',criteria[item.criterion]??T("具体反馈项","Feedback criterion")),el('p',item.source==='verified_rule'?T("规则核实","Verified by rules"):T("等待核验","Awaiting verification"),'muted'),el('p',item.explanation));if(item.rule_bound){const labels:Record<string,string>={NOT_MET:T("未满足","Not met"),PARTIAL:T("部分满足","Partially met"),MET:T("满足","Met")};section.append(el('p',item.rule_bound.lower===item.rule_bound.upper?T("规则确定：","Rule finding: ")+(labels[item.rule_bound.lower]??item.rule_bound.lower):T("规则已核实范围：","Verified rule interval: ")+(labels[item.rule_bound.lower]??item.rule_bound.lower)+'—'+(labels[item.rule_bound.upper]??item.rule_bound.upper)+T("；范围内的具体判断仍待核验。","; the exact judgment within this interval remains unverified."),'muted'));}refs(section,item.citations);section.append(responseForm(report,item.criterion,'rule_items'));
      if(item.label==='NOT_APPLICABLE'){notApplicable.append(section);inactive++;}else panel.append(section);
    }
    if(inactive)panel.append(notApplicable);
    const semantic=el('section');semantic.append(el('h3',T("理由与证据的支持关系","Support between reasoning and evidence")));
    const {advice,waitingForModel}=feedbackSemanticPresentation(report,adapter.snapshot());
    if(!advice.length)semantic.append(el('p',!waitingForModel?T("支持关系仍待核验；当前没有已完成的模型建议。","Support remains unverified; no completed model advice is available."):T("等待模型接入。当前只展示已核事实与规则，不对理由是否合理作模板判断。","Awaiting model connection. Only verified facts and rules are shown; no template judgment of reasoning quality is made."),'muted'));
    for(const item of advice){semantic.append(el('p',T("模型建议 · ","Model advice · ")+item.explanation));refs(semantic,item.citations);semantic.append(responseForm(report,item.criterion,'model_advice'));}
    panel.append(semantic);
    panel.append(el('p',report.business_response));for(const text of report.next_options)panel.append(el('p',text,'muted'));
    panel.append(responseForm(report));return panel;
  }
  function renderSelected(){
    selectedSummary.replaceChildren(...[...selected].map(([id,ref])=>{const row=el('p');row.append(el('span',`${T("将提交：","To submit: ")}${selectedTitles.get(id)} · ${versionLabel(ref.version)} `));row.append(button(T("查看","View"),()=>adapter.openReference(ref)),button(T("取消选择","Deselect"),()=>{selected.delete(id);render();}));return row;}));
  }
  function render(){
    if(destroyed)return;const state=adapter.snapshot();reviewControls?.render();
    notice.textContent=state.busy?T("正在等待服务端确认…","Waiting for server confirmation…"):state.pending?T("上一请求结果尚未确认，请先恢复。","The previous request is unresolved. Recover its result first."):state.status==='submitted'?(state.reports.some(r=>r.subject.object_id===state.submission?.ref.object_id)?T("本次提交已保存，可以看反馈、提出异议或开始修订。","Submission saved. Review feedback, raise a challenge or start revising."):T("本次提交已保存，反馈尚未就绪。","Submission saved. Feedback is not ready yet.")):T("可以继续工作，选择准备交付的版本。","Continue your work and select versions for submission.");
    selection.replaceChildren(...state.products.map(product=>{
      const ref:ObjectRef={session_id:product.session_id,kind:'product',object_id:product.product_id,version:product.version};const id=key(ref);
      const row=el('label','','field-row');const checkbox=el('input');checkbox.type='checkbox';checkbox.checked=selected.has(id);
      checkbox.disabled=state.status!=='active'||state.busy||!!product.removed_at;
      checkbox.addEventListener('change',()=>{if(checkbox.checked){selected.set(id,ref);selectedTitles.set(id,product.title||T("未命名作品","Untitled artifact"));}else selected.delete(id);renderSelected();});
      row.append(checkbox,el('span',`${product.title||T("未命名作品","Untitled artifact")} · ${versionLabel(product.version)}${product.author.kind==='external_agent'?T(" · Agent制作"," · Created by an Agent"):''}`));return row;
    }));
    renderSelected();selectedSummary.hidden=state.status==='submitted';
    if(state.status==='submitted' && state.submission)choice.value=state.submission.decision;
    submit.disabled=state.status!=='active'||state.busy||!!state.pending||adapter.canSubmit===false;choice.disabled=submit.disabled;
    recover.hidden=(!state.pending&&!state.awaitingFeedback) || !adapter.recover;recover.disabled=state.busy;recover.textContent=state.awaitingFeedback?T('查看反馈进度','Check feedback progress'):T('确认上一请求','Check the previous request');
    receipt.replaceChildren();if(state.submission){receipt.append(el('h3',T("已保存的提交快照","Saved submission snapshot")));refs(receipt,state.submission.products);}
    // Do not rebuild the response editor while it holds focus. Its content is
    // retained in the per-report draft even when the shared client refreshes.
    if(!reports.contains(doc.activeElement))reports.replaceChildren(...[...state.reports].sort((a,b)=>Number(b.subject.object_id===state.submission?.ref.object_id)-Number(a.subject.object_id===state.submission?.ref.object_id)).map(reportPanel));
    responseHistory.replaceChildren();if(state.responses?.length){responseHistory.append(el('h3',T("已记录的异议与补证","Recorded challenges and additional evidence")));for(const response of state.responses){responseHistory.append(el('p',(response.kind==='objection'?T("异议已记录","Challenge recorded"):T("补证已记录","Additional evidence recorded"))+T(" · 等待核验"," · Awaiting verification")),el('blockquote',response.text));}}
    revisions.hidden=state.status!=='submitted';revise.disabled=state.busy||!!state.pending||!!state.awaitingFeedback||!state.submission;
    reports.hidden=!!state.error&&!state.reports.length;submissions.hidden=!!state.error&&!state.products.length;
    if(state.error){failure.textContent=state.error;failure.hidden=false;}
  }
  const unsubscribe=adapter.subscribe(render);render();
  return {refresh:()=>act(()=>adapter.refresh()),destroy:()=>{destroyed=true;unsubscribe();reviewControls?.destroy();root.remove();}};
}

export { mountNativeFeedback as mount };
