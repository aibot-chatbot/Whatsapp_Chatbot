// Globals of the legacy shell scripts that AppLayout loads at their URLs (F2 design, section 6).
// Only what web/src/lib/api.ts uses. Each type is taken from the real source; the line refs say where.
// web/tests/legacy-shell-contract.test.ts runs those files and checks the behaviour behind these types.

/**
 * Options for authenticatedFetch. Headers must be a plain object: auth.js adds the token with
 * `options.headers["Authorization"] = ...` (frontend/assets/js/auth.js:86-93), which a Headers
 * instance would silently ignore. auth.js also writes into this object, so pass a fresh one.
 */
type AuthenticatedFetchInit = Omit<RequestInit, "headers"> & { headers?: Record<string, string> };

/** frontend/assets/js/resilient-load.js:24-29 (defaults), :63-67 and :98-105 (onRetry). */
interface LoadJsonOptions {
  attempts?: number;
  baseDelay?: number;
  maxDelay?: number;
  timeout?: number;
  onRetry?: (info: { attempt: number; of: number; delay: number; status: number; message: string }) => void;
}

/** frontend/assets/js/resilient-load.js:151 (success), :87-94 and :110-113 (failure). It never rejects. */
type LoadJsonResult =
  | { ok: true; data: unknown; status: number; message: ""; terminal: false }
  | { ok: false; data: null; status: number; message: string; terminal: boolean; attempts: number };

interface Window {
  /**
   * frontend/assets/js/auth.js:82-116 (a classic-script function, so a window property). It attaches
   * the session token to ANY url it is given; api.ts only ever passes a checked /api/ path.
   */
  authenticatedFetch(url: string, options?: AuthenticatedFetchInit): Promise<Response>;
  /** frontend/assets/js/resilient-load.js:174. */
  resilientLoad: {
    /** resilient-load.js:73. Authenticated GET with retry; it drops every fetch option, so GET only. */
    loadJson(url: string, options?: LoadJsonOptions): Promise<LoadJsonResult>;
    /** resilient-load.js:33-35. True for 408, 425, 429 and every 5xx. */
    isRetryableStatus(status: number): boolean;
  };
}
