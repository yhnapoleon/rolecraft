import type { MountV4Slot } from '../../v4-host';
import { NamedRegions } from '../../v4-regions';
import { mount as mountRoles } from './v4-slot';

/** One conversation renderer; role drafts and writes stay with the bound host. */
export class RolesRegions extends NamedRegions<'roles'> {
  constructor(mount: MountV4Slot = mountRoles) {
    super(['roles'], (_name, root, host) => {
      const thread = root.querySelector<HTMLElement>('.thread');
      const composer = root.querySelector<HTMLElement>('.composer');
      return mount({
        host,
        nodes: { ...(thread ? { thread } : {}), ...(composer ? { composer } : {}) },
      });
    });
  }
}
