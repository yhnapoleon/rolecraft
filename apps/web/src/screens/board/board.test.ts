import { describe, expect, it } from 'vitest';
import { briefKeyLine } from './brief';
import { orderDocs } from './documents';
import { markChangedFigures } from './material-overlay';

describe('briefKeyLine', () => {
  it('keeps the sentence that hands the call over, cut to its first clause', () => {
    expect(
      briefKeyLine(
        'I want our first colleagues using the knowledge assistant next week. Who it serves first, what it covers and what safeguards it needs is your call. Tell me when we should pause, too.',
      ),
    ).toBe('Who it serves first is your call.');
    expect(
      briefKeyLine(
        '我希望第一批同事下周就能用上知识助手。先服务谁、开放什么、要什么保障，你来定方案，也告诉我什么情况下该暂停。',
      ),
    ).toBe('先服务谁、开放什么、要什么保障，你来定方案。');
  });
  it('falls back to the first sentence', () => {
    expect(briefKeyLine('Plain words. More words.')).toBe('Plain words.');
  });
});

describe('markChangedFigures', () => {
  it('strikes the old figure beside the new one, once', () => {
    const html = '<p>The cap is now CNY 400 per night. Taxi stays CNY 200.</p>';
    expect(
      markChangedFigures(
        html,
        'Claims are capped at CNY 500. Taxi CNY 200.',
        'now CNY 400. Taxi CNY 200.',
      ),
    ).toBe(
      '<p>The cap is now CNY <del>500</del> <ins>400</ins> per night. Taxi stays CNY 200.</p>',
    );
  });
  it('leaves a rewrite without changed figures as it is', () => {
    expect(markChangedFigures('<p>Same 200.</p>', 'Old 200.', 'New 200.')).toBe('<p>Same 200.</p>');
  });
});

describe('orderDocs', () => {
  it('puts new versions first and keeps the rest in server order', () => {
    const rows = [
      { id: 'a', title: 'A', version: 1, state: 'read' as const },
      { id: 'b', title: 'B', version: 1, state: 'agent' as const },
      { id: 'c', title: 'C', version: 2, state: 'new' as const },
      { id: 'd', title: 'D', version: 1, state: 'unread' as const },
    ];
    expect(orderDocs(rows).map((r) => r.id)).toEqual(['c', 'a', 'b', 'd']);
  });
});
