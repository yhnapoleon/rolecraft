// Types for the work-folder markup that TypeScript modules reuse.
export interface FolderWork {
  id: string;
  title?: string;
  purpose?: string;
  kind?: string;
  body?: string;
  revision?: number;
  source?: string;
  adopted?: boolean;
  removedAt?: string | null;
}
export function workFolderMarkup(input: {
  taskId: string;
  title?: string;
  works?: readonly FolderWork[];
}): string;
export function installWorkFolders(
  root?: Document | Element,
  handlers?: {
    onSelect?: (taskId: string, workId: string, event?: Event) => void;
    onInteract?: () => void;
  },
): { sync(): void; destroy?(): void };
