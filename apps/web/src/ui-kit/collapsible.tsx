// Collapsible on Radix (shadcn collapsible, MIT). Content height animates with Radix's
// --radix-collapsible-content-height (the one allowed height animation: a disclosure).
import { Collapsible as Radix } from 'radix-ui';
import type * as React from 'react';
import { cn } from './cn';
import './kit.css';

export const Collapsible = Radix.Root;
export const CollapsibleTrigger = Radix.Trigger;

export function CollapsibleContent({
  className,
  ...props
}: React.ComponentProps<typeof Radix.Content>) {
  return (
    <Radix.Content className={cn('rc-collapsible tw:overflow-hidden', className)} {...props} />
  );
}
