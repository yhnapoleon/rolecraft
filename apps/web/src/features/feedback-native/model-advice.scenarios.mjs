/** Model-advice states for the controlled fixture page (`review-check.html`), built from
 * recorded HTTP output: 148's normal serve+worker feedback (sentences, counts, the feedback
 * record) and 145/146 registration identities. Shared by the browser tests and screenshots. */
import { readFileSync } from 'node:fs';

export const recorded = JSON.parse(
  readFileSync(new URL('./model-advice.fixtures.json', import.meta.url), 'utf8'),
);

/** Advice as the consumer (148) writes it in each state, from the recorded sentences. */
export const scenarios = {
  synthetic: (language) => recorded.advice[language],
  external: (language) => ({
    ...recorded.advice[language],
    status: 'completed',
    error_code: null,
    registration: { ...recorded.identities.linear, scope: 'external_candidate' },
  }),
  fusion: (language) => ({
    ...recorded.advice[language],
    registration: recorded.identities.fusion,
  }),
  // The registration could not be loaded at start-up: no identity, no sentence was judged.
  loadFailed: (language) => ({
    ...recorded.advice[language],
    status: 'unavailable',
    registration: null,
    label: null,
    evidence_ids: [],
    citations: [],
    error_code: 'model_load_failed',
    units: undefined,
    aggregation: undefined,
  }),
  timeout: (language) =>
    notJudged(language, 'failed', 'model_timeout', {
      registration: { ...recorded.identities.linear, scope: 'external_candidate' },
    }),
  abstained: (language) =>
    notJudged(language, 'abstained', 'unit_exceeds_encoder_limit', {
      registration: recorded.identities.encoder,
    }),
};
function notJudged(language, unitStatus, reason, extra) {
  const advice = recorded.advice[language];
  return {
    ...advice,
    ...extra,
    status: unitStatus === 'failed' ? 'failed' : 'unavailable',
    label: null,
    evidence_ids: [],
    citations: [],
    error_code: unitStatus === 'failed' ? reason : 'all_units_abstained',
    units: advice.units.map((unit) => ({
      ...unit,
      status: unitStatus,
      label: null,
      evidence_ids: [],
      citations: [],
      reason_code: reason,
    })),
    aggregation: {
      ...advice.aggregation,
      counts: {
        ...advice.aggregation.counts,
        supported: 0,
        contradicted: 0,
        insufficient: 0,
        [unitStatus]: advice.units.length,
      },
    },
  };
}
/** The recorded feedback record (rules, facts, range, provenance) with the given advice. */
export const recordedReport = (language, advice) => ({
  ...recorded.reports[language],
  semantic_status: 'available',
  model_advice: advice,
});
