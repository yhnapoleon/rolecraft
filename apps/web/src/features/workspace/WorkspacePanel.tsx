import { useState, useSyncExternalStore } from 'react';
import { WorkspaceClient, draftOf } from './client';
import type { ImportResult, WorkspaceImport } from './contract-types';
import { buildBrowserImport } from './import-browser';
import './workspace.css';

type Locale = 'zh' | 'en';
const words = (locale: Locale) => (zh: string, en: string) => locale === 'zh' ? zh : en;

/** Incremental feature only. 032 mounts it into the existing workbench surfaces. */
export function WorkspacePanel({ client, locale = 'zh' }: { client: WorkspaceClient; locale?: Locale }) {
  const state = useSyncExternalStore(client.subscribe, client.snapshot, client.snapshot);
  const t = words(locale);
  const [selected, select] = useState<string>();
  const [taskTitle, setTaskTitle] = useState('');
  const [recipient, setRecipient] = useState('tech_lead');
  const [question, setQuestion] = useState('');
  const [recoveredImport, setRecoveredImport] = useState<{ requestId: string; input: WorkspaceImport; preview: ImportResult }>();
  const product = state.products.find(p => p.product_id === selected);
  const draft = product ? state.journal.drafts[product.product_id] ?? draftOf(product) : undefined;
  const conflict = product && state.journal.conflicts[product.product_id];
  const pending = !!state.journal.pending;
  const blocked = state.busy || pending || state.storageError || state.localPending > 0;
  const act = (work: Promise<unknown>) => { void work.catch(() => {}); };
  return <section className="rc-workspace" aria-label={t('事项与作品','Tasks and work')}>
    <header><h2>{t('事项与作品','Tasks and work')}</h2><button onClick={() => act(client.refresh())} disabled={state.busy}>{t('重新读取','Refresh')}</button></header>
    {state.error && <p role="alert" className="rc-workspace-error">{state.error}</p>}
    {pending && <p role="status">{t('上一请求尚待确认，原文字和请求已保留。','The previous request is unconfirmed. Your text and original request are kept.')} <button onClick={() => act(client.retry())} disabled={state.busy || state.storageError}>{t('恢复原请求','Retry original request')}</button></p>}
    {Object.entries(state.journal.rejected).filter(([,r]) => !r.dismissed && !r.successor).map(([id,r]) => <section key={id} className="rc-workspace-conflict" aria-label={t('已拒绝的请求','Rejected request')}>
      <p>{t('这次请求未执行，原输入已保留。可以继续其他工作。','This request was rejected. Its inputs are kept, and you can continue other work.')}</p>
      <p>{String(r.request.command.payload?.title ?? r.request.command.payload?.question ?? r.request.command.payload?.purpose ?? t('工作区操作','Workspace action'))}</p>
      <details><summary>{t('核对原输入','Review original input')}</summary><pre>{String(r.request.command.payload?.content ?? r.request.command.payload?.goal ?? r.request.command.payload?.question ?? '')}</pre></details>
      {r.nextAction === 'repreview' ? <button disabled={blocked} onClick={() => act(client.repreviewRejectedImport(id).then(value => setRecoveredImport({ ...value, requestId:id })))}>{t('重新预览导入','Preview import again')}</button>
        : !r.request.draftId && <button disabled={blocked} onClick={() => act(client.resubmitRejected(id))}>{t('已核对，重新读取后重提','Checked: refresh and submit again')}</button>}
      {r.request.draftId && <button onClick={() => select(r.request.draftId)}>{t('打开草稿比较','Compare the draft')}</button>}
      <button disabled={blocked} onClick={() => act(client.dismissRejected(id))}>{t('暂不重提，保留记录','Keep the record without resubmitting')}</button>
    </section>)}
    {recoveredImport && <ImportPreview input={recoveredImport.input} preview={recoveredImport.preview} busy={blocked} locale={locale}
      onApply={() => act(client.applyImport(recoveredImport.input,recoveredImport.preview,recoveredImport.requestId).then(() => setRecoveredImport(undefined)))} />}
    <form className="rc-workspace-task-entry" onSubmit={e => { e.preventDefault(); act(client.createTask({ title: taskTitle, priority: 1, order: state.tasks.length })); }}>
      <label>{t('新增事项','New task')}<input value={taskTitle} onChange={e => setTaskTitle(e.target.value)} maxLength={120} required /></label>
      <button disabled={blocked || !taskTitle.trim()}>{t('添加','Add')}</button>
    </form>
    <ul className="rc-workspace-tasks">{state.tasks.map(task => <li key={task.id}>
      <span>{task.title}</span>
      <label className="rc-workspace-inline">{t('优先级','Priority')}<select value={task.priority ?? 1} disabled={blocked} onChange={e => act(client.patchTask({ item_id: task.id, expected_revision: task.revision, priority: Number(e.target.value) }))}>
        <option value={0}>{t('先做','First')}</option><option value={1}>{t('随后','Next')}</option><option value={2}>{t('暂放','Later')}</option>
      </select></label>
      <label className="rc-workspace-inline">{t('进展','Status')}<select value={task.status ?? 'open'} disabled={blocked} onChange={e => act(client.patchTask({ item_id: task.id, expected_revision: task.revision, status: e.target.value as 'open' }))}>
        <option value="open">{t('待处理','Open')}</option><option value="active">{t('正在做','Working')}</option><option value="paused">{t('暂放','Paused')}</option><option value="blocked">{t('受阻','Blocked')}</option><option value="done">{t('已处理','Done')}</option><option value="removed">{t('已移除','Removed')}</option>
      </select></label>
    </li>)}</ul>
    <div className="rc-workspace-layout">
      <nav aria-label={t('作品目录','Work directory')}>
        <button disabled={blocked} onClick={() => act(client.createProduct({ kind: 'text', title: t('未命名作品','Untitled work'), purpose: 'freeform', content: '' }))}>{t('开始写','Start writing')}</button>
        {state.products.map(p => <button key={p.product_id} className="rc-workspace-work" aria-current={selected === p.product_id ? 'true' : undefined} onClick={() => { select(p.product_id); act(client.loadShares(p.product_id)); }}>
          <span>{p.title || t('未命名作品','Untitled work')}</span><small>v{p.version} · {p.removed_at ? t('已移除','Removed') : p.adoption?.status === 'adopted' ? t('已采用','Adopted') : t('待检查','To check')}</small>
        </button>)}
      </nav>
      {product && draft ? <article className="rc-workspace-paper">
        <div className="rc-workspace-meta"><span>{t('服务端','Server')} v{product.version} · {product.purpose}{state.journal.drafts[product.product_id] && <> · {state.journal.draftBases[product.product_id] ? t('草稿基于','Draft based on')+' v'+state.journal.draftBases[product.product_id]!.product.version : t('草稿基准待核对','Draft base unknown')}</>}</span><span role="status">{state.storageError ? t('本机未保存','Not saved locally') : state.localPending ? t('正在保存到本机…','Saving locally…') : state.journal.drafts[product.product_id] ? t('待同步，文字已留在本机','Pending sync; text kept locally') : t('已保存到工作区','Saved to workspace')}</span></div>
        <label>{t('标题','Title')}<input value={draft.title ?? ''} readOnly={!!product.removed_at} maxLength={160} onChange={e => client.keepDraft(product.product_id, { ...draft, title: e.target.value })} /></label>
        <label>{t('用途','Purpose')}<input value={draft.purpose ?? ''} readOnly={!!product.removed_at} maxLength={200} onChange={e => client.keepDraft(product.product_id, { ...draft, purpose: e.target.value })} /></label>
        <label>{t('正文','Content')}<textarea value={draft.content ?? ''} readOnly={!!product.removed_at} rows={12} maxLength={50000} onChange={e => client.keepDraft(product.product_id, { ...draft, content: e.target.value })} /></label>
        {product.legacy && <p className="rc-workspace-muted">{t('原始作品、草稿和来源记录已保留；旧测试仍需核对，未自动执行或采用。','Original work, drafts and provenance are kept. Imported tests need checking; nothing was run or adopted automatically.')}</p>}
        {conflict && <section className="rc-workspace-conflict" aria-label={t('版本冲突','Version conflict')}>
          <p>{t('你的修改和服务端版本都已保留。核对后可以另存作品。','Your edits and the server version are both kept. Compare them or save a separate work.')}</p>
          <details><summary>{t('查看服务端内容','View server content')}</summary><pre>{conflict.server?.content ?? t('尚未取得，请重新读取','Not retrieved yet; refresh to compare')}</pre></details>
          <button disabled={blocked} onClick={() => act(client.saveCopy(product.product_id))}>{t('将我的文字另存','Save my text separately')}</button>
          {conflict.server && <button disabled={blocked} onClick={() => act(client.confirmMerge(product.product_id,draft,conflict.server!.version,state.journal.draftTokens[product.product_id]).then(() => client.save(client.snapshot().products.find(p => p.product_id === product.product_id)!)))}>{t('已比较，保存合并稿','Compared: save merged text')}</button>}
        </section>}
        {(state.journal.alternatives[product.product_id] ?? []).length > 0 && <details><summary>{t('保留的其他草稿','Other preserved drafts')}</summary>{state.journal.alternatives[product.product_id].map(alt => <section key={alt.token}><p>{alt.base ? 'v'+alt.base.product.version : t('基准待核对','Base unknown')}</p><pre style={{whiteSpace:'pre-wrap'}}>{alt.draft.content}</pre></section>)}</details>}
        <div className="rc-workspace-actions">
          <button disabled={blocked || !!product.removed_at || !!conflict} onClick={() => act(client.save(product))}>{t('保存版本','Save version')}</button>
          <button disabled={blocked || !!product.removed_at || !!state.journal.drafts[product.product_id]} onClick={() => act(client.adopt(product))}>{t('采用此版本','Adopt this version')}</button>
          <button disabled={blocked} onClick={() => act(client.remove(product, !product.removed_at))}>{product.removed_at ? t('恢复作品','Restore work') : t('移除作品','Remove work')}</button>
        </div>
        <fieldset disabled={blocked || !!product.removed_at}><legend>{t('分享已保存的确切版本','Share the exact saved version')} v{product.version}</legend>
          <label>{t('同事','Colleague')}<select value={recipient} onChange={e => setRecipient(e.target.value)}><option value="tech_lead">{t('技术负责人','Technical lead')}</option><option value="business_lead">{t('业务负责人','Business lead')}</option><option value="supervisor">{t('经理','Manager')}</option></select></label>
          <label>{t('想讨论什么','What would you like to discuss?')}<input value={question} onChange={e => setQuestion(e.target.value)} maxLength={4000} /></label>
          <button onClick={() => act(client.share({ product_id: product.product_id, product_version: product.version, recipient_role: recipient, question }).then(() => client.loadShares(product.product_id)))}>{t('分享此版本','Share this version')}</button>
          <p className="rc-workspace-muted">{t('新修改不会自动分享。撤销只限制今后的读取，已经发生的讨论会保留。','New edits are not shared automatically. Revocation limits future access; past discussions remain.')}</p>
          {(state.shares[product.product_id] ?? []).map(s => <p key={s.id}>{s.recipient_role} · v{s.product.version} · {s.revoked_at ? t('已撤销','Revoked') : t('可读取','Readable')} <button onClick={() => act(client.updateShare({ product_id: product.product_id, share_id: s.id, expected_revision: s.version, operation: s.revoked_at ? 'restore' : 'revoke' }).then(() => client.loadShares(product.product_id)))}>{s.revoked_at ? t('重新分享','Restore access') : t('撤销分享','Revoke')}</button></p>)}
        </fieldset>
      </article> : <p className="rc-workspace-empty">{t('选择一份作品，或先写下你的问题。','Choose a work, or start with your question.')}</p>}
    </div>
  </section>;
}

export function ImportPreview({ input, preview, onApply, busy = false, locale = 'zh' }: { input: WorkspaceImport; preview: ImportResult; onApply: () => void; busy?: boolean; locale?: Locale }) {
  const t = words(locale);
  return <section className="rc-workspace-import" aria-label={t('导入预览','Import preview')}>
    <h3>{t('核对所选内容','Check selected content')}</h3><p>{input.items.length} {t('项；原浏览器副本会保留。','items; the original browser copy stays intact.')}</p>
    <ul>{input.items.map(i => <li key={i.original_id}>{String(i.raw.title ?? i.original_id)} · {i.original_kind}</li>)}</ul>
    {preview.unresolved.length > 0 && <div role="status"><p>{t('这些关联尚未接通；正文会保留，旧测试不会变成新会话的执行记录。','These references are unresolved. Text is kept; old tests will not become runs in this session.')}</p><ul>{preview.unresolved.map(r => <li key={r.original_session_id + ':' + r.original_id}>{r.original_id} · {r.status}</li>)}</ul></div>}
    <button disabled={busy || input.package_id !== preview.package_id || preview.mode !== 'preview'} onClick={onApply}>{t('导入这些内容','Import this selection')}</button>
  </section>;
}

export function BrowserImportPicker({ client, attempt, locale = 'zh' }: { client: WorkspaceClient; attempt: any; locale?: Locale }) {
  const t = words(locale);
  const [taskIds, tasks] = useState<string[]>([]), [productIds, products] = useState<string[]>([]);
  const [prepared, prepare] = useState<{ input: WorkspaceImport; preview: ImportResult }>();
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const toggle = (id: string, selected: string[], setter: (ids: string[]) => void) => { setter(selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id]); prepare(undefined); };
  const perform = async (fn: () => Promise<void>) => { setBusy(true); setError(''); try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); } };
  return <section className="rc-workspace-import"><h3>{t('从本机存档选取','Choose from local notes')}</h3>
    <p>{t('只导入你勾选的内容，会话凭据和未完成请求不上传。','Only selected content is imported. Credentials and unfinished requests are not uploaded.')}</p>
    {[['task',attempt.tasks ?? [],taskIds,tasks],['product',attempt.artifacts ?? [],productIds,products]].map(([kind, list, ids, setter]: any) => <fieldset key={kind} disabled={busy}><legend>{kind === 'task' ? t('事项','Tasks') : t('作品','Work')}</legend>{list.map((item: any) => <label key={item.id}><input type="checkbox" checked={ids.includes(item.id)} onChange={() => toggle(item.id, ids, setter)} />{item.title || item.id}</label>)}</fieldset>)}
    {error && <p role="alert">{error}</p>}
    <button disabled={busy || taskIds.length + productIds.length === 0} onClick={() => void perform(async () => { const input = await buildBrowserImport(attempt,{ taskIds,productIds }); prepare({ input,preview:await client.previewImport(input) }); })}>{t('先看预览','Preview first')}</button>
    {prepared && <ImportPreview {...prepared} busy={busy} locale={locale} onApply={() => void perform(async () => { await client.applyImport(prepared.input,prepared.preview); prepare(undefined); })} />}
  </section>;
}
