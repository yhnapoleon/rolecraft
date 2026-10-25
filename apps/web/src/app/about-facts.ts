/** Workbench internals that a person may want to look up but does not need while working (for
 * example which rubric produced a feedback report). Feature views note them here as they render;
 * "⋯ → About this workspace" lists the ones noted for the open practice. Nothing is persisted. */
export type AboutFact = { label: string; value: string };

const facts = new Map<string, Map<string, AboutFact>>();

/** Notes one fact for a practice; a later note with the same key replaces it. */
export function noteAboutFact(sessionId: string | undefined, key: string, fact: AboutFact) {
  if (!sessionId) return;
  const own = facts.get(sessionId) ?? new Map<string, AboutFact>();
  facts.set(sessionId, own);
  own.set(key, fact);
}

export function aboutFacts(sessionId: string | undefined): AboutFact[] {
  return sessionId ? [...(facts.get(sessionId)?.values() ?? [])] : [];
}
