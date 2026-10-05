// Minimal Chrome DevTools Protocol driver for the headless walkthroughs in this folder.
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

// Any Chrome or chrome-headless-shell binary, e.g. one installed by `npx playwright install chromium`.
const BIN = process.env.CHROME_BIN;
if (!BIN) throw new Error('Set CHROME_BIN to a Chrome or chrome-headless-shell executable');

export async function launch({ width = 1440, height = 900, dark = false, mobile = false, reduced = false } = {}) {
  const dir = join(tmpdir(), 'rolecraft-cdp-' + process.pid + '-' + Math.round(performance.now()));
  const proc = spawn(BIN, ['--remote-debugging-port=0', '--user-data-dir=' + dir, '--no-first-run', '--hide-scrollbars', `--window-size=${width},${height}`, 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
  let stderr = '';
  const wsUrl = await new Promise((res, rej) => {
    proc.stderr.on('data', b => { stderr += b; const m = stderr.match(/ws:\/\/[^\s]+/); if (m) res(m[0]); });
    setTimeout(() => rej(new Error('no devtools url\n' + stderr)), 10000);
  });
  const port = new URL(wsUrl).port;
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = targets.find(t => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r, { once: true }));
  let id = 0; const pending = new Map(); const logs = [];
  ws.addEventListener('message', ev => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) { const p = pending.get(msg.id); pending.delete(msg.id); msg.error ? p.rej(new Error(JSON.stringify(msg.error))) : p.res(msg.result); }
    if (msg.method === 'Runtime.exceptionThrown') logs.push({ level: 'exception', text: msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text });
    if (msg.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(msg.params.type)) logs.push({ level: msg.params.type, text: msg.params.args.map(a => a.value ?? a.description).join(' ') });
    if (msg.method === 'Log.entryAdded' && ['error', 'warning'].includes(msg.params.entry.level)) logs.push({ level: msg.params.entry.level, text: msg.params.entry.text + ' ' + (msg.params.entry.url || '') });
  });
  const send = (method, params = {}) => new Promise((res, rej) => { const n = ++id; pending.set(n, { res, rej }); ws.send(JSON.stringify({ id: n, method, params })); setTimeout(() => { if (pending.has(n)) { pending.delete(n); rej(new Error('timeout ' + method)); } }, 20000); });
  await send('Runtime.enable'); await send('Log.enable'); await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 2, mobile, screenWidth: width, screenHeight: height });
  if (mobile) await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
  const features = [{ name: 'prefers-color-scheme', value: dark ? 'dark' : 'light' }];
  if (reduced) features.push({ name: 'prefers-reduced-motion', value: 'reduce' });
  await send('Emulation.setEmulatedMedia', { features });
  const api = {
    send, logs,
    async goto(url) { await send('Page.navigate', { url }); await delay(700); },
    async ev(expr) { const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text); return r.result.value; },
    async click(sel, i = 0) { const ok = await api.ev(`(() => { const els = [...document.querySelectorAll(${JSON.stringify(sel)})]; const el = els[${i}]; if (!el) return false; el.scrollIntoView({block:'center'}); el.click(); return true; })()`); if (!ok) throw new Error('click: not found ' + sel); await delay(650); },
    async clickText(text, scope = 'button, a, summary, [data-action]') { const ok = await api.ev(`(() => { const el = [...document.querySelectorAll(${JSON.stringify(scope)})].find(e => e.textContent.trim().includes(${JSON.stringify(text)}) && e.offsetParent !== null); if (!el) return false; el.scrollIntoView({block:'center'}); el.click(); return true; })()`); if (!ok) throw new Error('clickText: not found ' + text); await delay(650); },
    async type(sel, value) { const ok = await api.ev(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); if (!el) return false; el.focus(); el.value = ${JSON.stringify(value)}; el.dispatchEvent(new Event('input', {bubbles:true})); return true; })()`); if (!ok) throw new Error('type: not found ' + sel); await delay(200); },
    async select(sel, value, i = 0) { const ok = await api.ev(`(() => { const el = document.querySelectorAll(${JSON.stringify(sel)})[${i}]; if (!el) return false; el.value = ${JSON.stringify(value)}; el.dispatchEvent(new Event('change', {bubbles:true})); return true; })()`); if (!ok) throw new Error('select: not found ' + sel); await delay(650); },
    async submit(sel) { const ok = await api.ev(`(() => { const f = document.querySelector(${JSON.stringify(sel)}); if (!f) return false; f.requestSubmit(); return true; })()`); if (!ok) throw new Error('submit: not found ' + sel); await delay(800); },
    async shot(path, full = false) {
      let clip;
      if (full) { const m = await send('Page.getLayoutMetrics'); clip = { x: 0, y: 0, width: m.cssContentSize.width, height: Math.min(m.cssContentSize.height, 6000), scale: 1 }; }
      const r = await send('Page.captureScreenshot', { format: 'jpeg', quality: 82, captureBeyondViewport: full, ...(clip ? { clip } : {}) });
      writeFileSync(path, Buffer.from(r.data, 'base64')); return path;
    },
    async text(sel) { return api.ev(`[...document.querySelectorAll(${JSON.stringify(sel)})].map(e => e.textContent.trim().replace(/\\s+/g,' '))`); },
    async close() { try { ws.close(); } catch (_) {} proc.kill('SIGKILL'); await delay(200); try { rmSync(dir, { recursive: true, force: true }); } catch (_) {} }
  };
  return api;
}
export { delay };
