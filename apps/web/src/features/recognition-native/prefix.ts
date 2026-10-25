/** The reviewer model opens each semantic explanation with a recognition tag ("[识别一致]",
 * "[与识别不一致：原因]", "[识别缺失]" or their English forms), and the arbiter may put its own
 * sentence ("仲裁：…。" / "Arbiter: …. ") in front. The backend stores the text as written; the
 * learner never sees these markers. This splits them off so pages show the plain explanation and,
 * with the recognition lens on, a quiet structured tag instead. */
export type RecognitionTag = 'agree' | 'disagree' | 'missing';
export type SplitExplanation = {
  text: string;
  tag: RecognitionTag | null;
  /** The reviewer's reason for disagreeing, as written. */
  reason: string | null;
  /** The arbiter sentence written in front of the explanation, as stored. */
  arbiter: string | null;
};

const ARBITER = /^\s*(仲裁：[^。]*。|Arbiter:[^.]*(?:\.\d+[^.]*)*\.)\s*/i;
const OPEN = '[\\[【]';
const CLOSE = '[\\]】]';
const TAGS: [RecognitionTag, RegExp][] = [
  ['agree', new RegExp(`^${OPEN}\\s*(?:识别一致|recognition agrees)\\s*${CLOSE}\\s*`, 'i')],
  ['missing', new RegExp(`^${OPEN}\\s*(?:识别缺失|recognition missing)\\s*${CLOSE}\\s*`, 'i')],
  [
    'disagree',
    new RegExp(
      `^${OPEN}\\s*(?:与识别不一致|disagrees with recognition)\\s*(?:[:：]\\s*([^\\]】]*))?${CLOSE}\\s*`,
      'i',
    ),
  ],
];

export function splitRecognitionPrefix(raw: string): SplitExplanation {
  let text = raw;
  let arbiter: string | null = null;
  const lead = ARBITER.exec(text);
  if (lead) {
    arbiter = lead[1].trim();
    text = text.slice(lead[0].length);
  }
  for (const [tag, pattern] of TAGS) {
    const found = pattern.exec(text);
    if (!found) continue;
    const reason = found[1]?.trim();
    return { text: text.slice(found[0].length), tag, reason: reason || null, arbiter };
  }
  // An arbiter sentence alone (no tag after it) is still the system's note, not the reviewer's.
  return arbiter ? { text, tag: null, reason: null, arbiter } : { text: raw, tag: null, reason: null, arbiter: null };
}
