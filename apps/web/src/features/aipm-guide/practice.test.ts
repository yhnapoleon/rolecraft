import { describe, expect, it, vi } from 'vitest';
import { installAipmFeatures } from '../../aipm/registry';
import { createAipmPractice, type PracticeDeps } from './practice';

const deps = (transport = vi.fn(async () => ({}))): PracticeDeps => ({
  current: () => ({ id: 's1' }),
  transport: () => transport,
  dataHost: () => null,
  language: () => 'zh',
  redraw: () => {},
  openMaterial: () => {},
  openChat: () => {},
  ask: () => {},
  openWork: () => {},
  openSettings: () => {},
  submit: () => {},
  notifyDraft: () => {},
  prefillColleague: () => {},
  prdSharedWith: () => false,
  rememberPrompts: () => {},
  showBoard: () => {},
  openProduct: () => {},
  newFreeSheet: () => {},
  materialHtml: () => '',
  quoteToSheet: () => {},
});

describe('AIPM practice host', () => {
  it('sends a prepared tests.create command verbatim', async () => {
    const transport = vi.fn(async () => ({ ok: true }));
    const { host } = createAipmPractice(deps(transport));
    const command = {
      operation: 'tests.create',
      request_id: 'r-1',
      payload: { question: 'q' },
    };
    await host.sendPreparedTest(command);
    expect(transport).toHaveBeenCalledWith('/sessions/s1/tests', command, 'POST');
    await expect(
      host.sendPreparedTest({ operation: 'turns.create', request_id: 'r' }),
    ).rejects.toThrow();
  });
  it('reports features whose owning line has not installed them', async () => {
    const { host } = createAipmPractice(deps());
    const missing = await installAipmFeatures(host);
    expect(
      missing.every((id) => ['design', 'evaluation', 'worksheet', 'review'].includes(id)),
    ).toBe(true);
  });
  it('an old practice without the client stays on its original page', () => {
    const p = createAipmPractice(deps());
    expect(p.ready({ id: 's1' })).toBe(false);
  });
});
