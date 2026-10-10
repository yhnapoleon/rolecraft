/** Optional registered relation advice. This view never requests inference or changes scores. */
import type { ObjectRef } from '../workspace/contract-types';
import { feedbackText, type FeedbackLanguage } from './localization';

type Status = 'completed' | 'failed' | 'unavailable' | 'synthetic_mechanism_only';
type Relation = 'SUPPORTED' | 'CONTRADICTED' | 'INSUFFICIENT';
export type ModelRegistration = {
  id: string;
  model_revision: string;
  scope: 'synthetic_fixture' | 'external_candidate';
  quality_validated: false;
};
export type RegisteredAdvice = {
  criterion: 'R2.support';
  status: Status;
  registration: ModelRegistration | null;
  label: Relation | null;
  evidence_ids: string[];
  citations: ObjectRef[];
  error_code: string | null;
  mode: 'advisory';
  affects_score: false;
};
export type AdviceFallback = 'waiting' | 'pending' | 'unavailable' | 'failed';
type Row = Record<string, unknown>;
const row = (value: unknown): value is Row =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const fail = (): never => {
  throw Error('Invalid registered model advice');
};
const text = (value: unknown): string =>
  typeof value === 'string' && value.length > 0 ? value : fail();

function registration(value: unknown): ModelRegistration | null {
  if (value === null) return null;
  if (!row(value) || value.quality_validated !== false) return fail();
  const scope = value.scope;
  if (scope !== 'synthetic_fixture' && scope !== 'external_candidate') return fail();
  return {
    id: text(value.id),
    model_revision: text(value.model_revision),
    scope,
    quality_validated: false,
  };
}
function citation(value: unknown, sessionId: string): ObjectRef {
  if (
    !row(value) ||
    value.session_id !== sessionId ||
    typeof value.version !== 'number' ||
    !Number.isInteger(value.version) ||
    value.version < 1
  )
    return fail();
  const config = value.config_version;
  if (
    config !== undefined &&
    config !== null &&
    (typeof config !== 'number' || !Number.isInteger(config) || config < 0)
  )
    return fail();
  return {
    session_id: sessionId,
    kind: text(value.kind),
    object_id: text(value.object_id),
    version: value.version,
    config_version: config,
  };
}
function status(value: unknown): Status {
  if (
    value === 'completed' ||
    value === 'failed' ||
    value === 'unavailable' ||
    value === 'synthetic_mechanism_only'
  )
    return value;
  return fail();
}
function relation(value: unknown): Relation | null {
  if (
    value === null ||
    value === 'SUPPORTED' ||
    value === 'CONTRADICTED' ||
    value === 'INSUFFICIENT'
  )
    return value;
  return fail();
}

function readAdviceItem(item: unknown, sessionId: string): RegisteredAdvice {
  if (
    !row(item) ||
    item.criterion !== 'R2.support' ||
    item.mode !== 'advisory' ||
    item.affects_score !== false ||
    !Array.isArray(item.evidence_ids) ||
    !Array.isArray(item.citations)
  )
    return fail();
  const identity = registration(item.registration);
  const state = status(item.status);
  const label = relation(item.label);
  const ids = item.evidence_ids.map(text);
  const sources = item.citations.map((ref: unknown) => citation(ref, sessionId));
  const error = item.error_code ?? null;
  if (error !== null && typeof error !== 'string') return fail();
  if (new Set(ids).size !== ids.length || ids.length !== sources.length) return fail();
  if (state === 'completed') {
    if (identity?.scope !== 'external_candidate' || label === null || error !== null) return fail();
  } else if (label !== null || ids.length || sources.length) return fail();
  if (state === 'synthetic_mechanism_only' && identity?.scope !== 'synthetic_fixture')
    return fail();
  return {
    criterion: 'R2.support',
    status: state,
    registration: identity,
    label,
    evidence_ids: ids,
    citations: sources,
    error_code: error,
    mode: 'advisory',
    affects_score: false,
  };
}

function invalidAdvice(): RegisteredAdvice {
  return {
    criterion: 'R2.support',
    status: 'unavailable',
    registration: null,
    label: null,
    evidence_ids: [],
    citations: [],
    error_code: 'model_prediction_invalid',
    mode: 'advisory',
    affects_score: false,
  };
}

export function readRegisteredAdvice(
  value: unknown,
  sessionId: string,
): RegisteredAdvice[] | undefined {
  if (value === undefined || value === null) return undefined;
  if (!Array.isArray(value)) return [invalidAdvice()];
  return value.map((item: unknown) => {
    try {
      return readAdviceItem(item, sessionId);
    } catch {
      return invalidAdvice();
    }
  });
}

const failureCodes = new Set([
  'model_load_failed',
  'pretrained_encoder_dependencies_unavailable',
  'model_files_changed',
  'model_reference_invalid',
  'model_timeout',
  'model_infrastructure_failed',
  'model_prediction_invalid',
]);

export function registeredAdviceSummary(
  advice: RegisteredAdvice[] | undefined,
  language: FeedbackLanguage,
  fallback: AdviceFallback,
): string {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  if (
    advice?.some(
      (entry) => entry.status === 'failed' || failureCodes.has(entry.error_code ?? ''),
    ) ||
    (!advice?.length && fallback === 'failed')
  )
    return T('模型建议失败', 'Model advice failed');
  if (advice?.some((entry) => entry.status === 'synthetic_mechanism_only'))
    return T('机制验证', 'Mechanism validation');
  if (advice?.some((entry) => entry.status === 'completed'))
    return T('模型建议（不计分）', 'Model advice (not scored)');
  if (advice?.length || fallback === 'pending')
    return T('模型建议待核验', 'Model advice awaiting verification');
  return fallback === 'waiting'
    ? T('等待模型接入', 'Awaiting model connection')
    : T('当前模型建议不可读取', 'Model advice is unavailable');
}

function failureText(code: string | null, language: FeedbackLanguage): string {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  switch (code) {
    case 'synthetic_mechanism_only':
      return T(
        '机制验证样例，不代表模型质量。',
        'Mechanism validation sample; this does not establish model quality.',
      );
    case 'pretrained_encoder_dependencies_unavailable':
      return T('当前环境缺少编码器加载依赖。', 'Encoder loading dependencies are unavailable.');
    case 'model_files_changed':
      return T(
        '模型文件或推理环境已变化，需重新核验注册。',
        'Model files or the inference environment changed; verify the registration again.',
      );
    case 'model_reference_invalid':
      return T(
        '配置的注册引用不可读取或无效。',
        'The configured registration is unavailable or invalid.',
      );
    case 'evidence_unavailable':
      return T(
        '当前证据或权限不足，支持关系待核验。',
        'Evidence or current permissions are insufficient; support remains unverified.',
      );
    case 'model_result_unconfirmed':
      return T(
        '原调用结果尚未确认，没有自动重试。',
        'The original call is unconfirmed; it was not retried automatically.',
      );
    case 'model_timeout':
      return T(
        '模型调用超时，没有自动重试。',
        'The model call timed out and was not retried automatically.',
      );
    case 'model_infrastructure_failed':
      return T(
        '模型运行环境失败，原作品仍保留。',
        'The model runtime failed; your work is retained.',
      );
    case 'claim_not_available':
      return T(
        '尚无法取得这次评审的完整作品原文。',
        'The complete original work is unavailable for this review.',
      );
    case 'model_prediction_invalid':
      return T(
        '模型结果未通过格式、身份或证据核验。',
        'The model result did not pass format, identity or evidence checks.',
      );
    case 'model_load_failed':
      return T(
        '注册模型加载失败，未切换到其他模型。',
        'The registered model could not be loaded; no other model was substituted.',
      );
    default:
      return T(
        '模型建议尚不可用。已核实的规则结果仍保留。',
        'Model advice is unavailable. Verified rule results are retained.',
      );
  }
}

export function updateRegisteredAdvice(
  container: HTMLElement,
  advice: RegisteredAdvice[] | undefined,
  language: FeedbackLanguage,
  openReference: (ref: ObjectRef) => void,
  fallback: AdviceFallback,
): void {
  const doc = container.ownerDocument;
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  const element = <K extends keyof HTMLElementTagNameMap>(tag: K, content: string) => {
    const node = doc.createElement(tag);
    node.textContent = content;
    return node;
  };
  let details = container.querySelector<HTMLDetailsElement>('details[data-model-advice]');
  if (!details) {
    details = element('details', '');
    details.dataset.modelAdvice = 'true';
    details.append(element('summary', ''), element('div', ''));
    container.replaceChildren(details);
  }
  const summary = details.querySelector('summary');
  const body = details.querySelector('div');
  if (!summary || !body) throw Error('Invalid model advice view');
  const focused = body.contains(doc.activeElement);
  const focusKey =
    doc.activeElement instanceof HTMLElement ? doc.activeElement.dataset.modelReference : undefined;
  summary.textContent = registeredAdviceSummary(advice, language, fallback);
  const rows: HTMLElement[] = [];
  for (const entry of advice ?? []) {
    const section = element('section', '');
    if (entry.registration) {
      section.append(
        element('p', T('模型：', 'Model: ') + entry.registration.id),
        element('p', T('版本：', 'Revision: ') + entry.registration.model_revision),
      );
      section.append(
        element(
          'p',
          entry.registration.scope === 'synthetic_fixture'
            ? T(
                '机制验证样例，不代表模型质量。',
                'Mechanism validation sample; this does not establish model quality.',
              )
            : T(
                '外部候选；模型质量尚未验证。',
                'External candidate; model quality has not been validated.',
              ),
        ),
      );
    }
    if (entry.label) {
      const label =
        entry.label === 'SUPPORTED'
          ? T('支持', 'Supported')
          : entry.label === 'CONTRADICTED'
            ? T('矛盾', 'Contradicted')
            : T('证据不足', 'Insufficient evidence');
      section.append(element('p', T('关系建议：', 'Relation advice: ') + label));
    }
    for (const [index, id] of entry.evidence_ids.entries()) {
      const source = entry.citations[index];
      if (!source) throw Error('Missing model evidence reference');
      const button = element('button', T('证据 ', 'Evidence ') + id);
      button.type = 'button';
      button.className = 'btn';
      button.dataset.modelReference = JSON.stringify(source);
      button.addEventListener('click', () => openReference(source));
      section.append(button);
    }
    if (entry.error_code && entry.error_code !== 'synthetic_mechanism_only')
      section.append(element('p', failureText(entry.error_code, language)));
    rows.push(section);
  }
  if (!rows.length)
    rows.push(
      element(
        'p',
        fallback === 'waiting'
          ? T(
              '当前只展示已核事实与规则；接入模型后再提供关系建议。',
              'Only verified facts and rules are shown. Relation advice requires a connected model.',
            )
          : T(
              '当前结果或支持依据不可核验；原作品仍保留。',
              'The result or its supporting evidence is unavailable; your work is retained.',
            ),
      ),
    );
  body.replaceChildren(...rows);
  if (focused) {
    const target = [
      ...body.querySelectorAll<HTMLButtonElement>('button[data-model-reference]'),
    ].find((button) => button.dataset.modelReference === focusKey);
    (target ?? summary).focus();
  }
}
