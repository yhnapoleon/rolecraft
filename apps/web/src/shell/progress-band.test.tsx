import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';
import { ProgressBand, type ProgressBandProps } from './progress-band';
vi.stubGlobal('window', { matchMedia: () => ({ matches: false }) });
const words = {
  label: 'Progress',
  now: 'Current question',
  missing: 'Missing',
  nothingMissing: 'Ready',
  confirmed: 'Confirmed',
  next: 'Next',
  after: 'After that',
  basis: 'Records',
  basisHint: 'Records only',
  map: 'Map',
  fold: 'Hide',
  unfold: 'Show',
  viewing: 'Viewing',
  backToNow: 'Back',
  distilled: 'Summary',
  kept: 'Open',
  gotIt: 'OK',
  close: 'Close',
  mapTitle: 'Map',
  mapLead: 'Map',
  states: {
    done: 'done',
    current: 'current',
    reopened: 'reopened',
    todo: 'ahead',
    uncovered: 'uncovered',
  },
  stepOf: (n: number) => String(n),
  ending: { title: 'Next', items: ['Revise'] },
};
it.each([true, false])(
  'keeps current, goal, findings, gaps and both next layers while viewing 05 (folded=%s)',
  (folded) => {
    const p: ProgressBandProps = {
      layers: Array.from({ length: 6 }, (_, i) => ({
        id: String(i + 1),
        n: i + 1,
        label: `Layer ${i + 1}`,
        goal: `Goal ${i + 1}`,
        state: i === 1 ? 'current' : 'todo',
        confirmed: [`Fact ${i + 1}`],
        missing: [`Gap ${i + 1}`],
      })),
      current: '2',
      routeViewing: '5',
      carried: ['Policy changed'],
      folded,
      foldedByDefault: true,
      words,
      onFold: () => {},
      onArrivedSeen: () => {},
    };
    const html = renderToStaticMarkup(<ProgressBand {...p} />);
    const blocks =
      html.match(/class="rc-prog__summary"[\s\S]*?(?=<\/section>|class="rc-prog__tools")/g) ?? [];
    expect(blocks.length).toBeGreaterThan(0);
    for (const block of blocks) {
      for (const word of [
        'Layer 2',
        'Goal 2',
        'Fact 2',
        'Gap 2',
        'Layer 3',
        'Layer 4',
        'Viewing',
        'Layer 5',
        'Policy changed',
      ])
        expect(block).toContain(word);
    }
    expect(html).toContain('Map');
    expect(html).toContain('Summary');
  },
);
