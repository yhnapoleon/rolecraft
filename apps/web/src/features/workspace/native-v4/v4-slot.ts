import type { V4SlotContext, V4SlotHandle, V4HostSnapshot } from '../../../v4-host';
import type {
  WorkspaceTask,
  WorkspaceProductRead,
  ProductCreate,
  InvestigationPayload,
} from '../contract-types';
import { WorkspaceSlotController, productRef, taskRef } from './slot-controller';
import { workspaceActionMessage } from './messages';
import './v4-slot.css';
import { mountImport } from './import-slot';
import {
  canonicalPurpose,
  controlValue,
  writePurpose,
  disableControl,
  taskPriority,
} from './form-values';
import { bindWorkspaceForm } from './form-slot';
import { changedMaterials, outcomeView, renderOutcome, type PreviewEntry } from './outcome-preview';
import { recipientShares, rememberRequest } from '../../roles-native/v4-data';
import { agentMark, avatar, icon, PEOPLE, priMark, statusMark } from '../../../app/art.js';
import { workFolderMarkup } from '../../../app/work-folder.js';
import { PRI, STATUS, purposeLabel } from '../../../app/vocab.js';
import { cardPeople, taskCardFacts, taskProgress } from './card-facts';

const PRIORITY_KEYS = ['first', 'next', 'later'] as const;
/** A board card keeps keyboard focus through a move, even when the board remounts this slot. */
let pendingTaskFocus: { id: string; control: string; until?: number } | undefined;

/** Bind only nodes assigned by the v4 host. See v4-slot.md for exact node keys.
 * No application root, navigation, credentials, transport or request journal. */
export function mount(context: V4SlotContext): V4SlotHandle {
  const host = context.host;
  const nodes: Readonly<Record<string, HTMLElement>> = context.nodes;
  const doc = Object.values(nodes)[0]?.ownerDocument;
  if (!doc) throw Error('W03 slot requires an assigned node');
  const listeners: (() => void)[] = [],
    owned: HTMLElement[] = [];
  let destroyed = false,
    rendered = '',
    renderedVersion: number | undefined,
    readKey = '',
    history: WorkspaceProductRead[] = [],
    historyKey = '';
  let draftRendering = false,
    removeConfirmation = false,
    comparison: { head: number; token: string } | undefined;
  const controller = new WorkspaceSlotController(host, () => {
    if (!draftRendering) render();
  });
  const forms: ReturnType<typeof bindWorkspaceForm>[] = [];
  const T = (zh: string, en: string) => (host.snapshot().uiLanguage === 'en' ? en : zh);
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', cls = '') => {
    const n = doc.createElement(tag);
    n.textContent = text;
    n.className = cls;
    return n;
  };
  const on = (node: HTMLElement | undefined, event: string, fn: (e: Event) => void) => {
    if (!node) return;
    node.addEventListener(event, fn);
    listeners.push(() => node.removeEventListener(event, fn));
  };
  const input = (name: string) =>
    nodes[name] as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | undefined;
  const status = nodes.saveStatus;
  const message = (code: string) => workspaceActionMessage(code, T);
  const act = async (action: () => unknown | Promise<unknown>) => {
    try {
      await action();
    } catch (error) {
      host.announce(message(error instanceof Error ? error.message : ''), 'error');
    } finally {
      render();
    }
  };
  const button = (
    zh: string,
    en: string,
    action: () => unknown | Promise<unknown>,
    cls = 'quiet small',
  ) => {
    const b = el('button', T(zh, en), 'btn ' + cls);
    b.type = 'button';
    b.addEventListener('click', (event) => {
      if (destroyed) return;
      event.preventDefault();
      event.stopPropagation();
      void act(action);
    });
    return b;
  };
  const add = (name: string, node: HTMLElement) => {
    if (nodes[name]) {
      node.classList.add('w03-slot-content');
      nodes[name].append(node);
      owned.push(node);
    }
  };
  // Permanent editor controls; never replace the host's original input nodes.
  const controls = el('div', '', 'row-actions');
  const save = button('保存这版', 'Save this version', () => controller.save(), 'primary small');
  const copy = button('另存草稿', 'Save draft as a copy', async () => {
    const token = controller.draft()?.token;
    const result = await controller.saveCopy();
    if (!destroyed && controller.draft()?.token === token)
      controller.selectConfirmedProduct(result);
  });
  const refresh = button('读取工作区更新', 'Refresh workspace', () => controller.refresh());
  const reference = button('引用这版', 'Reference this version', () => {
    const p = controller.selected();
    if (p) return host.openReference(productRef(p));
  });
  const recover = button('查看上一请求结果', 'Check previous request', () => controller.recover());
  const retry = button('重新尝试', 'Try again', () => controller.recover(true));
  const remove = button('移除作品', 'Remove product', () => {
    removeConfirmation = true;
    render();
  });
  const confirmRemove = button(
    '确认移除并撤回全部分享',
    'Confirm removal and revoke all shares',
    async () => {
      await controller.remove(true);
      removeConfirmation = false;
    },
  );
  const restore = button('恢复作品', 'Restore product', async () => {
    const result = await controller.remove(false);
    if (result.status === 'confirmed')
      host.announce(
        T(
          '作品已恢复；此前分享仍已撤回，需要时请重新分享。',
          'Product restored. Previous shares remain revoked; share again when needed.',
        ),
      );
  });
  const adopt = button('检查后采用这版', 'Adopt this reviewed version', () => {
    const p = controller.selected();
    if (p)
      return controller.command('work_products.adopt', {
        product_id: p.product_id,
        product_version: p.version,
        expected_head: p.version,
        status: 'adopted',
      });
  });
  controls.append(
    save,
    copy,
    refresh,
    reference,
    recover,
    retry,
    adopt,
    remove,
    confirmRemove,
    restore,
  );
  add('actions', controls);
  const compare = el('details'),
    compareCaption = el('summary'),
    serverContent = el('pre', '', 'w03-slot-text');
  const merge = button(
    '已比较，保存这份草稿',
    'Reviewed: save this draft',
    () => controller.save(comparison),
    'primary small',
  );
  compare.append(compareCaption, serverContent, merge);
  add('actions', compare);
  const shareBox = el('div'),
    visibility = el('p', '', 'muted'),
    shareVersion = el('p', '', 'muted'),
    shareList = el('div');
  const recipient = el('select'),
    question = el('textarea');
  question.rows = 2;
  for (const role of ['supervisor', 'business_lead', 'tech_lead']) {
    const option = el('option');
    option.value = role;
    recipient.append(option);
  }
  const share = button('分享已保存的这版', 'Share this saved version', async () => {
    const text = question.value,
      role = recipient.value;
    const result = await controller.share(role, text);
    if (result.status === 'confirmed') {
      if (question.value === text) {
        question.value = '';
        rememberShare();
      }
      await discuss(role, text);
    }
  });
  shareBox.append(visibility, shareVersion, recipient, question, share, shareList);
  add('sharing', shareBox);
  const historyBox = el('details'),
    historyCaption = el('summary'),
    historyRows = el('div');
  const loadHistory = button('读取已保存版本', 'Load saved versions', async () => {
    const p = controller.selected();
    if (!p) return;
    const key = versionKey();
    const rows = await controller.versions(p.product_id);
    if (key === versionKey()) {
      history = rows;
      historyKey = key;
      render();
    }
  });
  historyBox.append(historyCaption, loadHistory, historyRows);
  add('versions', historyBox);
  // Saved outcome previews of the shown version: read only, never re-evaluated or executed.
  const outcomeBox = el('div');
  add('outcome', outcomeBox);
  let outcomeEntries: PreviewEntry[] = [],
    outcomeTitles: Record<string, string> = {},
    outcomeFor = '',
    outcomeLoading = '',
    outcomeShown = '';
  function showOutcome(p: WorkspaceProductRead | undefined, hasDraft: boolean) {
    if (!nodes.outcome) return;
    const language = host.snapshot().uiLanguage === 'en' ? 'en' : 'zh';
    const identity = p ? `${p.session_id}:${p.product_id}:` : '';
    if (p) {
      const key = `${identity}${p.version}:${JSON.stringify(controller.state.asOf)}`;
      if (key !== outcomeFor && key !== outcomeLoading) {
        outcomeLoading = key;
        void controller
          .previews(p.product_id)
          .then(async (entries) => ({
            entries,
            titles: changedMaterials(entries)
              ? await controller.materialTitles().catch(() => ({}))
              : {},
          }))
          .then(
            ({ entries, titles }) => {
              if (destroyed || outcomeLoading !== key) return;
              outcomeEntries = entries;
              outcomeTitles = titles;
              outcomeFor = key;
              outcomeLoading = '';
              render();
            },
            () => {
              // Keep what was shown; a later workspace change reads again.
              if (outcomeLoading === key) outcomeLoading = '';
              if (!outcomeFor.startsWith(identity)) outcomeEntries = [];
              outcomeFor = key;
            },
          );
      }
    }
    const view =
      p && outcomeFor.startsWith(identity)
        ? outcomeView(
            outcomeEntries,
            { version: p.version, hasDraft },
            language,
            (operation) => controller.can(operation),
            outcomeTitles,
          )
        : null;
    const signature = JSON.stringify([view, language]);
    if (signature === outcomeShown) return;
    outcomeShown = signature;
    const open = [...outcomeBox.querySelectorAll('details')].map((node) => node.open);
    outcomeBox.replaceChildren(...(view ? [renderOutcome(doc, view, language)] : []));
    outcomeBox.querySelectorAll('details').forEach((node, index) => {
      if (open[index]) node.open = true;
    });
  }
  const roleLabel = (role: string) =>
    (
      ({
        supervisor: T('经理', 'Manager'),
        business_lead: T('陈敏（业务负责人）', 'Chen Min (business lead)'),
        tech_lead: T('技术负责人', 'Technical lead'),
      }) as Record<string, string>
    )[role] ?? T('指定同事', 'Selected colleague');
  // An explicit share opens a discussion with that colleague: the person's own question (or a plain
  // note that they shared this exact version) is sent together with the colleague's current shares.
  const discuss = async (role: string, text: string) => {
    const p = controller.selected();
    if (!p) return;
    const words =
      text.trim() ||
      T(
        `我分享了《${p.title || '作品'}》第 ${p.version} 版，想请你看看。`,
        `I shared “${p.title || 'my work'}” v${p.version}. Could you take a look?`,
      );
    try {
      const shares = await recipientShares(host, p.session_id, role);
      const turn = await host.command('turns.create', {
        role_id: role,
        text: words,
        shares,
        ...(p.task ? { task: p.task } : {}),
      });
      await rememberRequest(host, 'roles', turn);
      // A colleague reply is a queued job, so an accepted message reports "pending".
      if (turn.status !== 'confirmed' && turn.status !== 'pending') {
        host.announce(
          T(
            '已分享；对话请求尚未确认，可在同事对话里重试。',
            'Shared. The message is not confirmed yet; retry it in the colleague conversation.',
          ),
          'error',
        );
        return;
      }
      host.announce(
        T(
          `已分享，并请${roleLabel(role)}在对话里回应。`,
          `Shared. ${roleLabel(role)} will reply in the conversation.`,
        ),
        'status',
      );
      document.dispatchEvent(new CustomEvent('rolecraft:open-chat', { detail: { roleId: role } }));
    } catch {
      host.announce(
        T(
          '已分享；请到同事对话里继续讨论。',
          'Shared. Continue the discussion in the colleague conversation.',
        ),
        'status',
      );
    }
  };
  const versionKey = () =>
    controller.selected()?.session_id +
    ':' +
    controller.selected()?.product_id +
    ':' +
    JSON.stringify(controller.state.asOf);
  const hasDraft = () => !!controller.draft();

  function edit(name: string, field: 'title' | 'content' | 'purpose') {
    const n = input(name);
    if (!n) return;
    const update = (event: Event) => {
      event.stopPropagation();
      if ((event as InputEvent).isComposing) return;
      draftRendering = true;
      void controller
        .edit({
          [field]:
            field === 'purpose' ? canonicalPurpose(controlValue(nodes[name]) ?? '') : n.value,
        })
        .catch((error) => host.announce(message(error.message), 'error'))
        .finally(() => {
          draftRendering = false;
          render();
        });
    };
    on(n, name === 'purpose' ? 'change' : 'input', update);
    if (name === 'purpose') on(n, 'input', (event) => event.stopPropagation());
    on(n, 'compositionend', update);
    on(n, 'focusout', (e) => e.stopPropagation());
  }
  edit('title', 'title');
  edit('body', 'content');
  edit('purpose', 'purpose');
  // Keep original investigation controls and payload IDs/references intact.
  const investigation = (event: Event) => {
    const target = event.target as HTMLInputElement;
    const data = target?.dataset;
    if (!data || (event as InputEvent).isComposing) return;
    let promise: Promise<unknown> | undefined;
    if (data.investigationQuestion !== undefined)
      promise = controller.editInvestigation('question', target.value);
    else if (data.investigationReview === 'focus')
      promise = controller.editInvestigation('review_focus', target.value);
    else if (data.investigationReview === 'note')
      promise = controller.editInvestigation('review_note', target.value);
    else if (data.w03BlockText) promise = controller.editBlock(data.w03BlockText, target.value);
    if (promise) {
      event.stopPropagation();
      void promise.catch((error) => host.announce(message(error.message), 'error'));
    }
  };
  on(nodes.investigation, 'input', investigation);
  on(nodes.investigation, 'change', investigation);
  on(nodes.investigation, 'compositionend', investigation);
  on(nodes.investigation, 'click', (event) => {
    const target = (event.target as Element).closest<HTMLElement>(
      '[data-action="investigation-review-save"]',
    );
    if (target) {
      event.preventDefault();
      event.stopPropagation();
      void act(() => controller.save());
    }
  });
  const rememberShare = () => {
    const p = controller.selected();
    if (p)
      void host
        .keepDraft('workspace', p.session_id + ':share-question:' + p.product_id, {
          question: question.value,
          recipient: recipient.value,
        })
        .catch(() => host.announce(message('draft_storage_failed'), 'error'));
  };
  on(question, 'input', rememberShare);
  on(recipient, 'change', rememberShare);
  let formSession = JSON.stringify([
    host.snapshot().session?.sessionId,
    host.snapshot().currentTask?.object_id,
  ]);
  const formFields = [
    'taskTitle',
    'taskGoal',
    'taskPriority',
    'newTitle',
    'newBody',
    'newPurpose',
    'newKind',
    'newTaskId',
  ] as const;
  const formKey = (name: string) =>
    host.snapshot().session?.sessionId +
    ':form:' +
    (name.startsWith('new') ? (host.snapshot().currentTask?.object_id ?? 'unassigned') + ':' : '') +
    name;
  for (const name of formFields) {
    if (
      (name.startsWith('task') && nodes.taskForm) ||
      (name.startsWith('new') && nodes.productForm)
    )
      continue;
    const node = input(name);
    if (!node) continue;
    const restored = host.draft<string>('workspace', formKey(name));
    if (restored !== undefined) {
      if (name === 'newPurpose') writePurpose(nodes[name], restored);
      else node.value = restored;
    }
    const keep = (event: Event) => {
      event.stopPropagation();
      void host
        .keepDraft('workspace', formKey(name), controlValue(nodes[name]) ?? '')
        .catch(() => host.announce(message('draft_storage_failed'), 'error'));
    };
    on(node, 'input', keep);
    on(node, 'change', keep);
    on(node, 'focusout', (event) => event.stopPropagation());
  }
  on(nodes.taskForm ? undefined : nodes.newTask, 'click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    void act(async () => {
      const sid = host.snapshot().session?.sessionId;
      const values = {
        taskTitle: input('taskTitle')?.value ?? '',
        taskGoal: input('taskGoal')?.value ?? '',
      };
      const result = await controller.createTask(
        values.taskTitle,
        values.taskGoal,
        taskPriority(controlValue(nodes.taskPriority) ?? '0'),
      );
      if (result.status === 'confirmed' && host.snapshot().session?.sessionId === sid) {
        for (const name of ['taskTitle', 'taskGoal'] as const) {
          const node = input(name);
          if (node && node.value === values[name]) {
            node.value = '';
            await host.keepDraft('workspace', sid + ':form:' + name, '');
          }
        }
      }
    });
  });
  on(nodes.productForm ? undefined : nodes.newProduct, 'click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    void act(async () => {
      const selectedTaskId = controlValue(nodes.newTaskId);
      const chosenTask = selectedTaskId
        ? controller.state.tasks.find((t) => t.id === selectedTaskId && t.status !== 'removed')
        : undefined;
      if (selectedTaskId && !chosenTask) throw Error('task_not_available');
      const task = nodes.newTaskId
        ? chosenTask
          ? taskRef(chosenTask)
          : null
        : host.snapshot().currentTask;
      const kind = (input('newKind')?.value ?? 'text') as ProductCreate['kind'];
      if (!['text', 'plan', 'test_plan', 'options', 'investigation'].includes(kind))
        throw Error('invalid_kind');
      const captured = {
        title: input('newTitle')?.value ?? '',
        content: input('newBody')?.value ?? '',
        purpose: controlValue(nodes.newPurpose),
        kind: input('newKind')?.value,
        taskId: controlValue(nodes.newTaskId),
        context: host.snapshot().currentTask?.object_id,
      };
      const result = await controller.create({
        kind,
        title: captured.title,
        content: captured.content,
        purpose: canonicalPurpose(captured.purpose ?? 'exploration'),
        task,
      });
      const unchanged =
        !destroyed &&
        captured.title === (input('newTitle')?.value ?? '') &&
        captured.content === (input('newBody')?.value ?? '') &&
        captured.purpose === controlValue(nodes.newPurpose) &&
        captured.kind === input('newKind')?.value &&
        captured.taskId === controlValue(nodes.newTaskId) &&
        captured.context === host.snapshot().currentTask?.object_id;
      if (result.status === 'confirmed' && unchanged) {
        for (const name of ['newTitle', 'newBody']) {
          if (input(name)) {
            input(name)!.value = '';
            await host.keepDraft('workspace', formKey(name), '');
          }
        }
        controller.selectConfirmedProduct(result);
      } else if (result.status === 'confirmed')
        host.announce(
          T(
            '此前作品已保存；新增文字仍在原处。',
            'The earlier product was saved; newer text remains here.',
          ),
        );
    });
  });
  // Existing folder owns layout/animation. Only its actual saved product is selected.
  on(nodes.folder, 'click', (event) => {
    const target = (event.target as Element).closest<HTMLElement>('[data-folder-card]');
    if (!target) return;
    const p = controller.state.products.find((p) => p.product_id === target.dataset.folderCard);
    if (!p) return;
    event.stopPropagation();
    void act(async () => {
      await controller.flush();
      host.selectProduct(productRef(p));
    });
  });

  // The card follows the board-card row of the design notes (frontend-style 3.6): progress
  // circle, title, latest work and its purpose, work and test counts, colleague reminders,
  // the stale-test and Agent-return flags, and the work folder. Ordering and pausing live in
  // the card's "⋯" menu; Option/Alt + arrows and dragging the card do the same.
  const lanesOrdered = (priority: number) =>
    controller.state.tasks
      .filter((t) => t.status !== 'removed' && (t.priority ?? 0) === priority)
      .sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || a.id.localeCompare(b.id));
  const priorityKey = (n: number | undefined) => PRIORITY_KEYS[n ?? 0] ?? 'first';
  const markup = (cls: string, html: string, tag: keyof HTMLElementTagNameMap = 'span') => {
    const node = el(tag, '', cls);
    node.innerHTML = html;
    return node;
  };
  const say = (zh: string, en: string) => host.announce(T(zh, en), 'status');
  /** The card keeps focus on itself through a move: the next render, here or after a remount,
   * puts focus back on the same control of the same task. */
  const keepFocus = (taskId: string, control = 'open') => {
    pendingTaskFocus = { id: taskId, control, until: Date.now() + 8000 };
  };
  const lanes = () =>
    (['tasks0', 'tasks1', 'tasks2', 'taskList'] as const).flatMap((n) => (nodes[n] ? [nodes[n]] : []));
  const lanesOwn = (node: Element) => lanes().some((lane) => lane.contains(node));
  /** Put focus back on the card control that had it before a re-render or remount. Only when
   * nothing else holds focus, and never once the person has moved on. */
  function restoreTaskFocus(blocked: boolean) {
    const want = pendingTaskFocus;
    if (!want || blocked) return;
    if (want.until && Date.now() > want.until) {
      pendingTaskFocus = undefined;
      return;
    }
    const active = doc.activeElement as HTMLElement | null;
    if (active && active !== doc.body && active.isConnected) {
      if (!lanesOwn(active)) pendingTaskFocus = undefined;
      return;
    }
    for (const lane of lanes()) {
      const card = [...lane.querySelectorAll<HTMLElement>('[data-task-id]')].find(
        (node) => node.dataset.taskId === want.id,
      );
      const target =
        card?.querySelector<HTMLElement>(`[data-w03-task-control="${want.control}"]:not(:disabled)`) ??
        card?.querySelector<HTMLElement>('[data-w03-task-control="open"]');
      if (target) {
        target.focus({ preventScroll: true });
        pendingTaskFocus = undefined;
        return;
      }
    }
  }
  const reportPlace = (taskId: string) => {
    const moved = controller.state.tasks.find((t) => t.id === taskId);
    if (!moved) return;
    const lane = lanesOrdered(moved.priority ?? 0);
    const place = lane.findIndex((t) => t.id === taskId) + 1;
    const name = PRI(priorityKey(moved.priority));
    say(
      `「${moved.title}」现在在${name}第 ${place} 位，共 ${lane.length} 项`,
      `“${moved.title}” is now ${place} of ${lane.length} in ${name}`,
    );
  };
  const movePriority = (task: WorkspaceTask, to: number) =>
    act(async () => {
      if (to < 0 || to > 2) {
        say('已经到头了', 'Already at the end');
        return;
      }
      keepFocus(task.id);
      await controller.patchTask(task, { priority: to });
      reportPlace(task.id);
    });
  const moveOrder = (task: WorkspaceTask, direction: -1 | 1) =>
    act(async () => {
      const lane = lanesOrdered(task.priority ?? 0);
      const index = lane.findIndex((t) => t.id === task.id);
      if (index + direction < 0 || index + direction >= lane.length) {
        say('已经到头了', 'Already at the end');
        return;
      }
      keepFocus(task.id);
      await controller.moveTask(task, direction);
      reportPlace(task.id);
    });
  let openMenu: { menu: HTMLElement; more: HTMLButtonElement } | undefined;
  function closeMenu(focusButton = false) {
    if (!openMenu) return;
    const { menu, more } = openMenu;
    openMenu = undefined;
    menu.hidden = true;
    more.setAttribute('aria-expanded', 'false');
    more.closest('.card')?.classList.remove('menu-open');
    if (focusButton) more.focus({ preventScroll: true });
  }
  on(doc.documentElement, 'pointerdown', (event) => {
    if (openMenu && !openMenu.menu.parentElement?.contains(event.target as Node)) closeMenu();
  });
  function cardMenu(task: WorkspaceTask, canMove: boolean, canUpdate: boolean) {
    const tools = el('div', '', 'card-tools');
    const more = el('button', '', 'btn icon quiet small card-more') as HTMLButtonElement;
    more.type = 'button';
    more.innerHTML = icon('more');
    more.setAttribute('aria-haspopup', 'menu');
    more.setAttribute('aria-expanded', 'false');
    more.setAttribute('aria-label', T(`「${task.title}」的更多操作`, `More for “${task.title}”`));
    more.dataset.w03TaskControl = 'more';
    more.draggable = false;
    const menu = el('div', '', 'menu card-menu');
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', T(`「${task.title}」`, `“${task.title}”`));
    menu.hidden = true;
    const item = (
      text: string,
      control: string,
      run: (() => unknown) | null,
      role = 'menuitem',
      html = '',
    ) => {
      const node = el('button', '', '') as HTMLButtonElement;
      node.type = 'button';
      node.setAttribute('role', role);
      node.tabIndex = -1;
      node.innerHTML = html;
      node.append(el('span', text, 'grow'));
      node.dataset.w03TaskControl = control;
      if (run)
        node.addEventListener('click', (event) => {
          if (destroyed) return;
          event.preventDefault();
          event.stopPropagation();
          closeMenu();
          void run();
        });
      return node;
    };
    const cap = el('p', T('优先级', 'Priority'), 'menu-cap');
    cap.setAttribute('aria-hidden', 'true');
    const group = el('div', '', 'card-menu-group');
    group.setAttribute('role', 'group');
    group.setAttribute('aria-label', T(`优先级：${task.title}`, `Priority: ${task.title}`));
    PRIORITY_KEYS.forEach((key, n) => {
      const choice = item(
        PRI(key),
        `priority-${n}`,
        () => (n === (task.priority ?? 0) ? undefined : movePriority(task, n)),
        'menuitemradio',
        priMark(key),
      );
      choice.setAttribute('aria-checked', String(n === (task.priority ?? 0)));
      choice.disabled = !canUpdate;
      group.append(choice);
    });
    const line = el('div', '', 'card-menu-sep');
    line.setAttribute('role', 'separator');
    const up = item(T('上移', 'Move up'), 'up', () => moveOrder(task, -1));
    const down = item(T('下移', 'Move down'), 'down', () => moveOrder(task, 1));
    const lane = lanesOrdered(task.priority ?? 0);
    const index = lane.findIndex((t) => t.id === task.id);
    up.disabled = !canMove || index <= 0;
    down.disabled = !canMove || index < 0 || index >= lane.length - 1;
    const paused = task.status === 'paused';
    const pause = item(
      paused ? T('继续这件事', 'Resume task') : T('暂停这件事', 'Pause task'),
      'pause',
      () =>
        act(async () => {
          keepFocus(task.id);
          await controller.patchTask(task, { status: paused ? 'open' : 'paused' });
        }),
    );
    pause.disabled = !canUpdate;
    // Editing opens the existing task sheet through the shell's own action.
    const edit = item(T('编辑这件事', 'Edit task'), 'edit', null);
    edit.dataset.action = 'edit-task';
    edit.dataset.id = task.id;
    edit.addEventListener('click', () => closeMenu());
    menu.append(cap, group, line, up, down, pause, edit);
    const items = () =>
      [...menu.querySelectorAll<HTMLButtonElement>('button')].filter((b) => !b.disabled);
    more.addEventListener('click', (event) => {
      if (destroyed) return;
      event.preventDefault();
      event.stopPropagation();
      if (openMenu?.menu === menu) {
        closeMenu(true);
        return;
      }
      closeMenu();
      openMenu = { menu, more };
      menu.hidden = false;
      more.setAttribute('aria-expanded', 'true');
      tools.closest('.card')?.classList.add('menu-open');
      (menu.querySelector<HTMLButtonElement>('[aria-checked="true"]:not(:disabled)') ?? items()[0])
        ?.focus({ preventScroll: true });
    });
    menu.addEventListener('keydown', (event) => {
      const list = items(),
        at = list.indexOf(doc.activeElement as HTMLButtonElement);
      const go = (n: number) => list[(n + list.length) % list.length]?.focus();
      if (event.key === 'ArrowDown') go(at + 1);
      else if (event.key === 'ArrowUp') go(at - 1);
      else if (event.key === 'Home') go(0);
      else if (event.key === 'End') go(list.length - 1);
      else if (event.key === 'Escape') closeMenu(true);
      else if (event.key === 'Tab') {
        closeMenu();
        return;
      } else return;
      event.preventDefault();
      event.stopPropagation();
    });
    tools.append(more, menu);
    return tools;
  }
  function taskCard(task: WorkspaceTask, index: number) {
    const facts = taskCardFacts(task.id);
    const works = controller.state.products
      .filter((p) => p.task?.object_id === task.id && !p.removed_at)
      .sort((a, b) => a.created_at.localeCompare(b.created_at));
    const progress = taskProgress(task.status, {
      works: works.length,
      tests: facts?.tests,
      asked: facts?.asked,
    });
    const row = el('li', '', `card ${progress}${task.status === 'paused' ? ' paused' : ''}`);
    row.dataset.taskId = task.id;
    row.style.setProperty('--i', String(index));
    const canMove = !controller.blocked() && controller.can('work_items.batch');
    const canUpdate = !controller.blocked() && controller.can('work_items.update');
    // Dragging reorders through the board's own drop handling (priority and order).
    row.draggable = canMove && canUpdate;
    const open = el('button', '', 'card-open') as HTMLButtonElement;
    open.type = 'button';
    open.dataset.id = task.id;
    open.dataset.w03TaskControl = 'open';
    open.setAttribute('aria-describedby', 'move-help');
    open.addEventListener('click', (event) => {
      if (destroyed) return;
      event.preventDefault();
      event.stopPropagation();
      void act(async () => {
        await controller.flush();
        host.selectTask(taskRef(task));
      });
    });
    const head = markup('card-head', statusMark(progress));
    head.title = STATUS(progress);
    head.append(el('span', task.title, 'card-title'), el('span', STATUS(progress), 'sr-only'));
    const latest = works.at(-1);
    // Work line: the latest work's title on paper (serif), its version and purpose small.
    const recent = el(
      'span',
      latest ? '' : T('还没有作品', 'No work yet'),
      'card-latest' + (latest ? '' : ' empty'),
    );
    if (latest) {
      recent.append(el('span', latest.title || T('未命名作品', 'Untitled work'), 'card-work'));
      const about = [
        T(`第 ${latest.version} 版`, `version ${latest.version}`),
        ...(latest.purpose ? [purposeLabel(latest.purpose)] : []),
      ].join(' · ');
      recent.append(el('small', about, 'card-work-about'));
    }
    // Foot: counts in words, the states that need a look, then who left a reminder (right).
    const meta = el('span', '', 'card-meta');
    const count = (glyph: string, words: string) => {
      const node = markup('card-count', icon(glyph, 'i-xs'));
      node.append(words);
      return node;
    };
    if (works.length)
      meta.append(count('note', T(`${works.length} 份作品`, `${works.length} ${works.length === 1 ? 'work' : 'works'}`)));
    if (facts?.tests)
      meta.append(count('flask', T(`${facts.tests} 次测试`, `${facts.tests} ${facts.tests === 1 ? 'test' : 'tests'}`)));
    if (facts?.testsPredatePolicy) {
      const chip = markup('flag-chip warn', icon('stale', 'i-xs'));
      chip.append(
        Number.isFinite(facts.policyVersion)
          ? T(`测试早于政策 v${facts.policyVersion}`, `Tests predate policy v${facts.policyVersion}`)
          : T('测试早于政策更新', 'Tests predate the policy update'),
      );
      meta.append(chip);
    }
    const toCheck = works.filter(
      (p) => !!p.source_return_id && p.adoption?.status !== 'adopted',
    ).length;
    if (toCheck) {
      const chip = markup('flag-chip agent', agentMark('xs'));
      chip.append(T(`${toCheck} 份回传待检查`, `${toCheck} agent return(s) to check`));
      meta.append(chip);
    }
    if (task.status === 'paused') meta.append(el('span', T('已暂停', 'Paused'), 'flag-chip'));
    if (facts?.reviseHere) {
      const chip = markup('flag-chip revise', icon('edit', 'i-xs'));
      chip.dataset.reviseHere = '';
      chip.append(T('从这里修订', 'Revise from here'));
      meta.append(chip);
    }
    // Whose request this is, then who left a reminder: the colleagues this task involves.
    const people = cardPeople(facts);
    if (people.length) {
      const notes = markup('card-notes', people.map((p) => avatar(p.role, 'xs')).join(''));
      notes.title = people
        .map((p) => {
          const name = PEOPLE[p.role]?.name ?? '';
          return p.why === 'asked' ? T(`${name}提的请求`, `Asked by ${name}`) : T(`${name}有提醒`, `${name} left a reminder`);
        })
        .join(T('；', '; '));
      notes.append(el('span', notes.title, 'sr-only'));
      meta.append(notes);
    }
    open.append(head, recent);
    if (meta.childElementCount) open.append(meta);
    open.addEventListener('keydown', (event) => {
      if (destroyed || !event.altKey || !event.key.startsWith('Arrow')) return;
      event.preventDefault();
      event.stopPropagation();
      if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
        if (canMove) void moveOrder(task, event.key === 'ArrowUp' ? -1 : 1);
      } else if (canUpdate)
        void movePriority(task, (task.priority ?? 0) + (event.key === 'ArrowLeft' ? -1 : 1));
    });
    row.append(open);
    const folder = workFolderMarkup({
      taskId: task.id,
      title: task.title,
      works: works.map((p) => ({
        id: p.product_id,
        title: p.title,
        purpose: p.purpose,
        kind: p.kind === 'test_plan' ? 'test_set' : p.kind,
        body: p.content,
        revision: p.version,
        source: p.source_return_id ? 'external-agent' : 'user',
        adopted: !p.source_return_id || p.adoption?.status === 'adopted',
      })),
    });
    if (folder) {
      const holder = doc.createElement('template');
      holder.innerHTML = folder;
      row.append(holder.content);
    }
    row.append(cardMenu(task, canMove, canUpdate));
    return row;
  }
  let taskRenderingKey = '';
  function render() {
    if (destroyed) return;
    const snap = host.snapshot(),
      p = controller.selected(),
      d = controller.draft(p),
      value =
        d?.value ?? (p ? { title: p.title, content: p.content, purpose: p.purpose } : undefined);
    const identity = (p?.session_id ?? '') + ':' + (p?.product_id ?? '');
    if (
      (p || !snap.currentProduct) &&
      (rendered !== identity || (!d && renderedVersion !== p?.version))
    ) {
      rendered = identity;
      renderedVersion = p?.version;
      removeConfirmation = false;
      for (const [key, field] of [
        ['title', 'title'],
        ['body', 'content'],
        ['purpose', 'purpose'],
      ] as const) {
        const n = input(key),
          next = value?.[field] ?? '';
        if (key === 'purpose') writePurpose(nodes.purpose, next);
        else if (n && n.value !== next) n.value = next;
      }
      if (nodes.investigation && p?.kind === 'investigation') {
        const payload = (d?.value.structured_payload ??
          p.structured_payload) as InvestigationPayload;
        const pairs: [string, string | undefined][] = [
          ['[data-investigation-question]', payload?.question],
          ['[data-investigation-review="focus"]', payload?.review_focus],
          ['[data-investigation-review="note"]', payload?.review_note],
        ];
        for (const [selector, v] of pairs) {
          const n = nodes.investigation.querySelector<HTMLInputElement>(selector);
          if (n && n.value !== (v ?? '')) n.value = v ?? '';
        }
      }
      const savedQuestion = p
        ? host.draft<{ question: string; recipient: string }>(
            'workspace',
            p.session_id + ':share-question:' + p.product_id,
          )
        : undefined;
      question.value = savedQuestion?.question ?? '';
      recipient.value = savedQuestion?.recipient ?? 'supervisor';
    }
    const readonly = !p || !!p.removed_at || !controller.can('work_products.versions.create'),
      blocked = controller.blocked();
    for (const key of ['title', 'body']) {
      const n = input(key) as HTMLInputElement | undefined;
      if (n) n.readOnly = readonly;
    }
    disableControl(nodes.purpose, readonly);
    const conflict = controller.conflict(p);
    if (status) {
      status.setAttribute('role', 'status');
      status.textContent = snap.storageError
        ? message('draft_storage_failed')
        : controller.state.error
          ? message(controller.state.error)
          : controller.state.receipt && controller.state.receipt.status !== 'confirmed'
            ? T(
                '请求尚未完成；输入已保留，请查看原请求结果。',
                'The request is not complete. Your input is retained; check its recorded result.',
              )
            : conflict
              ? message('draft_conflict')
              : d
                ? T(
                    '草稿已保留，尚未保存为工作区版本',
                    'Draft retained; not yet saved as a workspace version',
                  )
                : p
                  ? T('已保存到工作区', 'Saved to workspace')
                  : T('选择或新建一份作品', 'Select or create a work product');
    }
    save.textContent = T('保存这版', 'Save this version');
    copy.textContent = T('另存草稿', 'Save draft as a copy');
    refresh.textContent = T('读取工作区更新', 'Refresh workspace');
    reference.textContent = T('引用这版', 'Reference this version');
    recover.textContent = T('查看上一请求结果', 'Check previous request');
    retry.textContent = T('重新尝试', 'Try again');
    remove.textContent = T('移除作品', 'Remove product');
    restore.textContent = T('恢复作品', 'Restore product');
    confirmRemove.textContent = T(
      '确认移除并撤回全部分享',
      'Confirm removal and revoke all shares',
    );
    adopt.textContent = T('检查后采用这版', 'Adopt this reviewed version');
    save.disabled = readonly || blocked || conflict || !d;
    copy.hidden = !d;
    copy.disabled = blocked || !controller.can('work_products.create');
    reference.disabled = !p || !!d;
    refresh.disabled = controller.state.loading || snap.busy;
    recover.hidden = !controller.state.receipt || controller.state.receipt.status === 'confirmed';
    recover.disabled = snap.busy;
    retry.hidden = controller.state.receipt?.status !== 'failed';
    retry.disabled = snap.busy;
    remove.hidden = !p || !!p.removed_at;
    remove.disabled = blocked || readonly || !!d;
    confirmRemove.hidden = !removeConfirmation;
    confirmRemove.disabled = remove.disabled;
    restore.hidden = !p?.removed_at;
    restore.disabled = blocked || !controller.can('work_products.versions.create');
    adopt.hidden =
      !p ||
      (!p.source_return_id && p.executor.kind === 'human') ||
      p.adoption?.status === 'adopted';
    adopt.disabled = blocked || !controller.can('work_products.adopt') || !!d;
    compare.hidden = !d;
    compareCaption.textContent = T('比较已保存的内容', 'Compare saved content');
    serverContent.textContent = p
      ? T('第 ' + p.version + ' 版 · ', 'v' + p.version + ' · ') +
        (p.title ?? '') +
        '\n' +
        (p.content ?? '')
      : '';
    comparison = p && d ? { head: p.version, token: d.token } : undefined;
    merge.textContent = T('已比较，保存这份草稿', 'Reviewed: save this draft');
    merge.disabled = readonly || blocked || !d;
    const productShares = controller.state.shares.filter(
      (s) => s.product.object_id === p?.product_id,
    );
    const earlier = productShares.some((s) => !s.revoked_at && s.product.version !== p?.version);
    visibility.textContent = !p
      ? ''
      : p.removed_at
        ? T(
            '作品已移除；恢复不会重开此前分享。',
            'Product removed. Restoring it does not reactivate previous shares.',
          )
        : p.visibility === 'shared'
          ? T('当前第 ' + p.version + ' 版已有同事可见。', 'Current v' + p.version + ' is shared.')
          : p.visibility === 'private'
            ? T(
                '当前第 ' +
                  p.version +
                  ' 版仅自己可见。' +
                  (earlier ? '此前分享的旧版仍有效。' : ''),
                'Current v' +
                  p.version +
                  ' is private.' +
                  (earlier ? ' Previously shared versions remain visible.' : ''),
              )
            : T(
                '当前权限不能确认全部分享状态。',
                'Your access does not show all sharing activity.',
              );
    shareVersion.textContent = p
      ? T(
          '只分享已保存的第 ' + p.version + ' 版；之后修改不会自动分享。',
          'Share only saved v' + p.version + '. Later changes are not shared automatically.',
        )
      : '';
    recipient.setAttribute('aria-label', T('分享给同事', 'Share with colleague'));
    question.setAttribute('aria-label', T('分享问题', 'Question for colleague'));
    question.placeholder = T(
      '希望同事针对这版讨论什么？',
      'What should your colleague discuss about this version?',
    );
    for (const option of recipient.options) option.textContent = roleLabel(option.value);
    share.textContent = T('分享已保存的这版', 'Share this saved version');
    share.disabled = readonly || blocked || !!d || !controller.can('work_products.shares.create');
    recipient.disabled = share.disabled;
    question.disabled = share.disabled;
    shareList.replaceChildren(
      ...productShares.map((s) => {
        const row = el('div', '', 'row-actions');
        row.append(
          el(
            'span',
            roleLabel(s.recipient_role) +
              ' · v' +
              s.product.version +
              ' · ' +
              (s.revoked_at ? T('已撤回', 'Revoked') : T('可见', 'Visible')),
          ),
        );
        if (!s.revoked_at) {
          const revoke = button('撤回分享', 'Revoke share', () => controller.revoke(s));
          revoke.disabled = blocked || !controller.can('work_products.shares.change');
          row.append(revoke);
        }
        return row;
      }),
    );
    historyCaption.textContent = T('已保存版本', 'Saved versions');
    loadHistory.textContent = T('读取已保存版本', 'Load saved versions');
    loadHistory.disabled = !p || controller.state.loading;
    if (historyKey !== versionKey()) history = [];
    showOutcome(p ?? undefined, !!d);
    historyRows.replaceChildren(
      ...history.map((v) => {
        const row = el('details');
        row.append(
          el('summary', 'v' + v.version + ' · ' + v.title),
          el('pre', v.content, 'w03-slot-text'),
          button('打开这个版本', 'Open this version', () => host.openReference(productRef(v))),
        );
        return row;
      }),
    );
    const tk = JSON.stringify([
      controller.state.tasks,
      controller.state.products.map((p) => [
        p.product_id,
        p.version,
        p.task?.object_id,
        p.title,
        p.removed_at,
        p.created_at,
      ]),
      snap.uiLanguage,
      blocked,
      snap.available,
    ]);
    if (tk !== taskRenderingKey) {
      const focused = doc.activeElement as HTMLElement | null,
        card = focused?.closest<HTMLElement>('[data-task-id]');
      if (card && focused?.dataset.w03TaskControl && lanesOwn(card))
        pendingTaskFocus ??= {
          id: card.dataset.taskId ?? '',
          // An item of an open menu comes back as that card's "⋯" button.
          control: focused.closest('.card-menu') ? 'more' : focused.dataset.w03TaskControl,
        };
      closeMenu();
      taskRenderingKey = tk;
      for (const [name, priority] of [
        ['tasks0', 0],
        ['tasks1', 1],
        ['tasks2', 2],
        ['taskList', null],
      ] as const) {
        const lane = nodes[name];
        if (!lane) continue;
        const list =
          priority === null
            ? controller.state.tasks.filter((t) => t.status !== 'removed')
            : lanesOrdered(priority);
        lane.replaceChildren(...list.map((task, index) => taskCard(task, index)));
        if (priority !== null && !list.length) {
          // The drop hint shows only while a card is being dragged (styles); not read aloud.
          const empty = el('li', T('拖到这里', 'Drop here'), 'col-empty');
          empty.setAttribute('aria-hidden', 'true');
          lane.append(empty);
        }
      }
    }
    restoreTaskFocus(blocked);
    forms.forEach((form) => form.update());
    if (!nodes.taskForm && nodes.newTask)
      (nodes.newTask as HTMLButtonElement).disabled =
        blocked || !controller.can('work_items.create');
    if (!nodes.productForm && nodes.newProduct)
      (nodes.newProduct as HTMLButtonElement).disabled =
        blocked || !controller.can('work_products.create');
  }
  const update = (snapshot: Readonly<V4HostSnapshot>) => {
    if (destroyed) return;
    const nextFormSession = JSON.stringify([
      snapshot.session?.sessionId,
      snapshot.currentTask?.object_id,
    ]);
    if (formSession !== nextFormSession) {
      formSession = nextFormSession;
      for (const name of formFields) {
        if (
          (name.startsWith('task') && nodes.taskForm) ||
          (name.startsWith('new') && nodes.productForm)
        )
          continue;
        const n = input(name);
        if (!n) continue;
        const saved = host.draft<string>('workspace', formKey(name));
        if (name === 'newPurpose' && saved !== undefined) writePurpose(nodes[name], saved);
        else if (saved !== undefined) n.value = saved;
        else if (n.tagName === 'SELECT') {
          const select = n as HTMLSelectElement;
          select.value =
            [...select.options].find((o) => o.defaultSelected)?.value ??
            select.options[0]?.value ??
            '';
        } else if (['INPUT', 'TEXTAREA'].includes(n.tagName))
          n.value = (n as HTMLInputElement).defaultValue ?? '';
        else
          n.querySelectorAll<HTMLInputElement>('input[type=radio]').forEach((radio) => {
            radio.checked = radio.defaultChecked;
          });
      }
    }
    controller.update(snapshot);
    const key = JSON.stringify([snapshot.session, snapshot.asOf]);
    if (snapshot.session?.protocol === 2 && key !== readKey) {
      readKey = key;
      void act(() => controller.refresh());
    } else render();
  };
  for (const [kind, node] of [
    ['task', nodes.taskForm],
    ['product', nodes.productForm],
  ] as const) {
    if (node?.tagName === 'FORM')
      forms.push(bindWorkspaceForm(kind, node as HTMLFormElement, host, controller));
  }
  const importer = nodes.import ? mountImport(host, nodes.import, controller) : undefined;
  const unsubscribe = host.subscribe(() => update(host.snapshot()));
  update(host.snapshot());
  return {
    update,
    destroy: () => {
      destroyed = true;
      unsubscribe();
      importer?.destroy();
      forms.forEach((form) => form.destroy());
      listeners.forEach((off) => off());
      owned.forEach((node) => node.remove());
      controller.destroy();
    },
  };
}
export { mount as mountWorkspaceSlot };
