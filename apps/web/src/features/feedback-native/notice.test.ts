import { describe, it, expect } from 'vitest';
import { feedbackNotice, type FeedbackNativeState, type Report } from './index';

const submission = {
  ref: { session_id: 's', kind: 'submission', object_id: 'sub-2', version: 1 },
  products: [],
  decision: 'no_go',
};
const earlier = { id: 'f-1', subject: { object_id: 'sub-1' } } as unknown as Report;
const latest = { id: 'f-2', subject: { object_id: 'sub-2' } } as unknown as Report;
const submitted = (extra: Partial<FeedbackNativeState> = {}): FeedbackNativeState => ({
  status: 'submitted',
  feedbackPhase: 'running',
  busy: false,
  products: [],
  reports: [earlier],
  submission,
  ...extra,
});

describe('status line after a submission', () => {
  it('says the feedback is being generated until the latest submission has it', () => {
    expect(feedbackNotice(submitted(), 'zh')).toBe('本次提交已保存，反馈正在生成…');
    expect(feedbackNotice(submitted({ awaitingFeedback: true }), 'en')).toBe(
      'Submission saved. Feedback is being generated…',
    );
    // With its feedback in, the results cover says what was delivered (195): no sentence.
    expect(feedbackNotice(submitted({ reports: [earlier, latest] }), 'zh')).toBe('');
  });
  it('does not claim generation when the feedback job failed', () => {
    expect(feedbackNotice(submitted({ failedFeedback: true }), 'zh')).toBe(
      '本次提交已保存，反馈尚未就绪。',
    );
    expect(feedbackNotice(submitted({ failedFeedback: true }), 'en')).toBe(
      'Submission saved. Feedback is not ready yet.',
    );
  });
});

describe('status line while the delivery is read again (164 N10)', () => {
  it('keeps saying the feedback is being generated while the records are read', () => {
    expect(feedbackNotice(submitted({ busy: true }), 'zh')).toBe('本次提交已保存，反馈正在生成…');
    expect(feedbackNotice(submitted({ busy: true, awaitingFeedback: true }), 'en')).toBe(
      'Submission saved. Feedback is being generated…',
    );
  });
  it('still waits for confirmation while submitting, and once feedback is there', () => {
    expect(
      feedbackNotice({ status: 'active', busy: true, products: [], reports: [] }, 'zh'),
    ).toBe('正在等待服务端确认…');
    expect(feedbackNotice(submitted({ busy: true, reports: [earlier, latest] }), 'zh')).toBe(
      '正在读取反馈记录…',
    );
  });
});

it('does not invent a generation stage while reading stored feedback', () => {
  expect(feedbackNotice(submitted({ feedbackPhase: undefined, busy: true }), 'zh')).toBe('本次提交已保存，正在读取反馈…');
  expect(feedbackNotice(submitted({ feedbackPhase: undefined }), 'en')).toBe('Submission saved. Feedback is not ready yet.');
  expect(feedbackNotice(submitted({ feedbackPhase: 'queued' }), 'en')).toBe('Submission saved. Waiting for the reviewer…');
});
