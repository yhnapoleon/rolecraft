// "Your agent sent a draft": the connection notice's look (agent light, one line, close), with one
// action that opens the draft. Same visible-time budget: pointer, focus and hidden tabs pause it.
import { X } from 'lucide-react';
import { createElement, useEffect, useRef } from 'react';
import { toast as sonner } from 'sonner';
import { toastTimer } from '../../shell/status-toast';
import './draft-toast.css';

function DraftToast(p: {
  text: string;
  label: string;
  dismiss: string;
  run(): void;
  close(): void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const { close } = p;
  useEffect(() => {
    const el = ref.current?.closest<HTMLElement>('[data-sonner-toast]');
    if (!el) return;
    const timer = toastTimer(close, 8000);
    const enter = () => timer.pause('pointer');
    const leave = () => timer.resume('pointer');
    const visibility = () => (document.hidden ? timer.pause('hidden') : timer.resume('hidden'));
    el.addEventListener('mouseenter', enter);
    el.addEventListener('mouseleave', leave);
    document.addEventListener('visibilitychange', visibility);
    visibility();
    return () => {
      timer.stop();
      el.removeEventListener('mouseenter', enter);
      el.removeEventListener('mouseleave', leave);
      document.removeEventListener('visibilitychange', visibility);
    };
  }, [close]);
  return (
    <div
      ref={ref}
      className="rc-connection-toast aipm-draft-toast"
      role="status"
      aria-atomic="true"
    >
      <span className="rc-agent-light" data-state="connected" aria-hidden="true" />
      <span className="rc-connection-toast__text">{p.text}</span>
      <button
        type="button"
        className="aipm-draft-toast__go"
        onClick={() => {
          p.run();
          close();
        }}
      >
        {p.label}
      </button>
      <button type="button" onClick={close} aria-label={p.dismiss}>
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  );
}

export function showDraftToast(text: string, label: string, dismiss: string, run: () => void) {
  const id = `aipm-draft-${Date.now()}`;
  const close = () => sonner.dismiss(id);
  sonner.custom(() => createElement(DraftToast, { text, label, dismiss, run, close }), {
    id,
    duration: Infinity,
    testId: 'aipm-agent-draft',
  });
}
