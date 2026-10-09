/** Exact c7 envelopes. The public transport retains auth and network handling;
 * this adapter neither retries, changes request keys, nor creates a journal. */
import type { GatewayTransport, GatewayMethod } from '../../gateway-transport';
import type { Transport } from './client';
const object = (value: unknown): value is Record<string, any> =>
  !!value && typeof value === 'object' && !Array.isArray(value);
const point = (value: any) =>
  object(value) &&
  ['business_seq', 'workspace_revision', 'storage_revision'].every(
    (k) => Number.isInteger(value[k]) && value[k] >= 0,
  );
const unconfirmed = () =>
  Object.assign(Error('服务端结果尚未确认，请保留原请求。'), {
    status: 0,
    code: 'response_unconfirmed',
  });

export function workspaceGatewayTransport(raw: GatewayTransport): Transport {
  return async (path, body: any, method?: string) => {
    if (method && !['GET', 'POST', 'PATCH', 'DELETE'].includes(method)) throw unconfirmed();
    const response = await raw(path, body, method as GatewayMethod | undefined);
    if (!object(response) || response.schema_version !== 2) throw unconfirmed();
    if (body === undefined) {
      // Registered W03 read slots return V2Response inside Gateway's read shell.
      if (
        !object(response.result) ||
        response.result.schema_version !== 2 ||
        !object(response.result.result)
      )
        throw unconfirmed();
      const page = response.result.result;
      if (!Array.isArray(page.items) || !point(page.as_of)) throw unconfirmed();
      return page;
    }
    if (body.operation === 'workspace_imports' && body.payload?.mode === 'preview') {
      const preview = response.result;
      if (
        !object(preview) ||
        preview.mode !== 'preview' ||
        preview.package_id !== body.payload.package_id ||
        !point(preview.as_of)
      )
        throw unconfirmed();
      return preview;
    }
    if (
      typeof response.replayed !== 'boolean' ||
      !Array.isArray(response.objects) ||
      !Array.isArray(response.events) ||
      typeof response.transaction_id !== 'string' ||
      !object(response.boundary) ||
      response.boundary.request_id !== body.request_id ||
      response.boundary.transaction_id !== response.transaction_id ||
      !point(response.state) ||
      !object(response.result) ||
      !point(response.result.as_of)
    )
      throw unconfirmed();
    const session = decodeURIComponent(path.split('/')[2] ?? '');
    if (response.state.session_id !== session) throw unconfirmed();
    // Preserve import receipt points and removals/visible_revocations exactly.
    return response.result;
  };
}
