// Tabs on Radix (shadcn tabs, MIT), drawn as the same segmented control as the hat switch:
// real tab semantics (Radix triggers), the same sliding ink thumb.
import { LayoutGroup, motion, useReducedMotion } from 'motion/react';
import { Tabs as Radix } from 'radix-ui';
import { useId } from 'react';
import type * as React from 'react';
import { cn } from './cn';
import { type Segment, segmentClass, trackClass } from './toggle-group';

export function Tabs<V extends string>({
  value,
  onChange,
  items,
  label,
  children,
  className,
}: {
  value: V;
  onChange: (v: V) => void;
  items: Segment<V>[];
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  const id = useId();
  const reduce = useReducedMotion();
  return (
    <Radix.Root value={value} onValueChange={(v) => onChange(v as V)} className={className}>
      <LayoutGroup id={id}>
        <Radix.List aria-label={label} className={trackClass()}>
          {items.map((it) => {
            const on = it.value === value;
            return (
              <Radix.Trigger
                key={it.value}
                value={it.value}
                title={it.title}
                className={segmentClass(on, 'sm')}
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
              </Radix.Trigger>
            );
          })}
        </Radix.List>
      </LayoutGroup>
      {children}
    </Radix.Root>
  );
}

export function TabPanel({
  value,
  className,
  ...props
}: React.ComponentProps<typeof Radix.Content>) {
  return (
    <Radix.Content
      value={value}
      className={cn(
        'tw:outline-none tw:focus-visible:outline-solid tw:focus-visible:outline-2 tw:focus-visible:outline-ink',
        className,
      )}
      {...props}
    />
  );
}
