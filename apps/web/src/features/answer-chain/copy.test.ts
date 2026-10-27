import { describe, expect, it } from 'vitest';
import {
  CHAIN_COPY,
  STAGE_KEYS,
  guardText,
  methodText,
  offlineName,
  stageName,
  updateStrategyText,
} from './copy';

describe('answer chain copy', () => {
  it('pairs both languages key for key, with no Chinese in English', () => {
    expect(Object.keys(CHAIN_COPY.en).sort()).toEqual(Object.keys(CHAIN_COPY.zh).sort());
    for (const value of Object.values(CHAIN_COPY.en)) expect(value).not.toMatch(/[\u4e00-\u9fff]/);
  });

  it('names the five steps; the design calls the fifth "Who takes over"', () => {
    expect(STAGE_KEYS.map((k) => stageName(k, 'zh'))).toEqual([
      '能不能答',
      '找到什么',
      '资料新不新',
      '怎么答',
      '结果',
    ]);
    expect(STAGE_KEYS.map((k) => stageName(k, 'en'))).toEqual([
      'In scope?',
      'Found',
      'Up to date?',
      'Answer',
      'Result',
    ]);
    expect(stageName('result', 'zh', true)).toBe('答不了谁接');
    expect(stageName('result', 'en', true)).toBe('Who takes over');
    expect(stageName('scope', 'en', true)).toBe('In scope?');
    expect(offlineName('index', 'zh')).toBe('多久更新索引');
  });

  it('names setting values and returns null for unknown ones', () => {
    expect(updateStrategyText('daily', 'zh')).toEqual({
      value: '每日',
      note: '最长滞后 24 小时',
    });
    expect(updateStrategyText('weekly', 'en')).toBeNull();
    expect(guardText('fallback', 'en')).toBe('hand to a person');
    expect(guardText(undefined, 'en')).toBeNull();
  });

  it('names retrieval methods in product words only', () => {
    expect(methodText('rrf', false, 'en')).toBe('Semantic + keyword retrieval (fused)');
    expect(methodText('bm25', true, 'zh')).toBe('关键词检索（语义模型未加载）');
    expect(methodText(null, false, 'zh')).toBe('这条记录没有记下检索方法');
    for (const value of [...Object.values(CHAIN_COPY.zh), ...Object.values(CHAIN_COPY.en)])
      expect(value).not.toMatch(/\be5\b|BM25|置信度|confidence/i);
  });
});
