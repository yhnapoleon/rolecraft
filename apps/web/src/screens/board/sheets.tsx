// The board's two sheets, on the shell's ui-kit Sheet (shadcn/Radix Dialog):
// - the document (decision 14): paper over the desk column only, non-modal, so the rail stays in
//   use while you read; the dimmed desk, Esc or × closes it;
// - the record (what was the Activity tab): an instrument sheet over the rail.
// The words come from ui.js as markup; buttons in it reach ui.js through data-action.
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Sheet, SheetContent, SheetTitle } from '../../ui-kit';

export type DocSheetData = {
  id: string;
  title: string;
  titleLang?: string;
  meta: string;
  body: string;
  foot: string;
};

const X = (
  <svg className="i" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />
  </svg>
);
// A dialog of the page itself (cite picker, settings) opened on top takes Esc first.
const pageDialogOpen = () =>
  (document.getElementById('sheet') as HTMLDialogElement | null)?.open === true;

export function DocSheet(props: {
  sheet: DocSheetData | null;
  container: HTMLElement | null;
  labels: { close: string; dim: string };
  onClose: () => void;
}) {
  const { sheet, container, labels, onClose } = props;
  // While it slides out the sheet keeps its last words.
  const last = useRef(sheet);
  if (sheet) last.current = sheet;
  const shown = last.current;
  const open = !!sheet;
  const [dim, setDim] = useState(open);
  useEffect(() => {
    if (open) {
      setDim(true);
      return;
    }
    const t = window.setTimeout(() => setDim(false), 200);
    return () => window.clearTimeout(t);
  }, [open]);
  if (!shown || !container) return null;
  return (
    <>
      {dim &&
        createPortal(
          <button
            type="button"
            className="mat-dim"
            data-state={open ? 'open' : 'closed'}
            tabIndex={-1}
            aria-label={labels.dim}
            onClick={onClose}
          />,
          container,
        )}
      <Sheet open={open} modal={false} onOpenChange={(o) => !o && onClose()}>
        <SheetContent
          container={container}
          side="right"
          surface="paper"
          className="mat-sheet"
          data-mat-sheet={shown.id}
          aria-describedby={undefined}
          // Focus goes to the sheet itself (named by its title), so no ring sits on the serif title.
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            container.querySelector<HTMLElement>('.mat-sheet')?.focus({ preventScroll: true });
          }}
          onCloseAutoFocus={(e) => e.preventDefault()}
          // Only the dimmed desk closes it: the rail, the topbar and toasts stay usable.
          onInteractOutside={(e) => e.preventDefault()}
          onEscapeKeyDown={(e) => pageDialogOpen() && e.preventDefault()}
        >
          <header className="mat-head">
            <div className="grow">
              <SheetTitle asChild>
                <h2 className="mat-title" lang={shown.titleLang}>
                  {shown.title}
                </h2>
              </SheetTitle>
              {/* biome-ignore lint/security/noDangerouslySetInnerHtml: markup drawn by ui.js, which escapes every value (as it does for the rest of the page) */}
              <p className="mat-meta" dangerouslySetInnerHTML={{ __html: shown.meta }} />
            </div>
            <button
              type="button"
              className="btn icon quiet small mat-x"
              aria-label={labels.close}
              onClick={onClose}
            >
              {X}
            </button>
          </header>
          <div
            className="mat-body"
            data-mat-body
            // biome-ignore lint/security/noDangerouslySetInnerHtml: markup drawn by ui.js, which escapes every value (as it does for the rest of the page)
            dangerouslySetInnerHTML={{ __html: shown.body }}
          />
          {/* biome-ignore lint/security/noDangerouslySetInnerHtml: markup drawn by ui.js, which escapes every value (as it does for the rest of the page) */}
          <footer className="mat-foot" dangerouslySetInnerHTML={{ __html: shown.foot }} />
        </SheetContent>
      </Sheet>
    </>
  );
}

export function RecordsSheet(props: {
  open: boolean;
  title: string;
  body: string;
  close: string;
  onClose: () => void;
}) {
  const { open, title, body, close, onClose } = props;
  return (
    <Sheet open={open} modal={false} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side="right"
        surface="instrument"
        className="records-drawer"
        aria-describedby={undefined}
        onOpenAutoFocus={(e) => {
          e.preventDefault();
          document.querySelector<HTMLElement>('.records-drawer')?.focus({ preventScroll: true });
        }}
        onCloseAutoFocus={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => pageDialogOpen() && e.preventDefault()}
      >
        <header className="records-head">
          <SheetTitle asChild>
            <h2>{title}</h2>
          </SheetTitle>
          <button
            type="button"
            className="btn icon quiet small"
            aria-label={close}
            onClick={onClose}
          >
            {X}
          </button>
        </header>
        {/* biome-ignore lint/security/noDangerouslySetInnerHtml: markup drawn by ui.js, which escapes every value (as it does for the rest of the page) */}
        <div className="records-body" dangerouslySetInnerHTML={{ __html: body }} />
      </SheetContent>
    </Sheet>
  );
}
