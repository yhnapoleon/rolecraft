/** One read-only inspector for local entries and the global technical view. */
import type { Language } from '../results-native/localization';
import './evidence-check.css';
import { activeModal, containModalTab } from '../../app/modal-keyboard';
export const escapeCheck = (value: unknown) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c,
  );
export const layersIcon =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/></svg>';
let serial = 0;
export function openRecordInspector(
  trigger: HTMLElement,
  title: string,
  record: string,
  methods: string,
  language: Language,
) {
  const doc = trigger.ownerDocument;
  const t = (zh: string, en: string) => (language === 'zh' ? zh : en);
  const parent = trigger.closest<HTMLDialogElement>('dialog[open]');
  const dialog = parent ?? doc.createElement('dialog');
  const saved = parent ? [...parent.childNodes] : [];
  const scroll = [...doc.querySelectorAll<HTMLElement>('*')]
    .filter((e) => e.scrollTop || e.scrollLeft || e.scrollHeight > e.clientHeight || e.scrollWidth > e.clientWidth)
    .map((node) => ({ node, top: node.scrollTop, left: node.scrollLeft }));
  const oldLabel = dialog.getAttribute('aria-labelledby');
  const id = `record-inspector-${++serial}`;
  dialog.classList.add('rc-inspector');
  dialog.setAttribute('aria-labelledby', id);
  dialog.innerHTML = `<header class="ri-head"><div><p>${t('系统如何判断 · 只读记录', 'How this was assessed · Read-only record')}</p><h2 id="${id}" tabindex="-1">${escapeCheck(title)}</h2></div><button type="button" data-ri-close>${t(parent ? '返回原句与依据' : '关闭', parent ? 'Back to claim and source' : 'Close')}</button></header><div class="ri-body"><div role="tablist" aria-label="${t('识别详情', 'Assessment details')}" class="ri-tabs"><button type="button" role="tab" id="${id}-tab0" aria-controls="${id}-panel0" aria-selected="true" data-ri-tab="0">${t('本次记录', 'This record')}</button><button type="button" role="tab" id="${id}-tab1" aria-controls="${id}-panel1" aria-selected="false" tabindex="-1" data-ri-tab="1">${t('方法与实验', 'Methods and evaluation')}</button></div><section role="tabpanel" id="${id}-panel0" aria-labelledby="${id}-tab0" data-ri-panel="0">${record}</section><section role="tabpanel" id="${id}-panel1" aria-labelledby="${id}-tab1" data-ri-panel="1" hidden>${methods}</section></div>`;
  let restored = false;
  const restore = () => {
    if (restored) return;
    restored = true;
    dialog.removeEventListener('cancel', cancel);
    doc.removeEventListener('keydown', handleKeyboard, true);
    dialog.removeEventListener('close', restore);
    if (parent) {
      dialog.replaceChildren(...saved);
      dialog.classList.remove('rc-inspector');
      if (oldLabel) dialog.setAttribute('aria-labelledby', oldLabel);
      else dialog.removeAttribute('aria-labelledby');
    } else dialog.remove();
    trigger.setAttribute('aria-expanded', 'false');
    trigger.focus({ preventScroll: true });
    for (const p of scroll) {
      p.node.scrollTop = p.top;
      p.node.scrollLeft = p.left;
    }
  };
  const cancel = (e: Event) => {
    e.preventDefault();
    e.stopPropagation();
    restore();
  };
  const handleKeyboard = (event: KeyboardEvent) => {
    if (activeModal(doc) !== dialog) return;
    if (event.key === 'Tab') containModalTab(event, dialog);
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopImmediatePropagation();
    restore();
  };
  doc.addEventListener('keydown', handleKeyboard, true);
  dialog.addEventListener('cancel', cancel);
  dialog.addEventListener('close', restore);
  const closeButton = dialog.querySelector<HTMLButtonElement>('[data-ri-close]');
  if (closeButton) closeButton.onclick = restore;
  const tabs = [...dialog.querySelectorAll<HTMLButtonElement>('[data-ri-tab]')];
  const select = (i: number) => {
    tabs.forEach((b, n) => {
      b.setAttribute('aria-selected', String(n === i));
      b.tabIndex = n === i ? 0 : -1;
    });
    dialog.querySelectorAll<HTMLElement>('[data-ri-panel]').forEach((p, n) => {
      p.hidden = n !== i;
    });
  };
  tabs.forEach((b, i) => {
    b.onclick = () => select(i);
    b.onkeydown = (e) => {
      if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) {
        e.preventDefault();
        const next = e.key === 'Home' ? 0 : e.key === 'End' ? 1 : 1 - i;
        select(next);
        tabs[next].focus();
      }
    };
  });
  dialog.querySelectorAll<HTMLElement>('a[href], [data-ri-about]').forEach((a) => {
    a.addEventListener('click', () => {
      restore();
      if (parent?.open) parent.close();
    });
  });
  if (!parent) {
    doc.body.append(dialog);
    dialog.showModal();
  }
  trigger.setAttribute('aria-expanded', 'true');
  dialog.querySelector<HTMLElement>('h2')?.focus({ preventScroll: true });
  return dialog;
}
export function inspectorEntryHtml(
  title: string,
  record: string,
  methods: string,
  language: Language,
) {
  return `<rc-record-entry data-language="${language}" data-title="${escapeCheck(title)}"><button type="button" class="ec-tech" aria-haspopup="dialog" aria-expanded="false">${layersIcon}${language === 'zh' ? '系统如何判断' : 'How this was assessed'}</button><template data-record>${record}</template><template data-methods>${methods}</template></rc-record-entry>`;
}
export function methodsHtml(language: Language, task = 'relation') {
  const t = (zh: string, en: string) => (language === 'zh' ? zh : en);
  const title =
    task === 'behavior'
      ? t('从动作识别阶段，与参考做法对照', 'Recognise phases and compare reference approaches')
      : task === 'intent'
        ? t('识别提问意图，给出可选入口', 'Recognise question intent and offer an optional action')
        : t(
            '先识别关系，再决定能否下结论',
            'Recognise the relationship, then decide whether to conclude',
          );
  const explanation =
    task === 'behavior'
      ? t(
          'HMM 对有序动作划分阶段；DTW 寻找接近的参考。规则回退按动作类型整理，不代表运行了模型。',
          'HMM segments ordered actions; DTW finds close references. A rule fallback groups actions without running those models.',
        )
      : task === 'intent'
        ? t(
            '字符 TF-IDF 与逻辑回归识别问题类别。规则回退使用关键词；本次实际方法请看本次记录。',
            'Character TF-IDF and logistic regression classify questions. A rule fallback uses keywords; see This record for the actual method.',
          )
        : t(
            'XLM-R 读取原句与候选资料的关系；堆叠集成整合模型信号；数字规则核对数量和限制；融合与代价决定是否暂缓。这里只解释方法，本次执行以记录为准。',
            'XLM-R reads claim–passage relationships; stacking combines model signals; rules check numbers and limits. Fusion and cost-based decisions determine whether to defer. This describes the methods; actual execution is shown in This record.',
          );
  const rows = task === 'behavior' ? [
    [t('无监督学习', 'Unsupervised learning'), t('离散观测 HMM 从动作序列拟合隐状态，再解码工作阶段；阶段名称由训练序列的规则阶段对应命名。', 'A categorical HMM fits latent states from action sequences and decodes work phases; states are named from their correspondence with rule phases in training sequences.')],
    [t('机器学习 · 序列距离', 'Machine learning · sequence distance'), t('DTW 计算动作序列距离，用最近参考做法作对照；距离不是概率。记录带对齐路径时，「本次记录」逐步画出本局与这条参考的对应。', 'DTW measures action-sequence distance to select a nearest reference approach; distance is not probability. When the record includes the alignment path, This record shows the step-by-step match with that reference.')],
  ] : task === 'intent' ? [
    [t('监督学习', 'Supervised learning'), t('从带意图标签的问题学习分类，识别本次提问的类别。', 'Learn from intent-labelled questions to classify the current question.')],
    [t('经典机器学习', 'Classical machine learning'), t('字符 TF-IDF 表示问题，逻辑回归输出意图分数；前端只按展示门槛提供可选入口。', 'Character TF-IDF represents the question; logistic regression outputs intent scores. The interface uses a display threshold to offer an optional entry point.')],
  ] : [
    [t('监督学习', 'Supervised learning'), t('从已标注的原句与依据关系学习支持、矛盾和依据不足三类。', 'Learn supported, contradicted and insufficient relationships from labelled claim–evidence pairs.')],
    [t('深度学习', 'Deep learning'), t('XLM-R 交叉编码器读取原句与候选原文，输出关系分布。', 'The XLM-R cross-encoder reads the claim and candidate passage and outputs a relation distribution.')],
    [t('集成与混合', 'Ensemble and hybrid methods'), t('将 TF-IDF＋逻辑回归与 XLM-R 堆叠，再与数字规则晚期融合；代价决策决定判定或暂缓。', 'Stack TF-IDF + logistic regression with XLM-R, then apply late fusion with numeric rules; cost-based decisions determine whether to conclude or defer.')],
  ];
  const table = `<table class="ri-method-table"><thead><tr><th>${t('类别', 'Category')}</th><th>${t('本方法承担的工作', 'Work performed by this method')}</th></tr></thead><tbody>${rows.map(([category, work]) => `<tr><th scope="row">${category}</th><td>${work}</td></tr>`).join('')}</tbody></table>`;
  return `<div class="ri-methods"><h3>${title}</h3><p>${explanation}</p>${table}<aside><h4>${t('方法效果，请看对应的实验结果', 'For method performance, read the relevant evaluation')}</h4><p>${t('实验结果按语言和数据划分阅读。在线方法与离线候选分开；离线指标不是本次判断的可信程度。', 'Read results by language and data split. Online methods and offline candidates are separate; offline metrics are not confidence in this decision.')}</p><a href="#/lab/${task === 'behavior' ? 'c5' : task === 'intent' ? 'c11' : 'c1'}">${t('查看系统剖面的对应实验', 'View the relevant evaluation in the recognition lab')} →</a><p><a href="#/lab">${t('查看项目整体的课程技术覆盖', 'View course-wide technology coverage')} →</a></p><button type="button" class="ec-tech" data-action="about" data-ri-about>${t('查看模型身份与运行模式', 'View model identity and runtime mode')} →</button></aside></div>`;
}
if (typeof customElements !== 'undefined' && !customElements.get('rc-record-entry'))
  customElements.define(
    'rc-record-entry',
    class extends HTMLElement {
      connectedCallback() {
        queueMicrotask(() => {
          const b = this.querySelector<HTMLButtonElement>('button');
          if (b)
            b.onclick = () =>
              openRecordInspector(
                b,
                this.dataset.title ?? '',
                this.querySelector<HTMLTemplateElement>('[data-record]')?.innerHTML ?? '',
                this.querySelector<HTMLTemplateElement>('[data-methods]')?.innerHTML ?? '',
                this.dataset.language === 'zh' ? 'zh' : 'en',
              );
        });
      }
    },
  );
