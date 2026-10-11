import { describe, expect, it } from 'vitest';
import { renderShortResult } from './short-result';
import { asFake, fakeDocument, type FakeElement } from './fake-dom';
import { copyText, type CopyTable } from './localization';

describe('063-03 short result frame', () => {
  it('UI-01 shows one primary result and keeps detail behind one disclosure', () => {
    const doc = fakeDocument();
    const detail = doc.createElement('p');
    detail.textContent = 'Full original text';
    const view = renderShortResult(doc, {
      kind: 'reply',
      id: 'turn-1',
      statuses: [{ text: 'Sources checked by rules', tone: 'waiting' }],
      lead: 'Capacity is 30 people.',
      notes: ['Only the shared version is available.'],
      more: { label: 'Show full reply', meta: '3 sources', body: [detail] },
    });
    const root = asFake(view.element);
    expect(root.dataset.shortResult).toBe('reply');
    expect(root.dataset.shortResultId).toBe('turn-1');
    expect(root.byClass('short-result__lead').map((n) => n.textContent)).toEqual([
      'Capacity is 30 people.',
    ]);
    expect(root.byTag('details')).toHaveLength(1);
    expect(asFake(view.summary).textContent).toBe('Show full reply3 sources');
    expect(asFake(view.details).open).toBe(false);
    expect(asFake(view.details).children.at(-1)).toBe(detail);
  });

  it('UI-02 writes every status and limitation as text, never colour alone', () => {
    const doc = fakeDocument();
    const view = renderShortResult(doc, {
      kind: 'feedback',
      statusLabel: 'Result status',
      statuses: [
        { text: 'Verified by rules: 2', tone: 'verified' },
        { text: 'Awaiting model connection', tone: 'waiting' },
        { text: '', tone: 'failed' },
      ],
      notes: ['Permission limited'],
    });
    const root = asFake(view.element);
    const items = root.byTag('li');
    expect(items.map((n) => n.textContent)).toEqual([
      'Verified by rules: 2',
      'Awaiting model connection',
    ]);
    expect(items.map((n) => n.dataset.tone)).toEqual(['verified', 'waiting']);
    expect(root.byTag('ul')[0].getAttribute('aria-label')).toBe('Result status');
    expect(root.byClass('short-result__note')[0].textContent).toBe('Permission limited');
  });

  it('UI-04 treats markup-like text as text and adds no actions of its own', () => {
    const doc = fakeDocument();
    const view = renderShortResult(doc, {
      kind: 'result',
      lead: '<img src=x onerror=alert(1)>',
      derivedLead: true,
    });
    const lead = asFake(view.lead);
    expect(lead.textContent).toBe('<img src=x onerror=alert(1)>');
    expect(lead.children).toHaveLength(0);
    expect(lead.dataset.derived).toBe('');
    expect(asFake(view.element).byTag('button')).toHaveLength(0);
    expect(view.details).toBeUndefined();
  });

  it('UI-05 restores a host-kept open state and reports toggles without side effects', () => {
    const doc = fakeDocument();
    const toggled: boolean[] = [];
    const view = renderShortResult(doc, {
      kind: 'review',
      id: 'feedback:1',
      more: { label: 'Show all 14 items', body: [], open: true, onToggle: (o) => toggled.push(o) },
    });
    const details = asFake(view.details);
    expect(details.open).toBe(true);
    expect(details.dataset.shortResultMore).toBe('feedback:1');
    details.open = false;
    details.dispatch('toggle');
    expect(toggled).toEqual([false]);
  });

  it('keeps supported components visible in order between notes and the disclosure', () => {
    const doc = fakeDocument();
    const prompt = doc.createElement('fieldset');
    const view = renderShortResult(doc, {
      kind: 'review',
      lead: 'Purpose not specified',
      actions: [prompt],
      more: { label: 'Show all 14 items', body: [] },
    });
    const order = asFake(view.element).children.map((n) => (n as FakeElement).tagName);
    expect(order).toEqual(['p', 'fieldset', 'details']);
  });
});

describe('paired copy tables', () => {
  const table: CopyTable<'items'> = {
    zh: { items: '展开 {n} 项' },
    en: { items: 'Show all {n} items' },
  };
  it.each([
    ['zh', '展开 14 项'],
    ['en', 'Show all 14 items'],
  ] as const)('fills placeholders as text (%s)', (language, expected) => {
    expect(copyText(table, language, 'items', { n: 14 })).toBe(expected);
  });
});
