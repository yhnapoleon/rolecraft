/** Evidence of a saved work version in the v4 workspace: chosen with the shared picker, kept in
 * the work's draft until the person saves a version, and shown by title and version. */
import { T } from './app/i18n';
import type { EvidenceRefV2, ObjectRef } from './contracts-v2';
import { EVIDENCE_KINDS, evidenceKey } from './evidence-picker';
import type { V4HostAdapter } from './v4-host';

/** What the workspace already knows about cited objects. */
export type EvidenceNames = {
  material(id: string, version: number): string | undefined;
  test(id: string): { query: string; config?: number } | undefined;
  product(id: string): string | undefined;
};
export type EvidenceChip = {
  key: string;
  kind: 'material' | 'test' | 'product' | 'other';
  label: string;
  version: string;
  /** Screen-reader and hover text, including a cited passage. */
  description: string;
  /** The cited passage itself, shown under the chips so the basis can be read in place. */
  quote?: string;
};

const sameChoice = (a: readonly EvidenceRefV2[], b: readonly EvidenceRefV2[]) => {
  const keys = (refs: readonly EvidenceRefV2[]) => refs.map(evidenceKey).sort().join('\n');
  return keys(a) === keys(b);
};

/** Ask for the work's evidence; null when the person keeps the same evidence. */
export async function chooseWorkEvidence(
  host: V4HostAdapter,
  work: ObjectRef,
  current: readonly EvidenceRefV2[],
  focus?: ObjectRef,
): Promise<EvidenceRefV2[] | null> {
  const chosen = await host.chooseEvidence({
    kinds: EVIDENCE_KINDS,
    selected: current,
    exclude: [work],
    ...(focus ? { focus } : {}),
  });
  return sameChoice(chosen, current) ? null : [...chosen];
}

// A work's version is "第 N 版" / "version N"; documents keep "vN".
const versionText = (version: number) => T(`第 ${version} 版`, `version ${version}`);
const documentVersion = (version: number) => `v${version}`;

export function evidenceChips(
  refs: readonly EvidenceRefV2[],
  names: EvidenceNames,
): EvidenceChip[] {
  return refs.map((ref) => {
    const key = evidenceKey(ref);
    if (ref.kind === 'material') {
      const label = names.material(ref.object_id, ref.version) ?? T('资料', 'Document');
      const version = documentVersion(ref.version);
      const quote = ref.quote ? T('：', ': ') + ref.quote : '';
      return {
        key,
        kind: 'material',
        label,
        version,
        description: `${label} · ${version}${quote}`,
        ...(ref.quote ? { quote: ref.quote } : {}),
      };
    }
    if (ref.kind === 'test') {
      const test = names.test(ref.object_id);
      const label = test ? T('测试：', 'Test: ') + test.query : T('测试运行', 'Test run');
      const version =
        test?.config === undefined ? '' : T(`配置 v${test.config}`, `config v${test.config}`);
      return { key, kind: 'test', label, version, description: [label, version].join(' · ') };
    }
    if (ref.kind === 'product') {
      const title = names.product(ref.object_id);
      const label = title ? T(`《${title}》`, `“${title}”`) : T('作品', 'Work');
      const version = versionText(ref.version);
      return { key, kind: 'product', label, version, description: `${label} · ${version}` };
    }
    const label = T('依据', 'Evidence');
    const version = versionText(ref.version);
    return { key, kind: 'other', label, version, description: `${label} · ${version}` };
  });
}
