import { describe, expect, it, vi } from 'vitest';
import type { ObjectRef } from '../../aipm/types';
import { sheetDraftKey, sheetNames, unsavedSheets } from './unsaved';

/** FAKE DATA for unit tests only. */
const prd = (version: number): ObjectRef => ({ session_id: 's', kind: 'product', object_id: 'prd', version });
const paragraph = (text: string) => ({ blocks: [{ id: 'b', type: 'p' as const, text }], choice: '' });
function data(drafts: Record<string, unknown>, sections: Record<string, string>) {
  return {
    draft: vi.fn((_slot: string, key: string) => drafts[key]) as never,
    query: vi.fn(async () => ({
      items: [
        { version: 1, structured_payload: { type: 'plan', sections: {} } },
        { version: 2, structured_payload: { type: 'plan', sections } },
      ],
    })) as never,
  };
}

describe('unsaved worksheet text before delivery (QA G-13)', () => {
  it('names a sheet whose text is not in the version being submitted', async () => {
    const host = data(
      { [sheetDraftKey('decision')]: paragraph('Proceed narrowly from day 7.'), [sheetDraftKey('need')]: paragraph('Saved words.') },
      { need: 'Saved words.' },
    );
    const steps = await unsavedSheets(host, [prd(2)]);
    expect(steps).toEqual(['decision']);
    expect(sheetNames(steps, 'en')).toBe('⑦ Launch decision');
    expect(sheetNames(['need', 'decision'], 'zh')).toBe('③ 验证真需求、⑦ 上线决策');
  });

  it('says nothing, and reads nothing, when no sheet keeps unsaved text', async () => {
    const host = data({ [sheetDraftKey('decision')]: paragraph('   ') }, {});
    expect(await unsavedSheets(host, [prd(2)])).toEqual([]);
    expect(host.query).not.toHaveBeenCalled();
  });

  it('counts every unsaved sheet when no PRD is among the chosen versions', async () => {
    const host = {
      draft: vi.fn((_slot: string, key: string) =>
        key === sheetDraftKey('boundary') ? paragraph('Only explain.') : undefined,
      ) as never,
      query: vi.fn(async () => ({ items: [{ version: 1, structured_payload: { type: 'test_plan' } }] })) as never,
    };
    expect(await unsavedSheets(host, [{ ...prd(1), object_id: 'plan' }])).toEqual(['boundary']);
  });
});
