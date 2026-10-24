/** "One sentence, end to end" (top of #/lab): a claim walks the six stages of the
 * recognition pipeline. Stages are a tab list (arrow keys / Home / End move between them,
 * selection follows focus); each stage's detail sits in one tab panel.
 *
 * Motion: once, on entry, the claim travels stage by stage (each connector fills in 520 ms
 * on the spring curve, each note fades up in 280 ms). Any key or click stops it at the
 * final state; keyboard moves never animate. With reduced motion the final state shows at
 * once. */
import { criterionLabels } from '../feedback-native/criteria';
import type { Language } from '../results-native/localization';
import { tr, type Key } from './copy';
import type { Chain, Relation } from './data';
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

function detail(stage: Stage, c: Chain, l: Language) {
  const t = (k: Key, v: Record<string, string | number> = {}) => esc(tr(l, k, v));
  const label = tr(l, LABEL[c.label]);
  switch (stage) {
    case 'sense': {
      const counts = c.counts;
      return `<p>${counts ? t('sense_detail_counts', { tests: counts.scope ?? 0, replies: counts.reply_check ?? 0 }) : t('sense_detail')}</p>`;
    }
    case 'prep': {
      const ticks = Array.from(
        { length: c.total },
        (_, i) => `<i class="rc-tick-mark"${i === c.index ? ' data-on' : ''}></i>`,
      ).join('');
      return `<p class="rc-ticks" role="img" aria-label="${t('sentenceOf', { i: c.index + 1, n: c.total })}">${ticks}</p><p>${
        c.candidates != null
          ? t('prep_detail', { n: c.total, i: c.index + 1, m: c.candidates })
          : t('prep_detail_nounits', { n: c.total, i: c.index + 1 })
      }</p>`;
    }
    case 'repr':
      return `<p>${t('repr_detail')}</p>${
        c.top.length
          ? `<ol class="rc-hits">${c.top
              .map(
                (h) =>
                  `<li><span class="rc-hit-rank">${h.rank}</span><span class="rc-hit-quote">${esc(h.quote)}</span><span class="rc-hit-score">${t('repr_scores', { bm25: h.bm25 == null ? '–' : f2(h.bm25), dense: h.dense == null ? '–' : f2(h.dense) })}</span></li>`,
              )
              .join('')}</ol>`
          : `<p class="meta">${t('repr_short_none')}</p>`
      }`;
    case 'recog': {
      const rows = (['supported', 'contradicted', 'insufficient'] as const)
        .map((k) => {
          const p = c.probabilities[k];
          return `<li${k === c.label ? ' data-chosen' : ''} data-rel="${k}"><span>${t(LABEL[k])}</span><span class="rc-pbar"><i class="rc-bar-fill" style="transform:scaleX(${Math.max(0, Math.min(1, p)).toFixed(3)})"></i></span><span class="rc-pval">${f2(p)}</span></li>`;
        })
        .join('');
      const rule = ruleSentence(l, c.reason);
      return `<ul class="rc-lab-probs" aria-label="${t('st_recog')}">${rows}</ul><p>${t('recog_detail')}</p><p>${rule ? t('recog_rule', { rule }) : t('recog_pairs')}</p>${
        c.fallback ? `<p class="rc-fallback">${t('fallbackNote')}</p>` : ''
      }`;
    }
    case 'decide': {
      const scale = Math.max(c.expectedCost, c.deferCost) / 0.92 || 1;
      const bar = (name: string, v: number, chosen: boolean) =>
        `<li${chosen ? ' data-chosen' : ''}><span>${esc(name)}</span><span class="rc-cbar"><i class="rc-bar-fill" style="transform:scaleX(${(v / scale).toFixed(3)})"></i></span><span class="rc-pval">${f3(v)}</span></li>`;
      const decide = c.decision === 'decide';
      return `<ul class="rc-costs">${bar(tr(l, 'dec_decide'), c.expectedCost, decide)}${bar(tr(l, 'dec_defer'), c.deferCost, !decide)}</ul><p>${
        decide
          ? t('decide_detail_decide', { cost: f3(c.expectedCost), defer: f2(c.deferCost), label })
          : t('decide_detail_defer', { cost: f3(c.expectedCost), defer: f2(c.deferCost) })
      }</p><p class="meta">${t('decide_costs')}</p>`;
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
      return `<dl class="rc-gens"><div data-gen="judge"><dt>${t('generator_judge')}</dt><dd class="rc-gen-lead">${t(
        'gen_summary',
        {
          i: c.index + 1,
          label,
          k: c.evidence,
          decision: tr(l, c.decision === 'defer' ? 'dec_defer' : 'dec_decide'),
        },
      )} ${arbiter}</dd></div><div><dt>${t('generator_roles')} · ${t('generator_assistant')}</dt><dd>${peers}</dd></div></dl>`;
    }
  }
}

export function pipelineHtml(c: Chain, l: Language) {
  const t = (k: Key, v: Record<string, string | number> = {}) => esc(tr(l, k, v));
  const brief = notes(c, l);
  const picker = c.units.length
    ? `<label class="rc-pick"><span>${t('pick')}</span><select id="rc-unit" data-rc-unit>${c.units
        .map(
          (u) =>
            `<option value="${u.index}"${u.index === c.index ? ' selected' : ''}>${t('pickOption', {
              i: u.index + 1,
              label: tr(l, u.decision === 'defer' ? 'dec_defer' : LABEL[u.label]),
              quote: short(u.quote, l === 'zh' ? 22 : 44),
            })}</option>`,
        )
        .join('')}</select></label>`
    : '';
  const stations = STAGES.map(
    (s, i) =>
      `<li class="rc-station" data-state="ahead" role="presentation"><button type="button" role="tab" id="rc-st-${i}" class="rc-st" aria-selected="false" aria-controls="rc-st-panel" tabindex="-1" data-rc-stage="${i}"><span class="rc-node" aria-hidden="true"></span><span class="rc-st-num" aria-hidden="true">${String(i + 1).padStart(2, '0')}</span><span class="rc-st-name">${t(STAGE_NAME[s])}</span><span class="rc-st-note">${esc(brief[s])}</span></button>${i < STAGES.length - 1 ? '<span class="rc-seg" aria-hidden="true"><i class="rc-seg-fill"></i></span>' : ''}</li>`,
  ).join('');
  return `<div class="rc-claim">
      <p class="rc-claim-meta">${c.example ? `<span class="rc-example">${t('exampleTag')}</span>` : ''}<span>${t('sentenceOf', { i: c.index + 1, n: c.total })}</span><span class="rc-claim-actions">${picker}<button type="button" class="btn quiet small rc-play" data-rc-play>${t('replay')}</button></span></p>
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
    panel.innerHTML = detail(STAGES[selected], c, l);
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
