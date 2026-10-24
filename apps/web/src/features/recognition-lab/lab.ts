/** System profile (#/lab): how the system recognises, for reviewers and the video.
 *
 * Top: one sentence walks the pipeline (this practice's records, or a marked example).
 * Middle: the seven recognisers with their course family and published figures.
 * Bottom: the experiment story, E1–E10 and the real-data line E11 → E14 → E15.
 *
 * ui.js mounts this once per entry into the route and keeps the element across redraws;
 * a language switch mounts again from the cached data. Styles load with the main bundle.
 */
import type { SessionRecognition } from '../recognition-native/client';
import type { Language } from '../results-native/localization';
import { tr } from './copy';
import { chainFor, RESULT_FILES, results, sessionRecords, type Results } from './data';
import { type PipelineHandle, pipelineHtml, startPipeline } from './pipeline';
import { registerHtml } from './register';
import { storyHtml } from './story';
import { st } from './story-copy';
import { esc } from './html';

export interface LabOptions {
  language: Language;
  session: (() => Promise<SessionRecognition>) | null;
  /** The practice whose records are shown; '' when there is none. */
  sessionKey: string;
  /** True on entering the route: read this practice's records again. */
  refresh: boolean;
}

let seq = 0;
let pipeline: PipelineHandle | null = null;
let observer: ResizeObserver | null = null;
const wired = new WeakSet<HTMLElement>();

const reducedMotion = () =>
  typeof window !== 'undefined' &&
  !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
const NARROW = 600;
const chartWidth = (root: HTMLElement) => ((root.clientWidth || 1024) < NARROW ? 340 : 520);

function skeleton(l: Language) {
  const t = (k: Parameters<typeof tr>[1]) => esc(tr(l, k));
  const jump = (target: string, label: string) =>
    `<button type="button" class="rc-toc-link" data-rc-jump="${target}">${label}</button>`;
  return `<header class="rc-head">
      <h1 class="title-xl">${t('title')}</h1>
      <p class="rc-lead">${t('lead')}</p>
      <nav class="rc-toc" aria-label="${t('navLabel')}">${jump('rc-pipe', t('navPipeline'))}${jump('rc-register', t('navRegister'))}${jump('rc-story', t('navStory'))}</nav>
    </header>
    <section class="rc-section" id="rc-pipe" aria-labelledby="rc-pipe-title">
      <header class="rc-sec-head"><h2 id="rc-pipe-title" tabindex="-1">${t('pipeTitle')}</h2><p class="rc-sec-lead" data-rc-pipe-lead>${t('loading')}</p></header>
      <div class="paper rc-pipe" data-rc-pipe></div>
    </section>
    <section class="rc-section" id="rc-register" aria-labelledby="rc-register-title">
      <header class="rc-sec-head"><h2 id="rc-register-title" tabindex="-1">${t('regTitle')}</h2><p class="rc-sec-lead">${t('regLead')}</p></header>
      <div data-rc-register><p class="meta">${t('loading')}</p></div>
    </section>
    <section class="rc-section" id="rc-story" aria-labelledby="rc-story-title">
      <header class="rc-sec-head"><h2 id="rc-story-title" tabindex="-1">${esc(st(l, 'storyTitle'))}</h2><p class="rc-sec-lead">${esc(st(l, 'storyLead'))}</p></header>
      <div data-rc-story><p class="meta">${t('loading')}</p></div>
    </section>`;
}

function drawPipeline(
  root: HTMLElement,
  data: SessionRecognition | null,
  l: Language,
  selected?: number,
  autoplay = true,
) {
  const box = root.querySelector<HTMLElement>('[data-rc-pipe]');
  const lead = root.querySelector<HTMLElement>('[data-rc-pipe-lead]');
  if (!box) return;
  pipeline?.stop();
  const chain = chainFor(data, l, selected);
  if (lead) lead.textContent = tr(l, chain.example ? 'pipeLeadExample' : 'pipeLead');
  box.dataset.example = String(chain.example);
  box.innerHTML = pipelineHtml(chain, l);
  const reduced = reducedMotion();
  const play = box.querySelector<HTMLElement>('[data-rc-play]');
  if (play) play.hidden = reduced;
  pipeline = startPipeline(box, chain, l, { reduced, autoplay });
  box.querySelector<HTMLSelectElement>('[data-rc-unit]')?.addEventListener('change', (event) => {
    drawPipeline(root, data, l, Number((event.target as HTMLSelectElement).value));
    box.querySelector<HTMLSelectElement>('[data-rc-unit]')?.focus();
  });
}

function drawStory(root: HTMLElement, loaded: Results, l: Language) {
  const story = root.querySelector<HTMLElement>('[data-rc-story]');
  if (!story) return;
  const width = chartWidth(root);
  story.dataset.width = String(width);
  story.innerHTML = storyHtml(loaded, l, width);
}

export async function mountLab(root: HTMLElement, options: LabOptions) {
  const mine = ++seq;
  const l = options.language;
  pipeline?.stop();
  observer?.disconnect();
  root.innerHTML = skeleton(l);
  if (!wired.has(root)) {
    wired.add(root);
    root.addEventListener('click', (event) => {
      const button = (event.target as HTMLElement).closest<HTMLElement>('[data-rc-jump]');
      if (!button) return;
      const heading = root.querySelector<HTMLElement>(`#${button.dataset.rcJump} h2`);
      heading?.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' });
      heading?.focus({ preventScroll: true });
    });
  }
  const [loaded, data] = await Promise.all([
    results.load(RESULT_FILES),
    sessionRecords.read(options.sessionKey, options.session, options.refresh),
  ]);
  if (mine !== seq) return;
  drawPipeline(root, data, l);
  const register = root.querySelector<HTMLElement>('[data-rc-register]');
  if (register) register.innerHTML = registerHtml(loaded, l);
  drawStory(root, loaded, l);
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(() => {
      const story = root.querySelector<HTMLElement>('[data-rc-story]');
      if (story && story.dataset.width !== String(chartWidth(root))) drawStory(root, loaded, l);
    });
    observer.observe(root);
  }
}
