import { describe, it, expect } from 'vitest';
import { ApiError } from '../../api';
import { afterPracticeRead } from './practice-read';

const shown = { state: 'ready', submissionId: 'sub', options: [{ id: 'urgent-zh' }] };
const loading = { state: 'loading' };
const dropped = { error: new ApiError('The result is unconfirmed.', 0, 'response_unconfirmed') };
const refused = { error: new ApiError('Forbidden', 403, 'token_invalid') };
const unavailable = { error: 'unavailable', sealed: false };

describe('optional practice column after a read', () => {
  it('a dropped read keeps the shown choices and asks again', () => {
    expect(afterPracticeRead(shown, dropped, 0, false)).toEqual({
      view: shown,
      dropsInARow: 1,
      readAgain: true,
    });
  });
  it('stops asking after three more dropped reads in a row and still keeps the choices', () => {
    expect(afterPracticeRead(shown, dropped, 2, false).readAgain).toBe(true);
    expect(afterPracticeRead(shown, dropped, 3, false)).toEqual({
      view: shown,
      dropsInARow: 0,
      readAgain: false,
    });
  });
  it('an empty column says the practice is unavailable once drops keep coming', () => {
    expect(afterPracticeRead(loading, dropped, 0, false).view).toEqual(loading);
    expect(afterPracticeRead(loading, dropped, 3, false).view).toEqual(unavailable);
  });
  it('a refused read shows the unavailable notice at once', () => {
    expect(afterPracticeRead(shown, refused, 1, true)).toEqual({
      view: { error: 'unavailable', sealed: true },
      dropsInARow: 0,
      readAgain: false,
    });
  });
  it('a read result replaces what is shown and starts the count again', () => {
    const next = { state: 'feedback_pending', submissionId: 'sub-2' };
    expect(afterPracticeRead(shown, { view: next }, 2, false)).toEqual({
      view: next,
      dropsInARow: 0,
      readAgain: false,
    });
  });
});
