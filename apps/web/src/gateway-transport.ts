import { ApiError } from './api';
import { T } from './app/i18n';

export type GatewayCredentials = { sessionId: string; token: string };
export type GatewayMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE';
export type GatewayTransport = (path: string, body?: unknown, method?: GatewayMethod) => Promise<unknown>;

/** Thin HTTP boundary for native DOM integration. No journal, retry or result projection. */
export function createGatewayTransport(
  credentials: () => GatewayCredentials,
  fetcher: typeof fetch = fetch,
  prefix = '/api',
): GatewayTransport {
  const base = 'https://rolecraft.invalid';
  if (!prefix.startsWith('/') || prefix.startsWith('//') || /[?#\\]/.test(prefix) ||
      new URL(prefix, base).pathname !== prefix || /%(?:2e|2f|5c)/i.test(prefix)) {
    throw new ApiError('Invalid API path', 400, 'invalid_api_path');
  }
  const root = prefix.replace(/\/$/, '');
  return async (path, body, method) => {
    const current = credentials();
    if (!current.sessionId || !current.token) throw new ApiError(T('会话凭据失效，请保留原浏览器数据。', 'Session credentials are unavailable. Keep the original browser data.'), 401, 'token_required');
    const expected = '/sessions/' + encodeURIComponent(current.sessionId);
    const pathname = path.split('?')[0];
    const url = new URL(root + path, base);
    if (!path.startsWith('/') || path.startsWith('//') || /[\\#]/.test(path) ||
        /%(?:2e|2f|5c)/i.test(pathname) ||
        !(pathname === expected || pathname.startsWith(expected + '/')) ||
        url.origin !== base || url.pathname !== root + pathname) {
      throw new ApiError(T('请求不属于当前会话。', 'The request does not belong to this session.'), 404, 'session_route_mismatch');
    }
    const verb = method ?? (body === undefined ? 'GET' : 'POST');
    if (!['GET', 'POST', 'PATCH', 'DELETE'].includes(verb) || (verb === 'GET') !== (body === undefined)) {
      throw new ApiError('Invalid request method', 400, 'invalid_command');
    }
    let serialized: string | undefined;
    if (body !== undefined) {
      const c = body as Record<string, unknown>;
      if (!c || typeof c !== 'object' || Array.isArray(c) || c.schema_version !== 2 ||
          typeof c.request_id !== 'string' || !c.request_id || typeof c.operation !== 'string' || !c.operation ||
          !Number.isInteger(c.expected_version) || (c.expected_version as number) < 0 ||
          !Number.isInteger(c.expected_workspace_revision) || (c.expected_workspace_revision as number) < 0 ||
          !c.payload || typeof c.payload !== 'object' || Array.isArray(c.payload)) {
        throw new ApiError('An explicit v2 command is required', 400, 'invalid_command');
      }
      try { serialized = JSON.stringify(body); }
      catch { throw new ApiError('Invalid command data', 400, 'invalid_command'); }
    }
    let response: Response;
    try {
      response = await fetcher(root + path, {
        method: verb,
        headers: { Authorization: 'Bearer ' + current.token, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
        body: serialized, redirect: 'error', credentials: 'omit', cache: 'no-store',
        signal: AbortSignal.timeout(20000),
      });
    } catch {
      throw new ApiError(T('结果尚未确认。请保留原输入并核对原请求。', 'The result is unconfirmed. Keep the input and check the original request.'), 0, 'response_unconfirmed');
    }
    let result: unknown;
    try { result = await response.json(); }
    catch { throw new ApiError(T('返回内容无法核对，请保留原请求。', 'The response could not be verified. Keep the original request.'), 0, 'response_unconfirmed'); }
    if (!response.ok) {
      const error = result && typeof result === 'object' ? result as Record<string, unknown> : {};
      const historical = ['scenario_binding_mismatch','scenario_archive_unavailable','scenario_read_only'].includes(String(error.code));
      const detail = historical ? T('这个练习使用旧版场景。原记录仍保留，请只读查看或开始新的练习；若暂时无法读取，请保留浏览器存档并重试连接。','This practice uses an earlier scenario. Its records are retained. View them read-only or start a new practice; if reading is unavailable, keep your browser data and reconnect.') : typeof error.detail === 'string' ? error.detail : typeof error.error === 'string' ? error.error : T('请求未完成。', 'The request was not completed.');
      throw new ApiError(detail, response.status, typeof error.code === 'string' ? error.code : 'request_failed');
    }
    if (!result || typeof result !== 'object' || Array.isArray(result) || (result as Record<string, unknown>).schema_version !== 2) {
      throw new ApiError(T('返回内容无法核对，请保留原请求。', 'The response could not be verified. Keep the original request.'), 0, 'response_unconfirmed');
    }
    // Keep PublicTransactionResult and read wrappers intact. Consumers validate
    // their own DTOs and own the one durable request journal.
    return result;
  };
}
