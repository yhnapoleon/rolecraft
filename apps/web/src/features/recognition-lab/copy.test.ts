import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { COPY } from './copy';
import { RESULT_FILES, type Results } from './data';
import { fill } from './figures';
import { REGISTER } from './register';
import { ENTRIES, storyHtml } from './story';
import { STORY_COPY } from './story-copy';

const published = (): Results =>
  Object.fromEntries(
    RESULT_FILES.map((name) => {
      try {
        const url = new URL(`../../../public/lab/${name}.json`, import.meta.url);
        return [name, JSON.parse(readFileSync(url, 'utf8'))];
      } catch {
        return [name, null];
      }
    }),
  );

describe('system profile copy', () => {
  it('pairs every Chinese line with an English one', () => {
    for (const table of [COPY, STORY_COPY]) {
      expect(Object.keys(table.en).sort()).toEqual(Object.keys(table.zh).sort());
      for (const lang of ['zh', 'en'] as const)
        for (const [key, text] of Object.entries(table[lang]))
          expect(text.trim(), `${lang}.${key}`).not.toBe('');
    }
  });

  it('uses the same placeholders in both languages', () => {
    const holes = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort();
    for (const table of [COPY, STORY_COPY])
      for (const key of Object.keys(table.zh) as (keyof typeof table.zh)[])
        expect(holes(table.en[key]), String(key)).toEqual(holes(table.zh[key]));
  });

  it('writes no figure into the experiment copy: every number comes from a result field', () => {
    for (const { entry } of ENTRIES)
      for (const step of ['q', 'how', 'found', 'use'])
        for (const lang of ['zh', 'en'] as const) {
          const text = (STORY_COPY[lang] as Record<string, string>)[`${entry.id}_${step}`];
          expect(text, `${entry.id}_${step}`).toBeDefined();
          // Decimals belong in placeholders. Two settings may be written out: the fusion
          // weight α = 0.4 and the cost of sending a claim to a person (0.5).
          const settings = text.replace(/α = 0\.4|送人工 0\.5|to a person 0\.5/g, '');
          expect(settings, `${lang}.${entry.id}_${step}`).not.toMatch(/\d\.\d/);
        }
  });
});

describe('figures on the page', () => {
  it('resolves every story figure from the published results', () => {
    const results = published();
    for (const { entry } of ENTRIES) expect(fill(results, entry.figures), entry.id).not.toBeNull();
  });

  it('resolves every recogniser figure from the published results', () => {
    const results = published();
    for (const row of REGISTER) expect(fill(results, row.figures), row.id).not.toBeNull();
  });

  it('fills the story without leftover placeholders in either language', () => {
    const results = published();
    for (const lang of ['zh', 'en'] as const) {
      const html = storyHtml(results, lang, 520);
      expect(html).not.toMatch(/\{\w+\}/);
      expect(html).not.toMatch(/undefined|NaN/);
      expect(html).toContain('E15');
    }
  });

  it('says a result is missing instead of drawing empty numbers', () => {
    const html = storyHtml({}, 'zh', 520);
    expect(html).toContain('这项实验的结果还没有发布到页面。');
    expect(html).not.toMatch(/\{\w+\}/);
  });
});
