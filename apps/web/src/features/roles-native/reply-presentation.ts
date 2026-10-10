import { T } from '../../app/i18n';

export type RoleMode = 'local_reference' | 'model' | 'unavailable';
export type GenerationMode = 'local' | 'model';

export interface ReplyPresentationContext {
  generationMode?: GenerationMode;
  receivedVersionsOnly?: boolean;
  omissionCount?: number;
}

export interface ReplyPresentation {
  summary: string;
  status?: string;
  versionNote?: string;
  omissionNote?: string;
}

/** A complete paragraph or an explicit reading invitation; never a clipped claim. */
export function presentReply(text: string, context: ReplyPresentationContext): ReplyPresentation {
  const first = text.trim();
  const summary =
    first && first.length <= 280
      ? first
      : T(
          '回复包含完整条件与来源，请展开原文核对。',
          'Open the original reply to check its full conditions and sources.',
        );
  return {
    summary,
    versionNote: context.receivedVersionsOnly
      ? T(
          '仅依据已分享的确切版本；新版需要重新分享。',
          'Only exact shared versions are available; share a new version explicitly.',
        )
      : undefined,
    omissionNote:
      context.omissionCount && context.omissionCount > 0
        ? T(
            '部分资料因授权或上下文限额未纳入本次回复。',
            'Some sources were omitted because of access or context limits.',
          )
        : undefined,
    status:
      context.generationMode === 'local'
        ? T(
            '本地来源：规则核实 · 判断等待模型接入',
            'Sources checked by rules · judgment waiting for model connection',
          )
        : context.generationMode === 'model'
          ? T(
              '模型建议（不计分） · 保留原回复',
              'Model advice (not scored) · original reply retained',
            )
          : undefined,
  };
}

/** Panel configuration is independent of the generator recorded on each reply. */
export function currentModeNotice(mode: RoleMode): string {
  if (mode === 'local_reference')
    return T(
      '本地资料参考；需要同事判断的部分等待模型接入。',
      'Local source reference; colleague judgment is waiting for model connection.',
    );
  if (mode === 'unavailable')
    return T(
      '同事对话暂不可用，已有记录仍保留。',
      'Colleague replies are unavailable; existing records are retained.',
    );
  return T(
    '当前同事模式：模型建议（不计分）。',
    'Current colleague mode: model advice (not scored).',
  );
}
