/** Thin ownership/lifecycle bridge into the existing v4 DOM. No business rendering. */
import { WorkspaceRegions } from './features/workspace/native-v4/regions';
import { RolesRegions } from './features/roles-native/regions';
import { ResourceRegions } from './features/roles-native/resource-regions';
import { FeedbackRegions } from './features/feedback-native/regions';
import { surfaceHost } from './v4-surface-host';
import { mountV4AgentSlot } from './features/agent-native/v4-slot';
import type { V4DataHost } from './v4-data-host';
import type { V4SlotContext, V4SlotHandle } from './v4-host';
import type { LocalSession } from './types';

type Selection = { taskId: string | null; productId: string | null };
type Mounted = {
  host: V4DataHost;
  root: HTMLElement;
  content: Element | null;
  handle: V4SlotHandle;
  clean: () => void;
};
export class V4Mounts {
  private mounted = new Map<string, Mounted>();
  private generation = 0;
  private readonly feedback = new FeedbackRegions();
  private readonly roles = new RolesRegions();
  private readonly resources = new ResourceRegions();
  constructor(private readonly workspace = new WorkspaceRegions()) {}
  destroy() {
    this.generation++;
    this.feedback.destroy();
    this.roles.destroy();
    this.resources.destroy();
    this.workspace.destroy();
    for (const item of this.mounted.values()) {
      item.handle.destroy();
      item.clean();
    }
    this.mounted.clear();
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
    if (host.snapshot().state === 'unavailable') await host.query('workbench.read');
    const roots = new Map<string, HTMLElement>();
    const agentPanel = doc.querySelector<HTMLElement>('#ws-rail .agent-panel[data-agent-native]');
    if (agentPanel && session.v2NativeWorkspace) roots.set('agent', agentPanel);
    for (const [id, current] of this.mounted) {
      if (
        current.host !== host ||
        roots.get(id) !== current.root ||
        current.root.firstElementChild !== current.content ||
        !current.root.isConnected
      ) {
        current.handle.destroy();
        current.clean();
        this.mounted.delete(id);
      }
    }
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
    if (session.v2NativeWorkspace) this.workspace.sync(doc, host);
    else this.workspace.destroy();
    for (const [id, root] of roots) {
      if (this.mounted.has(id)) {
        this.mounted.get(id)!.handle.update(host.snapshot());
        continue;
      }
      const nodes: Record<string, HTMLElement> = {};
      const pick = (name: string, selector: string, within: ParentNode = root) => {
        const node = within.querySelector<HTMLElement>(selector);
        if (node) nodes[name] = node;
      };
      if (id === 'agent') {
        pick('connection', '[data-agent-connection]');
        pick('activity', '[data-agent-activity]');
        pick('returns', '[data-agent-returns]');
      } else {
        nodes.content = root;
      }
      if (!Object.keys(nodes).length) continue;
      // A completion from a destroyed surface may save its authorized command,
      // but must not navigate the user back to a surface they already left.
      let alive = true;
      const adapter = surfaceHost(host, () => alive);
      const context: V4SlotContext = { host: adapter, nodes };
      const handle = mountV4AgentSlot(context);
      this.mounted.set(id, {
        host,
        root,
        content: root.firstElementChild,
        handle,
        clean: () => {
          alive = false;
        },
      });
    }
  }
}
