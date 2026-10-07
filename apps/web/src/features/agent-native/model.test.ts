import { describe, expect, it } from 'vitest';
import { activities, connections, grantInput, restoreDraft, returnedWorks, semanticLabel } from './model';
const r = { session_id: 's1', kind: 'material', object_id: 'm1', version: 2 } as const;
const grant = { id: 'd1', session_id: 's1', executor: { kind: 'external_agent', delegation_id: 'd1' }, capabilities: ['read'], expires_at: '2026-10-08T01:00:00Z', revoked: false };
describe('Agent slot public projection and domain inputs', () => {
  it('never infers an active connection from expiry or browser draft', () => {
    expect(connections({ items: [grant] }, 's1')[0].status).toBe('unknown');
    expect(connections({ items: [{ ...grant, effective_status: 'active' }] }, 's1')[0].status).toBe('active');
    expect(connections({ items: [{ ...grant, effective_status: 'active', revoked: true }] }, 's1')[0].status).toBe('revoked');
  });
  it('defaults to explicit read scope and never adds submit, request keys or versions', () => {
    const value = grantInput({ name: '我的 Codex', act: false, all: false, minutes: 30, refs: [r] }, 's1', new Date('2026-10-07T00:00:00Z'));
    expect(value).toEqual({ agent_label: '我的 Codex', capabilities: ['read'], expires_at: '2026-10-07T00:30:00.000Z', allowed_objects: ['m1'], create_under_tasks: [] });
    expect(() => grantInput({ name: 'Agent', act: true, all: false, minutes: 30, refs: [] }, 's1', new Date())).toThrow('agent_scope_required');
  });
  it('rejects foreign or private refs and mismatched delegated identities', () => {
    expect(() => connections({ items: [{ ...grant, session_id: 's2' }] }, 's1')).toThrow();
    expect(() => grantInput({ name: 'Agent', act: false, all: false, minutes: 30, refs: [{ ...r, session_id: 's2' }] }, 's1', new Date())).toThrow();
    expect(() => activities({ events: [{ id: 'e', session_id: 's1', type: 'read', executor: { kind: 'human' }, refs: [{ ...r, kind: 'role_context' }] }] }, 's1')).toThrow();
  });
  it('keeps only returned external work with authoritative version/adoption', () => {
    const item = { product_id: 'p', session_id: 's1', version: 3, author: { kind: 'external_agent' }, executor: { kind: 'human' }, title: 'Kept source words', adoption: { status: 'unadopted' }, removed_at: null };
    expect(returnedWorks({ schema_version: 2, result: { result: { items: [item, { ...item, removed_at: 'date' }] } } }, 's1')).toEqual([{ ref: { session_id: 's1', kind: 'product', object_id: 'p', version: 3 }, title: 'Kept source words', purpose: '', adoption: 'unadopted', semanticStatus: undefined, verification: undefined }]);
  });
  it('restores user draft and only a pointer to the host recovery record', () => {
    const draft = restoreDraft({ name: '中文 name', refs: [r], pending: { requestId: 'original', action: 'delegations.create', status: 'unconfirmed' }, token: 'not-copied', command: { bad: true } }, 's1');
    expect(draft.pending?.requestId).toBe('original'); expect(draft.name).toBe('中文 name');
    expect(JSON.stringify(draft)).not.toContain('not-copied'); expect(draft).not.toHaveProperty('command');
  });
  it('shows model/rule attribution only from explicit statuses and in both languages', () => {
    expect(semanticLabel('zh', 'placeholder')).toBe('等待模型接入');
    expect(semanticLabel('en', undefined, 'rule_verified')).toBe('Rule verified');
    expect(semanticLabel('en', undefined, 'unverified')).toBe('');
  });
});
