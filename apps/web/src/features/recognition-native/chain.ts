/** One sentence of the work through the recognition chain: retrieval → relation → fusion →
 * cost decision → arbiter. Pure data taken only from stored recognizer records (a feedback's
 * `recognition`, or GET /recognition) or from what the pre-submission preview returned; nothing
 * here guesses a step the records do not carry. Shared by the recognition lens and the lab. */
import { arbiterOutcome, type RecognitionRecord } from './badge';

export type ChainUnit = {
  index: number;
  quote: string;
  /** supported / contradicted / insufficient */
  label: string;
  confidence: number;
  probabilities?: Record<string, number>;
  evidence_ids?: string[];
  reason?: string;
  /** decide, or defer when the cost decision sends it to a person */
  decision: string;
  expected_cost?: number;
  /** The material sentence the preview matched to this sentence. */
  evidence?: string | null;
  /** The material that sentence came from (preview only; stored records name a hash). */
  source?: { kind?: string; object_id?: string; version?: number; title?: string | null } | null;
  /** The top retrieval hits for this sentence (preview only; records keep them apart). */
  top?: Record<string, unknown>[];
};
/** Which material a matched sentence came from, as far as the records tell. */
export type SourceInfo = { title: string | null; version: number | null };
export type RetrievalHit = {
  rank: number;
  quote: string;
  evidenceId: string | null;
  bm25: number | null;
  dense: number | null;
};
export type RuleReason = {
  kind: string;
  value?: string;
  limit?: string;
  unit?: string;
};
export type Fusion =
  | { kind: 'late_fusion'; alpha: number; rule: RuleReason | null }
  | { kind: 'model_only' }
  | { kind: 'rule_only'; rule: RuleReason };
export type RecognitionChain = {
  units: ChainUnit[];
  unit: ChainUnit | null;
  relation: { recognizerId: string; revision: string; fallback: boolean } | null;
  retrieval: RetrievalHit[];
  fusion: Fusion | null;
  decision: { action: string; expectedCost: number | null; deferCost: number | null };
  arbiter: {
    outcome: 'agree' | 'conservative' | 'undecided';
    judge: string;
    recognizer: string;
    final: string;
  } | null;
  /** The material sentence this sentence was matched to, when the records name one. */
  evidence: string | null;
  /** The material of that sentence: its heading and version, when known. */
  source: SourceInfo | null;
};
/** The pre-submission preview body (recognition/judge.py `preview`). */
export type PreviewRecognition = {
  recognizer?: string;
  fallback?: boolean;
  duration_ms?: number;
  counts?: { supported?: number; contradicted?: number; insufficient?: number; deferred?: number };
  units?: ChainUnit[];
  /** The cost of sending a sentence to a person (C6). */
  defer_cost?: number;
};

const num = (value: unknown) => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const latest = (records: RecognitionRecord[], test: (record: RecognitionRecord) => boolean) =>
  [...records].reverse().find(test);
const hasUnits = (record: RecognitionRecord) =>
  record.task === 'relation' && Array.isArray(record.outputs?.units);

function rule(text: string): RuleReason {
  const [kind, rest] = text.split(/:(.*)/s);
  if (!rest) return { kind };
  const [amount, unit] = rest.trim().split(/\s+/, 2);
  const [value, limit] = amount.split(/>|!=/);
  return { kind, value, ...(limit !== undefined ? { limit } : {}), ...(unit ? { unit } : {}) };
}

/** What fusion did for one sentence, from its recorded reason (recognition/relation.py):
 * `late_fusion:α|<rule reason>` when the number-and-limit rule was fused in; `pair_aggregate`
 * when the relation model decided alone; a bare rule reason when only the rule ran. */
export function parseReason(reason: string | undefined | null): Fusion | null {
  if (!reason) return null;
  const fused = /^late_fusion:([\d.]+)(?:\|(.*))?$/s.exec(reason);
  if (fused) return { kind: 'late_fusion', alpha: Number(fused[1]), rule: fused[2] ? rule(fused[2]) : null };
  if (reason === 'pair_aggregate') return { kind: 'model_only' };
  return { kind: 'rule_only', rule: rule(reason) };
}

const SENTENCE_END = /(?<=[。！？!?；;])|(?<=\.)\s+|\n+/;
const NOISE = /[\s，,。．.；;：:！!？?、（）()【】[\]《》“”"'‘’#*-]/g;
const grams = (text: string) => {
  const s = text.toLowerCase().replace(NOISE, '');
  const out = new Set<string>();
  for (let i = 0; i < s.length - 1; i++) out.add(s.slice(i, i + 2));
  return out;
};

/** The sentence of a material passage sharing the most character pairs with the claim (the
 * same choice the preview makes on the server). */
export function closestSentence(claim: string, text: string): string {
  const want = grams(claim);
  // A passage's heading names the material; the matched sentence is in its body.
  const body = text
    .split('\n')
    .filter((line) => !/^\s*#/.test(line))
    .join('\n');
  const parts = (body.trim() ? body : text)
    .split(SENTENCE_END)
    .map((part) => part?.replace(/^[\s#*-]+|[\s#*-]+$/g, '') ?? '')
    .filter(Boolean);
  let best = parts[0] ?? text;
  let score = -1;
  for (const part of parts) {
    const shared = [...grams(part)].filter((g) => want.has(g)).length;
    if (shared > score) {
      best = part;
      score = shared;
    }
  }
  return best.slice(0, 160);
}

/** A passage's own title: its first markdown heading line, when it starts with one. */
export function passageHeading(text: string): string | null {
  const first = text.split('\n').find((line) => line.trim());
  const heading = first?.trim().match(/^#+\s*(.+)$/)?.[1]?.trim();
  return heading ? heading.slice(0, 80) : null;
}

const toHits = (top: Record<string, unknown>[]): RetrievalHit[] =>
  top.map((hit, i) => ({
    rank: num(hit.rank) ?? i + 1,
    quote: String(hit.quote ?? ''),
    evidenceId: typeof hit.evidence_id === 'string' ? hit.evidence_id : null,
    bm25: num(hit.bm25),
    dense: num(hit.dense),
  }));

function hits(record: RecognitionRecord | undefined, index: number): RetrievalHit[] {
  const rows = (record?.outputs?.per_sentence_top ?? []) as { index: number; top?: Record<string, unknown>[] }[];
  return (rows.find((row) => row.index === index)?.top ?? []).map((hit, i) => ({
    rank: num(hit.rank) ?? i + 1,
    quote: String(hit.quote ?? ''),
    evidenceId: typeof hit.evidence_id === 'string' ? hit.evidence_id : null,
    bm25: num(hit.bm25),
    dense: num(hit.dense),
  }));
}

/** The chain of sentence `index` (or the first sentence) in these records; null when they hold
 * no sentence-level relation record. */
export function recognitionChain(records: RecognitionRecord[], index: number): RecognitionChain | null {
  const relation = latest(records, hasUnits);
  if (!relation) return null;
  const units = (relation.outputs?.units ?? []) as ChainUnit[];
  const unit = units.find((u) => u.index === index) ?? units[0] ?? null;
  const top = unit ? hits(latest(records, (r) => r.task === 'retrieval' && Array.isArray(r.outputs?.per_sentence_top)), unit.index) : [];
  const decision = latest(records, (r) => r.task === 'decision');
  const arbiter = latest(records, (r) => r.task === 'arbiter');
  const cited = unit?.evidence_ids?.[0];
  const source = cited ? top.find((hit) => hit.evidenceId === cited) : undefined;
  const out = arbiter?.outputs ?? {};
  return {
    units,
    unit,
    relation: { recognizerId: relation.recognizer_id, revision: relation.revision, fallback: !!relation.fallback },
    retrieval: top,
    fusion: parseReason(unit?.reason),
    decision: {
      action: unit?.decision ?? 'decide',
      expectedCost: num(unit?.expected_cost),
      deferCost: num((decision?.outputs?.costs as { defer?: unknown } | undefined)?.defer),
    },
    arbiter: arbiter
      ? {
          outcome: arbiterOutcome(arbiter),
          judge: String(out.judge_label ?? ''),
          recognizer: String(out.recognizer_label ?? ''),
          final: String(out.final ?? ''),
        }
      : null,
    evidence: source && unit ? closestSentence(unit.quote, source.quote) : null,
    source: source ? { title: passageHeading(source.quote), version: null } : null,
  };
}

/** The shorter chain the preview carries: labels, the matched sentence, no retrieval list. */
export function previewChain(preview: PreviewRecognition | null | undefined, index: number): RecognitionChain | null {
  const units = preview?.units ?? [];
  if (!units.length) return null;
  const unit = units.find((u) => u.index === index) ?? units[0];
  const [recognizerId, revision = ''] = String(preview?.recognizer ?? '').split('@');
  return {
    units,
    unit,
    relation: { recognizerId, revision, fallback: !!preview?.fallback },
    retrieval: toHits(unit.top ?? []),
    fusion: parseReason(unit.reason),
    decision: {
      action: unit.decision,
      expectedCost: num(unit.expected_cost),
      deferCost: num(preview?.defer_cost),
    },
    arbiter: null,
    evidence: unit.evidence ?? null,
    source: unit.evidence
      ? { title: unit.source?.title ?? null, version: num(unit.source?.version) }
      : null,
  };
}
