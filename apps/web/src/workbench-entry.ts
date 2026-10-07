import { mountNativeFeedback } from './features/feedback-native';
import { feedbackAdapter, chooseEvidence } from './vertical-feedback-adapter';
import { mount as mountRoles } from './features/roles-native';
import { roleAdapter, observeDisplayedReplies } from './vertical-role-adapter';
import './app/styles.css';
import { initLocale } from './app/i18n';
import { LiveWorkbench } from './workbench-live';
declare global { interface Window { PracticeEngine: any; PracticeLive: LiveWorkbench } }

let storage: Storage | undefined;
try { storage = window.localStorage; } catch { storage = undefined; }
initLocale(storage);
window.PracticeLive = new LiveWorkbench(window.PracticeEngine, storage ?? { getItem: () => null, setItem: () => { throw new DOMException('blocked', 'SecurityError'); } });
// The UI reads the bridge when it loads, so it is imported after the bridge exists.
if (!new URLSearchParams(location.search).has('legacy')) {
  if(!storage){document.getElementById('app')!.textContent='无法访问浏览器存档，请保留原数据并允许本地存储后重开。';}
  else import('./vertical-workbench').then(({mountVerticalWorkbench})=>mountVerticalWorkbench(document.getElementById('app')!,storage!,{feedback:(node,client,open)=>{const handle=mountNativeFeedback(node,feedbackAdapter(client,open,()=>chooseEvidence(client)));void handle.refresh();return ()=>handle.destroy();},roles:(node,client,open)=>{const handle=mountRoles(node,roleAdapter(client,open));const off=observeDisplayedReplies(node,client);return ()=>{off();handle.destroy();};}}));
} else {
  import('./app/ui.js');
}
