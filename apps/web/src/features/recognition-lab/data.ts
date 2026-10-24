/** Data for the system profile page (#/lab).
 *
 * Two sources: the published experiment results (`public/lab/*.json`, copied there by
 * `experiments/recognition/publish_lab.py`) and this practice's recognition records
 * (GET /sessions/{id}/recognition). Results are cached for the life of the page; the
 * session read is cached per practice and only refreshed when the route is entered again.
 */
import type { SessionRecognition } from '../recognition-native/client';

export type Json = unknown;
export type Results = Record<string, Json>;

/** Every result file the page reads. */
export const RESULT_FILES = [
  'e1_relation',
  'e1_baselines',
  'e1_stack',
  'e3_retrieval',
  'e4_decision',
  'e5_scope',
  'e6_behavior',
  'e7_intent',
  'e8_judge',
  'e9_cross_domain',
  'e10_fusion',
  'e11_transfer_public',
  'e12_mix_public',
  'e13_reply',
  'e13_scope',
  'e13_retrieval',
  'e13_sequence',
  'e13_intent',
  'e14_diagnose_public',
  'e14_review_errors',
  'e15_nli_zs',
  'e15_nli_mix',
  'e15_reply_zs',
  'e15_reply_mix',
] as const;

export type Fetcher = (name: string) => Promise<Json | null>;

/** A missing or unreadable file is `null`, so its section says so instead of failing. */
export const fetchPublished: Fetcher = async (name) => {
  try {
    const response = await fetch(`/lab/${name}.json`, { cache: 'no-cache' });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
};

export function createResultStore(fetcher: Fetcher) {
  const files = new Map<string, Promise<Json | null>>();
  return {
    async load(names: readonly string[]): Promise<Results> {
      const values = await Promise.all(
        names.map((name) => {
          let file = files.get(name);
          if (!file) {
            file = fetcher(name).catch(() => null);
            files.set(name, file);
          }
          return file;
        }),
      );
      return Object.fromEntries(names.map((name, i) => [name, values[i]]));
    },
  };
}

/** The page's own store: one fetch per file per page load. */
export const results = createResultStore(fetchPublished);

/** This practice's records, read once per entry into the route. */
export function createSessionStore() {
  let entry: { key: string; read: Promise<SessionRecognition | null> } | null = null;
  return {
    read(
      key: string,
      loader: (() => Promise<SessionRecognition>) | null,
      refresh: boolean,
    ): Promise<SessionRecognition | null> {
      if (!loader) return Promise.resolve(null);
      if (!entry || entry.key !== key || refresh) {
        entry = { key, read: loader().catch(() => null) };
      }
      return entry.read;
    },
  };
}

export const sessionRecords = createSessionStore();

/* ---------- the claim that walks the pipeline ---------- */

export type Relation = 'supported' | 'contradicted' | 'insufficient';
export type Language = 'zh' | 'en';

export interface Hit {
  rank: number;
  quote: string;
  bm25: number | null;
  dense: number | null;
}

export interface Arbitration {
  criterion: string;
  judge: string;
  recognizer: string;
  final: string;
  agreement: boolean;
}

export interface Chain {
  /** True when this practice has no sentence-level records and a recorded example is shown. */
  example: boolean;
  quote: string;
  index: number;
  total: number;
  candidates: number | null;
  top: Hit[];
  probabilities: Record<Relation, number>;
  label: Relation;
  reason: string;
  fallback: boolean;
  decision: 'decide' | 'defer';
  expectedCost: number;
  deferCost: number;
  evidence: number;
  arbiter: Arbitration | null;
  counts: Record<string, number> | null;
  /** Every sentence of the work, for the picker (empty for the example). */
  units: { index: number; quote: string; label: Relation; decision: 'decide' | 'defer' }[];
}

type Unit = {
  index: number;
  quote: string;
  label: string;
  probabilities?: Partial<Record<Relation, number>>;
  evidence_ids?: string[];
  reason?: string;
  decision?: string;
  expected_cost?: number;
};
type RawHit = { rank?: number; quote?: unknown; bm25?: unknown; dense?: unknown };

const num = (v: unknown, fallback = 0) =>
  typeof v === 'number' && Number.isFinite(v) ? v : fallback;
const relation = (v: unknown): Relation =>
  v === 'supported' || v === 'contradicted' ? v : 'insufficient';

/** Material units come with markdown headings and line breaks; show them as one line. */
export function cleanQuote(text: string) {
  const line = text
    .split('\n')
    .map((part) => part.replace(/^#+\s*/, '').trim())
    .filter(Boolean)
    .join(' · ');
  return /[。．.!?！？；;：:」”"）)]$/.test(line) ? line : `${line}…`;
}

/** Contradictions first, then deferrals, then the closest supported call with evidence. */
function telling(units: Unit[]) {
  const rank = (u: Unit) =>
    u.label === 'contradicted'
      ? 3
      : u.decision === 'defer'
        ? 2
        : u.label === 'supported' && u.evidence_ids?.length
          ? 1 + num(u.probabilities?.contradicted) / 2
          : 0;
  return units.reduce((best, u) => (rank(u) > rank(best) ? u : best), units[0]);
}

export function chainFor(
  data: SessionRecognition | null,
  language: Language,
  selected?: number,
): Chain {
  const records = data?.records ?? [];
  const relationEntry = [...records]
    .reverse()
    .find((r) => r.record.task === 'relation' && Array.isArray(r.record.outputs?.units));
  const units = (relationEntry?.record.outputs?.units ?? []) as Unit[];
  if (!relationEntry || !units.length) return example(language);
  const carrier = relationEntry.carrier.object_id;
  const sibling = (task: string) =>
    records.find((r) => r.carrier.object_id === carrier && r.record.task === task)?.record;
  const unit = units.find((u) => u.index === selected) ?? telling(units);
  const retrieval = sibling('retrieval');
  const rows = (retrieval?.outputs?.per_sentence_top ?? []) as { index: number; top: RawHit[] }[];
  const top = (rows.find((row) => row.index === unit.index)?.top ?? []).slice(0, 3).map((h, i) => ({
    rank: num(h.rank, i + 1),
    quote: cleanQuote(String(h.quote ?? '')),
    bm25: typeof h.bm25 === 'number' ? h.bm25 : null,
    dense: typeof h.dense === 'number' ? h.dense : null,
  }));
  const costs = sibling('decision')?.outputs?.costs as { defer?: number } | undefined;
  const arbiter = sibling('arbiter')?.outputs;
  const p = unit.probabilities ?? {};
  return {
    example: false,
    quote: unit.quote,
    index: unit.index,
    total: units.length,
    candidates:
      typeof relationEntry.record.outputs?.candidates === 'number'
        ? relationEntry.record.outputs.candidates
        : null,
    top,
    probabilities: {
      supported: num(p.supported),
      contradicted: num(p.contradicted),
      insufficient: num(p.insufficient),
    },
    label: relation(unit.label),
    reason: unit.reason ?? '',
    fallback: !!relationEntry.record.fallback,
    decision: unit.decision === 'defer' ? 'defer' : 'decide',
    expectedCost: num(unit.expected_cost),
    deferCost: num(costs?.defer, 0.5),
    evidence: unit.evidence_ids?.length ?? 0,
    arbiter: arbiter
      ? {
          criterion: String(arbiter.criterion ?? ''),
          judge: String(arbiter.judge_label ?? ''),
          recognizer: String(arbiter.recognizer_label ?? ''),
          final: String(arbiter.final ?? ''),
          agreement: !!arbiter.agreement,
        }
      : null,
    counts: data?.counts ?? null,
    units: units.map((u) => ({
      index: u.index,
      quote: u.quote,
      label: relation(u.label),
      decision: u.decision === 'defer' ? 'defer' : 'decide',
    })),
  };
}

/** The example is real recorded output, not made up: sentence 5 of the demo pack's
 * completed knowledge-assistant run (`demo/demo-pack-v1.json.gz`, pm_pilot zh / en,
 * revision feedback). Shown only with the 「示例」 mark. */
const EXAMPLE_ARBITER: Arbitration = {
  criterion: 'R2.support',
  judge: 'INSUFFICIENT',
  recognizer: 'PARTIAL',
  final: 'INSUFFICIENT',
  agreement: false,
};
const EXAMPLE_COUNTS = {
  scope: 5,
  retrieval: 7,
  intent: 3,
  reply_check: 3,
  drift: 1,
  relation_units: 19,
  decision: 2,
  arbiter: 2,
  behavior: 2,
};
const EXAMPLES: Record<Language, Omit<Chain, 'example' | 'units'>> = {
  zh: {
    quote: '政策已更新：国内出差住宿报销上限为每人每晚 400 元，超出须事前取得经理书面批准。',
    index: 4,
    total: 10,
    candidates: 13,
    top: [
      {
        rank: 1,
        bm25: 0.548,
        dense: 0.9475,
        quote:
          '住宿报销上限是多少？ · 费用管理通知：国内出差住宿报销上限改为每人每晚400元；超出上限仍须事前取得经理书面批准并保留票据。',
      },
      {
        rank: 2,
        bm25: 0.3451,
        dense: 0.9532,
        quote: '费用管理通知：国内出差住宿报销上限改为每人每晚400元；',
      },
      {
        rank: 3,
        bm25: 0.5123,
        dense: 0.9431,
        quote:
          '住宿报销上限是多少？ · 国内出差住宿报销上限为每人每晚500元；超出上限须在出行前取得经理书面批准，并保留票据。',
      },
    ],
    probabilities: { supported: 0.513, contradicted: 0.421, insufficient: 0.066 },
    label: 'supported',
    reason: 'late_fusion:0.4|same_quantity:400 cny',
    fallback: false,
    decision: 'decide',
    expectedCost: 0.487,
    deferCost: 0.5,
    evidence: 1,
    arbiter: EXAMPLE_ARBITER,
    counts: EXAMPLE_COUNTS,
  },
  en: {
    quote:
      'The policy has been updated: the domestic hotel reimbursement cap is CNY 400 per person per night, and costs above it need prior written manager approval.',
    index: 4,
    total: 10,
    candidates: 13,
    top: [
      {
        rank: 1,
        bm25: 0.4817,
        dense: 0.8929,
        quote:
          'What is the hotel reimbursement limit? · Expense-management notice: the hotel reimbursement cap for domestic business trav…',
      },
      {
        rank: 2,
        bm25: 0.3131,
        dense: 0.9128,
        quote:
          'Expense-management notice: the hotel reimbursement cap for domestic business travel is now CNY 400 per person per night.',
      },
      {
        rank: 3,
        bm25: 0.3999,
        dense: 0.8852,
        quote:
          'Expense-management notice: hotel allowance · This company and its business information are fictional training material.',
      },
    ],
    probabilities: { supported: 0.525, contradicted: 0.09, insufficient: 0.385 },
    label: 'supported',
    reason: 'late_fusion:0.4|same_quantity:400 cny',
    fallback: false,
    decision: 'decide',
    expectedCost: 0.353,
    deferCost: 0.5,
    evidence: 1,
    arbiter: EXAMPLE_ARBITER,
    counts: { ...EXAMPLE_COUNTS, relation: 14 },
  },
};

function example(language: Language): Chain {
  return { ...EXAMPLES[language], example: true, units: [] };
}
