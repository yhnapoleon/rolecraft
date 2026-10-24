/** Where a work brought back from the person's agent is filed, decided before import.
 * A return answering a handed-over package belongs to that package's task. A return that
 * names a package (requestId) and itself (returnId) but matches no handed-over package is
 * refused: only copying or downloading hands a package over. Anything else is filed under
 * the task the person chooses; nothing defaults to the first task. */
import { T } from './i18n';

export interface ReturnIds {
  readonly requestId?: string | null;
  readonly returnId?: string | null;
}
export interface HandedOverPackage {
  readonly requestId: string;
  readonly taskId?: string | null;
}
export type ReturnPlacement =
  | { readonly status: 'unmatched' }
  | { readonly status: 'package'; readonly taskId: string }
  | { readonly status: 'choose'; readonly taskId: string | null };

export function returnPlacement(
  data: ReturnIds,
  handedOver: readonly HandedOverPackage[],
  tasks: readonly { readonly id: string }[],
  currentTaskId: string | null,
): ReturnPlacement {
  const exp = data.requestId
    ? handedOver.find((item) => item.requestId === data.requestId)
    : undefined;
  if (data.requestId && data.returnId && !exp) return { status: 'unmatched' };
  const exists = (id: string | null | undefined): id is string =>
    !!id && tasks.some((task) => task.id === id);
  if (exists(exp?.taskId)) return { status: 'package', taskId: exp.taskId };
  return { status: 'choose', taskId: exists(currentTaskId) ? currentTaskId : null };
}

export const unmatchedReturnText = () =>
  T(
    '找不到对应的任务包：这份回传的 requestId 没有对应已交出的任务包（只在“关于”里查看不算交出）。请核对 requestId，或去掉它后作为未关联回传导入。',
    'No matching task package: this return’s requestId matches no package you handed over (viewing a package in About does not hand it over). Check the requestId, or remove it to import the return unlinked.',
  );

/** A blocked copy hands nothing over, and viewing does not either: point to Download. */
export const copyBlockedText = () =>
  T(
    '浏览器不允许自动复制，任务包没有复制成功；请改用“下载”交出。',
    'The browser blocked copying, so the package was not copied. Use Download to hand it over.',
  );
