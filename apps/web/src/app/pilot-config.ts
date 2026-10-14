/** Pilot settings in the learner's words. Labels come from the shared vocabulary. */
import { T } from './i18n';
import { UPDATE, WORK_COST, WORK_ITEM } from './vocab.js';

// Server identifiers to the vocabulary's settings keys (the inverse of the API mapping).
const WORK_KEYS: Readonly<Record<string, string>> = {
  scope_filter: 'scope',
  human_fallback: 'fallback',
  realtime_sync: 'realtime',
};
const STRATEGY_KEYS: Readonly<Record<string, string>> = {
  daily: 'daily',
  realtime: 'realtime',
  manual_policy: 'manual',
};

export const workItemLabel = (id: string) => WORK_ITEM(WORK_KEYS[id] ?? id);
export const strategyLabel = (strategy: string) => UPDATE(STRATEGY_KEYS[strategy] ?? strategy);

// Work a strategy cannot run without. The settings include it with the strategy, so the
// saved plan and its developer-day total say the same thing (approval rules: a real-time
// strategy needs real-time sync work).
const STRATEGY_WORK: Readonly<Record<string, readonly string[]>> = { realtime: ['realtime'] };
export const strategyWork = (update: string) => STRATEGY_WORK[update] ?? [];

export function planWorkItems(update: string, checked: readonly string[]): string[] {
  return [...checked, ...strategyWork(update).filter((key) => !checked.includes(key))];
}

export const workCost = (update: string, checked: readonly string[]) =>
  planWorkItems(update, checked).reduce((total, key) => total + (WORK_COST[key] ?? 0), 0);

/** One work-item choice in the settings form; strategy work is shown chosen and locked. */
export function workItemChoice(
  key: string,
  config: { update: string; workItems: readonly string[] },
): string {
  const locked = strategyWork(config.update).includes(key);
  const checked = locked || config.workItems.includes(key);
  const cost = WORK_COST[key];
  return `<label class="choice"><input type="checkbox" name="workItems" value="${key}"${checked ? ' checked' : ''}${locked ? ' disabled' : ''}><span>${WORK_ITEM(key)}<small>${T(`${cost} 人日`, `${cost} pd`)}</small><small class="strategy-note"${locked ? '' : ' hidden'}>${T('随策略自动包含', 'Included with this strategy')}</small></span></label>`;
}

/** Re-lock work items when the strategy changes; unlocking gives back the learner's choice. */
export function syncStrategyWork(form: HTMLFormElement, update: string) {
  const included = strategyWork(update);
  for (const input of form.querySelectorAll<HTMLInputElement>('input[name="workItems"]')) {
    const locked = included.includes(input.value);
    if (locked && !input.disabled) {
      input.dataset.chosen = input.checked ? '1' : '';
      input.checked = true;
    } else if (!locked && input.disabled) {
      input.checked = input.dataset.chosen === '1';
      delete input.dataset.chosen;
    }
    input.disabled = locked;
    const note = input.parentElement?.querySelector<HTMLElement>('.strategy-note');
    if (note) note.hidden = !locked;
  }
}
