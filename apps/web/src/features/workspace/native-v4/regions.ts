import type { MountV4Slot, V4HostAdapter, V4SlotHandle } from '../../../v4-host';
import { NamedRegions } from '../../../v4-regions';
import { T } from '../../../app/i18n';
import { mountWorkspaceSlot } from './v4-slot';

type WorkspaceRegion = 'workspace' | 'workspace-form';

/** Workspace node allocation and lifecycle belong to the workspace module. */
export class WorkspaceRegions extends NamedRegions<WorkspaceRegion> {
  constructor(mount: MountV4Slot = mountWorkspaceSlot) {
    super(['workspace', 'workspace-form'], (name, root, host) => attach(name, root, host, mount));
  }
}

function attach(
  id: WorkspaceRegion,
  root: HTMLElement,
  host: V4HostAdapter,
  mount: MountV4Slot,
): V4SlotHandle {
  const doc = root.ownerDocument;
  const sheet = root.closest<HTMLDialogElement>('dialog');
  const owned: HTMLElement[] = [],
    restore: (() => void)[] = [];
  const nodes: Record<string, HTMLElement> = {};
  const pick = (name: string, selector: string, within: ParentNode = root) => {
    const node = within.querySelector<HTMLElement>(selector);
    if (node) nodes[name] = node;
  };
  const insert = (name: string, parent: HTMLElement | null, tag = 'div', text = '') => {
    if (!parent) return;
    const node = doc.createElement(tag);
    node.dataset.v4Insertion = name;
    node.textContent = text;
    parent.append(node);
    owned.push(node);
    nodes[name] = node;
    return node;
  };
  if (id === 'workspace') {
    pick('tasks0', '.col-first .cards');
    pick('tasks1', '.col-next .cards');
    pick('tasks2', '.col-later .cards');
    pick('folder', '[data-work-folder]');
    pick('title', '#editor-title');
    pick('body', '#editor-body');
    pick('purpose', '[data-edit="purpose"]');
    pick('saveStatus', '[data-save]');
    pick('investigation', '.investigation-paper');
    if (nodes.saveStatus) {
      const title = nodes.saveStatus.title;
      nodes.saveStatus.dataset.v4Managed = 'true';
      nodes.saveStatus.title = T(
        '草稿和服务端作品版本的保存状态',
        'Draft and server version save status',
      );
      restore.push(() => {
        delete nodes.saveStatus.dataset.v4Managed;
        nodes.saveStatus.title = title;
      });
    }
    if (nodes.title || nodes.investigation) {
      const paper = root.querySelector<HTMLElement>('.paper.editor, .paper.investigation-paper');
      const actions = root.querySelector<HTMLElement>('.action-bar') ?? paper;
      insert('actions', actions);
      insert('sharing', paper);
      insert('versions', paper);
      for (const button of root.querySelectorAll<HTMLElement>(
        '[data-action="save-work"], [data-action="remove-work"]',
      )) {
        const target = button.closest<HTMLElement>('.icon-control') ?? button;
        const parent = target.parentNode,
          next = target.nextSibling;
        target.remove();
        restore.push(() => {
          if (parent?.isConnected)
            parent.insertBefore(target, next?.parentNode === parent ? next : null);
        });
      }
    }
    pick('newTitle', '#new-title');
    pick('newBody', '#new-body');
    pick('newPurpose', '[data-new="purpose"]');
    if (nodes.newBody) {
      const meta =
        nodes.newBody.closest('.paper')?.querySelector<HTMLElement>('.editor-meta') ?? null;
      const button = insert('newProduct', meta, 'button', T('保存为作品', 'Save as work')) as
        | HTMLButtonElement
        | undefined;
      if (button) {
        button.type = 'button';
        button.className = 'btn small primary';
      }
      const hint = meta?.querySelector<HTMLElement>(':scope > span');
      if (hint) {
        const previous = hint.textContent;
        hint.textContent = T(
          '输入先保留为草稿，保存后形成作品版本',
          'Input stays as a draft until you save a version',
        );
        restore.push(() => {
          hint.textContent = previous;
        });
      }
    }
  } else if (id === 'workspace-form') {
    pick('taskTitle', '#task-form [name="title"]');
    pick('taskGoal', '#task-form [name="note"]');
    pick('taskForm', '#task-form');
    pick('productForm', '#artifact-form');
    pick('taskPriority', '#task-form [name="priority"]:checked');
    pick('taskSplit', '#task-form [name="split"]');
    pick('newTask', '[form="task-form"][type="submit"]', sheet ?? root);
    pick('newTitle', '#artifact-form [name="title"]');
    pick('newPurpose', '#artifact-form [name="purpose"]:checked');
    pick('newPurposeGroup', '#artifact-form fieldset');
    pick('newTaskId', '#artifact-form [name="taskId"]');
    pick('newProduct', '[form="artifact-form"][type="submit"]', sheet ?? root);
  }
  if (!Object.keys(nodes).length) return { update() {}, destroy() {} };
  const handle = mount({ host, nodes });
  return {
    update: (snapshot) => handle.update(snapshot),
    destroy: () => {
      handle.destroy();
      for (const restoreNode of restore) restoreNode();
      for (const node of owned) node.remove();
    },
  };
}
