/** Words for requested resources and approval decisions in the request panel. They are the words
 * the recorded business decisions use (business-response.fixtures.json), so the panel and the
 * feedback that quotes the record read alike. */
import { T } from '../../app/i18n';

export type ResourceKey = 'capacity' | 'dev_days' | 'deadline_day';

export const resourceNames = (): Record<ResourceKey, string> => ({
  capacity: T('名额', 'Seats'),
  dev_days: T('开发人日', 'Person-days'),
  deadline_day: T('截止日', 'Deadline day'),
});

const DAY = 'deadline_day';

/** An amount as the panel, the decision cards and the records write it: a deadline is a day. */
export const amountText = (resource: string, n: number) =>
  resource === DAY ? T(`第 ${n} 天`, `day ${n}`) : String(n);

/** One requested term as the recorded decisions write it: "开发人日：申请 7", "截止日：申请第 8 天". */
export function requestedTerm(resource: ResourceKey, n: number) {
  const label = resourceNames()[resource];
  return T(
    resource === DAY ? `${label}：申请第 ${n} 天` : `${label}：申请 ${n}`,
    `${label}: requested ${amountText(resource, n)}`,
  );
}

/** One resource with its amount in a list: "名额 30", "截止日第 7 天"; "Seats: 30". */
export function resourceAmount(resource: ResourceKey, n: number) {
  const label = resourceNames()[resource];
  return T(
    resource === DAY ? `${label}第 ${n} 天` : `${label} ${n}`,
    `${label}: ${amountText(resource, n)}`,
  );
}

export const decisionNames = (): Record<string, string> => ({
  pending: T('待核实', 'Awaiting rules check'),
  rejected: T('未批准', 'Declined'),
  countered: T('还价待接受', 'Counteroffer awaiting acceptance'),
  approved: T('已批准', 'Approved'),
  accepted: T('已接受', 'Accepted'),
});
