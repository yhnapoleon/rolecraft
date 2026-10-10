import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { setPreference } from '../../app/i18n';
import {
  currentModeNotice,
  presentReply,
  replyCopyTable,
  replyDisclosure,
} from './reply-presentation';

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

// 063-03 / 063-05 HELP-06: the first screen is quoted from the reply's own cited
// structure; the full reply stays unchanged behind the disclosure.
const LOCAL = {
  zh: [
    '本地资料参考；来源与权限由规则核实；需要同事判断的部分等待模型接入。',
    '我的职责：解释检索、版本与工程成本；提供可复现验证方法',
    '[经理委托：内部知识助手试点 · v1] 目前为项目预留的容量是30人，可用开发资源3人日，正式试点期限为第7天。',
    '[经理发布：资源审批规则 · v1] 发布人：经理。 …… 每项请求必须对应超过现有资源的真实配置缺口。',
    '其余可参考的资料（未展开）：[技术负责人交接：当前能力与配置项 · v1]',
  ].join('\n'),
  en: [
    'Local source reference; sources and access checked by rules; colleague judgment is waiting for model connection.',
    'My responsibilities: Explain retrieval, versions and engineering costs',
    '[Manager brief: an internal knowledge-assistant pilot · v1] The project currently has capacity for 30 people, 3 developer-days and a pilot deadline of day 7.',
    "[Manager's published resource-approval rules · v1] Published by: the manager. … Every requested resource must correspond to a real shortfall.",
    'Other sources available (not expanded): [Technical handover: capabilities and configuration · v1]',
  ].join('\n'),
};
const OLD_META = {
  zh: '回复包含完整条件与来源，请展开原文核对。',
  en: 'Open the original reply to check its full conditions and sources.',
};

describe.each(['zh', 'en'] as const)('first screen from the reply structure (%s)', (language) => {
  beforeEach(() => setPreference(language));

  it('HELP-01 quotes one rule-checked fact with its source, never the old invitation', () => {
    const shown = presentReply(LOCAL[language], { generationMode: 'local' });
    expect(shown.summary).toBe(
      language === 'zh'
        ? '目前为项目预留的容量是30人，可用开发资源3人日，正式试点期限为第7天。'
        : 'The project currently has capacity for 30 people, 3 developer-days and a pilot deadline of day 7.',
    );
    expect(shown.source).toBe(
      language === 'zh'
        ? '经理委托：内部知识助手试点 · v1'
        : 'Manager brief: an internal knowledge-assistant pilot · v1',
    );
    expect(shown.summary).not.toBe(OLD_META[language]);
    expect(shown).toMatchObject({ partial: true, derived: false, sourceCount: 3 });
    expect(shown.status).toContain(language === 'zh' ? '等待模型接入' : 'waiting for model');
    expect(replyDisclosure(shown)).toEqual({
      label: language === 'zh' ? '展开原文' : 'Show full reply',
      meta: language === 'zh' ? '引用 3 份资料' : 'Sources cited: 3',
    });
  });

  it('HELP-06 keeps a multi-line quoted fragment together with its condition', () => {
    const claim = language === 'zh' ? '容量可扩至80人。' : 'Capacity can reach 80 users.';
    const condition =
      language === 'zh'
        ? '只有明确申请获批并生效后才能扩容。'
        : 'Capacity changes only after explicit approval is committed.';
    const reply = `${LOCAL[language].split('\n').slice(0, 2).join('\n')}\n[Note · v1] ${claim}\n${condition}`;
    const shown = presentReply(reply, { generationMode: 'local' });
    expect(shown.summary).toBe(`${claim}\n${condition}`);
    expect(shown.source).toBe('Note · v1');
  });

  it('stops at the gap between two quoted fragments of one source', () => {
    const reply = `x\n[Rules · v1] ${language === 'zh' ? '第一段。 …… 第二段。' : 'First part. … Second part.'}`;
    expect(presentReply(reply, { generationMode: 'local' }).summary).toBe(
      language === 'zh' ? '第一段。' : 'First part.',
    );
  });

  it('states a recorded business decision first when the reply cites it first', () => {
    const decision =
      language === 'zh'
        ? '[业务决定 · v1] 已保存的业务决定：已批准。生效资源：容量 50。'
        : '[Business decision · v1] Committed business decision: approved. Effective resources: Capacity 50.';
    const shown = presentReply(`${LOCAL[language].split('\n')[0]}\n${decision}`, {
      generationMode: 'local',
    });
    expect(shown.summary).toContain('50');
    expect(shown.source).toBe(language === 'zh' ? '业务决定 · v1' : 'Business decision · v1');
  });

  it('describes a local reply without any quoted passage from its structure', () => {
    const reply = [
      LOCAL[language].split('\n')[0],
      language === 'zh' ? '本地资料中没有找到与这个问题直接相关的内容。' : 'No passage found.',
      `${language === 'zh' ? '其余可参考的资料（未展开）：' : 'Other sources: '}[A · v1]、[B · v2]`,
    ].join('\n');
    const shown = presentReply(reply, { generationMode: 'local' });
    expect(shown).toMatchObject({ derived: true, partial: true, sourceCount: 2 });
    expect(shown.summary).toBe(
      language === 'zh'
        ? '这次回复没有直接相关的原文摘录，列出了 2 份可参考资料。'
        : 'This reply quotes no directly related passage; sources listed for reference: 2.',
    );
  });

  it('leads a model reply with its first paragraph and summarizes an over-long one', () => {
    const question =
      language === 'zh'
        ? '你打算先用哪份记录证明容量缺口？'
        : 'Which record shows the capacity gap?';
    const shown = presentReply(`${question}\n[Brief · v1] long evidence`, {
      generationMode: 'model',
    });
    expect(shown).toMatchObject({ summary: question, partial: true, derived: false });
    const long = presentReply(`${'a'.repeat(400)}\nsee [Brief · v1] and [Rules · v2]`, {
      generationMode: 'model',
    });
    expect(long.derived).toBe(true);
    expect(long.summary).toBe(
      language === 'zh'
        ? '完整回复较长，引用 2 份资料。'
        : 'The full reply is long; sources cited: 2.',
    );
    const cited = presentReply(`${'a'.repeat(400)}\n[Brief · v1] Capacity is 30.`, {
      generationMode: 'model',
    });
    expect(cited).toMatchObject({ summary: 'Capacity is 30.', source: 'Brief · v1' });
  });
});

it('keeps identical copy keys in both languages', () => {
  expect(Object.keys(replyCopyTable.en).sort()).toEqual(Object.keys(replyCopyTable.zh).sort());
});
