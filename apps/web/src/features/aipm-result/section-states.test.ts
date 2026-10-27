import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ObjectRef, SectionReview, SectionReviewPage, StepId } from '../../aipm/types';
import {
  deliveredVersion,
  mountSectionStates,
  readAllReviews,
  resetSectionStatesCache,
  rose,
  rowSentence,
  sectionStates,
  sectionStatesHtml,
} from './section-states';

type Item = SectionReviewPage['items'][number];
const prd = (version: number): ObjectRef => ({ session_id: 's', kind: 'product', object_id: 'prd', version });
let n = 0;
/** FAKE DATA for unit tests only. */
function item(step: StepId, version: number, status: SectionReview['status'], extra: Partial<SectionReview> = {}): Item {
  n += 1;
  const ref: ObjectRef = { session_id: 's', kind: 'aipm_section_review', object_id: `r${n}`, version: 1 };
  return {
    ref,
    review: {
      id: `r${n}`,
      session_id: 's',
      step_id: step,
      prd_ref: prd(version),
      as_of: {} as SectionReview['as_of'],
      created_at: '',
      status,
      ...extra,
    },
  };
}
function stepOf<T extends { step: StepId }>(states: readonly T[], step: StepId): T {
  const found = states.find((s) => s.step === step);
  if (!found) throw new Error(`missing ${step}`);
  return found;
}
/** Newest first, as the server returns them. */
const newestFirst = (...items: Item[]) => [...items].reverse();

describe('section states', () => {
  beforeEach(() => resetSectionStatesCache());

  it('finds the delivered PRD version among the submitted products', () => {
    const products = [{ session_id: 's', kind: 'product', object_id: 'memo', version: 2 }, prd(4)];
    expect(deliveredVersion({ products }, 'prd')).toBe(4);
    expect(deliveredVersion({ products }, 'other')).toBeNull();
    expect(deliveredVersion({ products }, null)).toBeNull();
  });

  it('shows a section reviewed on two versions as before and after', () => {
    const items = newestFirst(item('need', 3, 'draft'), item('need', 3, 'based'), item('need', 4, 'solid'));
    const need = stepOf(sectionStates(items, 4), 'need');
    expect(need.first).toMatchObject({ status: 'draft', version: 3 });
    expect(need.delivered).toMatchObject({ status: 'solid', version: 4 });
    expect(need.open).toBe(items[0].ref);
    expect(rowSentence(need, 'zh')).toBe('验证真需求：第一次批改 草稿（第 3 版），交付版 站得住（第 4 版）');
    expect(rowSentence(need, 'en')).toBe('Validate the need: first review Draft (v3), delivered Holds up (v4)');
  });

  it('shows a section reviewed only on the delivered version without an arrow', () => {
    const items = newestFirst(item('business', 2, 'solid'));
    const business = stepOf(sectionStates(items, 2), 'business');
    expect(business.first).toBeNull();
    expect(rowSentence(business, 'zh')).toBe('看懂业务：站得住（第 2 版）');
    const html = sectionStatesHtml([business], 'zh');
    expect(html).not.toContain('aipm-states__arrow');
    expect(html).toContain('data-status="solid"');
  });

  it('says plainly when a section was never reviewed', () => {
    const states = sectionStates([], 5);
    expect(states).toHaveLength(7);
    expect(states.every((s) => s.open === null)).toBe(true);
    const html = sectionStatesHtml(states, 'en');
    expect(html).toContain('No section was reviewed before delivery.');
    expect(html).not.toContain('aipm-states__list');
    expect(html).not.toContain('data-states-step');
    expect(rowSentence(states[4], 'zh')).toBe('系统方案与市场做法：这一版没有批改过');
  });

  it('lists reviewed sections first and folds the rest into one closing line', () => {
    const states = sectionStates(newestFirst(item('need', 1, 'draft'), item('need', 2, 'draft')), 2);
    const html = sectionStatesHtml(states, 'zh');
    expect(html.match(/data-states-step/g)).toHaveLength(1);
    expect(html).toContain('其余 6 节交付前没有批改：看懂业务、');
    expect(html.indexOf('data-states-step="need"')).toBeLessThan(html.indexOf('aipm-states__rest'));
    expect(html).toContain('<h2 class="aipm-states__title" id="aipm-states-title">交付前的逐节批改</h2>');
    // Draft → Draft did not rise; nothing turns green.
    expect(html).not.toContain('data-rise');
    const en = sectionStatesHtml(sectionStates(newestFirst(item('business', 1, 'solid')), 1), 'en');
    expect(en).toContain('Section reviews before delivery');
    expect(en).toContain('The other 6 sections were not reviewed before delivery: Users and stakeholders');
  });

  it('marks a status that rose, and only that row', () => {
    const items = newestFirst(item('need', 1, 'draft'), item('need', 2, 'based'), item('business', 1, 'based'), item('business', 2, 'draft'));
    const states = sectionStates(items, 2);
    expect(rose(stepOf(states, 'need'))).toBe(true);
    expect(rose(stepOf(states, 'business'))).toBe(false);
    const html = sectionStatesHtml(states, 'en');
    expect(html.match(/data-rise="true"/g)).toHaveLength(2); // the need row and its delivered tag
    expect(html).toMatch(/data-states-step="need" data-rise="true"/);
  });

  it('keeps the first review when the delivered version was not reviewed again', () => {
    const states = sectionStates(newestFirst(item('boundary', 2, 'draft')), 3);
    const boundary = stepOf(states, 'boundary');
    expect(boundary.delivered).toBeNull();
    expect(boundary.open?.object_id).toBeTruthy();
    expect(rowSentence(boundary, 'zh')).toBe('划定 AI 边界：第一次批改 草稿（第 2 版），交付版没有再批改');
  });

  it("does not drop earlier reviews for their 'edited' flag", () => {
    const edited = { stale: { reason: 'edited' as const, detail: 'v3 -> v4' } };
    const items = newestFirst(item('need', 3, 'draft', edited), item('need', 4, 'solid'));
    const need = stepOf(sectionStates(items, 4), 'need');
    expect(need.first).toMatchObject({ status: 'draft', version: 3 });
  });

  it('never shows Holds up while the model part is still running', () => {
    const items = newestFirst(item('need', 4, 'solid', { model_status: 'running' }));
    expect(stepOf(sectionStates(items, 4), 'need').delivered?.status).toBe('based');
  });

  it('ignores reviews of versions after the delivered one', () => {
    const states = sectionStates(newestFirst(item('need', 5, 'solid')), 4);
    expect(stepOf(states, 'need').open).toBeNull();
  });

  it('reads every page', async () => {
    const all = Array.from({ length: 45 }, (_, i) => item('need', 1, i % 2 ? 'draft' : 'based'));
    const sectionReviews = vi.fn((_step?: StepId, cursor = 0, limit = 10) =>
      Promise.resolve({
        items: all.slice(cursor, cursor + limit),
        next_cursor: cursor + limit < all.length ? cursor + limit : null,
      }),
    );
    const items = await readAllReviews({ sectionReviews } as never);
    expect(items).toHaveLength(45);
    expect(sectionReviews).toHaveBeenCalledTimes(3);
    expect(sectionReviews.mock.calls.map((c) => c[1])).toEqual([0, 20, 40]);
  });
});

describe('mounting', () => {
  beforeEach(() => resetSectionStatesCache());
  type Listener = (event: { target: unknown }) => void;
  function fakeEl() {
    const listeners: Listener[] = [];
    const classes = new Set<string>();
    return {
      innerHTML: '',
      hidden: false,
      dataset: {} as DOMStringMap,
      attrs: {} as Record<string, string>,
      classList: { add: (c: string) => classes.add(c) },
      classes,
      setAttribute(name: string, value: string) {
        this.attrs[name] = value;
      },
      addEventListener: (_: string, fn: Listener) => listeners.push(fn),
      click: (step: string) => {
        for (const fn of listeners) fn({ target: { closest: () => ({ dataset: { statesStep: step } }) } });
      },
      listeners,
    };
  }
  const page = (items: Item[]) => ({ sectionReviews: vi.fn(() => Promise.resolve({ items, next_cursor: null })) });

  it('fills the section and opens the clicked review', async () => {
    const items = newestFirst(item('need', 3, 'draft'), item('need', 4, 'solid'));
    const el = fakeEl();
    const openReview = vi.fn();
    const client = page(items);
    const submission = { id: 'sub', version: 1, products: [prd(4)] };
    await mountSectionStates(el as never, { client, submission, prdId: 'prd', language: 'zh', openReview });
    expect(el.hidden).toBe(false);
    expect(el.classes.has('aipm-states')).toBe(true);
    expect(el.innerHTML).toContain('交付前的逐节批改');
    expect(el.innerHTML).toContain('不改变正式评分');
    el.click('need');
    expect(openReview).toHaveBeenCalledWith('need', items[0].ref);
    // A re-render mounts again from what was read, without reading again or binding twice.
    await mountSectionStates(el as never, { client, submission, prdId: 'prd', language: 'zh', openReview });
    expect(client.sectionReviews).toHaveBeenCalledTimes(1);
    expect(el.listeners).toHaveLength(1);
    expect(el.dataset.arriving).toBe('false');
  });

  it('stays hidden when the read fails or the PRD was not delivered', async () => {
    const el = fakeEl();
    const failing = { sectionReviews: vi.fn(() => Promise.reject(new Error('down'))) };
    const options = { submission: { products: [prd(4)] }, prdId: 'prd', language: 'en' as const, openReview: vi.fn() };
    await mountSectionStates(el as never, { ...options, client: failing });
    expect(el.hidden).toBe(true);
    expect(el.innerHTML).toBe('');
    await mountSectionStates(el as never, { ...options, client: page([]), prdId: 'missing' });
    expect(el.hidden).toBe(true);
  });
});
