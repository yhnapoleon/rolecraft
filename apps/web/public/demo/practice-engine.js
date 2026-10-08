/* Bounded, deterministic demo. No LLM, embeddings, training or external service. */
window.PracticeEngine = (() => {
  const topics = [
    ['leave', /年假|annual\s+leave|leave\s+(days|entitlement)|假期/i, 'DEMO_M05', 'M05§3'],
    [
      'expense',
      /报销|设备|办公补贴|expense|reimburse|equipment|claim\s+limit/i,
      'DEMO_M05',
      'M05§1',
    ],
    ['password', /密码|password/i, 'DEMO_M06', 'M06§1'],
    ['vpn', /\bvpn\b|远程连接/i, 'DEMO_M06', 'M06§2'],
    [
      'laptop',
      /电脑更换|换电脑|笔记本更换|laptop.*(replace|cycle)|replace.*laptop/i,
      'DEMO_M06',
      'M06§3',
    ],
    ['salary', /薪资|工资|salary|pay\s+band/i, null, null],
    ['refund', /退款|refund/i, null, null],
  ];
  function classify(text) {
    const hits = topics.filter((t) => t[1].test(text));
    if (hits.length !== 1)
      return {
        covered: false,
        reason: hits.length
          ? '这条问题涉及多个主题，请拆成独立测试，原文已保留。'
          : '这条问法尚未覆盖，模拟器无法可靠运行。可以保留为待真实服务验证的测试。',
      };
    const [topic, , source, para] = hits[0];
    // Only the small policy intents actually represented in the material are simulated.
    const detail =
      /离职|产假|病假|结转|累积|实习|part.?time|carry.?over|maternity|sick leave|resign|美元|人民币|usd|rmb|cny|去年|last year/i.test(
        text,
      );
    if (detail)
      return {
        covered: false,
        reason: '问题中的条件未在这份模拟政策中建模，不能给出可靠判断。测试已保留。',
      };
    return {
      covered: true,
      topic,
      source,
      para,
      kind: !source ? 'oos' : topic === 'expense' ? 'changed' : 'stable',
    };
  }
  function run(test, cfg, world, D) {
    const match = classify(test.text);
    const r = {
      ...match,
      passages: [],
      flags: [],
      answerKind: 'uncovered',
      answer: '',
      indexSnapshot: world.indexSnapshot,
      sourceNow: match.source === 'DEMO_M05' ? world.m05 : match.source ? 'v1' : null,
    };
    if (!match.covered) {
      r.answer = match.reason;
      return r;
    }
    const sc = D.SCOPES.find((s) => s.id === cfg.scope);
    const allowed = sc.docs.includes(match.source) || (sc.stableParas || []).includes(match.para);
    r.scope = allowed ? 'in' : 'out';
    if (!allowed) {
      r.answerKind = cfg.fallback === 'guess' ? 'guess' : cfg.fallback;
      r.answer =
        cfg.fallback === 'handoff'
          ? 'Your question is directed to the HR shared mailbox for review. Expected response: one working day. (Simulation only; no message sent.)'
          : cfg.fallback === 'refuse'
            ? 'This question is outside the pilot’s approved knowledge. The assistant cannot answer it.'
            : 'This request should be fine under the usual company policy. Please check with your manager if needed.';
    } else {
      const version = match.source === 'DEMO_M05' ? world.indexM05 : 'v1';
      const p = D.MATERIALS.find((m) => m.id === match.source)
        .versions.find((v) => v.v === version)
        .paras.find((p) => p.id === match.para);
      r.passages = [{ pid: p.id, version, text: p.text }];
      r.answerKind = 'answer';
      r.answer = p.text;
      if (match.topic === 'expense') {
        const amounts = [
          ...test.text.matchAll(
            /(?:SGD\s*|\$\s*)(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:元|SGD|dollars?)/gi,
          ),
        ].map((m) => Number(m[1] || m[2]));
        if (amounts.length > 1) {
          r.covered = false;
          r.answerKind = 'uncovered';
          r.answer = '多个金额之间的关系未建模，无法可靠模拟。请把条件拆成独立测试。';
          r.passages = [];
          return r;
        }
        if (amounts.length) {
          const n = amounts[0],
            cap = version === 'v1' ? 300 : 500;
          r.answer =
            n > cap
              ? `SGD ${n} exceeds the annual equipment claim limit of SGD ${cap}.`
              : `SGD ${n} is within the annual SGD ${cap} limit, provided the equipment is approved, receipts are available and the remaining annual allowance is sufficient.${version === 'v2' && n > 300 ? ' Finance sign-off is also required.' : ''}`;
        }
      }
      r.stale = match.topic === 'expense' && r.sourceNow !== version;
    }
    if (cfg.updateNotice)
      r.notice = `Index snapshot: ${world.indexSnapshot}. Later document changes may not be reflected.`;
    return r;
  }
  function colleague(cid, text, thread, world, variant, D) {
    const c = D.COLLEAGUES.find((c) => c.id === cid);
    const previous = [...thread].reverse().find((m) => m.type === 'a' && m.topic);
    let topic = null;
    if (/帮我写|替我写|直接.*方案|write.*plan|give.*answer/i.test(text))
      return {
        text: '这份决定需要由你来做。我可以说明我掌握的事实；请问一个你需要确认的问题。',
        sources: [],
        topic: 'boundary',
      };
    const tests = [
      [
        'notice',
        /只.*(提醒|时间)|显示.*(时间|日期)|提示.*(可靠|错误|修复)|notice|timestamp|warning/i,
      ],
      ['realtime', /实时|real.?time/i],
      [
        'raise',
        /扩容|增加.*容量|容量.*(?:增加|提高|调大|加到)|批准.*(50|80)|raise|bigger instance|increase.*capacity/i,
      ],
      [
        'index',
        /索引|同步|今晚|多久.*(生效|更新)|今天.*政策|index|sync|rebuild|policy.*(today|change)|更新.*(后|多久)/i,
      ],
      ['capacity', /容量|并发|多少人|支持.*人|capacity|concurrent|how many users/i],
      [
        'effort',
        /工时|人天|开发|工作量|effort|developer|engineering.*(time|days)|配置.*(小时|多久)/i,
      ],
      ['fallback', /兜底|转介|人工|答不准|不确定|handoff|hand.off|mailbox|fallback/i],
      ['changing', /报销|设备|expense|equipment|政策.*(改|新)|最近.*政策/i],
      ['stable', /稳定|年假|stable|leave/i],
      ['who', /哪些人|谁.*用|第一批|人群|给谁|users|audience|who|first group/i],
      ['deadline', /期限|一周|延期|deadline|week|delay|Wednesday/i],
      ['goal', /目标|解决.*问题|达成|成功|优先|goal|success|achieve|priority/i],
    ];
    const hits = tests.filter(([, rx]) => rx.test(text));
    if (hits.length) topic = hits[0][0];
    else if (
      previous &&
      /^(那具体呢|能说具体点吗|可以再解释一下吗|tell me more|can you elaborate)[？?。.!\s]*$/i.test(
        text,
      )
    )
      topic = previous.topic;
    const maps = {
      DEMO_C_MGR: { goal: 'goal', who: 'who', deadline: 'deadline', capacity: 'capacity' },
      DEMO_C_TECH: {
        capacity: 'capacity',
        index: 'index',
        realtime: 'realtime',
        effort: 'effort',
        raise: 'raise',
      },
      DEMO_C_BIZ: {
        stable: 'stable',
        changing: 'changing',
        who: 'users',
        fallback: 'fallback',
        capacity: 'capacity',
      },
    };
    if (topic === 'notice' && cid === 'DEMO_C_TECH')
      return {
        topic,
        text: 'The date notice displays which index snapshot was used. It does not rebuild the index or change the retrieved passage. You can test the same question with it on and off.',
        sources: ['M02§4', 'M03§2'],
      };
    if (topic === 'changing' && cid === 'DEMO_C_BIZ' && world.m05 === 'v2')
      return {
        topic,
        text: 'I have published M05 v2. The equipment cap is now SGD 500 per year; claims above SGD 300 also need Finance sign-off. Check the current chapter for the exact conditions.',
        sources: ['M05§1', 'M05§2'],
        version: 'v2',
      };
    const key = maps[cid]?.[topic];
    const q = key && c.questions.find((q) => q.id.endsWith('_' + key));
    if (q)
      return {
        topic,
        text:
          q.answer +
          (variant === 'DEMO_V2' && topic === 'who'
            ? ' Sales has requested 35 additional users. This request does not approve extra capacity.'
            : ''),
        sources: q.cite ? [q.cite] : [],
        fact: q.fact,
        refer: q.refer,
        origin: q.id,
      };
    if (topic) {
      const owner = ['index', 'capacity', 'realtime', 'effort', 'raise', 'notice'].includes(topic)
        ? 'DEMO_C_TECH'
        : ['changing', 'stable', 'fallback'].includes(topic)
          ? 'DEMO_C_BIZ'
          : 'DEMO_C_MGR';
      if (owner !== cid)
        return {
          topic,
          text:
            '这不在我的负责范围内。请向 ' +
            D.COLLEAGUES.find((x) => x.id === owner).name +
            ' 确认；我不能替他批准或作答。',
          sources: [],
          refer: owner,
        };
    }
    return {
      topic: null,
      text: '这条问题超出了当前模拟回答的覆盖范围，我不能可靠作答。你的问题已保留；可以换一个更具体的问法，或在方案中记录待确认事项。',
      sources: [],
      uncovered: true,
    };
  }
  return { classify, run, colleague };
})();
