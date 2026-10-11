import { describe, expect, it } from 'vitest';
import { evaluationVersionLine, evaluationVersionText } from './evaluation-version';

describe('saved report rubric version', () => {
  it.each([
    [
      'feedback-rubric-v2-final.1',
      '评价标准：rubric-v2 定稿（2026-10-09）',
      'Rubric: rubric-v2 final (2026-10-09)',
    ],
    [
      'feedback-rubric-v2-c2.1',
      '评价标准：rubric-v2 候选 2（定稿前）',
      'Rubric: rubric-v2 candidate 2 (pre-final)',
    ],
    [undefined, '评价标准版本：未记录', 'Rubric version: not recorded'],
    ['feedback-other.9', '评价标准：feedback-other.9', 'Rubric: feedback-other.9'],
  ])('names %s in both languages', (version, zh, en) => {
    expect(evaluationVersionText(version, 'zh')).toBe(zh);
    expect(evaluationVersionText(version, 'en')).toBe(en);
  });

  it('renders the stored provenance without inferring a missing version', () => {
    const doc = {
      createElement: () => ({ dataset: {} as Record<string, string> }),
    } as unknown as Document;
    const saved = evaluationVersionLine(
      doc,
      { id: 'f1', provenance: { evaluation_version: 'feedback-rubric-v2-c2.1' } },
      'en',
    );
    expect(saved.dataset.rubricVersion).toBe('feedback-rubric-v2-c2.1');
    expect(saved.textContent).toBe('Rubric: rubric-v2 candidate 2 (pre-final)');
    const old = evaluationVersionLine(doc, { id: 'f0' }, 'zh');
    expect(old.dataset.rubricVersion).toBe('not_recorded');
    expect(old.textContent).toBe('评价标准版本：未记录');
  });
});
