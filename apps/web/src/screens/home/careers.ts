/** Role selection on the real product home. Work scenes are labelled previews;
 * the app owns all start and recovery actions. */
import './careers.css';
import { avatar, icon } from '../../app/art.js';
import { locale, T } from '../../app/i18n';
import { personLabel } from '../../app/people.js';

export type CareersInput = {
  topbar: string;
  quote: string;
  capacity: number;
  resumeHtml: string;
  continueCode: string;
};
const esc = (v: unknown) =>
  String(v ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );
const roleName = (r: string) =>
  r === 'pm'
    ? T('AI 产品经理', 'AI Product Manager')
    : T('AI 应用工程师', 'AI Application Engineer');
const team = () =>
  ['manager', 'business', 'technical']
    .map(
      (r) =>
        `<span class="home-person">${avatar(r, 'sm')}<span>${esc(personLabel(r, locale()))}</span></span>`,
    )
    .join('');
const cta = (r: string) =>
  `<button class="btn primary home-cta" type="button" data-action="${r === 'pm' ? 'open-career' : 'engineer-start'}" aria-label="${esc(T('选择这个岗位：', 'Choose this role: ') + roleName(r))}">${T('选择这个岗位', 'Choose this role')}${icon('arrowRight', 'i-sm')}</button>`;
const steps = (r: string) =>
  r === 'pm'
    ? [
        T('找到真实需求', 'Find the real need'),
        T('用测试核实', 'Put it to the test'),
        T('交付你的决定', 'Deliver your decision'),
      ]
    : [
        T('复现失败', 'Reproduce the failure'),
        T('和 Agent 试修', 'Try a fix with your agent'),
        T('亲自签字', 'Sign the change yourself'),
      ];
const roleCopy = (r: string) =>
  r === 'pm'
    ? T('上线之前，你来做判断。', 'You make the call before launch.')
    : T('让它可靠，你来做最后一公里。', 'You make it ready for the real world.');
const next = (r: string) =>
  r === 'pm'
    ? T('接下来：选择情境，阅读委托', 'Next: choose a situation and read the brief')
    : T('接下来：新开一局，接收工程委托', 'Next: start a practice and receive your ticket');
function roleDetail(r: string) {
  return `<ol class="home-actions">${steps(r)
    .map((s, i) => `<li><span>0${i + 1}</span>${s}</li>`)
    .join(
      '',
    )}</ol><p class="home-role-note">${r === 'pm' ? T('Daniel 负责工程修复；用不用，由你决定。', 'Daniel handles the fix. You decide whether to use it.') : T('修好产品经理测出的问题，交回 Grace（AI 同事，产品侧）。Agent 可以帮忙，签字留给你。', 'Fix what the product manager found; hand it to Grace (AI colleague, product side). Your agent helps; only you sign.')}</p>`;
}
function scene(o: CareersInput, r: string) {
  if (r === 'engineer')
    return `<div class="home-scene home-scene--eng" aria-label="${T('工程工作预览', 'Engineering work preview')}"><div class="home-scene-bar">${icon('gear', 'i-sm')}<span>${T('签字台', 'Sign-off desk')}</span><small>${T('预览', 'Preview')}</small></div><div class="home-engine"><p class="home-kicker">${T('你的下一份委托', 'Your next ticket')}</p><h3>${T('回答还在引用旧政策。', 'The answer still cites the old policy.')}</h3><div class="home-version"><span>${T('政策', 'Policy')} <b>v2</b></span><i aria-hidden="true">≠</i><span>${T('索引', 'Index')} <b>v1</b></span></div><div class="home-trace"><span>${T('复现', 'Reproduce')}</span><i></i><span>${T('试修', 'Try a fix')}</span><i></i><span>${T('签字', 'Sign off')}</span></div><p class="home-sign">${T('你的签字', 'Your signature')}<span></span>${icon('edit', 'i-sm')}</p></div></div>`;
  return `<div class="home-scene home-scene--pm" aria-label="${T('产品工作预览', 'Product work preview')}"><div class="home-scene-bar">${icon('layers', 'i-sm')}<span>${T('工作板', 'Work board')}</span><small>${T('预览', 'Preview')}</small></div><div class="home-papers"><div class="home-paper home-paper--back" aria-hidden="true"></div><div class="home-paper"><p class="home-kicker">${T('经理的委托', 'The manager’s brief')}</p><p class="home-quote">${esc(o.quote.split(/[。.!]/u)[0])}${T('。', '.')}</p><div class="home-paper-person">${avatar('manager', 'sm')}<span>${esc(personLabel('manager', locale()))}</span></div></div><div class="home-capacity"><span>${T('试点容量', 'Pilot capacity')}</span><b>${esc(o.capacity)}</b><span>${T('人', 'people')}</span></div></div></div>`;
}
function roles(o: CareersInput) {
  return `<section id="home-roles" class="home-roles" aria-label="${T('选择你的岗位', 'Choose your role')}">${['pm', 'engineer'].map((r, i) => `<article class="home-role" data-role="${r}"><div class="home-role-top"><span class="home-kicker">0${i + 1} / ${T('你的岗位', 'Your role')}</span>${icon(r === 'pm' ? 'note' : 'gear', 'i-sm')}</div><h2>${roleName(r)}</h2><p class="home-role-promise">${roleCopy(r)}</p>${scene(o, r)}${roleDetail(r)}<div class="home-role-bottom">${cta(r)}<small>${next(r)}</small></div></article>`).join('')}</section>`;
}
function casting(o: CareersInput) {
  return `<header class="home-casting-head"><div><p class="home-kicker">${T('选一个岗位，接一份真切的工作', 'Choose a role. Step into the work.')}</p><h1>${T('今天，你来决定。', 'Today, it’s your call.')}</h1></div><p class="home-lede">${T('一个即将试点的知识助手。<br>两种责任，选你想承担的那一种。', 'A knowledge assistant is about to pilot.<br>Two responsibilities. Choose yours.')}</p></header>${roles(o)}<p class="home-bottom-note">${T('每局固定一个岗位，另一边由 AI 同事承担。允许犯错，也随时可以求助。', 'One role per practice. An AI colleague takes the other side. Make mistakes. Ask for help. Try again.')}</p>`;
}
export function careersHtml(o: CareersInput): string {
  return `${o.topbar}<main id="main" class="page home" tabindex="-1">${o.resumeHtml}${casting(o)}<footer class="home-footer"><div class="home-team">${team()}</div><div>${o.continueCode}</div></footer></main>`;
}
