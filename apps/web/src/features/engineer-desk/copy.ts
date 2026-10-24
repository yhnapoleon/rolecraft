/** Words for the engineer's desk: refusals from the engineer API in plain sentences, and setting
 * values as the pilot settings sheet names them. Every line is a T('中文', 'English') pair; an
 * error code is never shown. */
import { T } from '../../app/i18n';
import { DOMAIN, FALLBACK, UPDATE, WORK_ITEM } from '../../app/vocab.js';
import { FIELD_NAMES } from '../engineer-report';

const ERRORS: Readonly<Record<string, () => string>> = {
  engineer_signoff_requires_human: () =>
    T(
      '只有你本人能签字提交复核，Agent 不能代签。',
      'Only you can sign this off; your agent can’t.',
    ),
  engineer_ticket_requires_human: () =>
    T('只有你本人能开工程委托。', 'Only you can open an engineering ticket.'),
  engineer_review_budget_exhausted: () =>
    T('这份委托的 3 次复核已经用完。', 'This ticket’s 3 reviews are used up.'),
  engineer_suite_unavailable: () =>
    T(
      '这个情境还没有工程复核用的探针，暂时不能开委托。',
      'This situation has no regression probes for engineering yet, so no ticket can open.',
    ),
  engineer_impact_note_required: () =>
    T('先写这个改动还可能影响哪些问题。', 'Write which questions this change might affect first.'),
  engineer_impact_note_too_long: () =>
    T('影响说明最多 500 字。', 'Keep the impact note within 500 characters.'),
  engineer_draft_text_too_long: () =>
    T(
      '草稿的文字合计最多 2000 字，删减一些再保存。',
      'A draft holds 2,000 characters of text in total. Shorten it and save again.',
    ),
  engineer_test_selection_too_large: () =>
    T('一次最多交 10 条测试。', 'Hand over at most 10 tests at a time.'),
  engineer_test_selection_required: () =>
    T('先选至少一条测试。', 'Choose at least one test first.'),
  engineer_setting_not_editable: () =>
    T('这项设置不在委托可改的范围内。', 'This setting isn’t one the ticket can change.'),
  engineer_setting_value_invalid: () =>
    T(
      '有一项设置的值不被接受，检查范围后再试。',
      'One setting has a value that isn’t accepted. Check its range and try again.',
    ),
  engineer_change_statement_invalid: () =>
    T('逐条变更里每项设置只能写一条。', 'Each setting can appear only once in the change list.'),
  engineer_claim_incomplete: () =>
    T(
      '自报要覆盖全部公开探针，或者一条都不填。',
      'Report every public probe, or leave the self-report out.',
    ),
  engineer_claim_probe_unknown: () =>
    T('自报里有不是公开探针的编号。', 'The self-report names a probe that isn’t public.'),
  engineer_trial_limit_reached: () =>
    T('这份委托的试跑次数已经用完。', 'This ticket has no trial runs left.'),
  engineer_draft_limit_reached: () =>
    T('这份委托的草稿数已经用完。', 'This ticket has no drafts left.'),
  engineer_baseline_unsupported: () =>
    T(
      '现在的试点设置超出工程委托能改的范围，暂时不能开委托。',
      'The current pilot settings go beyond what a ticket can change, so no ticket can open.',
    ),
  engineer_review_changed: () =>
    T(
      '这次复核的记录对不上了，读不到报告。',
      'This review’s records no longer match, so its report can’t be read.',
    ),
  engineer_ticket_not_found: () => T('找不到这份委托。', 'This ticket can’t be found.'),
  engineer_ticket_changed: () =>
    T('这份委托的记录对不上了。', 'This ticket’s records no longer match.'),
  engineer_draft_not_found: () =>
    T('找不到这份草稿，刷新后再签。', 'This draft can’t be found. Refresh and sign again.'),
  engineer_review_not_found: () => T('找不到这次复核。', 'This review can’t be found.'),
  engineer_source_unavailable: () =>
    T('这份委托用到的记录暂时读不到。', 'The records behind this ticket can’t be read now.'),
  engineer_seeded_ticket_unavailable: () =>
    T('这个情境没有附带工程委托。', 'This situation comes with no engineering ticket.'),
  engineer_request_id_reused: () =>
    T(
      '这次请求和之前的对不上，刷新后再试。',
      'This request clashes with an earlier one. Refresh and try again.',
    ),
};

/** The codes with their own sentence (tests check the documented ones are here). */
export const ENGINEER_ERROR_CODES: readonly string[] = Object.keys(ERRORS);

/** A refusal in one plain sentence; unknown codes get a general sentence, never the code. */
export function engineerErrorText(code: string | undefined | null): string {
  const known = code ? ERRORS[code] : undefined;
  if (known) return known();
  if (code === 'response_unconfirmed')
    return T(
      '结果还没确认。输入还在，稍后再看一次再决定要不要重做。',
      'The result isn’t confirmed yet. Your input is kept; check again before redoing it.',
    );
  return T(
    '没有完成，输入还在，可以再试一次。',
    'That didn’t go through. Your input is kept; try again.',
  );
}

/** A setting's name, as the pilot settings sheet names it. */
export function fieldName(field: string): string {
  return FIELD_NAMES[T('zh', 'en') as 'zh' | 'en'][field] ?? field;
}

// Knowledge domains and work items keep the settings sheet's own words (vocab.js).
const DOMAIN_KEY: Readonly<Record<string, string>> = { stable_faq: 'faq' };
const WORK_KEY: Readonly<Record<string, string>> = {
  scope_filter: 'scope',
  human_fallback: 'fallback',
  realtime_sync: 'realtime',
};

/** One value of a setting in words. */
export function choiceText(field: string, value: string): string {
  switch (field) {
    case 'freshness_guard':
      return (
        { none: T('不处理', 'Off'), warn: T('加提醒', 'Warn'), fallback: T('转人工', 'Hand off') }[
          value
        ] ?? value
      );
    case 'update_strategy':
      return UPDATE(value === 'manual_policy' ? 'manual' : value);
    case 'fallback':
      return FALLBACK(value);
    case 'domains':
    case 'manual_domains':
      return DOMAIN(DOMAIN_KEY[value] ?? value);
    case 'work_items':
      return WORK_ITEM(WORK_KEY[value] ?? value);
    default:
      return value;
  }
}

/** A whole setting value in words: lists joined, booleans as on/off, numbers as written. */
export function valueText(field: string, value: unknown): string {
  if (Array.isArray(value)) {
    if (!value.length) return T('无', 'None');
    return value.map((v) => choiceText(field, String(v))).join(T('、', ', '));
  }
  if (typeof value === 'boolean') return value ? T('开', 'On') : T('关', 'Off');
  if (value === null || value === undefined || value === '') return T('无', 'None');
  return choiceText(field, String(value));
}
