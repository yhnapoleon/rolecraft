import { readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { ROUTES, STARTER_NEEDS } from './copy';

const content = resolve(__dirname, '../../../../../scenarios/pm_pilot/aipm-phase1/public');
const read = (language: 'zh' | 'en') =>
  JSON.parse(readFileSync(join(content, `design.${language}.json`), 'utf8'));

describe('AIPM design copy', () => {
  it.each([
    ['zh', 0],
    ['en', 1],
  ] as const)('mirrors public design content (%s)', (language, index) => {
    const data = read(language);
    expect(
      data.routes.map((r: { id: string; label: string; description: string }) => [
        r.id,
        r.label,
        r.description,
      ]),
    ).toEqual(Object.entries(ROUTES).map(([id, r]) => [id, r.label[index], r.description[index]]));
    expect(data.starter_needs).toEqual(
      STARTER_NEEDS.map((n) => ({ id: n.id, scope: n.scope, request: n.request[index] })),
    );
  });
  it('keeps English copy free of Chinese characters', () => {
    const english = JSON.stringify(
      Object.values(ROUTES).map((r) => [r.label[1], r.description[1]]),
    );
    expect(/[一-鿿]/.test(english)).toBe(false);
  });
  it('never references server-only grading files from the web feature', () => {
    for (const file of readdirSync(__dirname).filter(
      (f) => /\.(ts|tsx)$/.test(f) && !f.endsWith('.test.ts'),
    )) {
      expect(readFileSync(join(__dirname, file), 'utf8')).not.toMatch(
        /private\/grading|grading\/design/,
      );
    }
  });
});
