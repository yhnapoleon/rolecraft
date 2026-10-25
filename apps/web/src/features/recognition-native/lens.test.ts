import { describe, expect, it, vi } from 'vitest';
import { createLensState } from './lens';

const memory = (initial: Record<string, string> = {}) => {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
  };
};

describe('recognition lens state', () => {
  it('is off by default', () => {
    expect(createLensState({ search: '', storage: memory() }).on()).toBe(false);
  });

  it('follows the viewer’s saved preference', () => {
    expect(createLensState({ search: '', storage: memory({ 'rolecraft.lens': '1' }) }).on()).toBe(true);
  });

  it('treats an unreadable store as off', () => {
    const storage = {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
    };
    const lens = createLensState({ search: '', storage });
    expect(lens.on()).toBe(false);
    lens.set(true);
    expect(lens.on()).toBe(true);
  });

  it('lets ?lens=1 and ?lens=0 decide for this tab without changing the saved preference', () => {
    const storage = memory({ 'rolecraft.lens': '0' });
    expect(createLensState({ search: '?lens=1', storage }).on()).toBe(true);
    expect(storage.data.get('rolecraft.lens')).toBe('0');
    const saved = memory({ 'rolecraft.lens': '1' });
    expect(createLensState({ search: '?x=2&lens=0', storage: saved }).on()).toBe(false);
    expect(saved.data.get('rolecraft.lens')).toBe('1');
  });

  it('saves a toggle and tells subscribers once per change', () => {
    const storage = memory();
    const lens = createLensState({ search: '', storage });
    const seen = vi.fn();
    const stop = lens.subscribe(seen);
    lens.set(true);
    lens.set(true);
    expect(seen).toHaveBeenCalledTimes(1);
    expect(seen).toHaveBeenLastCalledWith(true);
    expect(storage.data.get('rolecraft.lens')).toBe('1');
    stop();
    lens.set(false);
    expect(seen).toHaveBeenCalledTimes(1);
    expect(lens.on()).toBe(false);
  });

  it('a toggle wins over the address flag in the same tab', () => {
    const lens = createLensState({ search: '?lens=1', storage: memory() });
    lens.set(false);
    expect(lens.on()).toBe(false);
  });
});
