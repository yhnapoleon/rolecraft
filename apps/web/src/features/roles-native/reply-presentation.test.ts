import { afterEach, expect, it } from 'vitest';
import { setPreference } from '../../app/i18n';
import { currentModeNotice, presentReply } from './reply-presentation';

afterEach(() => setPreference('zh'));

it.each(['zh', 'en'] as const)(
  'keeps structured state when the backend wording changes (%s)',
  (language) => {
    setPreference(language);
    const text = language === 'zh' ? '已整理本次可见材料。' : 'The available material is ready.';
    const shown = presentReply(text, {
      generationMode: 'local',
      receivedVersionsOnly: true,
      omissionCount: 2,
    });
    expect(shown.summary).toBe(text);
    expect(shown.status).toBe(
      language === 'zh'
        ? '本地来源：规则核实 · 判断等待模型接入'
        : 'Sources checked by rules · judgment waiting for model connection',
    );
    expect(shown.versionNote).toBe(
      language === 'zh'
        ? '仅依据已分享的确切版本；新版需要重新分享。'
        : 'Only exact shared versions are available; share a new version explicitly.',
    );
    expect(shown.omissionNote).toBe(
      language === 'zh'
        ? '部分资料因授权或上下文限额未纳入本次回复。'
        : 'Some sources were omitted because of access or context limits.',
    );
  },
);

for (const language of ['zh', 'en'] as const) {
  for (const generationMode of ['local', 'model', undefined] as const) {
    it.each([true, false])(
      `renders ${generationMode ?? 'unknown'} with explicit version scope %s (${language})`,
      (receivedVersionsOnly) => {
        setPreference(language);
        const status = {
          local:
            language === 'zh'
              ? '本地来源：规则核实 · 判断等待模型接入'
              : 'Sources checked by rules · judgment waiting for model connection',
          model:
            language === 'zh'
              ? '模型建议（不计分） · 保留原回复'
              : 'Model advice (not scored) · original reply retained',
          unknown: undefined,
        };
        // Text containing old markers still has no authority over either state field.
        const shown = presentReply('本地资料参考 Only the received versions', {
          generationMode,
          receivedVersionsOnly,
          omissionCount: 0,
        });
        expect(shown.status).toBe(status[generationMode ?? 'unknown']);
        expect(shown.versionNote).toBe(
          receivedVersionsOnly
            ? language === 'zh'
              ? '仅依据已分享的确切版本；新版需要重新分享。'
              : 'Only exact shared versions are available; share a new version explicitly.'
            : undefined,
        );
        expect(shown.omissionNote).toBeUndefined();
      },
    );
  }
}

it('does not infer missing historical scope from legacy wording', () => {
  const shown = presentReply('仅按已收到的版本引用作品。', { generationMode: 'model' });
  expect(shown.versionNote).toBeUndefined();
  expect(shown.omissionNote).toBeUndefined();
});

it.each(['zh', 'en'] as const)(
  'omits historical reply mode when no generation metadata was recorded (%s)',
  (language) => {
    setPreference(language);
    const historical =
      language === 'zh'
        ? '本地资料参考：此前已记录的回复。'
        : 'Local source reference: a previously recorded reply.';
    const shown = presentReply(historical, {});
    expect(shown.summary).toBe(historical);
    expect(shown.status).toBeUndefined();
  },
);

it.each(['zh', 'en'] as const)(
  'keeps the panel model notice visible for legacy replies (%s)',
  (language) => {
    setPreference(language);
    expect(presentReply('historical reply', {}).status).toBeUndefined();
    expect(currentModeNotice('model')).toBe(
      language === 'zh'
        ? '当前同事模式：模型建议（不计分）。'
        : 'Current colleague mode: model advice (not scored).',
    );
  },
);
