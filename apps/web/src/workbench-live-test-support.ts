/** Test-only: the published workbench engine and in-memory storage for LiveWorkbench. */
import { readFileSync } from 'node:fs';
import { runInThisContext } from 'node:vm';
import type { LiveWorkbench } from './workbench-live';

const mod = { exports: {} as ConstructorParameters<typeof LiveWorkbench>[0] };
runInThisContext(
  '(function(module){' +
    readFileSync(new URL('../public/workbench-engine.js', import.meta.url), 'utf8') +
    '\n})',
)(mod);
export const engine = mod.exports;

export function memory() {
  const values = new Map<string, string>();
  return {
    getItem: (k: string) => values.get(k) ?? null,
    setItem: (k: string, v: string) => {
      values.set(k, v);
    },
  };
}
