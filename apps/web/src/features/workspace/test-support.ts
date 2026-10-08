/** Explicit single-process test double. Browser validation uses native Web Locks. */
import {
  WorkspaceClient,
  type LocalStorage,
  type Transport,
  type JournalCoordinator,
} from './client';
export class MemoryCoordinator implements JournalCoordinator {
  private tails = new Map<string, Promise<void>>();
  exclusive<T>(name: string, body: () => T | Promise<T>): Promise<T> {
    const result = (this.tails.get(name) ?? Promise.resolve()).then(body);
    const tail = result.then(
      () => {},
      () => {},
    );
    this.tails.set(name, tail);
    return result.finally(() => {
      if (this.tails.get(name) === tail) this.tails.delete(name);
    });
  }
}
const coordinator = new MemoryCoordinator();
export function memoryClient(
  session: string,
  storage: LocalStorage,
  transport: Transport,
  id?: () => string,
) {
  return new WorkspaceClient(session, storage, transport, id, { coordinator });
}
