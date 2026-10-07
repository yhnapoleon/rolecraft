import assert from 'node:assert/strict';
import {writeFileSync,mkdirSync} from 'node:fs';
import {launch} from '../../../tests/walkthrough/cdp.mjs';
const output=process.env.W05_OUTPUT;if(!output)throw Error('W05_OUTPUT required');mkdirSync(output,{recursive:true});
const results=[];
for(const language of ['zh','en']){
 const browser=await launch({width:language==='en'?390:1200,height:900,mobile:language==='en'});
 try{
  await browser.goto('http://127.0.0.1:18958/src/features/feedback-native/review-check.html?lang='+language);
  assert.equal(await browser.ev('window.fixture.calls.length'),0);
  await browser.clickText(language==='en'?'Review artifacts while working':'工作中先评审作品');
  await browser.click('div[aria-label="'+(language==='en'?'Artifact versions to review':'评审的作品版本')+'"] input');
  await browser.type('input[aria-label="'+(language==='en'?'Artifact purpose (optional)':'作品用途（可留空）')+'"]','test plan');
  await browser.type('textarea[aria-label="'+(language==='en'?'Review question (optional)':'想核对的问题（可留空）')+'"]',language==='en'?'Does the new source support this note?':'新依据是否支持这份笔记？');
  await browser.click('div[aria-label="'+(language==='en'?'Link recorded challenges or additional evidence':'关联已记录的异议或补证')+'"] input');
  await browser.ev('window.fixture.remount()');
  await browser.clickText(language==='en'?'Review artifacts while working':'工作中先评审作品');
  assert.equal(await browser.ev('document.querySelector("input[placeholder]").value'),'test plan');
  assert.equal(await browser.ev('window.fixture.calls.length'),0);
  await browser.shot(output+'/'+language+'-review-form.jpg',false);
  assert.equal(await browser.ev('document.documentElement.scrollWidth<=innerWidth'),true);
  await browser.clickText(language==='en'?'Review selected versions':'评审选中的版本');
  const calls=await browser.ev('window.fixture.calls');assert.equal(calls.length,1);assert.equal(calls[0].operation,'reviews.create');assert.equal(calls[0].input.subjects[0].version,2);assert.equal(calls[0].input.decision,null);assert.equal(calls[0].input.followup_of[0].object_id,'response');
  assert.equal(await browser.ev('window.fixture.state.status'),'active');
  await browser.clickText(language==='en'?'Review and submission history':'查看评审与提交历史');
  await browser.clickText(language==='en'?'View reviewed artifact':'查看评审作品');
  assert.equal(await browser.ev('window.fixture.calls.at(-1).ref.version'),1);
  await browser.ev('window.fixture.state.status="submitted";window.fixture.update()');
  assert.equal(await browser.ev('[...document.querySelectorAll("button")].find(b=>b.textContent===' + JSON.stringify(language==='en'?'Review selected versions':'评审选中的版本') + ').disabled'),true);
  assert.deepEqual(browser.logs,[]);results.push({language,passed:true,checks:['no implicit request','draft restoration','exact version','unknown decision retained','explicit supplement link','nonterminal','old version reference','terminal disabled','viewport fit','no browser errors']});
 }finally{await browser.close();}
}
writeFileSync(output+'/browser-results.json',JSON.stringify({scope:'controlled component fixture; not normal v4/API acceptance',results},null,2)+'\n');console.log(JSON.stringify(results));
