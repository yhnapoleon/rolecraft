/** L1 entry points (v2 host, claude/192-aipm-l1 8d4bf212). installAipmWorksheet registers the
 * 'worksheet' feature; L1 remounts it per sheet and says which sheet through currentScreen(). */
import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { AipmFeatureId } from '../../aipm/host';
import type { AipmProgress, EvidenceRefV2, StepId } from '../../aipm/types';
import { STEP_IDS } from '../../aipm/types';
import { copy } from './copy';
import { sendQuote, Worksheet, type WorksheetHost } from './worksheet';

/** The material view's "quote to worksheet": the open sheet inserts it at the caret. */
export function quoteToWorksheet(ref: EvidenceRefV2, label: string) {
  sendQuote(ref, label);
}

function CurrentSheet({ host }: { host: WorksheetHost }) {
  const sheet = host.currentScreen?.().sheet ?? '';
  if ((STEP_IDS as readonly string[]).includes(sheet))
    return <Worksheet key={sheet} host={host} step={sheet as StepId} />;
  // A free sheet is an ordinary work item; it is written and linked in the work area.
  const c = copy(host.getSessionContext()?.workLanguage === 'en' ? 'en' : 'zh');
  const id = sheet.startsWith('free:') ? sheet.slice(5) : '';
  return (
    <section className="aipm-sheet">
      <p className="aipm-sheet__muted">
        {c.t(
          '自由纸在作品区里写，可以关联到某一个点。',
          'A free sheet is written in the work area and can be linked to a point.',
        )}
      </p>
      {id && (
        <button
          type="button"
          className="btn primary"
          onClick={() =>
            void host.openWork({
              session_id: host.getSessionContext()?.sessionId ?? '',
              kind: 'product',
              object_id: id,
              version: 0,
            })
          }
        >
          {c.t('打开这份作品', 'Open this work item')}
        </button>
      )}
    </section>
  );
}

export function installAipmWorksheet(host: WorksheetHost) {
  return host.registerFeature('worksheet' as AipmFeatureId, {
    render: () => '<div class="aipm-worksheet-root"></div>',
    mount(root) {
      const react = createRoot(root);
      react.render(<CurrentSheet host={host} />);
      return () => react.unmount();
    },
  });
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

/** Phase-1 slot, kept as L1's fallback: shows the focus step's sheet. */
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
