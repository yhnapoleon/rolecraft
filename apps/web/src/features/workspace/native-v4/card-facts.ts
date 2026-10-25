/** What a board card shows about one task beyond the workspace records the slot reads itself:
 * the tests run for it, whether those tests all predate the current policy, the colleagues who
 * left a reminder on it, and whether the last delivery's revision starts here. The shell owns
 * these facts (tests and colleague reminders live in its projection) and registers one
 * provider; the slot only reads it while rendering. Facts it cannot give stay absent. */
export type CardRole = 'manager' | 'business' | 'technical';
export interface TaskCardFacts {
  /** Tests run for this task. */
  tests: number;
  /** True only when the task has tests and none of them ran on the current policy version. */
  testsPredatePolicy: boolean;
  /** Colleagues with an open reminder on this task, once each, in the order given. */
  reminders: readonly CardRole[];
  /** The last delivery's work for this task is where its revision starts. */
  reviseHere?: boolean;
  /** The current policy version, to name it in the stale-test flag. */
  policyVersion?: number;
  /** Whose request a starting task is, from its own brief. */
  requestedBy?: CardRole;
  /** A question was asked in this task's context. */
  asked?: boolean;
}
type Provider = (taskId: string) => TaskCardFacts | null;
let provider: Provider | null = null;

export function provideTaskCardFacts(next: Provider | null) {
  provider = next;
}
export function taskCardFacts(taskId: string): TaskCardFacts | null {
  try {
    return provider?.(taskId) ?? null;
  } catch {
    return null;
  }
}

/** The tests of one task, read against the current policy version. A test that ran on the
 * current version means the task's evidence is not stale, whatever older runs exist. */
export function testFacts(
  tests: readonly { taskId?: string | null; policyVersion?: number | null }[],
  taskId: string,
  policyVersion: number | null | undefined,
): Pick<TaskCardFacts, 'tests' | 'testsPredatePolicy'> {
  const mine = tests.filter((test) => test.taskId === taskId);
  const known = mine.filter((test) => Number.isFinite(test.policyVersion));
  return {
    tests: mine.length,
    testsPredatePolicy:
      Number.isFinite(policyVersion) &&
      known.length > 0 &&
      known.length === mine.length &&
      known.every((test) => Number(test.policyVersion) < Number(policyVersion)),
  };
}

/** The progress circle: done when done, half once anything is on record for the task (the server
 * says it is active, or it has work, tests or a question), otherwise empty. */
export function taskProgress(
  status: string | undefined,
  record: { works: number; tests?: number; asked?: boolean },
): 'open' | 'working' | 'done' {
  if (status === 'done') return 'done';
  if (status === 'active' || record.works > 0 || (record.tests ?? 0) > 0 || record.asked)
    return 'working';
  return 'open';
}
/** Who appears at the card's foot, once each: whose request it is, then who left a reminder. */
export function cardPeople(
  facts: Pick<TaskCardFacts, 'requestedBy' | 'reminders'> | null,
): { role: CardRole; why: 'asked' | 'reminder' }[] {
  const out: { role: CardRole; why: 'asked' | 'reminder' }[] = [];
  if (facts?.requestedBy) out.push({ role: facts.requestedBy, why: 'asked' });
  for (const role of facts?.reminders ?? [])
    if (!out.some((p) => p.role === role)) out.push({ role, why: 'reminder' });
  return out;
}
