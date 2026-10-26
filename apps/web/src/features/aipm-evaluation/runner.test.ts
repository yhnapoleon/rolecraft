import { describe, expect, it } from 'vitest';
import { SerialEvaluationRunner, type EvaluationRunnerPort, type RunnerBatch } from './runner';

function fixture() {
  let batch: RunnerBatch = {
    id: 'batch',
    revision: 1,
    cases: [
      { id: 'a', request_id: 'original-a', status: 'pending', original_command: null },
      { id: 'b', request_id: 'original-b', status: 'pending', original_command: null },
    ],
  };
  const submitted: unknown[] = [];
  const results = new Set<string>();
  const port: EvaluationRunnerPort = {
    read: async () => structuredClone(batch),
    prepare: async (_id, revision, caseId) => {
      expect(revision).toBe(batch.revision);
      const row = batch.cases.find((c) => c.id === caseId);
      if (!row) throw new Error('fixture case missing');
      const command = {
        schema_version: 2 as const,
        request_id: row.request_id,
        operation: 'tests.create',
        expected_version: 0,
        expected_workspace_revision: ++batch.revision,
        payload: { query: caseId, config_version: 0 },
      };
      row.original_command = command;
      return { batch: structuredClone(batch), command };
    },
    submit: async (command) => {
      submitted.push(command);
      results.add(command.request_id);
      throw Error('response lost');
    },
    reconcile: async (_id, _revision, caseId) => {
      const row = batch.cases.find((c) => c.id === caseId);
      if (!row) throw new Error('fixture case missing');
      if (results.has(row.request_id)) row.status = 'completed';
      batch = { ...batch, revision: batch.revision + 1 };
      return structuredClone(batch);
    },
  };
  return {
    port,
    submitted,
    get batch() {
      return batch;
    },
  };
}

describe('serial evaluation recovery', () => {
  it('recovers a lost response using the original request and never submits it twice', async () => {
    const f = fixture();
    await new SerialEvaluationRunner(f.port).continue('batch');
    await new SerialEvaluationRunner(f.port).continue('batch');
    expect(f.submitted).toHaveLength(2);
    expect(f.batch.cases.map((c) => c.status)).toEqual(['completed', 'completed']);
    expect(f.submitted.map((c) => (c as { request_id: string }).request_id)).toEqual([
      'original-a',
      'original-b',
    ]);
  });
});

it('does not send a prepared request after reopening, even when its outcome is unknown', async () => {
  const f = fixture();
  await f.port.prepare('batch', 1, 'a');
  const result = await new SerialEvaluationRunner(f.port).continue('batch');
  expect(result.reason).toBe('pending');
  expect(f.submitted).toHaveLength(0);
  expect(f.batch.cases[1].original_command).toBeNull();
});

it('stops between durable preparation and dispatch when the page closes', async () => {
  const f = fixture();
  const runner = new SerialEvaluationRunner(f.port);
  const prepare = f.port.prepare;
  f.port.prepare = async (...args) => {
    const result = await prepare(...args);
    runner.stop();
    return result;
  };
  expect((await runner.continue('batch')).reason).toBe('stopped');
  expect(f.submitted).toHaveLength(0);
  await new SerialEvaluationRunner(f.port).continue('batch');
  expect(f.submitted).toHaveLength(0);
});

it('stops after the first accepted request when the page closes', async () => {
  const f = fixture();
  const runner = new SerialEvaluationRunner(f.port);
  const submit = f.port.submit;
  f.port.submit = async (command) => {
    runner.stop();
    return submit(command);
  };
  expect((await runner.continue('batch')).reason).toBe('stopped');
  expect(f.submitted).toHaveLength(1);
  expect(f.batch.cases[1].original_command).toBeNull();
  // Reopen: reconcile the first request, then explicitly continue the second.
  f.port.submit = submit;
  await new SerialEvaluationRunner(f.port).continue('batch');
  expect(f.submitted).toHaveLength(2);
});

it('does not dispatch another case when the server reports changed conditions', async () => {
  const f = fixture();
  const reconcile = f.port.reconcile;
  f.port.reconcile = async (...args) => {
    const batch = await reconcile(...args);
    batch.pause_reason = 'baseline_changed';
    return batch;
  };
  expect((await new SerialEvaluationRunner(f.port).continue('batch')).reason).toBe('paused');
  expect(f.submitted).toHaveLength(1);
});

it('coalesces repeated continue clicks into one active sequence', async () => {
  const f = fixture();
  const runner = new SerialEvaluationRunner(f.port);
  const first = runner.continue('batch');
  expect(runner.continue('batch')).toBe(first);
  await first;
  expect(f.submitted).toHaveLength(2);
});

it('never dispatches after an uncertain prepare response', async () => {
  const f = fixture();
  const prepare = f.port.prepare;
  f.port.prepare = async (...args) => {
    await prepare(...args);
    throw Error('prepare response lost');
  };
  await expect(new SerialEvaluationRunner(f.port).continue('batch')).rejects.toThrow(
    'prepare response lost',
  );
  await new SerialEvaluationRunner(f.port).continue('batch');
  expect(f.submitted).toHaveLength(0);
});
