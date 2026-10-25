// The topbar's stage scale and its one primary key, per hat. The product manager's stage is
// computed by the shell (pm-stage.ts); the engineer's is registered by 201.
import type { Hat } from './hat';
import type { Attempt } from './signals';

export type Stage = {
  /**
   * Optional: what this hat is working on, shown as the topbar's title (and the tab title) in
   * place of the case's question. Added for the engineer's hat; leaving it out keeps the default.
   */
  title?: [zh: string, en: string];
  steps: { id: string; label: [zh: string, en: string]; state: 'done' | 'current' | 'todo' }[];
  primary?: {
    label: [string, string];
    action: string;
    id?: string;
    disabledReason?: [string, string];
  };
};

const stages = new Map<Hat, (attempt: Attempt) => Stage>();

export function registerStage(hat: Hat, fn: (attempt: Attempt) => Stage): void {
  stages.set(hat, fn);
}

/** Whether a line registered this hat's stage (the shell only fills in what is missing). */
export const hasStage = (hat: Hat) => stages.has(hat);

/** The stage for this hat, or null when nobody registered one (the topbar then shows no scale). */
export function stageOf(hat: Hat, attempt: Attempt): Stage | null {
  const fn = stages.get(hat);
  if (!fn || !attempt) return null;
  try {
    return fn(attempt);
  } catch (err) {
    console.warn('stage failed', err);
    return null;
  }
}
