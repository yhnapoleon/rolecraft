/**
 * Continue codes on screen: the ⋯ dialog of an open practice and the entry on the job page.
 * A code exists only in the dialog that shows it once and in the field a person types it into;
 * neither keeps it. Every string rendered here is fixed text, a code or a typed draft limited to
 * letters, digits, spaces and dashes, so nothing needs escaping.
 */
import { ApiError } from '../../api';
import { T, when } from '../../app/i18n';
import type { ContinueCodeIssued, ContinueCodeStatus } from '../../contracts-v2';
import type { LocalSession } from '../../types';
import { continueCodeDraft, normalizeContinueCode } from './code';
import './continue-code.css';

export type RecoveryAttempt = { id: string };
type Dialog = { querySelector(selector: string): { remove(): void } | null };

export interface RecoveryHost {
  live: {
    recover(code: string, requestId: string): Promise<RecoveryAttempt>;
    continueCode(attempt: RecoveryAttempt): Promise<ContinueCodeStatus>;
    replaceContinueCode(attempt: RecoveryAttempt, expected: number): Promise<ContinueCodeIssued>;
  };
  button(label: string, action: string, cls?: string, attrs?: string): string;
  icon(name: string, cls?: string): string;
  openSheet(title: string, body: string, foot?: string, cls?: string): void;
  /** Called once when the open dialog closes, with that dialog. */
  onSheetClose(done: (dialog: Dialog) => void): void;
  notify(message: string): void;
  render(): void;
  /** Takes the person to the opened practice's board. */
  enter(attempt: RecoveryAttempt): Promise<void>;
  /** Shows the job page with the field of this id focused. */
  showEntry(focus: string): void;
  requestId?: () => string;
}

type Shown = {
  attempt: RecoveryAttempt;
  status: ContinueCodeStatus;
  issued: ContinueCodeIssued | null;
  notice: string;
};

const INPUT = 'continue-code-input';
const VALUE = 'data-continue-code-value';

/** Server refusals of a typed code, as one short sentence each. */
function entryFailure(error: unknown) {
  const code = error instanceof ApiError ? error.code : undefined;
  if (code === 'continue_code_malformed')
    return T('继续码是 20 位字母和数字。', 'A continue code has 20 letters and digits.');
  if (code === 'continue_code_invalid')
    return T('这个继续码不对，或已经换过新码。', 'This code is wrong or has been replaced.');
  if (code === 'continue_code_rate_limited' && error instanceof ApiError) {
    const minutes = Math.max(1, Math.ceil(Number(error.details?.retry_after_seconds) / 60) || 1);
    return T(
      `试得太多了，请 ${minutes} 分钟后再试。`,
      `Too many tries. Try again in ${minutes} min.`,
    );
  }
  if (code === 'credential_derivation_unavailable')
    return T('这台服务器现在不能用继续码。', 'Continue codes are not available on this server.');
  if (code === 'continue_code_scenario_unavailable')
    return T('这个练习的情境在这里打不开。', 'This practice’s situation is not available here.');
  if (code === 'storage_unavailable')
    return T(
      '这个浏览器现在存不下练习，腾出存储空间后再试。',
      'This browser cannot save the practice now. Free up storage and try again.',
    );
  if (code === 'recovered_unreadable')
    return T(
      '练习已加入「我的练习」，但现在读不到内容，稍后在那里打开。',
      'The practice is in My practice, but its records cannot be read yet. Open it there later.',
    );
  if (error instanceof ApiError && error.status === 0 && !code)
    return T(
      '结果没确认。再点一次「找回」，不会多开一份。',
      'Not confirmed. Press Continue again; it won’t open a second copy.',
    );
  return T('没能找回，请稍后再试。', 'Couldn’t open it. Try again later.');
}

function dialogFailure(error: unknown) {
  const code = error instanceof ApiError ? error.code : undefined;
  if (code === 'credential_derivation_unavailable')
    return T('这台服务器现在不能用继续码。', 'Continue codes are not available on this server.');
  if (error instanceof ApiError && error.status === 0 && !code)
    return T(
      '结果没确认。关掉再打开，看看是否已经生成。',
      'Not confirmed. Close and reopen this to see whether a code was created.',
    );
  return T('没能生成继续码，请稍后再试。', 'Couldn’t create a code. Try again later.');
}

export function createPracticeRecovery(host: RecoveryHost) {
  const newRequestId = host.requestId ?? (() => crypto.randomUUID());
  const entry = { open: false, text: '', error: '', busy: false, code: '', requestId: '' };
  let shown: Shown | null = null;
  let creating = false;

  function show(view: Shown) {
    shown = view;
    const lines = view.notice
      ? [
          `<p class="warn-line" role="status">${host.icon('warn', 'i-sm')}<span class="grow">${view.notice}</span></p>`,
        ]
      : [];
    let foot: string;
    if (view.issued) {
      lines.push(
        `<p class="continue-code" ${VALUE}>${view.issued.code}</p>`,
        `<p>${T('现在记下它，关掉后不会再显示。', 'Save it now; it won’t be shown again.')}</p>`,
      );
      foot =
        host.button(T('复制', 'Copy'), 'continue-code-copy', 'quiet') +
        host.button(T('记下了', 'Done'), 'close', 'primary');
    } else if (view.status.exists) {
      const made = when(view.status.created_at);
      lines.push(
        `<p>${T(`已有继续码，生成于 ${made}。`, `A code was created ${made}.`)}</p>`,
        `<p class="meta">${T(
          '找不到了就换一个：旧码立即失效，已经打开过的浏览器不受影响。',
          'Lost it? Replace it: the old code stops working at once; browsers already opened with it keep working.',
        )}</p>`,
      );
      // Enter must not replace a code someone may still rely on.
      foot =
        host.button(T('关闭', 'Close'), 'close', 'quiet', 'autofocus') +
        host.button(T('换一个新码', 'Replace code'), 'continue-code-create', 'primary');
    } else {
      lines.push(
        `<p>${T(
          '在另一台设备的「AI 产品经理」页输入继续码，就能回到这次练习，作品、测试、对话和反馈都在。',
          'Enter the code on the AI Product Manager page of another device to come back to this practice, with your work, tests, conversations and feedback.',
        )}</p>`,
        `<p class="meta">${T('只显示一次，拿到它的人都能打开这次练习。', 'Shown once. Anyone who has it can open this practice.')}</p>`,
      );
      foot = host.button(T('生成继续码', 'Create code'), 'continue-code-create', 'primary');
    }
    host.openSheet(
      T('在别的设备继续', 'Continue on another device'),
      `<div class="prose continue-sheet">${lines.join('')}</div>`,
      foot,
      'narrow',
    );
    if (view.issued)
      host.onSheetClose((dialog) => {
        dialog.querySelector(`[${VALUE}]`)?.remove();
        if (shown?.issued) shown = { ...shown, issued: null };
      });
  }

  return {
    /** The job page block. */
    entry() {
      const open = entry.open || entry.busy || Boolean(entry.error);
      const invalid = entry.error
        ? ' aria-invalid="true" aria-describedby="continue-code-error"'
        : '';
      return `<section class="block"><details class="intake continue-entry" data-continue-code${open ? ' open' : ''}>
        <summary><span class="section-title">${T('用继续码找回练习', 'Continue with a code')}</span>${host.icon('down', 'i-sm chev')}</summary>
        <form data-form="continue-code" class="intake-form" novalidate>
          <p class="meta">${T('继续码在原练习右上角 ⋯ 里。', 'Find it under ⋯ at the top right of the practice.')}</p>
          <label class="sr-only" for="${INPUT}">${T('继续码', 'Continue code')}</label>
          <input id="${INPUT}" class="input continue-code-input" name="code" value="${entry.text}" placeholder="XXXX-XXXX-XXXX-XXXX-XXXX" maxlength="64" autocomplete="off" autocapitalize="characters" spellcheck="false"${invalid}>
          <div class="row-actions"><button type="submit" class="btn primary"${entry.busy ? ' disabled' : ''}>${T('找回', 'Continue')}</button></div>
          ${entry.error ? `<p id="continue-code-error" class="warn-line" role="alert">${host.icon('warn', 'i-sm')}<span class="grow">${entry.error}</span></p>` : ''}
        </form>
      </details></section>`;
    },
    homeLink() {
      return `<p class="continue-link"><button type="button" class="link quiet" data-action="continue-code-home">${T('有继续码？', 'Have a continue code?')}</button></p>`;
    },
    reveal() {
      entry.open = true;
      host.showEntry(INPUT);
    },
    menuLabel: () => T('继续码…', 'Continue code…'),
    /** The start, or for a practice opened here with its code, when it was opened. */
    since(
      createdAt: string | undefined,
      session: Pick<LocalSession, 'recovered'> | null | undefined,
    ) {
      const comma = T('，', ', ');
      if (session?.recovered)
        return `${comma}${T('找回于 ', 'restored ')}${when(session.recovered)}`;
      return createdAt ? `${comma}${T('开始于 ', 'started ')}${when(createdAt)}` : '';
    },
    input(value: string) {
      entry.text = continueCodeDraft(value);
    },
    toggle(open: boolean) {
      entry.open = open;
    },
    async submit(typed: string) {
      if (entry.busy) return;
      entry.text = continueCodeDraft(typed);
      const code = normalizeContinueCode(typed);
      if (!code) {
        entry.error = entryFailure(new ApiError('', 422, 'continue_code_malformed'));
        host.render();
        return;
      }
      // The same code keeps its request, so an unconfirmed result never opens a second copy.
      if (entry.code !== code) Object.assign(entry, { code, requestId: newRequestId() });
      Object.assign(entry, { busy: true, error: '' });
      host.render();
      try {
        const attempt = await host.live.recover(code, entry.requestId);
        Object.assign(entry, { open: false, text: '', code: '', requestId: '', busy: false });
        await host.enter(attempt);
        host.notify(
          T(
            '已找回。只在原浏览器里的草稿、测试归属和笔记不会跟过来。',
            'Restored. Drafts, test filing and notes kept only in the other browser stay there.',
          ),
        );
      } catch (error) {
        Object.assign(entry, { busy: false, open: true, error: entryFailure(error) });
        host.render();
      }
    },
    /** The ⋯ dialog for this practice. */
    async open(attempt: RecoveryAttempt) {
      show({ attempt, status: await host.live.continueCode(attempt), issued: null, notice: '' });
    },
    async create() {
      const view = shown;
      if (!view || creating) return;
      creating = true;
      try {
        const issued = await host.live.replaceContinueCode(
          view.attempt,
          view.status.generation ?? 0,
        );
        const status = {
          exists: true,
          generation: issued.generation,
          created_at: issued.created_at,
        };
        show({ attempt: view.attempt, status, issued, notice: '' });
      } catch (error) {
        if (error instanceof ApiError && error.code === 'continue_code_changed') {
          const status = await host.live.continueCode(view.attempt);
          show({
            attempt: view.attempt,
            status,
            issued: null,
            notice: T('继续码刚在别处换过。', 'The code was just replaced elsewhere.'),
          });
        } else show({ ...view, issued: null, notice: dialogFailure(error) });
      } finally {
        creating = false;
      }
    },
    async copy() {
      const code = shown?.issued?.code;
      if (!code) return;
      try {
        await navigator.clipboard.writeText(code);
        host.notify(T('已复制', 'Copied'));
      } catch {
        host.notify(
          T('浏览器没让复制，请手动抄下。', 'The browser blocked copying; write it down instead.'),
        );
      }
    },
  };
}
