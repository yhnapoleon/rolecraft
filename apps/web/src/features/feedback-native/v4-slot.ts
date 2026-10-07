/** W05 native v4 slot: no transport, credentials, Command envelope or journal. */
import type {V4HostAdapter,V4HostSnapshot,V4SlotContext,V4SlotHandle,V4CommandResult} from '../../v4-host';
import type {ObjectRef} from '../workspace/contract-types';
import {mountNativeFeedback,type FeedbackNativeAdapter,type FeedbackNativeState,type Report,type ReviewRecord} from './index';

type Row=Record<string,unknown>;
const object=(v:unknown):v is Row=>typeof v==='object'&&v!==null&&!Array.isArray(v);
function payload(value:unknown):Row {
  for(let depth=0;depth<4;depth++){
    if(!object(value))throw Error('Invalid feedback data');
    if(Array.isArray(value.items)||value.workspace||value.feedback||value.objects)return value;
    if(!object(value.result))return value;
    value=value.result;
  }
  throw Error('Invalid feedback envelope');
}
function reference(value:unknown,sid:string):ObjectRef {
  if(!object(value)||value.session_id!==sid||typeof value.kind!=='string'||typeof value.object_id!=='string'||!Number.isInteger(value.version)||Number(value.version)<1)throw Error('Invalid feedback reference');
  return value as unknown as ObjectRef;
}
const signature=(s:Readonly<V4HostSnapshot>)=>JSON.stringify([s.session,s.asOf,s.state,s.available]);
const semantic=(s:Readonly<V4HostSnapshot>)=>s.semantic?.feedback==='waiting_model'?'waiting_for_model':s.semantic?.feedback==='model'?'available':s.semantic?.feedback==='unavailable'?'pending':undefined;
export const W05_V4_OPERATIONS=Object.freeze({products:'work_products.list',submissions:'submissions.list',feedback:'feedback.read',responses:'feedback.responses.list',timeline:'timeline',reviews:'reviews.read',review:'reviews.create',submit:'submissions.create',respond:'feedback.responses.create',revise:'revision_cycles'});

export function createV4FeedbackAdapter(host:V4HostAdapter) {
  const first=host.snapshot();const sid=first.session?.protocol===2?first.session.sessionId:null;
  let closed=false;let epoch=0;let seen=signature(first);let loading=false;let refreshAgain=false;let loadDone:Promise<void>=Promise.resolve();let finishLoad:(()=>void)|undefined;
  const pointer=host.draft<{requestId:string;status:V4CommandResult['status']}>('feedback','last-request');
  let pending:V4CommandResult|null=pointer?.requestId?{...pointer,result:null}:null;let config:ObjectRef|undefined;let loadedPoint:string|null=null;
  const listeners=new Set<()=>void>();
  let state:FeedbackNativeState={submissions:[],reviews:[],products:[],reports:[],responses:[],status:first.state==='active'?'active':first.state==='submitted'?'submitted':'paused',busy:true,workLanguage:first.session?.workLanguage??first.uiLanguage,uiLanguage:first.uiLanguage,semanticStatus:semantic(first)};
  const text=(zh:string,en:string)=>host.snapshot().uiLanguage==='en'?en:zh;
  function valid(){const s=host.snapshot();if(closed||!sid||s.session?.protocol!==2||s.session.sessionId!==sid)throw Error(text('练习已切换，请核对后继续。','The practice changed. Check it before continuing.'));return s;}
  function emit(){for(const fn of listeners)fn();}
  function sync(s:Readonly<V4HostSnapshot>){
    if(s.session?.protocol!==2||s.session.sessionId!==sid){epoch++;state={...state,products:[],reports:[],responses:[],reviews:[],submissions:[],reviewHistoryAvailable:false,submission:null,busy:false,status:'paused'};config=undefined;loadedPoint=null;emit();return;}
    state={...state,status:s.state==='submitted'?'submitted':s.state==='active'?'active':'paused',busy:s.busy||loading,pending:pending!==null&&['unconfirmed','needs_context'].includes(pending.status),awaitingFeedback:pending?.status==='pending',failedFeedback:pending?.status==='failed',workLanguage:s.session.workLanguage,uiLanguage:s.uiLanguage,semanticStatus:semantic(s)};emit();
    const next=signature(s);if(next!==seen){seen=next;void refresh();}
  }
  async function page(operation:string,input:Row={}){
    if(valid().available[operation]!==true)throw Error(text('这部分反馈服务尚未就绪。','This feedback service is not ready.'));
    return payload(await host.query(operation,input));
  }
  async function pages(operation:string,input:Row={}){
    const rows:unknown[]=[];const cursors=new Set<number>();let cursor=0;
    for(let n=0;n<100;n++){
      if(cursors.has(cursor))throw Error('Repeated feedback cursor');cursors.add(cursor);
      const data=await page(operation,{...input,cursor,limit:100});if(!Array.isArray(data.items))throw Error('Missing feedback items');rows.push(...data.items);
      if(data.next_cursor===null||data.next_cursor===undefined)return rows;
      if(!Number.isInteger(data.next_cursor)||Number(data.next_cursor)<0)throw Error('Invalid feedback cursor');cursor=Number(data.next_cursor);
    }
    throw Error(text('记录较多，请缩小范围后重试。','There are too many records; narrow the scope before retrying.'));
  }
  async function refresh(){
    if(closed||!sid)return;
    if(loading){refreshAgain=true;return loadDone;}
    const current=valid();if(current.state==='unavailable'){state={...state,products:[],reports:[],responses:[],reviews:[],submissions:[],reviewHistoryAvailable:false,submission:null,status:'paused',busy:false,error:text('当前记录无法读取，草稿仍由工作台保留。','Records are unavailable; the workbench retains your drafts.')};emit();return;}
    loading=true;loadDone=new Promise(resolve=>{finishLoad=resolve;});const started=++epoch;state={...state,busy:true};emit();
    try{
      if(pending){
        const recovered=await host.recover(pending.requestId);
        pending=recovered.status==='confirmed'?null:recovered;
        await host.keepDraft('feedback','last-request',pending?{requestId:pending.requestId,status:pending.status}:null);
      }
      const [products,submissions,timeline]=await Promise.all([pages(W05_V4_OPERATIONS.products),pages(W05_V4_OPERATIONS.submissions),current.available.timeline===true?page(W05_V4_OPERATIONS.timeline):Promise.resolve({} as Row)]);
      valid();const reports:Report[]=[];const responses:NonNullable<FeedbackNativeState['responses']>=[];
      const selected=products.map(row=>{if(!object(row)||row.session_id!==sid||typeof row.product_id!=='string'||(!Number.isInteger(row.version)||Number(row.version)<1)||!object(row.author))throw Error('Invalid work version');return row as unknown as FeedbackNativeState['products'][number];});
      const saved=submissions.map(row=>{if(!object(row)||row.session_id!==sid||typeof row.id!=='string'||(!Number.isInteger(row.version)||Number(row.version)<1)||!Array.isArray(row.products)||typeof row.decision!=='string')throw Error('Invalid submission');for(const ref of row.products)reference(ref,sid);return row;});
      // Shared public collection; older hosts may not yet expose this route.
      const reviews:ReviewRecord[]=[];let reviewHistoryAvailable=false;
      if(current.available[W05_V4_OPERATIONS.reviews]){
        try {
          const rows=await pages(W05_V4_OPERATIONS.reviews);
          for(const row of rows){
            if(!object(row)||row.session_id!==sid||typeof row.id!=='string'||!Number.isInteger(row.version)||Number(row.version)<1||!Array.isArray(row.subjects)||typeof row.purpose!=='string'||typeof row.question!=='string'||!Array.isArray(row.followup_of))throw Error('Invalid saved review');
            for(const subject of row.subjects)if(reference(subject,sid).kind!=='product')throw Error('Invalid review subject');
            for(const response of row.followup_of)if(reference(response,sid).kind!=='feedback_response')throw Error('Invalid review followup');
            if(!reviews.some(old=>old.id===row.id))reviews.push(row as unknown as ReviewRecord);
          }
          reviewHistoryAvailable=true;
        } catch {reviews.length=0;}
      }
      for(const submission of [...saved.map(row=>({id:String(row.id),version:Number(row.version),kind:'submission'})),...reviews.map(row=>({id:row.id,version:row.version,kind:'review'}))]){
        const data=await page(W05_V4_OPERATIONS.feedback,{submission_id:submission.id});if(!Array.isArray(data.items))throw Error('Invalid feedback collection');
        for(const row of data.items){
          if(!object(row)||row.session_id!==sid||typeof row.id!=='string'||(!Number.isInteger(row.version)||Number(row.version)<1)||!Array.isArray(row.items)||!Array.isArray(row.next_options)||typeof row.business_response!=='string')throw Error('Invalid feedback record');
          const subject=reference(row.subject,sid);if(subject.kind!==submission.kind||subject.object_id!==submission.id||subject.version!==submission.version)throw Error('Feedback subject mismatch');
          if(!reports.some(old=>old.id===row.id))reports.push(row as unknown as Report);
          if(current.available[W05_V4_OPERATIONS.responses])for(const response of await pages(W05_V4_OPERATIONS.responses,{feedback_id:row.id})){
            if(!object(response)||response.session_id!==sid||typeof response.id!=='string'||typeof response.text!=='string'||response.version!==1||!object(response.feedback)||!['objection','supplement'].includes(String(response.kind)))throw Error('Invalid feedback response');
            const feedbackRef=reference(response.feedback,sid);if(feedbackRef.kind!=='feedback'||feedbackRef.object_id!==row.id||feedbackRef.version!==row.version)throw Error('Response feedback mismatch');
            responses.push(response as unknown as NonNullable<FeedbackNativeState['responses']>[number]);
          }
        }
      }
      let chosen:ObjectRef|undefined;
      if(object(timeline.workspace)&&object(timeline.workspace.config)&&Array.isArray(timeline.objects)){
        const cfg=timeline.workspace.config;
        for(const row of timeline.objects)if(object(row)&&object(row.ref)&&row.ref.kind==='config'&&row.ref.object_id===cfg.id&&row.ref.version===cfg.version&&row.ref.config_version===cfg.config_version)chosen=reference(row.ref,sid);
      }
      if(started!==epoch||closed||host.snapshot().session?.sessionId!==sid)return;
      if(JSON.stringify(host.snapshot().asOf)!==JSON.stringify(current.asOf)){refreshAgain=true;return;}
      config=chosen;const last=saved.at(-1);loadedPoint=JSON.stringify(current.asOf);
      state={...state,products:selected,reports,responses,reviews,reviewHistoryAvailable,submissions:saved.map(row=>({ref:{session_id:sid,kind:'submission',object_id:String(row.id),version:Number(row.version)},products:row.products as ObjectRef[],decision:String(row.decision)})),submission:last?{ref:{session_id:sid,kind:'submission',object_id:String(last.id),version:Number(last.version)},products:last.products as ObjectRef[],decision:String(last.decision)}:null,error:undefined};
      // Never derive feedback readiness from timeline.role_mode.
    }catch(error){if(started===epoch&&!closed){config=undefined;loadedPoint=null;state={...state,products:[],reports:[],responses:[],reviews:[],submissions:[],reviewHistoryAvailable:false,submission:null,error:text('反馈记录暂时无法确认，请刷新或恢复原请求；草稿仍保留。','Feedback records are unconfirmed. Refresh or recover the original request; drafts are retained.')};host.announce(state.error!,'error');}}
    finally{loading=false;finishLoad?.();finishLoad=undefined;if(!closed){state={...state,busy:host.snapshot().busy,pending:pending!==null&&['unconfirmed','needs_context'].includes(pending.status),awaitingFeedback:pending?.status==='pending',failedFeedback:pending?.status==='failed'};emit();}if(refreshAgain){refreshAgain=false;if(!closed&&host.snapshot().session?.sessionId===sid)void refresh();}}
  }
  async function finish(result:V4CommandResult){
    valid();if(result.status==='pending'){
      pending=result;state={...state,pending:false,awaitingFeedback:true};emit();
      await host.query('workbench.read');await refresh();return;
    }
    if(result.status!=='confirmed'){
      pending=['pending','unconfirmed','needs_context','failed'].includes(result.status)?result:null;state={...state,pending:pending!==null&&['unconfirmed','needs_context'].includes(pending.status),awaitingFeedback:pending?.status==='pending',failedFeedback:pending?.status==='failed'};emit();
      throw Error(text('操作尚未确认，请通过工作台恢复原请求。','The action is not confirmed. Recover the original request through the workbench.'));
    }
    pending=null;await host.query('workbench.read');await refresh();
  }
  async function command(operation:string,input:Row){
    const s=valid();if(s.available[operation]!==true)throw Error(text('当前操作尚未就绪。','This action is not ready.'));
    if(operation===W05_V4_OPERATIONS.review&&!state.reviewHistoryAvailable)throw Error(text('评审历史入口尚未就绪，请稍后再评审。','Review history is not ready. Try the review later.'));
    if(pending&&['unconfirmed','needs_context'].includes(pending.status))throw Error(text('先恢复尚未确认的原请求。','Recover the outstanding request first.'));
    if((operation===W05_V4_OPERATIONS.submit||operation===W05_V4_OPERATIONS.review)&&loadedPoint!==JSON.stringify(s.asOf)){await refresh();throw Error(text('记录已变化，请核对确切版本后再交付。','Records changed. Check the exact versions before submitting.'));}
    await host.flushDrafts();const afterFlush=valid();if((operation===W05_V4_OPERATIONS.submit||operation===W05_V4_OPERATIONS.review)&&loadedPoint!==JSON.stringify(afterFlush.asOf))throw Error(text('记录已变化，请核对确切版本后再交付。','Records changed. Check exact versions before submitting.'));const result=await host.command(operation,input);
    await host.keepDraft('feedback','last-request',{requestId:result.requestId,status:result.status});
    await finish(result);
  }
  const adapter:FeedbackNativeAdapter={snapshot:()=>state,subscribe:fn=>{listeners.add(fn);return()=>{listeners.delete(fn);};},refresh,
    review:input=>{valid();if(!input.subjects.length)throw Error(text('请选择评审作品版本。','Select artifact versions for review.'));for(const ref of input.subjects)if(reference(ref,sid!).kind!=='product')throw Error('Invalid review subject');for(const ref of input.followup_of)if(reference(ref,sid!).kind!=='feedback_response')throw Error('Invalid review followup');return command(W05_V4_OPERATIONS.review,input as unknown as Row);},
    submit:input=>{valid();for(const ref of input.products)reference(ref,sid!);return command(W05_V4_OPERATIONS.submit,{...input,...(config?{config}:{})});},
    respond:input=>command(W05_V4_OPERATIONS.respond,input),beginRevision:input=>{reference(input.parent_submission,valid().session!.sessionId);return command(W05_V4_OPERATIONS.revise,input);},
    recover:async()=>{valid();if(pending)await finish(await host.recover(pending.requestId));},
    retry:async()=>{valid();if(!pending||pending.status!=='failed')return;const result=await host.retry(pending.requestId);await host.keepDraft('feedback','last-request',{requestId:result.requestId,status:result.status});await finish(result);},
    openReference:ref=>{valid();reference(ref,sid!);void host.openReference(ref);},chooseEvidence:async()=>{valid();const refs=await host.chooseEvidence();valid();for(const ref of refs)reference(ref,sid!);return [...refs];},
    readDraft:key=>{valid();return host.draft('feedback',key);},keepDraft:async(key,value)=>{valid();await host.keepDraft('feedback',key,value);}};
  Object.defineProperties(adapter,{canRetry:{get:()=>host.snapshot().available['jobs.refresh']===true},canReview:{get:()=>!state.error&&state.reviewHistoryAvailable===true&&!!host.snapshot().available[W05_V4_OPERATIONS.review]},canSubmit:{get:()=>!state.error&&!!host.snapshot().available[W05_V4_OPERATIONS.submit]},canRespond:{get:()=>!state.error&&!!host.snapshot().available[W05_V4_OPERATIONS.respond]}});
  const unsubscribe=host.subscribe(()=>sync(host.snapshot()));
  return {adapter,refresh,update:sync,destroy:()=>{closed=true;epoch++;unsubscribe();listeners.clear();},sessionId:sid};
}

/** Keys: content, or submission/reviewMain for the respective surface.
 * Reference navigation stays in host.openReference into existing review-side. */
export function mountV4Feedback(context:V4SlotContext):V4SlotHandle {
  const {host,nodes}=context;const surface=context.surface??'feedback';
  const content=nodes.content??(surface==='submission'?nodes.submission:nodes.reviewMain);
  if(!content)throw Error('W05 v4 content node required');
  const controller=createV4FeedbackAdapter(host);let mounted:ReturnType<typeof mountNativeFeedback>|undefined;let locale=host.snapshot().uiLanguage;let closed=false;
  const blockLegacySubmit=(event:Event)=>{event.preventDefault();event.stopPropagation();};
  if(content.tagName==='FORM'&&host.snapshot().session?.protocol===2)content.addEventListener('submit',blockLegacySubmit);
  function render(s:Readonly<V4HostSnapshot>){
    if(closed)return;
    if(s.session?.protocol!==2||s.session.sessionId!==controller.sessionId){mounted?.destroy();mounted=undefined;content.removeEventListener('submit',blockLegacySubmit);return;}
    if(locale!==s.uiLanguage&&content.contains(content.ownerDocument.activeElement)&&content.ownerDocument.activeElement?.matches('input,textarea,select,[contenteditable="true"]'))return;
    if(!mounted||locale!==s.uiLanguage){mounted?.destroy();locale=s.uiLanguage;mounted=mountNativeFeedback(content,controller.adapter,{surface});}
  }
  const onBlur=()=>render(host.snapshot());content.addEventListener('focusout',onBlur);
  const stop=controller.adapter.subscribe(()=>render(host.snapshot()));render(host.snapshot());void controller.refresh();
  return {update:s=>{controller.update(s);render(s);},destroy:()=>{closed=true;stop();controller.destroy();mounted?.destroy();content.removeEventListener('focusout',onBlur);content.removeEventListener('submit',blockLegacySubmit);}};
}
export {mountV4Feedback as mount};
