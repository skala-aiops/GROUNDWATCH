export class APIError extends Error {
  constructor(message, code = 'NETWORK_ERROR', details = [], requestId = '') {
    super(message); Object.assign(this, {code, details, requestId});
  }
}
export class APIClient {
  constructor(fetcher = globalThis.fetch.bind(globalThis), storage = null, uuid = () => crypto.randomUUID()) {
    Object.assign(this, {fetcher, storage, uuid}); this.keys = new Map();
  }
  async request(path, {params = {}, signal, method = 'GET', body, key} = {}) {
    const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== ''));
    const headers = {};
    if (key) headers['Idempotency-Key'] = key;
    if (body && !(body instanceof FormData)) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(body); }
    let response;
    try { response = await this.fetcher(`/api/v1${path}${query.size ? '?' + query : ''}`, {method, headers, body, signal}); }
    catch (e) { if (e.name === 'AbortError') throw e; throw new APIError('서버에 연결하지 못했습니다. 연결을 확인한 뒤 다시 시도하세요.'); }
    let payload;
    try { payload = await response.json(); }
    catch (e) { if (e.name === 'AbortError') throw e; throw new APIError('서버 응답을 확인하지 못했습니다. 잠시 후 다시 시도하세요.', 'INVALID_RESPONSE'); }
    if (!response.ok) throw new APIError(payload.error?.message || '요청을 처리하지 못했습니다.', payload.error?.code || 'SERVER_ERROR', payload.error?.details || [], payload.meta?.request_id);
    if (!payload.meta || !Object.hasOwn(payload, 'data')) throw new APIError('응답 형식이 올바르지 않습니다.', 'INVALID_RESPONSE');
    return {...payload, status: response.status};
  }
  async all(path, params = {}, signal) {
    const result = [], cursors = new Set(); let cursor;
    do {
      const page = await this.request(path, {params: {...params, limit: 100, cursor}, signal});
      result.push(...page.data); cursor = page.meta.next_cursor;
      if (cursor && cursors.has(cursor)) throw new APIError('목록의 다음 페이지를 확인하지 못했습니다.', 'INVALID_RESPONSE');
      cursors.add(cursor);
    } while (cursor);
    return result;
  }
  // Keep uncertain POST outcomes stable across network retries and reloads.
  async mutate(path, body) {
    const identity = `groundwatch:request:${path}:${JSON.stringify(body)}`;
    let key = this.keys.get(identity);
    try { key ||= this.storage?.getItem(identity); } catch { /* Optional persistence. */ }
    key ||= this.uuid(); this.keys.set(identity, key);
    try { this.storage?.setItem(identity, key); } catch { /* In-memory retry remains available. */ }
    try {
      const result = await this.request(path, {method: 'POST', body, key});
      this.keys.delete(identity); try { this.storage?.removeItem(identity); } catch { /* Optional persistence. */ }
      return result;
    } catch (error) {
      if (!['NETWORK_ERROR', 'INVALID_RESPONSE', 'INTERNAL_ERROR'].includes(error.code)) {
        this.keys.delete(identity); try { this.storage?.removeItem(identity); } catch { /* Optional persistence. */ }
      }
      throw error;
    }
  }
}
export const addDays = (day, amount) => new Date(Date.parse(day + 'T00:00:00Z') + amount * 86400000).toISOString().slice(0, 10);
export function dateWindows(from, to) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(from || '') || !/^\d{4}-\d{2}-\d{2}$/.test(to || '') || from > to) throw new APIError('시작일과 종료일을 확인하세요.', 'INVALID_DATA');
  const windows = [];
  for (let start = from; start <= to; start = addDays(start, 756)) windows.push([start, addDays(start, 755) < to ? addDays(start, 755) : to]);
  return windows;
}
export const isActive = run => ['queued', 'running'].includes(run?.status);
export function segments(rows, dateKey) {
  const result = [];
  for (const row of rows) {
    const previous = result.at(-1)?.at(-1);
    if (!previous || addDays(previous[dateKey], 1) !== row[dateKey]) result.push([]);
    result.at(-1).push(row);
  }
  return result;
}
export const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
