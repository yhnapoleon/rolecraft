/** #/engineer-report: two real regression reports (public/engineer/*.json, produced by the
 * engineer CLI against a local practice; see public/engineer/README.md), read-only.
 * The page is built once and kept: a host re-render re-attaches the same sheet, so the chosen
 * sample and the open "查看依据" survive; only a language change rebuilds it. */
import { copyText, type CopyTable, type Language } from '../results-native/localization';
import { renderEngineerReport } from './render';
import type { EngineerPublicReport } from './types';
import { engineerReportView } from './view';
import './page.css';

const SAMPLES = [
  { id: 'fixed', file: 'sample-target-fixed', label: 'fixed' },
  { id: 'not-fixed', file: 'sample-target-not-fixed', label: 'notFixed' },
] as const;
type SampleId = (typeof SAMPLES)[number]['id'];

const zh = {
  title: '知识助手配置的回归报告',
  sample: '样例',
  choose: '选择样例',
  fixed: '目标已修好',
  notFixed: '目标没修好',
  loading: '正在读取…',
  failed: '读不到这份样例，刷新页面再试。',
  retrieval: '规则版检索',
};
type Key = keyof typeof zh;
const COPY: CopyTable<Key> = {
  zh,
  en: {
    title: 'Regression reports for the assistant configuration',
    sample: 'Sample',
    choose: 'Choose a sample',
    fixed: 'Target fixed',
    notFixed: 'Target not fixed',
    loading: 'Loading…',
    failed: "Couldn't load this sample. Reload the page to try again.",
    retrieval: 'Rule-based retrieval',
  },
};

/** The sample files for one language, keyed by sample. */
export const sampleUrl = (sample: SampleId, language: Language) =>
  `/engineer/${SAMPLES.find((s) => s.id === sample)?.file}.${language}.json`;

const reports = new Map<string, Promise<EngineerPublicReport>>();
function load(url: string): Promise<EngineerPublicReport> {
  let pending = reports.get(url);
  if (!pending) {
    pending = fetch(url).then((response) => {
      if (!response.ok) throw new Error(String(response.status));
      return response.json() as Promise<EngineerPublicReport>;
    });
    pending.catch(() => reports.delete(url));
    reports.set(url, pending);
  }
  return pending;
}

const state: { sample: SampleId; basisOpen: Record<SampleId, boolean> } = {
  sample: 'fixed',
  basisOpen: { fixed: false, 'not-fixed': false },
};
let kept: { language: Language; element: HTMLElement } | null = null;

export function mountEngineerReportPage(root: HTMLElement, options: { language: Language }) {
  if (kept?.language === options.language && kept.element.ownerDocument === root.ownerDocument) {
    root.replaceChildren(kept.element);
    return;
  }
  const element = buildPage(root.ownerDocument, options.language);
  kept = { language: options.language, element };
  root.replaceChildren(element);
}

function buildPage(doc: Document, language: Language): HTMLElement {
  const t = (key: Key) => copyText(COPY, language, key);
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text?: string) => {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const page = el('div', 'er-page');
  page.lang = language === 'zh' ? 'zh-CN' : 'en';
  const head = el('header', 'er-page__head');
  head.append(el('h1', 'er-page__title', t('title')), el('span', 'er-page__sample', t('sample')));
  const choose = el('div', 'segmented er-page__switch');
  choose.setAttribute('role', 'group');
  choose.setAttribute('aria-label', t('choose'));
  const thumb = el('span', 'thumb');
  thumb.setAttribute('aria-hidden', 'true');
  choose.append(thumb);
  const buttons = SAMPLES.map((sample) => {
    const button = el('button', '', t(sample.label));
    button.type = 'button';
    button.dataset.sample = sample.id;
    button.addEventListener('click', () => {
      if (state.sample === sample.id) return;
      state.sample = sample.id;
      press();
      void show(true);
    });
    choose.append(button);
    return button;
  });
  const sheet = el('div', 'er-page__sheet');
  page.append(head, choose, sheet);

  let moved = false;
  function press() {
    for (const button of buttons)
      button.setAttribute('aria-pressed', String(button.dataset.sample === state.sample));
    const active = buttons.find((b) => b.dataset.sample === state.sample);
    if (!active?.offsetWidth) return;
    // First placement jumps; later ones slide with the shared segmented transition.
    if (!moved) thumb.style.transition = 'none';
    thumb.style.opacity = '1';
    thumb.style.width = `${active.offsetWidth}px`;
    thumb.style.transform = `translateX(${active.offsetLeft - 2}px)`;
    if (!moved) {
      void thumb.offsetWidth;
      thumb.style.transition = '';
      moved = true;
    }
  }

  let token = 0;
  async function show(animate: boolean) {
    const mine = ++token;
    const sample = state.sample;
    sheet.setAttribute('aria-busy', 'true');
    let report: EngineerPublicReport;
    try {
      report = await load(sampleUrl(sample, language));
    } catch {
      if (mine === token) {
        sheet.replaceChildren(el('p', 'er-page__note', t('failed')));
        sheet.removeAttribute('aria-busy');
      }
      return;
    }
    if (mine !== token) return;
    const drawn = renderEngineerReport(
      doc,
      engineerReportView(report, { language, retrievalNote: t('retrieval') }),
      {
        basisOpen: state.basisOpen[sample],
        onBasisToggle: (open) => {
          state.basisOpen[sample] = open;
        },
      },
    );
    if (animate) {
      drawn.classList.add('er-enter');
      drawn.addEventListener('animationend', () => drawn.classList.remove('er-enter'), {
        once: true,
      });
    }
    sheet.replaceChildren(drawn);
    sheet.removeAttribute('aria-busy');
  }

  press();
  sheet.append(el('p', 'er-page__note', t('loading')));
  void show(true);
  // The thumb needs layout; place it once the page is in the document.
  requestAnimationFrame(press);
  return page;
}
