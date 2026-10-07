if(new URL(location.href).searchParams.get('theme')==='dark'){const css=document.createElement('link');css.rel='stylesheet';css.href='/api/__w05_native_test__/dark-style';document.head.append(css);}
/** Development-only actual API fixture, not the shared production client. */
import {mountNativeFeedback,type FeedbackNativeAdapter,type FeedbackNativeState} from './index';
import type {EvidenceRefV2} from '../workspace/contract-types';
const created=await (await fetch('/api/__w05_native_test__/bootstrap',{method:'POST'})).json();
const sid=created.session_id;const listeners=new Set<()=>void>();
let state:FeedbackNativeState={workLanguage:created.work_language??'zh',products:[],reports:[],status:created.status??'active',busy:false,modelMode:'placeholder',responses:[],submission:created.submission};
state.reports=created.reports??[];
const emit=()=>listeners.forEach(f=>f());
async function api(path:string,body?:unknown){const r=await fetch('/api/sessions/'+encodeURIComponent(sid)+path,{method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+created.token,...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body)});const value=await r.json();if(!r.ok)throw Error(value.code??'request_failed');return value;}
async function command(operation:string,payload:unknown,path:string){const page=(await api('/work-products')).result.result;return api(path,{schema_version:2,request_id:crypto.randomUUID(),operation,payload,expected_version:page.as_of.business_seq,expected_workspace_revision:page.as_of.workspace_revision});}
let jobs:{requestId:string}[]=[];
async function refresh(){
  state.products=(await api('/work-products')).result.result.items;
  for(const job of jobs){const result=await api('/requests/'+encodeURIComponent(job.requestId));if(result.status==='pending')continue;if(result.status!=='completed')throw Error('反馈任务尚未完成：'+result.status);for(const entry of result.jobs){for(const ref of entry.effect?.result?.feedbacks??[]){const report=(await api('/feedback-records/'+encodeURIComponent(ref.object_id))).result.result.feedback;if(!state.reports.some(r=>r.id===report.id))state.reports.push(report);}}}
  const responses=[];for(const report of state.reports){const page=(await api('/feedback/'+encodeURIComponent(report.id)+'/responses')).result.result;responses.push(...page.items);}
  state.responses=responses;emit();
}
const adapter:FeedbackNativeAdapter={snapshot:()=>state,subscribe:fn=>{listeners.add(fn);return()=>{listeners.delete(fn);};},refresh,
  async submit(input){state.busy=true;emit();try{const done=await command('submit',input,'/submissions');const ref=done.objects.find((r:any)=>r.kind==='submission');state.submission={ref,products:input.products,decision:input.decision};state.status='submitted';jobs.push({requestId:done.boundary.request_id});const until=Date.now()+5000;while(Date.now()<until){await refresh();if(state.reports.some(r=>r.subject.object_id===ref.object_id))break;await new Promise(resolve=>setTimeout(resolve,100));}}finally{state.busy=false;emit();}},
  async respond(input){state.busy=true;emit();try{await command('feedback.responses.create',input,'/feedback/'+encodeURIComponent(input.feedback_id)+'/responses');await refresh();}finally{state.busy=false;emit();}},
  async beginRevision(input){state.busy=true;emit();try{const result=await command('begin_revision',input,'/revision-cycles');state.status=result.state.status;await refresh();}finally{state.busy=false;emit();}},
  openReference(ref){void (async()=>{const status=document.querySelector<HTMLElement>('#status')!;if(ref.kind==='product'){const page=(await api('/work-products/'+encodeURIComponent(ref.object_id)+'/versions')).result.result;const source=page.items.find((p:any)=>p.version===ref.version);status.textContent=source?'原文 · 第'+ref.version+'版：'+source.content:'该版本暂不可读';}else status.textContent='生产导航接点：'+ref.kind+' 第'+ref.version+'版';})();},
  chooseEvidence:async()=>created.evidence as EvidenceRefV2[],
  readDraft:key=>{const raw=localStorage.getItem('w05-demo:'+sid+':'+key);return raw?JSON.parse(raw):undefined;},
  keepDraft:async(key,value)=>{localStorage.setItem('w05-demo:'+sid+':'+key,JSON.stringify(value));},canSubmit:true,canRespond:true,
};
mountNativeFeedback(document.querySelector<HTMLElement>('#feedback')!,adapter);await refresh();
