// Segmented control on Radix ToggleGroup (shadcn toggle-group, MIT). The selected item gets an
// ink thumb that slides between items (Motion layoutId, ~200ms spring). Used by the hat switch
// and the result page's view switch.
import { LayoutGroup, motion, useReducedMotion } from 'motion/react';
import { ToggleGroup as Radix } from 'radix-ui';
import { useId } from 'react';
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
  const id = useId();
  const reduce = useReducedMotion();
  return (
    <LayoutGroup id={id}>
      <Radix.Root
        type="single"
        value={value}
        // Radix lets a single group be emptied by clicking the active item; we always keep one.
        onValueChange={(v) => v && onChange(v as V)}
        aria-label={label}
        className={cn(trackClass(), className)}
      >
        {items.map((it) => {
          const on = it.value === value;
          return (
            <Radix.Item
              key={it.value}
              value={it.value}
              title={it.title}
              className={segmentClass(on, size)}
            >
              {on && (
                <motion.span
                  layoutId="thumb"
                  aria-hidden="true"
                  className="tw:absolute tw:inset-0 tw:-z-10 tw:rounded-[6px] tw:bg-primary"
                  transition={
                    reduce ? { duration: 0 } : { type: 'spring', duration: 0.2, bounce: 0.12 }
                  }
                />
              )}
              <span className="tw:relative">{it.label}</span>
            </Radix.Item>
          );
        })}
      </Radix.Root>
    </LayoutGroup>
  );
}
