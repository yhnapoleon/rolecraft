// The product manager's stage: Investigate while there is no draft of work, Decide once there
// is one, Delivered once submitted. The scale only reports; it never forces an order.
import type { Stage } from './stage';

export type PmFacts = {
  /** Some piece of work has a written body (a draft). */
  hasDraft: boolean;
  /** The practice has been submitted and not reopened for revision. */
  delivered: boolean;
  /** The person is looking at the result page. */
  onResult?: boolean;
};

export function pmStage(f: PmFacts): Stage {
  const at = f.delivered ? 2 : f.hasDraft ? 1 : 0;
  const step = (i: number, id: string, label: [string, string]) => ({
    id,
    label,
    state: (i < at ? 'done' : i === at ? 'current' : 'todo') as 'done' | 'current' | 'todo',
  });
  const steps = [
    step(0, 'investigate', ['调查', 'Investigate']),
    step(1, 'decide', ['决定', 'Decide']),
    // Delivered is the last step: once reached it counts as done, so the whole scale turns green.
    { ...step(2, 'delivered', ['已交付', 'Delivered']), state: f.delivered ? 'done' : 'todo' },
  ] as Stage['steps'];
  const primary: Stage['primary'] = f.delivered
    ? f.onResult
      ? { label: ['修订', 'Revise'], action: 'result-revise' }
      : { label: ['看结果', 'See the result'], action: 'to-review' }
    : f.hasDraft
      ? { label: ['交付', 'Submit'], action: 'submit' }
      : {
          label: ['交付', 'Submit'],
          action: 'submit',
          disabledReason: ['先写一份作品草稿', 'Draft your work first'],
        };
  return { steps, primary };
}
