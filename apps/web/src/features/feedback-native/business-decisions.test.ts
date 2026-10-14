import { describe, expect, it } from 'vitest';
import { asFake, fakeDocument } from '../results-native/fake-dom';
import { decisionLines, decisionRecords, decisionsAt, renderDecisions } from './business-decisions';
import type { Report } from './index';

const at = (storage: number) => ({
  business_seq: storage,
  workspace_revision: storage,
  storage_revision: storage,
});
const request = (id: string, version: number, requested: Record<string, number>) => ({
  ref: { session_id: 's', kind: 'business_request', object_id: id, version },
  content: { id, version, requested, status: version === 1 ? 'pending' : 'approved' },
});
const decision = (
  id: string,
  requestId: string,
  status: string,
  storage: number,
  terms: Record<string, Record<string, number>> = {},
) => ({
  ref: { session_id: 's', kind: 'business_decision', object_id: id, version: 1 },
  content: {
    id,
    request: { session_id: 's', kind: 'business_request', object_id: requestId, version: 1 },
    status,
    granted: terms.granted ?? {},
    countered: terms.countered ?? {},
    as_of: at(storage),
  },
});
const timeline = [
  request('r1', 1, { dev_days: 6 }),
  decision('d1', 'r1', 'approved', 4, { granted: { dev_days: 6 } }),
  request('r1', 2, { dev_days: 6 }),
  request('r2', 1, { deadline_day: 7, dev_days: 7 }),
  decision('d2', 'r2', 'rejected', 8),
  request('r3', 1, { capacity: 60 }),
  decision('d3', 'r3', 'countered', 9, { countered: { capacity: 45 } }),
  decision('d4', 'r3', 'accepted', 12, { granted: { capacity: 45 } }),
  { ref: { session_id: 's', kind: 'config', object_id: 'c', version: 1 }, content: {} },
];
const report = (subject: string, storage: number, response: string): Report => ({
  id: 'f',
  version: 1,
  subject: { session_id: 's', kind: subject, object_id: 'x', version: 1 },
  items: [],
  business_response: response,
  next_options: [],
  as_of: at(storage),
});
const STORED =
  '已记录的业务决定（规则核实）：申请：开发人日: 6; 已批准; 开发人日: 6\n申请：截止日: 7, 开发人日: 7; 未批准';

describe('recorded business decisions', () => {
  it('takes the latest decision of each request recorded before the feedback point', () => {
    const records = decisionRecords(timeline);
    expect(decisionsAt(records, at(10)).map((row) => [row.request, row.status])).toEqual([
      ['r1', 'approved'],
      ['r2', 'rejected'],
      ['r3', 'countered'],
    ]);
    expect(decisionsAt(records, at(13)).map((row) => row.status)).toEqual([
      'approved',
      'rejected',
      'accepted',
    ]);
    expect(decisionsAt(records, at(4))).toEqual([]);
  });

  it('writes each decision as one readable line', () => {
    const rows = decisionsAt(decisionRecords(timeline), at(10));
    expect(decisionLines(rows, 'zh')).toEqual([
      '申请 开发人日 6 → 已批准：开发人日 6',
      '申请 截止日 7、开发人日 7 → 未批准',
      '申请 容量 60 → 收到还价：容量 45',
    ]);
    expect(decisionLines(rows, 'en')).toEqual([
      'Requested dev days 6 → approved: dev days 6',
      'Requested deadline day 7, dev days 7 → not approved',
      'Requested capacity 60 → countered: capacity 45',
    ]);
  });

  it('lists the decisions of a submission and keeps any other record as stored', () => {
    const doc = fakeDocument() as unknown as Document;
    const records = decisionRecords(timeline);
    const listed = asFake(renderDecisions(doc, report('submission', 10, STORED), records, 'zh'));
    expect(listed.byTag('h3').map((node) => node.textContent)).toEqual([
      '已记录的业务决定（规则核实）',
    ]);
    expect(listed.byTag('li').map((node) => node.textContent)).toEqual([
      '申请 开发人日 6 → 已批准：开发人日 6',
      '申请 截止日 7、开发人日 7 → 未批准',
      '申请 容量 60 → 收到还价：容量 45',
    ]);
    expect(listed.textContent).not.toContain(';');
    const review = asFake(
      renderDecisions(doc, report('review', 10, '未核对业务决定。'), records, 'zh'),
    );
    expect(review.textContent).toBe('未核对业务决定。');
    const none = asFake(
      renderDecisions(
        doc,
        report('submission', 3, '当前没有可核验的业务决定记录。'),
        records,
        'zh',
      ),
    );
    expect(none.textContent).toBe('当前没有可核验的业务决定记录。');
    const unread = asFake(renderDecisions(doc, report('submission', 10, STORED), undefined, 'zh'));
    expect(unread.textContent).toBe(STORED);
    expect(unread.className).toBe('rule-detail');
  });
});
