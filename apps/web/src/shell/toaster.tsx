// The one Sonner toaster: instrument surface, floating shadow, 12px radius, bottom centre.
import { Toaster } from 'sonner';

export function ShellToaster() {
  return (
    <Toaster
      position="bottom-center"
      visibleToasts={3}
      gap={8}
      offset={{ bottom: 24 }}
      mobileOffset={{ bottom: 16, left: 16, right: 16 }}
      containerAriaLabel="Notifications"
      className="rc-toaster rc-portal"
      toastOptions={{
        unstyled: true,
        classNames: {
          toast:
            'rc-toast tw:flex tw:items-center tw:gap-3 tw:min-h-11 tw:w-[min(440px,calc(100vw-32px))] tw:py-2.5 tw:pl-4 tw:pr-2.5 tw:rounded-panel tw:bg-inst tw:text-ink tw:shadow-float tw:font-sans tw:text-[13.5px] tw:leading-snug',
          content: 'tw:flex-1 tw:min-w-0',
          title: 'tw:font-normal',
          icon: 'tw:flex tw:shrink-0 tw:items-center',
          actionButton:
            'rc-toast-act tw:shrink-0 tw:h-8 tw:px-3 tw:rounded-key tw:bg-transparent tw:text-ink tw:font-semibold tw:text-[13px] tw:border-0 tw:cursor-pointer tw:transition-[background-color,scale] tw:duration-160 tw:ease-out tw:hover:bg-fill-2 tw:active:scale-[0.97]',
        },
      }}
    />
  );
}
