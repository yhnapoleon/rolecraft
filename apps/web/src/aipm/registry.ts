/** Empty feature mounts until their owning line installs them. No fixture fallback. */
import type { AipmFeature, AipmFeatureId } from './host';

export function createAipmRegistry() {
  const features = new Map<AipmFeatureId, AipmFeature>();
  let dispose: (() => void) | undefined;
  return {
    register(id: AipmFeatureId, feature: AipmFeature) {
      if (features.has(id)) throw new Error(`AIPM feature already registered: ${id}`);
      features.set(id, feature);
      return () => {
        if (features.get(id) === feature) features.delete(id);
      };
    },
    get: (id: AipmFeatureId) => features.get(id),
    mount(id: AipmFeatureId, root: HTMLElement) {
      dispose?.();
      dispose = features.get(id)?.mount?.(root) || undefined;
    },
    destroy() {
      dispose?.();
      dispose = undefined;
      features.clear();
    },
  };
}
