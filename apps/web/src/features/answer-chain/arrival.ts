/** A queued test that settles in the background (276-07): which result the page selects, and
 * whether the stage redraws even though a document sheet is open. */
export type Settled = { caseId: string | null; testId: string };
type Selection = {
  testHistory: Record<string, string>;
  testModes: Record<string, string>;
  lastRun: string | null;
  settledRun: string | null;
};

/** Select the arrived result where it was asked: the test case shows its result, the bench
 * marks it as the latest run. */
export function selectSettled(ui: Selection, settled: Settled) {
  if (settled.caseId) {
    ui.testHistory[settled.caseId] = settled.testId;
    ui.testModes[settled.caseId] = 'result';
  }
  ui.lastRun = settled.testId;
  ui.settledRun = settled.testId;
}

/** An open document holds the board as it is, except once for a settled run that is now loaded. */
export function holdsStageUnderDocument(
  ui: Pick<Selection, 'settledRun'>,
  tests: { id: string }[],
  documentOpen: boolean,
) {
  if (!documentOpen) return false;
  return !(ui.settledRun && tests.some((t) => t.id === ui.settledRun));
}
