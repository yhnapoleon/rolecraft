import type { MountV4Slot } from '../../v4-host';
import { NamedRegions } from '../../v4-regions';
import { mount as mountResources } from './v4-request-slot';

/** Resource requests own the original dialog form, never a second request journal. */
export class ResourceRegions extends NamedRegions<'resource-requests'> {
  constructor(mount: MountV4Slot = mountResources) {
    super(['resource-requests'], (_name, root, host) => {
      const form = root.querySelector<HTMLElement>('#res-form');
      const submit = root
        .closest('dialog')
        ?.querySelector<HTMLElement>('[form="res-form"][type="submit"]');
      return mount({
        host,
        nodes: { ...(form ? { form } : {}), ...(submit ? { submit } : {}) },
      });
    });
  }
}
