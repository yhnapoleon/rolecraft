/** S2 · Daniel's ticket (plan §13.4): a colleague hands you one thing, in the first person, on paper
 * like Grace's brief. Where it broke, what done looks like, the rules, and the starting point the
 * system prepared. Read-only: it is the reference the three steps below work against. */
import { avatar } from '../../../app/art.js';
import { T } from '../../../app/i18n';
import { personName, personTitle } from '../../../app/people.js';
import { chip, countNode } from '../bits';
import { el, iconNode, workLang } from '../dom';
import { clock, sourceName, statusWord, type TargetTest, type TicketDetail } from '../model';

/** The task in work words (title on the desk, the tab and the intro). */
export function ticketTask(ticket: TicketDetail): { title: string; short: string } {
  if (ticket.source === 'seeded')
    return {
      title: T('修好住宿上限的回答', 'Fix the hotel-limit answer'),
      short: T('住宿上限排查', 'Hotel-limit fix'),
    };
  const n = ticket.target_tests.length;
  return {
    title: T(
      `修好产品经理交来的 ${n} 条测试`,
      `Fix the ${n} ${n === 1 ? 'test' : 'tests'} product handed over`,
    ),
    short: T('交来的测试', 'Handed-over tests'),
  };
}

/** Daniel's first-person ask: words from the world, so in the practice's work language. */
export function ticketLetter(ticket: TicketDetail): string {
  const W = (zh: string, en: string) => (ticket.work_language === 'en' ? en : zh);
  return ticket.source === 'seeded'
    ? W(
        '知识助手还在按旧版差旅政策回答住宿上限，而且答得很肯定。修好它，别把原来答对的弄坏。改好你签字，复核会跑全部检查。',
        'The assistant still answers the hotel limit from the old travel policy, and sounds sure of it. Fix that without breaking what already worked. Sign it when you’re done; the review reruns every check.',
      )
    : W(
        '产品经理交来几条答得不对的测试。修好它们，别把原来答对的弄坏。改好你签字，复核会跑全部检查。',
        'Product handed over tests the assistant gets wrong. Fix them without breaking what already worked. Sign it when you’re done; the review reruns every check.',
      );
}

/** What is wrong with one target, in one line: the lagging index and what the answer cites. */
export function brokenLine(test: TargetTest): { stale: string; detail: string } {
  const lag = Object.entries(test.source_versions).find(
    ([key, v]) => test.indexed_versions[key] !== undefined && test.indexed_versions[key] !== v,
  );
  const cite = test.citations[0];
  const warned = test.status === 'answered_with_warning';
  const stale = lag
    ? T(
        `${sourceName(lag[0])} v${lag[1]} / 索引 v${test.indexed_versions[lag[0]]}`,
        `${sourceName(lag[0])} v${lag[1]} / index v${test.indexed_versions[lag[0]]}`,
      )
    : '';
  const parts: string[] = [];
  if (lag)
    parts.push(
      T(
        `${sourceName(lag[0])}已到 v${lag[1]}，索引停在 v${test.indexed_versions[lag[0]]}`,
        `${sourceName(lag[0])} is at v${lag[1]}, the index is still on v${test.indexed_versions[lag[0]]}`,
      ),
    );
  if (cite)
    parts.push(
      T(
        `引用${sourceName(cite.object_id)} v${cite.version}，${warned ? '带了提醒' : '没提醒'}`,
        `it cites ${sourceName(cite.object_id)} v${cite.version} ${warned ? 'with a warning' : 'with no warning'}`,
      ),
    );
  else parts.push(statusWord(test.status));
  return { stale, detail: parts.join(T('；', '; ')) };
}

/** The ticket paper. `left` is the reviews-left number (rolls when it changes). */
export function ticketPaper(doc: Document, ticket: TicketDetail) {
  const lang = workLang(ticket.work_language);
  const left = Math.max(0, ticket.review_budget.limit - ticket.review_budget.used);
  const leftNode = countNode(doc, left, 'ed-count');
  const from = el(doc, 'p', { class: 'ed-ticket__from' });
  from.insertAdjacentHTML('afterbegin', avatar('technical', 'sm'));
  from.append(
    el(doc, 'b', { class: 'ed-ticket__name' }, personName('technical')),
    el(
      doc,
      'span',
      { class: 'ed-ticket__role' },
      T(
        `${personTitle('technical', 'zh')} · ${clock(ticket.created_at)} 交给你`,
        `${personTitle('technical', 'en')} · handed to you ${clock(ticket.created_at)}`,
      ),
    ),
  );
  const targets = ticket.target_tests;
  const broken = el(
    doc,
    'div',
    { class: 'ed-ticket__broken', 'data-vt': 'ticket-target' },
    ...targets.slice(0, 3).map((test) => {
      const line = brokenLine(test);
      return el(
        doc,
        'div',
        { class: 'ed-ticket__case' },
        el(doc, 'p', { class: 'ed-ticket__q', lang }, test.query),
        el(doc, 'blockquote', { class: 'ed-ticket__quote', lang }, test.answer_summary),
        el(
          doc,
          'p',
          { class: 'ed-ticket__why' },
          line.stale ? chip(doc, [iconNode(doc, 'stale', 'i-xs'), line.stale], 'warn') : null,
          el(doc, 'span', {}, line.detail),
        ),
      );
    }),
    targets.length > 3
      ? el(
          doc,
          'p',
          { class: 'ed-ticket__more' },
          T(`另有 ${targets.length - 3} 条`, `${targets.length - 3} more`),
        )
      : null,
  );
  const done =
    ticket.source === 'seeded'
      ? T(
          '问到住宿上限时，提醒资料可能已过期；原来对的不变坏',
          'When asked, it warns the source may be out of date; nothing that worked breaks',
        )
      : T(
          `这 ${targets.length} 条要修好；其余公开检查不能变坏`,
          `These ${targets.length} must be fixed; no other public check may break`,
        );
  const row = (label: string, ...body: (Node | string | null)[]) =>
    el(
      doc,
      'div',
      { class: 'ed-ticket__row' },
      el(doc, 'dt', {}, label),
      el(doc, 'dd', {}, ...body),
    );
  const rules = el(
    doc,
    'span',
    {},
    T(
      `只改支持的设置 · 签字只能你 · 复核最多 ${ticket.review_budget.limit} 次（还剩 `,
      `Supported settings only · Only you sign · Up to ${ticket.review_budget.limit} reviews (`,
    ),
    leftNode,
    T('）', ' left)'),
  );
  const paper = el(
    doc,
    'article',
    { class: 'ed-ticket', 'aria-labelledby': 'ed-ticket-from' },
    from,
    el(
      doc,
      'blockquote',
      { class: 'ed-ticket__letter', id: 'ed-ticket-from', lang },
      ticketLetter(ticket),
    ),
    el(
      doc,
      'dl',
      { class: 'ed-ticket__facts' },
      row(T('坏在哪', 'What broke'), broken),
      row(T('做完是', 'Done means'), done),
      row(T('规矩', 'Rules'), rules),
    ),
    ticket.world_setup
      ? el(
          doc,
          'p',
          { class: 'ed-ticket__setup' },
          iconNode(doc, 'info', 'i-xs'),
          T(
            `这一局试点已按 v${ticket.world_setup.config_version} 上线，起点由系统准备，不是你的操作`,
            `The pilot went live as v${ticket.world_setup.config_version} for this practice; the system set this up, not you`,
          ),
        )
      : null,
  );
  return { paper, leftNode };
}
