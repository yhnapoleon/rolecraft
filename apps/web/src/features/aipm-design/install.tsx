/** L1 calls installAipmDesign(host) once; the panel opens the section of the server's focus step. */
import { createRoot } from 'react-dom/client';
import type { AipmClient } from '../../aipm/client';
import type { AipmHost } from '../../aipm/host';
import { DesignDesk } from './desk';

export function installAipmDesign(host: AipmHost<unknown, AipmClient>) {
  return host.registerFeature('design', {
    render: () => '<div class="aipm-design-root"></div>',
    mount(root) {
      const react = createRoot(root);
      react.render(<DesignDesk host={host} />);
      return () => react.unmount();
    },
  });
}
export { DesignDesk } from './desk';
export type { DesignRead, DraftItem } from './desk';
