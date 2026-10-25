// Sheet on Radix Dialog (shadcn sheet, MIT). `container` puts the portal inside an element, so
// a reading sheet can cover only the main screen while the right rail stays usable (decision 14).
// Paper or instrument surface; 280ms in/out on the drawer curve; the scrim uses --scrim-b.
import { Dialog } from 'radix-ui';
import type * as React from 'react';
import { cn } from './cn';
import './kit.css';

export const Sheet = Dialog.Root;
export const SheetTrigger = Dialog.Trigger;
export const SheetClose = Dialog.Close;
export const SheetTitle = Dialog.Title;
export const SheetDescription = Dialog.Description;

export function SheetContent({
  side = 'right',
  surface = 'paper',
  container,
  modal = true,
  className,
  children,
  ...props
}: React.ComponentProps<typeof Dialog.Content> & {
  side?: 'right' | 'left' | 'bottom';
  surface?: 'paper' | 'instrument';
  /** Where the sheet lives; defaults to <body>. Pass the main screen to cover only it. */
  container?: HTMLElement | null;
  /** false keeps the rest of the page interactive (no focus trap outside the container). */
  modal?: boolean;
}) {
  const contained = !!container;
  return (
    <Dialog.Portal container={container ?? undefined}>
      <Dialog.Overlay
        className={cn(
          'rc-portal rc-sheet-scrim tw:inset-0 tw:z-[80] tw:bg-[var(--scrim-b)]',
          contained ? 'tw:absolute' : 'tw:fixed',
        )}
      />
      <Dialog.Content
        data-side={side}
        data-modal={modal}
        className={cn(
          'rc-portal rc-sheet tw:z-[81] tw:flex tw:flex-col tw:outline-none tw:rounded-dialog tw:overflow-hidden',
          contained ? 'tw:absolute' : 'tw:fixed',
          side === 'right' &&
            'tw:inset-y-[var(--sheet-inset)] tw:right-[var(--sheet-inset)] tw:w-[min(720px,calc(100%_-_2_*_var(--sheet-inset)))]',
          side === 'left' &&
            'tw:inset-y-[var(--sheet-inset)] tw:left-[var(--sheet-inset)] tw:w-[min(720px,calc(100%_-_2_*_var(--sheet-inset)))]',
          side === 'bottom' &&
            'tw:inset-x-[var(--sheet-inset)] tw:bottom-[var(--sheet-inset)] tw:max-h-[85%]',
          surface === 'paper' ? 'tw:bg-paper tw:shadow-float' : 'tw:bg-inst tw:shadow-float',
          className,
        )}
        {...props}
      >
        {children}
      </Dialog.Content>
    </Dialog.Portal>
  );
}
