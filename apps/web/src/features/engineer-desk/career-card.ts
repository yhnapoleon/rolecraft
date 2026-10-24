/** The engineer job on the home page, open. Its picture is the job's own work object: a short
 * log tape of the three steps, ending on the signature line only the person signs. */
import { T } from '../../app/i18n';

const esc = (v: string) =>
  v.replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );

/** Only the knowledge-assistant pilot ships the engineer regression probes (HANDOVER: 回归探针). */
export const ENGINEER_CASES: readonly string[] = ['pilot'];

export function engineerCareerCardHtml(options: { practice: boolean }): string {
  const steps = [
    T('复现 AIPM 记录的失败', 'Reproduce the failure the AIPM recorded'),
    T('只调受支持的配置', 'Change only supported settings'),
    T('用真实回归证明', 'Prove it with a real regression run'),
  ];
  return `<article class="career open eng-career" data-career="engineer">
    <div class="career-art eng-career__art">
      <ol class="eng-career__tape" aria-label="${esc(T('这份工作的三步', 'The three steps of this job'))}">${steps
        .map(
          (step, i) =>
            `<li style="--i:${i}"><span class="eng-career__n" aria-hidden="true">0${i + 1}</span><span>${esc(step)}</span></li>`,
        )
        .join('')}</ol>
      <p class="eng-career__sign" aria-hidden="true"><span class="eng-career__rule"></span><span>${esc(T('只能由你签', 'Only you sign'))}</span></p>
    </div>
    <div class="career-body">
      <h2 class="career-name">${esc(T('AI 应用工程师', 'AI Application Engineer'))}</h2>
      <p>${esc(T('带你的 Agent 复现失败、试修配置；只有你能签字提交复核。', 'Bring your agent to reproduce the failure and try a fix; only you can sign it off for review.'))}</p>
      <p class="meta">${esc(T('和产品经理是同一个练习：测试台上的失败也能交给工程。', 'The same practice as the product manager: failures on the test bench can be handed to engineering.'))}</p>
      <div class="career-cta eng-career__cta">
        <button type="button" class="btn large" data-action="engineer-start">${esc(T('开始', 'Start'))}</button>
        ${options.practice ? `<button type="button" class="btn quiet" data-action="engineer-take">${esc(T('在当前练习里接手工程委托', 'Take the ticket in this practice'))}</button>` : ''}
      </div>
    </div>
  </article>`;
}
