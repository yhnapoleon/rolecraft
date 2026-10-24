// Tabs on Radix (shadcn tabs, MIT), drawn as the same segmented control as the hat switch:
// real tab semantics (Radix triggers), the same sliding ink plate.
import { Tabs as Radix } from 'radix-ui';
import type * as React from 'react';
import { cn } from './cn';
import { InkLayer, type Segment, segmentClass, trackClass, useInkClip } from './toggle-group';

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
  const { track, layer } = useInkClip(value);
  return (
    <Radix.Root value={value} onValueChange={(v) => onChange(v as V)} className={className}>
      <Radix.List ref={track} aria-label={label} className={trackClass()}>
        {items.map((it) => (
          <Radix.Trigger
            key={it.value}
            value={it.value}
            title={it.title}
            className={segmentClass(false, 'sm')}
          >
            {it.label}
          </Radix.Trigger>
        ))}
        <InkLayer layer={layer} items={items} size="sm" />
      </Radix.List>
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
