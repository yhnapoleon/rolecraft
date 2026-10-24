import { describe, expect, it } from 'vitest';
import { termName, termPieces } from './config-terms';

const read = (s: string) =>
  termPieces(s)
    .map((p) => (typeof p === 'string' ? p : p.name))
    .join('');
const keys = (s: string) => termPieces(s).flatMap((p) => (typeof p === 'string' ? [] : [p.key]));

// Config keys in a Chinese reply read in the settings panel's words; the key stays for the title.
describe('config terms', () => {
  it('names the keys a reply quotes and drops the spaces that set them apart', () => {
    const s =
      '人工兜底要选human并含human_fallback工作项；（fallback 为 human、包含 human_fallback 工作项）';
    expect(read(s)).toBe(
      '人工兜底要选转人工确认并含人工入口工作项；（答不了或不确定时为转人工确认、包含人工入口工作项）',
    );
    expect(keys(s)).toEqual(['human', 'human_fallback', 'fallback', 'human', 'human_fallback']);
  });

  it('keeps a space next to English text', () => {
    expect(read('use scope_filter now')).toBe('use 知识范围过滤 now');
  });

  it('leaves unknown words and parts of words alone', () => {
    expect(read('humanity 和 my_fallback_x 不动')).toBe('humanity 和 my_fallback_x 不动');
    expect(termPieces('没有键名')).toEqual(['没有键名']);
  });

  it('names a key written on its own', () => {
    expect(termName(' realtime_sync ')).toBe('实时同步');
    expect(termName('other_key')).toBeNull();
  });
});
