import './app/styles.css';
import { initLocale } from './app/i18n';
import { LiveWorkbench } from './workbench-live';
declare global { interface Window { PracticeEngine: any; PracticeLive: LiveWorkbench } }

let storage: Storage | undefined;
try { storage = window.localStorage; } catch { storage = undefined; }
initLocale(storage);
window.PracticeLive = new LiveWorkbench(window.PracticeEngine, storage ?? { getItem: () => null, setItem: () => { throw new DOMException('blocked', 'SecurityError'); } });
// The UI reads the bridge when it loads, so it is imported after the bridge exists.
import('./app/ui.js');
