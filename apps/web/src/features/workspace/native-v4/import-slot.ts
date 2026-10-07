/** Explicit legacy selection/preview/apply inside a host-provided import region. */
import type { V4HostAdapter } from '../../../v4-host';
import type { ImportResult, WorkspaceImport } from '../contract-types';
import { buildBrowserImport, sanitizeSelection } from '../import-browser';
import type { WorkspaceSlotController } from './slot-controller';

type LegacyAttempt={id:string;tasks:Array<{id:string;title?:string}>;artifacts:Array<{id:string;title?:string}>;[key:string]:unknown};
export function readLegacyAttempts(raw:unknown):LegacyAttempt[]{
  const value=raw as any;
  const list:any[]=Array.isArray(value?.attempts)?value.attempts:[value];
  if(!list.length||list.some(a=>!a||typeof a.id!=='string'||!Array.isArray(a.tasks)||!Array.isArray(a.artifacts)||[...a.tasks,...a.artifacts].some(x=>!x||typeof x.id!=='string')))throw Error('invalid_legacy_archive');
  // Raw credentials/unfinished requests never enter the host draft store.
  return sanitizeSelection(list) as LegacyAttempt[];
}
export function readImportPreview(raw:unknown,input:WorkspaceImport):ImportResult{
  const outer=raw as any,value=outer?.mode?outer:outer?.result;
  if(!value||value.mode!=='preview'||value.package_id!==input.package_id||typeof value.applied!=='boolean'||!Array.isArray(value.unresolved)||!value.id_map||!Number.isInteger(value.as_of?.storage_revision))throw Error('invalid_import_preview');
  return value;
}

export function mountImport(host:V4HostAdapter,container:HTMLElement,controller:WorkspaceSlotController){
  const doc=container.ownerDocument,T=(zh:string,en:string)=>host.snapshot().uiLanguage==='en'?en:zh;
  const node=<K extends keyof HTMLElementTagNameMap>(tag:K,text='')=>{const el=doc.createElement(tag);el.textContent=text;return el;};
  let stopped=false,attempts:LegacyAttempt[]=[],selected=0,selectedTasks=new Set<string>(),selectedProducts=new Set<string>(),prepared:{input:WorkspaceImport;preview:ImportResult}|undefined,busy=false;
  const root=node('div');root.className='w03-slot-content';
  const file=node('input');file.type='file';file.accept='.json,application/json';
  const sessions=node('select'),choices=node('div'),note=node('p'),results=node('div'),error=node('p');error.setAttribute('role','alert');
  const sessionId=host.snapshot().session?.sessionId;
  const active=()=>!stopped&&host.snapshot().session?.sessionId===sessionId;
  const key=()=>sessionId+':legacy-import-selection';
  const persist=async()=>host.keepDraft('workspace',key(),{taskIds:[...selectedTasks],productIds:[...selectedProducts],prepared});
  const run=async(body:()=>Promise<unknown>)=>{if(!active())return;busy=true;error.textContent='';render();try{await body();}catch{error.textContent=T('导入未完成；原存档保留，请核对选择并重新预览。','Import did not complete. The original archive is retained; review your selection and preview again.');}finally{busy=false;render();}};
  const previewButton=node('button'),applyButton=node('button'),recoverButton=node('button');
  for(const button of [previewButton,applyButton,recoverButton]){button.type='button';button.className='btn quiet small';}
  file.addEventListener('change',()=>{void run(async()=>{
    const chosen=file.files?.[0];if(!chosen)return;if(chosen.size>2*1024*1024)throw Error('archive_too_large');
    const parsed=JSON.parse(await chosen.text());if(!active())return;attempts=readLegacyAttempts(parsed);selected=0;selectedTasks.clear();selectedProducts.clear();prepared=undefined;await persist();renderChoices();
  });});
  sessions.addEventListener('change',()=>{selected=Number(sessions.value);selectedTasks.clear();selectedProducts.clear();prepared=undefined;void persist().then(renderChoices).catch(()=>{error.textContent=T('本机保存未确认','Local saving is unconfirmed');});});
  previewButton.addEventListener('click',event=>{event.stopPropagation();void run(async()=>{
    const attempt=attempts[selected];if(!attempt&&!prepared)throw Error('select_archive');
    const input=attempt?await buildBrowserImport(attempt,{taskIds:[...selectedTasks],productIds:[...selectedProducts]}):{...prepared!.input,mode:'preview' as const,preview_storage_revision:null};
    if(!active())return;const raw=await host.query('workspace_imports',input);if(!active())return;
    const preview=readImportPreview(raw,input);prepared={input,preview};await persist();
  });});
  applyButton.addEventListener('click',event=>{event.stopPropagation();void run(async()=>{
    if(!prepared||prepared.preview.applied||prepared.preview.conflicts?.some(c=>c.reason==='content_conflict'||c.reason==='version_conflict'))throw Error('preview_required');
    const {input,preview}=prepared;
    if(!active())return;const result=await controller.command('workspace_imports',{...input,mode:'apply',preview_storage_revision:preview.as_of.storage_revision});
    if(result.status==='confirmed'&&active()){const raw=result.result as any,body=raw?.read_only===true?raw.response:raw,value=body?.mode?body:body?.result;if(value?.package_id!==input.package_id||value?.applied!==true)throw Error('unconfirmed_import');prepared={input,preview:{...preview,applied:true}};await persist();}
  });});
  recoverButton.addEventListener('click',event=>{event.stopPropagation();void run(async()=>{const result=await controller.recover();if(result.status==='confirmed'&&prepared&&active()){const raw=result.result as any,body=raw?.read_only===true?raw.response:raw,value=body?.mode?body:body?.result;if(value?.package_id===prepared.input.package_id&&value?.applied===true){prepared.preview={...prepared.preview,applied:true};await persist();}}});});
  root.append(note,file,sessions,choices,previewButton,results,applyButton,recoverButton,error);container.append(root);
  function renderChoices(){
    const current=attempts[selected];sessions.replaceChildren(...attempts.map((a,i)=>{const o=node('option',a.id);o.value=String(i);return o;}));sessions.value=String(selected);choices.replaceChildren();
    for(const [kind,rows,chosen] of [['task',current?.tasks??[],selectedTasks],['product',current?.artifacts??[],selectedProducts]] as const){
      const field=node('fieldset'),caption=node('legend',kind==='task'?T('事项','Tasks'):T('作品','Work products'));field.append(caption);
      for(const row of rows){const label=node('label'),check=node('input');check.type='checkbox';check.checked=chosen.has(row.id);
        check.addEventListener('change',()=>{if(check.checked)chosen.add(row.id);else chosen.delete(row.id);prepared=undefined;void persist().catch(()=>{error.textContent=T('本机保存未确认','Local saving is unconfirmed');});render();});
        label.append(check,doc.createTextNode(row.title??row.id));field.append(label);
      }choices.append(field);
    }
    render();
  }
  function render(){
    if(stopped)return;
    note.textContent=T('只导入勾选内容；会话凭据和未完成请求不会上传。原存档保留。','Only selected content is imported. Credentials and unfinished requests are excluded. The original archive is retained.');
    file.setAttribute('aria-label',T('选择旧存档','Choose legacy archive'));sessions.setAttribute('aria-label',T('选择存档中的练习','Choose an archived session'));sessions.hidden=attempts.length<2;
    file.disabled=busy||controller.blocked();sessions.disabled=busy||controller.blocked();
    previewButton.textContent=T('先看预览','Preview first');applyButton.textContent=prepared?.preview.applied?T('这些内容已导入','This selection is imported'):T('导入这些内容','Import this selection');
    recoverButton.textContent=T('查看导入请求结果','Check import request result');recoverButton.hidden=controller.state.receipt?.operation!=='workspace_imports'||controller.state.receipt.status==='confirmed';recoverButton.disabled=busy;
    const unavailable=!controller.can('workspace_imports');
    previewButton.disabled=busy||controller.blocked()||unavailable||selectedTasks.size+selectedProducts.size===0;
    applyButton.disabled=busy||controller.blocked()||unavailable||!prepared||prepared.preview.applied||!!prepared.preview.conflicts?.some(c=>['content_conflict','version_conflict'].includes(c.reason));
    choices.querySelectorAll('input').forEach(n=>{n.disabled=busy||controller.blocked();});results.replaceChildren();
    if(prepared){
      const p=prepared.preview;
      results.append(node('p',T(prepared.input.items.length+' 项已选择，'+p.unresolved.length+' 处关联待核对。',prepared.input.items.length+' selected items; '+p.unresolved.length+' unresolved references.')));
      if(p.unresolved.length)results.append(node('p',T('正文保留；旧测试不会变成当前练习的执行记录。','Text is retained; old tests do not become execution records in the current session.')));
      const list=node('ul');for(const row of p.unresolved)list.append(node('li',row.original_id+' · '+row.status));
      for(const row of p.conflicts??[])list.append(node('li',row.original_id+' · '+row.reason));
      for(const row of p.version_map??[])list.append(node('li',row.original_id+' v'+row.original_version+' → '+(row.target?'v'+row.target.version:T('失联','Unresolved'))));results.append(list);
    }
  }
  const saved=host.draft<{taskIds:string[];productIds:string[];prepared?:{input:WorkspaceImport;preview:ImportResult}}>('workspace',key());
  if(saved){selectedTasks=new Set(saved.taskIds);selectedProducts=new Set(saved.productIds);prepared=saved.prepared;}
  renderChoices();const unsubscribe=host.subscribe(render);
  return {destroy:()=>{stopped=true;unsubscribe();root.remove();}};
}
