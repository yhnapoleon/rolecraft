// The topbar's two islands: the hat switch with the stage scale, and the one primary key.
// They live in islands so the thumb, the scale and the key's label can move between states
// across ui.js redraws. Clicks go through runAction, the same path as a native button.
// Ink plates are only for the hat switch (a switch) and the primary key (what to press); the
// scale is a track (where you are), so the three never read as three things to press.
import { AnimatePresence, LayoutGroup, motion, useReducedMotion } from 'motion/react';
import { useEffect, useId, useState } from 'react';
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
};

export function HatScale({
  hat,
  hats,
  canSwitch,
  steps,
  scaleLabel,
  stepName,
  delivered,
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
        />
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
}: {
  hat: Hat;
  steps: HatScaleProps['steps'];
  label: string;
  stepName: string;
  delivered: boolean;
}) {
  const reduce = useReducedMotion();
  const id = useId();
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
                      aria-current={i === mark ? 'step' : undefined}
                      onClick={() => {
                        void runAction(`stage-${hat}`, undefined, { step: s.id }).catch(() => {});
                      }}
                    >
                      {walked && (
                        <svg viewBox="0 0 16 16" className="rc-scale__tick" aria-hidden="true">
                          <path d="m3.5 8.5 3 3 6-7" />
                        </svg>
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
      {/* Narrow widths: "1/3" on its own short track; read out in full. */}
      <span className="rc-scale__compact" data-delivered={delivered}>
        <span aria-hidden="true">
          {delivered ? steps.length : at + 1}/{steps.length}
        </span>
        <span className="sr-only">{stepName}</span>
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
