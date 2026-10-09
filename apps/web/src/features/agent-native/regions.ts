import type { MountV4Slot } from '../../v4-host';
import { NamedRegions } from '../../v4-regions';
import { mountV4AgentSlot } from './v4-slot';

/** Agent controls own the assigned rail nodes; credentials remain private to the host. */
export class AgentRegions extends NamedRegions<'agent'> {
  constructor(mount: MountV4Slot = mountV4AgentSlot) {
    super(['agent'], (_name, root, host) => {
      const nodes: Record<string, HTMLElement> = {};
      for (const name of ['connection', 'activity', 'returns']) {
        const node = root.querySelector<HTMLElement>(`[data-agent-${name}]`);
        if (node) nodes[name] = node;
      }
      return mount({ host, nodes });
    });
  }
}
