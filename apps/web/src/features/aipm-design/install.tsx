/** L1 calls installAipmDesign(host) once; the host decides where the feature is shown. */
import { createRoot } from 'react-dom/client';
import type { AipmClient } from '../../aipm/client';
import type { AipmHost } from '../../aipm/host';
import { DesignDesk, type Tab } from './desk';

export function installAipmDesign(
  host: AipmHost<unknown, AipmClient>,
  options: { initialTab?: Tab } = {},
) {
  return host.registerFeature('design', {
    render: () => '<div class="aipm-design-root"></div>',
    mount(root) {
      const react = createRoot(root);
      react.render(<DesignDesk host={host} initialTab={options.initialTab} />);
      return () => react.unmount();
    },
  });
}
export { DesignDesk } from './desk';
export type { DesignRead, Tab } from './desk';
