/** Browser-owned orchestration only. The server owns snapshots and result verification. */
export type TestCommand = {
  schema_version: 2;
  request_id: string;
  operation: string;
  expected_version: number;
  expected_workspace_revision: number;
  payload: Record<string, unknown>;
};
export type RunnerCase = {
  id: string;
  request_id: string;
  status: 'pending' | 'completed' | 'execution_failed' | 'unsupported' | 'cancelled';
  original_command?: TestCommand | null;
};
/** A narrow projection consumed by the runner, not a second server DTO. */
export type RunnerBatch = {
  id: string;
  revision: number;
  pause_reason?: string | null;
  cases: RunnerCase[];
};
export interface EvaluationRunnerPort {
  read(id: string): Promise<RunnerBatch>;
  prepare(
    id: string,
    revision: number,
    caseId: string,
  ): Promise<{ batch: RunnerBatch; command: TestCommand }>;
  submit(command: TestCommand): Promise<unknown>;
  /** Server reads requests.read, verifies its test, and records only authoritative results. */
  reconcile(id: string, revision: number, caseId: string): Promise<RunnerBatch>;
}
export type RunStop = { batch: RunnerBatch; reason: 'complete' | 'paused' | 'pending' | 'stopped' };

export class SerialEvaluationRunner {
  private active: Promise<RunStop> | null = null;
  private stopped = false;
  constructor(private readonly port: EvaluationRunnerPort) {}

  /** Stop issuing new requests; an already accepted server job keeps its original identity. */
  stop() {
    this.stopped = true;
  }

  continue(id: string): Promise<RunStop> {
    if (this.active) return this.active;
    this.stopped = false;
    this.active = this.run(id).finally(() => {
      this.active = null;
    });
    return this.active;
  }

  private async run(id: string): Promise<RunStop> {
    let batch = await this.port.read(id);
    // A plan is bounded to 20 cases; no timers, background tasks or automatic retries.
    for (let count = 0; count < 20; count++) {
      if (this.stopped) return { batch, reason: 'stopped' };
      if (batch.pause_reason) return { batch, reason: 'paused' };
      const row = batch.cases.find((c) => c.status === 'pending');
      if (!row) return { batch, reason: 'complete' };
      if (!row.original_command) {
        const prepared = await this.port.prepare(id, batch.revision, row.id);
        batch = prepared.batch;
        if (this.stopped) return { batch, reason: 'stopped' };
        if (batch.pause_reason) return { batch, reason: 'paused' };
        const saved = batch.cases.find((c) => c.id === row.id)?.original_command;
        if (
          !saved ||
          saved.request_id !== row.request_id ||
          saved.operation !== 'tests.create' ||
          JSON.stringify(saved) !== JSON.stringify(prepared.command)
        ) {
          throw new Error('evaluation_command_unconfirmed');
        }
        try {
          // Send exactly the command saved by prepare, including its post-write version.
          await this.port.submit(saved);
        } catch {
          // A transport timeout is not execution failure. Never create another request.
        }
      }
      if (this.stopped) return { batch, reason: 'stopped' };
      batch = await this.port.reconcile(id, batch.revision, row.id);
      if (batch.pause_reason) return { batch, reason: 'paused' };
      if (batch.cases.find((c) => c.id === row.id)?.status === 'pending') {
        return { batch, reason: 'pending' };
      }
      // Refresh the authoritative snapshot before issuing another case.
      batch = await this.port.read(id);
    }
    return { batch, reason: 'complete' };
  }
}
