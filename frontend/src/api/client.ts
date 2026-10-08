import type { Row } from "../types/domain";

export type RequestContext = { url: string; init: RequestInit };
export type RequestInterceptor = (request: RequestContext) => RequestContext | Promise<RequestContext>;
export type ResponseInterceptor = (response: Response) => Response | Promise<Response>;

class Interceptors<T> {
  private handlers = new Map<number, T>();
  private sequence = 0;
  use(handler: T) { const id = this.sequence++; this.handlers.set(id, handler); return id; }
  eject(id: number) { this.handlers.delete(id); }
  values() { return [...this.handlers.values()]; }
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly details: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

/** Shared fetch client. It never retries mutations or redirects on a readiness 503. */
export function createApiClient() {
  const interceptors = {
    request: new Interceptors<RequestInterceptor>(),
    response: new Interceptors<ResponseInterceptor>(),
  };
  interceptors.request.use(({ url, init }) => {
    const headers = new Headers(init.headers);
    if (!headers.has("Accept")) headers.set("Accept", "application/json");
    // The browser must set the multipart boundary for FormData uploads.
    if (init.body instanceof FormData) headers.delete("Content-Type");
    return { url: url.startsWith("/health") || url.startsWith("/api/") ? url : "/api/v1" + url,
      init: { ...init, headers } };
  });
  interceptors.response.use(async (response) => {
    if (response.ok) return response;
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `HTTP ${response.status}`;
    throw new ApiError(message, response.status, detail ?? body);
  });
  async function request<T = Row>(path: string, init: RequestInit = {}): Promise<T> {
    let context = { url: path, init };
    for (const handler of interceptors.request.values()) context = await handler(context);
    let response = await fetch(context.url, context.init);
    for (const handler of interceptors.response.values()) response = await handler(response);
    if (response.status === 204) return undefined as T;
    // JSON is required by API endpoints. AbortError remains unchanged for polling cleanup.
    return await response.json() as T;
  }
  const post = <T = Row>(path: string, body: unknown) => request<T>(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  return { request, post, interceptors };
}

export const apiClient = createApiClient();
export const request = apiClient.request;
export const post = apiClient.post;
