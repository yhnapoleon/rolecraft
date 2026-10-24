/** "One sentence, end to end" (top of #/lab): a claim walks the six stages of the
 * recognition pipeline. Above it, the work's sentences are a radio group marked the way the
 * lens marks them (same words, same counts as the delivery dialog), and, when the practice
 * was delivered more than once, a second radio group picks the delivery. Stages are a tab
 * list (arrow keys / Home / End move between them, selection follows focus); each stage's
 * detail sits in one tab panel: what the stage does on the left, its figure on the right.
 *
 * Motion: once, on entry, the claim travels stage by stage (each connector fills in 520 ms
 * on the spring curve, each note fades up in 280 ms). Any key or click stops it at the
 * final state; keyboard moves never animate. With reduced motion the final state shows at
 * once. */
import { criterionLabels } from '../feedback-native/criteria';
import { LENS_COPY } from '../recognition-native/lens-copy';
import type { Language } from '../results-native/localization';
import { tr, type Key } from './copy';
import { EXAMPLE_DELIVERY, type Chain, type Relation } from './data';
import { esc } from './html';

const f2 = (v: number) => v.toFixed(2);
const f3 = (v: number) => (v < 0.1 ? v.toFixed(3) : v.toFixed(2));

export const STAGES = ['sense', 'prep', 'repr', 'recog', 'decide', 'gen'] as const;
type Stage = (typeof STAGES)[number];
const STAGE_NAME: Record<Stage, Key> = {
  sense: 'st_sense',
  prep: 'st_prep',
  repr: 'st_repr',
  recog: 'st_recog',
  decide: 'st_decide',
  gen: 'st_gen',
};
/** Dwell per stage while the claim travels: long enough to read the short note. */
const STEP_MS = 1300;

const LABEL: Record<Relation, Key> = {
  supported: 'lab_supported',
  contradicted: 'lab_contradicted',
  insufficient: 'lab_insufficient',
};

/** How the lens marks a sentence (sentence-view.ts uses the same rule). */
export type Tone = 'supported' | 'contradicted' | 'insufficient' | 'deferred';
export const toneOf = (u: { label: Relation; decision: 'decide' | 'defer' }): Tone =>
  u.decision === 'defer' ? 'deferred' : u.label;
const TONES: Tone[] = ['supported', 'contradicted', 'insufficient', 'deferred'];
/** The lens's word for a mark, so this page reads like the delivery dialog and feedback. */
const toneWord = (l: Language, tone: Tone) =>
  LENS_COPY[l][
    tone === 'supported'
      ? 's_supported'
      : tone === 'contradicted'
        ? 's_contradicted'
        : tone === 'insufficient'
          ? 's_insufficient'
          : 's_deferred'
  ];

/** Keyboard on a radio group: where a key moves the choice, or null for keys it leaves. */
export function moveChoice(key: string, at: number, count: number): number | null {
  switch (key) {
    case 'ArrowRight':
    case 'ArrowDown':
      return (at + 1) % count;
    case 'ArrowLeft':
    case 'ArrowUp':
      return (at - 1 + count) % count;
    case 'Home':
      return 0;
    case 'End':
      return count - 1;
    default:
      return null;
  }
}

function short(text: string, max: number) {
  const chars = [...text];
  return chars.length > max ? `${chars.slice(0, max).join('')}…` : text;
}

function verdict(l: Language, label: string) {
  const key = `verdict_${label}` as Key;
  return ['MET', 'PARTIAL', 'NOT_MET', 'INSUFFICIENT'].includes(label) ? tr(l, key) : label;
}

/** "late_fusion:0.4|same_quantity:400 cny" → a sentence about what the rule found. */
export function ruleSentence(l: Language, reason: string) {
  const qty = (v: string, unit: string) => {
    const key = `unit_${unit}` as Key;
    return ['pday', 'person', 'cny', 'hour', 'day', 'pct', 'day_index'].includes(unit)
      ? tr(l, key, { v })
      : `${v} ${unit}`;
  };
  const same = reason.match(/same_quantity:([\d.]+) (\w+)/);
  if (same) return tr(l, 'rule_same', { qty: qty(same[1], same[2]) });
  const over = reason.match(/exceeds_limit:([\d.]+)>([\d.]+) (\w+)/);
  if (over)
    return tr(l, 'rule_exceeds', { claim: qty(over[1], over[3]), limit: qty(over[2], over[3]) });
  const diff = reason.match(/different_quantity:([\d.]+)!=([\d.]+) (\w+)/);
  if (diff)
    return tr(l, 'rule_different', { claim: qty(diff[1], diff[3]), stated: qty(diff[2], diff[3]) });
  return null;
}

function notes(c: Chain, l: Language): Record<Stage, string> {
  const label = tr(l, LABEL[c.label]);
  const arbiter = c.arbiter;
  return {
    sense: tr(l, 'sense_short'),
    prep: tr(l, 'prep_short', { i: c.index + 1, n: c.total }),
    // A unit may start with its heading or FAQ question; the note quotes the evidence part.
    repr: c.top[0]
      ? tr(l, 'repr_short', {
          quote: short(c.top[0].quote.split(' · ').pop() ?? '', l === 'zh' ? 18 : 34),
        })
      : tr(l, 'repr_short_none'),
    recog: tr(l, 'recog_short', { label }),
    decide: tr(l, c.decision === 'defer' ? 'decide_short_defer' : 'decide_short_decide'),
    gen: !arbiter
      ? tr(l, 'gen_short_none')
      : arbiter.agreement
        ? tr(l, 'gen_short_agree')
        : arbiter.final && arbiter.final !== arbiter.judge
          ? tr(l, 'gen_short_conservative', { final: verdict(l, arbiter.final) })
          : tr(l, 'gen_short_undecided'),
  };
}

/** The course families a stage's recogniser belongs to; the rule fallback says so instead. */
function families(stage: Stage, c: Chain, l: Language): string[] {
  switch (stage) {
    case 'repr':
      return [tr(l, 'cat_c2')];
    case 'recog':
      return c.fallback ? [tr(l, 'fallbackTag')] : [tr(l, 'cat_c1'), tr(l, 'cat_chain')];
    case 'decide':
      return [tr(l, 'cat_c6')];
    default:
      return [];
  }
}

/** One stage's detail: what it does (left) and its figure (right), as panel HTML. */
export function stageDetail(stage: Stage, c: Chain, l: Language) {
  const t = (k: Key, v: Record<string, string | number> = {}) => esc(tr(l, k, v));
  const label = tr(l, LABEL[c.label]);
  const tags = families(stage, c, l);
  const head = tags.length
    ? `<p class="rc-families" aria-label="${t('catLabel')}">${tags.map((x) => `<span class="rc-family"${c.fallback && stage === 'recog' ? ' data-extra' : ''}>${esc(x)}</span>`).join('')}</p>`
    : '';
  let text = '';
  let figure = '';
  switch (stage) {
    case 'sense': {
      const counts = c.counts;
      text = `<p>${counts ? t('sense_detail_counts', { tests: counts.scope ?? 0, replies: counts.reply_check ?? 0 }) : t('sense_detail')}</p>`;
      break;
    }
    case 'prep': {
      const ticks = Array.from(
        { length: c.total },
        (_, i) => `<i class="rc-tick-mark"${i === c.index ? ' data-on' : ''}></i>`,
      ).join('');
      figure = `<p class="rc-ticks" role="img" aria-label="${t('sentenceOf', { i: c.index + 1, n: c.total })}">${ticks}</p>`;
      text = `<p>${
        c.candidates != null
          ? t('prep_detail', { n: c.total, i: c.index + 1, m: c.candidates })
          : t('prep_detail_nounits', { n: c.total, i: c.index + 1 })
      }</p>`;
      break;
    }
    case 'repr':
      text = `<p>${t('repr_detail')}</p>`;
      figure = c.top.length
        ? `<ol class="rc-hits">${c.top
            .map(
              (h) =>
                `<li><span class="rc-hit-rank">${h.rank}</span><span class="rc-hit-quote">${esc(h.quote)}</span><span class="rc-hit-score">${t('repr_scores', { bm25: h.bm25 == null ? '–' : f2(h.bm25), dense: h.dense == null ? '–' : f2(h.dense) })}</span></li>`,
            )
            .join('')}</ol>`
        : `<p class="meta">${t('repr_short_none')}</p>`;
      break;
    case 'recog': {
      const rows = (['supported', 'contradicted', 'insufficient'] as const)
        .map((k) => {
          const p = c.probabilities[k];
          return `<li${k === c.label ? ' data-chosen' : ''} data-rel="${k}"><span>${t(LABEL[k])}</span><span class="rc-pbar"><i class="rc-bar-fill" style="transform:scaleX(${Math.max(0, Math.min(1, p)).toFixed(3)})"></i></span><span class="rc-pval">${f2(p)}</span></li>`;
        })
        .join('');
      const rule = ruleSentence(l, c.reason);
      figure = `<ul class="rc-lab-probs" aria-label="${t('st_recog')}">${rows}</ul>`;
      text = `<p>${t('recog_detail')}</p><p>${rule ? t('recog_rule', { rule }) : t('recog_pairs')}</p>${
        c.fallback ? `<p class="rc-fallback">${t('fallbackNote')}</p>` : ''
      }`;
      break;
    }
    case 'decide': {
      const scale = Math.max(c.expectedCost, c.deferCost) / 0.92 || 1;
      const bar = (name: string, v: number, chosen: boolean) =>
        `<li${chosen ? ' data-chosen' : ''}><span>${esc(name)}</span><span class="rc-cbar"><i class="rc-bar-fill" style="transform:scaleX(${(v / scale).toFixed(3)})"></i></span><span class="rc-pval">${f3(v)}</span></li>`;
      const decide = c.decision === 'decide';
      figure = `<ul class="rc-costs">${bar(tr(l, 'dec_decide'), c.expectedCost, decide)}${bar(tr(l, 'dec_defer'), c.deferCost, !decide)}</ul><p class="rc-figure-note">${t('decide_costs')}</p>`;
      text = `<p>${
        decide
          ? t('decide_detail_decide', { cost: f3(c.expectedCost), defer: f2(c.deferCost), label })
          : t('decide_detail_defer', { cost: f3(c.expectedCost), defer: f2(c.deferCost) })
      }</p>`;
      break;
    }
    case 'gen': {
      const a = c.arbiter;
      const criterion = a ? (criterionLabels(l)[a.criterion] ?? a.criterion) : '';
      const arbiter = !a
        ? t('gen_none')
        : a.agreement
          ? t('gen_agree', { criterion, judge: verdict(l, a.judge) })
          : a.final && a.final !== a.judge
            ? t('gen_conservative', {
                criterion,
                judge: verdict(l, a.judge),
                rec: verdict(l, a.recognizer),
                final: verdict(l, a.final),
              })
            : t('gen_undecided', {
                criterion,
                judge: verdict(l, a.judge),
                rec: verdict(l, a.recognizer),
              });
      const counts = c.counts;
      const peers = counts
        ? t('gen_peers_counts', {
            intent: counts.intent ?? 0,
            reply: counts.reply_check ?? 0,
            scope: counts.scope ?? 0,
            drift: counts.drift ?? 0,
          })
        : t('gen_peers');
      text = `<dl class="rc-gens"><div data-gen="judge"><dt>${t('generator_judge')}</dt><dd class="rc-gen-lead">${t(
        'gen_summary',
        {
          i: c.index + 1,
          label,
          k: c.evidence,
          decision: tr(l, c.decision === 'defer' ? 'dec_defer' : 'dec_decide'),
        },
      )} ${arbiter}</dd></div></dl>`;
      figure = `<dl class="rc-gens"><div><dt>${t('generator_roles')} · ${t('generator_assistant')}</dt><dd>${peers}</dd></div></dl>`;
      break;
    }
  }
  return `<div class="rc-st-text">${head}${text}</div>${figure ? `<div class="rc-st-figure">${figure}</div>` : ''}`;
}

/** A radio group of small keys; the chosen one alone sits in the tab order. */
function radioGroup(
  group: string,
  label: string,
  items: { value: number; checked: boolean; aria: string; html: string; tone?: Tone }[],
  labelledBy = '',
) {
  const name = labelledBy ? `aria-labelledby="${labelledBy}"` : `aria-label="${esc(label)}"`;
  return `<div class="rc-lab-radios" role="radiogroup" ${name} data-rc-group="${group}">${items
    .map(
      (item) =>
        `<button type="button" role="radio" class="rc-lab-radio" data-rc-${group === 'units' ? 'unit' : 'delivery'}="${item.value}"${item.tone ? ` data-tone="${item.tone}"` : ''} aria-checked="${item.checked}" tabindex="${item.checked ? 0 : -1}" aria-label="${esc(item.aria)}">${item.html}</button>`,
    )
    .join('')}</div>`;
}

const mark = (tone: Tone) => `<i class="rc-lab-mark" data-tone="${tone}" aria-hidden="true"></i>`;

export function pipelineHtml(c: Chain, l: Language) {
  const t = (k: Key, v: Record<string, string | number> = {}) => esc(tr(l, k, v));
  const brief = notes(c, l);
  const delivery = c.example ? null : c.deliveries[c.deliveryAt];
  const deliveryName = c.example
    ? tr(l, 'deliveryN', { n: EXAMPLE_DELIVERY })
    : delivery?.number != null
      ? tr(l, 'deliveryN', { n: delivery.number })
      : tr(l, 'deliveryLatest');
  const switcher =
    c.deliveries.length > 1 && c.deliveries.every((d) => d.number != null)
      ? radioGroup(
          'deliveries',
          tr(l, 'deliveryPick'),
          c.deliveries.map((d, i) => {
            const name = `${tr(l, 'deliveryN', { n: d.number ?? i + 1 })} · ${tr(l, 'nSentences', { n: d.total })}`;
            return {
              value: i,
              checked: i === c.deliveryAt,
              aria: name,
              html: `<span>${esc(tr(l, 'deliveryN', { n: d.number ?? i + 1 }))}</span><span class="rc-lab-radio-sub">${esc(tr(l, 'nSentences', { n: d.total }))}</span>`,
            };
          }),
        )
      : '';
  let units = '';
  if (c.units.length > 1) {
    const tally = new Map<Tone, number>();
    const items = c.units.map((u) => {
      const tone = toneOf(u);
      tally.set(tone, (tally.get(tone) ?? 0) + 1);
      return {
        value: u.index,
        checked: u.index === c.index,
        tone,
        aria: tr(l, 'pickOption', { i: u.index + 1, label: toneWord(l, tone), quote: u.quote }),
        html: `<span class="rc-lab-radio-num">${u.index + 1}</span>${mark(tone)}`,
      };
    });
    const key = TONES.filter((tone) => tally.get(tone))
      .map((tone) => `<span class="rc-lab-key">${mark(tone)}${esc(toneWord(l, tone))}\u00a0<b>${tally.get(tone)}</b></span>`)
      .join('');
    units = `<div class="rc-lab-units"><span class="rc-lab-units-label" id="rc-lab-units-label">${t('pick')}</span>${radioGroup('units', '', items, 'rc-lab-units-label')}<p class="rc-lab-units-key">${key}</p></div>`;
  }
  const current = toneOf({ label: c.label, decision: c.decision });
  const stations = STAGES.map(
    (s, i) =>
      `<li class="rc-station" data-state="ahead" role="presentation"><button type="button" role="tab" id="rc-st-${i}" class="rc-st" aria-selected="false" aria-controls="rc-st-panel" tabindex="-1" data-rc-stage="${i}"><span class="rc-node" aria-hidden="true"></span><span class="rc-st-num" aria-hidden="true">${String(i + 1).padStart(2, '0')}</span><span class="rc-st-name">${t(STAGE_NAME[s])}</span><span class="rc-st-note">${esc(brief[s])}</span></button>${i < STAGES.length - 1 ? '<span class="rc-seg" aria-hidden="true"><i class="rc-seg-fill"></i></span>' : ''}</li>`,
  ).join('');
  return `<div class="rc-claim">
      ${switcher || units ? `<div class="rc-claim-bar">${switcher}${units}</div>` : ''}
      <div class="rc-claim-meta"><p>${c.example ? `<span class="rc-example">${t('exampleTag')}</span>` : ''}<span>${esc(deliveryName)} · ${t('sentenceOf', { i: c.index + 1, n: c.total })}</span><span class="rc-lab-key">${mark(current)}${esc(toneWord(l, current))}</span></p><button type="button" class="btn quiet small rc-play" data-rc-play>${t('replay')}</button></div>
      <blockquote class="rc-claim-quote">${esc(c.quote)}</blockquote>
    </div>
    <ol class="rc-track" role="tablist" aria-label="${t('stationsLabel')}">${stations}</ol>
    <div class="rc-st-panel" role="tabpanel" id="rc-st-panel" tabindex="0" aria-labelledby="rc-st-5" data-rc-panel></div>
    <p class="rc-pipe-hint">${t('keysHint')}</p>`;
}

export interface PipelineHandle {
  stop(): void;
}

/** Wire the tab list and, unless motion is reduced, play the walk once. */
export function startPipeline(
  root: HTMLElement,
  c: Chain,
  l: Language,
  options: { reduced: boolean; autoplay: boolean },
): PipelineHandle {
  const tabs = [...root.querySelectorAll<HTMLButtonElement>('[data-rc-stage]')];
  const items = tabs.map((tab) => tab.parentElement as HTMLElement);
  const panel = root.querySelector<HTMLElement>('[data-rc-panel]');
  const play = root.querySelector<HTMLButtonElement>('[data-rc-play]');
  let reached = STAGES.length - 1;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const paint = (selected: number, animate: boolean) => {
    items.forEach((item, i) => {
      item.dataset.state = i < reached ? 'reached' : i === reached ? 'current' : 'ahead';
    });
    tabs.forEach((tab, i) => {
      tab.setAttribute('aria-selected', String(i === selected));
      tab.tabIndex = i === selected ? 0 : -1;
    });
    if (!panel) return;
    panel.setAttribute('aria-labelledby', `rc-st-${selected}`);
    panel.innerHTML = stageDetail(STAGES[selected], c, l);
    panel.dataset.stage = STAGES[selected];
    if (animate) {
      panel.classList.remove('is-entering');
      void panel.offsetWidth;
      panel.classList.add('is-entering');
    } else panel.classList.remove('is-entering');
  };

  const stop = () => {
    if (timer) clearTimeout(timer);
    timer = null;
    root.classList.remove('is-playing');
    if (play) play.textContent = tr(l, 'replay');
  };

  const finish = (selected = reached) => {
    stop();
    reached = STAGES.length - 1;
    paint(selected, false);
  };

  const walk = () => {
    stop();
    reached = 0;
    root.classList.add('is-playing');
    if (play) play.textContent = tr(l, 'replay');
    paint(0, true);
    const next = () => {
      if (reached >= STAGES.length - 1) {
        stop();
        return;
      }
      reached += 1;
      paint(reached, true);
      timer = setTimeout(next, STEP_MS);
    };
    timer = setTimeout(next, STEP_MS);
  };

  tabs.forEach((tab, i) => {
    tab.addEventListener('click', () => finish(i));
    tab.addEventListener('keydown', (event) => {
      const move: Record<string, number> = {
        ArrowRight: i + 1,
        ArrowDown: i + 1,
        ArrowLeft: i - 1,
        ArrowUp: i - 1,
        Home: 0,
        End: tabs.length - 1,
      };
      if (!(event.key in move)) return;
      event.preventDefault();
      const to = (move[event.key] + tabs.length) % tabs.length;
      finish(to);
      tabs[to].focus();
    });
  });
  play?.addEventListener('click', () => (options.reduced ? finish(0) : walk()));

  if (options.autoplay && !options.reduced) walk();
  else finish();
  return { stop };
}
