import { afterAll, beforeAll, expect, it } from 'vitest';
import { createServer } from 'vite';
import { launch } from '../../../tests/walkthrough/cdp.mjs';

let server;
beforeAll(async () => {
  server = await createServer({ server: { port: 19810, strictPort: true }, logLevel: 'error' });
  await server.listen();
});
afterAll(async () => {
  await server?.close();
});

it('MODEL-02: synthetic feedback stays folded and identifies mechanism validation', async () => {
  const browser = await launch({ width: 390, height: 844, mobile: true, reduced: true });
  try {
    await browser.goto(
      'http://127.0.0.1:19810/src/features/feedback-native/review-check.html?lang=en',
    );
    await browser.ev(`window.fixture.state.reports[0].model_advice = [{
      criterion: 'R2.support', status: 'synthetic_mechanism_only',
      registration: { id: 'sample', model_revision: 'fixed', scope: 'synthetic_fixture', quality_validated: false },
      label: null, evidence_ids: [], citations: [], error_code: 'synthetic_mechanism_only',
      mode: 'advisory', affects_score: false
    }]; window.fixture.update();`);
    expect(
      await browser.ev(`document.querySelector('[data-model-advice] summary')?.textContent`),
    ).toBe('Mechanism validation');
    expect(await browser.ev(`document.querySelector('[data-model-advice]').open`)).toBe(false);
    expect(await browser.ev('window.fixture.calls')).toEqual([]);
  } finally {
    await browser.close();
  }
}, 20000);

const completed = {
  criterion: 'R2.support',
  status: 'completed',
  registration: {
    id: 'external-example',
    model_revision: 'fixed-revision',
    scope: 'external_candidate',
    quality_validated: false,
  },
  label: 'SUPPORTED',
  evidence_ids: ['public-source'],
  citations: [{ session_id: 'fixture', kind: 'product', object_id: 'note', version: 2 }],
  error_code: null,
  mode: 'advisory',
  affects_score: false,
};
const item = (criterion, source = 'pending', label = 'INSUFFICIENT') => ({
  criterion,
  source,
  label,
  explanation: 'Stored original',
  citations: [],
  applicability: 'applicable',
});

it.each(['zh', 'en'])(
  'MODEL-UI-coverage: %s keeps advice and pending coverage separate',
  async (language) => {
    const browser = await launch();
    try {
      await browser.goto(
        `http://127.0.0.1:19810/src/features/feedback-native/review-check.html?lang=${language}`,
      );
      await browser.ev(
        `Object.assign(window.fixture.state.reports[0], ${JSON.stringify({
          model_advice: [completed],
          items: [
            item('R1.target', 'verified_rule', 'MET'),
            item('R2.support'),
            item('R2.unknowns'),
            {
              ...item('R3.capacity', 'pending', 'NOT_APPLICABLE'),
              applicability: 'not_applicable',
            },
          ],
        })}); window.fixture.update();`,
      );
      const coverage = await browser.ev(
        `document.querySelector('[data-feedback-coverage]')?.textContent`,
      );
      expect(coverage).toBe(
        language === 'en'
          ? 'Verified by rules: 1/3 (33%) · Model advice: 1/3 (33%) · Pending verification: 1/3 (33%)'
          : '规则核实：1/3（33%） · 模型建议：1/3（33%） · 待核验：1/3（33%）',
      );
      expect(await browser.ev('window.fixture.calls')).toEqual([]);
    } finally {
      await browser.close();
    }
  },
);

async function withFeedback(language, run) {
  const browser = await launch({ width: 390, height: 844, mobile: true, reduced: true });
  try {
    await browser.goto(
      `http://127.0.0.1:19810/src/features/feedback-native/review-check.html?lang=${language}`,
    );
    await run(browser);
    expect(browser.logs.filter((entry) => entry.level === 'exception')).toEqual([]);
  } finally {
    await browser.close();
  }
}
const summaryText = (browser) =>
  browser.ev(`document.querySelector('[data-model-advice] summary')?.textContent`);
const setReport = (browser, report) =>
  browser.ev(
    `Object.assign(window.fixture.state.reports[0], ${JSON.stringify(report)}); window.fixture.update();`,
  );

it.each(['zh', 'en'])(
  'MODEL-UI-states: %s distinguishes empty, waiting, failed and completed advice',
  async (language) => {
    await withFeedback(language, async (browser) => {
      const en = language === 'en';
      expect(await summaryText(browser)).toBe(en ? 'Awaiting model connection' : '等待模型接入');
      await setReport(browser, { semantic_status: 'pending', model_advice: [] });
      expect(await summaryText(browser)).toBe(
        en ? 'Model advice awaiting verification' : '模型建议待核验',
      );
      await setReport(browser, { semantic_status: 'waiting_for_model' });
      expect(await summaryText(browser)).toBe(en ? 'Awaiting model connection' : '等待模型接入');
      await setReport(browser, { semantic_status: 'failed' });
      expect(await summaryText(browser)).toBe(en ? 'Model advice failed' : '模型建议失败');
      await setReport(browser, { semantic_status: 'available', model_advice: [completed] });
      expect(await summaryText(browser)).toBe(
        en ? 'Model advice (not scored)' : '模型建议（不计分）',
      );
      expect(await browser.ev(`document.querySelector('[data-model-advice]').open`)).toBe(false);
      await browser.click('[data-model-advice] summary');
      expect(await browser.ev(`document.querySelector('[data-model-advice]').open`)).toBe(true);
      await browser.ev('window.fixture.update()');
      expect(await browser.ev(`document.querySelector('[data-model-advice]').open`)).toBe(true);
      await browser.click('[data-model-advice] summary');
      await browser.ev('window.fixture.update()');
      expect(await browser.ev(`document.querySelector('[data-model-advice]').open`)).toBe(false);
      expect(await browser.ev('window.fixture.calls')).toEqual([]);
    });
  },
);

it.each(['zh', 'en'])(
  'MODEL-04: %s permission refresh removes only denied advice and retains keyboard focus',
  async (language) => {
    await withFeedback(language, async (browser) => {
      const second = {
        ...completed,
        evidence_ids: ['other-source'],
        citations: [{ ...completed.citations[0], object_id: 'other' }],
      };
      await setReport(browser, { model_advice: [completed, second], items: [item('R2.support')] });
      await browser.click('[data-model-advice] summary');
      await browser.ev(`document.querySelector('[data-model-reference]').focus()`);
      const denied = {
        ...completed,
        status: 'unavailable',
        label: null,
        evidence_ids: [],
        citations: [],
        error_code: 'evidence_unavailable',
      };
      await setReport(browser, { model_advice: [denied, second] });
      expect(await browser.ev(`document.querySelector('[data-model-advice]').open`)).toBe(true);
      expect(await browser.ev(`document.activeElement.tagName`)).toBe('SUMMARY');
      expect(await browser.ev(`document.querySelectorAll('[data-model-reference]').length`)).toBe(
        1,
      );
      expect(
        await browser.ev(`document.querySelector('[data-model-advice]').innerText`),
      ).not.toContain('public-source');
      expect(
        await browser.ev(`document.querySelector('[data-feedback-coverage]').textContent`),
      ).toContain(language === 'en' ? 'Model advice: 0/1 (0%)' : '模型建议：0/1（0%）');
      await browser.click('[data-model-reference]');
      expect(await browser.ev('window.fixture.calls')).toEqual([
        { operation: 'openReference', ref: second.citations[0] },
      ]);
      await browser.ev(
        `document.querySelector('[data-model-reference]').focus(); window.fixture.state.reports = []; window.fixture.update();`,
      );
      expect(await browser.ev(`document.querySelectorAll('[data-model-reference]').length`)).toBe(
        0,
      );
      expect(await summaryText(browser)).toBe(
        language === 'en' ? 'Model advice is unavailable' : '当前模型建议不可读取',
      );
    });
  },
);

it.each(['zh', 'en'])(
  'MODEL-06: %s keeps failure states and original feedback without a replacement model',
  async (language) => {
    await withFeedback(language, async (browser) => {
      await setReport(browser, {
        model_advice: [
          {
            ...completed,
            status: 'unavailable',
            label: null,
            evidence_ids: [],
            citations: [],
            error_code: 'model_load_failed',
          },
        ],
      });
      expect(await summaryText(browser)).toBe(
        language === 'en' ? 'Model advice failed' : '模型建议失败',
      );
      await browser.click('[data-model-advice] summary');
      expect(await browser.ev(`document.querySelector('[data-model-advice]').innerText`)).toContain(
        language === 'en'
          ? 'The registered model could not be loaded; no other model was substituted.'
          : '注册模型加载失败，未切换到其他模型。',
      );
      expect(await browser.ev(`document.querySelector('.native-feedback').innerText`)).toContain(
        language === 'en' ? 'Recorded fixture; no semantic judgment.' : '受控记录，未作语义判断。',
      );
      expect(await browser.ev('window.fixture.calls')).toEqual([]);
    });
  },
);

it.each(['zh', 'en'])(
  'MODEL-UI-layout: %s long registered identifiers wrap at 390px',
  async (language) => {
    await withFeedback(language, async (browser) => {
      const long = {
        ...completed,
        registration: {
          ...completed.registration,
          id: 'registration'.repeat(12),
          model_revision: 'f'.repeat(128),
        },
      };
      await setReport(browser, { model_advice: [long] });
      await browser.click('[data-model-advice] summary');
      expect(await browser.ev('document.documentElement.scrollWidth > innerWidth')).toBe(false);
    });
  },
);

it.each(['zh', 'en'])(
  'MODEL-UI-keyboard: %s opens and closes by Enter with native key text',
  async (language) => {
    await withFeedback(language, async (browser) => {
      await browser.ev(`document.querySelector('[data-model-advice] summary').focus()`);
      expect(await browser.ev(`document.activeElement.tagName`)).toBe('SUMMARY');
      const press = async () => {
        await browser.send('Input.dispatchKeyEvent', {
          type: 'keyDown',
          key: 'Enter',
          code: 'Enter',
          windowsVirtualKeyCode: 13,
          text: '\r',
          unmodifiedText: '\r',
        });
        await browser.send('Input.dispatchKeyEvent', {
          type: 'keyUp',
          key: 'Enter',
          code: 'Enter',
          windowsVirtualKeyCode: 13,
        });
      };
      await press();
      expect(await browser.ev(`document.querySelector('[data-model-advice]').open`)).toBe(true);
      await browser.ev('window.fixture.update()');
      expect(await browser.ev(`document.activeElement.tagName`)).toBe('SUMMARY');
      await press();
      expect(await browser.ev(`document.querySelector('[data-model-advice]').open`)).toBe(false);
    });
  },
);
