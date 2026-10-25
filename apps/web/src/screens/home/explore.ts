/** Opt-in design studies on the real home. All entry actions belong to ui.js.
 * Preview controls only change presentation; they never create a session or call a model. */
import './explore.css';
import { avatar, icon } from '../../app/art.js';
import { locale, T } from '../../app/i18n';
import { personLabel } from '../../app/people.js';

export type Direction = 'a' | 'b' | 'c';
export function homeDirection(): Direction | null {
  if (typeof window === 'undefined') return null;
  const v = new URLSearchParams(window.location.search).get('home');
  return v === 'a' || v === 'b' || v === 'c' ? v : null;
}
type Input = {
  topbar: string;
  quote: string;
  capacity: number;
  seeds: string[];
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
        `<span class="hx-person">${avatar(r, 'sm')}<span>${esc(personLabel(r, locale()))}</span></span>`,
    )
    .join('');
const cta = (r: string) =>
  `<button class="btn primary hx-cta" type="button" data-action="${r === 'pm' ? 'open-career' : 'engineer-start'}" aria-label="${esc(T('选择这个岗位：', 'Choose this role: ') + roleName(r))}">${T('选择这个岗位', 'Choose this role')}${icon('arrowRight', 'i-sm')}</button>`;
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
  return `<ol class="hx-actions">${steps(r)
    .map((s, i) => `<li><span>0${i + 1}</span>${s}</li>`)
    .join(
      '',
    )}</ol><p class="hx-role-note">${r === 'pm' ? T('Daniel 负责工程修复；用不用，由你决定。', 'Daniel handles the fix. You decide whether to use it.') : T('Agent 可以帮忙，最后的签字留给你。', 'Your agent can help. The final signature is yours.')}</p>`;
}
function scene(o: Input, r: string) {
  if (r === 'engineer')
    return `<div class="hx-scene hx-scene--eng" aria-label="${T('工程工作预览', 'Engineering work preview')}"><div class="hx-scene-bar">${icon('gear', 'i-sm')}<span>${T('签字台', 'Sign-off desk')}</span><small>${T('预览', 'Preview')}</small></div><div class="hx-engine"><p class="hx-kicker">${T('你的下一份委托', 'Your next ticket')}</p><h3>${T('回答还在引用旧政策。', 'The answer still cites the old policy.')}</h3><div class="hx-version"><span>${T('政策', 'Policy')} <b>v2</b></span><i aria-hidden="true">≠</i><span>${T('索引', 'Index')} <b>v1</b></span></div><div class="hx-trace"><span>${T('复现', 'Reproduce')}</span><i></i><span>${T('试修', 'Try a fix')}</span><i></i><span>${T('签字', 'Sign off')}</span></div><p class="hx-sign">${T('你的签字', 'Your signature')}<span></span>${icon('edit', 'i-sm')}</p></div></div>`;
  return `<div class="hx-scene hx-scene--pm" aria-label="${T('产品工作预览', 'Product work preview')}"><div class="hx-scene-bar">${icon('layers', 'i-sm')}<span>${T('工作板', 'Work board')}</span><small>${T('预览', 'Preview')}</small></div><div class="hx-papers"><div class="hx-paper hx-paper--back" aria-hidden="true"></div><div class="hx-paper"><p class="hx-kicker">${T('经理的委托', 'The manager’s brief')}</p><p class="hx-quote">${esc(o.quote.split(/[。.!]/u)[0])}${T('。', '.')}</p><div class="hx-paper-person">${avatar('manager', 'sm')}<span>${esc(personLabel('manager', locale()))}</span></div></div><div class="hx-capacity"><span>${T('试点容量', 'Pilot capacity')}</span><b>${esc(o.capacity)}</b><span>${T('人', 'people')}</span></div></div></div>`;
}
function roles(o: Input, large: boolean) {
  return `<section id="hx-roles" class="hx-roles ${large ? 'hx-roles--large' : ''}" aria-label="${T('选择你的岗位', 'Choose your role')}">${['pm', 'engineer'].map((r, i) => `<article class="hx-role" data-role="${r}"><div class="hx-role-top"><span class="hx-kicker">0${i + 1} / ${T('你的岗位', 'Your role')}</span>${icon(r === 'pm' ? 'note' : 'gear', 'i-sm')}</div><h2>${roleName(r)}</h2><p class="hx-role-promise">${roleCopy(r)}</p>${large ? scene(o, r) : ''}${roleDetail(r)}<div class="hx-role-bottom">${cta(r)}<small>${next(r)}</small></div></article>`).join('')}</section>`;
}
function studyNav(d: Direction) {
  const names = { a: T('叙事', 'Story'), b: T('选角', 'Roles'), c: T('工作台', 'Workspace') };
  return `<nav class="hx-study" aria-label="${T('首页方案', 'Home studies')}"><span>${T('设计探索', 'Design study')}</span>${(
    ['a', 'b', 'c'] as const
  )
    .map((v) => {
      const url = new URL(window.location.href);
      url.searchParams.set('home', v);
      url.hash = '/';
      return `<a href="${esc(url.pathname + url.search + url.hash)}" ${d === v ? 'aria-current="page"' : ''}>${v.toUpperCase()}<span>${names[v]}</span></a>`;
    })
    .join(
      '',
    )}<a href="${esc(`${window.location.pathname}${new URLSearchParams(window.location.search).get('polish') === '1' ? '?polish=1' : ''}#/`)}">${T('原版', 'Original')}</a></nav>`;
}
function narrative(o: Input) {
  return `<section class="hx-story"><div class="hx-story-copy"><p class="hx-kicker">${T('一份委托 · 一个由你决定的开始', 'One brief. A beginning you decide.')}</p><h1>${T('下周上线。<br>你，准备好了吗？', 'Launch next week.<br>Are you ready?')}</h1><p class="hx-lede">${T('接手一个 AI 产品，和三位同事把问题问透、把方案测清，再交付你的判断。', 'Take on an AI product. Ask the hard questions, test your assumptions and deliver a decision you can stand behind.')}</p><a class="btn primary hx-cta" href="#hx-roles" data-hx-scroll>${T('找到你的角色', 'Find your role')}${icon('down', 'i-sm')}</a><p class="hx-meta">${T('20–30 分钟一局 · 随时停，随时继续', '20–30 minutes · Pause and return any time')}</p></div><div class="hx-stage">${scene(o, 'pm')}<div class="hx-floating-note">${icon('quote', 'i-sm')}<p>${T('答案不会自己出现。<br>你的判断会改变下一步。', 'Answers take work.<br>Your judgment shapes what comes next.')}</p></div></div></section><div class="hx-chapter"><span>01 — ${T('接手', 'Take ownership')}</span><span>02 — ${T('问清与核实', 'Question and verify')}</span><span>03 — ${T('交付与修订', 'Deliver and revise')}</span></div><section class="hx-role-intro"><p class="hx-kicker">${T('同一间办公室，不同的责任', 'One workplace. Different responsibilities.')}</p><h2>${T('你想在哪一边，推动事情发生？', 'Where will you make a difference?')}</h2></section>${roles(o, false)}`;
}
function casting(o: Input) {
  return `<header class="hx-casting-head"><div><p class="hx-kicker">${T('选一个岗位，接一份真切的工作', 'Choose a role. Step into the work.')}</p><h1>${T('今天，你来决定。', 'Today, it’s your call.')}</h1></div><p class="hx-lede">${T('一个即将试点的知识助手。<br>两种责任，选你想承担的那一种。', 'A knowledge assistant is about to pilot.<br>Two responsibilities. Choose yours.')}</p></header>${roles(o, true)}<p class="hx-bottom-note">${T('每局固定一个岗位，另一边由 AI 同事承担。允许犯错，也随时可以求助。', 'One role per practice. An AI colleague takes the other side. Make mistakes. Ask for help. Try again.')}</p>`;
}
function workspace(o: Input) {
  return `<header class="hx-product-head"><p class="hx-kicker">${T('你的下一张工作台', 'Your next workspace')}</p><h1>${T('从「我会」，到「我做过」。', 'From knowing to doing.')}</h1><p class="hx-lede">${T('读资料、问同事、做测试。让每一个决定，都有自己的依据。', 'Read the sources. Talk to colleagues. Run the tests. Give every decision a foundation.')}</p></header><section class="hx-workspace" aria-label="${T('知识助手工作台预览', 'Knowledge assistant workspace preview')}"><header class="hx-workspace-bar"><span class="wordmark-glyph" aria-hidden="true"></span><b>${T('知识助手试点', 'Knowledge assistant pilot')}</b><span class="hx-preview-tag">${T('工作台预览', 'Workspace preview')}</span></header><div class="hx-workspace-body"><nav class="hx-workspace-nav" aria-label="${T('预览内容', 'Preview content')}">${[T('委托', 'Brief'), T('事项', 'Tasks'), T('同事', 'Team')].map((n, i) => `<button type="button" data-hx-tab="${i}" aria-pressed="${i === 0}" aria-controls="hx-preview-content">${icon(['note', 'layers', 'team'][i], 'i-sm')}<span>${n}</span></button>`).join('')}<span class="hx-nav-bottom">${T('自由安排工作顺序', 'Work in your own order')}</span></nav><div class="hx-preview-content" id="hx-preview-content"><div data-hx-panel="0"><p class="hx-kicker">${T('从这份委托开始', 'It begins with a brief')}</p><div class="hx-product-brief"><span class="hx-paper-label">${T('委托书', 'The brief')}</span><blockquote>${esc(o.quote)}</blockquote><div class="hx-paper-person">${avatar('manager', 'sm')}<span>${esc(personLabel('manager', locale()))}</span></div></div><div class="hx-product-foot"><p>${T('先读清楚，再决定从哪里动手。', 'Read it through. Decide where to begin.')}</p><b>${o.capacity}<small>${T('人试点容量', 'pilot capacity')}</small></b></div></div><div data-hx-panel="1" hidden><p class="hx-kicker">${T('你来安排先后', 'You set the priorities')}</p><h2>${T('把大问题，拆成手里的事。', 'Turn a big question into work you can do.')}</h2><div class="hx-task-stack">${o.seeds.map((s, i) => `<div class="hx-task-paper"><span class="hx-task-number">0${i + 1}</span>${icon('circle', 'i-sm')}<span>${esc(s)}</span></div>`).join('')}</div><p class="hx-meta">${T('进入工作板后，可调整优先级、留下作品。', 'Inside the board, set priorities and create your work.')}</p></div><div data-hx-panel="2" hidden><p class="hx-kicker">${T('三位同事，三种上下文', 'Three colleagues. Three perspectives.')}</p><h2>${T('带着问题，去找对的人。', 'Take the question to the right person.')}</h2><div class="hx-team-list">${['manager', 'business', 'technical'].map((r, i) => `<div>${avatar(r, 'md')}<div><b>${esc(personLabel(r, locale()))}</b><p>${[T('确认目标、资源与决定', 'Align on goals, resources and decisions'), T('问清需求和实际使用场景', 'Understand needs and how people work'), T('核实技术边界和测试问题', 'Check technical limits and test failures')][i]}</p></div></div>`).join('')}</div></div></div><aside class="hx-workspace-aside"><p class="hx-kicker">${T('你会带走什么', 'What you take away')}</p><h3>${T('一份经得起追问的决定。', 'A decision you can explain.')}</h3><p>${T('留下过程作品，查看交付反馈，再修订一次。', 'Keep your work, examine the feedback and make another revision.')}</p><div class="hx-evidence-path" aria-hidden="true"><span>${T('资料', 'Sources')}</span><i></i><span>${T('判断', 'Decision')}</span><i></i><span>${T('反馈', 'Feedback')}</span></div></aside></div></section>${roles(o, false)}`;
}
export function exploreHome(o: Input, d: Direction): string {
  return `${o.topbar}<main id="main" class="page hx hx--${d}" tabindex="-1">${studyNav(d)}${o.resumeHtml}${d === 'a' ? narrative(o) : d === 'b' ? casting(o) : workspace(o)}<footer class="hx-footer"><div class="hx-team">${team()}</div><div>${o.continueCode}</div></footer></main>`;
}
if (typeof document !== 'undefined') {
  document.addEventListener('click', (e) => {
    const target = e.target instanceof Element ? e.target : null;
    const root = target?.closest<HTMLElement>('.hx');
    if (!root) return;
    const jump = target?.closest('[data-hx-scroll]');
    if (jump) {
      e.preventDefault();
      const roles = root.querySelector<HTMLElement>('#hx-roles');
      roles?.scrollIntoView({
        block: 'start',
        behavior:
          matchMedia('(prefers-reduced-motion: reduce)').matches || (e as MouseEvent).detail === 0
            ? 'instant'
            : 'smooth',
      });
      roles?.querySelector<HTMLButtonElement>('button')?.focus({ preventScroll: true });
    }
    const tab = target?.closest<HTMLElement>('[data-hx-tab]');
    if (!tab) return;
    root.querySelectorAll('[data-hx-tab]').forEach((el) => {
      el.setAttribute('aria-pressed', String(el === tab));
    });
    root.querySelectorAll<HTMLElement>('[data-hx-panel]').forEach((el) => {
      el.hidden = el.dataset.hxPanel !== tab.dataset.hxTab;
    });
    const panel = root.querySelector<HTMLElement>(`[data-hx-panel="${tab.dataset.hxTab}"]`);
    if (
      panel &&
      (e as MouseEvent).detail > 0 &&
      !matchMedia('(prefers-reduced-motion: reduce)').matches
    )
      panel.animate(
        [
          { opacity: 0.3, transform: 'translateY(6px)' },
          { opacity: 1, transform: 'translateY(0)' },
        ],
        { duration: 280, easing: 'cubic-bezier(.23,1,.32,1)' },
      );
  });
}
