// The live stream on the desk: 205's TransmissionStream, compact (the last three engineer.* calls
// of this practice's Agent), kept in the Agent panel's `data-transmission-slot`
// (data-island="engineer-stream") with keepIsland. A row opens the matching card through openCard.
import { keepIsland } from '../../../islands/mount';
import { LiveTransmissionStream } from '../../agent-page/live';
import { openCard } from './panel';

function EngineerStream() {
  return (
    <LiveTransmissionStream
      variant="compact"
      hat="engineer"
      onOpen={(e) => openCard(e.tool, e.object?.id)}
    />
  );
}

/** Puts the stream island in this panel's slot (the panel element is kept across redraws, and a
 * desk kept off screen gives the island up to the one on screen). */
export function mountStreamSlot(root: ParentNode) {
  return keepIsland('engineer-stream', EngineerStream, {}, { root, persist: true });
}
