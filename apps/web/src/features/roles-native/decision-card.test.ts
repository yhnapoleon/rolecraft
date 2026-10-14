import { afterEach, expect, it } from 'vitest';
import { setPreference } from '../../app/i18n';
import type { BusinessDecision, BusinessRequest } from '../../contracts-v2';
import { decisionCardModel } from './decision-card';

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
    { ok: true, text: 'Developer-days: 3 → 6 (plan needs 6 · ceiling 6)' },
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
    { ok: false, text: '答不了时要转人工确认' },
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
