import { describe, expect, it } from 'vitest';
import zh from '../../../../../scenarios/pm_pilot/aipm-phase1/public/guide.zh.json';
import en from '../../../../../scenarios/pm_pilot/aipm-phase1/public/guide.en.json';
import { guideView, matchingSnapshot, progressView } from './model';
import { createAipmRegistry } from '../../aipm/registry';

// Explicit fake progress: content comes from the real guide; no production fallback uses this.
const fixture = (g = zh) => ({
  ...g,
  session_id: 'fixture',
  as_of: { business_seq: 0, workspace_revision: 3, storage_revision: 3 },
  focus_step: 'assurance',
  suggested_step: 'need',
  projection: { complete: true },
  steps: g.steps.map((s) => ({
    ...s,
    work_status: s.id === 'business' ? 'recorded' : 'not_started',
    completed: s.id === 'business',
    quality_status: 'unverified',
    missing: [],
    open_feedback: [],
  })),
});
describe('AIPM presentation preserves authoritative meaning', () => {
  it.each([
    ['zh', zh],
    ['en', en],
  ] as const)('loads %s content without translating labels', (_, input) => {
    const g = guideView(input);
    expect(g.steps).toHaveLength(7);
    expect(g.steps[0].questions).toHaveLength(2);
    expect(g.steps[6].id).toBe('decision');
    expect(g.steps[0].label).toBe(input.steps[0].label);
  });
  it('keeps chosen focus separate from suggestion and work from quality', () => {
    const p = progressView(fixture());
    expect(p.focus).toBe('assurance');
    expect(p.suggested).toBe('need');
    expect(p.steps[0].status).toBe('recorded');
    expect(p.steps[0].quality).toBe('unverified');
  });
  it('rejects mixed-session, language and content snapshots', () => {
    const g = guideView(zh),
      p = progressView(fixture());
    expect(matchingSnapshot(g, p, 'fixture', 'zh')).toBe(true);
    expect(matchingSnapshot(g, p, 'other', 'zh')).toBe(false);
    expect(matchingSnapshot(g, p, 'fixture', 'en')).toBe(false);
    expect(matchingSnapshot(g, { ...p, revision: 'other' }, 'fixture', 'zh')).toBe(false);
  });
  it('rejects a second order and unsupported experience', () => {
    const p = fixture();
    expect(() => progressView({ ...p, experience_revision: 'old' })).toThrow();
    expect(() => progressView({ ...p, steps: [...p.steps].reverse() })).toThrow();
  });
  it('never invents completion for unavailable records', () => {
    const p = fixture();
    expect(() => progressView({ ...p, steps: p.steps.slice(0, 6) })).toThrow();
    expect(() =>
      progressView({
        ...p,
        steps: p.steps.map((s) => ({ ...s, completed: true })),
      }),
    ).toThrow();
  });
  it('marks limited projection incomplete', () =>
    expect(progressView({ ...fixture(), projection: { complete: false } }).complete).toBe(false));
  it('registry is empty until installed and refuses duplicate owners', () => {
    const r = createAipmRegistry();
    expect(r.get('design')).toBeUndefined();
    const remove = r.register('design', {
      render: () => '<p>real feature</p>',
    });
    expect(() => r.register('design', { render: () => '' })).toThrow();
    remove();
    expect(r.get('design')).toBeUndefined();
  });
});
