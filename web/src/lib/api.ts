// Typed API client for Astro islands (F2 design, section 6). It wraps the legacy shell globals and
// re-implements neither: the token, 401 logout and 403-deactivated handling stay in auth.js, GET retry
// stays in resilient-load.js (types: src/types/legacy-globals.d.ts). It never reads sessionStorage and
// never throws on HTTP, envelope or network failure; a bad path throws, because that is a coding error.
// No page imports it yet: the first consumer is an F4 island.

export type ApiPath = `/api/${string}`;
export type Envelope<T> = { status: "success"; data: T; message?: string } | { status: "error"; message: string };
export type ApiResult<T> =
  | { ok: true; data: T; status: number }
  | { ok: false; status: number; message: string; terminal: boolean };
export type Guard<T> = (data: unknown) => data is T;

const UNEXPECTED = "The server sent an unexpected response.";
// The same sentence resilient-load.js gives for a request that never got an answer.
const UNREACHABLE = "We could not reach the server.";
const NOT_JSON = Symbol("not JSON");

// authenticatedFetch attaches the Bearer token to ANY url (auth.js:91-95), so only a same-origin path
// under /api/ may reach it: no scheme or host, no "//", and no backslash, whitespace or control
// character, which URL parsing may turn into a slash or strip.
const API_PATH = /^\/api\/[^\\\s\u0000-\u001f\u007f]*$/;

function assertApiPath(path: string): asserts path is ApiPath {
  if (!API_PATH.test(path)) throw new TypeError(`Not a same-origin /api/ path: ${JSON.stringify(path)}`);
}

const fail = (status: number, message: string, terminal: boolean): ApiResult<never> => ({ ok: false, status, message, terminal });

function guarded<T>(data: unknown, status: number, isT: Guard<T>): ApiResult<T> {
  return isT(data) ? { ok: true, data, status } : fail(status, UNEXPECTED, true);
}

function serverSentence(body: unknown): string | null {
  const message = typeof body === "object" && body !== null ? (body as { message?: unknown }).message : undefined;
  return typeof message === "string" && message.trim() ? message : null;
}

function isEnvelope(body: unknown): body is Envelope<unknown> {
  const status = typeof body === "object" && body !== null ? (body as { status?: unknown }).status : undefined;
  return status === "success" || status === "error";
}

// One authenticatedFetch call. HTTP and network failures come back as a verdict, never as an exception.
async function callOnce(path: ApiPath, init?: AuthenticatedFetchInit): Promise<ApiResult<unknown>> {
  let response: Response;
  try {
    response = await window.authenticatedFetch(path, init);
  } catch {
    return fail(0, UNREACHABLE, false);
  }
  const body: unknown = await response.json().catch(() => NOT_JSON);
  if (!response.ok) {
    const message = serverSentence(body) ?? `The server responded with status ${response.status}.`;
    return fail(response.status, message, !window.resilientLoad.isRetryableStatus(response.status));
  }
  return body === NOT_JSON ? fail(response.status, UNEXPECTED, true) : { ok: true, data: body, status: response.status };
}

// The exported functions are not async on purpose: a bad path throws synchronously, before any fetch.

/** Authenticated GET of an envelope endpoint, retried by resilientLoad.loadJson (network, 408, 425, 429, 5xx). */
export function getJson<T>(path: ApiPath, isT: Guard<T>): Promise<ApiResult<T>> {
  assertApiPath(path);
  return loadOnce(path, isT);
}

async function loadOnce<T>(path: ApiPath, isT: Guard<T>): Promise<ApiResult<T>> {
  const result = await window.resilientLoad.loadJson(path);
  return result.ok ? guarded(result.data, result.status, isT) : fail(result.status, result.message, result.terminal);
}

/** One mutation of an envelope endpoint. Never retried: the caller decides whether a repeat is safe. */
export function sendJson<T>(path: ApiPath, method: "POST" | "PUT" | "PATCH" | "DELETE", body: unknown, isT: Guard<T>): Promise<ApiResult<T>> {
  assertApiPath(path);
  return sendOnce(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }, isT);
}

async function sendOnce<T>(path: ApiPath, init: AuthenticatedFetchInit, isT: Guard<T>): Promise<ApiResult<T>> {
  const reply = await callOnce(path, init);
  if (!reply.ok) return reply;
  if (!isEnvelope(reply.data)) return fail(reply.status, UNEXPECTED, true);
  if (reply.data.status === "error") return fail(reply.status, serverSentence(reply.data) ?? UNEXPECTED, true);
  return guarded(reply.data.data, reply.status, isT);
}

/** One call to an endpoint that answers without the envelope (/api/broadcast/*, /api/ai-models); the guard sees the whole body. */
export function requestRaw<T>(path: ApiPath, isT: Guard<T>, init?: AuthenticatedFetchInit): Promise<ApiResult<T>> {
  assertApiPath(path);
  // A fresh object and headers: auth.js writes the token into options.headers (auth.js:86-93).
  return rawOnce(path, isT, { ...init, headers: { ...init?.headers } });
}

async function rawOnce<T>(path: ApiPath, isT: Guard<T>, init?: AuthenticatedFetchInit): Promise<ApiResult<T>> {
  const reply = await callOnce(path, init);
  return reply.ok ? guarded(reply.data, reply.status, isT) : reply;
}
