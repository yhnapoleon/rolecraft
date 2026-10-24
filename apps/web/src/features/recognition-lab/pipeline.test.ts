import { describe, expect, it } from 'vitest';
import { chainFor, type Chain } from './data';
import { moveChoice, pipelineHtml, STAGES, stageDetail, stationMarks } from './pipeline';

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
    const plain = (html: string) => html.replace(/\u00a0/g, ' ');
    expect(plain(stageDetail('repr', chain, 'zh'))).toContain('>混合<');
    expect(plain(stageDetail('recog', chain, 'zh'))).toContain('监督 · 深度学习');
    expect(plain(stageDetail('decide', chain, 'zh'))).toContain('统计决策 · 混合');
    const fallback = stageDetail('recog', { ...chain, fallback: true }, 'zh');
    expect(fallback).not.toContain('深度学习');
    expect(fallback).toContain('规则回退');
  });
});

/** The course-family pills in a piece of HTML, in order. */
const pills = (html: string) =>
  [...html.matchAll(/<span class="rc-family"[^>]*>([^<]*)<\/span>/g)].map(([, x]) => x.replace(/\u00a0/g, ' '));
/** The course-family notes (plain text, one per line) on a station, in order. */
const notes = (html: string) =>
  [...html.matchAll(/<span class="rc-st-fam"[^>]*>([^<]*)<\/span>/g)].map(([, x]) => x.replace(/\u00a0/g, ' '));
/** The station of stage i as drawn on the track. */
const station = (html: string, i: number) =>
  html.match(new RegExp(`<li class="rc-station"[^>]*><button[^>]*data-rc-stage="${i}"[\\s\\S]*?</li>`))?.[0] ?? '';

describe('the six stations on the system profile', () => {
  it('puts the halo on the chosen station, wherever the walk has got to', () => {
    // Walk finished, the reviewer picks Represent: one halo, on Represent.
    const done = stationMarks(5, 2, 6);
    expect(done.filter((m) => m.halo).map((m) => m.index)).toEqual([2]);
    expect(done.map((m) => m.state)).toEqual(['reached', 'reached', 'reached', 'reached', 'reached', 'current']);
    // While the claim travels, the halo is the head of the walk.
    const walking = stationMarks(3, 3, 6);
    expect(walking.filter((m) => m.halo).map((m) => m.index)).toEqual([3]);
    expect(walking.map((m) => m.state)).toEqual(['reached', 'reached', 'reached', 'current', 'ahead', 'ahead']);
  });

  it('shows each station’s course families under its name, from the same data as its detail', () => {
    const chain = chainFor(practice, 'zh', 1, { submitted: 2 });
    const html = pipelineHtml(chain, 'zh');
    STAGES.forEach((stage, i) => {
      expect(notes(station(html, i)), stage).toEqual(pills(stageDetail(stage, chain, 'zh')));
    });
    expect(notes(station(html, 2))).toEqual(['混合']);
    expect(notes(station(html, 3))).toEqual(['监督 · 深度学习', '集成 · 混合']);
    // Reading in and splitting are not the course's “sensing”: no pill, no empty row.
    expect(station(html, 0)).not.toContain('rc-st-fams');
    expect(station(html, 1)).not.toContain('rc-st-fams');
    // The name comes before the pills, the pills before the result.
    const represent = station(html, 2);
    expect(represent.indexOf('rc-st-name')).toBeLessThan(represent.indexOf('rc-st-fams'));
    expect(represent.indexOf('rc-st-fams')).toBeLessThan(represent.indexOf('rc-st-note'));
    const fallback = pipelineHtml({ ...chain, fallback: true }, 'zh');
    expect(notes(station(fallback, 3))).toEqual(['规则回退']);
  });

  it('writes the station families as plain notes and keeps pills in the stage detail', () => {
    const chain = chainFor(practice, 'en', 1, { submitted: 2 });
    const html = pipelineHtml(chain, 'en');
    const track = html.slice(html.indexOf('rc-track'), html.indexOf('data-rc-panel'));
    // On the track: no capsules, one note per family (a long one wraps by words).
    expect(track).not.toContain('class="rc-family"');
    expect(notes(station(html, 3))).toEqual(['Supervised · deep learning', 'Ensemble · hybrid']);
    // In the detail below: the same families, still as pills.
    expect(pills(stageDetail('recog', chain, 'en'))).toEqual(['Supervised · deep learning', 'Ensemble · hybrid']);
    expect(stageDetail('recog', chain, 'en')).not.toContain('rc-st-fam');
  });

  it('says the decision and the reviewer summary in plain English, with the right plural', () => {
    const one = chainFor(practice, 'en', 1, { submitted: 2 });
    const html = pipelineHtml(one, 'en');
    expect(html).toContain('Decided directly');
    expect(html).not.toContain('Decides itself');
    const summary = stageDetail('gen', one, 'en');
    expect(summary).toContain('sentence 2 · matches the materials · 1 piece of evidence · decided directly');
    expect(summary).not.toMatch(/evidence units|· supported ·/);
    const two = { ...one, evidence: 2 };
    expect(stageDetail('gen', two, 'en')).toContain('2 pieces of evidence');
    const none = { ...one, evidence: 0, decision: 'defer' as const };
    expect(stageDetail('gen', none, 'en')).toContain('0 pieces of evidence · sent to a person');
    // Chinese stays as it was.
    expect(stageDetail('gen', chainFor(practice, 'zh', 1, { submitted: 2 }), 'zh')).toContain(
      '第 2 句 · 与材料一致 · 证据 1 条 · 直接判定',
    );
  });

  it('cuts an English quote on a word boundary', () => {
    // The example's top hit is “Expense-management notice: the hotel reimbursement cap …”.
    const note = pipelineHtml(chainFor(null, 'en'), 'en').match(/Retrieved: ([^<]*)/)?.[1];
    expect(note).toBe('Expense-management notice: the…');
    // Chinese has no spaces: cut by characters as before.
    const zh = pipelineHtml(chainFor(null, 'zh'), 'zh').match(/检索到：([^<]*)/)?.[1];
    expect(zh).toBe('费用管理通知：国内出差住宿报销上限改…');
  });
});

