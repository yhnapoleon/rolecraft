// By status · By colleague: the shell's segmented control (ui-kit Segmented, the same one as the
// hat switch). One island per feedback surface; its host element is moved into each redraw of
// the list, so the thumb slides instead of being redrawn.
import { mountIsland } from '../../islands/mount';
import { Segmented, type Segment } from '../../ui-kit';

export type DetailView = 'status' | 'colleague';

type Props = {
  value: DetailView;
  onChange: (v: DetailView) => void;
  items: Segment<DetailView>[];
  label: string;
};

function ViewSwitch(p: Props) {
  return <Segmented value={p.value} onChange={p.onChange} items={p.items} label={p.label} />;
}

export function createViewSwitch(doc: Document, props: Props) {
  const host = doc.createElement('div');
  host.className = 'result-switch';
  const island = mountIsland(host, ViewSwitch, props);
  return {
    element: host,
    update: (next: Props) => island.update(next),
    destroy: () => island.destroy(),
  };
}
