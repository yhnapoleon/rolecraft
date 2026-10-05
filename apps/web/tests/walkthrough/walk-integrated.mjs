// Integration of source transitions, multi-work folders and investigation persistence.
import { launch, delay } from './cdp.mjs';
import { mkdirSync, writeFileSync } from 'node:fs';
import assert from 'node:assert/strict';
const base=(process.env.BASE || 'http://127.0.0.1:5173/').replace(/\/?$/, '/');
const out=process.env.OUT || '/tmp/rolecraft-integration-check';mkdirSync(out,{recursive:true});
const b=await launch();
const checks=[];
const waitFor=async(expr)=>{for(let i=0;i<70;i++){if(await b.ev(expr))return;await delay(100);}throw new Error('Timeout: '+expr);};
const check=async(name,fn)=>{await fn();checks.push(name);console.log('PASS '+name);};
try {
  await b.goto(base);
  await waitFor('!!window.PracticeLive');
  const ids=await b.ev(`(async()=>{const L=window.PracticeLive,E=L.engine;const a=await L.start('pilot');
    await L.config(a,{participants:20,domains:['faq','policy'],update:'daily',fallback:'human',workItems:['scope','fallback'],launchDay:7});
    const run=await L.test(a,{question:'住宿报销上限是多少？',taskId:a.tasks[1].id});
    await L.action(a,'read_material',{material_id:'business'});
    const work=E.createArtifact(a,{kind:'investigation',taskId:a.tasks[1].id,title:'整合验收：政策调查工作纸',question:'旧回答与当前资料是否一致？',source:'user',adopted:true,blocks:[{type:'source_check',testId:run.id,material:{id:'policy',version:a.world.policyVersion}},{type:'retest',testId:run.id}]});
    E.createArtifact(a,{taskId:work.taskId,title:'整合验收：同事项第二份作品',body:'合成验收内容，用于检验文件夹打开确切作品。',source:'user',adopted:true});
    localStorage.setItem('rolecraft.open-work.ui.v1',JSON.stringify(L.state));
    return {work:work.id,task:work.taskId,firstAnswer:run.answer,policy:a.world.policyVersion,index:a.world.indexVersion};})()`);
  assert.ok(ids.firstAnswer.includes('500'));assert.equal(ids.policy,2);assert.equal(ids.index,1);
  await b.goto(base+'#/work');await delay(1000);
  await check('document expand, interrupted return, focus and no leftover layer',async()=>{
    await b.ev(`document.querySelector('.doc-card[data-id="brief"]').click()`);await delay(90);
    await b.ev(`document.querySelector('[data-action="to-board"]').click()`);await delay(90);
    await b.ev(`document.querySelector('.doc-card[data-id="brief"]').click()`);await delay(850);
    assert.equal(await b.ev('document.querySelectorAll(".document-flight").length'),0);
    assert.equal(await b.ev('document.activeElement.id'),'document-title-brief');
    await b.click('[data-action="to-board"]');
  });
  const folder=`[data-work-folder="${ids.task}"] [data-folder-toggle]`;
  await check('folder opens the exact investigation and loads source comparison',async()=>{
    await b.click(folder);await b.shot(out+'/folder-desktop.jpg');
    await b.click(`[data-folder-card="${ids.work}"]`);
    assert.equal(await b.ev('document.documentElement.dataset.input'),'keyboard');
    await waitFor('!!document.querySelector(".inv-diff-surface .diff")');
    assert.equal(await b.ev('document.querySelectorAll(".work-folder-tray,.work-folder-flight-layer").length'),0);
    assert.equal(await b.ev('document.getElementById("editor-title").value'),'整合验收：政策调查工作纸');
  });
  await check('review draft survives mode change, save, reload and folder reopening',async()=>{
    await b.type('#investigation-review-note','整合验收：先检查索引版本，保留这条用户判断。');
    await b.click('[data-action="investigation-mode"][data-mode="original"]');
    assert.equal(await b.ev('document.getElementById("investigation-review-note").value'),'整合验收：先检查索引版本，保留这条用户判断。');
    await b.click('[data-action="investigation-review-save"]');
    await b.goto(base+'#/work');await delay(600);
    await b.click(folder);await b.click(`[data-folder-card="${ids.work}"]`);
    assert.equal(await b.ev('document.getElementById("investigation-review-note").value'),'整合验收：先检查索引版本，保留这条用户判断。');
  });
  await check('explicit refresh then retest keeps v2/400 result with judgment',async()=>{
    await b.click('[data-action="investigation-refresh-index"]');
    await b.click('[data-action="investigation-retest"]');
    await waitFor('!!document.querySelector(".inv-result-label")');
    assert.ok((await b.text('.inv-run-pane')).some(t=>t.includes('400')));
    assert.equal(await b.ev('document.getElementById("investigation-review-note").value'),'整合验收：先检查索引版本，保留这条用户判断。');
    await b.shot(out+'/investigation-desktop.jpg');
  });
  await check('390px folder and workpaper stay inside viewport',async()=>{
    await b.send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:2,mobile:true});
    await delay(350);assert.equal(await b.ev('document.documentElement.scrollWidth-document.documentElement.clientWidth'),0);
    await b.shot(out+'/investigation-mobile.jpg');await b.click('[data-action="to-board"]');await b.click(folder);
    assert.equal(await b.ev('document.documentElement.scrollWidth-document.documentElement.clientWidth'),0);
    await b.shot(out+'/folder-mobile.jpg');
    await b.click(`[data-folder-card="${ids.work}"]`);
    assert.ok(await b.ev('!!document.querySelector(".investigation-work")'));
  });
  await check('reduced motion skips document flight and folder keyboard recovers focus',async()=>{
    await b.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
    await b.click('[data-action="to-board"]');await b.click('.doc-card[data-id="brief"]');
    assert.equal(await b.ev('document.querySelectorAll(".document-flight").length'),0);
    await b.click('[data-action="to-board"]');
    await b.ev(`document.querySelector(${JSON.stringify(folder)}).focus()`);
    await b.send('Input.dispatchKeyEvent',{type:'keyDown',key:'ArrowDown',code:'ArrowDown'});await delay(150);
    assert.ok(await b.ev('document.activeElement.matches("[data-folder-card]")'));
    await b.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});await delay(100);
    assert.ok(await b.ev('document.activeElement.matches("[data-folder-toggle]")'));
    assert.equal(await b.ev('document.querySelectorAll(".work-folder-tray,.work-folder-flight-layer").length'),0);
  });
  assert.deepEqual(b.logs,[]);
  writeFileSync(out+'/result.json',JSON.stringify({checks,logs:b.logs},null,2));
} catch(e){await b.shot(out+'/failure.jpg');console.error(e);console.log(JSON.stringify(b.logs));process.exitCode=1;}
finally{await b.close();}
