import './app/styles.css';
import { initLocale } from './app/i18n';
import { LiveWorkbench } from './workbench-live';
declare global { interface Window { PracticeEngine: any; PracticeLive: LiveWorkbench } }

let storage: Storage | undefined;
try { storage = window.localStorage; } catch { storage = undefined; }
initLocale(storage);
window.PracticeLive = new LiveWorkbench(window.PracticeEngine, storage ?? { getItem: () => null, setItem: () => { throw new DOMException('blocked', 'SecurityError'); } });
// v4 is the product entry. This separate shell is a development-only diagnostic.
if (import.meta.env.DEV && new URLSearchParams(location.search).get('dev-v2') === '1') {
  if (!storage) {
    document.getElementById('app')!.textContent = '开发自测：无法访问浏览器存档，请保留原数据。';
  } else {
    Promise.all([
      import('./vertical-workbench'), import('./features/roles-native'),
      import('./vertical-role-adapter'), import('./features/feedback-native'),
      import('./vertical-feedback-adapter'),
    ]).then(([{ mountVerticalWorkbench }, { mount: mountRoles }, { roleAdapter, observeDisplayedReplies },
      { mountNativeFeedback }, { feedbackAdapter, chooseEvidence }]) => {
      mountVerticalWorkbench(document.getElementById('app')!, storage!, {
        roles: (node, client, open) => {
          const handle = mountRoles(node, roleAdapter(client, open));
          const off = observeDisplayedReplies(node, client);
          return () => { off(); handle.destroy(); };
        },
        feedback: (node, client, open) => {
          const handle = mountNativeFeedback(node, feedbackAdapter(client, open, () => chooseEvidence(client)));
          void handle.refresh();
          return () => handle.destroy();
        },
      });
    });
  }
} else {
  import('./app/ui.js');
}
