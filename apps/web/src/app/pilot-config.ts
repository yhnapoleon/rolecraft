/** Pilot settings in the learner's words. Labels come from the shared vocabulary. */
import type { EffectiveConfig } from '../contracts-v2';
import { locale, T } from './i18n';
import { FALLBACK, UPDATE, WORK_COST, WORK_ITEM } from './vocab.js';

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
export const fallbackLabel = (fallback: string) => FALLBACK(fallback);

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

export interface ConfigUse {
  text: string;
  /** True when approved developer-days, not the plan itself, hold the work back. */
  unfunded: boolean;
}

/**
 * What the next test actually uses when it differs from the saved settings, and why, in
 * one sentence; null when tests use the saved settings. Only differences that change an
 * answer count: feasibility notes (participants, launch day) and name normalisation do not.
 * The server's resolution decides; this only names it.
 */
export function configUse(
  config: EffectiveConfig | null | undefined,
  approvedDevDays: number,
): ConfigUse | null {
  if (!config) return null;
  const { requested, effective, differences = {} } = config;
  const used: string[] = [];
  const needs: string[] = [];
  let manual = false;
  if (differences.update_strategy) {
    used.push(strategyLabel(effective.update_strategy ?? 'daily'));
    if (requested.update_strategy === 'realtime') needs.push('realtime_sync');
    else manual = true;
  }
  if (differences.fallback) {
    used.push(T('答不了时不转人工', 'no hand-off to a person'));
    needs.push('human_fallback');
  }
  if (differences.scope_filter) {
    used.push(T('不过滤知识范围', 'no scope filter'));
    // Real-time sync brings scope filtering with it (policy: scoped = realtime or scope
    // filter), so a real-time plan's reason is the real-time work alone.
    if (requested.update_strategy !== 'realtime') needs.push('scope_filter');
  }
  if (!used.length) return null;
  const planned = requested.work_items ?? [];
  const delivered = effective.work_items ?? [];
  const waiting = needs.filter((id) => planned.includes(id) && !delivered.includes(id));
  const missing = needs.filter((id) => !planned.includes(id));
  const names = (ids: string[]) => ids.map(workItemLabel).join(T('、', ' and '));
  const reasons = [
    ...(waiting.length
      ? [
          T(
            `${names(waiting)}还没批到开发人日（已批准 ${approvedDevDays} 人日）`,
            `${names(waiting)} isn't funded yet (${approvedDevDays} developer-days approved)`,
          ),
        ]
      : []),
    ...(missing.length
      ? [T(`方案里没安排${names(missing)}`, `${names(missing)} isn't in the plan`)]
      : []),
    ...(manual
      ? [
          T(
            '政策转人工要先排上人工入口和范围过滤',
            'routing policy to people needs the hand-off and the scope filter in place',
          ),
        ]
      : []),
  ];
  // English clauses after the first continue the sentence in lower case.
  const clauses = reasons.map((reason, i) =>
    i && locale() === 'en' ? reason.charAt(0).toLowerCase() + reason.slice(1) : reason,
  );
  return {
    text: T(
      `测试实际用：${used.join('、')} · ${clauses.join('；')}`,
      `Tests actually use: ${used.join(', ')} · ${clauses.join('; ')}`,
    ),
    unfunded: waiting.length > 0,
  };
}

/** The save notice says what the next test uses, not only that settings were saved. */
export function savedConfigNotice(version: number, use: ConfigUse | null): string {
  return use
    ? T(
        `试点设置 v${version} 已保存；${use.text}。`,
        `Pilot settings v${version} saved. ${use.text}.`,
      )
    : T(
        `试点设置 v${version} 已保存，下一次测试会用它。`,
        `Pilot settings v${version} saved. The next test uses them.`,
      );
}
