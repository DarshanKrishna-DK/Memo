/** Typed fetch helpers. Same-origin (vite proxies /api to FastAPI), cookies always included. */
export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) { super(message); }
}

type Listener = () => void;
const unauthListeners = new Set<Listener>();
export const onUnauthorized = (fn: Listener) => { unauthListeners.add(fn); return () => { unauthListeners.delete(fn); }; };

async function parse(res: Response): Promise<unknown> {
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json().catch(() => null);
  const t = await res.text().catch(() => '');
  return t || null;
}

function messageOf(body: unknown, status: number): string {
  if (body && typeof body === 'object') {
    const b = body as Record<string, unknown>;
    const d = b.detail ?? b.error ?? b.message;
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) return d.map((x) => (x && typeof x === 'object' && 'msg' in x ? String((x as { msg: unknown }).msg) : String(x))).join('; ');
  }
  if (typeof body === 'string' && body) return body.slice(0, 200);
  return `Request failed (${status})`;
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown; quiet401?: boolean } = {}): Promise<T> {
  const { json, quiet401, headers, ...rest } = init;
  const h = new Headers(headers);
  let body = rest.body;
  if (json !== undefined) { h.set('Content-Type', 'application/json'); body = JSON.stringify(json); }
  const res = await fetch(path, { credentials: 'include', ...rest, headers: h, body });
  const data = await parse(res);
  if (!res.ok) {
    if (res.status === 401 && !quiet401) unauthListeners.forEach((f) => f());
    throw new ApiError(res.status, messageOf(data, res.status), data);
  }
  return data as T;
}

export const get = <T,>(p: string, o?: RequestInit & { quiet401?: boolean }) => api<T>(p, { ...o, method: 'GET' });
export const post = <T,>(p: string, json?: unknown, o?: RequestInit) => api<T>(p, { ...o, method: 'POST', json: json ?? {} });
export const patch = <T,>(p: string, json?: unknown) => api<T>(p, { method: 'PATCH', json: json ?? {} });
export const put = <T,>(p: string, json?: unknown) => api<T>(p, { method: 'PUT', json: json ?? {} });
export const del = <T,>(p: string, json?: unknown) => api<T>(p, json === undefined ? { method: 'DELETE' } : { method: 'DELETE', json });
export const upload = <T,>(p: string, form: FormData, signal?: AbortSignal) => api<T>(p, { method: 'POST', body: form, signal });

/** Lists may come back bare or wrapped ({items: []}, {rooms: []} ...). */
export function listOf<T>(data: unknown, ...keys: string[]): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === 'object') {
    const o = data as Record<string, unknown>;
    for (const k of [...keys, 'items', 'results', 'data']) if (Array.isArray(o[k])) return o[k] as T[];
  }
  return [];
}
