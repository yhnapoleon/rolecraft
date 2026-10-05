import { LiveWorkbench } from './workbench-live';
declare global { interface Window { PracticeEngine: any; PracticeLive: LiveWorkbench } }
window.PracticeLive = new LiveWorkbench(window.PracticeEngine, localStorage);
// Keep the HTML renderer shared with the explicit offline demo.
const script = document.createElement('script');
script.src = '/workbench.js?v=20261005-live1';
document.body.append(script);
