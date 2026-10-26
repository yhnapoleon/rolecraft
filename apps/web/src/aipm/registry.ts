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

// L2 and L3 each export one installer from their feature folder; absent ones stay absent.
const modules = import.meta.glob<Record<string, unknown>>([
  '../features/aipm-design/{index,install}.{ts,tsx}',
  '../features/aipm-evaluation/{index,install}.{ts,tsx}',
  '../features/aipm-review/{index,install}.{ts,tsx}',
]);
const OWNERS: Record<AipmFeatureId, [folder: string, name: string]> = {
  design: ['../features/aipm-design/', 'installAipmDesign'],
  evaluation: ['../features/aipm-evaluation/', 'installAipmEvaluation'],
  worksheet: ['../features/aipm-design/', 'installAipmWorksheet'],
  review: ['../features/aipm-review/', 'installAipmReview'],
};

/** Runs every installer present in this build once per host. Returns the features still missing,
 * so the page can say the candidate is incomplete instead of showing a stand-in. */
export async function installAipmFeatures(host: AipmHost): Promise<AipmFeatureId[]> {
  const missing: AipmFeatureId[] = [];
  for (const [id, [folder, name]] of Object.entries(OWNERS) as [
    AipmFeatureId,
    [string, string],
  ][]) {
    let install: unknown;
    for (const [path, load] of Object.entries(modules))
      if (path.startsWith(folder) && !install) install = (await load())[name];
    if (typeof install === 'function') install(host);
    else missing.push(id);
  }
  return missing;
}
