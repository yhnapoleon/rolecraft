import { describe, expect, it } from 'vitest';
import { chainFor, type Chain } from './data';
import { moveChoice, pipelineHtml, stageDetail } from './pipeline';

const unit = (index: number, label: string, decision = 'decide') => ({
  index,
  quote: `第 ${index + 1} 句：上限 ${400 + index} 元，超出须事前批准。`,
  label,
  probabilities: { supported: 0.6, contradicted: 0.1, insufficient: 0.3 },
  evidence_ids: label === 'supported' ? ['e-1'] : [],
  reason: 'pair_aggregate',
  decision,
  expected_cost: 0.4,
});
const relation = (object_id: string, units: ReturnType<typeof unit>[]) => ({
  carrier: { kind: 'feedback', object_id, version: 1 },
  position: 0,
  record: { recognizer_id: 'xlm-r-pair-v1', revision: 'abc', task: 'relation', outputs: { candidates: 13, units } },
});
const practice = {
  session_id: 's1',
  counts: {},
  recognizers: [],
  records: [
    relation('fb-1', [unit(0, 'insufficient'), unit(1, 'supported')]),
    relation('fb-2', [unit(0, 'insufficient'), unit(1, 'supported'), unit(2, 'contradicted'), unit(3, 'insufficient', 'defer')]),
  ],
};

/** The sentence choices as the page draws them. */
function radios(html: string, group: string) {
  const box = html.match(new RegExp(`<div[^>]*data-rc-group="${group}"[^>]*>([\\s\\S]*?)</div>`));
  if (!box) return null;
  return [...box[1].matchAll(/<button[^>]*role="radio"[^>]*>/g)].map(([tag]) => ({
    checked: /aria-checked="true"/.test(tag),
    tabindex: tag.match(/tabindex="(-?\d+)"/)?.[1],
    label: tag.match(/aria-label="([^"]*)"/)?.[1] ?? '',
    tone: tag.match(/data-tone="(\w+)"/)?.[1],
  }));
}

describe('choosing a sentence on the system profile', () => {
  it('moves through a radio group with the arrow keys, Home and End, wrapping at the ends', () => {
    expect(moveChoice('ArrowRight', 0, 4)).toBe(1);
    expect(moveChoice('ArrowDown', 3, 4)).toBe(0);
    expect(moveChoice('ArrowLeft', 0, 4)).toBe(3);
    expect(moveChoice('ArrowUp', 2, 4)).toBe(1);
    expect(moveChoice('Home', 2, 4)).toBe(0);
    expect(moveChoice('End', 0, 4)).toBe(3);
    expect(moveChoice('Enter', 1, 4)).toBeNull();
    expect(moveChoice('a', 1, 4)).toBeNull();
  });

  it('draws every sentence as a radio, the chosen one checked and the only one in the tab order', () => {
    const chain = chainFor(practice, 'zh', 1, { submitted: 2 });
    const html = pipelineHtml(chain, 'zh');
    expect(html).not.toContain('<select');
    expect(html).toMatch(/role="radiogroup"[^>]*aria-labelledby="rc-lab-units-label"/);
    const units = radios(html, 'units');
    expect(units).toHaveLength(4);
    expect(units?.map((u) => u.checked)).toEqual([false, true, false, false]);
    expect(units?.map((u) => u.tabindex)).toEqual(['-1', '0', '-1', '-1']);
    // Marks and words are the lens's, so the page reads like the delivery dialog.
    expect(units?.map((u) => u.tone)).toEqual(['insufficient', 'supported', 'contradicted', 'deferred']);
    expect(units?.[1].label).toBe('第 2 句 · 与材料一致：第 2 句：上限 401 元，超出须事前批准。');
    expect(units?.[3].label).toContain('还不知道 · 送人工');
  });

  it('counts the sentences the way the lens and the delivery dialog do', () => {
    const html = pipelineHtml(chainFor(practice, 'zh', undefined, { submitted: 2 }), 'zh');
    const key = html.match(/<p class="rc-lab-units-key"[^>]*>([\s\S]*?)<\/p>/)?.[1] ?? '';
    const items = [...key.matchAll(/<span class="rc-lab-key">([\s\S]*?)<\/span>/g)].map(([, x]) =>
      x.replace(/<[^>]+>/g, '').replace(/\u00a0/g, ' '),
    );
    expect(items).toEqual(['与材料一致 1', '与材料矛盾 1', '还不知道 1', '还不知道 · 送人工 1']);
  });

  it('names the delivery and its count, and offers the other deliveries when they are numbered', () => {
    const latest = pipelineHtml(chainFor(practice, 'zh', undefined, { submitted: 2 }), 'zh');
    expect(latest).toContain('第 2 次交付 · 第 3 / 4 句');
    const deliveries = radios(latest, 'deliveries');
    expect(deliveries?.map((d) => [d.label, d.checked])).toEqual([
      ['第 1 次交付 · 2 句', false],
      ['第 2 次交付 · 4 句', true],
    ]);
    const first = pipelineHtml(chainFor(practice, 'en', undefined, { submitted: 2, delivery: 0 }), 'en');
    expect(first).toContain('Delivery 1 · Sentence 2 of 2');
  });

  it('says only “latest delivery” and offers no switch when the deliveries cannot be numbered', () => {
    const html = pipelineHtml(chainFor(practice, 'zh'), 'zh');
    expect(html).toContain('最近一次交付 · 第 3 / 4 句');
    expect(radios(html, 'deliveries')).toBeNull();
  });

  it('marks the example and names the recorded delivery it comes from, with no choices', () => {
    const chain: Chain = chainFor(null, 'zh');
    const html = pipelineHtml(chain, 'zh');
    expect(html).toContain('示例');
    expect(html).toContain('第 2 次交付 · 第 5 / 10 句');
    expect(radios(html, 'units')).toBeNull();
  });

  it('labels the recognition stages with their course family, and the rule fallback honestly', () => {
    const chain = chainFor(practice, 'zh', 1, { submitted: 2 });
    expect(stageDetail('repr', chain, 'zh')).toContain('>混合<');
    expect(stageDetail('recog', chain, 'zh')).toContain('监督 · 深度学习');
    expect(stageDetail('decide', chain, 'zh')).toContain('统计决策 · 混合');
    const fallback = stageDetail('recog', { ...chain, fallback: true }, 'zh');
    expect(fallback).not.toContain('深度学习');
    expect(fallback).toContain('规则回退');
  });
});
