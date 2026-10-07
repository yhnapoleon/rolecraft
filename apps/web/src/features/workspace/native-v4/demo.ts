/** Development-only fixture. No token is printed, exported or put in a URL. */
import { mountNativeWorkspace } from './index';
import { WorkspaceClient } from '../client';
import { workspaceGatewayTransport } from '../gateway-adapter';
import { createGatewayTransport } from '../../../gateway-transport';
const status=document.querySelector<HTMLPreElement>('#boot-status')!;
try {
  const response=await fetch('/api/__w03_native_test__/bootstrap',{method:'POST'});
  if(!response.ok)throw Error('受控测试服务未连接');
  const created=await response.json();
  const client=new WorkspaceClient(created.session_id,localStorage,workspaceGatewayTransport(createGatewayTransport(()=>({sessionId:created.session_id,token:created.token}))));
  const component=mountNativeWorkspace(document.querySelector<HTMLElement>('#workspace')!,client,{canEdit:true,canAdopt:true});
  await component.refresh();status.textContent='已连接；新建作品 → 编辑保存 → 分享 → 再保存 → 撤回。';
} catch {status.textContent='受控组件服务未就绪；没有使用本地模拟结果。';}
