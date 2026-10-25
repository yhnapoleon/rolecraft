// The shell: the contracts every line builds on, and its one-time install from ui.js.
// See README.md in this folder.
import { keepIsland, sweepIslands } from '../islands/mount';
import { setActionRunner } from './registry';
import { ShellToaster } from './toaster';
import './shell.css';
import './agent-light.css';

export * from './registry';
export * from './signals';
export * from './hat';
export * from './stage';
export * from './agent-bus';
export * from './toast';
export { pmStage, type PmFacts } from './pm-stage';
export { setKeyState } from './keys';

let installed = false;

/** Called once by ui.js at boot with its act(). Mounts the global toaster outside #app. */
export function installShell(run: (el: HTMLElement, ev: Event) => unknown): void {
  setActionRunner(run);
  if (installed) return;
  installed = true;
  const host = document.createElement('div');
  host.id = 'rc-toaster';
  host.dataset.island = 'toaster';
  document.body.appendChild(host);
  keepIsland('toaster', ShellToaster, {}, { persist: true });
}

/**
 * Called by ui.js at the end of every render (afterRender): islands whose placeholder did not
 * come back are released.
 */
export function afterShellRender(): void {
  sweepIslands();
}
