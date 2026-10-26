import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import {
  type StackItem,
  fanOffset,
  initialFocus,
  pendingCount,
  stackLayout,
  topItem,
} from './model';
import { WorkStack } from './stack';

const item = (id: string, over: Partial<StackItem> = {}): StackItem => ({
  id,
  order: 1,
  segment: 'clarify',
  icon: 'Search',
  name: id,
  purpose: 'p',
  status: 'not_started',
  statusText: 'Not started',
  agentDraft: false,
  suggested: false,
  ...over,
});

describe('work stack model', () => {
  it('fans up to nine, grids from ten or in a short window, sheets on a phone', () => {
    expect(stackLayout(7, 900, 1440)).toBe('fan');
    expect(stackLayout(10, 900, 1440)).toBe('grid');
    expect(stackLayout(7, 740, 1440)).toBe('grid');
    expect(stackLayout(7, 900, 390)).toBe('sheet');
  });
  it('puts a sheet to recheck on top, then the suggested one', () => {
    const items = [item('a'), item('b', { suggested: true }), item('c', { status: 'recheck' })];
    expect(topItem(items)?.id).toBe('c');
    expect(topItem(items.slice(0, 2))?.id).toBe('b');
    expect(initialFocus(items)).toBe(1);
  });
  it('counts rechecks and agent drafts in the badge', () => {
    expect(pendingCount([item('a', { status: 'recheck', agentDraft: true }), item('b')])).toBe(2);
  });
  it('drifts the fan right and turns it at most 3 degrees', () => {
    expect(fanOffset(0)).toEqual({ x: 0, rotate: 0 });
    expect(fanOffset(9).rotate).toBe(3);
  });
});

describe('work stack pile', () => {
  it('renders closed as one labelled button with the badge and caption', () => {
    const html = renderToStaticMarkup(
      <WorkStack
        title="My sheets"
        status="1 to recheck"
        ariaLabel="My sheets, 2 sheets, 1 to recheck"
        capsule="Sheets 0/2"
        words={{ suggested: 'Suggested', close: 'Close' }}
        items={[item('a', { status: 'recheck' }), item('b')]}
        onOpen={() => {}}
      />,
    );
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('aria-label="My sheets, 2 sheets, 1 to recheck"');
    expect(html).toContain('ws-stack__badge');
    expect(html).toContain('My sheets');
    expect(html).not.toContain('ws-stack__panel');
  });
});
