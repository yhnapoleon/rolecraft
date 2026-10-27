import { afterEach, expect, it } from 'vitest';
import { setPreference } from '../../app/i18n';
import type { BusinessDecision, BusinessRequest, _ApprovalTermCheck } from '../../contracts-v2';
import { asFake, fakeDocument } from '../results-native/fake-dom';
import { decisionCardModel, renderDecisionCard } from './decision-card';
import { resourceNames, type ResourceKey } from './decision-words';

afterEach(() => setPreference('zh'));

const ceiling = {
  session_id: 's',
  kind: 'material',
  object_id: 'approvals',
  version: 1,
  span_start: 89,
  span_end: 116,
  quote: '可审批上限：容量60人，开发资源6人日，期限第10天。',
  observed_at_seq: 3,
};
const shortfall = {
  ...ceiling,
  span_start: 186,
  span_end: 302,
  quote: '每项请求必须对应……整单退回。',
};
const safeguards = {
  ...ceiling,
  span_start: 304,
  span_end: 411,
  quote: '所有资源申请……实时策略需realtime_sync。',
};
const effect = {
  ...ceiling,
  span_start: 413,
  span_end: 490,
  quote: '决定记录生效后才调整资源额度……',
};
const titles = { 'approvals:1': '经理发布：资源审批规则' };

function decision(status: BusinessDecision['status'], assessment: BusinessDecision['assessment']) {
  return {
    id: 'd',
    session_id: 's',
    version: 1,
    request: { session_id: 's', kind: 'business_request', object_id: 'r', version: 1 },
    status,
    decider: 'supervisor',
    rule_revision: 'rules',
    reason_code: 'request_over_limit',
    reason: '请求超过当前可审批上限，或试图降低既有资源；请对照审批规则调整条款。',
    as_of: { business_seq: 3, workspace_revision: 1, storage_revision: 4 },
    assessment,
  } as BusinessDecision;
}
const request = (update_strategy = 'realtime') =>
  ({ basis: { config: { update_strategy } } }) as unknown as BusinessRequest;

it('names the ceiling sentence, the gap and a capped re-application for an over-ceiling request', () => {
  const model = decisionCardModel(
    decision('rejected', {
      terms: [
        {
          resource: 'dev_days',
          current: 3,
          requested: 7,
          limit: 6,
          needed: 6,
          issues: ['over_limit'],
        },
      ],
      clauses: [ceiling],
    }),
    request(),
    titles,
  );
  expect(model.clauses).toEqual([
    { ref: ceiling, title: '经理发布：资源审批规则', version: 1, quote: ceiling.quote },
  ]);
  expect(model.lines).toEqual([
    { ok: false, text: '开发人日：申请 7，超出上限 6；方案需要 6（缺口 3）' },
  ]);
  expect(model.ceiling).toEqual({ dev_days: 6 });
});

it('sends a plan that needs more than the ceiling to its settings, on every rejection', () => {
  // 164 N1: real-time sync with the default safeguards needs 7 developer-days; the ceiling is 6.
  const asked7 = decisionCardModel(
    decision('rejected', {
      terms: [
        {
          resource: 'dev_days',
          current: 3,
          requested: 7,
          limit: 6,
          needed: 7,
          issues: ['over_limit', 'need_over_limit'],
        },
      ],
      clauses: [ceiling],
    }),
    request(),
    titles,
  );
  expect(asked7.lines).toEqual([
    { ok: false, text: '开发人日：申请 7，超出上限 6；方案需要 7，超出上限 6' },
  ]);
  expect(asked7.ceiling).toBeNull();
  expect(asked7.replan).toEqual(['先把方案降到 6 人日以内再申请']);
  // Asking for the ceiling anyway is declined again, and that card points to the settings too.
  const asked6 = decisionCardModel(
    decision('rejected', {
      terms: [
        {
          resource: 'dev_days',
          current: 3,
          requested: 6,
          limit: 6,
          needed: 7,
          issues: ['insufficient', 'need_over_limit'],
        },
      ],
      clauses: [shortfall, ceiling],
    }),
    request(),
    titles,
  );
  expect(asked6.ceiling).toBeNull();
  expect(asked6.replan).toEqual(['先把方案降到 6 人日以内再申请']);
});

/** The card as drawn, with what its buttons did. */
function drawn(model: ReturnType<typeof decisionCardModel>) {
  const refilled: Readonly<Record<string, number>>[] = [];
  const card = asFake(
    renderDecisionCard(fakeDocument(), model, {
      open: () => undefined,
      refill: (terms) => refilled.push(terms),
    }),
  );
  const button = (text: string) => card.byTag('button').find((b) => b.textContent === text);
  return { card, refilled, button };
}
const overCeiling = (requested: number, issues: _ApprovalTermCheck['issues']) =>
  decision('rejected', {
    terms: [{ resource: 'dev_days', current: 3, requested, limit: 6, needed: 7, issues }],
    clauses: [ceiling],
  });

it('draws the way out of an over-ceiling plan: the settings, never a capped request', () => {
  for (const declined of [
    overCeiling(7, ['over_limit', 'need_over_limit']),
    overCeiling(6, ['insufficient', 'need_over_limit']),
  ]) {
    const { card, refilled, button } = drawn(decisionCardModel(declined, request(), titles));
    expect(button('按上限改申请')).toBeUndefined();
    expect(card.textContent).toContain('先把方案降到 6 人日以内再申请');
    const settings = button('调整设置');
    // The workbench's own "config" action opens the pilot settings, as the pre-submission
    // card's "adjust settings" does; the card adds no entry of its own.
    expect(settings?.dataset.action).toBe('config');
    settings?.click();
    expect(refilled).toEqual([]);
  }
});

it('says what to change in the plan for each term over its ceiling, in both languages', () => {
  const declined = decision('rejected', {
    terms: [
      {
        resource: 'capacity',
        current: 30,
        requested: 80,
        limit: 60,
        needed: 80,
        issues: ['over_limit', 'need_over_limit'],
      },
      {
        resource: 'deadline_day',
        current: 7,
        requested: 12,
        limit: 10,
        needed: 12,
        issues: ['over_limit', 'need_over_limit'],
      },
      {
        resource: 'dev_days',
        current: 3,
        requested: 7,
        limit: 6,
        needed: 7,
        issues: ['over_limit', 'need_over_limit'],
      },
    ],
    clauses: [ceiling],
  });
  const replan = () => decisionCardModel(declined, request(), titles).replan;
  expect(replan()).toEqual([
    '先把试点人数降到 60 人以内再申请',
    '先把计划上线日提前到第 10 天以内再申请',
    '先把方案降到 6 人日以内再申请',
  ]);
  setPreference('en');
  expect(replan()).toEqual([
    'Bring the pilot down to 60 users or fewer before requesting',
    'Move the planned launch day to day 10 or earlier before requesting',
    'Bring the plan down to 6 person-days or less before requesting',
  ]);
  expect(
    drawn(decisionCardModel(declined, request(), titles)).button('Adjust settings'),
  ).toBeDefined();
});

it('sends a plan missing a required safeguard to its settings, not to a capped request', () => {
  // Real-time sync without the human hand-off: 6 developer-days fit the ceiling, but a request
  // capped at 6 would be declined again for the missing safeguard.
  const assessment = (extra: Partial<NonNullable<BusinessDecision['assessment']>>) =>
    decision('rejected', {
      terms: [
        {
          resource: 'dev_days',
          current: 3,
          requested: 7,
          limit: 6,
          needed: 6,
          issues: ['over_limit'],
        },
      ],
      clauses: [ceiling, safeguards],
      ...extra,
    });
  const missing = decisionCardModel(
    assessment({ missing_work_items: ['human_fallback'] }),
    request(),
    titles,
  );
  expect(missing.ceiling).toBeNull();
  expect(missing.replan).toEqual(['先在设置里补上人工入口再申请']);
  const handOff = decisionCardModel(assessment({ fallback_required: true }), request(), titles);
  expect(handOff.ceiling).toBeNull();
  expect(handOff.replan).toEqual(['先在设置里把“答不了或不确定时”选成“转人工确认”再申请']);
  const { button, refilled } = drawn(missing);
  expect(button('按上限改申请')).toBeUndefined();
  expect(button('调整设置')?.dataset.action).toBe('config');
  button('调整设置')?.click();
  expect(refilled).toEqual([]);
  setPreference('en');
  expect(
    decisionCardModel(
      assessment({
        missing_work_items: ['scope_filter', 'human_fallback'],
        fallback_required: true,
      }),
      request('daily'),
      titles,
    ).replan,
  ).toEqual([
    'Add Scope filter and Human hand-off in the settings before requesting',
    'In the settings, set “When it cannot answer” to “Hand off to a person” before requesting',
  ]);
});

it('fills a term asked too low with what the plan needs, beside the capped one', () => {
  // 185 P2-1: day 8 and 7 developer-days for a plan launching on day 9 that needs 6. Keeping
  // day 8 would be declined again for the short deadline; day 9 fits the ceiling of day 10.
  const declined = decision('rejected', {
    terms: [
      {
        resource: 'deadline_day',
        current: 7,
        requested: 8,
        limit: 10,
        needed: 9,
        issues: ['insufficient'],
      },
      {
        resource: 'dev_days',
        current: 3,
        requested: 7,
        limit: 6,
        needed: 6,
        issues: ['over_limit'],
      },
    ],
    clauses: [ceiling],
  });
  const model = decisionCardModel(declined, request(), titles);
  expect(model.ceiling).toEqual({ deadline_day: 9, dev_days: 6 });
  const { refilled, button } = drawn(model);
  button('按上限改申请')?.click();
  expect(refilled).toEqual([{ deadline_day: 9, dev_days: 6 }]);
});

it('quiets the way out of an old card once a later approval followed it', () => {
  // 185 P3-2: after these rejections the plan came down to 6 and 6 developer-days were
  // approved. That approval needed a plan within the ceiling and with its safeguards, so the
  // old cards' advice has been followed: they keep their lines but offer nothing.
  const overPlan = overCeiling(7, ['over_limit', 'need_over_limit']);
  const missingHandOff = decision('rejected', {
    terms: [
      {
        resource: 'dev_days',
        current: 3,
        requested: 7,
        limit: 6,
        needed: 6,
        issues: ['over_limit'],
      },
    ],
    missing_work_items: ['human_fallback'],
    clauses: [ceiling, safeguards],
  });
  for (const declined of [overPlan, missingHandOff]) {
    const before = decisionCardModel(declined, request(), titles, { dev_days: 3 });
    expect(before.replan).not.toEqual([]);
    const after = decisionCardModel(declined, request(), titles, { dev_days: 6 });
    expect(after.lines).toEqual(before.lines);
    expect(after.replan).toEqual([]);
    expect(after.ceiling).toBeNull();
    const { button } = drawn(after);
    expect(button('调整设置')).toBeUndefined();
    expect(button('按上限改申请')).toBeUndefined();
  }
});

it('keeps the capped request when the plan itself fits under the ceiling', () => {
  const declined = decision('rejected', {
    terms: [
      {
        resource: 'dev_days',
        current: 3,
        requested: 7,
        limit: 6,
        needed: 6,
        issues: ['over_limit'],
      },
    ],
    clauses: [ceiling],
  });
  const { refilled, button } = drawn(decisionCardModel(declined, request(), titles));
  expect(button('调整设置')).toBeUndefined();
  button('按上限改申请')?.click();
  expect(refilled).toEqual([{ dev_days: 6 }]);
});

it('lists every problem of the 164 request and offers no ceiling when nothing is short', () => {
  const model = decisionCardModel(
    decision('rejected', {
      terms: [
        {
          resource: 'deadline_day',
          current: 7,
          requested: 7,
          limit: 10,
          needed: 7,
          issues: ['no_increase', 'no_shortfall'],
        },
        {
          resource: 'dev_days',
          current: 3,
          requested: 7,
          limit: 6,
          needed: 2,
          issues: ['over_limit', 'no_shortfall'],
        },
      ],
      missing_work_items: ['realtime_sync'],
      clauses: [ceiling, shortfall, safeguards],
    }),
    request(),
    titles,
  );
  expect(model.lines).toEqual([
    { ok: false, text: '截止日：申请第 7 天，和现有一样；计划第 7 天上线，现有期限已够' },
    { ok: false, text: '开发人日：申请 7，超出上限 6；方案只需 2，现有 3 已够' },
    { ok: false, text: '实时同步策略还要安排：实时同步' },
  ]);
  expect(model.clauses.map((c) => c.quote)).toEqual([
    ceiling.quote,
    shortfall.quote,
    safeguards.quote,
  ]);
  expect(model.ceiling).toBeNull();
});

it('shows approved terms as met in English without offering a re-application', () => {
  setPreference('en');
  const model = decisionCardModel(
    decision('approved', {
      terms: [{ resource: 'dev_days', current: 3, requested: 6, limit: 6, needed: 6, issues: [] }],
      clauses: [shortfall, effect],
    }),
    request(),
    { 'approvals:1': "Manager's published resource-approval rules" },
  );
  expect(model.lines).toEqual([
    { ok: true, text: 'Person-days: 3 → 6 (plan needs 6 · ceiling 6)' },
  ]);
  expect(model.clauses[0].title).toBe("Manager's published resource-approval rules");
  expect(model.ceiling).toBeNull();
});

it('leaves a counteroffer to its own acceptance and explains a lowered deadline', () => {
  const countered = decisionCardModel(
    decision('countered', {
      terms: [
        {
          resource: 'dev_days',
          current: 3,
          requested: 7,
          limit: 6,
          needed: 6,
          issues: ['over_limit'],
        },
      ],
      clauses: [ceiling],
    }),
    request(),
    titles,
  );
  expect(countered.ceiling).toBeNull();
  const lowered = decisionCardModel(
    decision('rejected', {
      terms: [
        {
          resource: 'deadline_day',
          current: 7,
          requested: 6,
          limit: 10,
          needed: 9,
          issues: ['below_current', 'insufficient'],
        },
      ],
      clauses: [shortfall],
    }),
    request('daily'),
    titles,
  );
  expect(lowered.lines).toEqual([
    { ok: false, text: '截止日：申请第 6 天，比现有第 7 天少；计划第 9 天上线，申请不够' },
  ]);
});

it('names a missing hand-off and the safeguards a daily index plan lacks', () => {
  const model = decisionCardModel(
    decision('rejected', {
      terms: [
        { resource: 'capacity', current: 30, requested: 60, limit: 60, needed: 50, issues: [] },
      ],
      missing_work_items: ['scope_filter'],
      fallback_required: true,
      clauses: [safeguards],
    }),
    request('daily'),
    titles,
  );
  expect(model.lines).toEqual([
    { ok: true, text: '名额：30 → 60（方案需要 50 · 上限 60）' },
    { ok: false, text: '每日索引策略还要安排：知识范围过滤' },
    { ok: false, text: '答不了或不确定时要转人工确认' },
  ]);
});

it('offers no ceiling re-application once the allocation in effect already reaches it', () => {
  const overCeiling = decision('rejected', {
    terms: [
      {
        resource: 'dev_days',
        current: 3,
        requested: 7,
        limit: 6,
        needed: 6,
        issues: ['over_limit'],
      },
    ],
    clauses: [ceiling],
  });
  // Six developer-days were approved after this rejection.
  expect(decisionCardModel(overCeiling, request(), titles, { dev_days: 6 }).ceiling).toBeNull();
  expect(decisionCardModel(overCeiling, request(), titles, { dev_days: 3 }).ceiling).toEqual({
    dev_days: 6,
  });
  // The allocation already stood at the ceiling when the request was decided.
  const atCeiling = decision('rejected', {
    terms: [
      {
        resource: 'dev_days',
        current: 6,
        requested: 7,
        limit: 6,
        needed: 7,
        issues: ['over_limit'],
      },
    ],
    clauses: [ceiling],
  });
  expect(decisionCardModel(atCeiling, request(), titles).ceiling).toBeNull();
});

it('keeps the recorded reason when no line on the card explains a rejection', () => {
  const reason = '引用尚未出现、不存在或不在当前权限内；请核对确切版本后重提。';
  const invalidEvidence = {
    ...decision('rejected', {
      terms: [{ resource: 'dev_days', current: 3, requested: 6, limit: 6, needed: 6, issues: [] }],
      clauses: [shortfall],
    }),
    reason_code: 'request_evidence_invalid',
    reason,
  };
  expect(decisionCardModel(invalidEvidence, request(), titles).lines).toEqual([
    { ok: true, text: '开发人日：3 → 6（方案需要 6 · 上限 6）' },
    { ok: false, text: reason },
  ]);
  const unsupported = {
    ...decision('rejected', { terms: [], clauses: [] }),
    reason_code: 'unsupported_resource_request',
    reason: '当前仅受理容量、开发人日与正式试点期限的申请。',
  };
  expect(decisionCardModel(unsupported, request(), titles).lines).toEqual([
    { ok: false, text: '当前仅受理容量、开发人日与正式试点期限的申请。' },
  ]);
  // A rejection its lines already explain does not repeat the general sentence.
  const explained = decision('rejected', {
    terms: [
      {
        resource: 'dev_days',
        current: 3,
        requested: 7,
        limit: 6,
        needed: 6,
        issues: ['over_limit'],
      },
    ],
    clauses: [ceiling],
  });
  expect(decisionCardModel(explained, request(), titles).lines).toHaveLength(1);
});

it('names each resource as the request panel and the recorded decisions do', () => {
  const terms = [
    { resource: 'capacity', current: 30, requested: 45, limit: 60, needed: 40, issues: [] },
    { resource: 'dev_days', current: 3, requested: 6, limit: 6, needed: 6, issues: [] },
    { resource: 'deadline_day', current: 7, requested: 9, limit: 10, needed: 9, issues: [] },
  ];
  const lines = () =>
    decisionCardModel(decision('approved', { terms, clauses: [effect] }), request(), titles).lines;
  expect(lines().map((line) => line.text)).toEqual([
    '名额：30 → 45（方案需要 40 · 上限 60）',
    '开发人日：3 → 6（方案需要 6 · 上限 6）',
    '截止日：第 7 天 → 第 9 天（方案需要第 9 天 · 上限第 10 天）',
  ]);
  setPreference('en');
  expect(lines().map((line) => line.text)).toEqual([
    'Seats: 30 → 45 (plan needs 40 · ceiling 60)',
    'Person-days: 3 → 6 (plan needs 6 · ceiling 6)',
    'Deadline day: day 7 → day 9 (plan needs day 9 · ceiling day 10)',
  ]);
  const names = resourceNames();
  for (const [index, term] of terms.entries())
    expect(lines()[index].text.startsWith(`${names[term.resource as ResourceKey]}: `)).toBe(true);
});
