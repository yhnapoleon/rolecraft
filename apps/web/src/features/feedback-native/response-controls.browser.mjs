import assert from 'node:assert/strict';
import { launch } from '../../../tests/walkthrough/cdp.mjs';
const base=process.env.W05_BASE;
if(!base) throw Error('W05_BASE must name an isolated Vite fixture server');
const browser=await launch();
try {
  await browser.goto(base+'/src/features/feedback-native/review-check.html?lang=en');
  await browser.ev('window.fixture.state.busy=true; window.fixture.update()');
  await browser.clickText('Challenge or supplement the evidence');
  await browser.type('details[data-response-id] textarea','Preserve this challenge while request state changes.');
  await browser.ev('window.responseEditor=document.querySelector("details[data-response-id] textarea")');
  const state=()=>browser.ev(`({focused:document.activeElement===window.responseEditor,value:window.responseEditor.value,sameNode:document.querySelector('details[data-response-id] textarea')===window.responseEditor,disabled:[...document.querySelectorAll('details[data-response-id] button')].filter(b=>/Record a challenge|Submit additional evidence/.test(b.textContent)).map(b=>b.disabled)})`);
  await browser.ev('window.fixture.state.busy=false; window.fixture.update()');
  let observed=await state();assert.deepEqual(observed.disabled,[false,false]);assert.ok(observed.focused&&observed.sameNode);assert.equal(observed.value,'Preserve this challenge while request state changes.');
  await browser.ev('window.fixture.state.busy=true; window.fixture.update()');
  assert.deepEqual((await state()).disabled,[true,true]);
  await browser.ev('window.fixture.state.busy=false; window.fixture.state.pending=true; window.fixture.update()');
  assert.deepEqual((await state()).disabled,[true,true]);
  await browser.ev('window.fixture.state.pending=false; window.fixture.update()');
  observed=await state();assert.deepEqual(observed.disabled,[false,false]);assert.ok(observed.focused&&observed.sameNode);
  console.log(JSON.stringify({passed:4,scope:'controlled native DOM state changes; production UI checked separately'}));
} finally {await browser.close();}
