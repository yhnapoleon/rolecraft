/** One role per practice (phase 2, step 3): the AI colleague who takes the other side.
 *
 * In a product manager's practice "Hand to engineering" goes to Daniel. His run is one request
 * (rule orchestration of the engineer tools on the server); while it runs the page says only that
 * he is on it, and when it returns his report lands where reports land (Needs you, the report
 * sheet) with the run shown as what it was: what he tried, what he skipped and why he chose it.
 * In an engineer's practice the signed report goes to Grace, who decides by rule; her reply is
 * hers, said in her words, and nothing is applied as the person's own action. */
import { T } from '../../app/i18n';
import { signalsChanged } from '../../shell';
import { keepGraceReply as keep } from './grace-signal';
import type { GatewayTransport } from '../../gateway-transport';
import { engineerApi, failureText, type DecisionResult } from './api';
import { reviewResult, outcomeClean, withTargetCheck } from './hand-back';
import { recordHandBack } from './local-state';
import type { TicketDetail } from './model';

const REASON: Record<string, [string, string]> = {
  no_rule: ['规则表里没有适用于这类故障的改动', 'no rule in the table fits this kind of failure'],
  no_valid_candidate: ['规则给出的改动在这个场景里都不能用', 'none of the rules’ changes are valid here'],
  engineer_review_budget_exhausted: ['这张委托的 3 次复核已经用完', 'this ticket’s 3 reviews are used up'],
  engineer_trial_limit_reached: ['这张委托的试跑次数已经用完', 'this ticket has no trial runs left'],
  engineer_baseline_unsupported: ['当前设置本身不能作为工程候选', 'the current settings cannot be an engineering candidate'],
};
export const reasonText = (code: string) => {
  const r = REASON[code];
  return r ? T(r[0], r[1]) : code;
};

/** Daniel's report is back: keep it for Needs you and open it. A run that did not finish says
 * why, and nothing else is shown. */
export async function colleagueReported(
  transport: GatewayTransport,
  sessionId: string,
  ticket: TicketDetail,
  reread?: () => Promise<unknown>,
): Promise<string | null> {
  const h = ticket.handover;
  if (!h || h.state === 'failed' || !h.review_id)
    return T(
      `Daniel 没能完成这张委托：${reasonText(h?.failed_reason ?? '')}。可以再交一次，或自己处理。`,
      `Daniel could not finish this ticket: ${reasonText(h?.failed_reason ?? '')}. Hand it over again, or handle it yourself.`,
    );
  const api = engineerApi(transport, sessionId);
  const record = await api.review(h.review_id);
  // The board reads the target as the report does: from Daniel's rule check.
  const result = withTargetCheck(reviewResult(record, T('zh', 'en') as 'zh' | 'en'), h.rule?.target);
  recordHandBack(sessionId, h.review_id, {
    at: new Date().toISOString(),
    ticketId: ticket.id,
    clean: outcomeClean(result),
    newFailures: result.newFailures,
    title: ticket.source,
    result,
    colleague: 'Daniel',
  });
  signalsChanged();
  const { openHandBackSheet } = await import('./hand-back-ui');
  openHandBackSheet({ transport, sessionId, reviewId: h.review_id, reread });
  return null;
}

/* ---------- Grace, in an engineer's practice ---------- */

/** Hand the signed report to Grace; her decision and reply come back from the server's rule. */
export async function handToGrace(
  transport: GatewayTransport,
  sessionId: string,
  ticketId: string,
  reviewId?: string,
): Promise<DecisionResult['decision']> {
  try {
    const { decision } = await engineerApi(transport, sessionId).decide(ticketId, 'handover');
    keep(sessionId, {
      at: new Date().toISOString(),
      ticketId,
      text: decision.reply ?? '',
      result: decision.result ?? '',
      reviewId,
    });
    signalsChanged();
    return decision;
  } catch (error) {
    throw new Error(failureText(error));
  }
}
