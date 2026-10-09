/** Native v4 colleague slot. The injected client owns API calls, journals and jobs. */
import { T, onLocaleChange } from '../../app/i18n';
import './roles.css';

export type RoleId = 'supervisor' | 'business_lead' | 'tech_lead';
export type WorkLanguage = 'zh' | 'en';
export type TurnStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'needs_context'
  | 'paused'
  | 'cancelled'
  | 'unknown';
export interface MaterialReference {
  id: string;
  title: string;
  version: number;
}
export interface Colleague {
  id: RoleId;
  name: string;
  available: boolean;
}
export interface ConversationTurn {
  id: string;
  roleId: RoleId;
  question: string;
  status: TurnStatus;
  reply?: string;
  materials?: readonly MaterialReference[];
  /** Only a learner-safe explanation already projected by the real client. */
  explanation?: string;
  canRetry?: boolean;
  canRefresh?: boolean;
  canRecordDisplay?: boolean;
  displayRecorded?: boolean; // Public server receipt, never inferred from a read.
}
/** Presentation data, not a new server schema. Never pass private audit objects. */
export interface RolesView {
  sessionId: string;
  workLanguage: WorkLanguage;
  mode: 'local_reference' | 'model' | 'unavailable';
  colleagues: readonly Colleague[];
  turns: readonly ConversationTurn[];
  canSend: boolean;
  restriction?: string;
  /** The existing durable client journal still has an unconfirmed operation. */
  unconfirmed?: boolean;
}
export interface RolesNativeAdapter {
  /** Return the current public projection for this one fixed session. */
  read(): Promise<RolesView>;
  /** Resolve only after the existing client has confirmed/journalled acceptance. */
  send(input: { roleId: RoleId; text: string }): Promise<void>;
  /** Recover the client's original request; never mint a replacement command. */
  recover(): Promise<void | { confirmed: { roleId: RoleId; text: string } }>;
  retry?(turnId: string): Promise<void>;
  refreshContext?(turnId: string): Promise<void>;
  openMaterial?(material: MaterialReference): void | Promise<void>;
  /** Map a visibly painted reply to the existing idempotent display command.
   * Supply only when authorized; journal/recovery remain with the shared client.
   */
  recordDisplay?(turnId: string): Promise<void>;
  subscribe?(changed: () => void): () => void;
  drafts?: { read(role: RoleId): string; write(role: RoleId, value: string): void };
}
export interface RolesNativeHandle {
  refresh(): Promise<void>;
  destroy(): void;
}
export interface RolesMountOptions {
  surface?: 'standalone' | 'v4-history';
  roleId?: RoleId;
}

const ROLES: readonly RoleId[] = ['supervisor', 'business_lead', 'tech_lead'];
const roleTitle = (id: RoleId) =>
  ({
    supervisor: T('经理', 'Manager'),
    business_lead: T('业务负责人', 'Business lead'),
    tech_lead: T('技术负责人', 'Technical lead'),
  })[id];
const statusText = (status: TurnStatus) =>
  ({
    queued: T('问题已收到，等待回复', 'Question received; waiting for a reply'),
    running: T('正在处理', 'Processing'),
    completed: T('已回复', 'Replied'),
    failed: T('这次回复未完成', 'This reply was not completed'),
    needs_context: T('材料已变化，需要确认后继续', 'Materials changed; confirm before continuing'),
    paused: T('已暂停，问题仍保留', 'Paused; the question is retained'),
    cancelled: T('本次处理已停止，问题仍保留', 'Stopped; the question is retained'),
    unknown: T(
      '处理状态尚待确认，问题仍保留',
      'Processing status is unconfirmed; the question is retained',
    ),
  })[status];

export function mount(
  container: HTMLElement,
  adapter: RolesNativeAdapter,
  options: RolesMountOptions = {},
): RolesNativeHandle {
  const historyOnly = options.surface === 'v4-history';
  if (historyOnly && (!options.roleId || !ROLES.includes(options.roleId)))
    throw new Error('A v4 colleague is required');
  const doc = container.ownerDocument;
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string) => {
    const node = doc.createElement(tag);
    if (cls) node.className = cls;
    return node;
  };
  const button = (cls?: string) => {
    const node = el('button', cls);
    node.type = 'button';
    return node;
  };
  const root = el('section', 'rc-roles');
  root.dataset.rolePanel = '';
  if (historyOnly) root.classList.add('rc-roles--v4-history');
  const header = el('header', 'rc-roles__header');
  const heading = el('h2');
  const language = el('span', 'rc-roles__language');
  const reload = button('rc-roles__text-button');
  reload.dataset.action = 'reload';
  header.append(heading, language, reload);
  const mode = el('p', 'rc-roles__mode');
  mode.setAttribute('role', 'note');
  const notice = el('p', 'rc-roles__notice');
  notice.setAttribute('role', 'status');
  notice.setAttribute('aria-live', 'polite');
  const recover = button('rc-roles__text-button');
  recover.dataset.action = 'recover';
  const layout = el('div', 'rc-roles__layout');
  const nav = el('nav', 'rc-roles__people');
  const main = el('div', 'rc-roles__main');
  const activeName = el('h3');
  const list = el('ol', 'rc-roles__conversation');
  const empty = el('p', 'rc-roles__empty');
  const form = el('form', 'rc-roles__composer');
  const label = el('label');
  const textarea = el('textarea');
  textarea.rows = 4;
  textarea.maxLength = 12000;
  textarea.dataset.roleQuestion = '';
  const inputId = 'role-question-' + crypto.randomUUID();
  textarea.id = inputId;
  label.htmlFor = inputId;
  const actions = el('div', 'rc-roles__actions');
  const hint = el('span', 'rc-roles__hint');
  const send = el('button', 'rc-roles__send');
  send.type = 'submit';
  send.dataset.action = 'send';
  actions.append(hint, send);
  form.append(label, textarea, actions);
  if (historyOnly) {
    // v4 owns the colleague header, navigation, composer and scroll region.
    main.append(list, empty);
    layout.append(main);
    root.append(mode, notice, recover, reload, layout);
  } else {
    main.append(activeName, list, empty, form);
    layout.append(nav, main);
    root.append(header, mode, notice, recover, layout);
  }
  container.append(root);

  let selected: RoleId = options.roleId ?? 'supervisor';
  let view: RolesView | undefined;
  let sessionId: string | undefined;
  let loaded = false;
  let busy = false;
  let uncertain = false;
  let destroyed = false;
  let loadTicket = 0;
  let feedback: 'read' | 'unconfirmed' | 'action' | 'draft' | undefined;
  const drafts = new Map<RoleId, string>();
  const people = new Map<RoleId, HTMLButtonElement>();
  const displayAttempts = new Set<string>();
  const visibleReplies = new Map<HTMLElement, { turnId: string; visible: boolean }>();
  const markDisplayed = (node: HTMLElement) => {
    const entry = visibleReplies.get(node);
    if (!adapter.recordDisplay || !entry?.visible || destroyed || doc.visibilityState !== 'visible')
      return;
    const key = sessionId + ':' + entry.turnId;
    if (displayAttempts.has(key)) return;
    requestAnimationFrame(() => {
      if (
        destroyed ||
        !node.isConnected ||
        !visibleReplies.get(node)?.visible ||
        doc.visibilityState !== 'visible' ||
        displayAttempts.has(key)
      )
        return;
      for (let parent: HTMLElement | null = node; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        if (
          style.display === 'none' ||
          style.visibility === 'hidden' ||
          Number(style.opacity) === 0
        )
          return;
      }
      // At most one automatic attempt in this mount. A failure is recovered via
      // the shared original request journal, never by a render/observer retry.
      displayAttempts.add(key);
      void Promise.resolve()
        .then(() => adapter.recordDisplay!(entry.turnId))
        .catch(() => {
          if (!destroyed) {
            feedback = 'action';
            render();
          }
        });
    });
  };
  const displayObserver =
    adapter.recordDisplay && typeof IntersectionObserver !== 'undefined'
      ? new IntersectionObserver((entries) => {
          for (const entry of entries) {
            const node = entry.target as HTMLElement;
            const tracked = visibleReplies.get(node);
            if (!tracked) continue;
            tracked.visible = entry.isIntersecting && entry.intersectionRatio > 0;
            markDisplayed(node);
          }
        })
      : undefined;
  const onVisibility = () => {
    if (doc.visibilityState === 'visible')
      for (const node of visibleReplies.keys()) markDisplayed(node);
  };
  doc.addEventListener('visibilitychange', onVisibility);

  const draft = (id: RoleId) => {
    if (!drafts.has(id)) {
      try {
        drafts.set(id, adapter.drafts?.read(id) ?? '');
      } catch {
        drafts.set(id, '');
        feedback = 'draft';
      }
    }
    return drafts.get(id)!;
  };
  const keepDraft = (id: RoleId, value: string) => {
    drafts.set(id, value);
    try {
      adapter.drafts?.write(id, value);
      if (feedback === 'draft') feedback = undefined;
    } catch {
      feedback = 'draft';
    }
  };
  for (const id of ROLES) {
    const item = button('rc-roles__person');
    item.dataset.role = id;
    item.addEventListener('click', () => {
      selected = id;
      textarea.value = draft(id);
      render();
    });
    people.set(id, item);
    nav.append(item);
  }
  if (!historyOnly) textarea.value = draft(selected);

  function canSend() {
    return (
      loaded &&
      !busy &&
      !uncertain &&
      !view?.unconfirmed &&
      view?.canSend &&
      view.mode !== 'unavailable' &&
      view.colleagues.some((c) => c.id === selected && c.available) &&
      !!textarea.value.trim()
    );
  }
  const appendAction = (
    parent: HTMLElement,
    title: string,
    name: string,
    invoke: () => Promise<void>,
  ) => {
    const control = button('rc-roles__text-button');
    control.textContent = title;
    control.dataset.action = name;
    control.disabled = busy || !loaded || uncertain || !!view?.unconfirmed;
    control.addEventListener('click', () => {
      void perform(invoke);
    });
    parent.append(control);
  };
  function render() {
    if (destroyed) return;
    root.setAttribute('aria-busy', String(busy));
    heading.textContent = T('同事', 'Colleagues');
    nav.setAttribute('aria-label', T('选择同事', 'Choose a colleague'));
    language.textContent = view
      ? T('工作语言：', 'Working language: ') + (view.workLanguage === 'en' ? 'English' : '中文')
      : '';
    reload.textContent = T('刷新对话', 'Refresh conversation');
    reload.disabled = busy;
    mode.textContent =
      view?.mode === 'local_reference'
        ? T(
            '本地资料参考；需要同事判断的部分等待模型接入。',
            'Local source reference; colleague judgment is waiting for model connection.',
          )
        : view?.mode === 'unavailable'
          ? T(
              '同事对话暂不可用，已有记录仍保留。',
              'Colleague replies are unavailable; existing records are retained.',
            )
          : '';
    mode.hidden = !mode.textContent;
    for (const [id, item] of people) {
      const colleague = view?.colleagues.find((c) => c.id === id);
      item.replaceChildren();
      const avatar = el('span', 'rc-roles__avatar');
      avatar.setAttribute('aria-hidden', 'true');
      avatar.textContent = (colleague?.name || roleTitle(id)).slice(0, 1);
      const name = el('span');
      name.textContent = colleague?.name || roleTitle(id);
      const title = el('small');
      title.textContent = roleTitle(id);
      name.append(title);
      item.append(avatar, name);
      item.setAttribute('aria-pressed', String(id === selected));
      // Past conversations remain selectable even while a colleague is unavailable.
    }
    const colleague = view?.colleagues.find((c) => c.id === selected);
    activeName.textContent = colleague?.name || roleTitle(selected);
    list.setAttribute('aria-label', T('对话记录', 'Conversation history'));
    const turns = view?.turns.filter((t) => t.roleId === selected) ?? [];
    displayObserver?.disconnect();
    visibleReplies.clear();
    const fragments = turns.map((turn) => {
      const item = el('li', 'rc-roles__turn');
      item.dataset.turnId = turn.id;
      const questionLabel = el('strong');
      questionLabel.textContent = T('你', 'You');
      const question = el('p', 'rc-roles__question');
      question.textContent = turn.question;
      item.append(questionLabel, question);
      if (turn.status === 'completed' && turn.reply !== undefined) {
        const replyLabel = el('strong');
        replyLabel.textContent = colleague?.name || roleTitle(selected);
        const reply = el('p', 'rc-roles__reply');
        reply.textContent = turn.reply;
        item.append(replyLabel, reply);
        if (displayObserver && turn.canRecordDisplay !== false && !turn.displayRecorded) {
          visibleReplies.set(reply, { turnId: turn.id, visible: false });
          displayObserver.observe(reply);
        }
        if (turn.materials?.length) {
          const refs = el('div', 'rc-roles__materials');
          refs.setAttribute('aria-label', T('引用材料', 'Referenced materials'));
          for (const ref of turn.materials) {
            const text = (ref.title.trim() || T('材料', 'Material')) + ' · v' + ref.version;
            const link = adapter.openMaterial
              ? button('rc-roles__material')
              : el('span', 'rc-roles__material');
            link.textContent = text;
            if (adapter.openMaterial)
              link.addEventListener('click', () => {
                Promise.resolve()
                  .then(() => adapter.openMaterial!(ref))
                  .catch(() => {
                    if (!destroyed) {
                      feedback = 'action';
                      render();
                    }
                  });
              });
            refs.append(link);
          }
          item.append(refs);
        }
      } else {
        const status = el('p', 'rc-roles__turn-status');
        status.textContent = turn.explanation || statusText(turn.status);
        item.append(status);
        if (turn.status === 'failed' && turn.canRetry && adapter.retry)
          appendAction(item, T('重试这次回复', 'Retry this reply'), 'retry', () =>
            adapter.retry!(turn.id),
          );
        if (turn.status === 'needs_context' && turn.canRefresh && adapter.refreshContext)
          appendAction(
            item,
            T('确认新材料并继续', 'Confirm updated materials'),
            'refresh-context',
            () => adapter.refreshContext!(turn.id),
          );
      }
      return item;
    });
    list.replaceChildren(...fragments);
    empty.hidden = turns.length > 0;
    empty.textContent = loaded
      ? T(
          '从一个具体问题开始。只会使用这位同事已知且获准讨论的资料。',
          'Start with a specific question. This colleague can use only information they know and may discuss.',
        )
      : T('正在读取对话…', 'Loading conversation…');
    label.textContent = T('想和这位同事讨论什么？', 'What would you like to discuss?');
    textarea.placeholder = T(
      '例如：35-45人的试点需要先确认哪些条件？',
      'For example: what should we confirm for a 35-45 person pilot?',
    );
    textarea.disabled = false; // Drafting stays available during failures and recovery.
    send.textContent = busy ? T('正在处理…', 'Working…') : T('发送问题', 'Send question');
    send.disabled = !canSend();
    hint.textContent = T('⌘ / Ctrl + Enter 发送', '⌘ / Ctrl + Enter to send');
    const needsRecovery = uncertain || !!view?.unconfirmed;
    recover.hidden = !needsRecovery;
    recover.textContent = T('恢复原请求', 'Recover original request');
    recover.disabled = busy;
    notice.textContent = needsRecovery
      ? T(
          '结果尚未确认。输入已保留，请恢复原请求。',
          'The result is unconfirmed. Your input is retained; recover the original request.',
        )
      : feedback === 'read'
        ? T(
            '暂时无法读取对话。已有记录与输入保留，请刷新。',
            'Conversation could not be read. Existing records and input are retained; refresh to continue.',
          )
        : feedback === 'action'
          ? T(
              '这次操作未完成，已有记录与输入保留。',
              'This action was not completed. Records and input are retained.',
            )
          : feedback === 'draft'
            ? T(
                '输入尚未保存到本机，请保留文字。',
                'Input has not been saved locally; keep your text.',
              )
            : view?.restriction || '';
    notice.hidden = !notice.textContent;
  }
  async function refresh() {
    const ticket = ++loadTicket;
    try {
      const next = await adapter.read();
      if (destroyed || ticket !== loadTicket) return;
      if (
        !next.sessionId ||
        (sessionId && sessionId !== next.sessionId) ||
        !['zh', 'en'].includes(next.workLanguage) ||
        !['local_reference', 'model', 'unavailable'].includes(next.mode) ||
        !Array.isArray(next.colleagues) ||
        !Array.isArray(next.turns)
      )
        throw new Error('Invalid session projection');
      if (view && view.workLanguage !== next.workLanguage)
        throw new Error('Working language changed');
      sessionId = next.sessionId;
      view = next;
      loaded = true;
      if (feedback === 'read') feedback = undefined;
    } catch {
      if (destroyed || ticket !== loadTicket) return;
      loaded = false;
      feedback = 'read';
    }
    render();
  }
  async function perform(action: () => Promise<void>, recovery = false) {
    if (busy || destroyed) return;
    busy = true;
    feedback = undefined;
    render();
    try {
      await action();
      if (destroyed) return;
      if (recovery) uncertain = false;
      await refresh();
    } catch {
      if (!destroyed) {
        uncertain = true;
        feedback = 'unconfirmed';
      }
    } finally {
      busy = false;
      render();
    }
  }
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!canSend()) return;
    const roleId = selected;
    const text = textarea.value;
    void perform(async () => {
      await adapter.send({ roleId, text });
      if (destroyed) return;
      if (draft(roleId) === text) {
        keepDraft(roleId, '');
        if (selected === roleId) textarea.value = '';
      }
    });
  });
  textarea.addEventListener('input', () => {
    const before = feedback;
    keepDraft(selected, textarea.value);
    if (before !== feedback) render();
    else send.disabled = !canSend();
  });
  textarea.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  reload.addEventListener('click', () => {
    void refresh();
  });
  recover.addEventListener('click', () => {
    void perform(async () => {
      const result = await adapter.recover();
      if (destroyed) return;
      const confirmed = result?.confirmed;
      if (confirmed && draft(confirmed.roleId) === confirmed.text) {
        keepDraft(confirmed.roleId, '');
        if (selected === confirmed.roleId) textarea.value = '';
      }
    }, true);
  });
  const unsubscribe = adapter.subscribe?.(() => {
    void refresh();
  });
  const unlocale = onLocaleChange(render);
  render();
  void refresh();
  return {
    refresh,
    destroy() {
      if (destroyed) return;
      destroyed = true;
      ++loadTicket;
      unsubscribe?.();
      unlocale();
      displayObserver?.disconnect();
      visibleReplies.clear();
      doc.removeEventListener('visibilitychange', onVisibility);
      root.remove();
    },
  };
}

/** Mount only the selected colleague's history into v4's existing thread node.
 * v4 sends through its own composer/client. Destroy/remount when its role changes.
 */
export function mountConversation(
  container: HTMLElement,
  adapter: RolesNativeAdapter,
  roleId: RoleId,
): RolesNativeHandle {
  return mount(container, adapter, { surface: 'v4-history', roleId });
}
