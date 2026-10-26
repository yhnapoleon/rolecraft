/** L1 entry points. installAipmWorksheet backs host.openWorksheet; installAipmDesign keeps the
 * older feature slot working by opening the sheet of the server's focus step. */
import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { AipmProgress, EvidenceRefV2, StepId } from '../../aipm/types';
import { sendQuote, Worksheet, type WorksheetHost } from './worksheet';

export function installAipmWorksheet(host: WorksheetHost) {
  return {
    /** Mounts one sheet; returns the unmount function. */
    mount(root: HTMLElement, step: StepId) {
      const react = createRoot(root);
      react.render(<Worksheet key={step} host={host} step={step} />);
      return () => react.unmount();
    },
    /** From the material view's "quote to worksheet": the open sheet inserts it at the caret. */
    quote(ref: EvidenceRefV2, label: string) {
      sendQuote(ref, label);
    },
  };
}

function FocusSheet({ host }: { host: WorksheetHost }) {
  const [step, setStep] = useState<StepId | null>(null);
  useEffect(() => {
    host
      .readProgress()
      .then((p) => setStep((p as AipmProgress | null)?.focus_step ?? 'business'))
      .catch(() => setStep('business'));
  }, [host]);
  return step ? <Worksheet key={step} host={host} step={step} /> : null;
}

export function installAipmDesign(host: WorksheetHost) {
  return host.registerFeature('design', {
    render: () => '<div class="aipm-design-root"></div>',
    mount(root) {
      const react = createRoot(root);
      react.render(<FocusSheet host={host} />);
      return () => react.unmount();
    },
  });
}
export { DesignDesk } from './desk';
export type { DesignRead, DraftItem } from './desk';
export { Worksheet, type WorksheetHost } from './worksheet';
