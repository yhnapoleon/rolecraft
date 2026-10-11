import { afterEach, describe, expect, it } from 'vitest';
import { ASSISTANT_COPY } from './assistant-mode';
import { setPreference } from './i18n';
import { investigationView } from './investigation-view.js';

// Rendered as strings: the unit environment has no DOM, so markup is inspected directly.
const count = (text, part) => text.split(part).length - 1;

function view(run, blocks) {
  return investigationView({
    work: {
      id: 'work',
      title: 'Check',
      revision: 1,
      adopted: true,
      evidence: [],
      question: 'Which version?',
      review: { focus: 'uncertain', note: '' },
      blocks,
    },
    attempt: {
      id: 'attempt',
      tests: [run],
      world: { policyVersion: 2, indexVersion: 1 },
      backend: { materials: [{ id: 'policy', title: 'Policy', version: 2 }] },
    },
    session: {},
    mutable: true,
    canRun: true,
    cache: {},
    md: (text) => String(text ?? ''),
    diffHtml: () => '',
    viewState: { modes: {}, open: {} },
  });
}

const run = (mode, assistant) => ({
  id: 'run',
  question: 'Hotel limit?',
  answer: 'Saved answer text',
  citations: [{ id: 'policy', title: 'Policy', version: 1 }],
  configVersion: 1,
  policyVersion: 2,
  indexVersion: 1,
  mode,
  assistant,
});
const source = {
  id: 'source',
  type: 'source_check',
  testId: 'run',
  material: { id: 'policy', version: 2 },
};
const compare = { id: 'compare', type: 'test_compare', testIds: ['run'] };

afterEach(() => setPreference('zh'));

describe('investigation worksheet answer modes', () => {
  it.each(['zh', 'en'])('labels the actual answer once per surface in %s', (language) => {
    setPreference(language);
    const copy = ASSISTANT_COPY[language];
    for (const block of [source, compare]) {
      const waiting = view(run('extractive', 'waiting_model'), [block]);
      expect(count(waiting, copy.assistant_mode_waiting)).toBe(1);
      expect(count(waiting, 'class="answer-mode"')).toBe(1);
      const generated = view(run('llm', 'model'), [block]);
      expect(count(generated, copy.assistant_mode_llm)).toBe(1);
      expect(count(generated, copy.assistant_mode_waiting)).toBe(0);
      const extractive = view(run('extractive', 'model'), [block]);
      expect(count(extractive, `>${copy.assistant_mode_extractive}</p>`)).toBe(1);
    }
  });
});
