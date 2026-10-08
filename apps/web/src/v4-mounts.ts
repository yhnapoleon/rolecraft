/** Thin ownership/lifecycle bridge into the existing v4 DOM. No business rendering. */
import { WorkspaceRegions } from './features/workspace/native-v4/regions';
import { RolesRegions } from './features/roles-native/regions';
import { ResourceRegions } from './features/roles-native/resource-regions';
import { FeedbackRegions } from './features/feedback-native/regions';
import { AgentRegions } from './features/agent-native/regions';
import type { V4DataHost } from './v4-data-host';
import type { LocalSession } from './types';

type Selection = { taskId: string | null; productId: string | null };
export class V4Mounts {
  private generation = 0;
  private readonly feedback = new FeedbackRegions();
  private readonly roles = new RolesRegions();
  private readonly resources = new ResourceRegions();
  private readonly agent = new AgentRegions();
  constructor(private readonly workspace = new WorkspaceRegions()) {}
  destroy() {
    this.generation++;
    this.feedback.destroy();
    this.roles.destroy();
    this.resources.destroy();
    this.workspace.destroy();
    this.agent.destroy();
  }
  async sync(
    doc: Document,
    session: LocalSession | undefined,
    host: V4DataHost | null,
    selection: Selection,
  ) {
    if (session?.protocol !== 2 || !host) {
      this.destroy();
      return;
    }
    this.workspace.prune(doc, host);
    this.feedback.prune(doc, host);
    this.roles.prune(doc, host);
    this.resources.prune(doc, host);
    this.agent.prune(doc, host);
    if (host.snapshot().state === 'unavailable') await host.query('workbench.read');
    const task = session.v2Workspace?.tasks.find((t) => t.id === selection.taskId);
    const product = session.v2Workspace?.products.find((p) => p.product_id === selection.productId);
    const epoch = ++this.generation;
    await host.reflectSelection(
      task
        ? { session_id: session.id, kind: 'task', object_id: task.id, version: task.revision }
        : null,
      product
        ? {
            session_id: session.id,
            kind: 'product',
            object_id: product.product_id,
            version: product.version,
          }
        : null,
    );
    await host.flushDrafts();
    if (epoch !== this.generation) return;
    this.feedback.sync(doc, host);
    this.roles.sync(doc, host);
    this.resources.sync(doc, host);
    if (session.v2NativeWorkspace) {
      this.workspace.sync(doc, host);
      this.agent.sync(doc, host);
    } else {
      this.workspace.destroy();
      this.agent.destroy();
    }
  }
}
