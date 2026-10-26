import { describe, expect, it, vi } from 'vitest';
import { installAipmFeatures } from '../../aipm/registry';
import { ApiError } from '../../api';
import { createAipmPractice, type PracticeDeps, withVersionRetry } from './practice';

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
  readMaterial: () => {},
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

describe('AIPM commands and a moved version point', () => {
  const moved = () => new ApiError('moved', 409, 'version_conflict');
  it('resends once, built afresh, and succeeds quietly', async () => {
    const send = vi.fn().mockRejectedValueOnce(moved()).mockResolvedValueOnce('ok');
    await expect(withVersionRetry(send)).resolves.toBe('ok');
    expect(send).toHaveBeenCalledTimes(2);
  });
  it('reports a second conflict', async () => {
    const send = vi.fn().mockRejectedValue(moved());
    await expect(withVersionRetry(send)).rejects.toMatchObject({ code: 'version_conflict' });
    expect(send).toHaveBeenCalledTimes(2);
  });
  it('never retries a content conflict', async () => {
    const send = vi
      .fn()
      .mockRejectedValue(new ApiError('edited', 409, 'aipm_design_revision_conflict'));
    await expect(withVersionRetry(send)).rejects.toMatchObject({
      code: 'aipm_design_revision_conflict',
    });
    expect(send).toHaveBeenCalledTimes(1);
  });
});
