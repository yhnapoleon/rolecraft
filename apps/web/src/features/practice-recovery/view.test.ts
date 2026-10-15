import { describe, expect, it, type Mock, vi } from 'vitest';
import { ApiError } from '../../api';
import { setPreference } from '../../app/i18n';
import type { ContinueCodeIssued } from '../../contracts-v2';
import { createPracticeRecovery, type RecoveryHost } from './view';

const CODE = '7K3QM9XRPD2WTHC6NJAF';
const SHOWN = '7K3Q-M9XR-PD2W-THC6-NJAF';
const attempt = { id: 's1' };

type Live = RecoveryHost['live'];
type Fakes = { [K in keyof Live]: Mock<Live[K]> };

function host(overrides: Partial<Fakes> = {}) {
  const sheets: { title: string; body: string; foot: string }[] = [];
  const closing: ((dialog: {
    querySelector(selector: string): { remove(): void } | null;
  }) => void)[] = [];
  const notes: string[] = [];
  const entered: unknown[] = [];
  const shown: string[] = [];
  let id = 0;
  const live: Fakes = {
    recover: vi.fn<Live['recover']>(async () => ({ attempt, held: false })),
    continueCode: vi.fn<Live['continueCode']>(async () => ({ exists: false })),
    replaceContinueCode: vi.fn<Live['replaceContinueCode']>(
      async (_attempt, expected): Promise<ContinueCodeIssued> => ({
        code: SHOWN,
        generation: expected + 1,
        created_at: '2026-10-14T07:02:00Z',
      }),
    ),
    ...overrides,
  };
  const value: RecoveryHost = {
    live,
    button: (label, action, cls = '', attrs = '') =>
      `<button class="btn ${cls}" data-action="${action}" ${attrs}>${label}</button>`,
    icon: (name) => `<i data-icon="${name}"></i>`,
    openSheet: (title, body, foot = '') => {
      sheets.push({ title, body, foot });
    },
    onSheetClose: (done) => {
      closing.push(done);
    },
    notify: (message) => {
      notes.push(message);
    },
    render: () => {},
    enter: async (opened, held) => {
      entered.push([opened, held]);
    },
    showEntry: (focus) => {
      shown.push(focus);
    },
    requestId: () => {
      id += 1;
      return `request-${id}`;
    },
  };
  return { value, live, sheets, closing, notes, entered, shown };
}

describe('opening a practice from the job page with its code', () => {
  it('turns a typed code into the practice and says what stays behind', async () => {
    const h = host();
    const recovery = createPracticeRecovery(h.value);

    await recovery.submit('7k3q m9xr pd2w thc6 njaf');

    expect(h.live.recover).toHaveBeenCalledWith(CODE, 'request-1');
    expect(h.entered).toEqual([[attempt, false]]);
    expect(h.notes).toEqual(['已找回。只在原浏览器里的草稿、测试归属和笔记不会跟过来。']);
    expect(recovery.entry()).not.toContain('value="7k3q');
    expect(recovery.entry()).not.toMatch(/<details[^>]* open/);
  });

  it('only switches to a practice this browser already holds, and says so', async () => {
    const h = host({
      recover: vi.fn<Live['recover']>(async () => ({ attempt, held: true })),
    });
    const recovery = createPracticeRecovery(h.value);

    await recovery.submit(SHOWN);

    expect(h.entered).toEqual([[attempt, true]]);
    expect(h.notes).toEqual(['这是你在本机的练习，已切换过去。']);
  });

  it('refuses text that cannot be a code without asking the server', async () => {
    const h = host();
    const recovery = createPracticeRecovery(h.value);

    await recovery.submit('7K3Q-M9XR');

    expect(h.live.recover).not.toHaveBeenCalled();
    expect(recovery.entry()).toContain('继续码是 20 位字母和数字。');
    expect(recovery.entry()).toContain('role="alert"');
  });

  it('retries an unconfirmed result as the same request, and a new code as a new one', async () => {
    const lost = new ApiError('timeout', 0);
    const h = host({
      recover: vi
        .fn<Live['recover']>()
        .mockRejectedValueOnce(lost)
        .mockResolvedValue({ attempt, held: false }),
    });
    const recovery = createPracticeRecovery(h.value);

    await recovery.submit(SHOWN);
    expect(recovery.entry()).toContain('结果没确认。再点一次「找回」，不会多开一份。');
    await recovery.submit(CODE.toLowerCase());
    await recovery.submit('0011ABCDEFGHJKMNPQRS');

    expect(h.live.recover.mock.calls).toEqual([
      [CODE, 'request-1'],
      [CODE, 'request-1'],
      ['0011ABCDEFGHJKMNPQRS', 'request-2'],
    ]);
  });

  it.each([
    [
      'continue_code_invalid',
      new ApiError('x', 404, 'continue_code_invalid'),
      '这个继续码不对，或已经换过新码。',
    ],
    [
      'continue_code_rate_limited',
      new ApiError('x', 429, 'continue_code_rate_limited', { retry_after_seconds: 840 }),
      '试得太多了，请 14 分钟后再试。',
    ],
    [
      'credential_derivation_unavailable',
      new ApiError('x', 503, 'credential_derivation_unavailable'),
      '这台服务器现在不能用继续码。',
    ],
    [
      'continue_code_scenario_unavailable',
      new ApiError('x', 409, 'continue_code_scenario_unavailable'),
      '这个练习的情境在这里打不开。',
    ],
  ])('says %s as one short sentence', async (_code, error, sentence) => {
    const h = host({ recover: vi.fn<Live['recover']>().mockRejectedValue(error) });
    const recovery = createPracticeRecovery(h.value);

    await recovery.submit(SHOWN);

    expect(recovery.entry()).toContain(sentence);
    expect(recovery.entry()).not.toContain('continue_code');
  });

  it('opens the job page entry ready to type from the home page link', () => {
    const h = host();
    const recovery = createPracticeRecovery(h.value);
    expect(recovery.homeLink()).toContain('data-action="continue-code-home"');

    recovery.reveal();

    expect(h.shown).toEqual(['continue-code-input']);
    expect(recovery.entry()).toMatch(/<details[^>]* open/);
  });

  it('names when a practice was opened here, not a start time it does not know', () => {
    const recovery = createPracticeRecovery(host().value);
    const started = new Date(Date.now() - 2 * 60000).toISOString();
    expect(recovery.since(started, {})).toBe('，开始于 2 分钟前');
    expect(recovery.since(started, { recovered: new Date().toISOString() })).toBe('，找回于 刚刚');
    setPreference('en');
    try {
      expect(recovery.since(started, { recovered: new Date().toISOString() })).toBe(
        ', restored just now',
      );
    } finally {
      setPreference('zh');
    }
  });
});

describe('the continue code of an open practice', () => {
  it('is created on request, shown once and taken off the page when the dialog closes', async () => {
    const h = host();
    const recovery = createPracticeRecovery(h.value);

    await recovery.open(attempt);
    expect(h.sheets[0].title).toBe('在别的设备继续');
    expect(h.sheets[0].foot).toContain('data-action="continue-code-create"');
    expect(h.sheets[0].body).toContain('只显示一次，拿到它的人都能打开这次练习。');
    await recovery.create();

    expect(h.live.replaceContinueCode).toHaveBeenCalledWith(attempt, 0);
    expect(h.sheets[1].body).toContain(SHOWN);
    expect(h.sheets[1].body).toContain('现在记下它，关掉后不会再显示。');
    const remove = vi.fn();
    for (const done of h.closing) done({ querySelector: () => ({ remove }) });
    expect(remove).toHaveBeenCalled();
    const clipboard = vi.fn();
    vi.stubGlobal('navigator', { clipboard: { writeText: clipboard } });
    await recovery.copy();
    expect(clipboard).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it('says on which day and time an existing code was made, and replacing it names that generation', async () => {
    // Made at local 15:02 and read two minutes later: still a date and time, not "2 minutes ago".
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date(2026, 9, 14, 15, 4));
    const made = new Date(2026, 9, 14, 15, 2).toISOString();
    const h = host({
      continueCode: vi.fn<Live['continueCode']>(async () => ({
        exists: true,
        generation: 2,
        created_at: made,
      })),
    });
    const recovery = createPracticeRecovery(h.value);

    await recovery.open(attempt);
    expect(h.sheets[0].body).toContain('已有继续码，生成于 10月14日 15:02。');
    setPreference('en');
    try {
      await recovery.open(attempt);
      expect(h.sheets[1].body).toContain('A code was created on Oct 14 15:02.');
    } finally {
      setPreference('zh');
      vi.useRealTimers();
    }
    expect(h.sheets[0].body).not.toContain(SHOWN);
    // Enter must not replace a code someone may still rely on: Close takes the focus.
    expect(h.sheets[0].foot).toMatch(/data-action="close"[^>]*autofocus/);
    await recovery.create();

    expect(h.live.replaceContinueCode).toHaveBeenCalledWith(attempt, 2);
  });

  it('reports a replacement made elsewhere and shows the current state', async () => {
    const h = host({
      replaceContinueCode: vi
        .fn<Live['replaceContinueCode']>()
        .mockRejectedValue(new ApiError('x', 409, 'continue_code_changed')),
    });
    const recovery = createPracticeRecovery(h.value);
    await recovery.open(attempt);
    h.live.continueCode.mockResolvedValue({
      exists: true,
      generation: 1,
      created_at: new Date().toISOString(),
    });

    await recovery.create();

    expect(h.sheets.at(-1)?.body).toContain('继续码刚在别处换过。');
    expect(h.sheets.at(-1)?.body).toContain('已有继续码');
  });

  it('creates one code for two quick presses', async () => {
    const h = host();
    const recovery = createPracticeRecovery(h.value);
    await recovery.open(attempt);

    await Promise.all([recovery.create(), recovery.create()]);

    expect(h.live.replaceContinueCode).toHaveBeenCalledTimes(1);
  });
});
