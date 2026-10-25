import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { afterAll, beforeAll, expect, it } from 'vitest';
import { launch } from '../../tests/walkthrough/cdp.mjs';

let server;
beforeAll(async () => {
  server = await createServer({
    root: fileURLToPath(new URL('../../', import.meta.url)),
    server: { port: 19780, strictPort: true },
    logLevel: 'error',
    plugins: [
      {
        name: 'transition-fixture',
        configureServer(vite) {
          vite.middlewares.use('/transition-fixture', (_req, res) => {
            res.setHeader('Content-Type', 'text/html');
            res.end(
              '<!doctype html><html><head><title>Transition fixture</title></head><body></body></html>',
            );
          });
        },
      },
    ],
  });
  await server.listen();
});
afterAll(async () => {
  await server?.close();
});

it('keeps the page transition animated while the entrance cover still carries a cloned title', async () => {
  const browser = await launch({ reduced: false });
  try {
    await browser.goto('http://127.0.0.1:19780/transition-fixture');
    const result = await browser.ev(`(async () => {
      await import('/src/screens/home/home.css');
      const { createPageTransition } = await import('/src/app/view-transition.ts');
      const { walkIn } = await import('/src/screens/home/walk-in.ts');
      document.body.innerHTML = '<div id="app"><section class="hm-brief"><h1 data-title style="view-transition-name:case-title">Brief title</h1><div class="hm-seed"><span class="hm-seed__text">Task</span></div><button id="take">Take on</button></section></div>';
      const original = document.startViewTransition.bind(document);
      let transition, copied;
      document.startViewTransition = update => transition = original(update);
      const run = createPageTransition(document, {matches:false}).run;
      const entrance = walkIn({
        trigger: document.querySelector('#take'), hold: () => {}, open: async () => {},
        show: () => {
          document.querySelector('#app').innerHTML = '<h1 style="view-transition-name:case-title">Live title</h1><section data-board-tasks><article data-task-id="task"><span class="card-title">Task</span></article></section>';
          copied = getComputedStyle(document.querySelector('.hm-cover [data-title]')).viewTransitionName;
          run(() => document.querySelector('h1').textContent = 'Task title');
        },
      });
      // walkIn awaits the practice opening before it draws the live page and creates the cover.
      await new Promise(resolve => setTimeout(resolve, 0));
      await transition.ready;
      const animated = !!document.getAnimations().length;
      await transition.finished;
      await entrance;
      return {
        live: getComputedStyle(document.querySelector('h1')).viewTransitionName,
        copied,
        title: document.querySelector('h1').textContent,
        animated,
      };
    })()`);
    expect(result).toEqual({
      live: 'case-title',
      copied: 'none',
      title: 'Task title',
      animated: true,
    });
    expect(browser.logs.filter((row) => row.level === 'exception')).toEqual([]);
  } finally {
    await browser.close();
  }
});
