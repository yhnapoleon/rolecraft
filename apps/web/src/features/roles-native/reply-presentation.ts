import { T } from '../../app/i18n';

export interface ReplyPresentation {
  summary: string;
  status: string;
  versionNote?: string;
}

/** A complete paragraph or an explicit reading invitation; never a clipped claim. */
export function presentReply(text: string): ReplyPresentation {
  const local = /^(本地资料参考|Local source reference)/.test(text);
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
    versionNote: /仅按已收到的版本|Only the received versions/.test(text)
      ? T(
          '仅依据已分享的确切版本；新版需要重新分享。',
          'Only exact shared versions are available; share a new version explicitly.',
        )
      : undefined,
    status: local
      ? T(
          '本地来源：规则核实 · 判断等待模型接入',
          'Sources checked by rules · judgment waiting for model connection',
        )
      : T('建议（不计分） · 保留原回复', 'Advice (not scored) · original reply retained'),
  };
}
