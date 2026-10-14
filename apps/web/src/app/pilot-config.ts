/** Pilot settings in the learner's words. Labels come from the shared vocabulary. */
import { UPDATE, WORK_ITEM } from './vocab.js';

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
