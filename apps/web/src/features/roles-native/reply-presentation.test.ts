import { afterEach, expect, it } from 'vitest';
import { setPreference } from '../../app/i18n';
import { presentReply } from './reply-presentation';

afterEach(() => setPreference('zh'));

it.each(['zh', 'en'] as const)(
  'keeps structured state when the backend wording changes (%s)',
  (language) => {
    setPreference(language);
    const text = language === 'zh' ? '已整理本次可见材料。' : 'The available material is ready.';
    const shown = presentReply(text, {
      roleMode: 'local_reference',
      receivedVersionsOnly: true,
      omissionCount: 2,
    });
    expect(shown.summary).toBe(text);
    expect(shown.status).toBe(
      language === 'zh'
        ? '当前同事模式：本地来源／规则核实 · 判断等待模型接入'
        : 'Current colleague mode: local sources / rule checks · judgment waiting for model connection',
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
  for (const roleMode of ['local_reference', 'model', 'unavailable'] as const) {
    it.each([true, false])(
      `renders ${roleMode} with explicit version scope %s (${language})`,
      (receivedVersionsOnly) => {
        setPreference(language);
        const status = {
          local_reference:
            language === 'zh'
              ? '当前同事模式：本地来源／规则核实 · 判断等待模型接入'
              : 'Current colleague mode: local sources / rule checks · judgment waiting for model connection',
          model:
            language === 'zh'
              ? '当前同事模式：模型建议（不计分） · 保留原回复'
              : 'Current colleague mode: model advice (not scored) · original reply retained',
          unavailable:
            language === 'zh'
              ? '当前同事模式：不可用 · 保留原回复'
              : 'Current colleague mode: unavailable · original reply retained',
        };
        // Even text containing the old markers has no authority over state.
        const shown = presentReply('本地资料参考 Only the received versions', {
          roleMode,
          receivedVersionsOnly,
          omissionCount: 0,
        });
        expect(shown.status).toBe(status[roleMode]);
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
  const shown = presentReply('仅按已收到的版本引用作品。', { roleMode: 'model' });
  expect(shown.versionNote).toBeUndefined();
  expect(shown.omissionNote).toBeUndefined();
});

it.each(['zh', 'en'] as const)(
  'identifies current mode without relabelling the historical reply (%s)',
  (language) => {
    setPreference(language);
    const historical = language === 'zh' ? '此前已记录的回复。' : 'A previously recorded reply.';
    for (const roleMode of ['model', 'local_reference', 'unavailable'] as const) {
      const shown = presentReply(historical, { roleMode });
      expect(shown.summary).toBe(historical);
      expect(
        shown.status.startsWith(language === 'zh' ? '当前同事模式：' : 'Current colleague mode: '),
      ).toBe(true);
    }
  },
);
