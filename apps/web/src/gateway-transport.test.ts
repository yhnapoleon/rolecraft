import { describe, it, expect, vi } from 'vitest';
import { createGatewayTransport } from './gateway-transport';

const credentials = { sessionId: 's', token: 'synthetic-token' };
const command = { schema_version: 2, request_id: 'same-key', operation: 'work_items.update', expected_version: 0, expected_workspace_revision: 1, payload: { item_id: 't', expected_revision: 1, title: 'new' } };
const wire = { schema_version: 2, transaction_id: 'txn', boundary: { request_id: 'same-key' }, state: { storage_revision: 2 }, objects: [], events: [], result: { object: { id: 't' } }, replayed: false };
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });

describe('native workbench Gateway transport', () => {
  it('keeps PATCH command identity and the full public transaction, without adding defaults or retrying', async () => {
    const fetcher = vi.fn<typeof fetch>(async () => response(wire));
    const send = createGatewayTransport(() => credentials, fetcher);
    const before = structuredClone(command);
    expect(await send('/sessions/s/work-items/t', command, 'PATCH')).toEqual(wire);
    expect(await send('/sessions/s/work-items/t', command, 'PATCH')).toEqual(wire);
    expect(command).toEqual(before);
    expect(fetcher.mock.calls.map(c => c[1]?.body)).toEqual([JSON.stringify(command), JSON.stringify(command)]);
    expect(fetcher.mock.calls[0][1]).toMatchObject({ method: 'PATCH', redirect: 'error', credentials: 'omit', cache: 'no-store' });
  });

  it('preserves read wrappers and re-reads credentials from the existing session owner', async () => {
    let token = 'first';
    const page = { schema_version: 2, result: { items: [], next_cursor: null } };
    const fetcher = vi.fn<typeof fetch>(async () => response(page));
    const send = createGatewayTransport(() => ({ ...credentials, token }), fetcher);
    expect(await send('/sessions/s/work-items?cursor=0')).toEqual(page);
    token = 'updated'; await send('/sessions/s/work-items');
    expect(fetcher.mock.calls[1][1]?.headers).toEqual({ Authorization: 'Bearer updated' });
  });

  it.each(['/sessions/other/work-items', '/sessions/s/../other/work-items', '/sessions/s/%2e%2e/other', '/sessions/s/%2fother', '//other/sessions/s/work-items', '/sessions/s/work-items#ignored'])('rejects an unsafe or cross-session route before networking: %s', async path => {
    const fetcher = vi.fn<typeof fetch>(); const send = createGatewayTransport(() => credentials, fetcher);
    await expect(send(path)).rejects.toMatchObject({ code: 'session_route_mismatch' });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('rejects missing envelopes without silently manufacturing v2 requests', async () => {
    const fetcher = vi.fn<typeof fetch>(); const send = createGatewayTransport(() => credentials, fetcher);
    const { schema_version, ...old } = command;
    await expect(send('/sessions/s/work-items/t', old, 'PATCH')).rejects.toMatchObject({ code: 'invalid_command', status: 400 });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each(['detail', 'error'])('keeps a definite version rejection distinguishable via %s', async field => {
    const fetcher = vi.fn<typeof fetch>(async () => response({ code: 'object_version_conflict', [field]: 'Reload current version' }, 409));
    const send = createGatewayTransport(() => credentials, fetcher);
    await expect(send('/sessions/s/work-items/t', command, 'PATCH')).rejects.toMatchObject({ status: 409, code: 'object_version_conflict', message: 'Reload current version' });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it.each(['network', 'invalid-json', 'legacy-shape'])('preserves ambiguous outcomes without retry: %s', async kind => {
    const fetcher = vi.fn<typeof fetch>(async () => {
      if (kind === 'network') throw new TypeError('network');
      if (kind === 'invalid-json') return new Response('incomplete');
      return response({ saved: true });
    });
    const send = createGatewayTransport(() => credentials, fetcher);
    await expect(send('/sessions/s/work-items/t', command, 'PATCH')).rejects.toMatchObject({ status: 0, code: 'response_unconfirmed' });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});


const api = process.env.ROLECRAFT_TEST_API;
it.skipIf(!api)('sends a native PATCH through a real frozen Gateway and recovers its original request', async () => {
  const created = await fetch(api + '/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ schema_version: 2, scenario: 'w14-wire-contract' }) }).then(r => r.json());
  expect(created.schema_version).toBe(2);
  const creds = { sessionId: created.session_id, token: created.token };
  const fetcher: typeof fetch = (input, init) => fetch(api + String(input).replace(/^\/api/, ''), init);
  const send = createGatewayTransport(() => creds, fetcher);
  const make = { schema_version: 2, request_id: 'task-create', operation: 'work_items.create', expected_version: 0, expected_workspace_revision: 0, payload: { title: 'Transport verification' } };
  const initial: any = await send('/sessions/' + creds.sessionId + '/work-items', make);
  const ref = initial.objects[0];
  const edit = { ...make, request_id: 'task-edit', operation: 'work_items.update', expected_workspace_revision: 1, payload: { item_id: ref.object_id, expected_revision: 1, title: 'Saved through PATCH' } };
  const path = '/sessions/' + creds.sessionId + '/work-items/' + ref.object_id;
  const changed: any = await send(path, edit, 'PATCH');
  expect(changed.boundary.request_id).toBe('task-edit');
  expect(changed.objects[0].version).toBe(2);
  expect((await send(path, edit, 'PATCH') as any).replayed).toBe(true);
  const receipt: any = await send('/sessions/' + creds.sessionId + '/requests/task-edit');
  expect(receipt.response.transaction_id).toBe(changed.transaction_id);
  await expect(send(path, { ...edit, request_id: 'stale-edit' }, 'PATCH')).rejects.toMatchObject({ status: 409, code: 'version_conflict' });
  await expect(send(path, { ...edit, request_id: 'wrong-operation', operation: 'work_products.create' }, 'PATCH')).rejects.toMatchObject({ status: 403, code: 'operation_route_mismatch' });
});
