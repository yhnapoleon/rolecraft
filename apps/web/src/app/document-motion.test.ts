import { describe, expect, it } from 'vitest';
import { DOCUMENT_DURATION, documentEase, mixBox } from './document-motion.js';

describe('shared document geometry', () => {
  it('uses the reference timing, exact endpoints and monotonic iOS easing', () => {
    expect(DOCUMENT_DURATION).toBe(500);
    expect(documentEase(0)).toBe(0);
    expect(documentEase(1)).toBe(1);
    const samples = Array.from({ length: 101 }, (_, i) => documentEase(i / 100));
    expect(samples.every((v, i) => i === 0 || v >= samples[i - 1])).toBe(true);
    // Independent cubic-Bezier solution at x=.5: u=.6682339592265568.
    expect(documentEase(0.5)).toBeCloseTo(0.7737196918, 5);
  });
  it('retargets a partially expanded surface without snapping either endpoint', () => {
    const card = { x: 20, y: 650, width: 210, height: 112 },
      paper = { x: 42, y: 76, width: 810, height: 700 };
    const interrupted = mixBox(card, paper, documentEase(0.3));
    expect(mixBox(interrupted, card, 0)).toEqual(interrupted);
    expect(mixBox(interrupted, card, 1)).toEqual(card);
    expect(mixBox(interrupted, paper, 0)).toEqual(interrupted);
    expect(mixBox(interrupted, paper, 1)).toEqual(paper);
  });
});
