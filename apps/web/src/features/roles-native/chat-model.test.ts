import { describe, expect, it } from 'vitest';
import {
  NAME_CLOSE,
  NAME_OPEN,
  awaitingRoles,
  dropEmphasis,
  evidenceBySource,
  isLocalReply,
  localRoleLine,
  localRows,
  noticeKind,
  previewLine,
  replyParts,
  splitCitations,
} from './chat-model';

// The local reference reply as the server writes it (runtime/roles_v2.py LocalRoleModel).
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
const NO_MATCH = {
  zh: [
    LOCAL.zh.split('\n')[0],
    LOCAL.zh.split('\n')[1],
    '本地资料中没有找到与这个问题直接相关的内容。',
    '其余可参考的资料（未展开）：[A · v1]、[B · v2]',
  ].join('\n'),
  en: [
    LOCAL.en.split('\n')[0],
    LOCAL.en.split('\n')[1],
    'No passage directly related to this question was found in the local sources.',
    'Other sources available (not expanded): [A · v1], [B · v2]',
  ].join('\n'),
};

describe('CHAT-02 the list shows the first sentence of the last reply', () => {
  it('takes the first sentence of a model reply, without Markdown or tags', () => {
    expect(previewLine('不能直接这样算。这个数是陈敏在《草稿 BC-01 · v1》里写的。')).toBe(
      '不能直接这样算。',
    );
    expect(
      previewLine(
        '**Main observation: No — it cannot be counted directly as labor saved.** Supporting qualifications follow [Brief · v1].',
      ),
    ).toBe('Main observation: No — it cannot be counted directly as labor saved.');
    expect(
      previewLine('- **当前委托里的预留容量是30人**，这是项目现有资源：[经理委托 · v1]。\n- 其余'),
    ).toBe('当前委托里的预留容量是30人，这是项目现有资源。');
  });

  it('names a document the first sentence needs without its tag', () => {
    expect(previewLine('From [Rules · v1]: every request needs a shortfall. More.')).toBe(
      'From Rules: every request needs a shortfall.',
    );
  });

  it('ends a first line that only introduces a list without its colon', () => {
    expect(previewLine('问题是“最多”与“现有额度”要分开看：\n\n- 当前是30人')).toBe(
      '问题是“最多”与“现有额度”要分开看',
    );
  });

  it.each(['zh', 'en'] as const)(
    'skips the local preamble and role line and quotes the first passage (%s)',
    (language) => {
      expect(previewLine(LOCAL[language])).toBe(
        language === 'zh'
          ? '目前为项目预留的容量是30人，可用开发资源3人日，正式试点期限为第7天。'
          : 'The project currently has capacity for 30 people, 3 developer-days and a pilot deadline of day 7.',
      );
    },
  );

  it.each(['zh', 'en'] as const)(
    'shows nothing for a local reply that quotes no passage (%s)',
    (language) => {
      expect(previewLine(NO_MATCH[language])).toBe('');
    },
  );

  it('keeps a closing quote with the sentence it ends', () => {
    expect(previewLine('她自己注明“十个工作日可释放429分钟。”后面还有。')).toBe(
      '她自己注明“十个工作日可释放429分钟。”',
    );
  });
});

const name = (title: string) => NAME_OPEN + title + NAME_CLOSE;

// Real sentences from the demo-pack replies (old long prompt) and the v3 short form.
describe('CHAT-01 citation tags leave the sentence', () => {
  it('drops a trailing citation and the colon that introduced it (zh)', () => {
    const shown = splitCitations('这是项目现有资源：[经理委托：内部知识助手试点 · v1]。', 'zh');
    expect(shown.text).toBe('这是项目现有资源。');
    expect(shown.cites).toEqual([
      { label: '经理委托：内部知识助手试点 · v1', title: '经理委托：内部知识助手试点', version: 1 },
    ]);
  });

  it('drops a citation that closes a sentence after a figure (zh)', () => {
    expect(splitCitations('目前预留容量是30人[经理委托 · v1]。', 'zh').text).toBe(
      '目前预留容量是30人。',
    );
  });

  it('keeps a document the sentence needs, named in book quotes (zh)', () => {
    expect(splitCitations('按[经理发布：资源审批规则 · v1]，任何调整都要先申请。', 'zh').text).toBe(
      '按《经理发布：资源审批规则》，任何调整都要先申请。',
    );
    expect(
      splitCitations('这个数是陈敏在《陈敏的收益测算草稿 BC-01 · v1》里写的。', 'zh').text,
    ).toBe('这个数是陈敏在《陈敏的收益测算草稿 BC-01》里写的。');
    expect(
      splitCitations('但 [服务台导出 SD-120：工单登记与字段口径 · v1] 写明口径。', 'zh').text,
    ).toBe('但《服务台导出 SD-120：工单登记与字段口径》写明口径。');
    expect(splitCitations('见《经理委托 · v1》和《资源审批规则 · v1》。', 'zh').text).toBe(
      '见《经理委托》和《资源审批规则》。',
    );
  });

  it('drops a parenthesis that held only citations (zh and en)', () => {
    expect(
      splitCitations('草案不等于已获批资源（《经理委托：IT 工单助手试点 · v1》）。', 'zh').text,
    ).toBe('草案不等于已获批资源。');
    const en = splitCitations(
      "not yet a verified basis ([Chen Min's benefits estimate BC-01 · v1](material:bc-01); [Service-desk export SD-120 · v1](material:sd-120-fields)).",
      'en',
    );
    expect(en.text).toBe('not yet a verified basis.');
    expect(en.cites.map((c) => c.label)).toEqual([
      "Chen Min's benefits estimate BC-01 · v1",
      'Service-desk export SD-120 · v1',
    ]);
  });

  it('drops a trailing citation after a quote or a dash (en)', () => {
    expect(
      splitCitations(
        'The brief states "capacity for 30 people" [Manager brief: an internal knowledge-assistant pilot · v1].',
        'en',
      ).text,
    ).toBe('The brief states "capacity for 30 people".');
    expect(
      splitCitations(
        "- Approval ceiling: 60 people — [Manager's published resource-approval rules · v1]",
        'en',
      ).text,
    ).toBe('- Approval ceiling: 60 people');
  });

  it('keeps a document the sentence needs as a marked name (en)', () => {
    expect(
      splitCitations(
        "From [Manager's published resource-approval rules · v1]: every request needs a real shortfall.",
        'en',
      ).text,
    ).toBe(
      `From ${name("Manager's published resource-approval rules")}: every request needs a real shortfall.`,
    );
    expect(splitCitations('See [Manager brief · v1].', 'en').text).toBe(
      `See ${name('Manager brief')}.`,
    );
  });

  it('lists each cited source once, in the order it first appears', () => {
    const shown = splitCitations('A [X · v1]. B [Y · v2]. C [X · v1].', 'en');
    expect(shown.text).toBe('A. B. C.');
    expect(shown.cites.map((c) => c.label)).toEqual(['X · v1', 'Y · v2']);
  });
});

describe('CHAT-03 a local reply reads as quoted passages with their sources', () => {
  it.each(['zh', 'en'] as const)(
    'keeps passages and listed sources, not the preamble (%s)',
    (language) => {
      const rows = localRows(LOCAL[language]);
      expect(rows.map((r) => r.kind)).toEqual(['excerpt', 'excerpt', 'others']);
      expect(rows[0]).toMatchObject({
        cite: {
          title:
            language === 'zh'
              ? '经理委托：内部知识助手试点'
              : 'Manager brief: an internal knowledge-assistant pilot',
          version: 1,
        },
      });
      expect(rows[2]).toMatchObject({
        cites: [
          {
            title:
              language === 'zh'
                ? '技术负责人交接：当前能力与配置项'
                : 'Technical handover: capabilities and configuration',
            version: 1,
          },
        ],
      });
    },
  );

  it('keeps a passage that runs over several lines together', () => {
    const rows = localRows(
      `${LOCAL.zh.split('\n')[0]}\n[第一批方案 · v1] ## 决定\n- 先给 20 人\n- 保留人工兜底`,
    );
    expect(rows).toEqual([
      {
        kind: 'excerpt',
        cite: { label: '第一批方案 · v1', title: '第一批方案', version: 1 },
        text: '## 决定\n- 先给 20 人\n- 保留人工兜底',
      },
    ]);
  });

  it.each(['zh', 'en'] as const)(
    'knows a local reply and keeps its role line apart (%s)',
    (language) => {
      expect(isLocalReply(LOCAL[language])).toBe(true);
      expect(isLocalReply('不能直接这样算。')).toBe(false);
      expect(localRoleLine(LOCAL[language])).toBe(
        language === 'zh'
          ? '我的职责：解释检索、版本与工程成本；提供可复现验证方法'
          : 'My responsibilities: Explain retrieval, versions and engineering costs',
      );
    },
  );

  it.each(['zh', 'en'] as const)('says when nothing matched (%s)', (language) => {
    expect(localRows(NO_MATCH[language]).map((r) => r.kind)).toEqual(['none', 'others']);
  });
});

describe('CHAT-04 a reply arrives as a few messages, long ones folded', () => {
  it('sends each paragraph as its own bubble', () => {
    expect(replyParts('第一段。\n\n第二段。\n- 一\n- 二\n\n第三段。')).toEqual({
      shown: ['第一段。', '第二段。\n- 一\n- 二', '第三段。'],
      folded: [],
    });
  });

  it('folds everything after two paragraphs once the reply passes 700 characters', () => {
    const long = ['A'.repeat(300), 'B'.repeat(300), 'C'.repeat(150), 'D'.repeat(10)].join('\n\n');
    expect(replyParts(long)).toEqual({
      shown: ['A'.repeat(300), 'B'.repeat(300)],
      folded: ['C'.repeat(150), 'D'.repeat(10)],
    });
  });

  it('keeps a 700-character reply whole', () => {
    const whole = ['A'.repeat(350), 'B'.repeat(348)].join('\n\n');
    expect(replyParts(whole).folded).toEqual([]);
  });
});

describe('CHAT-05 an exact quote is shown under the source it came from', () => {
  const quote = '目前为项目预留的容量是30人，可用开发资源3人日，正式试点期限为第7天。';
  it('pairs a verified quote with the source named beside it', () => {
    const reply = `经理给的预留是 **30 人**。依据是《经理委托：IT 工单助手试点 · v1》原文：“${quote}”\n\n另见 [资源审批规则 · v1]。`;
    expect(evidenceBySource(reply, [quote])).toEqual(
      new Map([['经理委托：IT 工单助手试点 · v1', quote]]),
    );
  });

  it('pairs a local passage with the tag that opens its line', () => {
    expect(evidenceBySource(LOCAL.zh, [quote]).get('经理委托：内部知识助手试点 · v1')).toBe(quote);
  });

  it('pairs nothing when the quote is not in the reply or no source is named near it', () => {
    expect(evidenceBySource('没有引用。', [quote]).size).toBe(0);
    expect(evidenceBySource(`${quote}\n\n[A · v1]`, [quote]).size).toBe(0);
  });
});

describe('CHAT-06 who is replying right now', () => {
  const pending = (requestId: string, role: string, turn: string) => ({
    requestId,
    status: 'pending',
    result: { turn: { object_id: turn }, role_id: role, status: 'queued' },
  });
  it('names a colleague whose question is still being answered', () => {
    expect(
      awaitingRoles(
        [pending('r1', 'business_lead', 't1'), pending('x', 'tech_lead', 't9')],
        ['r1'],
        new Set(),
      ),
    ).toEqual(new Set(['business_lead']));
  });

  it('reads the recovered request shape too', () => {
    const recovered = {
      requestId: 'r2',
      status: 'pending',
      result: {
        response: { result: { turn: { object_id: 't2' }, role_id: 'supervisor' } },
        jobs: [],
      },
    };
    expect(awaitingRoles([recovered], ['r2'], new Set())).toEqual(new Set(['supervisor']));
  });

  it('drops a colleague whose reply has already arrived, or whose request failed', () => {
    expect(
      awaitingRoles([pending('r1', 'business_lead', 't1')], ['r1'], new Set(['t1'])).size,
    ).toBe(0);
    expect(
      awaitingRoles(
        [{ ...pending('r1', 'business_lead', 't1'), status: 'failed' }],
        ['r1'],
        new Set(),
      ).size,
    ).toBe(0);
  });
});

describe('CHAT-07 a reply that did not come through says why in one grey line', () => {
  it('separates a reply held back by the checks from one that failed', () => {
    for (const code of [
      'role_output_blocked',
      'role_reply_stance_inconsistent',
      'role_reply_semantics_unverified',
      'role_help_unverified',
      'role_help_citation_invalid',
    ])
      expect(noticeKind('failed', code)).toBe('held');
    expect(noticeKind('failed', 'role_model_timeout')).toBe('failed');
    expect(noticeKind('failed', undefined)).toBe('failed');
  });

  it('waits while queued or running and names the other states', () => {
    expect(noticeKind('queued')).toBe('typing');
    expect(noticeKind('running')).toBe('typing');
    expect(noticeKind('needs_context')).toBe('context');
    expect(noticeKind('paused')).toBe('paused');
    expect(noticeKind('cancelled')).toBe('stopped');
    expect(noticeKind('unknown')).toBe('unknown');
  });
});

describe('CHAT-09 single-asterisk emphasis reads as plain words', () => {
  it('drops *word* marks but keeps bold, bullets and multiplication', () => {
    expect(dropEmphasis('780 is total *elapsed* time')).toBe('780 is total elapsed time');
    expect(dropEmphasis('**bold** stays')).toBe('**bold** stays');
    expect(dropEmphasis('* a bullet\n* another')).toBe('* a bullet\n* another');
    expect(dropEmphasis('55% * 780 minutes')).toBe('55% * 780 minutes');
  });
});
