// The transmission stream wired to this practice's agent feed, for screens other than My agent
// (the engineer's sign-off desk): <LiveTransmissionStream variant="compact" hat="engineer"
// onOpen={(e) => openCard(e.tool, e.object?.id)} />. Rows that arrive while it is on screen press
// in; earlier ones are shown still.
import { useSyncExternalStore } from 'react';
import { feedStore } from './index';
import { TransmissionStream, type TransmissionStreamProps } from './stream';

export function LiveTransmissionStream(
  props: Omit<TransmissionStreamProps, 'events' | 'liveFrom'>,
) {
  const feed = useSyncExternalStore(feedStore.subscribe, feedStore.snapshot);
  return <TransmissionStream {...props} events={feed.events} liveFrom={feed.liveFrom} />;
}
