/** Host-owned routing. Slots pass business DTOs, never URLs or Command envelopes. */
import { ApiError } from './api';
import type { GatewayMethod } from './gateway-transport';
type Input = Readonly<Record<string, unknown>>;
export type Route = { path: string; method: GatewayMethod; action: string };
const fail = () => { throw new ApiError('Operation is unavailable', 400, 'operation_not_public'); };
const id = (input: Input, key: string) => {
  const value = input[key];
  if (typeof value !== 'string' || !value) return fail();
  return encodeURIComponent(value);
};
const reads: Record<string, string> = {
  'workbench.read': '/workbench', 'materials.list': '/materials', timeline: '/timeline',
  'tests.list': '/tests', 'submissions.list': '/submissions', 'work_items.list': '/work-items',
  'work_products.list': '/work-products', 'workspace_imports.list': '/workspace-imports',
  observation: '/observation', tools: '/tools', 'delegations.list': '/delegations',
};
export function readRoute(operation: string, input: Input = {}): string {
  let path = reads[operation];
  if (operation === 'session.read') return '';
  if (operation === 'objects.read') path = '/objects/' + id(input, 'kind') + '/' + id(input, 'object_id') + '/' + id({ version: String(input.version) }, 'version');
  if (operation === 'work_products.versions.list') path = '/work-products/' + id(input, 'product_id') + '/versions';
  if (operation === 'work_products.shares.list') path = '/work-products/' + id(input, 'product_id') + '/shares';
  if (operation === 'feedback.read') path = '/feedback/' + id(input, input.review_id != null ? 'review_id' : 'submission_id');
  if (operation === 'feedback.records.read') path = '/feedback-records/' + id(input, 'feedback_id');
  if (operation === 'feedback.responses.list') path = '/feedback/' + id(input, 'feedback_id') + '/responses';
  if (operation === 'feedback.responses.read') path = '/feedback-responses/' + id(input, 'response_id');
  if (operation === 'reviews.read') path = input.review_id == null ? '/reviews' : '/reviews/' + id(input, 'review_id');
  if (operation === 'workspace_imports.read') path = '/workspace-imports/' + id(input, 'import_id');
  if (!path) return fail();
  const query = new URLSearchParams();
  for (const key of ['cursor', 'limit', 'since_seq', 'as_of_seq', 'config_version']) {
    if (input[key] != null) query.set(key, String(input[key]));
  }
  return path + (query.size ? '?' + query : '');
}
export function commandRoute(operation: string, input: Input): Route {
  const fixed: Record<string, string> = {
    'configuration.apply': '/configuration', actions: '/actions', 'tests.create': '/tests', 'turns.create': '/turns', 'turns.display': '/turns/display',
    'approvals.resolve': '/approvals/resolve', 'submissions.create': '/submissions', 'reviews.create': '/reviews',
    'feedback.create': '/feedback', begin_revision: '/revision-cycles', revision_cycles: '/revision-cycles',
    'work_items.create': '/work-items', 'work_items.batch': '/work-items/batch', 'work_products.create': '/work-products',
    workspace_imports: '/workspace-imports', 'delegations.create': '/delegations',
  };
  let path = fixed[operation], method: GatewayMethod = 'POST', action = operation;
  if (operation === 'actions') { if (typeof input.tool !== 'string' || !input.tool) return fail(); action = input.tool; }
  if (operation === 'approvals.resolve') action = 'resolve_approval';
  if (operation === 'revision_cycles') action = 'begin_revision';
  if (operation === 'work_items.update') { path = '/work-items/' + id(input, 'item_id'); method = 'PATCH'; }
  if (operation === 'work_products.versions.create') path = '/work-products/' + id(input, 'product_id') + '/versions';
  if (operation === 'work_products.adopt') path = '/work-products/' + id(input, 'product_id') + '/adoption';
  if (operation === 'work_products.shares.create') path = '/work-products/' + id(input, 'product_id') + '/shares';
  if (operation === 'work_products.shares.change') path = '/work-products/' + id(input, 'product_id') + '/shares/' + id(input, 'share_id');
  if (operation === 'feedback.responses.create') path = '/feedback/' + id(input, 'feedback_id') + '/responses';
  if (operation === 'jobs.refresh') path = '/jobs/' + id(input, 'job_id') + '/refresh';
  if (operation === 'delegations.revoke') { path = '/delegations/' + id(input, 'delegation_id'); method = 'DELETE'; }
  if (!path) return fail();
  return { path, method, action };
}
