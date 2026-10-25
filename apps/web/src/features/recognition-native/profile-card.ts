/** The profile card behind a lens chip (phase 2, step 2): one recognizer call, opened in place.
 *
 * Three layers, the same everywhere: what this call found in this practice (its own numbers:
 * the score against its threshold, the probabilities, the per-sentence labels), how it works
 * (method and course category, from the system profile's register), and the published figures
 * on the same measure (`public/lab/*.json`, read through the register; nothing typed in). The
 * run mode comes from the record: inference, rule calculation, fallback or unknown. The
 * carrier identifies saved action records versus delivery snapshots and current computation. A figure the record does not carry is
 * not drawn: no invented point, no invented share of a branch.
 */
import { COPY as LAB, type Key as LabKey } from '../recognition-lab/copy';
import { results, RESULT_FILES } from '../recognition-lab/data';
import { REGISTER, rowMetricsHtml } from '../recognition-lab/register';
import type { Language } from '../results-native/localization';
import { arbiterOutcome, type RecognitionRecord } from './badge';
import './profile-card.css';
import { actualMethod } from './actual-method';

/** Which register row (system profile section) explains each task. */
export const TASK_ROW: Record<string, string> = {
  relation: 'c1',
  retrieval: 'c2',
  scope: 'c4',
  drift: 'c4',
  behavior: 'c5',
  reply_check: 'c10',
  intent: 'c11',
  decision: 'c6',
  arbiter: 'c6',
};

const W = {
  zh: {
    thisTime: '这一次',
    how: '方法家族与备选方案',
    published: '离线实验 · 同口径结果',
    open: '打开系统剖面',
    real: '真实推理',
    fallback: '规则回退',
    replay: '记录回放',
    replayNote: '这局是用继续码打开的：看到的是当时保存的识别记录，不是现在重算。',
    fallbackNote: '本次记录标记了回退；实际使用的方法见上方。离线实验不代表这次执行。',
    threshold: '阈值',
    score: '这次',
    inside: '在范围内',
    outside: '超出范围',
    scopeLine: '离当前知识范围的距离 {score}，阈值 {thr}：{side}。',
    scopeRule: '这次没有数值，按规则判断：{rule}。',
    driftLine: '和记录指定的同题基准相比，余弦距离 {score}，阈值 {thr}。',
    driftNumbers: '回答里的数字从 {before} 变成 {after}。',
    driftRule: '这次没有向量距离，按文字是否变化判断。',
    retrievalLine: '实际用的检索：{method}。按名次排的前 {n} 段：',
    intentLine: '系统怎样理解了你的问题。它只影响已选同事回答的详略，不会替你决定由谁来回答。',
    intentRule: '这次按关键词规则理解。',
    replyLine: '逐句核对同事这条回复能不能追到他有权看到的资料。只标每一句，不给整段盖章；私密资料的编号不显示。',
    relationLine: '你交付的每一句原话，和它能找到的证据之间的关系：',
    decisionLine: '期望代价不低于「暂不判断」的代价时，这一句先不判断，留给人看。暂不判断不算你的错。',
    arbiterLine: '识别器和评审各自给出判断后，在规则允许的范围内取更保守的那个。',
    behaviorLine: '你这一局的操作序列，和几种参考做法对齐比较。只描述做法，不计分。',
    supported: '有依据',
    contradicted: '矛盾',
    insufficient: '依据不足',
    deferred: '暂不判断',
    leak: '涉及私密资料',
    judge: '评审',
    recognizer: '识别器',
    final: '最终',
    nearest: '最接近的做法',
    missing: '少了',
    extra: '多了',
    noFile: '实验结果文件暂时读不到。',
    deferCost: '「暂不判断」的代价：{cost}',
    driftByRule: '整体意思几乎没变（距离低于阈值），是数字校验规则抓到了这处改动：向量看语义，规则看数字，两者合用。',
    denseNote: '知识助手默认请求 e5 向量（dense）；关系链和同事来源排序才用 RRF 融合。下面「改写过的提问」一行就是两者的对照。',
  },
  en: {
    thisTime: 'This time',
    how: 'Method family and alternatives',
    published: 'Offline experiments · same measure',
    open: 'Open the system profile',
    real: 'Real inference',
    fallback: 'Rule fallback',
    replay: 'Record replay',
    replayNote: 'This practice was opened with a continue code: these are the records saved at the time, not computed again now.',
    fallbackNote: 'This record marks a fallback; the actual method is shown above. Offline results describe the method, not this call.',
    threshold: 'threshold',
    score: 'this time',
    inside: 'inside the scope',
    outside: 'outside the scope',
    scopeLine: 'Distance from the current knowledge scope {score}, threshold {thr}: {side}.',
    scopeRule: 'No score this time; a rule decided: {rule}.',
    driftLine: 'Against the recorded baseline for the same question: cosine distance {score}, threshold {thr}.',
    driftNumbers: 'The numbers in the answer went from {before} to {after}.',
    driftRule: 'No vector distance this time; it checked whether the text changed.',
    retrievalLine: 'Retrieval actually used: {method}. Top {n} passages by rank:',
    intentLine: 'How the system read your question. It only shapes how much the colleague you chose says; it never decides who answers.',
    intentRule: 'Read by keyword rules this time.',
    replyLine: 'Each sentence of this reply, checked against what the colleague may see. Each sentence is marked; the reply as a whole gets no stamp, and private evidence IDs are not shown.',
    relationLine: 'Each sentence you submitted, and how it stands against the evidence it found:',
    decisionLine: 'When the expected cost is no lower than the cost of deferring, the sentence is left for a person. A deferral is not your mistake.',
    arbiterLine: 'The recognizer and the reviewer each judge; within the rule’s bounds the more conservative label stands.',
    behaviorLine: 'Your sequence of actions, aligned with a few reference ways of working. It describes, it does not score.',
    supported: 'supported',
    contradicted: 'contradicted',
    insufficient: 'not enough evidence',
    deferred: 'deferred',
    leak: 'touches private material',
    judge: 'Reviewer',
    recognizer: 'Recognizer',
    final: 'Final',
    nearest: 'Closest way of working',
    missing: 'missing',
    extra: 'extra',
    noFile: 'The result files cannot be read right now.',
    deferCost: 'Cost of deferring: {cost}',
    driftByRule: 'The meaning barely moved (distance under the threshold); the number check caught the change. Vectors read meaning, the rule reads numbers, and the two are used together.',
    denseNote: 'The knowledge assistant requests e5 vectors (dense) by default; RRF fusion is used by the relation chain and colleague source ranking. The “paraphrased questions” line below compares the two.',
  },
} as const;
type Words = Record<keyof (typeof W)["zh"], string>;

const esc = (value: unknown) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c,
  );
const fill = (text: string, values: Record<string, string | number>) =>
  text.replace(/\{(\w+)\}/g, (_, k: string) => String(values[k] ?? ''));
// A quoted sentence as plain words: the reply's own markdown marks are not shown in a quote.
const plain = (text: unknown, max: number) =>
  String(text ?? '')
    .replace(/\*\*|__|`/g, '')
    .replace(/^#+\s*/, '')
    .trim()
    .slice(0, max);
const n2 = (x: unknown) => (typeof x === 'number' && Number.isFinite(x) ? x.toFixed(2) : '–');
const isNum = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x);
const lab = (language: Language, key: string) => LAB[language][key as LabKey] ?? '';

export type CardOptions = {
  source?: 'delivery' | 'saved' | 'current';
  materialName?: (id: string) => string;
  /** The practice was opened with a continue code: its records are replayed, not recomputed. */
  replay?: boolean;
};

export type RunMode = 'real' | 'fallback' | 'rule' | 'unknown';
export const runMode = (record: RecognitionRecord): RunMode => actualMethod(record, 'en').mode;
export function cardProvenance(language: Language, o: CardOptions = {}) {
  const zh = language === 'zh';
  return o.source === 'current'
    ? zh
      ? '现在在本地重新计算'
      : 'Recomputed locally now'
    : o.source === 'delivery'
      ? zh
        ? '交付时的记录'
        : 'Record at delivery'
      : zh
        ? '本次操作保存的记录'
        : 'Record saved by this action';
}

/**
 * Where a score falls against its threshold, on one axis from 0 to a little past the larger of
 * the two. The threshold is a tick, the score a dot; the side past the threshold is shaded.
 * Only drawn from the call's own score and threshold.
 */
function axis(score: number, threshold: number, w: Words) {
  const max = Math.max(score, threshold) * 1.25 || 1;
  const at = (x: number) => `${Math.min(100, (x / max) * 100).toFixed(1)}%`;
  const over = score > threshold;
  return `<div class="rc-axis" role="img" aria-label="${esc(`${w.score} ${n2(score)} · ${w.threshold} ${n2(threshold)}`)}">
    <span class="rc-axis__beyond" style="inset-inline-start:${at(threshold)}"></span>
    <span class="rc-axis__tick" style="inset-inline-start:${at(threshold)}"><b>${esc(w.threshold)} ${n2(threshold)}</b></span>
    <span class="rc-axis__dot" data-over="${over}" style="inset-inline-start:${at(score)}"><b>${esc(w.score)} ${n2(score)}</b></span>
  </div>`;
}

function bars(rows: [string, number][], top?: string) {
  return `<ul class="rc-bars">${rows
    .map(
      ([label, p]) =>
        `<li${label === top ? ' data-top=""' : ''}><span class="rc-bars__label">${esc(label)}</span><span class="rc-bars__bar"><i style="inline-size:${(Math.max(0, Math.min(1, p)) * 100).toFixed(1)}%"></i></span><span class="rc-bars__p">${Math.round(p * 100)}%</span></li>`,
    )
    .join('')}</ul>`;
}

const INTENT: Record<string, [string, string]> = {
  ask_limit: ['问限制', 'Asks about a limit'],
  ask_resource: ['问资源', 'Asks about resources'],
  ask_process: ['问流程', 'Asks about a process'],
  seek_approval: ['请求批准', 'Seeks approval'],
  other: ['其他', 'Other'],
};

/** What this call found, drawn from its own fields only. */
function thisTime(record: RecognitionRecord, language: Language, o: CardOptions) {
  const w = W[language];
  const out = (record.outputs ?? {}) as Record<string, unknown>;
  const name = o.materialName ?? ((id: string) => id);
  const label = (l: string) =>
    l === 'supported'
      ? w.supported
      : l === 'contradicted'
        ? w.contradicted
        : l === 'deferred'
          ? w.deferred
          : w.insufficient;
  switch (record.task) {
    case 'scope':
      if (isNum(record.score) && isNum(record.threshold))
        return `<p>${esc(fill(w.scopeLine, { score: n2(record.score), thr: n2(record.threshold), side: record.label === 'out' ? w.outside : w.inside }))}</p>${axis(record.score, record.threshold, w)}`;
      return `<p>${esc(fill(w.scopeRule, { rule: language === 'zh' ? (out.rule === 'no_retrieval_hit' ? '有无相关检索命中' : '记录中的范围规则') : (out.rule === 'no_retrieval_hit' ? 'whether retrieval found a relevant hit' : 'the recorded scope rule') }))}</p>`;
    case 'drift': {
      const before = ((out.numbers_before ?? []) as string[]).join('/');
      const after = ((out.numbers_after ?? []) as string[]).join('/');
      const numbers = out.numeric_change
        ? `<p class="rc-card__change"><s>${esc(before || '–')}</s><span aria-hidden="true">→</span><b>${esc(after || '–')}</b><span class="sr-only">${esc(fill(w.driftNumbers, { before, after }))}</span></p>`
        : '';
      if (isNum(record.score) && isNum(record.threshold)) {
        const byRule = out.numeric_change && record.score <= record.threshold;
        return `<p>${esc(fill(w.driftLine, { score: n2(record.score), thr: n2(record.threshold) }))}</p>${axis(record.score, record.threshold, w)}${numbers}${byRule ? `<p class="rc-card__note">${esc(w.driftByRule)}</p>` : ''}`;
      }
      return `<p>${esc(w.driftRule)}</p>${numbers}`;
    }
    case 'retrieval': {
      const top = Array.isArray(out.top) ? (out.top as Record<string, unknown>[]).slice(0, 3) : [];
      const methodName = actualMethod(record, language).method;
      if (!top.length && Array.isArray(out.per_sentence_top))
        return `<p>${esc(fill(w.retrievalLine, { method: methodName, n: (out.per_sentence_top as unknown[]).length }))}</p>`;
      return `<p>${esc(fill(w.retrievalLine, { method: methodName, n: top.length }))}</p><ol class="rc-hits">${top
        .map(
          (h) =>
            `<li><span class="rc-hits__rank">${esc(h.rank)}</span><span class="rc-hits__name">${esc(name(String(h.material_id ?? '')))}</span>${h.quote ? `<q>${esc(plain(h.quote, 90))}</q>` : ''}</li>`,
        )
        .join('')}</ol>`;
    }
    case 'intent': {
      const probs = out.probabilities as Record<string, number> | undefined;
      if (!probs) return `<p>${esc(w.intentLine)}</p><p class="rc-card__quiet">${esc(w.intentRule)}</p>`;
      const rows = Object.entries(probs)
        .sort((x, y) => y[1] - x[1])
        .map(([k, p]) => [INTENT[k]?.[language === 'zh' ? 0 : 1] ?? k, p] as [string, number]);
      const top = INTENT[String(record.label)]?.[language === 'zh' ? 0 : 1];
      return `<p>${esc(w.intentLine)}</p>${bars(rows, top)}`;
    }
    case 'reply_check': {
      const rows = (Array.isArray(out.sentences) ? out.sentences : []) as Record<string, unknown>[];
      return `<p>${esc(w.replyLine)}</p><ol class="rc-lines">${rows
        .map(
          (r) =>
            `<li data-label="${esc(r.leak ? 'leak' : r.label)}"><q>${esc(plain(r.quote, 120))}</q><span class="rc-lines__mark">${esc(r.leak ? w.leak : label(String(r.label)))}${isNum(r.confidence) ? ` · ${Math.round(r.confidence * 100)}%` : ''}</span></li>`,
        )
        .join('')}</ol>`;
    }
    case 'relation': {
      const counts = (out.counts ?? {}) as Record<string, number>;
      const units = (Array.isArray(out.units) ? out.units : []) as Record<string, unknown>[];
      const list = units.length
        ? `<ol class="rc-lines">${units
            .slice(0, 6)
            .map(
              (u) =>
                `<li data-label="${esc(u.decision === 'defer' ? 'deferred' : u.label)}"><q>${esc(plain(u.quote, 120))}</q><span class="rc-lines__mark">${esc(label(u.decision === 'defer' ? 'deferred' : String(u.label)))}${u.reason ? ` · ${esc(String(u.reason).slice(0, 60))}` : ''}</span></li>`,
            )
            .join('')}</ol>`
        : '';
      const total = Object.values(counts).reduce((x, y) => x + (Number(y) || 0), 0) || 1;
      const strip = `<p class="rc-strip" role="img" aria-label="${esc(`${w.supported} ${counts.supported ?? 0} · ${w.contradicted} ${counts.contradicted ?? 0} · ${w.insufficient} ${(counts.insufficient ?? 0) + (counts.deferred ?? 0)}`)}">${(
        [
          ['supported', counts.supported],
          ['contradicted', counts.contradicted],
          ['insufficient', (counts.insufficient ?? 0) + (counts.deferred ?? 0)],
        ] as [string, number | undefined][]
      )
        .filter(([, v]) => v)
        .map(
          ([k, v]) =>
            `<i data-k="${k}" style="flex:${v}"><span>${esc(label(k))} ${v}</span></i>`,
        )
        .join('')}</p>`;
      return `<p>${esc(w.relationLine)}</p>${total > 1 || counts.supported ? strip : ''}${list}`;
    }
    case 'decision': {
      const defer = (out.costs as Record<string, unknown> | undefined)?.defer;
      return `<p>${esc(w.decisionLine)}</p>${isNum(out.deferred) ? `<p class="rc-card__big"><b>${out.deferred}</b> ${esc(w.deferred)}</p>` : ''}${
        isNum(defer) ? `<p class="rc-card__quiet">${esc(fill(w.deferCost, { cost: n2(defer) }))}</p>` : ''
      }`;
    }
    case 'arbiter': {
      const outcome = arbiterOutcome(record);
      return `<p>${esc(w.arbiterLine)}</p><dl class="rc-arbiter" data-outcome="${outcome}"><div><dt>${esc(w.recognizer)}</dt><dd>${esc(out.recognizer_label ?? '–')}</dd></div><div><dt>${esc(w.judge)}</dt><dd>${esc(out.judge_label ?? '–')}</dd></div><div><dt>${esc(w.final)}</dt><dd><b>${esc(out.final ?? record.label ?? '–')}</b></dd></div></dl>`;
    }
    case 'behavior': {
      const align = (out.alignment ?? {}) as Record<string, unknown[]>;
      return `<p>${esc(w.behaviorLine)}</p>${record.label ? `<p class="rc-card__big">${esc(w.nearest)}：<b>${esc(record.label)}</b></p>` : ''}${
        align.missing || align.extra
          ? `<p class="rc-card__quiet">${esc(w.missing)} ${(align.missing ?? []).length} · ${esc(w.extra)} ${(align.extra ?? []).length}</p>`
          : ''
      }`;
    }
    default:
      return record.label ? `<p>${esc(record.label)}</p>` : '';
  }
}

/** The card's markup; its published figures are filled in by `fillCardMetrics` once read. */
export function cardHtml(record: RecognitionRecord, language: Language, given: CardOptions = {}) {
  const o = given;
  const w = W[language];
  const rowId = TASK_ROW[record.task];
  const row = REGISTER.find((r) => r.id === rowId);
  const mode = runMode(record);
  const actual = actualMethod(record, language);
  const modeText = mode === 'fallback' ? w.fallback : mode === 'rule' ? (language === 'zh' ? '规则计算' : 'Rule calculation') : mode === 'unknown' ? (language === 'zh' ? '实际方法未记录' : 'Actual method not recorded') : w.real;
  const cats = row
    ? [...row.cats, ...(row.extraCat ? [row.extraCat] : [])].map((c) => `<span class="rc-family">${esc(lab(language, c))}</span>`).join('')
    : '';
  return `<section class="rc-card" data-task="${esc(record.task)}" data-mode="${mode}">
    <header class="rc-card__head">
      <h4 class="rc-card__name">${esc(row ? lab(language, `${row.id}_name`) : record.task)}</h4>
      <p class="rc-card__tags"><span class="rc-family">${esc(actual.category)} · ${esc(actual.method)}</span><span class="rc-mode" data-mode="${mode}">${esc(modeText)}</span>${o.replay ? `<span class="rc-mode" data-mode="replay">${esc(w.replay)}</span>` : ''}</p>
    </header>
    <div class="rc-card__cols">
      <div class="rc-card__now"><p class="rc-card__eyebrow">${esc(w.thisTime)} · ${esc(cardProvenance(language, o))}</p><p class="rc-card__actual">${esc(actual.method)} · ${esc(modeText)}</p>${thisTime(record, language, o)}
        ${mode === 'fallback' ? `<p class="rc-card__note">${esc(w.fallbackNote)}</p>` : ''}
        ${o.replay ? `<p class="rc-card__note">${esc(w.replayNote)}</p>` : ''}
      </div>
      <div class="rc-card__how">${cats}<p class="rc-card__eyebrow">${esc(w.how)}</p>
        ${row ? `<p class="rc-card__method">${esc(lab(language, `${row.id}_method`))}</p>` : ''}
        ${record.task === 'retrieval' && (record.outputs as Record<string, unknown> | undefined)?.method === 'dense' ? `<p class="rc-card__note">${esc(w.denseNote)}</p>` : ''}
        <p class="rc-card__eyebrow">${esc(w.published)}</p>
        <ul class="rc-card__metrics" data-rc-metrics="${esc(rowId ?? '')}"></ul>
        ${rowId ? `<a class="rc-card__open" href="#/lab/${esc(rowId)}">${esc(w.open)} →</a>` : ''}
      </div>
    </div>
  </section>`;
}

/** Reads the published results once (cached) and fills every card's figures under `root`. */
export async function fillCardMetrics(root: ParentNode, language: Language) {
  const lists = [...root.querySelectorAll<HTMLElement>('[data-rc-metrics]:not([data-filled])')];
  if (!lists.length) return;
  const loaded = await results.load(RESULT_FILES);
  for (const ul of lists) {
    const row = REGISTER.find((r) => r.id === ul.dataset.rcMetrics);
    const html = row ? rowMetricsHtml(row, loaded, language) : '';
    ul.innerHTML = html || `<li class="rc-card__quiet">${esc(W[language].noFile)}</li>`;
    ul.dataset.filled = '';
  }
}

/** One listener for every chip that opens a card, wherever the chips were drawn (HTML strings in
 * ui.js, DOM in native slots). Opening fills the card's published figures. */
let installed = false;
export function installCardToggles(language: () => Language) {
  if (installed || typeof document === 'undefined') return;
  installed = true;
  document.addEventListener('click', (event) => {
    const key = (event.target as Element | null)?.closest?.<HTMLElement>('[data-rc-card]');
    if (!key) return;
    const card = document.getElementById(key.dataset.rcCard ?? '');
    if (!card) return;
    event.preventDefault();
    const open = card.hidden;
    // One card open per row: opening another closes the first.
    const row = key.closest('.rc-sigs-wrap');
    for (const other of row?.querySelectorAll<HTMLElement>('[data-rc-card][aria-expanded="true"]') ?? []) {
      if (other === key) continue;
      other.setAttribute('aria-expanded', 'false');
      const c = document.getElementById(other.dataset.rcCard ?? '');
      if (c) c.hidden = true;
    }
    card.hidden = !open;
    key.setAttribute('aria-expanded', String(open));
    if (open) void fillCardMetrics(card, language());
  });
}
