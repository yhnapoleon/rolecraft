import { describe, expect, it } from 'vitest';
import { resultWaitWords } from './result-head';

describe('result wait stages', () => {
  it('distinguishes an in-flight read from a reported generation job', () => {
    expect(resultWaitWords('zh', { reading: true })).toBe('交付已记录，正在读取反馈。');
    expect(resultWaitWords('en', {})).toBe('The delivery is recorded; feedback is not ready yet.');
    expect(resultWaitWords('en', { phase: 'running', reading: true })).toBe('The reviewer is writing the feedback.');
    expect(resultWaitWords('zh', { phase: 'queued' })).toBe('交付已记录，正在等待评审。');
  });
});
