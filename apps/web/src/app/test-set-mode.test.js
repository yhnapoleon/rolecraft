import { afterEach, describe, expect, it } from 'vitest';
import { ASSISTANT_COPY } from './assistant-mode';
import { setPreference } from './i18n';
import { testRunView } from './test-set-view.js';

// Rendered as strings: the unit environment has no DOM, so markup is inspected directly.
const count = (text, part) => text.split(part).length - 1;
const between = (html, start, end) => html.slice(html.indexOf(start) + start.length).split(end)[0];

afterEach(() => setPreference('zh'));

describe('test-plan result mode row', () => {
  it('renders one mode row in a saved test-plan result, with no answer prefix', () => {
    for (const language of ['zh', 'en']) {
      setPreference(language);
      const run = {
        id: 'saved',
        answer: 'Original passage',
        caseRevision: 1,
        configVersion: 3,
        policyVersion: 1,
        indexVersion: 1,
        mode: 'extractive',
        assistant: 'waiting_model',
        effectiveConfig: { generator: 'extractive', update_strategy: 'daily' },
        citations: [{ id: 'policy', version: 1, title: 'Travel policy' }],
      };
      const view = (overrides) =>
        testRunView({
          run: { ...run, ...overrides },
          runs: [run],
          item: { id: 'case', revision: 1 },
          work: { adopted: true },
          session: { testNotes: {}, world: { status: 'active' } },
          md: (value) => value,
        });
      const html = view({});
      expect(count(html, ASSISTANT_COPY[language].assistant_mode_waiting)).toBe(1);
      expect(count(html, 'class="test-generation-label"')).toBe(1);
      expect(between(html, '<div class="test-answer prose">', '</div>')).toBe('Original passage');
      expect(html).toContain(
        `<summary>${ASSISTANT_COPY[language].assistant_mode_effective_config} · v3</summary>`,
      );
      const generated = view({
        mode: 'llm',
        generation: { provider: 'openai', model_revision: 'm1' },
      });
      expect(between(generated, 'class="test-generation-label"', '</span>')).toContain(
        ASSISTANT_COPY[language].assistant_mode_llm,
      );
      expect(generated).toContain('openai / m1');
      expect(count(generated, ASSISTANT_COPY[language].assistant_mode_waiting)).toBe(0);
    }
  });
});
