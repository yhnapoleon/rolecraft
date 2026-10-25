import { afterEach, expect, it } from 'vitest';
import { setPreference } from '../../app/i18n';
import type { AgentEvent } from '../../shell/agent-bus';
import { agentLine } from './agent-line';
afterEach(() => setPreference('zh'));
const empty = { exports: [], artifacts: [] };
const events: AgentEvent[] = [
  'engineer.reproduce',
  'engineer.trial',
  'engineer.submissions.draft',
].map((tool, i) => ({
  id: String(i),
  at: `2026-10-25T01:00:0${i}Z`,
  tool,
  direction: 'to_workspace',
  status: 'ok',
  verb: ['完成', 'Done'],
}));
it('214 engineering returns are visible even without PM packages or products, including loaded history', () => {
  setPreference('en');
  expect(agentLine(empty, 'engineer', { state: 'connected', client: 'Claude Code' }, events)).toBe(
    'Drafted a sign-off',
  );
  setPreference('zh');
  expect(agentLine(empty, 'engineer', { state: 'idle' }, events)).toBe('已起草签字单');
});
it('214 a connected engineer never reads as having no handover; failed calls do not imply success', () => {
  setPreference('en');
  expect(agentLine(empty, 'engineer', { state: 'connected', client: 'Claude Code' }, [])).toBe(
    'Claude Code · connected',
  );
  expect(
    agentLine(empty, 'engineer', { state: 'connected' }, [{ ...events[2], status: 'error' }]),
  ).toBe('Connected');
});
it('214 product-manager package and return counts stay intact', () => {
  setPreference('en');
  expect(
    agentLine(
      { exports: [{}], artifacts: [{ source: 'external-agent' }] },
      'pm',
      { state: 'connected' },
      events,
    ),
  ).toBe('1 handed over, 1 returned');
  expect(agentLine(empty, 'pm', { state: 'none' }, [])).toBe('Nothing handed over yet');
});
