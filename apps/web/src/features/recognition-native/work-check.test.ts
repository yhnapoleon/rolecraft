import { describe, expect, it } from 'vitest';
import { createWorkChecks, workCheckHtml } from './work-check';
import { businessSentenceState, businessSentencesHtml } from './business-sentences';
import type { PreviewRecognition } from './chain';
const preview: PreviewRecognition = { recognizer: 'relation-stack-v1@r', fallback: false, units: [{ index: 0, quote: 'A saved claim.', label: 'contradicted', confidence: .8, decision: 'decide', evidence: 'The original source, even when it is the wrong match.', source: { title: 'Policy', version: 1 } }] };
describe('saved-version evidence checks', () => {
  it('keeps evidence insufficiency distinct from cost deferral', () => {
    expect(businessSentenceState({ label: 'insufficient', decision: 'decide' })).toBe('insufficient');
    expect(businessSentenceState({ label: 'supported', decision: 'defer' })).toBe('deferred');
    expect(businessSentenceState({ label: 'unsupported-label', decision: 'decide' })).toBe('unknown');
  });
  it('renders exact server evidence and version without correcting the recognizer', () => {
    const html = businessSentencesHtml(preview, 'en');
    expect(html).toContain('wrong match');
    expect(html).toContain('Policy · v1');
    expect(html).toContain('Contradicted');
    expect(html).not.toContain('Deferred judgement</span>');
    expect(html).not.toMatch(/[\u4e00-\u9fff]/);
  });
  it('only describes cost deferral when the server defers', () => {
    const unit = preview.units?.[0];
    if (!unit) throw Error('fixture');
    const html = businessSentencesHtml({ ...preview, units: [{ ...unit, decision: 'defer' }] }, 'zh');
    expect(html).toContain('自动判定的预期代价较高');
    expect(html).toContain('暂缓判定');
    expect(html).not.toContain('>矛盾</span>');
  });
  it('invalidates an in-flight response immediately when the text changes', async () => {
    const c = createWorkChecks();
    let resolve: (value: { enabled: boolean; recognition: PreviewRecognition }) => void = () => {};
    const pending = c.run('work', 'v1', () => new Promise(r => { resolve = r; }), () => true);
    c.invalidate('work');
    resolve({ enabled: true, recognition: preview });
    await pending;
    expect(c.get('work')?.kind).toBe('stale');
  });
  it('discards an older run when a newer check already exists', async () => {
    const c = createWorkChecks();
    let resolve: (value: { enabled: boolean; recognition: PreviewRecognition }) => void = () => {};
    const first = c.run('work', 'v1', () => new Promise(r => { resolve = r; }), () => true);
    await c.run('work', 'v2', async () => ({ enabled: false, recognition: null }), () => true);
    resolve({ enabled: true, recognition: preview }); await first;
    expect(c.get('work')).toEqual({ basis: 'v2', kind: 'disabled' });
  });
  it('keeps disabled, empty and failed responses separate', async () => {
    const c = createWorkChecks();
    await c.run('off', 'v1', async () => ({ enabled: false, recognition: null }), () => true);
    await c.run('empty', 'v1', async () => ({ enabled: true, recognition: null }), () => true);
    await c.run('fail', 'v1', async () => { throw Error('timeout'); }, () => true);
    expect(c.get('off')?.kind).toBe('disabled');
    expect(c.get('empty')?.kind).toBe('empty');
    expect(c.get('fail')?.kind).toBe('failed');
    expect(workCheckHtml(c.get('off'), 'en', 'v1')).toContain('not enabled');
    expect(workCheckHtml(c.get('fail'), 'en', 'v1')).toContain('check failed');
  });
  it('shows an out-of-date notice instead of a current judgement after context changes', async () => {
    const c = createWorkChecks();
    await c.run('work', 'v1', async () => ({ enabled: true, recognition: preview }), () => true);
    expect(workCheckHtml(c.get('work'), 'en', 'v2')).toContain('out of date');
    expect(workCheckHtml(c.get('work'), 'en', 'v1', true)).not.toContain('data-sentence-state');
  });
  it('escapes both the work and source text', () => {
    const unit = preview.units?.[0]; if (!unit) throw Error('fixture');
    const html = businessSentencesHtml({ ...preview, units: [{ ...unit, quote: '<img onerror=attack>', evidence: '<script>attack</script>' }] }, 'en');
    expect(html).toContain('&lt;img'); expect(html).not.toContain('<img'); expect(html).not.toContain('<script>');
  });
});
