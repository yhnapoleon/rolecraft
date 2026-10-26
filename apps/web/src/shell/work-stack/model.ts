/** The work stack's data: what each sheet is, which one shows on top, how the stack opens.
 * Language-free; the caller passes every visible word. (v2 spec §4.) */
export type StackStatus = 'not_started' | 'draft' | 'based' | 'solid' | 'recheck';
export type StackSegment = 'clarify' | 'design' | 'verify' | 'free' | 'material';
export type StackItem = {
  id: string;
  /** 1–7 for a step's sheet; null for a free sheet or a material. */
  order: number | null;
  segment: StackSegment;
  /** A lucide icon name. */
  icon: string;
  name: string;
  /** What this sheet is for, one sentence. */
  purpose: string;
  status: StackStatus;
  /** The status said in words (the dot never carries it alone). */
  statusText: string;
  recheckReason?: string;
  agentDraft: boolean;
  suggested: boolean;
  /** The most serious open point from its latest review, shown on hover or focus. */
  gapHint?: string;
  /** Materials: a newer version arrived. */
  updated?: boolean;
};
export type StackLayout = 'fan' | 'grid' | 'sheet';

/** macOS "automatic": a fan for up to nine, a grid from ten or when the window is short;
 * a bottom sheet on a phone. */
export function stackLayout(count: number, height: number, width: number): StackLayout {
  if (width < 768) return 'sheet';
  return count > 9 || height < 760 ? 'grid' : 'fan';
}

/** The sheet on top of the pile: one to recheck first, then the suggested one, then the first. */
export function topItem(items: readonly StackItem[]): StackItem | undefined {
  return items.find((i) => i.status === 'recheck') ?? items.find((i) => i.suggested) ?? items[0];
}

/** The amber badge: sheets to recheck plus agent drafts waiting for the person. */
export function pendingCount(items: readonly StackItem[]): number {
  return items.reduce(
    (n, i) => n + (i.status === 'recheck' ? 1 : 0) + (i.agentDraft ? 1 : 0) + (i.updated ? 1 : 0),
    0,
  );
}

/** Where keyboard focus lands when the stack opens: the suggested sheet, else the top one. */
export function initialFocus(items: readonly StackItem[]): number {
  const at = items.findIndex((i) => i.suggested);
  return at >= 0 ? at : 0;
}

/** The fan's drift: it leans right faster the higher it goes (a curve, as in a Dock fan), and
 * turns a little with it, up to 3°. */
export function fanOffset(index: number): { x: number; rotate: number } {
  return { x: Math.round(2.6 * index * index), rotate: Math.min(+(index * 0.42).toFixed(2), 3) };
}
