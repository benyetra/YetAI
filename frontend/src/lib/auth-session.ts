/**
 * Client-side auth session helpers: JWT expiry, proactive logout, and 401 handling.
 */

const AUTH_TOKEN_KEY = 'auth_token';
const USER_DATA_KEY = 'user_data';

export type SessionEndReason = 'expired' | 'unauthorized';

type SessionEndHandler = (reason: SessionEndReason) => void;

let sessionEndHandler: SessionEndHandler | null = null;
let expiryTimer: ReturnType<typeof setTimeout> | null = null;

export function registerSessionEndHandler(handler: SessionEndHandler | null): void {
  sessionEndHandler = handler;
}

export function getStoredAuthToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = payload.padEnd(payload.length + ((4 - (payload.length % 4)) % 4), '=');
    return JSON.parse(atob(padded)) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function getTokenExpiryMs(token: string): number | null {
  const payload = decodeJwtPayload(token);
  const exp = payload?.exp;
  if (typeof exp !== 'number') return null;
  return exp * 1000;
}

/** True when JWT is missing, malformed, or past exp (with small clock skew). */
export function isTokenExpired(token: string, skewMs = 5000): boolean {
  const expiryMs = getTokenExpiryMs(token);
  if (expiryMs === null) return true;
  return Date.now() >= expiryMs - skewMs;
}

export function clearAuthStorage(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(USER_DATA_KEY);
}

function clearExpiryTimer(): void {
  if (expiryTimer !== null) {
    clearTimeout(expiryTimer);
    expiryTimer = null;
  }
}

/** Stop proactive expiry timer without clearing credentials (e.g. manual sign-out). */
export function cancelSessionMonitoring(): void {
  clearExpiryTimer();
}

export function scheduleTokenExpiryLogout(token: string): void {
  clearExpiryTimer();
  const expiryMs = getTokenExpiryMs(token);
  if (expiryMs === null) return;

  const delay = expiryMs - Date.now();
  if (delay <= 0) {
    endSession('expired');
    return;
  }

  expiryTimer = setTimeout(() => endSession('expired'), delay);
}

export function persistAuthToken(token: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(AUTH_TOKEN_KEY, token);
  scheduleTokenExpiryLogout(token);
}

/** Clear storage, notify AuthProvider, and redirect to login when appropriate. */
export function endSession(reason: SessionEndReason): void {
  clearExpiryTimer();
  clearAuthStorage();
  sessionEndHandler?.(reason);

  if (typeof window === 'undefined') return;

  const path = window.location.pathname;
  const isPublicAuthPage =
    path === '/' ||
    path.startsWith('/login') ||
    path.startsWith('/auth/callback') ||
    path.startsWith('/verify-email') ||
    path.startsWith('/reset-password') ||
    path.startsWith('/forgot-password');

  if (!isPublicAuthPage) {
    const params = new URLSearchParams({ login: 'true', reason });
    window.location.href = `/?${params.toString()}`;
  }
}

/** End session on 401 for authenticated API calls (not login/register). */
export function handleUnauthorizedResponse(
  response: Response,
  options?: { hadAuthToken?: boolean; skipSessionEnd?: boolean },
): boolean {
  if (options?.skipSessionEnd) return false;
  const hadAuth = options?.hadAuthToken ?? Boolean(getStoredAuthToken());
  if (response.status === 401 && hadAuth) {
    endSession('unauthorized');
    return true;
  }
  return false;
}
