/** GET /sessions/{id}/recognition: every recognizer record of this practice, with counts. */
import { sessionPath, type Transport } from '../../api';
import type { LocalSession } from '../../types';
import type { RecognitionRecord } from './badge';

type Credentials = Pick<LocalSession, 'id' | 'token'>;

export interface SessionRecognition {
  session_id: string;
  records: {
    carrier: { kind: string; object_id: string; version: number };
    position: number;
    record: RecognitionRecord;
  }[];
  counts: Record<string, number>;
  recognizers: { id: string; revision: string; fallback: boolean }[];
}

/** GET /sessions/{id}/behavior: the C5 trajectory analysis of this practice. */
export async function readBehavior(transport: Transport, session: Credentials) {
  return (await transport(sessionPath(session, '/behavior'), undefined, session)).result.result;
}

export async function readRecognition(
  transport: Transport,
  session: Credentials,
): Promise<SessionRecognition> {
  return (await transport(sessionPath(session, '/recognition'), undefined, session)).result.result;
}
