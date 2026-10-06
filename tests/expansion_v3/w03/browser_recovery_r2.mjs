// Real isolated Chromium tabs + native localStorage/Web Locks. Transport is
// explicitly synthetic; this is recovery QA, not W01/API/product integration.
import {spawn} from 'node:child_process';
import {mkdirSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {randomUUID} from 'node:crypto';
import assert from 'node:assert/strict';
import {setTimeout as delay} from 'node:timers/promises';

const evidence=resolve(process.argv[2]),origin=process.argv[3]||'http://127.0.0.1:18660';
mkdirSync(evidence,{recursive:true});
const chrome=process.env.CHROME_BIN||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const proc=spawn(chrome,['--headless=new','--remote-debugging-port=0','--user-data-dir='+join(evidence,'browser-profile'),
  '--no-first-run','--disable-default-apps','--disable-sync','about:blank'],{stdio:['ignore','ignore','pipe']});
let stderr='',ws,sequence=0;const pending=new Map(),exceptions=[],results=[];
try{
  const wsUrl=await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(Error('Chrome startup timeout '+stderr)),15000);
    proc.stderr.on('data',chunk=>{stderr+=chunk;const m=stderr.match(/ws:\/\/[^\s]+/);if(m){clearTimeout(timer);resolve(m[0]);}});
    proc.once('exit',code=>{clearTimeout(timer);reject(Error('Chrome exited '+code));});
  });
  ws=new WebSocket(wsUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));
  ws.addEventListener('message',event=>{
    const m=JSON.parse(event.data);
    if(m.id && pending.has(m.id)){const p=pending.get(m.id);clearTimeout(p.timer);pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}
    if(m.method==='Runtime.exceptionThrown')exceptions.push(m.params.exceptionDetails);
  });
  const send=(method,params={},sessionId)=>new Promise((resolve,reject)=>{
    const id=++sequence;const timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout '+method));},15000);
    pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));
  });
  const run='w03-r2-test-'+randomUUID(),url=origin+'/src/features/workspace/recovery-browser.html?session='+run;
  const page=async()=>{
    const {targetId}=await send('Target.createTarget',{url:'about:blank'});
    const {sessionId}=await send('Target.attachToTarget',{targetId,flatten:true});
    await send('Runtime.enable',{},sessionId);await send('Page.enable',{},sessionId);
    const ev=async expression=>{const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true},sessionId);if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
    const ready=async()=>{for(let i=0;i<100;i++){if(await ev('!!window.harness?.ready'))return;await delay(50);}throw Error('fixture not ready');};
    await send('Page.navigate',{url},sessionId);await ready();
    return {ev,sessionId,reload:async()=>{await send('Page.reload',{},sessionId);await delay(100);await ready();},
      screenshot:async name=>{await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false},sessionId);const p=await send('Page.captureScreenshot',{format:'png'},sessionId);writeFileSync(join(evidence,name),Buffer.from(p.data,'base64'));}};
  };
  const [a,b]=await Promise.all([page(),page()]);
  assert.equal(await a.ev('!!navigator.locks?.request'),true);
  await Promise.all([a.ev("harness.client.keepDraft('p1',{...harness.draftOf(harness.client.snapshot().products[0]),content:'tab A kept'})"),
    b.ev("harness.client.keepDraft('p2',{...harness.draftOf(harness.client.snapshot().products[1]),content:'tab B kept'})")]);
  await a.reload();let journal=await a.ev('harness.client.snapshot().journal');
  assert.equal(journal.drafts.p1.content,'tab A kept');assert.equal(journal.drafts.p2.content,'tab B kept');
  results.push({id:'R1-different-drafts',result:'pass',nativeWebLocks:true,reloadedDrafts:Object.keys(journal.drafts)});

  await a.ev('harness.controls.lose=true;harness.controls.delayMs=150');
  const uncertain=a.ev("harness.client.save(harness.client.snapshot().products[0]).then(()=>false,e=>e.message)");
  await delay(50);await b.ev("harness.client.keepDraft('p2',{...harness.client.snapshot().journal.drafts.p2,content:'B during pending'})");
  assert.match(await uncertain,/lost response/);await b.reload();journal=await b.ev('harness.client.snapshot().journal');
  const key=journal.pending.command.request_id;
  assert.equal(journal.drafts.p2.content,'B during pending');await b.ev('harness.client.retry()');
  const server=await b.ev('harness.read()');assert.equal(server.products[0].version,2);
  assert.equal(server.requests.filter(r=>r.request_id===key).length,2);
  assert.equal((await b.ev('harness.client.snapshot().journal')).drafts.p2.content,'B during pending');
  results.push({id:'R1-pending-survives-other-tab',result:'pass',originalRequest:key,actualProductVersion:2});

  await a.reload();await a.ev("harness.client.keepDraft('p1',{...harness.draftOf(harness.client.snapshot().products[0]),content:'A based on v2'})");
  await b.ev('harness.externalEdit()');await a.reload();journal=await a.ev('harness.client.snapshot().journal');
  const refused=await a.ev('harness.client.save(harness.client.snapshot().products[0]).then(()=>false,e=>e.message)');
  assert.match(refused,/草稿基准/);assert.equal(journal.draftBases.p1.product.version,2);
  assert.equal((await a.ev('harness.read()')).products[0].content,'other tab server content');
  await a.ev("document.querySelectorAll('.rc-workspace-work')[0].click()");await delay(100);await a.screenshot('r2-conflict-preserved.png');
  await a.ev("(async()=>{const c=harness.client;await c.confirmMerge('p1',{...c.snapshot().journal.drafts.p1,content:'explicit A plus B merge'},3,c.snapshot().journal.draftTokens.p1);await c.save(c.snapshot().products[0]);})()");
  assert.equal((await a.ev('harness.read()')).products[0].content,'explicit A plus B merge');
  results.push({id:'R2-refresh-keeps-base-and-explicit-merge',result:'pass',draftBaseBeforeMerge:2,serverHeadReviewed:3});

  await a.ev("harness.controls.rejectOnce={status:409,code:'version_conflict'}");
  assert.match(await a.ev("harness.client.createTask({title:'original rejected task'}).then(()=>false,e=>e.message)"),/version_conflict/);
  await a.reload();journal=await a.ev('harness.client.snapshot().journal');assert.equal(journal.pending,undefined);
  const rejected=Object.values(journal.rejected).find(r=>r.request.command.payload.title==='original rejected task');assert.ok(rejected);
  await a.screenshot('r3-rejected-input-recoverable.png');
  await a.ev("harness.client.createTask({title:'independent later task'})");
  // Exercise the actual component's explicit retry button, not an automatic retry.
  await a.ev("[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Checked: refresh and submit again')).click()");
  for(let i=0;i<100;i++){if((await a.ev('harness.read().tasks.length'))===2)break;await delay(50);}
  const final=await a.ev('harness.read()');assert.equal(final.tasks.length,2);
  const attempts=final.requests.filter(r=>r.payload.title==='original rejected task');assert.equal(attempts.length,2);assert.notEqual(attempts[0].request_id,attempts[1].request_id);
  results.push({id:'R3-rejection-unlocks-and-explicit-new-request',result:'pass',preservedInput:true,requestKeys:attempts.map(r=>r.request_id)});
  assert.equal(exceptions.length,0);
  const report={result:'pass',scope:'Isolated Chromium tabs, native Web Locks/localStorage and real feature component; synthetic transport, NOT product/API integration',browser:await send('Browser.getVersion'),results,exceptions};
  writeFileSync(join(evidence,'browser-result.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
}catch(error){const report={result:'fail',error:String(error.stack||error),results,exceptions};writeFileSync(join(evidence,'browser-result.json'),JSON.stringify(report,null,2)+'\n');console.error(error);process.exitCode=1;}
finally{if(ws)ws.close();proc.kill('SIGTERM');}
