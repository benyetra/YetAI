export const OAUTH_RETURN_PATH_KEY = 'yetai_auth_next';
export const DEFAULT_POST_LOGIN_PATH = '/dashboard';

const AUTH_PAGE_PREFIXES = [
  '/login',
  '/signup',
  '/auth/callback',
  '/verify-email',
  '/forgot-password',
  '/reset-password',
] as const;

function pathnameOf(path: string): string {
  const noHash = path.split('#')[0] ?? path;
  const q = noHash.indexOf('?');
  return q === -1 ? noHash : noHash.slice(0, q);
}

export function isSafeReturnPath(path: string): boolean {
  if (!path || typeof path !== 'string') return false;
  if (!path.startsWith('/')) return false;
  if (path.startsWith('//')) return false;
  if (path.includes('\\')) return false;
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(path)) return false;

  const pathname = pathnameOf(path);
  if (pathname === '/') return false;
  for (const prefix of AUTH_PAGE_PREFIXES) {
    if (pathname === prefix || pathname.startsWith(`${prefix}/`)) return false;
  }
  return true;
}

export function resolvePostLoginRedirect(next?: string | null): string {
  if (next && isSafeReturnPath(next)) return next;
  return DEFAULT_POST_LOGIN_PATH;
}

export function buildLoginUrl(
  returnPath?: string | null,
  options?: { reason?: string },
): string {
  const path =
    returnPath ??
    (typeof window !== 'undefined'
      ? `${window.location.pathname}${window.location.search}`
      : null);

  const params = new URLSearchParams();
  if (path && isSafeReturnPath(path)) params.set('next', path);
  if (options?.reason) params.set('reason', options.reason);

  const qs = params.toString();
  return qs ? `/login?${qs}` : '/login';
}

export function stashOAuthReturnPath(path: string): void {
  if (typeof window === 'undefined') return;
  if (!isSafeReturnPath(path)) return;
  sessionStorage.setItem(OAUTH_RETURN_PATH_KEY, path);
}

export function consumeOAuthReturnPath(): string | null {
  if (typeof window === 'undefined') return null;
  const raw = sessionStorage.getItem(OAUTH_RETURN_PATH_KEY);
  sessionStorage.removeItem(OAUTH_RETURN_PATH_KEY);
  if (raw && isSafeReturnPath(raw)) return raw;
  return null;
}
