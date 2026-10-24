// S9 · The engineering review on the product manager's side (plan §13.11): a report sheet that
// slides in from the right over the main screen, and "Update pilot settings from this review",
// which confirms in a dialog and sends the existing configuration.apply. The engineer never applies
// anything; the product manager decides. A delivered practice first opens a revision.
import { Dialog } from 'radix-ui';
import { useRef } from 'react';
import { T } from '../../app/i18n';
import { Button, Sheet, SheetContent, SheetDescription, SheetTitle } from '../../ui-kit';
import type { HandBackRow } from './hand-back';
import type { DiffRow } from './model';

export interface HandBackView {
  readonly open: boolean;
  readonly loading: boolean;
  readonly error: string;
  readonly signedAt: string;
  /** The signed draft came from the engineer's agent. */
  readonly fromAgent: boolean;
  /** Everything holds (the mark is green only then). */
  readonly clean: boolean;
  /** What the review came to: the report headline's sentence. */
  readonly title: string;
  /** What comes with updating from a review that is not clean ('' when clean). */
  readonly caution: string;
  readonly newFailures: number;
  readonly fixed: number;
  readonly publicPassed: number;
  readonly publicTotal: number;
  readonly hidden: number;
  readonly diff: readonly DiffRow[];
  /** Settings that differ from the pilot now; null until read. */
  readonly rows: readonly HandBackRow[] | null;
  readonly fromVersion: number | null;
  readonly submitted: boolean;
  readonly confirm: boolean;
  readonly applying: boolean;
  readonly applyError: string;
  /** The pilot changed meanwhile: read it again before confirming. */
  readonly conflict: boolean;
  readonly reloading: boolean;
  readonly appliedVersion: number | null;
  onOpenChange(open: boolean): void;
  onConfirmChange(open: boolean): void;
  onApply(): void;
  onReload(): void;
  onRetry(): void;
}

const Mark = ({ clean }: { clean: boolean }) => (
  <span
    aria-hidden="true"
    className={
      clean
        ? 'tw:grid tw:place-items-center tw:size-9 tw:rounded-full tw:border-[1.5px] tw:border-good tw:bg-good-tint tw:text-good tw:text-[16px]'
        : 'tw:grid tw:place-items-center tw:size-9 tw:rounded-full tw:border-[1.5px] tw:border-warn tw:text-warn tw:text-[16px]'
    }
  >
    {clean ? '✓' : '↓'}
  </span>
);

function Diff({ rows }: { rows: readonly { name: string; before: string; after: string }[] }) {
  return (
    <ul className="tw:m-0 tw:p-0 tw:list-none tw:grid tw:gap-1.5">
      {rows.map((r) => (
        <li
          key={r.name}
          className="tw:flex tw:flex-wrap tw:items-baseline tw:gap-x-3 tw:text-[13.5px]"
        >
          <span className="tw:text-ink-2 tw:min-w-[9rem]">{r.name}</span>
          <span className="tw:inline-flex tw:items-baseline tw:gap-1.5">
            <del className="tw:text-ink-3">{r.before}</del>
            <span aria-hidden="true" className="tw:text-ink-4">
              →
            </span>
            <b className="tw:text-ink tw:font-semibold">{r.after}</b>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function HandBackSheet(v: HandBackView) {
  const trigger = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const nextVersion = (v.fromVersion ?? 1) + 1;
  const title = v.title;
  const nothing = v.rows !== null && v.rows.length === 0;
  return (
    <Sheet open={v.open} onOpenChange={v.onOpenChange}>
      <SheetContent side="right" className="tw:w-[min(640px,100%)] tw:overflow-y-auto">
        <div className="tw:grid tw:gap-6 tw:p-8 tw:max-sm:p-5">
          <header className="tw:grid tw:gap-1">
            <SheetDescription className="tw:m-0 tw:text-[12px] tw:text-ink-3">
              {T(
                `工程复核报告 · 签字人：你（工程师）${v.fromAgent ? ' · 草稿来自你的 Agent' : ''} · ${v.signedAt}`,
                `Engineering review · signed by you (engineer)${v.fromAgent ? ' · draft from your agent' : ''} · ${v.signedAt}`,
              )}
            </SheetDescription>
            <div className="tw:flex tw:items-start tw:gap-3.5 tw:mt-2">
              <Mark clean={v.clean} />
              <SheetTitle className="tw:m-0 tw:font-sans tw:text-[22px] tw:leading-tight tw:font-semibold">
                {title}
              </SheetTitle>
            </div>
          </header>
          {v.loading ? (
            <p className="tw:m-0 tw:text-ink-3">{T('正在读取复核…', 'Reading the review…')}</p>
          ) : v.error ? (
            <div className="tw:flex tw:items-center tw:gap-3">
              <p className="tw:m-0 tw:text-bad tw:text-[13px]">{v.error}</p>
              <Button variant="ghost" onClick={v.onRetry}>
                {T('重试', 'Try again')}
              </Button>
            </div>
          ) : (
            <>
              <section className="tw:grid tw:gap-2">
                <h3 className="tw:m-0 tw:text-[12.5px] tw:font-semibold tw:text-ink-2">
                  {T('改动', 'The change')}
                </h3>
                <Diff rows={v.diff} />
              </section>
              <p className="tw:m-0 tw:flex tw:flex-wrap tw:gap-x-5 tw:gap-y-1 tw:text-[13px] tw:text-ink-2 tw:tabular-nums">
                <span>
                  {T(
                    `公开 ${v.publicPassed}/${v.publicTotal} 通过`,
                    `Public ${v.publicPassed}/${v.publicTotal} passed`,
                  )}
                </span>
                <span>
                  {T(
                    `隐藏 ${v.hidden} 条：新增失败 ${v.newFailures} · 另修好 ${v.fixed}`,
                    `Hidden ${v.hidden}: ${v.newFailures} new failures · ${v.fixed} also fixed`,
                  )}
                </span>
              </p>
              <footer className="tw:flex tw:flex-wrap tw:items-center tw:gap-2 tw:pt-2 tw:border-0 tw:border-t tw:border-solid tw:border-line">
                {v.appliedVersion !== null ? (
                  <p className="tw:m-0 tw:text-good tw:text-[14px] tw:font-medium">
                    ✓{' '}
                    {T(
                      `已按这份改动更新试点 · 配置 v${v.appliedVersion}`,
                      `Pilot updated from this review · configuration v${v.appliedVersion}`,
                    )}
                  </p>
                ) : (
                  <>
                    <Button
                      ref={trigger}
                      variant="primary"
                      disabled={v.rows === null || nothing}
                      reason={
                        nothing
                          ? T('试点已经是这组设置', 'The pilot already has these settings')
                          : undefined
                      }
                      onClick={() => v.onConfirmChange(true)}
                    >
                      {T('按这份改动更新试点设置', 'Update pilot settings from this review')}
                    </Button>
                    <Button variant="ghost" onClick={() => v.onOpenChange(false)}>
                      {T('先不更新', 'Not now')}
                    </Button>
                  </>
                )}
              </footer>
            </>
          )}
        </div>
      </SheetContent>
      <Dialog.Root open={v.confirm} onOpenChange={(open) => !v.applying && v.onConfirmChange(open)}>
        <Dialog.Portal>
          <Dialog.Overlay className="rc-portal rc-sheet-scrim tw:fixed tw:inset-0 tw:z-[90] tw:bg-[var(--dim)]" />
          <Dialog.Content
            // Opening reads from the top: the title takes focus (no ring), not the first key.
            onOpenAutoFocus={(e) => {
              e.preventDefault();
              heading.current?.focus({ preventScroll: true });
            }}
            onCloseAutoFocus={(e) => {
              e.preventDefault();
              trigger.current?.focus();
            }}
            className="rc-portal ed-confirm tw:fixed tw:z-[91] tw:left-1/2 tw:top-1/2 tw:w-[min(480px,calc(100%-32px))] tw:-translate-x-1/2 tw:-translate-y-1/2 tw:grid tw:gap-4 tw:p-6 tw:rounded-dialog tw:bg-inst tw:shadow-float tw:outline-none"
          >
            <Dialog.Title
              ref={heading}
              tabIndex={-1}
              className="tw:m-0 tw:font-sans tw:text-[17px] tw:font-semibold tw:outline-none"
            >
              {T('按工程复核更新试点', 'Update the pilot from the engineering review')}
            </Dialog.Title>
            {v.rows && (
              <Diff
                rows={v.rows.map((r) => ({ name: r.name, before: r.current, after: r.next }))}
              />
            )}
            <Dialog.Description className="tw:m-0 tw:text-[13.5px] tw:text-ink-2">
              {T(
                `试点配置会从 v${v.fromVersion ?? 1} 升到 v${nextVersion}，知识助手之后按新设置回答。`,
                `The pilot configuration goes from v${v.fromVersion ?? 1} to v${nextVersion}; the assistant answers with the new settings from then on.`,
              )}
            </Dialog.Description>
            {v.submitted && (
              <p className="tw:m-0 tw:text-[13.5px] tw:text-ink-2">
                {T(
                  '这一局已经交付。更新试点前先开一轮修订：交付记录和反馈都会保留。',
                  'This practice is delivered. Updating the pilot opens a revision first; your delivery and feedback stay.',
                )}
              </p>
            )}
            {v.caution && <p className="tw:m-0 tw:text-[13.5px] tw:text-warn">{v.caution}</p>}
            {v.applyError && (
              <p role="alert" className="tw:m-0 tw:text-bad tw:text-[13px]">
                {v.applyError}
              </p>
            )}
            <div className="tw:flex tw:justify-end tw:gap-2">
              <Dialog.Close asChild>
                <Button variant="ghost" disabled={v.applying || v.reloading}>
                  {T('取消', 'Cancel')}
                </Button>
              </Dialog.Close>
              {v.conflict ? (
                // The pilot changed meanwhile: read it again (the list above follows), then confirm.
                <Button
                  variant="secondary"
                  state={v.reloading ? 'loading' : 'idle'}
                  onClick={v.onReload}
                >
                  {T('重新读取', 'Read again')}
                </Button>
              ) : null}
              <Button
                variant="primary"
                state={v.applying ? 'loading' : 'idle'}
                disabled={v.conflict || v.reloading || !v.rows?.length}
                reason={
                  v.conflict
                    ? T('先重新读取试点设置', 'Read the pilot settings again first')
                    : v.rows && !v.rows.length
                      ? T('试点已经是这组设置', 'The pilot already has these settings')
                      : undefined
                }
                onClick={v.onApply}
              >
                {v.applyError && !v.conflict
                  ? T('重试', 'Try again')
                  : v.submitted
                    ? T('开始修订并更新', 'Open a revision and update')
                    : T(`更新为 v${nextVersion}`, `Update to v${nextVersion}`)}
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </Sheet>
  );
}
