/** The intro's "To fix" slip (plan §13.3, 208 G12): the same four parts whichever way the person
 * came in (a new practice, tests product handed over, a delivered practice):
 *   the question · the assistant's recorded answer (quoted) · what is wrong with it · an amber tag
 *   when the index lags the source.
 * The quote is always the assistant's answer as the ticket recorded it, never a document's text.
 * When that recorded answer is already right (a seeded ticket captured after the index was
 * refreshed: no source lags), it is not quoted; the slip says only the ticket's problem. */
import { T } from '../../app/i18n';
import { quoteExcerpt, sourceName, statusWord, type TicketDetail } from './model';
import { brokenLine } from './steps/ticket';

export interface TargetSlip {
  readonly query: string;
  /** The assistant's recorded answer (cut to the sentence with the number), or none. */
  readonly quote: string | null;
  /** One sentence: what is wrong with it. */
  readonly wrong: string;
  /** "Travel policy v2 / index v1" when the index lags, else none. */
  readonly stale: string | null;
  /** Further targets in the ticket (the slip shows the first). */
  readonly more: number;
}

/** The situation's own words for the hotel-limit ticket (also what a delivered practice shows
 * before its ticket is opened, since opening one puts the pilot live). */
const situation = () => ({
  query: T('住宿报销上限是多少？', 'What is the hotel reimbursement limit per night?'),
  problem: T(
    '知识助手还在按旧版差旅政策回答，而且没有提醒资料可能已过期。',
    'The assistant still answers from the old travel policy, with no warning that it may be out of date.',
  ),
});

export function targetSlip(ticket: TicketDetail | null): TargetSlip {
  const test = ticket?.target_tests[0];
  if (!ticket || !test) {
    const s = situation();
    return { query: s.query, quote: null, wrong: s.problem, stale: null, more: 0 };
  }
  const more = Math.max(0, ticket.target_tests.length - 1);
  const stale = brokenLine(test).stale || null;
  const cite = test.citations[0];
  if (stale) {
    const warned = test.status === 'answered_with_warning';
    const wrong = cite
      ? T(
          `仍引用${sourceName(cite.object_id)} v${cite.version}，${warned ? '虽然带了提醒' : '没有提醒'}。`,
          `It still cites ${sourceName(cite.object_id)} v${cite.version}, ${warned ? 'even with a warning' : 'with no warning'}.`,
        )
      : T(
          `索引落后，回答是「${statusWord(test.status)}」。`,
          `The index lags; it gave ${statusWord(test.status)}.`,
        );
    return { query: test.query, quote: quoteExcerpt(test.answer_summary), wrong, stale, more };
  }
  if (ticket.source === 'seeded')
    return { query: test.query, quote: null, wrong: situation().problem, stale: null, more };
  const said = cite
    ? T(
        `引用${sourceName(cite.object_id)} v${cite.version}`,
        `It cites ${sourceName(cite.object_id)} v${cite.version}`,
      )
    : T(statusWord(test.status), `It gave ${statusWord(test.status)}`);
  return {
    query: test.query,
    quote: test.answer_summary ? quoteExcerpt(test.answer_summary) : null,
    wrong: T(`${said}，产品经理认为这条答得不对。`, `${said}; product says this answer is wrong.`),
    stale: null,
    more,
  };
}
