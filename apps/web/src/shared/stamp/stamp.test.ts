import { describe, expect, it } from 'vitest';
import { stampHtml } from './stamp';

describe('shared stamp', () => {
  it('draws kicker, words and time, with tone and size marks, escaped', () => {
    const html = stampHtml({ kicker: 'Signed', text: 'Fix F01 <v2>', when: '21:19', tone: 'ink' });
    expect(html).toContain('data-tone="ink"');
    expect(html).toContain('data-size="md"');
    expect(html).toContain('<span class="rc-stamp__text">Fix F01 &lt;v2&gt;</span>');
    expect(html).toContain('<span class="rc-stamp__when">21:19</span>');
  });
  it('leaves the time out when it is not known', () => {
    expect(stampHtml({ kicker: 'Submitted', text: 'Go' })).not.toContain('rc-stamp__when');
  });
});
