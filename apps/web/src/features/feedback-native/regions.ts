import type { MountV4Slot, V4HostAdapter, V4SlotHandle } from '../../v4-host';
import { surfaceHost } from '../../v4-surface-host';
import { mountV4Feedback } from './v4-slot';

const names = ['feedback', 'submission'] as const;
type RegionName = (typeof names)[number];
type MountedRegion = {
  host: V4HostAdapter;
  root: HTMLElement;
  handle: V4SlotHandle;
  close: () => void;
};

/** The shell allocates empty named regions; the feedback module owns their entire contents. */
export class FeedbackRegions {
  private readonly mounted = new Map<RegionName, MountedRegion>();

  constructor(private readonly mount: MountV4Slot = mountV4Feedback) {}

  destroy(): void {
    for (const region of this.mounted.values()) region.close();
    this.mounted.clear();
  }

  sync(document: Document, host: V4HostAdapter): void {
    if (host.snapshot().session?.protocol !== 2) {
      this.destroy();
      return;
    }
    const roots = this.roots(document);
    for (const name of names) {
      const root = roots.get(name);
      const previous = this.mounted.get(name);
      if (previous && (previous.host !== host || previous.root !== root || !root?.isConnected)) {
        previous.close();
        this.mounted.delete(name);
      }
      if (!root?.isConnected) continue;
      const mounted = this.mounted.get(name);
      if (mounted) mounted.handle.update(host.snapshot());
      else this.mounted.set(name, this.attach(name, root, host));
    }
  }

  private roots(document: Document): Map<RegionName, HTMLElement> {
    const roots = new Map<RegionName, HTMLElement>();
    for (const name of names) {
      const matches = document.querySelectorAll<HTMLElement>(`[data-v4-region="${name}"]`);
      if (matches.length > 1) throw new Error(`Duplicate v4 region: ${name}`);
      const root = matches[0];
      const dialog = root?.closest<HTMLDialogElement>('dialog');
      if (root && (!dialog || dialog.open)) roots.set(name, root);
    }
    return roots;
  }

  private attach(name: RegionName, root: HTMLElement, host: V4HostAdapter): MountedRegion {
    let active = true;
    const handle = this.mount({
      host: surfaceHost(host, () => active),
      nodes: { content: root },
      surface: name,
    });
    if (name === 'feedback' && root.dataset.openReview === 'true') {
      const review = root.querySelector<HTMLDetailsElement>(
        'section[aria-label="作品评审"] details, section[aria-label="Artifact review"] details',
      );
      if (review) review.open = true;
    }
    return {
      host,
      root,
      handle,
      close: () => {
        active = false;
        handle.destroy();
      },
    };
  }
}
