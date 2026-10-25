// A Sonner content view with a visible-time budget: pointer, focus and hidden tabs pause it.
import { X } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { T } from '../app/i18n';

export function toastTimer(close: () => void, duration = 5000) {
  let remaining = duration;
  let started = Date.now();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const reasons = new Set<string>();
  const start = () => {
    started = Date.now();
    timer = setTimeout(close, remaining);
  };
  start();
  return {
    pause(reason: string) {
      if (!reasons.size) {
        clearTimeout(timer);
        remaining = Math.max(0, remaining - (Date.now() - started));
      }
      reasons.add(reason);
    },
    resume(reason: string) {
      if (reasons.delete(reason) && !reasons.size) start();
    },
    stop() {
      clearTimeout(timer);
    },
  };
}

export function ConnectionToast({ text, close }: { text: string; close: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current?.closest<HTMLElement>('[data-sonner-toast]');
    if (!el) return;
    const timer = toastTimer(close);
    const enter = () => timer.pause('pointer');
    const leave = () => timer.resume('pointer');
    const focus = () => timer.pause('focus');
    const blur = (event: FocusEvent) => {
      if (!el.contains(event.relatedTarget as Node | null)) timer.resume('focus');
    };
    const visibility = () => (document.hidden ? timer.pause('hidden') : timer.resume('hidden'));
    el.addEventListener('mouseenter', enter);
    el.addEventListener('mouseleave', leave);
    el.addEventListener('focusin', focus);
    el.addEventListener('focusout', blur);
    document.addEventListener('visibilitychange', visibility);
    if (el.matches(':hover')) enter();
    if (el.contains(document.activeElement)) focus();
    visibility();
    return () => {
      timer.stop();
      el.removeEventListener('mouseenter', enter);
      el.removeEventListener('mouseleave', leave);
      el.removeEventListener('focusin', focus);
      el.removeEventListener('focusout', blur);
      document.removeEventListener('visibilitychange', visibility);
    };
  }, [close]);
  return (
    <div
      ref={ref}
      className="rc-connection-toast"
      data-agent-connected-toast
      role="status"
      aria-atomic="true"
    >
      <span className="rc-agent-light" data-state="connected" aria-hidden="true" />
      <span className="rc-connection-toast__text">{text}</span>
      <button
        type="button"
        onClick={close}
        aria-label={T('关闭连接提示', 'Dismiss connection notice')}
      >
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  );
}
