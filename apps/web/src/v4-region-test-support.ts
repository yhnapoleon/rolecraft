import { vi } from 'vitest';
import type { V4HostAdapter, V4HostSnapshot } from './v4-host';

export function regionHost(): V4HostAdapter {
  const snapshot: V4HostSnapshot = {
    session: { protocol: 2, sessionId: 's', workLanguage: 'en', scenarioHash: 'fixed' },
    uiLanguage: 'en',
    state: 'active',
    asOf: null,
    currentTask: null,
    currentProduct: null,
    busy: false,
    storageError: false,
    available: {},
  };
  return {
    snapshot: () => snapshot,
    subscribe: () => () => {},
    query: vi.fn<V4HostAdapter['query']>(),
    command: vi.fn(async () => ({
      requestId: 'original',
      status: 'confirmed' as const,
      result: {},
    })),
    recover: vi.fn(async () => ({
      requestId: 'original',
      status: 'confirmed' as const,
      result: {},
    })),
    retry: vi.fn(async () => ({ requestId: 'retry', status: 'pending' as const, result: {} })),
    draft: () => undefined,
    keepDraft: vi.fn(async () => {}),
    flushDrafts: vi.fn(async () => {}),
    openReference: vi.fn(async () => {}),
    chooseEvidence: vi.fn(async () => []),
    selectTask: vi.fn(),
    selectProduct: vi.fn(),
    announce: vi.fn(),
  };
}
