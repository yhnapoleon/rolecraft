import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { holdToSign } from './hold';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

function setup() {
  const calls: string[] = [];
  const hold = holdToSign({
    onStart: (kind, ms) => calls.push(`start:${kind}:${ms}`),
    onCancel: (hint) => calls.push(`cancel:${hint}`),
    onComplete: () => calls.push('complete'),
  });
  return { hold, calls };
}

describe('hold to sign', () => {
  it('ED-80 a pointer held for a full second signs once', () => {
    const { hold, calls } = setup();
    hold.press('pointer');
    expect(hold.state()).toBe('holding');
    vi.advanceTimersByTime(999);
    expect(calls).toEqual(['start:pointer:1000']);
    vi.advanceTimersByTime(1);
    expect(calls).toEqual(['start:pointer:1000', 'complete']);
    expect(hold.state()).toBe('signed');
    hold.release();
    hold.press('pointer');
    vi.advanceTimersByTime(2000);
    expect(calls).toHaveLength(2);
  });

  it('ED-81 letting go early cancels; the hint comes only the first time', () => {
    const { hold, calls } = setup();
    hold.press('pointer');
    vi.advanceTimersByTime(400);
    hold.release();
    hold.press('pointer');
    vi.advanceTimersByTime(300);
    hold.release();
    vi.advanceTimersByTime(2000);
    expect(calls).toEqual([
      'start:pointer:1000',
      'cancel:true',
      'start:pointer:1000',
      'cancel:false',
    ]);
    expect(hold.state()).toBe('idle');
  });

  it('ED-82 Enter or Space needs no holding: the line draws in 400ms and signs', () => {
    const { hold, calls } = setup();
    hold.press('keyboard');
    hold.release();
    vi.advanceTimersByTime(400);
    expect(calls).toEqual(['start:keyboard:400', 'complete']);
  });

  it('ED-83 a refused or failed signing can be held again', () => {
    const { hold, calls } = setup();
    hold.press('pointer');
    vi.advanceTimersByTime(1000);
    hold.reset();
    expect(hold.state()).toBe('idle');
    hold.press('keyboard');
    vi.advanceTimersByTime(400);
    expect(calls.filter((c) => c === 'complete')).toHaveLength(2);
  });
});
