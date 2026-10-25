// Button, from shadcn/ui (MIT), in our four levels and seven states (implementation plan §2.4).
// The native side uses the same look through the .k classes in ui-kit/keys.css.
import { cva, type VariantProps } from 'class-variance-authority';
import { Check, LoaderCircle } from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { Slot } from 'radix-ui';
import type * as React from 'react';
import { cn } from './cn';

export const buttonVariants = cva(
  [
    'tw:relative tw:inline-flex tw:items-center tw:justify-center tw:gap-1.5 tw:whitespace-nowrap',
    'tw:font-sans tw:text-[13.5px] tw:font-semibold tw:leading-none tw:select-none',
    'tw:border-0 tw:cursor-pointer',
    'tw:transition-[background-color,box-shadow,scale,opacity] tw:duration-160 tw:ease-out',
    'tw:active:scale-[0.97] tw:motion-reduce:active:scale-100',
    'tw:focus-visible:outline-solid tw:focus-visible:outline-2 tw:focus-visible:outline-offset-2 tw:focus-visible:outline-ink',
    'tw:disabled:opacity-40 tw:disabled:cursor-default tw:disabled:active:scale-100',
    'tw:aria-busy:cursor-progress',
  ],
  {
    variants: {
      variant: {
        primary:
          'tw:h-9 tw:px-4 tw:rounded-key tw:bg-primary tw:text-on-primary tw:shadow-primary tw:[&_.lucide]:stroke-[1.9]',
        secondary:
          'tw:h-9 tw:px-3.5 tw:rounded-key tw:bg-key tw:text-ink tw:shadow-key tw:hover:bg-[color-mix(in_oklab,var(--key-bg)_94%,var(--ink)_6%)] tw:active:bg-[color-mix(in_oklab,var(--key-bg)_90%,var(--ink)_10%)]',
        ghost:
          'tw:h-9 tw:px-2.5 tw:rounded-key tw:bg-transparent tw:text-ink-2 tw:hover:bg-fill tw:hover:text-ink',
        icon: 'tw:size-8 tw:rounded-key tw:bg-transparent tw:text-ink-2 tw:hover:bg-fill tw:hover:text-ink',
      },
    },
    defaultVariants: { variant: 'secondary' },
  },
);

export type ButtonState = 'idle' | 'loading' | 'done';

export type ButtonProps = React.ComponentProps<'button'> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
    /** Leading icon; replaced by a spinner while loading and by a check when done. */
    icon?: React.ReactNode;
    state?: ButtonState;
    /** Shown under a disabled button: why it cannot be pressed (decision 4). */
    reason?: React.ReactNode;
  };

export function Button({
  className,
  variant,
  asChild = false,
  icon,
  state = 'idle',
  reason,
  children,
  disabled,
  ...props
}: ButtonProps) {
  const reduce = useReducedMotion();
  const Comp = asChild ? Slot.Root : 'button';
  const glyph =
    state === 'loading' ? (
      <LoaderCircle className="tw:size-3.5 tw:animate-spin" aria-hidden="true" />
    ) : state === 'done' ? (
      <Check className="tw:size-3.5" aria-hidden="true" />
    ) : (
      icon
    );
  // Done: the icon cross-fades through blur(2px) into a check (the caller resets after 1.6s).
  const lead = glyph ? (
    <span className="tw:inline-grid tw:size-3.5 tw:place-items-center" aria-hidden="true">
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={state}
          className="tw:inline-grid tw:place-items-center"
          initial={reduce ? { opacity: 0 } : { opacity: 0, filter: 'blur(2px)', scale: 0.9 }}
          animate={{ opacity: 1, filter: 'blur(0px)', scale: 1 }}
          exit={reduce ? { opacity: 0 } : { opacity: 0, filter: 'blur(2px)', scale: 0.9 }}
          transition={{ duration: 0.16, ease: [0.23, 1, 0.32, 1] }}
        >
          {glyph}
        </motion.span>
      </AnimatePresence>
    </span>
  ) : null;
  const button = (
    <Comp
      data-slot="button"
      data-state={state}
      aria-busy={state === 'loading' || undefined}
      disabled={disabled}
      className={cn(buttonVariants({ variant }), className)}
      {...props}
    >
      {asChild ? (
        children
      ) : (
        <>
          {lead}
          {children}
        </>
      )}
    </Comp>
  );
  if (!disabled || !reason) return button;
  return (
    <span className="tw:inline-flex tw:flex-col tw:items-start tw:gap-1">
      {button}
      <span className="tw:text-[12px] tw:leading-tight tw:text-ink-3">{reason}</span>
    </span>
  );
}
