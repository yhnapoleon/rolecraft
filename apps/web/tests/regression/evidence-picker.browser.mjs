import { clickReady, waitFor, submitDelivery } from './browser-support.mjs';
/** Cite read passages, test runs and work versions in the normal v4 entry, then read the
 * shortened feedback. Real HTTP API and worker; BASE is the web entry, OUT a new directory. */
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { delay, launch } from '../walkthrough/cdp.mjs';

const base = process.env.BASE;
const output = process.env.OUT;
assert.ok(base && output, 'BASE and OUT are required');
mkdirSync(output, { recursive: true });
const results = [];

const pickerOpen = `!!document.querySelector('dialog.evidence-picker[open]')`;
const tick = (browser, section, row = 0) =>
  browser.ev(`(() => {
    const box = document.querySelectorAll('dialog.evidence-picker section')[${section}]
      ?.querySelectorAll('input[type=checkbox]')[${row}];
    if (!box) return false;
    box.click();
    return true;
  })()`);
const checked = (browser, section) =>
  browser.ev(`[...(document.querySelectorAll('dialog.evidence-picker section')[${section}]
    ?.querySelectorAll('input[type=checkbox]') ?? [])].map((box) => box.checked)`);
const mainQuestion = `[...document.querySelectorAll('[data-outcome-question]')]
  .some((node) => !node.closest('details'))`;

async function run(language, reduced, width, flow) {
  const browser = await launch({ width, height: 1000, reduced, mobile: width < 600 });
  const tag = `${language}-${reduced ? 'reduced' : 'motion'}${width < 600 ? '-390' : ''}${flow === 'main' ? '' : `-${flow}`}`;
  const text = (zh, en) => (language === 'en' ? en : zh);
  const shot = async (name) => {
    await delay(reduced ? 300 : 900);
    await browser.shot(`${output}/${tag}-${name}.jpg`);
  };
  const step = async (name, action) => {
    await action();
    results.push({ tag, name, status: 'passed' });
    console.log(`PASS ${tag}: ${name}`);
  };
  let decidedPanel = '';
  const noSideScroll = async () =>
    assert.equal(
      await browser.ev(
        'document.documentElement.scrollWidth > document.documentElement.clientWidth',
      ),
      false,
      'no horizontal scroll',
    );
  try {
    await browser.goto(base);
    await browser.ev(
      `localStorage.clear(); localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)});`,
    );
    await browser.goto(base);
    await step('enter the practice', async () => {
      await waitFor(browser, `!!document.querySelector('.home-roles [data-role="pm"] [data-action="open-career"]')`);
      await browser.click('.home-roles [data-role="pm"] [data-action="open-career"]');
      await browser.click('.case-hero [data-action="take-case"]');
      await waitFor(
        browser,
        `location.hash === '#/work' && !!document.querySelector('.card-open')`,
      );
    });
    if (flow === 'investigation') {
      await step('the investigation worksheet cites its run through the picker', async () => {
        await browser.click('.product-bar [data-action="open-bench"]');
        await browser.type(
          '#lab-q',
          text('住宿报销上限是多少？', 'What is the hotel reimbursement limit?'),
        );
        await browser.submit('[data-form="run-test"]');
        await waitFor(browser, `!!document.querySelector('.run [data-action="investigate-run"]')`);
        await browser.click('.run [data-action="investigate-run"]');
        // The run was made on the board, so the person places the investigation under a task.
        await waitFor(
          browser,
          `!!document.querySelector('[data-action="native-investigation-task"]')`,
        );
        await browser.click('[data-action="native-investigation-task"]');
        const cite = `document.querySelector('[data-action="investigation-cite"]')`;
        await waitFor(browser, `!!${cite} && !${cite}.disabled`, 20000);
        await browser.ev(`${cite}.scrollIntoView({ block: 'center' })`);
        await shot('investigation');
        // Earlier notices may still be in the toast; only what citing says counts.
        await browser.ev(`document.querySelector('#toast').textContent = ''`);
        await browser.click('[data-action="investigation-cite"]');
        const toast = `document.querySelector('#toast')?.textContent ?? ''`;
        await waitFor(browser, `${pickerOpen} || (${toast}).length > 0`);
        assert.equal(await browser.ev(toast), '', 'citing opens the picker without an error');
        assert.deepEqual(await checked(browser, 1), [true], 'the run is already chosen');
        await shot('investigation-picker');
        await browser.clickText(text('使用选中的依据', 'Use selected evidence'), 'dialog button');
        await waitFor(browser, `!document.querySelector('dialog.evidence-picker')`);
        await waitFor(
          browser,
          `(${toast}).includes(${JSON.stringify(
            text('依据已加入草稿，保存这版后生效。', 'Evidence added to your draft.'),
          )})`,
        );
        await shot('investigation-cited');
        // Saving the version keeps the cited run with the investigation.
        await clickReady(browser, text('保存这版', 'Save this version'));
        await waitFor(
          browser,
          `(() => {
            const live = window.PracticeLive;
            const practice = live.state.attempts.find((a) => a.id === live.state.activeId);
            const work = document.querySelector('[data-action="obj"][data-type="work"]')?.dataset.id;
            return !!practice && !!work &&
              live.nativeEvidence(practice, work).some((ref) => ref.kind === 'test') &&
              !document.querySelector('#ws-stage').innerText.includes(${JSON.stringify(
                text('草稿已保留', 'Draft retained'),
              )});
          })()`,
          20000,
        );
        await shot('investigation-saved');
      });
      assert.deepEqual(
        browser.logs.filter((item) => item.level === 'exception'),
        [],
      );
      return;
    }
    await step('run a test and read its source', async () => {
      await browser.click('.product-bar [data-action="open-bench"]');
      await browser.type(
        '#lab-q',
        text('住宿报销上限是多少？', 'What is the hotel reimbursement limit?'),
      );
      await browser.submit('[data-form="run-test"]');
      await waitFor(browser, `document.querySelectorAll('.run').length > 0`);
      // Opening the cited source reads it, so its passages can be cited.
      await browser.click('.run [data-action="run-source"]');
      await waitFor(browser, `!!document.querySelector('#sheet[open]')`);
      await delay(500);
      await browser.click('#sheet [data-action="close"]');
      await browser.click('[data-action="to-board"]');
      if (reduced) {
        // Opening a document card reads it too (the default-motion pass skips this path).
        await browser.click('.doc-card[data-id="brief"]');
        await waitFor(browser, `location.hash.startsWith('#/doc/')`);
        await delay(800);
        await browser.click('[data-action="to-board"]');
      }
    });
    await step('a decision without cited evidence is asked for it', async () => {
      await browser.click('.card-open');
      await browser.type('#new-title', text('试点决定草稿', 'Pilot decision draft'));
      await browser.type(
        '#new-body',
        text('先小范围开放，依据见引用。', 'Open narrowly first; see the cited basis.'),
      );
      await browser.clickText(text('保存为作品', 'Save as work'));
      await waitFor(browser, `!!document.querySelector('.ol-row[data-type="work"]')`);
      await browser.click('.ol-row[data-type="work"]');
      await waitFor(browser, `!!document.querySelector('#editor-body')`);
      await browser.select('[data-edit="purpose"]', '试点决定');
      await clickReady(browser, text('保存这版', 'Save this version'));
      await waitFor(browser, mainQuestion, 20000);
      await shot('preview-asks');
    });
    await step('cite a passage and a test run from the preview', async () => {
      await browser.click('[data-outcome-question] [data-action="cite-pick"]');
      await waitFor(browser, pickerOpen);
      assert.deepEqual(
        await browser.ev(
          `[...document.querySelectorAll('dialog.evidence-picker h3')].map((n) => n.textContent)`,
        ),
        [
          text('读过的资料段落', 'Passages you read'),
          text('测试运行', 'Test runs'),
          text('作品版本', 'Work versions'),
        ],
      );
      // The work being edited is never offered as its own evidence.
      assert.deepEqual(await checked(browser, 2), []);
      await noSideScroll();
      await shot('picker');
      if (reduced)
        assert.equal(
          await browser.ev(`document.querySelectorAll('dialog.evidence-picker h4').length`),
          2,
          'passages of both read documents are offered',
        );
      assert.ok(await tick(browser, 0));
      assert.ok(await tick(browser, 1));
      await browser.clickText(text('使用选中的依据', 'Use selected evidence'), 'dialog button');
      await waitFor(browser, `!document.querySelector('dialog.evidence-picker')`);
      await waitFor(browser, `document.querySelectorAll('.evidence-row .chip').length === 2`);
      await shot('cited-draft');
      await clickReady(browser, text('保存这版', 'Save this version'));
      await waitFor(
        browser,
        `document.querySelector('.w03-outcome-meta')?.textContent.includes(${JSON.stringify(
          text('按第 3 版计算', 'Computed for version 3'),
        )}) && !(${mainQuestion})`,
        20000,
      );
      await shot('preview-satisfied');
    });
    await step(
      'a test result offers itself as evidence, and closing keeps the choice',
      async () => {
        await browser.click('.action-bar [data-action="obj"][data-type="bench"]');
        // The run was made on the board, so it is listed under all tests.
        await browser.clickText(text('全部测试', 'All tests'));
        await waitFor(browser, `!!document.querySelector('.run [data-action="cite-run"]')`);
        await browser.click('.run [data-action="cite-run"]');
        await waitFor(browser, pickerOpen);
        assert.deepEqual(await checked(browser, 1), [true]);
        await shot('picker-from-run');
        await browser.click('dialog.evidence-picker .sheet-head button');
        await waitFor(browser, `!document.querySelector('dialog.evidence-picker')`);
      },
    );
    await step('a resource request cites the test run and the decision', async () => {
      await browser.click('[data-action="to-board"]');
      await browser.click('.product-bar [data-action="resources"]');
      await waitFor(browser, `!!document.querySelector('#res-form [name="reason"]')`);
      await browser.click('#res-form [name="kind"][value="request_resources"]');
      await browser.type('#res-form [name="dev_days"]', '6');
      await browser.type(
        '#res-form [name="reason"]',
        text('实时同步需要更多开发人日。', 'Real-time sync needs more developer-days.'),
      );
      await browser.clickText(text('选择依据', 'Choose evidence'), '#res-form button');
      await waitFor(browser, pickerOpen);
      assert.ok(await tick(browser, 1));
      assert.ok(await tick(browser, 2));
      await shot('picker-request');
      await browser.clickText(text('使用选中的依据', 'Use selected evidence'), 'dialog button');
      await waitFor(
        browser,
        `[...document.querySelectorAll('#res-form .meta')].some((n) => n.textContent === ${JSON.stringify(
          text('已选依据：1 次测试 · 1 份作品', 'Selected evidence: 1 test run · 1 work version'),
        )})`,
      );
      await browser.click('[form="res-form"][type="submit"]');
      await clickReady(browser, text('核实申请', 'Check request'));
      await waitFor(
        browser,
        `document.querySelector('[data-w04-resource-results]')?.textContent.length > 0`,
      );
      await shot('request-decided');
      decidedPanel = await browser.ev(
        `document.querySelector('[data-w04-resource-results]').innerText`,
      );
      await browser.click('#sheet [data-action="close"]');
      await waitFor(browser, `!document.querySelector('#sheet').open`);
    });
    await step('submit the decision and read the shortened feedback', async () => {
      await browser.click('.ws-toolbar [data-action="submit"]');
      await waitFor(browser, `!!document.querySelector('.native-feedback input[type="checkbox"]')`);
      await browser.click('.native-feedback input[type="checkbox"]');
      await browser.select('.native-feedback select', 'launch_narrow');
      await submitDelivery(browser);
      await waitFor(browser, `window.PracticeLive.store.active().world.status === 'submitted'`);
      await browser.ev(`document.querySelector('#sheet')?.close()`);
      await browser.goto(`${base}#/review`);
      await waitFor(browser, `!!document.querySelector('[data-rule-lines]')`, 30000);
      await waitFor(
        browser,
        `!!document.querySelector('[data-action="practice-reload"], [data-action="practice-choose"]')`,
        30000,
      );
      if (await browser.ev(`!!document.querySelector('[data-action="practice-reload"]')`))
        await browser.click('[data-action="practice-reload"]');
      await waitFor(
        browser,
        `document.querySelectorAll('[data-action="practice-choose"]').length > 0`,
      );
      const premise = text(
        '本项仅核对明确承诺的受限范围及固定配置。',
        'This criterion checks only the committed limited scope and fixed configuration.',
      );
      // Item by item (195): the premise is stated once, in the scope line's basis.
      const first = await browser.ev(`document.querySelector('[data-rule-lines]').textContent`);
      assert.equal(first.split(premise).length - 1, 1, 'the shared premise is stated once');
      assert.ok(
        !(await browser.ev(
          `[...document.querySelectorAll('.practice-option')].some((card) => card.innerText.includes(${JSON.stringify(premise)}))`,
        )),
        'practice cards repeat no rule explanation',
      );
      // The recorded decision is shown as written: the heading line, then one sentence per
      // request in the words of the request panel (lower case mid-sentence in English).
      const decisions = await browser.ev(
        `[...document.querySelectorAll('.business-decisions p')].map((n) => n.textContent)`,
      );
      assert.deepEqual(
        decisions.slice(0, 1),
        [text('已记录的业务决定（规则核实）：', 'Recorded business decisions (rule checked):')],
        'the heading line',
      );
      assert.equal(decisions.length, 2, 'the heading line, then the one recorded decision');
      const line = decisions[1];
      assert.ok(
        line.startsWith(text('开发人日：申请 6 · ', 'Person-days: requested 6 · ')),
        line,
      );
      const status = text(
        ['未批准', '已批准', '还价待接受', '已接受'],
        ['Declined', 'Approved', 'Counteroffer awaiting acceptance', 'Accepted'],
      ).find((word) => line.toLowerCase().includes(word.toLowerCase()));
      assert.ok(status && decidedPanel.includes(status), 'the panel and the record agree');
      await noSideScroll();
      await shot('feedback');
      // The expanded items keep their findings without repeating the shared premise.
      await browser.ev(`(() => {
        const row = document.querySelector('.native-feedback [data-feedback-item] .fb-item__head');
        row.click();
        row.scrollIntoView({ block: 'start' });
      })()`);
      const details = await browser.ev(
        `[...document.querySelectorAll('.native-feedback .rule-detail')].map((n) => n.textContent)`,
      );
      assert.ok(details.length >= 5);
      assert.ok(!details.some((line) => line.startsWith(premise)), 'items omit the shared premise');
      await shot('feedback-items');
    });
    await step('a supplement cites the test run', async () => {
      // The panel may re-render; every action reads the current general response form.
      const general = `[...document.querySelectorAll('details[data-response-id]')]
        .find((node) => node.dataset.responseId.endsWith(':general:'))`;
      const control = (match) =>
        `[...(${general}).querySelectorAll('button')].find((b) => ${match})`;
      await browser.ev(`(() => {
        const form = ${general};
        form.open = true;
        form.scrollIntoView({ block: 'center' });
      })()`);
      await browser.ev(
        `(${control(`b.textContent === ${JSON.stringify(text('选择依据', 'Choose evidence'))}`)}).click()`,
      );
      await waitFor(browser, pickerOpen);
      assert.ok(await tick(browser, 1));
      await browser.clickText(text('使用选中的依据', 'Use selected evidence'), 'dialog button');
      await waitFor(
        browser,
        `(${general}).innerText.includes(${JSON.stringify(
          text('已选依据：1 次测试', 'Selected evidence: 1 test run'),
        )})`,
      );
      await browser.ev(`(() => {
        const box = (${general}).querySelector('textarea');
        box.value = ${JSON.stringify(text('配置 v2 之后已复测。', 'Retested after configuration v2.'))};
        box.dispatchEvent(new Event('input', { bubbles: true }));
      })()`);
      await shot('supplement');
      const supplement = control(`b.dataset.responseAction === 'supplement'`);
      await waitFor(browser, `!(${supplement}).disabled`);
      await browser.ev(`(${supplement}).click()`);
      await waitFor(
        browser,
        `[...document.querySelectorAll('.native-feedback blockquote')].some((node) => node.textContent === ${JSON.stringify(
          text('配置 v2 之后已复测。', 'Retested after configuration v2.'),
        )})`,
        20000,
      );
      await shot('supplement-recorded');
    });
    assert.deepEqual(
      browser.logs.filter((item) => item.level === 'exception'),
      [],
    );
  } catch (error) {
    results.push({ tag, status: 'failed', error: String(error) });
    await browser.shot(`${output}/${tag}-failure.jpg`).catch(() => {});
    throw error;
  } finally {
    writeFileSync(`${output}/${tag}-logs.json`, JSON.stringify(browser.logs, null, 2));
    writeFileSync(`${output}/result.json`, `${JSON.stringify(results, null, 2)}\n`);
    await browser.close();
  }
}

for (const flow of (process.env.FLOWS ?? 'main,investigation').split(','))
  for (const language of (process.env.LANGS ?? 'zh,en').split(','))
    for (const motion of (process.env.MOTION ?? 'reduced,motion').split(','))
      await run(language, motion === 'reduced', Number(process.env.WIDTH ?? 1440), flow);
