import { describe, expect, it } from 'vitest';
import type { WorkProductVersion } from './contracts-v2';
import { productBody } from './v4-workspace-projection';

describe('structured work preview', () => {
  it.each(['zh', 'en'])('renders all seven saved sections and exact quotations in %s', (language) => {
    const sections = Object.fromEntries(['business', 'stakeholders', 'need', 'boundary', 'solution', 'assurance', 'decision'].map((key) => [key, `Saved ${key}\n> Exact quotation\n> — Source v1`]));
    const p = { content: '', structured_payload: { type: 'plan', sections } } as WorkProductVersion;
    const text = productBody(p, language);
    for (const body of Object.values(sections)) expect(text).toContain(body);
    expect(text).toContain(language === 'en' ? '## Pilot decision' : '## 试点决定');
  });
  it('keeps a supplied body verbatim and supports other structured text', () => {
    expect(productBody({ content: ' original ', structured_payload: { type: 'text', body: 'other' } } as WorkProductVersion, 'en')).toBe(' original ');
    expect(productBody({ content: '', structured_payload: { type: 'text', body: 'text body' } } as WorkProductVersion, 'en')).toBe('text body');
    expect(productBody({ content: '', structured_payload: { type: 'options', options: [{title: 'A', rationale: 'Because', tradeoffs: ['Cost']}] } } as WorkProductVersion, 'en')).toBe('A\nBecause\nCost');
  });
});
