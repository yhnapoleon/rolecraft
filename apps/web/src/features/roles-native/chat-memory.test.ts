import { expect, it } from 'vitest';
import { noteOutgoing, outgoing, outgoingListeners, threadKey } from './chat-memory';

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

it('CHAT-08 a sent message reads sending, then sent once the client confirms it', async () => {
  let confirm!: () => void;
  const calls: string[] = [];
  const listen = () => calls.push(outgoing.get(threadKey('s', 'business_lead'))?.state ?? 'gone');
  outgoingListeners.add(listen);
  try {
    noteOutgoing(
      's',
      'business_lead',
      'Can the 429 minutes count?',
      new Promise<void>((r) => (confirm = r)),
    );
    expect(outgoing.get(threadKey('s', 'business_lead'))).toMatchObject({
      text: 'Can the 429 minutes count?',
      state: 'sending',
    });
    confirm();
    await settle();
    expect(calls).toEqual(['sending', 'sent']);
  } finally {
    outgoingListeners.delete(listen);
    outgoing.clear();
  }
});

it('CHAT-08 a message the client could not send leaves no bubble behind', async () => {
  noteOutgoing('s', 'tech_lead', 'question', Promise.reject(new Error('unconfirmed')));
  await settle();
  expect(outgoing.has(threadKey('s', 'tech_lead'))).toBe(false);
});
