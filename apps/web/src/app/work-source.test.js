import { describe, expect, it } from 'vitest';
import { workSourceLabel } from './work-source';
describe('saved author provenance after adoption', () => {
  it.each([['zh', 'Agent 制作 · 本人采用'], ['en', 'Made by an Agent · Adopted by you']])('keeps a direct MCP return without a browser transfer link (%s)', (language, expected) => {
    expect(workSourceLabel({source:'external-agent', adopted:true}, language, 'external_agent')).toBe(expected);
  });
  it('keeps human imports distinct from Agent authorship', () => {
    expect(workSourceLabel({source:'external-agent', adopted:true}, 'en', 'human')).toBe('Imported work');
    expect(workSourceLabel({source:'user', adopted:true}, 'en', 'human')).toBe('By you');
  });
});
