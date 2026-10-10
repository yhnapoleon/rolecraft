/** Knowledge-assistant answer modes and the generator setting, from saved records only.
 * Each answer carries the mode recorded for it; the deployment state never relabels history. */
import { locale } from './i18n';
import './assistant-mode.css';

export type AnswerMode = 'extractive' | 'llm' | 'unavailable' | 'failed';
export type Generator = 'extractive' | 'llm';
export type AssistantDeployment = 'model' | 'waiting_model' | 'unavailable';

const ZH = {
  assistant_mode_waiting: '等待模型接入（当前为原文检索结果）',
  assistant_mode_extractive: '原文抽取',
  assistant_mode_extractive_hint: '规则核实：回答是检索到的原文片段，可回到出处核对。',
  assistant_mode_llm: '模型生成 · 回答待核验',
  assistant_mode_llm_hint: '模型根据检索到的片段组织了回答；引用可回跳，回答内容需要你核验。',
  assistant_model_unavailable: '未配置模型',
  assistant_model_unavailable_hint:
    '这次测试选择了模型生成，但当时部署没有接入模型，没有生成回答。',
  assistant_generation_failed: '生成失败',
  assistant_generation_failed_hint: '模型调用或结果校验没有通过，问题与配置已保留，没有自动重试。',
  assistant_mode_unknown: '模式信息暂不可用',
  assistant_mode_effective_config: '本次有效配置',
  assistant_mode_effective_config_unavailable: '本次有效配置暂不可用',
  assistant_mode_queued: '已提交，等待模型生成回答；完成后这里会自动更新。',
  assistant_mode_queued_short: '等待模型生成',
  assistant_mode_queued_failed: '这次测试没有生成结果，问题已保留，可以重新运行。',
  generator_legend: '回答方式',
  generator_extractive: '原文抽取',
  generator_extractive_note: '直接给出检索到的原文片段，可回到出处核对。',
  generator_llm: '模型生成',
  generator_llm_note: '模型根据检索到的片段组织回答；回答需要你核验。',
  generator_unavailable: '模型生成：当前部署未接入模型，暂不能选择。',
  generator_stuck:
    '当前设置是模型生成，但部署没有接入模型，测试不会生成回答。可以随时改回原文抽取。',
} as const;

type CopyKey = keyof typeof ZH;

const EN: Record<CopyKey, string> = {
  assistant_mode_waiting: 'Awaiting model connection (showing extractive result)',
  assistant_mode_extractive: 'Extractive',
  assistant_mode_extractive_hint:
    'Rule-verified: the answer is the retrieved source passage; open the source to check it.',
  assistant_mode_llm: 'Model-generated · Answer awaiting verification',
  assistant_mode_llm_hint:
    'A model wrote this answer from the retrieved passages. Citations open the sources; verify the answer yourself.',
  assistant_model_unavailable: 'Model not configured',
  assistant_model_unavailable_hint:
    'This test asked for model generation, but no model was connected, so no answer was generated.',
  assistant_generation_failed: 'Generation failed',
  assistant_generation_failed_hint:
    'The model call or its validation failed. The question and settings are saved; nothing was retried.',
  assistant_mode_unknown: 'Mode information unavailable',
  assistant_mode_effective_config: 'Effective configuration for this run',
  assistant_mode_effective_config_unavailable: 'Effective configuration unavailable',
  assistant_mode_queued:
    'Submitted. Waiting for the model to answer; this updates automatically when it is done.',
  assistant_mode_queued_short: 'Waiting for the model',
  assistant_mode_queued_failed:
    'This test did not produce a result. The question is kept; run it again when ready.',
  generator_legend: 'How it answers',
  generator_extractive: 'Extractive',
  generator_extractive_note: 'Returns the retrieved source passage, which you can open and check.',
  generator_llm: 'Model-generated',
  generator_llm_note: 'A model writes the answer from the retrieved passages; you verify it.',
  generator_unavailable:
    'Model-generated: no model is connected to this deployment, so it cannot be selected.',
  generator_stuck:
    'The setting is model generation, but no model is connected, so tests will not generate answers. You can switch back to extractive at any time.',
};

export const ASSISTANT_COPY: Readonly<Record<'zh' | 'en', Readonly<Record<CopyKey, string>>>> = {
  zh: ZH,
  en: EN,
};

export const assistantText = (key: CopyKey) => ASSISTANT_COPY[locale()][key];

const esc = (value: unknown) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );

const RECORDED: Record<AnswerMode, [CopyKey, CopyKey]> = {
  extractive: ['assistant_mode_extractive', 'assistant_mode_extractive_hint'],
  llm: ['assistant_mode_llm', 'assistant_mode_llm_hint'],
  unavailable: ['assistant_model_unavailable', 'assistant_model_unavailable_hint'],
  failed: ['assistant_generation_failed', 'assistant_generation_failed_hint'],
};

export interface ModeLabel {
  /** The saved mode, or unknown when the record carries none. */
  mode: AnswerMode | 'unknown';
  text: string;
  hint: string;
}

/** One label per answer. An extractive answer on a deployment without a model says so once. */
export function answerModeLabel(run: { mode?: string; assistant?: string | null }): ModeLabel {
  const mode = Object.hasOwn(RECORDED, run.mode ?? '') ? (run.mode as AnswerMode) : 'unknown';
  if (mode === 'unknown') return { mode, text: assistantText('assistant_mode_unknown'), hint: '' };
  const [label, hint] =
    mode === 'extractive' && run.assistant === 'waiting_model'
      ? (['assistant_mode_waiting', 'assistant_mode_extractive_hint'] as const)
      : RECORDED[mode];
  return { mode, text: assistantText(label), hint: assistantText(hint) };
}

/** Compact mode line for a saved answer; empty for records without a v2 mode. */
export function answerModeLine(run: { mode?: string; assistant?: string | null }): string {
  if (!run.assistant) return '';
  const label = answerModeLabel(run);
  return `<p class="answer-mode" data-answer-mode="${esc(label.mode)}"${label.hint ? ` title="${esc(label.hint)}"` : ''}>${esc(label.text)}</p>`;
}

/** The visible generator choice in pilot settings; always submitted with the other settings. */
export function generatorField(current: Generator, deployment: AssistantDeployment | null): string {
  const connected = deployment === 'model';
  // A saved llm choice stays selectable without a model so that saving keeps it visible.
  const stuck = current === 'llm' && !connected;
  const locked = !connected && !stuck;
  const option = (value: Generator, label: CopyKey, disabled: boolean) =>
    `<label class="choice${disabled ? ' is-disabled' : ''}"><input type="radio" name="generator" value="${value}" ${current === value ? 'checked' : ''}${disabled ? ' disabled aria-describedby="generator-unavailable"' : ''}><span>${esc(assistantText(label))}</span></label>`;
  const note = (key: CopyKey, attributes: string) =>
    `<p class="generator-note" ${attributes}>${esc(assistantText(key))}</p>`;
  return `<fieldset class="field generator-field" data-generator="${esc(current)}" data-deployment="${esc(deployment ?? 'unknown')}"><legend>${esc(assistantText('generator_legend'))}</legend><div class="choices">${option('extractive', 'generator_extractive', false)}${option('llm', 'generator_llm', locked)}</div>${note('generator_extractive_note', 'data-for="extractive"')}${note('generator_llm_note', 'data-for="llm"')}${locked ? note('generator_unavailable', 'id="generator-unavailable" data-state="unavailable"') : ''}${stuck ? note('generator_stuck', 'role="note" data-state="stuck"') : ''}</fieldset>`;
}

/** Read the submitted generator; a missing value keeps the visible saved choice. */
export function submittedGenerator(form: FormData, current: Generator): Generator {
  const value = form.get('generator');
  return value === 'llm' || value === 'extractive' ? value : current;
}
