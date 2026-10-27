/** Worksheet text kept in this browser that the version about to be delivered does not contain.
 * The delivery panel warns with it: submitting locks saved versions only, and an unsaved sheet
 * would otherwise go missing from the delivery without a word (QA G-13). Reads only. */
import { STEP_IDS, type ObjectRef, type StepId } from '../../aipm/types';
import type { V4HostAdapter } from '../../v4-host';
import { copy } from './copy';
import type { Language } from './model';
import { type SheetDraft, toText } from './sheet-model';

/** The key the worksheet keeps its unsaved draft under (cleared once a version is saved). */
export const sheetDraftKey = (step: StepId) => `aipm-sheet:${step}`;

const GLYPH = ['①', '②', '③', '④', '⑤', '⑥', '⑦'];
type Data = Pick<V4HostAdapter, 'draft' | 'query'>;
type Version = { version: number; structured_payload?: unknown };

/** Sheets with unsaved text that differs from the PRD version among `products`; with no PRD
 * among them, every sheet with unsaved text. */
export async function unsavedSheets(data: Data, products: readonly ObjectRef[]): Promise<StepId[]> {
  const kept = STEP_IDS.flatMap((step) => {
    const draft = data.draft<SheetDraft>('workspace', sheetDraftKey(step));
    const text = draft?.blocks?.length ? toText(draft.blocks).trim() : '';
    return text ? [{ step, text }] : [];
  });
  if (!kept.length) return [];
  let sections: Partial<Record<StepId, string>> | null = null;
  for (const ref of products) {
    const page = (await data.query('work_products.versions.list', {
      product_id: ref.object_id,
      limit: 100,
    })) as { items?: Version[] };
    const payload = page.items?.find((v) => v.version === ref.version)?.structured_payload as
      | { sections?: Partial<Record<StepId, string>> }
      | undefined;
    if (payload?.sections) {
      sections = payload.sections;
      break;
    }
  }
  return kept
    .filter(({ step, text }) => !sections || String(sections[step] ?? '').trim() !== text)
    .map(({ step }) => step);
}

/** "③ Validate the need, ⑦ Launch decision" in the work language. */
export function sheetNames(steps: readonly StepId[], language: Language) {
  const c = copy(language);
  return steps
    .map((step) => `${GLYPH[STEP_IDS.indexOf(step)]} ${c.section(step)}`)
    .join(language === 'zh' ? '、' : ', ');
}
