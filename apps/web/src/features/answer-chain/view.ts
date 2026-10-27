/** The answer chain as markup: five dots on one line, the reason under it, and the expanded
 * steps. String rendering for ui.js (test bench) and the evaluation desk. */
import { registerActions } from '../../shell/registry';
import type { Language } from '../results-native/localization';
import { chainText } from './copy';
import type { ChainView } from './model';
import './answer-chain.css';

export type ChainHtmlOptions = {
  language: Language;
  /** Show "Hand to Daniel" where the chain allows it (the caller checks the practice). */
  handover?: boolean;
  /** Offer "How the system judged ›" on the expanded steps (the run's records are on the page). */
  inspect?: boolean;
  /** Evaluation desk: no identity line, no "Show each step". */
  compact?: boolean;
  /** A result that just arrived: the dots come in once. */
  fresh?: boolean;
};

const esc = (value: unknown) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c,
  );

// Memory only: which chains are expanded, and which fresh results already came in once.
const open = new Set<string>();
const arrived = new Set<string>();
const INSPECT_TASKS = ['scope', 'retrieval', 'drift'];

/** `inspectOrder` is the run's recognition tasks in saved order, to find the matching record. */
export function answerChainHtml(
  view: ChainView,
  runId: string,
  options: ChainHtmlOptions,
  inspectOrder: string[] = [],
) {
  const { language } = options;
  const t = (key: Parameters<typeof chainText>[1]) => esc(chainText(language, key));
  const expanded = !options.compact && open.has(runId);
  const animate = !!options.fresh && !arrived.has(runId);
  if (options.fresh) arrived.add(runId);
  const rowsId = `ac-rows-${esc(runId)}`;
  const steps = view.stages
    .map(
      (s, i) =>
        `<li class="ac-step" data-state="${s.state}"${i === view.stopAt ? ' data-decides=""' : ''} style="--i:${i}"><span class="ac-dot" aria-hidden="true"></span><span class="ac-name" aria-hidden="true">${esc(s.label)}</span>${options.compact ? '' : `<span class="ac-who" aria-hidden="true">${esc(s.identity)}</span>`}<span class="sr-only">${esc(s.sr)}</span></li>`,
    )
    .join('');
  const handover =
    options.handover && view.handover
      ? `<button type="button" class="btn small quiet ac-key" data-action="engineer-handover" data-id="${esc(runId)}">${t('handover')}</button>`
      : '';
  const toggle = options.compact
    ? ''
    : `<button type="button" class="btn small quiet ac-key" data-action="chain-steps" aria-expanded="${expanded}" aria-controls="${rowsId}" data-show="${t('show_steps')}" data-hide="${t('hide_steps')}">${t(expanded ? 'hide_steps' : 'show_steps')}</button>`;
  const order = inspectOrder.filter((task) => INSPECT_TASKS.includes(task));
  const rows = options.compact
    ? ''
    : `<ul class="ac-rows" id="${rowsId}"${expanded ? '' : ' hidden'}>${view.rows
        .map((row, i) => {
          const stage = view.stages[i];
          const rest = row.startsWith(`${stage.label} · `)
            ? row.slice(stage.label.length + 3)
            : row;
          const index = stage.inspect ? order.indexOf(stage.inspect) : -1;
          const link =
            options.inspect && index >= 0
              ? `<button type="button" class="ac-inspect" data-action="chain-inspect" data-index="${index}">${t('how_judged')}</button>`
              : '';
          return `<li class="ac-row"><span class="ac-row-text"><strong>${esc(stage.label)}</strong> · ${esc(rest)}</span>${link}</li>`;
        })
        .join('')}</ul>`;
  return `<div class="ac" data-answer-chain data-run="${esc(runId)}" data-tone="${view.tone}"${options.compact ? ' data-compact=""' : ''}${animate ? ' data-arriving=""' : ''}><ol class="ac-path" aria-label="${t('path_label')}">${steps}</ol><div class="ac-foot"><p class="ac-reason">${esc(view.reason)}</p>${handover || toggle ? `<span class="ac-keys">${handover}${toggle}</span>` : ''}</div>${rows}</div>`;
}

/** Expand or fold one chain in place; the choice lasts for this page only. */
function toggleSteps(el: HTMLElement) {
  const chain = el.closest<HTMLElement>('[data-answer-chain]');
  const rows = chain?.querySelector<HTMLElement>('.ac-rows');
  const runId = chain?.dataset.run;
  if (!chain || !rows || !runId) return;
  const next = rows.hidden;
  rows.hidden = !next;
  if (next) open.add(runId);
  else open.delete(runId);
  el.setAttribute('aria-expanded', String(next));
  el.textContent = (next ? el.dataset.hide : el.dataset.show) ?? el.textContent;
}

/** Open the existing technical card of the same record, in the same run; no new inspector. */
function inspect(el: HTMLElement) {
  const run = el.closest('article.run');
  const index = Number(el.dataset.index);
  const target = run?.querySelectorAll<HTMLElement>('.rc-test-moment .rc-signature')[index];
  if (!target) return;
  if (target.getAttribute('aria-expanded') !== 'true') target.click();
  target.scrollIntoView?.({ block: 'nearest' });
  target.focus({ preventScroll: true });
}

registerActions({ 'chain-steps': toggleSteps, 'chain-inspect': inspect });

/** For tests: forget expanded and arrived chains. */
export function resetChainMemory() {
  open.clear();
  arrived.clear();
}
