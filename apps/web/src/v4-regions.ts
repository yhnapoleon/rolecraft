import type { V4HostAdapter, V4SlotHandle } from './v4-host';
import { surfaceHost } from './v4-surface-host';

type RegionMount<Name extends string> = (
  name: Name,
  root: HTMLElement,
  host: V4HostAdapter,
) => V4SlotHandle;
type Region = {
  root: HTMLElement;
  host: V4HostAdapter;
  handle: V4SlotHandle;
  close(): void;
};

/** The shell replaces named roots; modules exclusively own their assigned contents. */
export class NamedRegions<Name extends string> {
  private readonly mounted = new Map<Name, Region>();

  constructor(
    private readonly names: readonly Name[],
    private readonly mount: RegionMount<Name>,
  ) {}

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
    this.releaseMissing(roots, host);
    for (const name of this.names) {
      const root = roots.get(name);
      if (!root?.isConnected) continue;
      const current = this.mounted.get(name);
      if (current) current.handle.update(host.snapshot());
      else this.mounted.set(name, this.attach(name, root, host));
    }
  }

  /** Release departed surfaces synchronously, before awaiting host locks or reads. */
  prune(document: Document, host: V4HostAdapter): void {
    if (host.snapshot().session?.protocol !== 2) this.destroy();
    else this.releaseMissing(this.roots(document), host);
  }

  private releaseMissing(roots: ReadonlyMap<Name, HTMLElement>, host: V4HostAdapter): void {
    for (const [name, region] of this.mounted) {
      const root = roots.get(name);
      if (region.host !== host || region.root !== root || !root?.isConnected) {
        region.close();
        this.mounted.delete(name);
      }
    }
  }

  private roots(document: Document): Map<Name, HTMLElement> {
    const roots = new Map<Name, HTMLElement>();
    for (const name of this.names) {
      const matches = document.querySelectorAll<HTMLElement>(`[data-v4-region="${name}"]`);
      if (matches.length > 1) throw new Error(`Duplicate v4 region: ${name}`);
      const root = matches[0];
      const dialog = root?.closest<HTMLDialogElement>('dialog');
      if (root && (!dialog || dialog.open)) roots.set(name, root);
    }
    return roots;
  }

  private attach(name: Name, root: HTMLElement, host: V4HostAdapter): Region {
    let active = true;
    const handle = this.mount(
      name,
      root,
      surfaceHost(host, () => active),
    );
    return {
      root,
      host,
      handle,
      close: () => {
        active = false;
        handle.destroy();
      },
    };
  }
}
