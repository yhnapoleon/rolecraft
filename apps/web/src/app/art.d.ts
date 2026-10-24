// Types for the marks that TypeScript modules reuse from the plain-JavaScript art.
export function icon(name: string, cls?: string): string;
export function priMark(priority: 'first' | 'next' | 'later' | string): string;
export function statusMark(status: 'open' | 'working' | 'done' | string): string;
export function avatar(
  role: string,
  size?: string,
  opts?: { typing?: boolean; dot?: boolean },
): string;
export function agentMark(size?: string): string;
export function assistantMark(size?: string): string;
export const PEOPLE: Readonly<
  Record<
    string,
    {
      readonly name: string;
      readonly ref: string;
      readonly subject: string;
      readonly initial: string;
      readonly title: string;
      readonly label: string;
      readonly titled: boolean;
    }
  >
>;
export const ROLES: readonly string[];
