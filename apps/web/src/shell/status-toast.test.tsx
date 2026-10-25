import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setPreference } from '../app/i18n';
import { ConnectionToast, toastTimer } from './status-toast';
afterEach(() => vi.useRealTimers());
describe('connection toast visible time', () => {
  it('closes after five visible seconds', () => {
    vi.useFakeTimers();
    const close = vi.fn();
    toastTimer(close);
    vi.advanceTimersByTime(4999);
    expect(close).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(close).toHaveBeenCalledTimes(1);
  });
  it('pauses on overlapping hover, focus and hidden state, then uses the remaining time', () => {
    vi.useFakeTimers();
    const close = vi.fn();
    const timer = toastTimer(close);
    vi.advanceTimersByTime(2000);
    timer.pause('pointer');
    timer.pause('focus');
    vi.advanceTimersByTime(10000);
    timer.resume('pointer');
    vi.advanceTimersByTime(5000);
    expect(close).not.toHaveBeenCalled();
    timer.pause('hidden');
    timer.resume('focus');
    vi.advanceTimersByTime(5000);
    expect(close).not.toHaveBeenCalled();
    timer.resume('hidden');
    vi.advanceTimersByTime(2999);
    expect(close).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(close).toHaveBeenCalledTimes(1);
  });
  it('cancels the timer when dismissed or unmounted', () => {
    vi.useFakeTimers();
    const close = vi.fn();
    const timer = toastTimer(close);
    timer.stop();
    vi.advanceTimersByTime(6000);
    expect(close).not.toHaveBeenCalled();
  });
  it('provides a polite status and localized manual close control', () => {
    setPreference('en');
    const html = renderToStaticMarkup(
      <ConnectionToast text="Your agent is connected" close={() => {}} />,
    );
    expect(html).toContain('role="status"');
    expect(html).toContain('Dismiss connection notice');
    expect(html).not.toMatch(/[\u4e00-\u9fff]/);
    setPreference('zh');
  });
});
