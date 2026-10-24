/** Renderer of the recognition lens reading ("透镜读稿", spec 197 §7). It draws the pure view from
 * sentence-view.ts and nothing else: each sentence marked by its relation (sure ones drawn as a
 * line under the words, unsure ones dotted or dashed), a 12px mark at the line end, the numbers in
 * conflict highlighted, the material sentence on paper in the margin with a leader line (below the
 * sentence on a narrow screen), and one sentence at a time opening its five-step chain. The
 * reading is played only when asked (lens switched on, preview arrived, Replay); redraws show the
 * resting state. Changing the presentation changes this file and its CSS only. */
import type { ChainStepView, Part, SentenceLensView, SentenceSource, SentenceView } from './sentence-view';
import { sentenceLensView } from './sentence-view';
import { renderMeter } from './signals';

export { previewQuiet } from './sentence-view';
export type SentenceLensInput = SentenceSource & {
  /** The open sentence, kept across redraws: pass the same set (at most one index). */
  open?: Set<number>;
  /** A view built elsewhere; otherwise it is built from records or preview. */
  view?: SentenceLensView | null;
  /** Play the reading once this block is in the page. */
  play?: boolean;
};

const ENTER_MS = 300;
let ids = 0;

function maker(doc: Document) {
  return <K extends keyof HTMLElementTagNameMap>(tag: K, cls = '', text = '') => {
    const node = doc.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  };
}

function appendParts(doc: Document, host: HTMLElement, parts: Part[]) {
  for (const part of parts) {
    if (!part.mark) {
      host.append(part.text);
      continue;
    }
    const mark = doc.createElement('mark');
    mark.className = part.mark === 'src' ? 'rc-num is-src' : 'rc-num';
    mark.textContent = part.text;
    host.append(mark);
  }
}

const reduced = () =>
  typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Play the reading on a drawn block: sure lines drawn left to right sentence by sentence,
 * unsure ones faded in, marks, numbers, then leader lines and margin papers. At most 2.5 s; the
 * resting state is the end state. Over 30 sentences, or with reduced motion, everything fades. */
export function playReading(root: HTMLElement) {
  const rows = [...root.querySelectorAll<HTMLElement>('.rc-srow')];
  const n = rows.length;
  if (!n) return;
  delete root.dataset.reading;
  void root.offsetWidth;
  let total: number;
  if (reduced()) {
    root.dataset.reading = 'fade';
    total = 200;
  } else if (n > 30) {
    root.dataset.reading = 'flat';
    total = 320;
  } else {
    const step = Math.min(110, 1300 / n);
    let lastSure = 80;
    rows.forEach((row, i) => {
      const start = 80 + i * step;
      row.style.setProperty('--rc-t', `${Math.round(start)}ms`);
      if (row.dataset.certain !== undefined) lastSure = start + 520;
    });
    const threads = lastSure - 100;
    root.style.setProperty('--rc-T', `${Math.round(threads)}ms`);
    root.dataset.reading = 'draw';
    total = Math.max(threads + 520, 80 + (n - 1) * step + 480 + 280) + 40;
  }
  const token = String(Date.now() + Math.random());
  root.dataset.readingToken = token;
  setTimeout(() => {
    if (root.dataset.readingToken !== token) return;
    delete root.dataset.reading;
    delete root.dataset.readingToken;
  }, total);
}

export function renderSentenceLens(doc: Document, input: SentenceLensInput): HTMLElement {
  const el = maker(doc);
  const open = input.open ?? new Set<number>();
  const view = input.view ?? sentenceLensView(input);
  const root = el('section', 'rc-sentences');
  root.setAttribute('data-rc-sentences', '');
  if (!view) return root;
  const head = el('header', 'rc-sentences__head');
  head.append(el('h4', 'rc-sentences__title', view.title), el('span', 'rc-sentences__counts', view.counts));
  const cats = el('span', 'rc-sentences__cats');
  for (const category of view.categories) {
    const cat = el('span', 'rc-cat', category.text);
    if (category.fallback) cat.setAttribute('data-fallback', '');
    cats.append(cat);
  }
  const replay = el('button', 'rc-replay');
  replay.setAttribute('type', 'button');
  replay.setAttribute('aria-label', view.replay);
  const icon = el('span', 'rc-replay__icon');
  icon.setAttribute('aria-hidden', 'true');
  replay.append(icon, el('span', 'rc-replay__label', view.replay));
  replay.addEventListener('click', () => playReading(root));
  head.append(cats, replay);
  const legend = el('p', 'rc-sentences__legend');
  for (const item of view.legend) {
    const key = el('span', 'rc-key');
    key.dataset.tone = item.tone;
    const swatch = el('i');
    swatch.setAttribute('aria-hidden', 'true');
    key.append(swatch, item.label);
    legend.append(key);
  }
  root.append(head, legend, el('p', 'rc-sentences__note', view.note));
  const list = el('ol', 'rc-slist');
  const rows: { sentence: SentenceView; show: (open: boolean, animate: boolean) => void; toggle: HTMLButtonElement }[] = [];
  for (const sentence of view.sentences) {
    const row = el('li', 'rc-srow');
    row.dataset.tone = sentence.tone;
    if (sentence.certain) row.dataset.certain = '';
    if (sentence.sure) row.dataset.sure = sentence.sure;
    const main = el('div', 'rc-srow__main');
    const chainId = `rc-chain-${++ids}`;
    const toggle = el('button', 'rc-s');
    toggle.setAttribute('type', 'button');
    toggle.setAttribute('aria-controls', chainId);
    const text = el('span', 'rc-s__text');
    appendParts(doc, text, sentence.parts);
    toggle.append(text, el('span', 'sr-only', ` (${sentence.srText})`));
    const marker = el('span', 'rc-mkr');
    marker.setAttribute('aria-hidden', 'true');
    main.append(toggle, marker);
    row.append(main);
    let paper: HTMLElement | null = null;
    if (sentence.source) {
      paper = el('aside', 'rc-s__match');
      paper.dataset.relation = sentence.source.relation;
      const lead = el('span', 'rc-lead');
      lead.setAttribute('aria-hidden', 'true');
      paper.append(lead);
      if (sentence.source.title || sentence.source.version) {
        const top = el('p', 'rc-src__top');
        top.append(el('b', '', sentence.source.title ?? ''), el('span', '', sentence.source.version ?? ''));
        paper.append(top);
      }
      const quote = el('p', 'rc-src__quote');
      appendParts(doc, quote, sentence.source.parts);
      paper.append(quote, el('p', 'rc-src__rel', sentence.source.relationLabel));
      row.append(paper);
    }
    const chain = el('div', 'rc-chain');
    chain.id = chainId;
    let filled = false;
    const show = (isOpen: boolean, animate: boolean) => {
      chain.hidden = !isOpen;
      toggle.setAttribute('aria-expanded', String(isOpen));
      if (isOpen) row.dataset.open = '';
      else delete row.dataset.open;
      if (paper) {
        const visible = sentence.shown === 'always' || isOpen;
        const was = !paper.hidden;
        paper.hidden = !visible;
        if (animate && visible && !was) {
          const target = paper;
          target.dataset.entering = '';
          setTimeout(() => delete target.dataset.entering, ENTER_MS);
        }
      }
      if (isOpen && !filled) {
        filled = true;
        chain.append(renderChain(doc, sentence, view.showAll));
      }
    };
    show(open.has(sentence.index), false);
    row.append(chain);
    list.append(row);
    rows.push({ sentence, show, toggle });
  }
  // One sentence open at a time: opening another closes the one before.
  for (const { sentence, show, toggle } of rows) {
    toggle.addEventListener('click', () => {
      const opening = !open.has(sentence.index);
      for (const other of rows)
        if (other.sentence.index !== sentence.index && open.has(other.sentence.index)) {
          open.delete(other.sentence.index);
          other.show(false, false);
        }
      if (opening) open.add(sentence.index);
      else open.delete(sentence.index);
      show(opening, true);
    });
  }
  // Up and down move between sentences.
  list.addEventListener('keydown', (event: Event) => {
    const key = (event as KeyboardEvent).key;
    if (key !== 'ArrowDown' && key !== 'ArrowUp') return;
    const at = rows.findIndex((r) => r.toggle === (doc.activeElement as unknown));
    if (at < 0) return;
    const next = rows[at + (key === 'ArrowDown' ? 1 : -1)];
    if (!next) return;
    event.preventDefault();
    next.toggle.focus();
  });
  root.append(list);
  if (input.play && typeof requestAnimationFrame === 'function')
    requestAnimationFrame(() => {
      if (root.isConnected) playReading(root);
    });
  return root;
}

function renderChain(doc: Document, sentence: SentenceView, showAll: string): HTMLElement {
  const el = maker(doc);
  const panel = el('div', 'rc-chain__panel');
  const head = el('p', 'rc-chain__head');
  head.append(el('b', '', sentence.chain.head), el('q', '', sentence.chain.quote));
  panel.append(head, renderSteps(doc, sentence.chain.steps, showAll));
  return panel;
}

function renderSteps(doc: Document, steps: ChainStepView[], showAll: string) {
  const el = maker(doc);
  const list = el('ol', 'rc-steps');
  for (const step of steps) {
    const li = el('li', 'rc-step');
    li.dataset.step = step.step;
    if (step.muted) li.dataset.muted = '';
    li.append(el('p', 'rc-step__name', step.name));
    const result = el('p', 'rc-step__result', step.result);
    result.dataset.tone = step.resultTone;
    li.append(result);
    if (step.cells != null) {
      const cells = el('span', 'rc-cells');
      cells.setAttribute('role', 'img');
      cells.setAttribute('aria-label', step.cellsLabel ?? '');
      for (let i = 0; i < 5; i++) {
        const cell = el('i', 'rc-cell');
        if (i < step.cells) cell.dataset.on = '';
        cells.append(cell);
      }
      li.append(cells);
    }
    li.append(el('p', 'rc-step__method', step.method));
    const category = el('span', 'rc-step__cat', step.category);
    if (step.fallback) category.dataset.fallback = '';
    li.append(category);
    if (step.note) li.append(el('p', 'rc-step__note', step.note));
    if (step.hit) li.append(hitRow(doc, step.hit));
    if (step.more) {
      const more = el('details', 'rc-step__more');
      more.append(el('summary', '', step.more.label || showAll));
      for (const hit of step.more.hits) more.append(hitRow(doc, hit));
      if (step.more.probabilities.length) {
        const probs = el('ul', 'rc-probs');
        for (const p of step.more.probabilities) {
          const row = el('li');
          row.dataset.label = p.key;
          row.append(el('span', '', p.label), renderMeter(doc, p.meter));
          probs.append(row);
        }
        more.append(probs);
      }
      li.append(more);
    }
    list.append(li);
  }
  return list;
}

function hitRow(doc: Document, hit: { rank: number; quote: string; cited: boolean }) {
  const el = maker(doc);
  const row = el('p', hit.cited ? 'rc-hit is-cited' : 'rc-hit');
  row.append(el('span', 'rc-hit__rank', `#${hit.rank}`), el('span', 'rc-hit__quote', hit.quote));
  return row;
}
