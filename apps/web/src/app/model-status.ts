/** One model status for the whole workbench. The toolbar carries a short label whose popover says
 * which parts wait for a model and what stands in for them now; each item that waits shows only a
 * small grey mark with a readable name, and its own details say the rest. The state comes from the
 * server's semantic status of the practice (`workbench.read`), never from a guess. */
import { locale, type Locale } from './i18n';
import './model-status.css';

export type SemanticState = 'model' | 'waiting_model' | 'unavailable';
export type Semantic = Readonly<Record<'roles' | 'feedback' | 'assistant', SemanticState>>;
export type ModelPartKey = keyof Semantic;
export type ModelStatusKind = 'model' | 'local' | 'partial';

const say = (language: Locale, zh: string, en: string) => (language === 'en' ? en : zh);

const esc = (value: unknown) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );

/** The readable name of the grey mark: what a screen reader says and the hover shows. */
export const modelWaitName = (language: Locale = locale()) =>
  say(language, '等待模型接入', 'Awaiting model connection');

/** The grey mark as HTML. `detail` is one sentence for the hover; the name is always read. */
export function modelWaitHtml(detail = '', language: Locale = locale()): string {
  const name = modelWaitName(language);
  const title = detail ? `${name} · ${detail}` : name;
  return `<span class="model-wait" data-model-wait title="${esc(title)}"><span class="model-wait__name">${esc(name)}</span></span>`;
}

/** The same mark as a DOM node, for the native feature modules. */
export function modelWaitNode(doc: Document, detail = '', language: Locale = locale()) {
  const name = modelWaitName(language);
  const mark = doc.createElement('span');
  mark.className = 'model-wait';
  mark.dataset.modelWait = '';
  mark.title = detail ? `${name} · ${detail}` : name;
  const label = doc.createElement('span');
  label.className = 'model-wait__name';
  label.textContent = name;
  mark.append(label);
  return mark;
}

const PARTS: Record<
  ModelPartKey,
  { name: [string, string]; now: [string, string]; model: [string, string]; off: [string, string] }
> = {
  roles: {
    name: ['同事回复', 'Colleague replies'],
    now: ['引用本地资料，来源由规则核实', 'Quote local sources, checked by rules'],
    model: ['模型给出建议，不计分', 'A model advises; not scored'],
    off: ['暂不可用，已有记录保留', 'Unavailable; earlier replies are kept'],
  },
  assistant: {
    name: ['知识助手', 'Knowledge assistant'],
    now: ['给出检索到的原文片段', 'Returns the retrieved source passages'],
    model: ['可以选模型生成回答', 'Model-written answers can be chosen'],
    off: ['只能给原文片段', 'Source passages only'],
  },
  feedback: {
    name: ['反馈', 'Feedback'],
    now: ['只判规则能核实的项', 'Judges only what rules can check'],
    model: ['模型参与语义评审', 'A model takes part in the semantic review'],
    off: ['只判规则能核实的项', 'Judges only what rules can check'],
  },
};
const ORDER: ModelPartKey[] = ['roles', 'assistant', 'feedback'];

export interface ModelPart {
  key: ModelPartKey;
  state: SemanticState;
  name: string;
  /** What this part does now: the stand-in while it waits, or what the model does. */
  now: string;
}
export interface ModelStatus {
  kind: ModelStatusKind;
  /** The short toolbar label, e.g. "模型：本地模式". */
  label: string;
  /** The label without its "Model:" prefix, for narrow toolbars. */
  short: string;
  parts: ModelPart[];
  waiting: ModelPart[];
}

/** The status of one practice; null when the server has not said (legacy or unread practice). */
export function modelStatus(
  semantic: Semantic | null | undefined,
  language: Locale = locale(),
): ModelStatus | null {
  if (!semantic || !ORDER.every((key) => typeof semantic[key] === 'string')) return null;
  const parts = ORDER.map((key) => {
    const state = semantic[key];
    const copy = PARTS[key];
    const now = state === 'model' ? copy.model : state === 'unavailable' ? copy.off : copy.now;
    return { key, state, name: say(language, ...copy.name), now: say(language, ...now) };
  });
  const connected = parts.filter((part) => part.state === 'model').length;
  const kind: ModelStatusKind =
    connected === parts.length ? 'model' : connected === 0 ? 'local' : 'partial';
  const short = {
    model: say(language, '已接入', 'connected'),
    local: say(language, '本地模式', 'local mode'),
    partial: say(language, '部分接入', 'partly connected'),
  }[kind];
  return {
    kind,
    label: say(language, `模型：${short}`, `Model: ${short}`),
    short,
    parts,
    waiting: parts.filter((part) => part.state !== 'model'),
  };
}

/** The toolbar chip and its popover. `open` renders the popover under the chip. */
export function modelChipHtml(status: ModelStatus, open: boolean, language: Locale = locale()) {
  const mark =
    status.kind === 'model'
      ? '<span class="model-chip__on" aria-hidden="true"></span>'
      : '<span class="model-wait" aria-hidden="true"></span>';
  const button = `<button type="button" class="btn quiet model-chip" data-action="menu" data-menu="model" data-model-status="${status.kind}" aria-haspopup="dialog" aria-expanded="${open}" aria-label="${esc(status.label)}" title="${esc(status.label)}">${mark}<span class="model-chip__label"><span class="model-chip__prefix">${esc(say(language, '模型：', 'Model: '))}</span>${esc(status.short)}</span></button>`;
  return `<div class="menu-wrap model-wrap">${button}${open ? modelPopoverHtml(status, language) : ''}</div>`;
}

export function modelPopoverHtml(status: ModelStatus, language: Locale = locale()) {
  const lead =
    status.kind === 'model'
      ? say(language, '三部分都已接入模型。', 'All three parts use a model.')
      : say(
          language,
          '带灰圈的部分等模型接入，现在先这样做：',
          'Parts with a grey ring wait for a model. For now:',
        );
  return `<div class="popover model-pop" role="dialog" aria-label="${esc(status.label)}"><p class="model-pop__lead">${esc(lead)}</p>${modelPartsHtml(status, language)}</div>`;
}

/** One row per part: a green dot when a model does it, the grey ring and its stand-in when not. */
export function modelPartsHtml(status: ModelStatus, language: Locale = locale()) {
  const row = (part: ModelPart) =>
    `<li data-model-part="${part.key}" data-state="${part.state}">${part.state === 'model' ? '<span class="model-chip__on" aria-hidden="true"></span>' : modelWaitHtml('', language)}<span class="grow"><b>${esc(part.name)}</b><span class="model-pop__now">${esc(part.now)}</span></span></li>`;
  return `<ul class="model-pop__parts">${status.parts.map(row).join('')}</ul>`;
}
