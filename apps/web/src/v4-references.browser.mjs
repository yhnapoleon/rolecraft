import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { afterAll, beforeAll, expect, it } from 'vitest';
import { launch } from '../tests/walkthrough/cdp.mjs';
import { waitFor } from '../tests/regression/browser-support.mjs';

let server;
let origin;
beforeAll(async () => {
  server = await createServer({
    root: fileURLToPath(new URL('../', import.meta.url)),
    server: { port: 19780, strictPort: true },
    logLevel: 'error',
    plugins: [
      {
        name: 'reference-fixture',
        configureServer(vite) {
          vite.middlewares.use('/reference-fixture', (_req, res) => {
            res.setHeader('Content-Type', 'text/html');
            res.end(
              '<!doctype html><html><head><title>Reference fixture</title></head><body></body></html>',
            );
          });
        },
      },
    ],
  });
  await server.listen();
  origin = 'http://127.0.0.1:19780';
});
afterAll(async () => {
  await server?.close();
});

// Exercise the public event through the real reader, dialog and native focus behavior.
// The fixture host supplies an immutable record; no backend or model call is needed.
for (const language of ['zh', 'en']) {
  for (const width of [1440, 390]) {
    it(`${language} at ${width}: normal close and rebuilt references return to the same opener`, async () => {
      const browser = await launch({ width, height: 1000, reduced: true });
      try {
        await browser.goto(`${origin}/reference-fixture`);
        await browser.ev(`(async () => {
          const { setPreference } = await import('/src/app/i18n.ts');
          setPreference(${JSON.stringify(language)});
          const { installV4References } = await import('/src/v4-references.ts');
          const ref = { session_id: 'fixture', kind: 'material', object_id: 'policy', version: 1 };
          installV4References(() => ({
            snapshot: () => ({ session: { protocol: 2, sessionId: 'fixture' }, available: {} }),
            query: async () => ({ ref, content: { title: 'Policy', text: 'Verified source.' } }),
          }));
          window.rebuild = (attribute) => {
            document.querySelector('#feedback')?.remove();
            const panel = document.createElement('section');
            panel.id = 'feedback';
            panel.innerHTML = '<details><summary>Sources</summary><button '+attribute+'="other">Other</button><button '+attribute+'="same">First</button><details><summary>More</summary><button id="opener" '+attribute+'="same">Second</button></details></details><button id="practice-a">Practice A</button><button id="practice-b">Practice B</button>';
            document.body.prepend(panel);
          };
          window.readReference = async () => {
            const opener = document.querySelector('#opener');
            for (let n = opener.parentElement; n; n = n.parentElement) if (n instanceof HTMLDetailsElement) n.open = true;
            opener.focus();
            await new Promise((resolve, reject) => window.dispatchEvent(new CustomEvent('v4-open-reference', { detail: {ref, resolve, reject} })));
          };
        })()`);
        for (const key of ['data-reference-key', 'data-model-reference-key']) {
          for (const rebuilt of [false, true]) {
            await browser.ev(`window.rebuild(${JSON.stringify(key)}); window.readReference()`);
            expect(
              await browser.ev(
                `!!document.querySelector('dialog[open]') && document.activeElement.tagName === 'H2'`,
              ),
            ).toBe(true);
            if (rebuilt) await browser.ev(`window.rebuild(${JSON.stringify(key)})`);
            // Escape and the close button both dispatch the native dialog close event.
            if (rebuilt) {
              await browser.send('Input.dispatchKeyEvent', {
                type: 'keyDown',
                key: 'Escape',
                code: 'Escape',
                windowsVirtualKeyCode: 27,
              });
              await browser.send('Input.dispatchKeyEvent', {
                type: 'keyUp',
                key: 'Escape',
                code: 'Escape',
                windowsVirtualKeyCode: 27,
              });
            } else await browser.click('dialog button');
            await waitFor(browser, `!document.querySelector('dialog')`);
            expect(await browser.ev(`document.activeElement.id`)).toBe('opener');
            expect(
              await browser.ev(
                `[...document.querySelectorAll('#feedback details')].every(n => n.open)`,
              ),
            ).toBe(true);
            for (const choice of ['practice-a', 'practice-b']) {
              await browser.send('Input.dispatchKeyEvent', {
                type: 'keyDown',
                key: 'Tab',
                code: 'Tab',
                windowsVirtualKeyCode: 9,
              });
              await browser.send('Input.dispatchKeyEvent', {
                type: 'keyUp',
                key: 'Tab',
                code: 'Tab',
                windowsVirtualKeyCode: 9,
              });
              expect(await browser.ev('document.activeElement.id')).toBe(choice);
            }
          }
        }
        expect(browser.logs.filter((row) => row.level === 'exception')).toEqual([]);
      } finally {
        await browser.close();
      }
    });
  }
}
