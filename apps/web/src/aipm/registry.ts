/** Empty feature mounts until their owning line installs them. No fixture fallback. */
import type { AipmFeature, AipmFeatureId, AipmHost } from './host';

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

// L2 and L3 each export one installer from their feature's index; absent ones stay absent.
const installers = import.meta.glob<Record<string, (host: AipmHost) => unknown>>([
  '../features/aipm-design/index.ts',
  '../features/aipm-evaluation/index.ts',
]);
const OWNERS: Record<AipmFeatureId, [path: string, name: string]> = {
  design: ['../features/aipm-design/index.ts', 'installAipmDesign'],
  evaluation: ['../features/aipm-evaluation/index.ts', 'installAipmEvaluation'],
};

/** Runs every installer present in this build once per host. Returns the features still missing,
 * so the page can say the candidate is incomplete instead of showing a stand-in. */
export async function installAipmFeatures(host: AipmHost): Promise<AipmFeatureId[]> {
  const missing: AipmFeatureId[] = [];
  for (const [id, [path, name]] of Object.entries(OWNERS) as [AipmFeatureId, [string, string]][]) {
    const install = (await installers[path]?.())?.[name];
    if (install) install(host);
    else missing.push(id);
  }
  return missing;
}
