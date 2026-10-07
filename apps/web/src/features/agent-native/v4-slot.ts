import type { V4CommandResult, V4HostSnapshot, V4SlotContext, V4SlotHandle } from '../../v4-host';
import { activities, connections, grantInput, listData, ref, restoreDraft, returnedWorks, semanticLabel, t,
  type Activity, type Connection, type Draft, type ReturnedWork } from './model';
import './v4-slot.css';

/** Hosts supply empty insertion nodes INSIDE the existing Agent rail:
 * connection, activity, returns. Existing manual package/return controls stay host-owned.
 * Connection configuration export stays host-owned too; no credential enters this slot.
 */
export function mountV4AgentSlot(context: V4SlotContext): V4SlotHandle {
  const { host, nodes } = context;
  if (!nodes.connection || !nodes.activity || !nodes.returns) throw Error('agent_slot_nodes_required');
  let snapshot = host.snapshot();
  const sessionId = snapshot.session?.sessionId ?? '';
  const draftKey = `${sessionId}:authorization`;
  let draft: Draft = restoreDraft(host.draft('agent', draftKey), sessionId);
  let destroyed = false, inFlight = false, storageFailed = false, generation = 0, reading = false;
  let rows: Connection[] = [], events: Activity[] = [], products: ReturnedWork[] = [];
  let connectionState: 'unavailable' | 'loading' | 'verified' | 'error' = 'unavailable';
  let activityFailed = false, productsFailed = false, nextProductCursor: number | undefined;
  let unsubscribe: () => void = () => {};
  let queryStamp = '', statusText: [string, string] = ['', ''];
  const abort = new AbortController(), roots: HTMLElement[] = [];
  const element = <K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = '') => {
    const value = document.createElement(tag); value.className = className; value.textContent = text; return value;
  };
  const label = (zh: string, en: string) => t(snapshot.uiLanguage, zh, en);
  const available = (operation: string) => snapshot.session?.protocol === 2 && snapshot.available[operation] === true;
  const locked = () => inFlight || snapshot.busy || storageFailed || snapshot.storageError || !!draft.dispatchUnknown;
  const button = (zh: string, en: string, action: () => void, className = 'btn small quiet') => {
    const value = element('button', className, label(zh, en)); value.type = 'button';
    value.addEventListener('click', action, { signal: abort.signal }); return value;
  };
  const attach = (node: HTMLElement, className: string) => { const root = element('div', `agent-v4-slot ${className}`); node.append(root); roots.push(root); return root; };
  const connectionRoot = attach(nodes.connection, 'agent-v4-connection');
  const activityRoot = attach(nodes.activity, 'agent-v4-activity');
  const returnRoot = attach(nodes.returns, 'agent-v4-returns');
  const connectionStatus = element('p', 'meta'); connectionStatus.setAttribute('role', 'status');
  const connectionList = element('div', 'stack');
  const refreshButton = button('刷新授权与记录', 'Refresh access and records', () => { void refresh(); });
  const form = element('form', 'agent-v4-grant');
  const nameLabel = element('label', 'agent-v4-field'), nameText = element('span');
  const name = element('input', 'input'); name.name = 'agentName'; name.maxLength = 64; name.autocomplete = 'off'; name.value = draft.name;
  nameLabel.append(nameText, name);
  const actLabel = element('label', 'check'), actText = element('span'), act = element('input'); act.type = 'checkbox'; act.checked = draft.act; actLabel.append(act, actText);
  const allLabel = element('label', 'check'), allText = element('span'), all = element('input'); all.type = 'checkbox'; all.checked = draft.all; allLabel.append(all, allText);
  const chooseButton = button('选择材料与作品范围', 'Choose sources and work', () => { void choose(); });
  const taskButton = button('加入当前事项', 'Include current task', () => {
    if (!snapshot.currentTask || locked()) return;
    draft.refs = uniqueRefs([...draft.refs, snapshot.currentTask]); draft.all = false; all.checked = false; void saveDraft(); renderScope();
  });
  const scopeStatus = element('p', 'meta');
  const durationLabel = element('label', 'agent-v4-field'), durationText = element('span'), duration = element('select', 'select');
  for (const minutes of [15, 30, 60]) { const option = element('option'); option.value = String(minutes); duration.append(option); }
  duration.value = String(draft.minutes); durationLabel.append(durationText, duration);
  const createButton = element('button', 'btn small primary'); createButton.type = 'submit';
  const separation = element('p', 'meta');
  form.append(nameLabel, actLabel, allLabel, chooseButton, taskButton, scopeStatus, durationLabel, createButton, separation);
  const pending = element('div', 'agent-v4-pending'); pending.setAttribute('role', 'status');
  const pendingText = element('p', 'meta');
  const recoverButton = button('核对原请求结果', 'Check original result', () => { void recover(false); });
  const retryButton = button('明确重试这次操作', 'Retry this operation', () => { void recover(true); });
  pending.append(pendingText, recoverButton, retryButton);
  const notice = element('p', 'meta'); notice.setAttribute('role', 'status');
  connectionRoot.append(connectionStatus, connectionList, refreshButton, form, pending, notice);
  const eventList = element('ol', 'log'), eventNote = element('p', 'meta'); activityRoot.append(eventNote, eventList);
  const productList = element('div', 'stack'), productNote = element('p', 'meta');
  const moreButton = button('继续读取作品', 'Load more work', () => { void loadMore(); }); returnRoot.append(productNote, productList, moreButton);
  const uniqueRefs = (values: Draft['refs']) => [...new Map(values.map(value => [JSON.stringify(value), value])).values()];

  async function saveDraft() {
    try {
      await host.keepDraft('agent', draftKey, structuredClone(draft));
      if (!destroyed && storageFailed) { storageFailed = false; statusText = ['草稿已保存。', 'Draft saved.']; renderControls(); }
    }
    catch { if (!destroyed) { storageFailed = true; statusText = ['草稿未保存，请保留当前输入。', 'Draft not saved. Keep your current input.']; renderControls(); } }
  }
  for (const input of [name, act, all, duration]) input.addEventListener('input', () => {
    draft = { ...draft, name: name.value, act: act.checked, all: all.checked, minutes: Number(duration.value) };
    void saveDraft(); renderScope(); renderControls();
  }, { signal: abort.signal });
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (createButton.disabled) return;
    try { void command('delegations.create', grantInput(draft, sessionId, new Date())); }
    catch { statusText = ['填写名称并明确授权范围。', 'Enter a name and choose the permitted scope.']; renderControls(); }
  }, { signal: abort.signal });

  async function choose() {
    if (locked()) return;
    try {
      const selected = await host.chooseEvidence(); if (destroyed) return;
      draft.refs = uniqueRefs(selected.map(value => ref(value, sessionId))); draft.all = false; all.checked = false;
      await saveDraft(); if (!destroyed) renderScope();
    } catch { if (!destroyed) { statusText = ['未能选择范围，请重试选择。', 'Could not select the scope. Choose again.']; renderControls(); } }
  }
  async function accept(result: V4CommandResult, action: string) {
    if (destroyed) return;
    // Only a pointer into the HOST journal is kept. No Command or response is copied.
    if (result.status === 'confirmed') {
      draft.pending = undefined; draft.dispatchUnknown = false;
      statusText = action === 'delegations.create'
        ? ['授权已创建。请使用宿主提供的连接配置入口。', 'Access created. Use the host connection setup control.']
        : ['操作已确认，正在读取实际记录。', 'Action confirmed. Reading the actual records.'];
    } else {
      draft.pending = { requestId: result.requestId, action, status: result.status };
      statusText = ['结果尚未确认，请先核对原请求。', 'Result is not confirmed. Check the original request first.'];
    }
    await saveDraft(); if (!destroyed) await refresh();
  }
  async function command(operation: string, input: Record<string, unknown>) {
    if (destroyed || locked() || draft.pending || !available(operation)) return;
    inFlight = true; renderControls();
    let issued = false;
    try { await host.flushDrafts(); if (!destroyed) { issued = true; await accept(await host.command(operation, input), operation); } }
    catch { if (!destroyed) { if (issued) { draft.dispatchUnknown = true; await saveDraft(); } else { storageFailed = true; } statusText = ['操作结果未知，请从统一请求记录核对。', 'Outcome unknown. Check the shared request history.']; host.announce(label(...statusText), 'error'); } }
    finally { inFlight = false; if (!destroyed) renderControls(); }
  }
  async function recover(retry: boolean) {
    const item = draft.pending;
    if (destroyed || locked() || !item) return;
    if (retry && !['failed', 'needs_context'].includes(item.status)) return;
    inFlight = true; renderControls();
    try { await accept(await (retry ? host.retry(item.requestId) : host.recover(item.requestId)), item.action); }
    catch { if (!destroyed) statusText = ['仍未确认，原请求与草稿已保留。', 'Still unconfirmed. The original request and draft are retained.']; }
    finally { inFlight = false; if (!destroyed) renderControls(); }
  }
  async function refresh() {
    if (destroyed || snapshot.session?.protocol !== 2) return;
    const mine = ++generation; reading = true; connectionState = available('delegations.list') ? 'loading' : 'unavailable'; renderLists();
    const result = await Promise.allSettled([
      available('delegations.list') ? Promise.resolve().then(() => host.query('delegations.list', { cursor: 0, limit: 50 })) : Promise.resolve(null),
      available('timeline') ? Promise.resolve().then(() => host.query('timeline', { cursor: 0, limit: 50 })) : Promise.resolve(null),
      available('work_products.list') ? Promise.resolve().then(() => host.query('work_products.list', { cursor: 0, limit: 50 })) : Promise.resolve(null),
    ]);
    if (destroyed || mine !== generation) return;
    try { rows = result[0].status === 'fulfilled' && result[0].value != null ? connections(result[0].value, sessionId) : []; connectionState = result[0].status === 'rejected' ? 'error' : available('delegations.list') ? 'verified' : 'unavailable'; }
    catch { rows = []; connectionState = 'error'; }
    try { if (result[1].status === 'rejected') throw Error(); events = result[1].value == null ? [] : activities(result[1].value, sessionId); activityFailed = false; }
    catch { events = []; activityFailed = true; }
    try { if (result[2].status === 'rejected') throw Error(); products = result[2].value == null ? [] : returnedWorks(result[2].value, sessionId); nextProductCursor = result[2].value == null ? undefined : listData(result[2].value, 'items').cursor; productsFailed = false; }
    catch { products = []; nextProductCursor = undefined; productsFailed = true; }
    reading = false; renderLists(); renderControls();
  }
  async function loadMore() {
    if (destroyed || reading || nextProductCursor == null) return;
    const mine = generation, cursor = nextProductCursor; reading = true; renderControls();
    try {
      const value = await host.query('work_products.list', { cursor, limit: 50 }); if (destroyed || mine !== generation) return;
      products = [...new Map([...products, ...returnedWorks(value, sessionId)].map(row => [JSON.stringify(row.ref), row])).values()];
      nextProductCursor = listData(value, 'items').cursor;
      if (nextProductCursor != null && nextProductCursor <= cursor) { nextProductCursor = undefined; productsFailed = true; }
    } catch { if (!destroyed && mine === generation) productsFailed = true; }
    finally { if (!destroyed && mine === generation) { reading = false; renderLists(); renderControls(); } }
  }
  function renderScope() { scopeStatus.textContent = draft.all ? label('允许读取整个工作区内获准的内容。', 'Allow authorized content across the workspace.') : label(`已选择 ${draft.refs.length} 个来源或事项。`, `${draft.refs.length} sources or tasks selected.`); }
  function renderControls() {
    if (destroyed) return;
    nameText.textContent = label('Agent 名称', 'Agent name'); actText.textContent = label('允许操作与回传作品', 'Allow actions and returned work');
    allText.textContent = label('授权整个工作区的可见内容', 'Allow visible content across the workspace'); durationText.textContent = label('授权时长', 'Access duration');
    for (const option of duration.options) option.textContent = label(`${option.value} 分钟`, `${option.value} minutes`);
    createButton.textContent = label('创建授权', 'Create access'); refreshButton.textContent = label('刷新授权与记录', 'Refresh access and records');
    chooseButton.textContent = label('选择材料与作品范围', 'Choose sources and work'); taskButton.textContent = label('加入当前事项', 'Include current task');
    separation.textContent = label('默认只读。作品由你检查采用，再从交付入口提交。', 'Read only by default. Review and adopt work, then submit from the delivery entry.');
    form.hidden = snapshot.session?.protocol !== 2;
    createButton.disabled = locked() || !!draft.pending || snapshot.state !== 'active' || !available('delegations.create');
    for (const input of [name, act, all, duration]) input.disabled = inFlight || snapshot.busy || !!draft.pending || !!draft.dispatchUnknown;
    chooseButton.disabled = locked() || !!draft.pending;
    taskButton.disabled = locked() || !!draft.pending || !snapshot.currentTask; refreshButton.disabled = reading;
    pending.hidden = !draft.pending;
    pendingText.textContent = draft.pending?.status === 'failed' ? label('本次操作失败，原记录保留。', 'This action failed. The original record is retained.') : label('本次操作等待核对。', 'This action needs verification.');
    recoverButton.textContent = label('核对原请求结果', 'Check original result'); recoverButton.disabled = locked();
    retryButton.textContent = label('明确重试这次操作', 'Retry this operation'); retryButton.hidden = !['failed', 'needs_context'].includes(draft.pending?.status ?? ''); retryButton.disabled = locked();
    notice.textContent = draft.dispatchUnknown ? label('结果未知，请在统一请求记录核对后继续。', 'Outcome unknown. Resolve it in the shared request history before continuing.') : snapshot.storageError ? label('保存不可用，请保留输入。', 'Saving is unavailable. Keep your input.') : label(...statusText);
    moreButton.textContent = label('继续读取作品', 'Load more work'); moreButton.disabled = reading; moreButton.hidden = nextProductCursor == null;
    for (const write of roots.flatMap(root => [...root.querySelectorAll<HTMLButtonElement>('button[data-agent-write]')])) {
      write.disabled = locked() || !!draft.pending || write.dataset.agentBlocked === 'true' || !available(write.dataset.agentWrite!);
    }
    renderScope();
  }
  function renderLists() {
    if (destroyed) return;
    connectionStatus.textContent = connectionState === 'verified' ? label('以下为刚读取的授权状态。', 'Access state just read from the service.') : connectionState === 'loading' ? label('正在核对授权状态…', 'Checking access state…') : connectionState === 'error' ? label('无法确认当前授权状态，请刷新核对。', 'Cannot confirm current access. Refresh to verify.') : label('连接状态读取尚未接入。', 'Connection state is not connected yet.');
    connectionList.replaceChildren();
    if (connectionState === 'verified') for (const row of rows) {
      const line = element('div', 'agent-v4-access-row'), text = element('p');
      const status = { active: ['已授权', 'Authorized'], revoked: ['已撤销', 'Revoked'], expired: ['已到期', 'Expired'], unknown: ['状态待核实', 'State unverified'] } as const;
      text.textContent = `${row.label || label('我的 Agent', 'My Agent')} · ${label(status[row.status][0], status[row.status][1])}`;
      const detail = element('p', 'meta', `${label('权限：', 'Permissions: ')}${row.capabilities.map(cap => cap === 'read' ? label('读取', 'read') : cap === 'act' ? label('操作', 'act') : label('提交', 'submit')).join(' / ')} · ${label('到期：', 'Expires: ')}${new Date(row.expiresAt).toLocaleString(snapshot.uiLanguage === 'zh' ? 'zh-CN' : 'en-US')}`);
      const revoke = button('撤销授权', 'Revoke access', () => { void command('delegations.revoke', { delegation_id: row.id }); });
      revoke.dataset.agentWrite = 'delegations.revoke'; revoke.dataset.agentBlocked = String(row.status === 'revoked');
      revoke.disabled = locked() || !!draft.pending || row.status === 'revoked' || !available('delegations.revoke'); line.append(text, detail, revoke); connectionList.append(line);
    }
    eventList.replaceChildren(); eventNote.textContent = activityFailed ? label('操作记录暂时无法读取。', 'Action records are temporarily unavailable.') : label('只显示已读取的实际记录。', 'Only actual retrieved records are shown.');
    const titles: Record<string, [string, string]> = { material_read: ['读取材料', 'Read a source'], test_completed: ['完成测试', 'Completed a test'], permission_denied: ['未获授权', 'Permission denied'], submission_recorded: ['提交作品', 'Submitted work'] };
    for (const event of events) {
      const row = element('li', 'log-item'), content = element('div', 'grow');
      const who = event.executor === 'human' ? label('你', 'You') : event.executor === 'external_agent' ? label('我的 Agent', 'My Agent') : event.executor === 'reference_agent' ? label('参考 Agent', 'Reference Agent') : label('系统', 'System');
      content.append(element('p', '', `${who} · ${label(...(titles[event.type] ?? ['工作记录', 'Work record'] as [string, string]))}`));
      if (event.summary) content.append(element('p', 'meta', event.summary));
      const marker = semanticLabel(snapshot.uiLanguage, event.semanticStatus, event.verification); if (marker) content.append(element('p', 'meta', marker));
      for (const source of event.refs) content.append(button('查看依据', 'View source', () => { void host.openReference(source).catch(() => host.announce(label('当前无法打开依据。', 'Source cannot be opened now.'), 'error')); }));
      row.append(content); eventList.append(row);
    }
    productList.replaceChildren(); productNote.textContent = productsFailed ? label('回传作品暂时无法读取，原作品保留。', 'Returned work is unavailable. Original work is retained.') : label('查看确切版本，再决定是否采用。', 'Review the exact version before adopting.');
    for (const product of products) {
      const row = element('div', 'agent-v4-work-row');
      row.append(element('p', '', `${product.title || label('Agent 作品', 'Agent work')} · v${product.ref.version}`));
      row.append(element('p', 'meta', product.adoption === 'adopted' ? label('此版本已采用', 'This version is adopted') : label('此版本待你检查', 'This version awaits your review')));
      const marker = semanticLabel(snapshot.uiLanguage, product.semanticStatus, product.verification); if (marker) row.append(element('p', 'meta', marker));
      row.append(button('打开原作', 'Open work', () => host.selectProduct(product.ref)));
      const adopt = button('采用此版本', 'Adopt this version', () => { void command('work_products.adopt', { product_id: product.ref.object_id, product_version: product.ref.version, expected_head: product.ref.version, status: 'adopted' }); });
      adopt.dataset.agentWrite = 'work_products.adopt'; adopt.dataset.agentBlocked = String(product.adoption === 'adopted' || snapshot.state !== 'active');
      adopt.disabled = locked() || !!draft.pending || product.adoption === 'adopted' || snapshot.state !== 'active' || !available('work_products.adopt'); row.append(adopt); productList.append(row);
    }
  }
  function update(next: Readonly<V4HostSnapshot>) {
    if (destroyed) return;
    if ((next.session?.sessionId ?? '') !== sessionId) { destroy(); return; }
    snapshot = next;
    const stamp = JSON.stringify([next.session, next.asOf, next.available, next.state]);
    renderControls(); renderLists();
    if (stamp !== queryStamp) { queryStamp = stamp; void refresh(); }
  }
  function destroy() { if (destroyed) return; destroyed = true; generation++; abort.abort(); unsubscribe(); for (const root of roots) root.remove(); }
  unsubscribe = host.subscribe(() => update(host.snapshot()));
  if (destroyed) unsubscribe(); else update(snapshot);
  return { update, destroy };
}
export default mountV4AgentSlot;
