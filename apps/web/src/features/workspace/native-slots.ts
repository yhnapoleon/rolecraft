/** Small bindings for the existing v4 DOM. Own no navigation or workbench root. */
import { T, onLocaleChange } from '../../app/i18n';
import type { WorkspaceClient } from './client';

export function purposeText(purpose:string) {
  const known:Record<string,string>={exploration:T('探索笔记','Exploration'),freeform:T('自由作品','Freeform work'),
    option:T('方案比较','Options'),comparison:T('方案比较','Options'),plan:T('计划','Plan'),
    test_plan:T('测试计划','Test plan'),commitment:T('试点决定','Pilot decision'),result:T('结果报告','Results')};
  return known[purpose] ?? purpose;
}
export function recipientText(role:string) {
  return ({supervisor:T('经理','Manager'),business_lead:T('业务负责人','Business lead'),tech_lead:T('技术负责人','Technical lead')} as Record<string,string>)[role] ?? T('指定同事','Selected colleague');
}
export function saveStatus(client:WorkspaceClient,productId:string) {
  const state=client.snapshot();
  if(state.storageError)return {text:T('本机尚未保存，请保留输入','Not saved locally; keep your text'),tone:'bad'};
  if(state.localPending)return {text:T('正在保存到本机…','Saving locally…'),tone:''};
  if(state.journal.conflicts[productId])return {text:T('版本已变化，请比较后处理','Version changed; compare before continuing'),tone:'warn'};
  if(state.journal.drafts[productId])return {text:T('草稿已存本机，待同步','Draft kept locally; pending sync'),tone:''};
  return {text:T('已保存到工作区','Saved to workspace'),tone:''};
}

export function bindWorkspaceSaveStatus(node:HTMLElement,client:WorkspaceClient,productId:()=>string) {
  const render=()=>{const status=saveStatus(client,productId());node.textContent=status.text;node.dataset.workspaceSave=status.tone;
    node.style.color=status.tone==='bad'?'var(--bad)':status.tone==='warn'?'var(--warn)':'var(--ink-2)';node.setAttribute('role','status');};
  render();const unsubscribe=client.subscribe(render);const unlocale=onLocaleChange(render);
  return ()=>{unsubscribe();unlocale();};
}
