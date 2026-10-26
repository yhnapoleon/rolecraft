import type { AipmScreen } from '../../aipm/host';
import { IDS, type StepId } from './model';

/** Same hash route, session-scoped screen data. Never restore another practice's paper. */
export function screenFromHistory(value: unknown, session: string): AipmScreen {
  const state = value as { aipmSession?: string; aipm?: AipmScreen } | null;
  const screen = state?.aipm;
  if (state?.aipmSession !== session || !screen) return { kind: 'workbench' };
  if (
    screen.kind === 'worksheet' &&
    typeof screen.sheet === 'string' &&
    (IDS.includes(screen.sheet as StepId) || screen.sheet.startsWith('free:'))
  ) {
    return {
      kind: 'worksheet',
      sheet: screen.sheet,
      ...(typeof screen.material === 'string' ? { material: screen.material } : {}),
    };
  }
  if (screen.kind === 'review' && IDS.includes(screen.step)) {
    const ref = screen.reviewRef;
    return {
      kind: 'review',
      step: screen.step,
      ...(ref?.session_id === session &&
      typeof ref.object_id === 'string' &&
      Number.isSafeInteger(ref.version) &&
      ref.version > 0
        ? { reviewRef: ref }
        : {}),
    };
  }
  return { kind: 'workbench' };
}
