import type { LocalSession } from './types';
import { T } from './app/i18n';

export class ApiError extends Error {
  constructor(message: string, public status = 0) { super(message); }
}
export type Transport = (path: string, body?: unknown, session?: Pick<LocalSession, 'id' | 'token'>) => Promise<any>;
export const request: Transport = async (path, body, session) => {
  let response: Response;
  try {
    response = await fetch('/api' + path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }), ...(session ? { Authorization: 'Bearer ' + session.token } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(20000),
      cache: 'no-store',
    });
  } catch { throw new ApiError(T('连接中断或请求超时。写入结果可能已保存，请用“重试原请求”核对，避免重复操作。', 'The connection dropped or timed out. The write may have been saved; retry the same request to check instead of repeating it.')); }
  let data: any;
  try { data = await response.json(); } catch { throw new ApiError(T('服务未返回可识别的结果，请检查 API 是否启动。', 'The server returned something unreadable. Check that the API is running.'), response.status >= 500 ? response.status : 0); }
  if (!response.ok) {
    const detail = data.detail ?? data.error ?? T('请求失败', 'Request failed');
    throw new ApiError(typeof detail === 'string' ? detail : JSON.stringify(detail), response.status);
  }
  return data;
};
export const sessionPath = (s: Pick<LocalSession, 'id'>, suffix = '') => '/sessions/' + encodeURIComponent(s.id) + suffix;
