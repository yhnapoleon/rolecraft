import { describe, expect, it } from 'vitest';
import { ApiError } from '../../api';
import { engineerApi, failureText } from './api';

type Call = { path: string; body?: unknown };

function fakeTransport(responses: Record<string, unknown>) {
  const calls: Call[] = [];
  const transport = async (path: string, body?: unknown) => {
    calls.push({ path, body });
    const key = `${body === undefined ? 'GET' : 'POST'} ${path}`;
    if (!(key in responses)) throw new ApiError('nope', 404, 'not_found');
    return responses[key];
  };
  return { calls, transport };
}

const S = '/sessions/s%201';
const state = { schema_version: 2, state: { business_seq: 7, workspace_revision: 3 } };

describe('engineer desk · API client', () => {
  it('ED-40 writes carry the standard command envelope with the current point', async () => {
    const { calls, transport } = fakeTransport({
      [`GET ${S}`]: state,
      [`POST ${S}/engineer/tickets`]: {
        schema_version: 2,
        result: { ticket: { id: 't' }, created: true },
      },
      [`POST ${S}/engineer/tickets/t/trials`]: {
        schema_version: 2,
        result: { trial: { id: 'x' } },
      },
    });
    const api = engineerApi(transport, 's 1');
    expect(await api.createTicket({ from: 'seeded' })).toEqual({
      ticket: { id: 't' },
      created: true,
    });
    const trial = await api.trial('t', { freshness_guard: 'warn' });
    expect(trial).toEqual({ id: 'x' });
    const sent = calls.filter((c) => c.body) as { path: string; body: Record<string, unknown> }[];
    expect(sent[0].body).toMatchObject({
      schema_version: 2,
      operation: 'engineer.tickets.create',
      payload: { from: 'seeded' },
      expected_version: 7,
      expected_workspace_revision: 3,
    });
    expect(typeof sent[0].body.request_id).toBe('string');
    expect(sent[1].body).toMatchObject({
      operation: 'engineer.trial',
      payload: { ticket_id: 't', changes: { freshness_guard: 'warn' } },
    });
  });

  it('ED-41 reads unwrap the result; a review list can be narrowed to one ticket', async () => {
    const { calls, transport } = fakeTransport({
      [`GET ${S}/engineer/tickets/t%2F1`]: { schema_version: 2, result: { ticket: { id: 't/1' } } },
      [`GET ${S}/engineer/reviews?ticket_id=t%2F1`]: { schema_version: 2, result: { reviews: [] } },
      [`GET ${S}/engineer/reviews/r`]: {
        schema_version: 2,
        result: { review: { review_id: 'r' } },
      },
    });
    const api = engineerApi(transport, 's 1');
    expect(await api.ticket('t/1')).toEqual({ id: 't/1' });
    expect(await api.reviews('t/1')).toEqual([]);
    expect(await api.review('r')).toEqual({ review_id: 'r' });
    expect(calls.every((c) => c.body === undefined)).toBe(true);
  });

  it('ED-42 a refusal becomes one plain sentence from its code', () => {
    expect(failureText(new ApiError('x', 409, 'engineer_review_budget_exhausted'))).toBe(
      '这份委托的 3 次复核已经用完。',
    );
    expect(failureText(new Error('boom'))).toBe('没有完成，输入还在，可以再试一次。');
  });
});
