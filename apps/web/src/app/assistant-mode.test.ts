import { afterEach, describe, expect, it } from 'vitest';
import {
  ASSISTANT_COPY,
  answerModeLabel,
  answerModeLine,
  generatorField,
  quotedAnswer,
  submittedGenerator,
} from './assistant-mode';
import { setPreference } from './i18n';

// Rendered as strings: the unit environment has no DOM, so markup is inspected directly.
const count = (text: string, part: string) => text.split(part).length - 1;
const input = (html: string, value: string) =>
  html.match(new RegExp(`<input[^>]*name="generator" value="${value}"[^>]*>`))?.[0] ?? '';

afterEach(() => setPreference('zh'));

describe('assistant answer modes', () => {
  it('keeps identical Chinese and English copy keys', () => {
    expect(Object.keys(ASSISTANT_COPY.en).sort()).toEqual(Object.keys(ASSISTANT_COPY.zh).sort());
    for (const language of ['zh', 'en'] as const)
      for (const value of Object.values(ASSISTANT_COPY[language]))
        expect(value.trim()).not.toBe('');
  });

  it.each([
    ['zh', '原文抽取', '原文抽取', '模型生成 · 回答待核验'],
    ['en', 'Extractive', 'Extractive', 'Model-generated · Answer awaiting verification'],
  ] as const)(
    'labels each saved mode in %s from the record',
    (language, waiting, extractive, llm) => {
      setPreference(language);
      // Waiting for a model keeps the saved mode's words; the grey mark says the rest.
      expect(answerModeLabel({ mode: 'extractive', assistant: 'waiting_model' })).toMatchObject({
        text: waiting,
        waiting: true,
      });
      expect(answerModeLabel({ mode: 'extractive', assistant: 'model' }).waiting).toBe(false);
      expect(answerModeLabel({ mode: 'extractive', assistant: 'model' }).text).toBe(extractive);
      // A generated answer stays generated even after the deployment loses its model.
      expect(answerModeLabel({ mode: 'llm', assistant: 'waiting_model' }).text).toBe(llm);
      expect(answerModeLabel({ mode: 'llm', assistant: 'model' }).text).toBe(llm);
      expect(answerModeLabel({ mode: 'unavailable', assistant: 'waiting_model' }).mode).toBe(
        'unavailable',
      );
      expect(answerModeLabel({ mode: 'failed', assistant: 'model' }).mode).toBe('failed');
      expect(answerModeLabel({ mode: 'waiting_model' }).mode).toBe('unknown');
    },
  );

  it('shows the waiting label exactly once and leaves records without a v2 mode unlabelled', () => {
    for (const language of ['zh', 'en'] as const) {
      setPreference(language);
      const html = answerModeLine({ mode: 'extractive', assistant: 'waiting_model' });
      expect(count(html, 'class="answer-mode"')).toBe(1);
      expect(count(html, ASSISTANT_COPY[language].assistant_mode_waiting)).toBe(1);
      expect(count(html, 'data-model-wait')).toBe(1);
      expect(html).toContain('data-answer-mode="extractive"');
      expect(answerModeLine({ mode: 'local' })).toBe('');
    }
  });
});

describe('quoted answers', () => {
  it.each(['zh', 'en'] as const)('keeps the generated marker in quotes in %s', (language) => {
    setPreference(language);
    const marker = ASSISTANT_COPY[language].assistant_quote_generated;
    expect(quotedAnswer({ mode: 'llm', answer: 'Generated text' })).toBe(
      `${marker} Generated text`,
    );
    expect(quotedAnswer({ mode: 'llm' }, 'Shortened')).toBe(`${marker} Shortened`);
    expect(quotedAnswer({ mode: 'extractive', answer: 'Source passage' })).toBe('Source passage');
    expect(quotedAnswer({ mode: 'failed', answer: 'Failure text' })).toBe('Failure text');
  });
});

describe('generator setting', () => {
  it('shows model generation as unavailable without a connected model', () => {
    for (const language of ['zh', 'en'] as const) {
      setPreference(language);
      const html = generatorField('extractive', 'waiting_model');
      expect(input(html, 'extractive')).toContain(' checked');
      expect(input(html, 'extractive')).not.toContain(' disabled');
      expect(input(html, 'llm')).toContain(' disabled');
      expect(html).toContain(`>${ASSISTANT_COPY[language].generator_unavailable}</p>`);
      expect(html).toContain(`<legend>${ASSISTANT_COPY[language].generator_legend}</legend>`);
    }
  });

  it('lets a connected deployment choose either generator', () => {
    const html = generatorField('llm', 'model');
    expect(input(html, 'llm')).toContain(' checked');
    expect(input(html, 'llm')).not.toContain(' disabled');
    expect(html).not.toContain('data-state=');
  });

  it('keeps a saved llm choice visible and resettable when the model is gone', () => {
    const html = generatorField('llm', 'waiting_model');
    expect(input(html, 'llm')).toContain(' checked');
    expect(input(html, 'llm')).not.toContain(' disabled');
    expect(input(html, 'extractive')).not.toContain(' disabled');
    expect(html).toContain('data-state="stuck"');
  });

  it('submits the visible choice and never invents a hidden change', () => {
    const form = (value?: string) => {
      const data = new FormData();
      if (value) data.set('generator', value);
      return data;
    };
    expect(submittedGenerator(form('extractive'), 'llm')).toBe('extractive');
    expect(submittedGenerator(form('llm'), 'extractive')).toBe('llm');
    expect(submittedGenerator(form(), 'llm')).toBe('llm');
    expect(submittedGenerator(form('other'), 'extractive')).toBe('extractive');
  });
});
