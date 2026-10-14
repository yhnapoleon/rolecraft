/** Test-only: the browser's practice engine run in this realm, and in-memory storage. */
import { readFileSync } from 'node:fs';
import { runInThisContext } from 'node:vm';

const loaded = { exports: {} };
runInThisContext(
  '(function(module){' +
    readFileSync(new URL('../public/workbench-engine.js', import.meta.url), 'utf8') +
    '\n})',
)(loaded);
export const engine = loaded.exports;

export function memory() {
  const values = new Map();
  return {
    getItem: (k) => values.get(k) ?? null,
    setItem: (k, v) => {
      values.set(k, v);
    },
  };
}
