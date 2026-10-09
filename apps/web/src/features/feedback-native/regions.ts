import type { MountV4Slot } from '../../v4-host';
import { NamedRegions } from '../../v4-regions';
import { mountV4Feedback } from './v4-slot';

type RegionName = 'feedback' | 'submission';

/** Feedback owns the contents of the shell's two named regions. */
export class FeedbackRegions extends NamedRegions<RegionName> {
  constructor(mount: MountV4Slot = mountV4Feedback) {
    super(['feedback', 'submission'], (name, root, host) => {
      const handle = mount({ host, nodes: { content: root }, surface: name });
      if (name === 'feedback' && root.dataset.openReview === 'true') {
        const review = root.querySelector<HTMLDetailsElement>(
          'section[aria-label="作品评审"] details, section[aria-label="Artifact review"] details',
        );
        if (review) review.open = true;
      }
      return handle;
    });
  }
}
