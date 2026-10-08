/** Compile-only checks at the public host seam; this module is not an application entry. */
import type { WorkspaceTask, WorkspaceProductRead } from './features/workspace/contract-types';
import type { V4HostAdapter } from './v4-host';

export async function checkHostOperations(host: V4HostAdapter): Promise<void> {
  const tasks: WorkspaceTask[] = (await host.query('work_items.list', { limit: 20 })).items;
  const products: WorkspaceProductRead[] = (await host.query('work_products.list')).items;
  void tasks;
  void products;
  await host.command('work_items.create', { title: 'Investigate' });
  await host.command('work_products.adopt', {
    product_id: 'work',
    product_version: 1,
    expected_head: 1,
    status: 'adopted',
  });
  // @ts-expect-error Only a registered operation is callable.
  await host.query('work_item.list');
  // @ts-expect-error Reading an object requires its exact reference.
  await host.query('objects.read');
  // @ts-expect-error Domain inputs cannot supply a command journal request ID.
  await host.command('work_items.create', { title: 'Work', request_id: 'forged' });
  await host.command('work_products.adopt', {
    product_id: 'work',
    product_version: 1,
    expected_head: 1,
    // @ts-expect-error Adoption status is a closed protocol vocabulary.
    status: 'approved',
  });
}

export async function checkWorkspaceCommands(
  controller: import('./features/workspace/native-v4/slot-controller').WorkspaceSlotController,
): Promise<void> {
  // @ts-expect-error A workspace wrapper must preserve the adoption operation's payload type.
  await controller.command('work_products.adopt', { title: 'Wrong payload' });
  await controller.command('work_products.adopt', {
    product_id: 'work',
    product_version: 1,
    expected_head: 1,
    status: 'adopted',
  });
}

export async function checkPublicResultBoundaries(host: V4HostAdapter): Promise<void> {
  const issued = await host.command('delegations.create', {
    agent_label: 'My agent',
    expires_at: '2026-10-09T03:00:00Z',
  });
  if (issued.result && 'delegation' in issued.result) {
    // @ts-expect-error The one-time private token is not part of a host result.
    void issued.result.token;
  }
  const action = await host.command('actions', {
    tool: 'read_material',
    material: { session_id: 's', kind: 'material', object_id: 'doc', version: 1 },
  });
  const fragment =
    action.result && 'fragments' in action.result ? action.result.fragments?.[0] : undefined;
  if (fragment) {
    // @ts-expect-error Internal fact linkage is removed by the public material projection.
    void fragment.fact_ids;
  }
}
