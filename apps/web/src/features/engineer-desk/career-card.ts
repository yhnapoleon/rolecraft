/** The engineer job on the home page: its row in the list of jobs. */
import { T } from '../../app/i18n';

const esc = (v: string) =>
  v.replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );

/** Only the knowledge-assistant pilot ships the engineer regression probes (HANDOVER: 回归探针). */
export const ENGINEER_CASES: readonly string[] = ['pilot'];

/** The engineer's row in home's list of jobs (199 decisions 5, 6): the same four parts as the
 * product manager's row above it (name · what you do · how it runs · the key), drawn by home's
 * own row styles. The row says the one thing that sets this job apart: it is the same practice
 * as the product manager's, worn with the other hat. */
export function engineerCareerCardHtml(options: { practice: boolean }): string {
  return `<article class="career open eng-career" data-career="engineer">
    <div class="career-body">
      <h2 class="career-name">${esc(T('AI 应用工程师', 'AI Application Engineer'))}</h2>
      <p>${esc(T('修好产品经理测出的问题，并亲自为改动签字。你的 Agent 可以帮忙，不能替你签。', 'Fix what the product manager found and sign the change yourself. Your agent can help; it can’t sign.'))}</p>
      <p class="meta">${esc(T('委托由 Grace（AI 同事，产品侧）发出；你签字后交回她，由她按规则决定是否应用。', 'Grace (AI colleague, product side) sends the ticket; once you sign, it goes back to her and she decides by rule whether to apply it.'))}</p>
      <div class="career-cta eng-career__cta">
        <button type="button" class="btn" data-action="engineer-start">${esc(T('开始', 'Start'))}</button>
        ${options.practice ? `<button type="button" class="btn quiet" data-action="engineer-take">${esc(T('在当前练习里接手', 'Take it in this practice'))}</button>` : ''}
      </div>
    </div>
  </article>`;
}
