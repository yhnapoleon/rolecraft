import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { launch, delay } from '../../../tests/walkthrough/cdp.mjs';
import { waitFor, clickReady } from '../../../tests/regression/browser-support.mjs';
const base = process.env.BASE;
const out = process.env.OUT;
mkdirSync(out, { recursive: true });
const results = [];
for (const language of ['zh', 'en']) {
  const browser = await launch({ width: 1440, height: 1000, reduced: true });
  try {
    await browser.send('Page.bringToFront');
    await browser.send('Emulation.setFocusEmulationEnabled', { enabled: true });
    await browser.goto(base);
    await browser.ev(`localStorage.clear(); localStorage.setItem('rolecraft.locale', '${language}')`);
    await browser.goto(base);
    await waitFor(browser, `!!document.querySelector('[data-action="open-career"]')`);
    await browser.click('[data-action="open-career"]');
    await browser.click('.case-hero [data-action="take-case"]');
    await waitFor(browser, `!!document.querySelector('.card-open')`);
    await browser.click('.card-open');
    await waitFor(browser, `!!document.querySelector('[data-action="chat"][data-role="technical"]')`);
    await browser.click('[data-action="chat"][data-role="technical"]');
    const questions = language === 'zh' ? [
      '当前试点容量是多少？', '刷新索引这个操作会做什么？',
      '我认为保存配置就已经批准扩容，这样理解对吗？', '请直接给我完整试点方案。',
    ] : [
      'What is the current pilot capacity?', 'What does refreshing the index do?',
      'I think saving a configuration approves capacity. Is that correct?',
      'Give me the complete pilot solution.',
    ];
    for (const question of questions) {
      const count = await browser.ev(`document.querySelectorAll('.rc-roles__reply').length`);
      await waitFor(browser, `document.querySelector('.composer [type="submit"]')?.disabled === false`);
      await browser.type('#chat-input', question);
      await browser.submit('.composer');
      await waitFor(browser, `document.querySelectorAll('.rc-roles__reply').length > ${count}`, 60000);
      assert.ok(await browser.ev(`document.querySelectorAll('.rc-roles__details').length > ${count}`));
      const marker = language === 'zh' ? '等待模型接入' : 'waiting for model connection';
      assert.ok(await browser.ev(`document.querySelector('.rc-roles__turn:last-child').innerText.includes(${JSON.stringify(marker)})`));
      results.push({ language, question, mechanism: 'local', status: 'passed', semantic_quality: 'blocked' });
    }
    const workTitle = language === 'zh' ? '容量条件笔记' : 'Capacity conditions';
    const condition = language === 'zh'
      ? '只有明确申请获批并生效后才能扩容。'
      : 'Capacity changes only after explicit approval is committed.';
    const workText = `${language === 'zh' ? '容量可扩至80人。' : 'Capacity can reach 80 users.'}\n${condition}`;
    await browser.type('#new-title', workTitle);
    await browser.type('#new-body', workText);
    await browser.clickText(language === 'zh' ? '保存为作品' : 'Save as work');
    await waitFor(browser, `!!document.querySelector('.ol-row[data-type="work"]')`);
    await browser.click('.ol-row[data-type="work"]');
    await waitFor(browser, `!!document.querySelector('[data-v4-insertion="sharing"] select')`);
    const shareLabel = language === 'zh' ? '分享已保存的这版' : 'Share this saved version';
    await waitFor(browser, `Array.from(document.querySelectorAll('button')).some(n => n.textContent.trim() === ${JSON.stringify(shareLabel)} && !n.disabled)`);
    await browser.select('[data-v4-insertion="sharing"] select', 'tech_lead');
    await waitFor(browser, `document.querySelector('[data-v4-insertion="sharing"] select')?.value === 'tech_lead'`);
    await waitFor(browser, `document.querySelectorAll('.rc-roles__reply').length === ${questions.length}`);
    const beforeShare = await browser.ev(`document.querySelectorAll('.rc-roles__reply').length`);
    await clickReady(browser, shareLabel);
    await waitFor(browser, `document.querySelectorAll('.rc-roles__reply').length > ${beforeShare}`, 60000);
    const preview = await browser.ev(`Array.from(document.querySelectorAll('.rc-roles__preview')).at(-1).textContent`);
    assert.ok(!preview.includes('80') || preview.includes(condition), 'Preview must preserve the complete condition');
    const versionNote = language === 'zh' ? '新版需要重新分享' : 'share a new version explicitly';
    assert.ok(await browser.ev(`Array.from(document.querySelectorAll('.rc-roles__limitation')).some(n => n.innerText.includes(${JSON.stringify(versionNote)}))`));
    const displayCount = `(async () => {
      const live = window.PracticeLive;
      let data = await live.v4Host(live.engine.getAttempt(live.state)).query('timeline');
      while (data.result) data = data.result;
      return data.objects.filter(row => row.ref.kind === 'role_display').length;
    })()`;
    assert.equal(await browser.ev(displayCount), 0, 'Collapsed replies must not count as displayed');
    await browser.shot(`${out}/${language}-desktop.jpg`);
    await browser.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
    await browser.send('Emulation.setEmulatedMedia', { features: [
      { name: 'prefers-color-scheme', value: 'dark' },
      { name: 'prefers-reduced-motion', value: 'reduce' },
    ] });
    await browser.click('[data-action="open-rail"]');
    await waitFor(browser, `!!document.querySelector('.rc-roles__details summary') && document.querySelector('.rc-roles__details summary').offsetParent !== null`);
    await browser.ev(`Array.from(document.querySelectorAll('.rc-roles__details summary')).at(-1).focus()`);
    await browser.send('Input.dispatchKeyEvent', { type: 'keyDown', text: '\r', unmodifiedText: '\r', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
    await browser.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
    await delay(200);
    assert.ok(await browser.ev(`!!document.querySelector('.rc-roles__details[open]')`));
    assert.equal(await browser.ev('document.documentElement.scrollWidth > document.documentElement.clientWidth'), false);
    await waitFor(browser, `(${displayCount}).then(count => count === 1)`, 15000);
    await browser.shot(`${out}/${language}-narrow-expanded.jpg`);
    const route = await browser.ev('location.hash');
    await browser.goto(base + route);
    await waitFor(browser, '!!window.PracticeLive');
    assert.equal(await browser.ev(displayCount), 1, 'Refresh must not replay display writes');
    results.push({ language, check: '390px, dark, keyboard, reduced motion', status: 'passed' });
  } catch (error) {
    await browser.shot(`${out}/${language}-failure.jpg`);
    writeFileSync(`${out}/results.json`, JSON.stringify([...results, { language, error: String(error) }], null, 2));
    throw error;
  } finally {
    await browser.close();
  }
}
writeFileSync(`${out}/results.json`, JSON.stringify(results, null, 2));
