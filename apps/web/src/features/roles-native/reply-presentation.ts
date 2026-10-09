import { T } from '../../app/i18n';

export type RoleMode = 'local_reference' | 'model' | 'unavailable';

export interface ReplyPresentationContext {
  roleMode: RoleMode;
  receivedVersionsOnly?: boolean;
  omissionCount?: number;
}

export interface ReplyPresentation {
  summary: string;
  status: string;
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
      context.roleMode === 'local_reference'
        ? T(
            '当前同事模式：本地来源／规则核实 · 判断等待模型接入',
            'Current colleague mode: local sources / rule checks · judgment waiting for model connection',
          )
        : context.roleMode === 'model'
          ? T(
              '当前同事模式：模型建议（不计分） · 保留原回复',
              'Current colleague mode: model advice (not scored) · original reply retained',
            )
          : T(
              '当前同事模式：不可用 · 保留原回复',
              'Current colleague mode: unavailable · original reply retained',
            ),
  };
}
