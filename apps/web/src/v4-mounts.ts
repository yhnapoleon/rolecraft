/** Thin ownership/lifecycle bridge into the existing v4 DOM. No business rendering. */
import { mountWorkspaceSlot } from './features/workspace/native-v4/v4-slot';
import { mount as mountRoles } from './features/roles-native/v4-slot';
import { mount as mountResources } from './features/roles-native/v4-request-slot';
import { mountV4Feedback } from './features/feedback-native/v4-slot';
import { mountV4AgentSlot } from './features/agent-native/v4-slot';
import type { V4DataHost } from './v4-data-host';
import type { V4HostAdapter, V4SlotContext, V4SlotHandle } from './v4-host';
import type { LocalSession } from './types';
import { T } from './app/i18n';

type Selection = { taskId: string | null; productId: string | null };
type Mounted = { host: V4DataHost; root: HTMLElement; content: Element | null; handle: V4SlotHandle; clean: () => void };
export class V4Mounts {
  private mounted = new Map<string, Mounted>();
  private generation = 0;
  destroy() {
    this.generation++;
    for (const item of this.mounted.values()) { item.handle.destroy(); item.clean(); }
    this.mounted.clear();
  }
  async sync(doc: Document, session: LocalSession | undefined, host: V4DataHost | null, selection: Selection) {
    const stage = doc.querySelector<HTMLElement>('#ws-stage');
    const sheet = doc.querySelector<HTMLDialogElement>('#sheet');
    if (session?.protocol !== 2 || !host) { this.destroy(); return; }
    if (host.snapshot().state === 'unavailable') await host.query('workbench.read');
    const roots = new Map<string, HTMLElement>();
    if (stage && session.v2NativeWorkspace) roots.set('workspace', stage);
    if (session.v2NativeWorkspace && sheet?.open && sheet.querySelector('#task-form, #artifact-form')) roots.set('workspace-form', sheet.querySelector('.sheet-body')!);
    const chat = doc.querySelector<HTMLElement>('#ws-rail .chat');
    if (chat) roots.set('roles', chat);
    if (sheet?.open && sheet.querySelector('#res-form')) roots.set('resource-requests', sheet.querySelector('.sheet-body')!);
    if (sheet?.open && sheet.querySelector('[data-v4-submission]')) roots.set('submission', sheet.querySelector('[data-v4-submission]')!);
    const feedback = doc.querySelector<HTMLElement>('[data-v4-feedback]');
    if (feedback) roots.set('feedback', feedback);
    const agentPanel = doc.querySelector<HTMLElement>('#ws-rail .agent-panel[data-agent-native]');
    if (agentPanel && session.v2NativeWorkspace) roots.set('agent', agentPanel);
    for (const [id, current] of this.mounted) {
      if (current.host !== host || roots.get(id) !== current.root || current.root.firstElementChild !== current.content || !current.root.isConnected) {
        current.handle.destroy(); current.clean(); this.mounted.delete(id);
      }
    }
    const task = session.v2Workspace?.tasks.find(t => t.id === selection.taskId);
    const product = session.v2Workspace?.products.find(p => p.product_id === selection.productId);
    const epoch = ++this.generation;
    await host.reflectSelection(task ? { session_id: session.id, kind: 'task', object_id: task.id, version: task.revision } : null,
      product ? { session_id: session.id, kind: 'product', object_id: product.product_id, version: product.version } : null);
    await host.flushDrafts();
    if (epoch !== this.generation) return;
    for (const [id, root] of roots) {
      if (this.mounted.has(id)) { this.mounted.get(id)!.handle.update(host.snapshot()); continue; }
      const owned: HTMLElement[] = [], restore: (() => void)[] = [];
      const nodes: Record<string, HTMLElement> = {};
      const pick = (name: string, selector: string, within: ParentNode = root) => {
        const node = within.querySelector<HTMLElement>(selector); if (node) nodes[name] = node;
      };
      const insert = (name: string, parent: HTMLElement | null, tag = 'div', text = '') => {
        if (!parent) return;
        const node = doc.createElement(tag); node.dataset.v4Insertion = name; node.textContent = text;
        parent.append(node); owned.push(node); nodes[name] = node;
        return node;
      };
      if (id === 'workspace') {
        pick('tasks0', '.col-first .cards'); pick('tasks1', '.col-next .cards'); pick('tasks2', '.col-later .cards');
        pick('folder', '[data-work-folder]'); pick('title', '#editor-title'); pick('body', '#editor-body');
        pick('purpose', '[data-edit="purpose"]'); pick('saveStatus', '[data-save]');
        pick('investigation', '.investigation-paper');
        if (nodes.saveStatus) { const title = nodes.saveStatus.title; nodes.saveStatus.dataset.v4Managed = 'true'; nodes.saveStatus.title = T('草稿和服务端作品版本的保存状态', 'Draft and server version save status'); restore.push(() => { delete nodes.saveStatus.dataset.v4Managed; nodes.saveStatus.title = title; }); }
        if (nodes.title || nodes.investigation) {
          const paper = root.querySelector<HTMLElement>('.paper.editor, .paper.investigation-paper');
          const actions = root.querySelector<HTMLElement>('.action-bar') ?? paper;
          insert('actions', actions); insert('sharing', paper); insert('versions', paper);
          for (const button of root.querySelectorAll<HTMLElement>('[data-action="save-work"], [data-action="remove-work"]')) {
            const target = button.closest<HTMLElement>('.icon-control') ?? button;
            const parent = target.parentNode, next = target.nextSibling; target.remove();
            restore.push(() => { if (parent?.isConnected) parent.insertBefore(target, next?.parentNode === parent ? next : null); });
          }
        }
        pick('newTitle', '#new-title'); pick('newBody', '#new-body'); pick('newPurpose', '[data-new="purpose"]');
        if (nodes.newBody) {
          const meta = nodes.newBody.closest('.paper')?.querySelector<HTMLElement>('.editor-meta') ?? null;
          const button = insert('newProduct', meta, 'button', T('保存为作品', 'Save as work')) as HTMLButtonElement | undefined;
          if (button) { button.type = 'button'; button.className = 'btn small primary'; }
          const hint = meta?.querySelector<HTMLElement>(':scope > span');
          if (hint) { const previous = hint.textContent; hint.textContent = T('输入先保留为草稿，保存后形成作品版本', 'Input stays as a draft until you save a version'); restore.push(() => { hint.textContent = previous; }); }
        }
      } else if (id === 'workspace-form') {
        pick('taskTitle', '#task-form [name="title"]'); pick('taskGoal', '#task-form [name="note"]');
        pick('taskForm', '#task-form');
        if (nodes.taskForm?.dataset.id) {
          const shown = session.v2Workspace?.tasks.find(t => t.id === nodes.taskForm.dataset.id);
          if (shown) nodes.taskForm.dataset.revision = String(shown.revision);
        }
        pick('productForm', '#artifact-form');
        pick('taskPriority', '#task-form [name="priority"]:checked');
        pick('taskSplit', '#task-form [name="split"]');
        pick('newTask', '[form="task-form"][type="submit"]', sheet!);
        pick('newTitle', '#artifact-form [name="title"]'); pick('newPurpose', '#artifact-form [name="purpose"]:checked');
        pick('newPurposeGroup', '#artifact-form fieldset'); pick('newTaskId', '#artifact-form [name="taskId"]');
        pick('newProduct', '[form="artifact-form"][type="submit"]', sheet!);
      } else if (id === 'roles') {
        pick('thread', '.thread'); pick('composer', '.composer');
      } else if (id === 'agent') {
        pick('connection', '[data-agent-connection]'); pick('activity', '[data-agent-activity]'); pick('returns', '[data-agent-returns]');
      } else if (id === 'resource-requests') {
        pick('form', '#res-form');
        pick('submit', '[form="res-form"][type="submit"]', sheet!);
      } else {
        nodes.content = root;
      }
      if (!Object.keys(nodes).length) { owned.forEach(n => n.remove()); continue; }
      // A completion from a destroyed surface may save its authorized command,
      // but must not navigate the user back to a surface they already left.
      let alive = true;
      const adapter: V4HostAdapter = {
        snapshot: () => host.snapshot(), subscribe: fn => host.subscribe(fn), query: (op, input) => host.query(op, input),
        command: (op, input) => host.command(op, input), recover: id => host.recover(id), retry: id => host.retry(id),
        draft: (slot, key) => host.draft(slot, key), keepDraft: (slot, key, value) => host.keepDraft(slot, key, value), flushDrafts: () => host.flushDrafts(),
        openReference: ref => host.openReference(ref), chooseEvidence: () => host.chooseEvidence(),
        selectTask: ref => { if (alive) host.selectTask(ref); }, selectProduct: ref => { if (alive) host.selectProduct(ref); },
        announce: (message, kind) => { if (alive) host.announce(message, kind); },
      };
      const context: V4SlotContext = { host: adapter, nodes };
      const handle = id === 'agent' ? mountV4AgentSlot(context)
        : id === 'roles' ? mountRoles(context)
        : id === 'resource-requests' ? mountResources(context)
        : id === 'submission' || id === 'feedback' ? mountV4Feedback({ ...context, surface: id === 'submission' ? 'submission' : 'feedback' })
        : mountWorkspaceSlot(context);
      if (id === 'feedback' && root.dataset.openReview === 'true') {
        const form=root.querySelector<HTMLDetailsElement>('section[aria-label="作品评审"] details, section[aria-label="Artifact review"] details');
        if(form)form.open=true;
      }
      this.mounted.set(id, { host, root, content: root.firstElementChild, handle, clean: () => { alive = false; restore.forEach(fn => fn()); owned.forEach(n => n.remove()); } });
    }
  }
}
