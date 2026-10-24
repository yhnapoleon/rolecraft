/** The work sentence by sentence, as data for the recognition lens ("透镜读稿"): for each
 * sentence its relation and whether the recognizers were sure of it, the numbers in conflict,
 * the material sentence it hit (with material and version when known), and the five steps of
 * its recognition chain, each with result, method and course category. Pure: built only from
 * stored records or the preview's reply, all wording from the lens copy. The renderer
 * (sentences.ts) draws it; a new presentation changes the renderer, not this. */
import { copyText, type Language } from '../results-native/localization';
import type { RecognitionRecord } from './badge';
import {
  closestSentence,
  previewChain,
  recognitionChain,
  type ChainUnit,
  type PreviewRecognition,
  type RecognitionChain,
  type RuleReason,
} from './chain';
import { LENS_COPY, type LensKey } from './lens-copy';
import { categoryOf, sureMeter, type Meter } from './signals';

export type SentenceTone = 'supported' | 'contradicted' | 'insufficient' | 'deferred';
export type SureLevel = 'high' | 'mid' | 'low';
export type ChainStepName = 'retrieval' | 'relation' | 'fusion' | 'decision' | 'arbiter';
/** A run of text; `num` marks the work's number in conflict, `src` the material's. */
export type Part = { text: string; mark?: 'num' | 'src' };
export type ChainStepView = {
  step: ChainStepName;
  name: string;
  /** The step's finding in one or two words. */
  result: string;
  resultTone: 'good' | 'bad' | 'unknown' | 'ink';
  /** Confidence as 0–5 lit cells (relation only); null where a step has no confidence. */
  cells: number | null;
  cellsLabel: string | null;
  method: string;
  category: string;
  /** Rule fallback: method and category say so, never a learned model. */
  fallback: boolean;
  /** Before submission, arbitration has not happened yet. */
  muted: boolean;
  /** One line of detail under the finding. */
  note: string | null;
  /** The first retrieval hit, shown; the rest go behind "Show all". */
  hit: { rank: number; quote: string; cited: boolean } | null;
  more: {
    label: string;
    hits: { rank: number; quote: string; cited: boolean }[];
    probabilities: { key: string; label: string; meter: Meter }[];
  } | null;
};
export type SourceView = {
  title: string | null;
  version: string | null;
  quote: string;
  parts: Part[];
  relation: 'contradicts' | 'supports';
  relationLabel: string;
};
export type SentenceView = {
  index: number;
  quote: string;
  parts: Part[];
  tone: SentenceTone;
  /** Supported and contradicted are drawn; the uncertain two only fade in. */
  certain: boolean;
  toneLabel: string;
  /** What a screen reader hears after the sentence. */
  srText: string;
  confidence: number | null;
  sure: SureLevel | null;
  /** The material sentence this sentence hit; shown in the margin as `shown` says. */
  source: SourceView | null;
  /** 'always' for a contradiction, 'open' while a supported sentence is open. */
  shown: 'always' | 'open' | null;
  /** The numbers the rule found in conflict ("80" against a limit of "30" people). */
  conflict: { value?: string; limit?: string; unit?: string; unitLabel?: string } | null;
  chain: { head: string; quote: string; steps: ChainStepView[] };
};
export type SentenceLensView = {
  title: string;
  counts: string;
  tally: { s: number; c: number; u: number };
  categories: { text: string; fallback: boolean }[];
  legend: { tone: SentenceTone; label: string }[];
  hint: string;
  note: string;
  replay: string;
  showAll: string;
  sentences: SentenceView[];
};
export type SentenceSource = {
  language: Language;
  /** Stored records of one feedback (or of the session). */
  records?: RecognitionRecord[];
  /** The pre-submission preview body, when there are no stored records yet. */
  preview?: PreviewRecognition | null;
};

const t = (language: Language, key: LensKey, values: Record<string, string | number> = {}) =>
  copyText(LENS_COPY, language, key, values);
const known = (key: string): key is LensKey => key in LENS_COPY.zh;

export const toneOf = (unit: Pick<ChainUnit, 'decision' | 'label'>): SentenceTone =>
  unit.decision === 'defer'
    ? 'deferred'
    : unit.label === 'supported' || unit.label === 'contradicted'
      ? unit.label
      : 'insufficient';
const TONE_KEY: Record<SentenceTone, LensKey> = {
  supported: 's_supported',
  contradicted: 's_contradicted',
  insufficient: 's_insufficient',
  deferred: 's_deferred',
};
const sureOf = (p: number): SureLevel => (p >= 0.8 ? 'high' : p >= 0.6 ? 'mid' : 'low');

function unitLabel(unit: string | undefined, language: Language) {
  const key = `unit_${unit}`;
  return unit && known(key) ? t(language, key) : (unit ?? '');
}

/** One rule finding in words ("80 人超过材料里的上限 30 人"). */
export function ruleText(rule: RuleReason | null, language: Language) {
  if (!rule) return '';
  const key = `rule_${rule.kind}`;
  return known(key)
    ? t(language, key, { value: rule.value ?? '', limit: rule.limit ?? '', unit: unitLabel(rule.unit, language) })
        .replace(/\s+/g, ' ')
        .trim()
    : rule.kind;
}

/** Split `text` around the first occurrence of the number `value`, matched on number
 * boundaries, with thousands separators and a leading currency (CNY, ¥, $) allowed. No value,
 * or no match, leaves the text whole: nothing is guessed. */
export function markNumber(text: string, value: string | undefined, mark: 'num' | 'src'): Part[] {
  const digits = value?.match(/^(\d+)(\.\d+)?$/);
  if (!digits) return [{ text }];
  const [, whole, fraction = ''] = digits;
  const grouped = whole
    .split('')
    .map((d, i) => ((whole.length - i) % 3 === 0 && i > 0 ? `,?${d}` : d))
    .join('');
  const pattern = new RegExp(
    `(?<![\\d.,])((?:CNY\\s?|RMB\\s?|¥|\\$)?${grouped}${fraction.replace('.', '\\.')})(?![\\d]|\\.\\d)`,
    'i',
  );
  const found = pattern.exec(text);
  if (!found) return [{ text }];
  const start = found.index;
  const end = start + found[1].length;
  return [
    ...(start ? [{ text: text.slice(0, start) }] : []),
    { text: text.slice(start, end), mark },
    ...(end < text.length ? [{ text: text.slice(end) }] : []),
  ];
}

const cellsOf = (p: number) => Math.max(0, Math.min(5, Math.round(p * 5)));

/** The five steps of one sentence. Steps the records do not carry say so instead of guessing;
 * a rule fallback is named as such, never as a learned model. */
export function chainSteps(chain: RecognitionChain | null, language: Language, beforeSubmission: boolean): ChainStepView[] {
  const unit = chain?.unit;
  if (!chain || !unit) return [];
  const base = { cells: null, cellsLabel: null, fallback: false, muted: false, note: null, hit: null, more: null };
  const cited = unit.evidence_ids?.[0];
  const hits = chain.retrieval.slice(0, 5).map((hit) => ({
    rank: hit.rank,
    quote: closestSentence(unit.quote, hit.quote),
    cited: !!hit.evidenceId && hit.evidenceId === cited,
  }));
  const relation: RecognitionRecord = {
    recognizer_id: chain.relation?.recognizerId ?? '',
    revision: chain.relation?.revision ?? '',
    task: 'relation',
    fallback: chain.relation?.fallback,
  };
  const ruleOnly = !!relation.fallback;
  const fusion = chain.fusion;
  const label = unit.label === 'supported' || unit.label === 'contradicted' ? unit.label : 'insufficient';
  const probabilities = unit.probabilities
    ? ['supported', 'contradicted', 'insufficient'].map((key) => {
        const name = t(language, `p_${key}` as LensKey);
        const p = unit.probabilities?.[key] ?? 0;
        return { key, label: name, meter: { value: p, label: `${name} · ${sureMeter(p, language).label}` } };
      })
    : [];
  const arbiter = chain.arbiter;
  const VERDICT: Record<string, LensKey> = {
    MET: 'lbl_MET',
    PARTIAL: 'lbl_PARTIAL',
    NOT_MET: 'lbl_NOT_MET',
    INSUFFICIENT: 'lbl_INSUFFICIENT',
  };
  const word = (v: string) => (VERDICT[v] ? t(language, VERDICT[v]) : v || '–');
  return [
    {
      ...base,
      step: 'retrieval',
      name: t(language, 'step_retrieval'),
      result: hits.length
        ? chain.retrieval.length === 1
          ? t(language, 'r_found_one')
          : t(language, 'r_found', { n: chain.retrieval.length })
        : chain.evidence
          ? t(language, 'r_one')
          : t(language, 'r_nothing'),
      resultTone: 'ink',
      method: t(language, 'm_retrieval'),
      category: t(language, 'cat_hybrid'),
      note: hits.length ? null : chain.evidence,
      hit: hits[0] ?? null,
      more: hits.length > 1 ? { label: t(language, 'showAll'), hits: hits.slice(1), probabilities: [] } : null,
    },
    {
      ...base,
      step: 'relation',
      name: t(language, 'step_relation'),
      result: t(language, `res_${label}` as LensKey),
      resultTone: label === 'supported' ? 'good' : label === 'contradicted' ? 'bad' : 'unknown',
      cells: typeof unit.confidence === 'number' ? cellsOf(unit.confidence) : null,
      cellsLabel: typeof unit.confidence === 'number' ? sureMeter(unit.confidence, language).label : null,
      method: t(language, ruleOnly ? 'm_relation_rule' : /stack/.test(relation.recognizer_id) ? 'm_relation_stack' : 'm_relation'),
      category: ruleOnly ? t(language, 'fallback') : categoryOf(relation, language),
      fallback: ruleOnly,
      more: probabilities.length ? { label: t(language, 'showAll'), hits: [], probabilities } : null,
    },
    {
      ...base,
      step: 'fusion',
      name: t(language, 'step_fusion'),
      result: t(
        language,
        !fusion ? 'f_res_none' : fusion.kind === 'late_fusion' ? 'f_res_late' : fusion.kind === 'model_only' ? 'f_res_model' : 'f_res_rule',
      ),
      resultTone: 'ink',
      method: t(language, 'm_fusion'),
      category: t(language, 'cat_ensemble'),
      note: !fusion
        ? t(language, ruleOnly ? 'fusion_off' : 'fusion_unknown')
        : fusion.kind === 'late_fusion'
          ? t(language, 'fusion_late', { alpha: fusion.alpha, rule: ruleText(fusion.rule, language) })
          : fusion.kind === 'model_only'
            ? t(language, 'fusion_model')
            : t(language, 'fusion_rule', { rule: ruleText(fusion.rule, language) }),
    },
    {
      ...base,
      step: 'decision',
      name: t(language, 'step_decision'),
      result: t(language, chain.decision.action === 'defer' ? 'd_res_defer' : 'd_res_decide'),
      resultTone: chain.decision.action === 'defer' ? 'unknown' : 'ink',
      method: t(language, 'm_decision'),
      category: t(language, 'cat_decision'),
      note: t(language, chain.decision.action === 'defer' ? 'd_defer' : 'd_decide'),
    },
    {
      ...base,
      step: 'arbiter',
      name: t(language, 'step_arbiter'),
      result: arbiter
        ? t(language, `a_res_${arbiter.outcome}` as LensKey)
        : t(language, beforeSubmission ? 'a_res_later' : 'a_res_none'),
      resultTone: arbiter ? 'ink' : 'unknown',
      method: t(language, 'm_arbiter'),
      category: t(language, 'cat_decision'),
      muted: !arbiter,
      note: arbiter
        ? t(language, 'a_line', { judge: word(arbiter.judge), recognizer: word(arbiter.recognizer), final: word(arbiter.final) })
        : null,
    },
  ];
}

/** The lens-closed line for the preview: "与材料一致 2/10 句 · 1 句与材料矛盾". */
export function previewQuiet(
  preview: (Pick<PreviewRecognition, 'counts'> & { units?: unknown[] }) | null | undefined,
  language: Language,
): string | null {
  const n = preview?.units?.length ?? 0;
  if (!n) return null;
  const counts = preview?.counts ?? {};
  const contradicted = counts.contradicted ?? 0;
  return [
    t(language, 'quietCount', { s: counts.supported ?? 0, n }),
    contradicted ? t(language, 'quietContradicted', { c: contradicted }) : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

/** The whole block as data; null when the source holds no sentence-level labels. */
export function sentenceLensView(source: SentenceSource): SentenceLensView | null {
  const { language } = source;
  const fromRecords = !!source.records?.length;
  const chainFor = (index: number) =>
    fromRecords ? recognitionChain(source.records ?? [], index) : previewChain(source.preview, index);
  const first = chainFor(-1);
  if (!first) return null;
  const relation: RecognitionRecord = {
    recognizer_id: first.relation?.recognizerId ?? '',
    revision: first.relation?.revision ?? '',
    task: 'relation',
    fallback: first.relation?.fallback,
  };
  const fallbackLabel = t(language, 'fallback');
  const labels = [
    relation.fallback ? fallbackLabel : categoryOf(relation, language),
    first.units.some((u) => /^late_fusion/.test(u.reason ?? '')) ? t(language, 'cat_ensemble') : '',
    t(language, 'cat_hybrid'),
    t(language, 'cat_decision'),
  ].filter((label, i, all) => label && all.indexOf(label) === i);
  const tally = { s: 0, c: 0, u: 0 };
  const sentences = first.units.map((unit): SentenceView => {
    const tone = toneOf(unit);
    if (tone === 'supported') tally.s++;
    else if (tone === 'contradicted') tally.c++;
    else tally.u++;
    const chain = chainFor(unit.index);
    const rule = chain?.fusion && chain.fusion.kind !== 'model_only' ? chain.fusion.rule : null;
    const conflict =
      tone === 'contradicted' && rule && (rule.kind === 'exceeds_limit' || rule.kind === 'different_quantity')
        ? { value: rule.value, limit: rule.limit, unit: rule.unit, unitLabel: unitLabel(rule.unit, language) }
        : null;
    const relationTone = tone === 'contradicted' ? 'contradicts' : tone === 'supported' ? 'supports' : null;
    const evidence = relationTone ? (chain?.evidence ?? null) : null;
    const version = chain?.source?.version != null ? t(language, 'version', { n: chain.source.version }) : null;
    const sourceView: SourceView | null = evidence && relationTone
      ? {
          title: chain?.source?.title ?? null,
          version,
          quote: evidence,
          parts: markNumber(evidence, conflict?.limit, 'src'),
          relation: relationTone,
          relationLabel: t(language, relationTone === 'contradicts' ? 'src_contradicts' : 'src_supports'),
        }
      : null;
    const confidence = typeof unit.confidence === 'number' ? unit.confidence : null;
    const toneLabel = t(language, TONE_KEY[tone]);
    const srExtra =
      tone === 'contradicted' && sourceView?.title
        ? t(language, 'sr_contradicts', { title: sourceView.title, version: sourceView.version ?? '' }).trim()
        : '';
    return {
      index: unit.index,
      quote: unit.quote,
      parts: markNumber(unit.quote, conflict?.value, 'num'),
      tone,
      certain: tone === 'supported' || tone === 'contradicted',
      toneLabel,
      srText: [toneLabel, srExtra].filter(Boolean).join(language === 'zh' ? '，' : ', '),
      confidence,
      sure: confidence == null ? null : sureOf(confidence),
      source: sourceView,
      shown: sourceView ? (tone === 'contradicted' ? 'always' : 'open') : null,
      conflict,
      chain: { head: t(language, 'chainHead'), quote: unit.quote, steps: chainSteps(chain, language, !fromRecords) },
    };
  });
  return {
    title: t(language, 'sentences'),
    counts: t(language, 'counts', tally),
    tally,
    categories: labels.map((text) => ({ text, fallback: text === fallbackLabel })),
    legend: (['supported', 'contradicted', 'insufficient', 'deferred'] as SentenceTone[]).map((tone) => ({
      tone,
      label: t(language, TONE_KEY[tone]),
    })),
    hint: t(language, 'sentencesHint'),
    note: t(language, 'lensNote'),
    replay: t(language, 'replay'),
    showAll: t(language, 'showAll'),
    sentences,
  };
}
