/** Resource negotiation inside v4's existing res-form; no independent panel or rule engine. */
import type { V4SlotContext, V4SlotHandle, V4HostSnapshot, V4CommandResult } from '../../v4-host';
import type { EvidenceRefV2 } from '../../contracts-v2';
import { T, onLocaleChange } from '../../app/i18n';
import './roles.css';
import { object, session, ref, timeline, requestRefs, rememberRequest, type PublicRow } from './v4-data';

const labels=()=>({capacity:T('名额','Seats'),dev_days:T('开发人日','Developer-days'),deadline_day:T('截止日','Deadline day')});
const keys=['capacity','dev_days','deadline_day'] as const;
type ResourceKey=typeof keys[number];
type Draft={kind:string;reason:string;terms:Partial<Record<ResourceKey,string>>;evidence:readonly EvidenceRefV2[]};
export function mount(context:V4SlotContext):V4SlotHandle {
  const {host,nodes}=context;const initial=host.snapshot().session;
  if(!initial||initial.protocol!==2)return {update(){},destroy(){}};
  const sid=initial.sessionId;const form=nodes.form;
  const reason=form?.querySelector<HTMLTextAreaElement>('[name="reason"]');
  if(!(form instanceof HTMLFormElement)||!reason){host.announce(T('资源插槽缺少原申请表单。','The resource slot is missing its original request form.'),'error');return {update(){},destroy(){}};}
  const formNode=form;const reasonNode=reason;const doc=form.ownerDocument;
  const controls=doc.createElement('fieldset');controls.className='field rc-resource-fields';controls.dataset.w04ResourceInputs='';
  const legend=doc.createElement('legend');controls.append(legend);
  const inputs=new Map<ResourceKey,HTMLInputElement>();const captions=new Map<ResourceKey,HTMLElement>();const rows=new Map<ResourceKey,HTMLElement>();
  for(const key of keys){const label=doc.createElement('label');label.className='field';const caption=doc.createElement('span');const input=doc.createElement('input');input.type='number';input.min='1';input.step='1';input.name=key;input.className='input';input.inputMode='numeric';input.dataset.resource=key;label.append(caption,input);controls.append(label);inputs.set(key,input);captions.set(key,caption);rows.set(key,label);}
  const evidenceRow=doc.createElement('div');evidenceRow.className='row-actions';const choose=doc.createElement('button');choose.type='button';choose.className='btn small quiet';const evidenceLabel=doc.createElement('span');evidenceLabel.className='meta';evidenceRow.append(choose,evidenceLabel);controls.append(evidenceRow);const reasonField=reasonNode.closest('.field');if(reasonField?.parentElement===formNode)formNode.insertBefore(controls,reasonField);else formNode.append(controls);
  const output=doc.createElement('section');output.dataset.w04ResourceResults='';output.className='stack';
  if(nodes.results){nodes.results.replaceChildren(output);}else formNode.append(output);
  let disposed=false,busy=false,pending:string|undefined,unknown=false,readTicket=0;let evidence:readonly EvidenceRefV2[]=[];let editRevision=0;let knownFailure=false;
  const kind=()=>String(new FormData(formNode).get('kind')??'');
  const current=():Draft=>({kind:kind(),reason:reasonNode.value,terms:Object.fromEntries([...inputs].map(([key,input])=>[key,input.value])),evidence});
  const stored=host.draft<Draft>('resource-requests','form');
  if(stored){
    if(!reasonNode.value&&doc.activeElement!==reasonNode)reasonNode.value=stored.reason||'';
    for(const [key,input] of inputs)input.value=stored.terms?.[key]??'';
    for(const radio of formNode.querySelectorAll<HTMLInputElement>('[name="kind"]'))radio.checked=radio.value===stored.kind;
    evidence=stored.evidence??[];
  }
  const writable=(operation:string)=>!disposed&&!busy&&!pending&&!unknown&&!host.snapshot().busy&&!host.snapshot().storageError&&host.snapshot().state==='active'&&!!host.snapshot().available[['request_business','accept_counteroffer'].includes(operation)?'actions':operation];
  const fail=()=>{if(!disposed)host.announce(knownFailure?T('本次操作未成功，申请内容仍保留。','This operation failed; request contents are retained.'):T('操作尚未确认，申请内容已保留。请恢复原请求。','The operation is unconfirmed. Request contents are retained; recover the original request.'),'error');};
  const save=()=>host.keepDraft('resource-requests','form',current());
  function renderControls(){
    legend.textContent=T('申请后的资源总量','Requested total resources');choose.textContent=T('选择依据','Choose evidence');evidenceLabel.textContent=T('已选依据：','Selected evidence: ')+evidence.length;
    const capacity=kind()==='request_capacity';
    for(const key of keys){captions.get(key)!.textContent=labels()[key];rows.get(key)!.hidden=capacity?key!=='capacity':key==='capacity';inputs.get(key)!.disabled=capacity?key!=='capacity':key==='capacity';inputs.get(key)!.required=capacity&&key==='capacity';}
    for(const button of formNode.querySelectorAll<HTMLButtonElement>('button[type="submit"]'))button.disabled=!writable('request_business');
    if(nodes.submit instanceof HTMLButtonElement)nodes.submit.disabled=!writable('request_business');
    choose.disabled=busy||disposed;
  }
  const onEdit=(event:Event)=>{event.stopImmediatePropagation();++editRevision;renderControls();void save().catch(fail);};
  formNode.addEventListener('input',onEdit);formNode.addEventListener('change',onEdit);
  choose.addEventListener('click',()=>{void host.chooseEvidence().then(async refs=>{session(host,sid);for(const r of refs)ref(r,sid);if(disposed)return;++editRevision;evidence=refs;await save();renderControls();}).catch(fail);});
  const termsText=(value:unknown)=>{
    const terms=object(value);return Object.entries(terms).map(([key,amount])=>{
      if(!keys.includes(key as ResourceKey)||!Number.isInteger(amount)||amount<0)throw Error('Invalid resource result');
      return labels()[key as ResourceKey]+': '+amount;
    }).join(T('，',', '));
  };
  async function recover(id:string){const result=await host.recover(id);session(host,sid);if(['pending','unconfirmed'].includes(result.status)){pending=id;throw Error('Still unresolved');}pending=undefined;unknown=false;renderControls();await refresh();}
  async function command(operation:string,input:Record<string,unknown>){
    if(!writable(operation))throw Error('Command unavailable');knownFailure=false;busy=true;renderControls();let result:V4CommandResult|undefined;let dispatched=false;
    try{
      await save();await host.flushDrafts();session(host,sid);dispatched=true;result=await host.command(['request_business','accept_counteroffer'].includes(operation)?'actions':operation,input);
      await rememberRequest(host,'resource-requests',result);
      if(['pending','unconfirmed'].includes(result.status)){pending=result.requestId;throw Error('Original request unresolved');}
      if(result.status!=='confirmed')throw Error('Request failed');
      unknown=false;
    }catch(error){unknown=dispatched&&!result;knownFailure=result?.status==='failed';throw error;}
    finally{busy=false;renderControls();await refresh().catch(fail);}
    return result;
  }
  function button(parent:HTMLElement,title:string,operation:string,invoke:()=>Promise<unknown>){const b=doc.createElement('button');b.type='button';b.className='btn small quiet';b.textContent=title;b.disabled=!writable(operation);b.addEventListener('click',()=>{void invoke().catch(fail);});parent.append(b);}
  async function refresh(){
    const ticket=++readTicket;const data=await timeline(host,sid);
    let unresolved:string|undefined;
    for(const id of requestRefs(host,'resource-requests')){try{const result=await host.recover(id);if(['pending','unconfirmed'].includes(result.status))unresolved=id;}catch{unresolved=id;}}
    if(disposed||ticket!==readTicket)return;session(host,sid);pending=unresolved;renderControls();
    const fragment=doc.createDocumentFragment();
    const currentResources=data.data.workspace?.resources;
    if(currentResources){const p=doc.createElement('p');p.className='meta';p.textContent=T('最近核实的生效资源（规则核实）：','Last checked resources in effect (rule checked): ')+termsText(currentResources);fragment.append(p);}
    if(pending){const p=doc.createElement('p');p.className='warn-line';p.textContent=T('原申请结果待确认，未重新发送。','The original request is unconfirmed; it has not been resent.');const b=doc.createElement('button');b.type='button';b.className='btn small quiet';b.textContent=T('恢复原请求','Recover original request');const id=pending;b.addEventListener('click',()=>{void recover(id).catch(fail);});p.append(b);fragment.append(p);}
    const requests=new Map<string,PublicRow>();for(const row of data.rows.filter(r=>r.ref.kind==='business_request')){const old=requests.get(row.ref.object_id);if(!old||old.ref.version<row.ref.version)requests.set(row.ref.object_id,row);}
    const decisions=data.rows.filter(r=>r.ref.kind==='business_decision');
    for(const row of requests.values()){
      const req=row.content;const item=doc.createElement('div');item.className='pending-row';item.dataset.requestId=row.ref.object_id;
      const text=doc.createElement('div');text.className='grow';const requested=doc.createElement('p');requested.textContent=T('申请：','Requested: ')+termsText(req.requested);const why=doc.createElement('p');why.className='meta';why.textContent=typeof req.reason==='string'?req.reason:'';text.append(requested,why);item.append(text);
      const status=String(req.status);const decision=decisions.filter(d=>ref(d.content.request,sid,'business_request').object_id===row.ref.object_id).sort((a,b)=>b.content.request.version-a.content.request.version)[0];
      const label=doc.createElement('p');label.className='meta';
      const statusLabel=({pending:T('待核实','Awaiting rules check'),rejected:T('未批准','Declined'),countered:T('待接受还价','Counteroffer awaiting acceptance'),approved:T('已批准','Approved'),accepted:T('已接受','Accepted')} as Record<string,string>)[status]??T('状态待确认','Status unconfirmed');
      label.textContent=statusLabel+(decision?T('（规则核实）',' (rule checked)'):'');text.append(label);
      if(decision){const reasonText=doc.createElement('p');reasonText.textContent=typeof decision.content.reason==='string'?decision.content.reason:'';text.append(reasonText);
        if(status==='countered'){const p=doc.createElement('p');p.textContent=T('还价条件：','Counteroffer terms: ')+termsText(decision.content.countered);text.append(p);}
        if(['approved','accepted'].includes(status)){const p=doc.createElement('p');p.dataset.committedTerms='';p.textContent=T('生效决定（规则核实）：','Committed terms (rule checked): ')+termsText(decision.content.granted);text.append(p);}
      }
      if(status==='pending')button(item,T('核实申请','Check request'),'approvals.resolve',()=>command('approvals.resolve',{request:row.ref,expected_request_revision:row.ref.version}));
      if(status==='countered'&&decision)button(item,T('接受这些条件','Accept these terms'),'accept_counteroffer',()=>command('accept_counteroffer',{tool:'accept_counteroffer',request:row.ref,terms:decision.content.countered}));
      fragment.append(item);
    }
    output.replaceChildren(fragment);
  }
  const onSubmit=(event:Event)=>{
    event.preventDefault();event.stopImmediatePropagation();if(!writable('request_business'))return;
    const submitted=current();const submittedRevision=editRevision;const terms:Record<string,number>={};
    try{
      const selected=kind()==='request_capacity'?['capacity']:kind()==='request_resources'?['dev_days','deadline_day']:[];
      if(!selected.length||!submitted.reason.trim())throw Error('Missing request');
      for(const key of selected){const value=submitted.terms[key as ResourceKey];if(value){const amount=Number(value);if(!Number.isSafeInteger(amount)||amount<=0)throw Error('Invalid amount');terms[key]=amount;}}
      if(!Object.keys(terms).length)throw Error('Missing amount');
      for(const e of evidence)ref(e,sid);
    }catch{host.announce(T('请填写明确的申请数量和理由。','Enter explicit requested quantities and a reason.'),'error');return;}
    void command('request_business',{tool:'request_business',terms,reason:submitted.reason,evidence_refs:evidence}).then(async()=>{
      if(!disposed&&editRevision===submittedRevision&&reasonNode.value===submitted.reason){reasonNode.value='';await save();}
    }).catch(fail);
  };
  formNode.addEventListener('submit',onSubmit);
  const unlocale=onLocaleChange(()=>{renderControls();void refresh().catch(fail);});
  let lastSnapshot=JSON.stringify(host.snapshot());
  const unsubscribe=host.subscribe(()=>{const snapshot=host.snapshot();const key=JSON.stringify(snapshot);if(key===lastSnapshot)return;lastSnapshot=key;update(snapshot);});
  function update(snapshot:Readonly<V4HostSnapshot>){if(disposed)return;if(snapshot.session?.sessionId!==sid||snapshot.session.protocol!==2){destroy();return;}renderControls();void refresh().catch(fail);}
  function destroy(){if(disposed)return;disposed=true;++readTicket;unsubscribe();unlocale();formNode.removeEventListener('input',onEdit);formNode.removeEventListener('change',onEdit);formNode.removeEventListener('submit',onSubmit);controls.remove();output.remove();}
  renderControls();void refresh().catch(fail);
  return {update,destroy};
}
export default mount;
