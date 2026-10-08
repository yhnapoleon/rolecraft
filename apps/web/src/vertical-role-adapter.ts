import type { RolesNativeAdapter, RoleId } from './features/roles-native';
/** Public adapter for the fixed W04 native component. No private audit reaches it. */
import type { VerticalClient, Ref } from './vertical-client';
import { T } from './app/i18n';

function localReplyText(text:string):string {
  return text.split('\n').map(line=>{
    const start=line.indexOf('] {');
    if(start<0)return line;
    try{
      const value=JSON.parse(line.slice(start+2));
      if(typeof value.historical_question==='string'&&typeof value.historical_reply==='string'&&typeof value.meaning==='string')
        return line.slice(0,start+1)+'\n'+T('上次的问题：','Previous question: ')+value.historical_question+'\n'+T('上次的回复：','Previous reply: ')+value.historical_reply+'\n'+value.meaning;
    }catch{ /* Ordinary source text remains verbatim. */ }
    return line;
  }).join('\n');
}

export function roleAdapter(client:VerticalClient, open:(ref:Ref)=>Promise<void>):RolesNativeAdapter {
  const names:Record<RoleId,string>={supervisor:'经理',business_lead:'陈敏',tech_lead:'技术负责人'};
  const requestIds=():string[]=>JSON.parse(client.draft('role-request-ids','[]'));
  const requestForTurn=new Map<string,any>();
  const saved=(id:string)=>JSON.parse(client.storage.getItem(client.requestKey(id))||'null');
  let pending:string|undefined;
  const polling=new Set<string>();
  const poll=(id:string)=>{if(polling.has(id))return;polling.add(id);void client.wait(id).catch(()=>{}).finally(()=>polling.delete(id));};
  async function retry(turnId:string) {
    const request=requestForTurn.get(turnId);
    const job=request?.jobs?.find((j:any)=>['failed','needs_context'].includes(j.status));
    if(!job)throw Error(T('此回复尚不能重试，请刷新记录。','Refresh the record before retrying.'));
    await client.command('/jobs/'+job.job_id+'/refresh','jobs.refresh',{job_id:job.job_id});
    poll(request.request_id);
  }
  return {
    async read(){
      await client.refresh(false);
      const statuses=new Map<string,any>();pending=undefined;
      await Promise.all(requestIds().map(async(id:string)=>{
        const journal=saved(id);
        if(journal?.status==='rejected')return;
        try{
          const request=await client.recover(id);
          const turn=request.response?.result?.turn;
          if(turn){statuses.set(turn.object_id,request);requestForTurn.set(turn.object_id,request);}
          if(request.status==='pending')poll(id);
        }catch{pending=id;}
      }));
      const replies=client.objects('role_reply');
      const titles=client.timeline.workspace?.material_titles||{};
      const turns=client.objects('role_turn').map((row:any)=>{
        const request=row.content;
        const reply=replies.find((item:any)=>item.content.request.object_id===row.ref.object_id)?.content;
        const progress=statuses.get(row.ref.object_id);
        const job=progress?.jobs?.[0];
        const materials=Object.entries(titles).flatMap(([key,title])=>{
          const split=key.lastIndexOf(':');const version=Number(key.slice(split+1));const id=key.slice(0,split);
          // This is a navigable reference label in the public utterance, never a
          // declaration that its wording semantically supports the answer.
          return reply?.text.includes('['+title+' · v'+version+']')?[{id,title:String(title),version}]:[];
        });
        return {id:row.ref.object_id,roleId:request.input.role_id,question:request.input.text,
          status:reply?'completed':job?.status||'queued',reply:reply?(client.timeline.role_mode==='local_reference'?localReplyText(reply.text):reply.text):undefined,materials,
          canRetry:job?.status==='failed',canRefresh:job?.status==='needs_context',
          explanation:job?.status==='failed'?T('回复未完成，问题已保留。主动重试会再次调用模型插槽。','Reply failed; the question is retained. An explicit retry invokes the model slot again.'):undefined};
      });
      return {sessionId:client.session.sessionId,workLanguage:client.session.workLanguage,
        mode:client.timeline.role_mode??'unavailable',colleagues:Object.entries(names).map(([id,name])=>({id:id as RoleId,name,available:client.timeline.role_mode!=='unavailable'})),turns,
        canSend:client.state.status==='active',unconfirmed:!!pending,
        restriction:client.state.status==='active'?'':T('当前练习已提交或暂停，可保留问题，开启修订后继续。','This session is submitted or paused. Keep your question and start a revision to continue.')};
    },
    async send(input:{roleId:string;text:string}) {
      const id=crypto.randomUUID();
      // Work is shared by exact role receipt; private drafts are not attached.
      await client.workspace.refresh();
      const shares=Object.values(client.workspace.snapshot().shares).flat().filter((s:any)=>s.recipient_role===input.roleId&&!s.revoked_at)
        .map((s:any)=>client.ref('share',s.id,s.version));
      try {await client.command('/turns','turns.create',{role_id:input.roleId,text:input.text,shares},id);}
      finally {if(saved(id))client.keep('role-request-ids',JSON.stringify([...new Set([...requestIds(),id])]));}
      poll(id);
    },
    async recover(){
      const id=pending??requestIds().find(id=>saved(id)?.status==='pending');
      if(!id)return;
      await client.recover(id);poll(id);const journal=saved(id);
      return {confirmed:{roleId:journal.command.payload.role_id,text:journal.command.payload.text}};
    },retry,refreshContext:retry,
    openMaterial:(material:{id:string;version:number})=>open(client.ref('material',material.id,material.version)),
    subscribe:(changed:()=>void)=>client.subscribe(changed),
    drafts:{read:(role:string)=>client.draft('role-'+role),write:(role:string,value:string)=>client.keep('role-'+role,value)},
  };
}

/** Append a display receipt only once that exact public reply is visibly drawn.
 * An observation is not a comprehension claim and never runs for a polling result. */
export function observeDisplayedReplies(container:HTMLElement, client:VerticalClient) {
  const seen=new Set<string>(),busy=new Set<string>();let destroyed=false;
  const observer=new IntersectionObserver(entries=>{
    for(const entry of entries){
      if(!entry.isIntersecting||destroyed)continue;
      const turnId=(entry.target as HTMLElement).dataset.turnId!;
      const row=client.objects('role_reply').find((r:any)=>r.content.request.object_id===turnId);
      if(!row||seen.has(row.ref.object_id)||busy.has(row.ref.object_id))continue;
      busy.add(row.ref.object_id);
      void client.command('/turns/display','turns.display',{ref:row.ref})
        .then(()=>seen.add(row.ref.object_id)).catch(()=>{}).finally(()=>busy.delete(row.ref.object_id));
    }
  },{threshold:0.1});
  const scan=()=>container.querySelectorAll<HTMLElement>('[data-turn-id]').forEach(node=>{if(node.querySelector('.rc-roles__reply'))observer.observe(node);});
  const changes=new MutationObserver(scan);changes.observe(container,{childList:true,subtree:true});scan();
  return ()=>{destroyed=true;observer.disconnect();changes.disconnect();};
}
