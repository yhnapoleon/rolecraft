import { describe, expect, it } from 'vitest';
import { splitRecognitionPrefix } from './prefix';

describe('recognition prefix in reviewer explanations', () => {
  it('strips the Chinese agreement prefix and keeps it as a tag', () => {
    expect(splitRecognitionPrefix('[识别一致] 本文对试点决策给出了多个可核验的指标。')).toEqual({
      text: '本文对试点决策给出了多个可核验的指标。',
      tag: 'agree',
      reason: null,
      arbiter: null,
    });
  });

  it('strips the Chinese disagreement prefix and keeps its reason', () => {
    const split = splitRecognitionPrefix(
      '[与识别不一致：识别器将多数逐句判定为insufficient，但综合作品文本可核准] 作品引用并复现了失败案例。',
    );
    expect(split.text).toBe('作品引用并复现了失败案例。');
    expect(split.tag).toBe('disagree');
    expect(split.reason).toBe('识别器将多数逐句判定为insufficient，但综合作品文本可核准');
  });

  it('strips the Chinese missing prefix', () => {
    expect(splitRecognitionPrefix('[识别缺失]识别结果未覆盖这一项，故自行核验。')).toMatchObject({
      text: '识别结果未覆盖这一项，故自行核验。',
      tag: 'missing',
    });
  });

  it('strips the English prefixes in any letter case', () => {
    expect(splitRecognitionPrefix('[recognition agrees] The plan names its metrics.')).toMatchObject({
      text: 'The plan names its metrics.',
      tag: 'agree',
    });
    expect(splitRecognitionPrefix('[Recognition missing] Judged on its own.')).toMatchObject({
      text: 'Judged on its own.',
      tag: 'missing',
    });
    expect(
      splitRecognitionPrefix('[disagrees with recognition: most sentences were marked insufficient] It separates facts.'),
    ).toEqual({
      text: 'It separates facts.',
      tag: 'disagree',
      reason: 'most sentences were marked insufficient',
      arbiter: null,
    });
  });

  it('accepts full-width brackets and an ASCII colon', () => {
    expect(splitRecognitionPrefix('【与识别不一致: 原因】正文')).toMatchObject({
      text: '正文',
      tag: 'disagree',
      reason: '原因',
    });
  });

  it('moves the arbiter sentence written in front of the prefix out of the text', () => {
    const split = splitRecognitionPrefix(
      '仲裁：识别器 PARTIAL / 评审 MET，取保守 PARTIAL。[与识别不一致：原因] 正文。',
    );
    expect(split.text).toBe('正文。');
    expect(split.tag).toBe('disagree');
    expect(split.arbiter).toBe('仲裁：识别器 PARTIAL / 评审 MET，取保守 PARTIAL。');
    const en = splitRecognitionPrefix(
      'Arbiter: recognizer PARTIAL / reviewer MET; kept the conservative PARTIAL. [recognition agrees] Body.',
    );
    expect(en.text).toBe('Body.');
    expect(en.arbiter).toBe('Arbiter: recognizer PARTIAL / reviewer MET; kept the conservative PARTIAL.');
  });

  it('leaves text without a prefix as written', () => {
    const text = '模型建议的引用已定位，支持关系仍待核验；[识别一致] 只出现在句中时不动。';
    expect(splitRecognitionPrefix(text)).toEqual({ text, tag: null, reason: null, arbiter: null });
  });
});
