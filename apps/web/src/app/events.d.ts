/** One activity line for a server event projected into the attempt. */
export interface EventLine {
  text: string;
  icon: string;
  tone?: 'warn' | 'good';
  /** A change from outside the learner's own task: shown in every task scope. */
  world?: boolean;
  announce?: 'policy' | 'info';
  /** The workbench action that opens what the line is about. */
  open?: { action: string; id?: string; compare?: boolean };
  /** The task a test event belongs to, when known. */
  taskId?: string | null;
}
/** `workLanguage` is the practice's: world lines are told in it; your own actions follow the interface. */
export function eventLine(
  attempt: object,
  event: object,
  workLanguage?: 'zh' | 'en' | null,
): EventLine;
export function isFeedEvent(event: { type: string }): boolean;
