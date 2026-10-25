import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { AgentEvent } from './feed';
import { TransmissionStream } from './stream';
const event = (id: string, tool: string, title: string): AgentEvent => ({
  id,
  tool,
  at: '2026-10-25T12:00:00Z',
  direction: tool === 'work_products.create' ? 'to_workspace' : 'to_agent',
  verb: ['交回', 'Handed back'],
  status: 'ok',
  object: { kind: 'work_product', id, title },
});
describe('My agent hand-back focus', () => {
  it('puts the most recent returned paper ahead of later reads without losing history', () => {
    const html = renderToStaticMarkup(
      <TransmissionStream
        lang="en"
        spotlight
        events={[
          event('1', 'work_products.create', 'Earlier draft'),
          event('2', 'work_products.create', 'Latest draft'),
          event('3', 'materials.list', 'Recent read'),
        ]}
        onOpen={() => {}}
        onAdopt={() => {}}
      />,
    );
    expect(html.indexOf('Latest draft')).toBeLessThan(html.indexOf('Recent read'));
    expect(html).toContain('Earlier draft');
    expect(html).toContain('Review &amp; adopt');
    expect(html).toContain('Activity');
    expect(html.match(/Latest draft/g)).toHaveLength(1);
  });
  it('retains compact engineer ordering and the same actions', () => {
    const html = renderToStaticMarkup(
      <TransmissionStream
        lang="en"
        variant="compact"
        spotlight
        events={[event('1', 'work_products.create', 'Draft'), event('2', 'materials.list', 'Read')]}
        onOpen={() => {}}
      />,
    );
    expect(html).not.toContain('Latest hand-back');
    expect(html.indexOf('Read')).toBeLessThan(html.indexOf('Draft'));
    expect(html).toContain('is-row-link');
  });
});
