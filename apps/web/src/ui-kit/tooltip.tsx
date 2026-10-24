// Tooltip on Radix (shadcn tooltip, MIT). The first one waits; moving to a neighbour inside the
// same provider opens at once and without animation (Radix's skipDelayDuration + data-state
// "instant-open"). Native templates keep title= as their fallback.
import { Tooltip as Radix } from 'radix-ui';
import type * as React from 'react';
import { cn } from './cn';

export function TooltipProvider({ children }: { children: React.ReactNode }) {
  return (
    <Radix.Provider delayDuration={500} skipDelayDuration={300}>
      {children}
    </Radix.Provider>
  );
}

export function Tooltip({
  content,
  children,
  side = 'bottom',
}: {
  content: React.ReactNode;
  children: React.ReactNode;
  side?: 'top' | 'bottom' | 'left' | 'right';
}) {
  if (!content) return <>{children}</>;
  return (
    <Radix.Root>
      <Radix.Trigger asChild>{children}</Radix.Trigger>
      <Radix.Portal>
        <Radix.Content
          side={side}
          sideOffset={6}
          collisionPadding={8}
          className={cn(
            'rc-portal rc-tooltip tw:z-[200] tw:max-w-64 tw:px-2.5 tw:py-1.5 tw:rounded-key',
            'tw:bg-primary tw:text-on-primary tw:font-sans tw:text-[12px] tw:leading-snug',
            'tw:origin-(--radix-tooltip-content-transform-origin)',
          )}
        >
          {content}
        </Radix.Content>
      </Radix.Portal>
    </Radix.Root>
  );
}
