/** Test-only boundary for legacy envelopes and deliberately malformed host responses.
 * Production code must use V4HostAdapter directly; fixtures retain unknown wire values
 * so the real feature parsers and recovery guards, rather than casts, are exercised. */
import type { V4HostAdapter, V4CommandResult } from './v4-host';

export type HostFixture = Omit<V4HostAdapter, 'query' | 'command' | 'recover' | 'retry'> & {
  query(operation: string, input?: Readonly<Record<string, unknown>>): Promise<unknown>;
  command(operation: string, input: Readonly<Record<string, unknown>>): Promise<V4CommandResult>;
  recover(requestId: string): Promise<V4CommandResult>;
  retry(requestId: string): Promise<V4CommandResult>;
};

export function fixtureHost(fixture: HostFixture): V4HostAdapter {
  // This is intentional fault injection at a test seam, not a production decoder.
  return fixture as V4HostAdapter;
}
