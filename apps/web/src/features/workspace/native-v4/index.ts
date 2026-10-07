/** Native v4 document panel. The injected WorkspaceClient owns persistence,
 * exact versions, recovery and permissions; this module owns no app root. */
import { draftOf, type WorkspaceClient, type Draft } from '../client';
import type { WorkspaceProductRead, ProductShare } from '../contract-types';
import { saveStatus } from '../native-slots';

export interface NativeWorkspaceOptions {
  productId?: string;
  canEdit?: boolean;
  canAdopt?: boolean;
  onSelected?: (product: WorkspaceProductRead) => void;
  onSaved?: (product: WorkspaceProductRead) => void;
  onReference?: (product: WorkspaceProductRead) => void;
  onError?: (error: unknown) => void;
}

export function mountNativeWorkspace(host: HTMLElement, client: WorkspaceClient, options: NativeWorkspaceOptions = {}) {
  const doc = host.ownerDocument;
  const node = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', cls = '') => {
    const el = doc.createElement(tag); el.textContent = text; el.className = cls; return el;
  };
  let selected = options.productId ?? '', rendered = '', destroyed = false;
  const root = node('section', '', 'native-workspace');
  root.setAttribute('aria-label', '工作作品');
  const hiddenStyle=doc.createElement('style');hiddenStyle.textContent='.native-workspace [hidden]{display:none!important}';root.append(hiddenStyle);
  const toolbar = node('div', '', 'sheet-head');
  toolbar.append(node('h2', '工作作品'));
  const list = node('nav'); list.setAttribute('aria-label', '选择作品');
  const body = node('div', '', 'sheet-body');
  const notice = node('p', '', 'muted'); notice.setAttribute('role', 'status'); notice.setAttribute('aria-live', 'polite');
  const error = node('p', '', 'inline-alert'); error.setAttribute('role', 'alert'); error.hidden = true;
  const title = node('input', '', 'input'); title.setAttribute('aria-label', '作品标题');
  const text = node('textarea', '', 'textarea'); text.rows = 12; text.setAttribute('aria-label', '作品正文');
  const purpose = node('select', '', 'select'); purpose.setAttribute('aria-label', '作品用途');
  for (const [value,label] of [['exploration','探索笔记'],['option','方案比较'],['plan','测试或行动计划'],['commitment','试点决定'],['result','结果报告']]) {
    const option = node('option', label); option.value = value; purpose.append(option);
  }
  const visibility = node('p', '', 'muted');
  const actions = node('div', '', 'field-row');
  const sharing = node('section'); sharing.setAttribute('aria-label', '已分享的确切版本');
  const shares = node('div'); const recipient = node('select', '', 'select'); recipient.setAttribute('aria-label', '分享给同事');
  for (const [value,label] of [['supervisor','经理'],['business_lead','业务负责人'],['tech_lead','技术负责人']]) {
    const option = node('option', label); option.value = value; recipient.append(option);
  }
  const question = node('textarea', '', 'textarea'); question.rows = 2; question.placeholder = '希望同事针对这版作品讨论什么？'; question.setAttribute('aria-label', '分享时的问题');
  const version = node('p', '', 'muted');
  const button = (label: string, handler: () => Promise<unknown> | void, primary = false) => {
    const el = node('button',label,'btn'+(primary?' primary':'')); el.type = 'button';
    el.addEventListener('click', () => { void perform(handler); }); return el;
  };
  const perform = async (handler: () => Promise<unknown> | void) => {
    error.hidden = true;
    try { await handler(); }
    catch (cause) { if (!destroyed) { error.textContent = cause instanceof Error ? cause.message : '操作未完成，原文仍保留。'; error.hidden = false; options.onError?.(cause); } }
    finally { if (!destroyed) render(); }
  };
  const current = () => client.snapshot().products.find(p => p.product_id === selected);
  const create = button('新建作品', async () => {
    const result = await client.createProduct({kind:'text',purpose:'exploration',title:'未命名作品',content:''});
    selected = result.object.product_id; rendered = ''; render(); options.onSelected?.(result.object);
  });
  const refresh = button('刷新', () => client.refresh()); toolbar.append(create,refresh);
  const save = button('保存这版', async () => {
    const product = current(); if (!product) return;
    const result = await client.save(product); options.onSaved?.(result.object);
  },true);
  const copy = button('另存这份草稿', async () => {
    const result = await client.saveCopy(selected); selected = result.object.product_id; rendered = ''; render();
  });
  const recover = button('确认上一请求', () => client.retry());
  const adopt = button('我已检查，采用这版', async () => { const product=current(); if(product) await client.adopt(product); });
  const cite = button('引用这版', () => { const product=current(); if(product) options.onReference?.(product); });
  actions.append(save,copy,recover,adopt,cite);
  const share = button('分享已保存的这版', async () => {
    const product = current(); if (!product) return;
    if (client.snapshot().journal.drafts[selected]) throw Error('先保存正文，再选择分享的版本。');
    await client.share({product_id:product.product_id,product_version:product.version,recipient_role:recipient.value,question:question.value,purpose:'discussion'});
    question.value = '';
  });
  sharing.append(node('h3','同事能看到的版本'),version,recipient,question,share,shares);
  const field = (label: string, control: HTMLElement) => { const el=node('label','','field'); el.append(node('span',label),control); return el; };
  body.append(error,notice,field('标题',title),field('用途',purpose),field('正文',text),actions,visibility,sharing);
  root.append(toolbar,list,body); host.replaceChildren(root);
  const keep = () => {
    const product = current(); if (!product || options.canEdit === false || product.removed_at) return;
    const draft: Draft = {...(client.snapshot().journal.drafts[selected] ?? draftOf(product)),title:title.value,content:text.value,purpose:purpose.value};
    void client.keepDraft(selected,draft).catch(cause => { error.textContent='本机保存未完成，请保留本页文字。';error.hidden=false;options.onError?.(cause); });
  };
  title.addEventListener('input',keep); text.addEventListener('input',keep); purpose.addEventListener('change',keep);
  const choose = async (id: string) => { await client.flushLocal(); selected=id;rendered='';render(); const p=current();if(p)options.onSelected?.(p); };
  function renderShare(record: ProductShare) {
    const row=node('div','','field-row');
    const role=({supervisor:'经理',business_lead:'业务负责人',tech_lead:'技术负责人'} as Record<string,string>)[record.recipient_role] ?? record.recipient_role;
    row.append(node('p',`${role} · 第 ${record.product.version} 版 · ${record.revoked_at?'已撤回':'可见'}`));
    if (!record.revoked_at && options.canEdit !== false) {
      const revoke=button('撤回这次分享',()=>client.updateShare({product_id:selected,share_id:record.id,expected_revision:record.version,operation:'revoke'}));
      revoke.disabled=client.snapshot().busy || !!client.snapshot().journal.pending; row.append(revoke);
    }
    return row;
  }
  function render() {
    if (destroyed) return;
    const state=client.snapshot();
    if (!selected && state.products.length) selected=state.products[0].product_id;
    const product=current();
    list.replaceChildren(...state.products.map(p=>{
      const entry=button(`${p.title || '未命名作品'} · 第 ${p.version} 版`,()=>choose(p.product_id));
      entry.setAttribute('aria-current',p.product_id===selected?'true':'false'); return entry;
    }));
    if (rendered!==selected) {
      rendered=selected; const draft=product ? state.journal.drafts[selected] ?? draftOf(product) : null;
      title.value=draft?.title ?? '';text.value=draft?.content ?? '';
      const value=draft?.purpose ?? 'exploration';
      if (![...purpose.options].some(o=>o.value===value)) { const option=node('option',value);option.value=value;purpose.append(option); }
      purpose.value=value;
    }
    const readonly=options.canEdit===false || !product || !!product.removed_at;
    title.readOnly=readonly;text.readOnly=readonly;purpose.disabled=readonly;
    const pending=state.busy || !!state.journal.pending;
    create.disabled=options.canEdit===false || pending || !state.asOf;
    save.disabled=readonly || pending || !!state.journal.conflicts[selected];
    copy.hidden=!state.journal.conflicts[selected];copy.disabled=pending || readonly;
    recover.hidden=!state.journal.pending;recover.disabled=state.busy;
    adopt.hidden=!options.canAdopt || !product || product.adoption?.status==='adopted' || product.author.kind==='human';adopt.disabled=pending;
    cite.hidden=!options.onReference;cite.disabled=!product || !!state.journal.drafts[selected];
    share.disabled=readonly || pending || !!state.journal.drafts[selected];recipient.disabled=share.disabled;question.disabled=share.disabled;
    notice.textContent=product ? saveStatus(client,selected).text : '新建一份作品后，可以随时保存和请同事查看。';
    if (state.journal.conflicts[selected]) notice.textContent='工作区有更新。你的草稿已保留，可以另存后继续；未覆盖已有版本。';
    version.textContent=product ? `将分享第 ${product.version} 版；之后保存的新版本不会自动替换已分享版本。` : '';
    const hasEarlierShare=(state.shares[selected]??[]).some(s=>!s.revoked_at && s.product.version!==product?.version);
    visibility.textContent=!product?'':product.visibility==='shared'?`当前第 ${product.version} 版已有同事可见。`:product.visibility==='private'?`当前第 ${product.version} 版仅自己可见。${hasEarlierShare?'此前分享仍有效，见下方具体版本。':''}`:'当前读取范围不足以确认全部分享状态。';
    shares.replaceChildren(...(state.shares[selected] ?? []).map(renderShare));
  }
  const unsubscribe=client.subscribe(render);render();
  return { refresh:()=>perform(()=>client.refresh()),select:choose,destroy:()=>{destroyed=true;unsubscribe();root.remove();} };
}

export { mountNativeWorkspace as mount };
