import { describe, expect, it } from 'vitest';
import { returnPlacement } from './agent-return';

const tasks = [{ id: 'needs' }, { id: 'policy' }, { id: 'decision' }];
// Copy and download hand a package over; "view" alone records nothing.
const handedOver = [
  { requestId: 'request-policy', taskId: 'policy' },
  { requestId: 'request-whole-job', taskId: null },
];

describe('where a returned work is filed', () => {
  it('files a return under the task its package was handed over for, wherever it is opened', () => {
    const data = { requestId: 'request-policy', returnId: 'return-1' };
    expect(returnPlacement(data, handedOver, tasks, null)).toEqual({
      status: 'package',
      taskId: 'policy',
    });
    expect(returnPlacement(data, handedOver, tasks, 'needs')).toEqual({
      status: 'package',
      taskId: 'policy',
    });
  });

  it('lets the person choose for a whole-job package or a return without one', () => {
    expect(
      returnPlacement(
        { requestId: 'request-whole-job', returnId: 'return-2' },
        handedOver,
        tasks,
        'decision',
      ),
    ).toEqual({ status: 'choose', taskId: 'decision' });
    // Opened from the board there is no task to assume: never the first task.
    expect(returnPlacement({}, handedOver, tasks, null)).toEqual({
      status: 'choose',
      taskId: null,
    });
  });

  it('refuses before import a return naming a package that was never handed over', () => {
    expect(
      returnPlacement(
        { requestId: 'request-viewed-only', returnId: 'return-3' },
        handedOver,
        tasks,
        'needs',
      ),
    ).toEqual({ status: 'unmatched' });
    // Without a return id the text comes in as an unlinked return, as before.
    expect(
      returnPlacement({ requestId: 'request-viewed-only' }, handedOver, tasks, 'needs'),
    ).toEqual({ status: 'choose', taskId: 'needs' });
  });

  it('asks again when the package task no longer exists', () => {
    expect(
      returnPlacement(
        { requestId: 'request-policy', returnId: 'return-4' },
        handedOver,
        [{ id: 'needs' }],
        null,
      ),
    ).toEqual({ status: 'choose', taskId: null });
  });
});
