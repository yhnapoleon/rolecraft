import type { V4HostAdapter } from './v4-host';

/** One data/journal owner; disposed surfaces cannot navigate or announce late results. */
export function surfaceHost(host: V4HostAdapter, active: () => boolean): V4HostAdapter {
  return {
    snapshot: () => host.snapshot(),
    subscribe: (callback) => host.subscribe(callback),
    query: (operation, input) => host.query(operation, input),
    command: (operation, input) => host.command(operation, input),
    recover: (requestId) => host.recover(requestId),
    retry: (requestId) => host.retry(requestId),
    draft: (slot, key) => host.draft(slot, key),
    keepDraft: (slot, key, value) => host.keepDraft(slot, key, value),
    flushDrafts: () => host.flushDrafts(),
    openReference: (reference) => host.openReference(reference),
    chooseEvidence: () => host.chooseEvidence(),
    selectTask: (reference) => {
      if (active()) host.selectTask(reference);
    },
    selectProduct: (reference) => {
      if (active()) host.selectProduct(reference);
    },
    announce: (message, kind) => {
      if (active()) host.announce(message, kind);
    },
  };
}
