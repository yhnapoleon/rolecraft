/** Native v4 editor; the host owns navigation and the client owns persistence. */
import { draftOf, type WorkspaceClient, type Draft } from '../client';
import type { WorkspaceProductRead, ProductShare } from '../contract-types';
import { saveStatus, recipientText } from '../native-slots';
import { T, onLocaleChange } from '../../../app/i18n';
import './workspace.css';

export interface NativeWorkspaceOptions {
  productId?: string;
  /** The host owns the folder, heading and product selection. */
  embedded?: boolean;
  canEdit?: boolean;
  canAdopt?: boolean;
  onSelected?: (product: WorkspaceProductRead) => void;
  onSaved?: (product: WorkspaceProductRead) => void;
  onReference?: (product: WorkspaceProductRead) => void;
  onError?: (error: unknown) => void;
}

export function mountNativeWorkspace(host: HTMLElement, client: WorkspaceClient, options: NativeWorkspaceOptions = {}) {
  const doc=host.ownerDocument;
  const node=<K extends keyof HTMLElementTagNameMap>(tag:K, text='', cls='')=>{
    const el=doc.createElement(tag);el.textContent=text;el.className=cls;return el;
  };
  // Translate static controls in place: never recreate a focused editor.
  const translations:(()=>void)[]=[];
  const label=(el:HTMLElement,zh:string,en:string,attr?:string)=>{
    const update=()=>{if(attr)el.setAttribute(attr,T(zh,en));else el.textContent=T(zh,en);};
    translations.push(update);update();
  };
  let selected=options.productId??'',rendered='',renderedVersion:number|undefined,destroyed=false;
  let history:WorkspaceProductRead[]=[];
  let historyKey='',historyRequest=0;
  const root=node('section','','native-workspace');label(root,'工作作品','Work product','aria-label');
  const toolbar=node('div','','field-row');toolbar.hidden=!!options.embedded;
  const list=node('div','','native-workspace-list');list.hidden=!!options.embedded;label(list,'选择作品','Choose a work product','aria-label');
  const body=node('div','','sheet-body');
  const notice=node('p','','muted');notice.setAttribute('role','status');notice.setAttribute('aria-live','polite');
  const error=node('p','','inline-alert');error.setAttribute('role','alert');error.hidden=true;
  const title=node('input','','input');label(title,'作品标题','Product title','aria-label');
  const text=node('textarea','','textarea');text.rows=12;label(text,'作品正文','Product content','aria-label');
  const purpose=node('select','','select');label(purpose,'作品用途','Product purpose','aria-label');
  for(const [value,zh,en] of [['exploration','探索笔记','Exploration'],['option','方案比较','Options'],['plan','测试或行动计划','Test or action plan'],['commitment','试点决定','Pilot decision'],['result','结果报告','Results']]){
    const option=node('option');option.value=value;label(option,zh,en);purpose.append(option);
  }
  const visibility=node('p','','muted'),actions=node('div','','field-row');
  const sharing=node('section');label(sharing,'已分享的确切版本','Exact shared versions','aria-label');
  const shares=node('div'),recipient=node('select','','select');label(recipient,'分享给同事','Share with colleague','aria-label');
  for(const [value,zh,en] of [['supervisor','经理','Manager'],['business_lead','业务负责人','Business lead'],['tech_lead','技术负责人','Technical lead']]){
    const option=node('option');option.value=value;label(option,zh,en);recipient.append(option);
  }
  const question=node('textarea','','textarea');question.rows=2;
  label(question,'希望同事针对这版作品讨论什么？','What should your colleague discuss about this version?','placeholder');
  label(question,'分享时的问题','Question for colleague','aria-label');
  const version=node('p','','muted');
  const current=()=>client.snapshot().products.find(p=>p.product_id===selected);
  const perform=async(handler:()=>Promise<unknown>|void)=>{
    error.hidden=true;
    try{await handler();}
    catch(cause){if(!destroyed){error.textContent=cause instanceof Error?cause.message:T('操作未完成，原文仍保留。','The action did not complete. Your text is retained.');error.hidden=false;options.onError?.(cause);}}
    finally{if(!destroyed)render();}
  };
  // Dynamic rows translate during render, without registering stale DOM nodes.
  const button=(zh:string,en:string,handler:()=>Promise<unknown>|void,primary=false,localize=true)=>{
    const el=node('button',T(zh,en),'btn'+(primary?' primary':''));el.type='button';
    if(localize)label(el,zh,en);el.addEventListener('click',()=>{void perform(handler);});return el;
  };
  const create=button('新建作品','New product',async()=>{
    const result=await client.createProduct({kind:'text',purpose:'exploration',title:T('未命名作品','Untitled product'),content:''});
    selected=result.object.product_id;rendered='';render();options.onSelected?.(result.object);
  });
  const refresh=button('刷新','Refresh',()=>client.refresh());toolbar.append(create,refresh);
  const save=button('保存这版','Save this version',async()=>{
    const product=current();if(product){const result=await client.save(product);options.onSaved?.(result.object);}
  },true);
  const copy=button('另存这份草稿','Save draft as a copy',async()=>{
    const result=await client.saveCopy(selected);selected=result.object.product_id;rendered='';render();options.onSelected?.(result.object);
  });
  const recover=button('确认上一请求','Recover previous request',()=>client.retry());
  const adopt=button('我已检查，采用这版','Adopt this reviewed version',async()=>{const product=current();if(product)await client.adopt(product);});
  const cite=button('引用这版','Reference this version',()=>{const product=current();if(product)options.onReference?.(product);});
  const comparison=node('details');const comparisonTitle=node('summary');
  label(comparisonTitle,'比较工作区已保存内容','Compare saved workspace content');
  const serverText=node('pre','','native-version-content');
  let reviewed:{id:string;head:number;token:string;draft:Draft}|undefined;
  const merge=button('我已比较，保存这份草稿','Reviewed: save this draft',async()=>{
    const choice=reviewed;if(!choice)return;
    await client.confirmMerge(choice.id,choice.draft,choice.head,choice.token);
    const product=client.snapshot().products.find(p=>p.product_id===choice.id);
    if(product){const result=await client.save(product);options.onSaved?.(result.object);}
  });
  comparison.append(comparisonTitle,serverText,merge);
  actions.append(save,copy,recover,adopt,cite);
  const share=button('分享已保存的这版','Share this saved version',async()=>{
    const product=current();if(!product)return;
    if(client.snapshot().journal.drafts[selected])throw Error(T('先保存正文，再选择分享的版本。','Save your draft before sharing this version.'));
    await client.share({product_id:product.product_id,product_version:product.version,recipient_role:recipient.value,question:question.value,purpose:'discussion'});
    question.value='';
  });
  const sharingTitle=node('h3');label(sharingTitle,'同事能看到的版本','Versions colleagues can see');
  sharing.append(sharingTitle,version,recipient,question,share,shares);
  const historySection=node('details');
  const historyTitle=node('summary');label(historyTitle,'已保存版本','Saved versions');
  const historyRows=node('div'),historyNotice=node('p','','muted');historyNotice.setAttribute('role','status');
  const loadHistory=button('读取版本记录','Load version history',async()=>{
    const id=selected,key=viewKey(),request=++historyRequest;
    const versions=await client.loadVersions(id);
    if(destroyed||request!==historyRequest||selected!==id||viewKey()!==key)return;
    history=versions;historyKey=key;renderHistory();
  });
  historySection.append(historyTitle,loadHistory,historyNotice,historyRows);
  const field=(zh:string,en:string,control:HTMLElement)=>{const el=node('label','','field'),caption=node('span');label(caption,zh,en);el.append(caption,control);return el;};
  body.append(error,notice,field('标题','Title',title),field('用途','Purpose',purpose),field('正文','Content',text),actions,comparison,visibility,sharing,historySection);
  root.append(toolbar,list,body);host.replaceChildren(root);
  const keep=()=>{
    const product=current();if(!product||options.canEdit===false||product.removed_at)return;
    const draft:Draft={...(client.snapshot().journal.drafts[selected]??draftOf(product)),title:title.value,content:text.value,purpose:purpose.value};
    void client.keepDraft(selected,draft).catch(cause=>{if(!destroyed){error.textContent=T('本机保存未完成，请保留本页文字。','Local saving failed. Keep your text on this page.');error.hidden=false;options.onError?.(cause);}});
  };
  title.addEventListener('input',keep);text.addEventListener('input',keep);purpose.addEventListener('change',keep);
  const choose=async(id:string)=>{await client.flushLocal();selected=id;rendered='';render();const p=current();if(p)options.onSelected?.(p);};
  const viewKey=()=>selected+':'+JSON.stringify(client.snapshot().asOf);
  function renderShare(record:ProductShare){
    const row=node('div','','field-row'),role=recipientText(record.recipient_role);
    row.append(node('p',T(role+' · 第 '+record.product.version+' 版 · '+(record.revoked_at?'已撤回':'可见'),role+' · v'+record.product.version+' · '+(record.revoked_at?'Revoked':'Visible'))));
    if(!record.revoked_at&&options.canEdit!==false){
      const id=selected;
      const revoke=button('撤回这次分享','Revoke this share',()=>client.updateShare({product_id:id,share_id:record.id,expected_revision:record.version,operation:'revoke'}),false,false);
      revoke.disabled=client.snapshot().busy||!!client.snapshot().journal.pending;row.append(revoke);
    }return row;
  }
  function renderHistory(){
    if(historyKey!==viewKey()){history=[];historyKey='';}
    historyNotice.textContent=historyKey?'':T('读取已保存的正文；本页草稿保持原样。','Read saved content while keeping your current draft.');
    historyRows.replaceChildren(...history.map(p=>{
      const row=node('details'),heading=node('summary',T('第 '+p.version+' 版 · ','v'+p.version+' · ')+p.title);
      const content=node('pre',p.content,'native-version-content');
      row.append(heading,content);
      if(options.onReference){const ref=button('引用这个版本','Reference this version',()=>options.onReference?.(p),false,false);row.append(ref);}
      return row;
    }));
  }
  function render(){
    if(destroyed)return;
    const state=client.snapshot();
    if(!selected&&!options.embedded&&state.products.length)selected=state.products[0].product_id;
    const product=current();
    list.replaceChildren(...state.products.map(p=>{
      const entry=button((p.title||'未命名作品')+' · 第 '+p.version+' 版',(p.title||'Untitled product')+' · v'+p.version,()=>choose(p.product_id),false,false);
      entry.setAttribute('aria-current',p.product_id===selected?'true':'false');return entry;
    }));
    // r8: refresh clean fields when a version changes, retain dirty fields/caret.
    if(rendered!==selected||(!state.journal.drafts[selected]&&renderedVersion!==product?.version)){
      rendered=selected;renderedVersion=product?.version;
      const draft=product?state.journal.drafts[selected]??draftOf(product):null;
      title.value=draft?.title??'';text.value=draft?.content??'';
      const value=draft?.purpose??'exploration';
      if(![...purpose.options].some(o=>o.value===value)){const option=node('option',value);option.value=value;purpose.append(option);}purpose.value=value;
    }
    const readonly=options.canEdit===false||!product||!!product.removed_at;
    title.readOnly=readonly;text.readOnly=readonly;purpose.disabled=readonly;
    const pending=state.busy||!!state.journal.pending;
    create.disabled=options.canEdit===false||pending||!state.asOf;
    save.disabled=readonly||pending||!!state.journal.conflicts[selected];
    copy.hidden=!state.journal.conflicts[selected];copy.disabled=pending||options.canEdit===false;
    comparison.hidden=!state.journal.conflicts[selected];
    reviewed=product&&state.journal.drafts[selected]?{id:selected,head:product.version,token:state.journal.draftTokens[selected],draft:structuredClone(state.journal.drafts[selected])}:undefined;
    serverText.textContent=product?T('第 '+product.version+' 版 · ','v'+product.version+' · ')+product.title+'\n'+product.content:'';
    merge.disabled=readonly||pending||!reviewed;
    recover.hidden=!state.journal.pending;recover.disabled=state.busy;
    adopt.hidden=!options.canAdopt||!product||product.adoption?.status==='adopted'||product.author.kind==='human';adopt.disabled=pending||readonly;
    cite.hidden=!options.onReference;cite.disabled=!product||!!state.journal.drafts[selected];
    share.disabled=readonly||pending||!!state.journal.drafts[selected];recipient.disabled=share.disabled;question.disabled=share.disabled;
    loadHistory.disabled=!product||state.busy;
    notice.textContent=product?saveStatus(client,selected).text:T('新建一份作品后，可以随时保存和请同事查看。','Create a product to save your work and share it with colleagues.');
    if(state.journal.conflicts[selected])notice.textContent=T('工作区有更新。草稿已保留，可以比较后保存，或另存一份。','The workspace changed. Your draft is retained; compare before saving, or save a copy.');
    version.textContent=product?T('将分享第 '+product.version+' 版；之后保存的新版本不会自动替换已分享版本。','Sharing v'+product.version+'. Later versions stay private until you share them.'):'';
    const earlier=(state.shares[selected]??[]).some(s=>!s.revoked_at&&s.product.version!==product?.version);
    visibility.textContent=!product?'':product.visibility==='shared'?T('当前第 '+product.version+' 版已有同事可见。','Current v'+product.version+' is shared with colleagues.'):product.visibility==='private'?T('当前第 '+product.version+' 版仅自己可见。'+(earlier?'此前分享仍有效，见下方具体版本。':''),'Current v'+product.version+' is private.'+(earlier?' Earlier shares are still active; see the versions below.':'')):T('当前读取范围不足以确认全部分享状态。','Your access does not show all sharing activity.');
    shares.replaceChildren(...(state.shares[selected]??[]).map(renderShare));renderHistory();
  }
  const unsubscribe=client.subscribe(render);
  const unlocale=onLocaleChange(()=>{translations.forEach(update=>update());render();});render();
  return {refresh:()=>perform(()=>client.refresh()),select:choose,destroy:()=>{destroyed=true;historyRequest++;unsubscribe();unlocale();root.remove();}};
}
export { mountNativeWorkspace as mount };
