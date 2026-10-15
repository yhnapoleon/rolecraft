/** Words for requested resources and approval decisions in the request panel. They are the words
 * the recorded business decisions use (business-response.fixtures.json), so the panel and the
 * feedback that quotes the record read alike. */
import { T } from '../../app/i18n';

export type ResourceKey = 'capacity' | 'dev_days' | 'deadline_day';

export const resourceNames = (): Record<ResourceKey, string> => ({
  capacity: T('名额', 'Seats'),
  dev_days: T('开发人日', 'Developer-days'),
  deadline_day: T('截止日', 'Deadline day'),
});

export const decisionNames = (): Record<string, string> => ({
  pending: T('待核实', 'Awaiting rules check'),
  rejected: T('未批准', 'Declined'),
  countered: T('还价待接受', 'Counteroffer awaiting acceptance'),
  approved: T('已批准', 'Approved'),
  accepted: T('已接受', 'Accepted'),
});
