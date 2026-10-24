// The topbar's two islands: the hat switch with the stage scale, and the one primary key.
// They live in islands so the thumb, the scale and the key's label can move between states
// across ui.js redraws. Clicks go through runAction, the same path as a native button.
// Ink plates are only for the hat switch (a switch) and the primary key (what to press); the
// scale is a track (where you are), so the three never read as three things to press.
import { Eye } from 'lucide-react';
import { AnimatePresence, LayoutGroup, motion, useReducedMotion } from 'motion/react';
import { useEffect, useId, useRef, useState } from 'react';
import { Segmented } from '../ui-kit/toggle-group';
import type { Hat } from './hat';
import { runAction } from './registry';
import type { Stage } from './stage';
import { showToast } from './toast';

const EASE_OUT = [0.23, 1, 0.32, 1] as const;

/** A follow-up an action's error may offer: one key on the toast, running another action. */
type ToastAction = { label: string; action: string; data?: Record<string, string> };
/** The thumb leads: the screen changes once it has started to slide. */
const LEAD_MS = 120;

export type HatScaleProps = {
  hat: Hat;
  /** Labels already in the interface language. */
  hats: { pm: string; engineer: string; label: string; busy: string };
  /** False where only one hat can be worn (no practice, an old local one). */
  canSwitch: boolean;
  steps: { id: string; label: string; state: Stage['steps'][number]['state'] }[];
  scaleLabel: string;
  /** "Step 1 of 3: Investigate", for the compact scale's screen-reader name. */
  stepName: string;
  delivered: boolean;
  /** The interface language, so a language switch redraws the labels. */
  lang?: string;
  /**
   * Optional: the step whose screen is shown when it is not the current step's own (looking
   * back at Investigate while deciding). The scale outlines it and writes `viewingWord`; the
   * current step keeps its ink stretch. Added by the stage-view fix (204).
   */
  viewing?: string;
  viewingWord?: string;
  /** Optional: the way back to the current step's screen, a ghost key right after the scale. */
  back?: { label: string; action: string };
};

export function HatScale({
  hat,
  hats,
  canSwitch,
  steps,
  scaleLabel,
  stepName,
  delivered,
  viewing,
  viewingWord,
  back,
}: HatScaleProps) {
  // The thumb moves at the click; the screen follows when the other hat's screen is ready.
  // While it is being prepared the switch shows a spinning dot; a failure sends the thumb back
  // at once and says why.
  const [asked, setAsked] = useState<Hat | null>(null);
  const [busy, setBusy] = useState(false);
  // biome-ignore lint/correctness/useExhaustiveDependencies: the worn hat changing ends the request
  useEffect(() => setAsked(null), [hat]);
  const ask = (next: Hat) => {
    if (busy || next === hat) return;
    setAsked(next);
    setBusy(true);
    setTimeout(() => {
      runAction('hat-switch', undefined, { hat: next })
        .catch((err: unknown) => {
          setAsked(null);
          // An error may carry one follow-up action (toastAction) for the toast's key.
          const follow = (err as { toastAction?: ToastAction } | null)?.toastAction;
          showToast(err instanceof Error && err.message ? err.message : String(err), {
            label: follow?.label,
            run: follow
              ? () => {
                  runAction(follow.action, undefined, follow.data).catch((e: unknown) =>
                    showToast(e instanceof Error ? e.message : String(e)),
                  );
                }
              : undefined,
          });
        })
        .finally(() => setBusy(false));
    }, LEAD_MS);
  };
  return (
    <div className="rc-hatscale">
      {canSwitch && (
        <span className="rc-hat-wrap" aria-busy={busy || undefined}>
          <Segmented<Hat>
            className="rc-hat"
            value={asked ?? hat}
            onChange={ask}
            label={hats.label}
            items={[
              { value: 'pm', label: hats.pm },
              { value: 'engineer', label: hats.engineer },
            ]}
          />
          {busy && (
            <svg
              className="rc-hat-spin key-spin"
              viewBox="0 0 16 16"
              role="img"
              aria-label={hats.busy}
            >
              <circle
                cx="8"
                cy="8"
                r="6"
                fill="none"
                stroke="currentColor"
                strokeOpacity=".25"
                strokeWidth="2"
              />
              <path
                d="M14 8a6 6 0 0 0-6-6"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          )}
        </span>
      )}
      {steps.length > 0 && (
        <Scale
          hat={hat}
          steps={steps}
          label={scaleLabel}
          stepName={stepName}
          delivered={delivered}
          viewing={viewing}
          viewingWord={viewingWord}
        />
      )}
      {back && (
        <button
          type="button"
          className="btn quiet small rc-scale__back"
          onClick={() => {
            runAction(back.action).catch((e: unknown) =>
              showToast(e instanceof Error ? e.message : String(e)),
            );
          }}
        >
          <svg viewBox="0 0 16 16" className="rc-scale__back-i" aria-hidden="true">
            <path d="M6.5 4 2.5 8l4 4M3 8h7.5a3 3 0 0 1 3 3v1" />
          </svg>
          <span className="rc-scale__back-label">{back.label}</span>
        </button>
      )}
    </div>
  );
}

/**
 * Three steps of text along a hairline track. The current step is ink text (600) with a solid
 * ink stretch of track under it, which slides when the step moves; steps walked are ticked
 * (--ink-2), steps ahead are --ink-3. Once delivered the track and the ticks turn green over
 * 520ms (an opacity cross-fade) and "Delivered" is written in --good. Status only: every step
 * can be clicked, nothing is forced in order. When the set of steps changes (another hat), the
 * words cross-fade in 160ms.
 */
function Scale({
  hat,
  steps,
  label,
  stepName,
  delivered,
  viewing,
  viewingWord,
}: {
  hat: Hat;
  steps: HatScaleProps['steps'];
  label: string;
  stepName: string;
  delivered: boolean;
  viewing?: string;
  viewingWord?: string;
}) {
  const reduce = useReducedMotion();
  const id = useId();
  // The narrow scale's list of steps: closes on a pick, Esc, or a press anywhere else.
  const [listOpen, setListOpen] = useState(false);
  const opener = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLOListElement>(null);
  const byKeys = useRef(false);
  // Opened from the keyboard, focus goes to the first step; Esc gives it back to "2/3".
  useEffect(() => {
    if (listOpen && byKeys.current)
      list.current?.querySelector<HTMLButtonElement>('button')?.focus();
  }, [listOpen]);
  useEffect(() => {
    if (!listOpen) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent && e.key !== 'Escape') return;
      if (e instanceof PointerEvent && (e.target as Element)?.closest?.('.rc-scale__compact-wrap'))
        return;
      setListOpen(false);
      if (e instanceof KeyboardEvent) opener.current?.focus();
    };
    document.addEventListener('pointerdown', close, true);
    document.addEventListener('keydown', close, true);
    return () => {
      document.removeEventListener('pointerdown', close, true);
      document.removeEventListener('keydown', close, true);
    };
  }, [listOpen]);
  const at = Math.max(
    0,
    steps.findIndex((s) => s.state === 'current'),
  );
  const mark = delivered ? steps.length - 1 : at;
  const slide = reduce ? { duration: 0 } : { type: 'spring' as const, duration: 0.28, bounce: 0 };
  const fade = { duration: reduce ? 0.16 : 0.52, ease: EASE_OUT };
  const set = steps.map((s) => s.id).join('|');
  return (
    <nav className="rc-scale" aria-label={label} data-delivered={delivered}>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.div
          key={set}
          className="rc-scale__wide"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.16, ease: EASE_OUT }}
        >
          <LayoutGroup id={`${id}-${set}`}>
            <ol className="rc-scale__steps">
              {steps.map((s, i) => {
                const walked = delivered || s.state === 'done';
                return (
                  <li key={s.id}>
                    <button
                      type="button"
                      className="rc-scale__step"
                      data-state={delivered ? 'done' : s.state}
                      data-last={i === steps.length - 1 || undefined}
                      data-viewing={s.id === viewing || undefined}
                      aria-current={i === mark ? 'step' : undefined}
                      onClick={() => {
                        void runAction(`stage-${hat}`, undefined, { step: s.id }).catch(() => {});
                      }}
                    >
                      {walked && s.id !== viewing && (
                        <svg viewBox="0 0 16 16" className="rc-scale__tick" aria-hidden="true">
                          <path d="m3.5 8.5 3 3 6-7" />
                        </svg>
                      )}
                      {s.id === viewing && viewingWord && (
                        <span className="rc-scale__viewing">
                          <Eye size={14} strokeWidth={1.75} aria-hidden="true" />
                          {viewingWord}
                        </span>
                      )}
                      {s.label}
                      {i === mark && (
                        <motion.span layoutId="mark" className="rc-scale__mark" transition={slide}>
                          <motion.span
                            className="rc-scale__mark-good"
                            initial={false}
                            animate={{ opacity: delivered ? 1 : 0 }}
                            transition={fade}
                          />
                        </motion.span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ol>
          </LayoutGroup>
          <span className="rc-scale__track" aria-hidden="true">
            <motion.i
              className="rc-scale__track-good"
              initial={false}
              animate={{ opacity: delivered ? 1 : 0 }}
              transition={fade}
            />
          </span>
        </motion.div>
      </AnimatePresence>
      {/* Narrow widths: "1/3" on its own short track, read out in full. It opens the steps as a
          short list, so every step can be reached at phone width too (204). */}
      <span className="rc-scale__compact-wrap">
        <button
          type="button"
          className="rc-scale__compact"
          data-delivered={delivered}
          data-viewing={viewing ? true : undefined}
          ref={opener}
          aria-expanded={listOpen}
          aria-controls={`${id}-steps`}
          onClick={(e) => {
            byKeys.current = e.detail === 0;
            setListOpen((v) => !v);
          }}
        >
          {/* Short at phone width ("Viewing 1/3"); the full name is read out. */}
          <span aria-hidden="true">
            {viewing && viewingWord
              ? `${viewingWord} ${steps.findIndex((s) => s.id === viewing) + 1}/${steps.length}`
              : `${delivered ? steps.length : at + 1}/${steps.length}`}
          </span>
          <span className="sr-only">
            {viewing && viewingWord
              ? `${viewingWord} ${steps.find((s) => s.id === viewing)?.label ?? ''}. ${stepName}`
              : stepName}
          </span>
        </button>
        {listOpen && (
          <ol className="rc-scale__list" id={`${id}-steps`} ref={list} aria-label={label}>
            {steps.map((s, i) => (
              <li key={s.id}>
                <button
                  type="button"
                  className="rc-scale__list-step"
                  data-state={delivered ? 'done' : s.state}
                  data-last={i === steps.length - 1 || undefined}
                  data-delivered={delivered || undefined}
                  data-viewing={s.id === viewing || undefined}
                  aria-current={i === mark ? 'step' : undefined}
                  onClick={() => {
                    setListOpen(false);
                    void runAction(`stage-${hat}`, undefined, { step: s.id }).catch(() => {});
                  }}
                >
                  {/* The wide scale's marks: walked steps ticked, the current one in ink. */}
                  <span className="rc-scale__list-n" aria-hidden="true">
                    {delivered || s.state === 'done' ? (
                      <svg viewBox="0 0 16 16" className="rc-scale__tick" aria-hidden="true">
                        <path d="m3.5 8.5 3 3 6-7" />
                      </svg>
                    ) : (
                      i + 1
                    )}
                  </span>
                  {s.label}
                  {s.id === viewing && viewingWord && (
                    <span className="rc-scale__viewing">
                      <Eye size={14} strokeWidth={1.75} aria-hidden="true" />
                      {viewingWord}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ol>
        )}
      </span>
    </nav>
  );
}

export type PrimaryKeyProps = {
  label: string;
  action: string;
  id?: string;
  /** Present when the key cannot be pressed: why (decision 4). */
  reason?: string;
  hint?: string;
  icon?: 'stamp' | 'none';
};

/**
 * The one ink key. When the stage moves, the old words blur out, the new ones fade in, and the
 * key's width follows (Motion layout, a FLIP). The button carries data-action, so the document
 * click listener runs it like any native button. When it cannot be pressed it stays focusable
 * (aria-disabled, described by its reason) and a press says the reason in a toast instead.
 */
export function PrimaryKey({ label, action, id, reason, hint, icon }: PrimaryKeyProps) {
  const reduce = useReducedMotion();
  const reasonId = useId();
  const swap = reduce
    ? { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 } }
    : {
        initial: { opacity: 0, filter: 'blur(2px)' },
        animate: { opacity: 1, filter: 'blur(0px)' },
        exit: { opacity: 0, filter: 'blur(2px)' },
      };
  return (
    <span className="rc-primary">
      {reason && (
        <span id={reasonId} className="rc-primary__reason">
          {reason}
        </span>
      )}
      <motion.button
        layout={!reduce}
        type="button"
        className="rc-primary__key"
        data-action={reason ? undefined : action}
        data-id={reason ? undefined : id}
        aria-disabled={reason ? 'true' : undefined}
        aria-describedby={reason ? reasonId : undefined}
        title={reason ? undefined : hint || undefined}
        onClick={reason ? () => showToast(reason) : undefined}
        transition={{ layout: { duration: 0.28, ease: EASE_OUT } }}
        style={{ borderRadius: 8 }}
      >
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.span
            key={`${action}|${label}`}
            layout="position"
            className="rc-primary__label"
            transition={{ duration: 0.16, ease: EASE_OUT }}
            {...swap}
          >
            {icon === 'stamp' && (
              <svg viewBox="0 0 24 24" className="rc-primary__icon" aria-hidden="true">
                <path d="M9.5 4h5l-1 6h3.5a2 2 0 0 1 2 2v2.5H5V12a2 2 0 0 1 2-2h3.5l-1-6zM5 18.5h14" />
              </svg>
            )}
            {label}
          </motion.span>
        </AnimatePresence>
      </motion.button>
    </span>
  );
}
