// Segmented control on Radix ToggleGroup (shadcn toggle-group, MIT). The selected item sits on
// an ink plate that slides between items (~200ms on the spring curve). Used by the hat switch
// and, through Tabs, the result page's view switch.
import './kit.css';
import { ToggleGroup as Radix } from 'radix-ui';
import { useLayoutEffect, useRef } from 'react';
import { cn } from './cn';

/** The control's track: instrument inset with a hairline. */
export const trackClass = () =>
  'tw:relative tw:inline-flex tw:items-center tw:gap-0.5 tw:p-0.5 tw:rounded-key tw:bg-inst-2 tw:shadow-[inset_0_0_0_0.5px_var(--line)]';

/** One segment; the selected one sits on the ink thumb. */
export const segmentClass = (on: boolean, size: 'sm' | 'md') =>
  cn(
    'tw:relative tw:z-0 tw:inline-flex tw:items-center tw:justify-center tw:border-0 tw:bg-transparent',
    'tw:font-sans tw:font-semibold tw:whitespace-nowrap tw:cursor-pointer tw:rounded-[6px]',
    'tw:transition-[color,scale] tw:duration-160 tw:ease-out tw:active:scale-[0.97]',
    'tw:focus-visible:outline-solid tw:focus-visible:outline-2 tw:focus-visible:outline-offset-2 tw:focus-visible:outline-ink',
    size === 'sm' ? 'tw:h-6 tw:px-2.5 tw:text-[12px]' : 'tw:h-7 tw:px-3 tw:text-[13px]',
    on ? 'tw:text-on-primary' : 'tw:text-ink-2 tw:hover:text-ink',
  );

export type Segment<V extends string> = { value: V; label: React.ReactNode; title?: string };

/**
 * The ink plate, done the clip-path way (Emil Kowalski): a copy of the labels in ink, clipped to
 * the active item's box, sits over the plain labels. Moving the clip moves the plate, and the
 * text under it is always the right colour, mid-slide included.
 */
export function useInkClip(value: string) {
  const track = useRef<HTMLDivElement>(null);
  const layer = useRef<HTMLDivElement>(null);
  const last = useRef<string | null>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-measure whenever the value moves
  useLayoutEffect(() => {
    const el = track.current;
    const ink = layer.current;
    if (!el || !ink) return;
    const clipOf = () => {
      const on = el.querySelector<HTMLElement>('[data-state="on"], [data-state="active"]');
      if (!on) return 'inset(50%)';
      const l = on.offsetLeft;
      const r = el.clientWidth - l - on.offsetWidth;
      const t = on.offsetTop;
      const b = el.clientHeight - t - on.offsetHeight;
      return `inset(${t}px ${r}px ${b}px ${l}px round 6px)`;
    };
    const next = clipOf();
    ink.style.clipPath = next;
    // Animated with WAAPI, not a CSS transition: under ui.js the island is moved into a freshly
    // drawn bar on the same click, and a moved node loses its running transitions.
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (last.current && last.current !== next && !reduce) {
      const spring = getComputedStyle(document.documentElement).getPropertyValue('--spring').trim();
      ink.animate([{ clipPath: last.current }, { clipPath: next }], {
        duration: 200,
        easing: spring || 'cubic-bezier(.23,1,.32,1)',
      });
    }
    last.current = next;
    const ro = new ResizeObserver(() => {
      last.current = clipOf();
      ink.style.clipPath = last.current;
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [value]);
  return { track, layer };
}

export function InkLayer({
  layer,
  items,
  size,
}: {
  layer: React.RefObject<HTMLDivElement | null>;
  items: { value: string; label: React.ReactNode }[];
  size: 'sm' | 'md';
}) {
  return (
    <div ref={layer} className="rc-ink-layer" aria-hidden="true">
      {items.map((it) => (
        <span key={it.value} className={segmentClass(true, size)}>
          {it.label}
        </span>
      ))}
    </div>
  );
}

export function Segmented<V extends string>({
  value,
  onChange,
  items,
  label,
  size = 'md',
  className,
}: {
  value: V;
  onChange: (v: V) => void;
  items: Segment<V>[];
  label: string;
  size?: 'sm' | 'md';
  className?: string;
}) {
  const { track, layer } = useInkClip(value);
  return (
    <Radix.Root
      ref={track}
      type="single"
      value={value}
      // Radix lets a single group be emptied by clicking the active item; we always keep one.
      onValueChange={(v) => v && onChange(v as V)}
      aria-label={label}
      className={cn(trackClass(), className)}
    >
      {items.map((it) => (
        <Radix.Item
          key={it.value}
          value={it.value}
          title={it.title}
          className={segmentClass(false, size)}
        >
          {it.label}
        </Radix.Item>
      ))}
      <InkLayer layer={layer} items={items} size={size} />
    </Radix.Root>
  );
}
