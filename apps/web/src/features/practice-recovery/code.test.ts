import { describe, expect, it } from 'vitest';
import { continueCodeDraft, groupContinueCode, normalizeContinueCode } from './code';

// The same examples as the server's tests/unit/test_continue_codes.py.
const CODE = '7K3QM9XRPD2WTHC6NJAF';

describe('what a person may type as a continue code', () => {
  it.each([
    '7K3Q-M9XR-PD2W-THC6-NJAF',
    '7k3q m9xr pd2w thc6 njaf',
    '  7K3Q–M9XR—PD2W−THC6‐NJAF  ',
    '７Ｋ３Ｑ－Ｍ９ＸＲ－PD2W　THC6NJAF',
  ])('reads %j as the same code', (typed) => {
    expect(normalizeContinueCode(typed)).toBe(CODE);
  });

  it('reads O as zero and I or L as one', () => {
    expect(normalizeContinueCode('OoIl-ABCD-EFGH-JKMN-PQRS')).toBe('0011ABCDEFGHJKMNPQRS');
  });

  it.each([
    '',
    '7K3Q-M9XR-PD2W-THC6-NJA',
    '7K3Q-M9XR-PD2W-THC6-NJAFX',
    '7K3Q-M9XR-PD2W-THC6-NJAU',
    '7K3Q_M9XR_PD2W_THC6_NJAF',
    '继续码7K3QM9XRPD2WTHC6NJAF',
  ])('refuses %j', (typed) => {
    expect(normalizeContinueCode(typed)).toBeNull();
  });

  it('shows a code in five groups of four', () => {
    expect(groupContinueCode(CODE)).toBe('7K3Q-M9XR-PD2W-THC6-NJAF');
  });

  it('keeps only half-width letters, digits, spaces and dashes in the field between renders', () => {
    expect(continueCodeDraft('７Ｋ３Ｑ－m9xr <b>"x"</b>')).toBe('7K3Q-m9xr bxb');
  });
});
