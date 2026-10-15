/** Continue-code calls. Codes and tokens live only in these requests and responses. */
import { sessionPath, type Transport } from '../../api';
import type {
  ContinueCodeExchangeResult,
  ContinueCodeIssued,
  ContinueCodeStatus,
} from '../../contracts-v2';
import type { LocalSession } from '../../types';

type Credentials = Pick<LocalSession, 'id' | 'token'>;

export async function readContinueCode(
  transport: Transport,
  session: Credentials,
): Promise<ContinueCodeStatus> {
  return (await transport(sessionPath(session, '/continue-code'), undefined, session)).result;
}

/** ``expectedGeneration`` is the code the person saw; 0 when there was none. */
export async function replaceContinueCode(
  transport: Transport,
  session: Credentials,
  expectedGeneration: number,
): Promise<ContinueCodeIssued> {
  const body = { expected_generation: expectedGeneration };
  return (await transport(sessionPath(session, '/continue-code'), body, session)).result;
}

/** No bearer: the code is the credential. The same request ID returns the same access. */
export async function exchangeContinueCode(
  transport: Transport,
  code: string,
  requestId: string,
): Promise<ContinueCodeExchangeResult> {
  return (await transport('/continue-codes/exchange', { code, request_id: requestId })).result;
}
