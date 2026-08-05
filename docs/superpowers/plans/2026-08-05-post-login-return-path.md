# Post-login Return Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After email/password or Google login, restore users to the page that triggered auth (via `?next=` + sessionStorage), defaulting to `/dashboard`.

**Architecture:** Pure helpers in `auth-redirect.ts` validate and build return URLs. Kick-to-login call sites use `buildLoginUrl()`. Login and OAuth callback consume `next` / sessionStorage. Signup stays on `/dashboard`.

**Tech Stack:** Next.js 15 App Router, TypeScript, Jest (unit), existing client auth in `auth-session.ts`.

**Spec:** `docs/superpowers/specs/2026-08-05-post-login-return-path-design.md`

## Global Constraints

- Frontend only — no backend OAuth `state` changes
- Signup never uses return path → always `/dashboard`
- Safe paths only: relative `/…`, reject open redirects and auth pages
- Preserve query string; ignore hash
- sessionStorage key: `yetai_auth_next`

## File map

| File | Responsibility |
|------|----------------|
| `frontend/src/lib/auth-redirect.ts` | Create — safe path helpers, login URL builder, OAuth stash |
| `frontend/src/lib/auth-redirect.test.ts` | Create — unit tests |
| `frontend/src/lib/auth-session.ts` | Modify — `endSession` uses `buildLoginUrl` |
| `frontend/src/app/login/page.tsx` | Modify — resolve `next`; stash before Google URL redirect |
| `frontend/src/app/auth/callback/page.tsx` | Modify — consume OAuth stash |
| `frontend/src/app/page.tsx` | Modify — forward `next` + `reason` to `/login` |
| Protected pages + `Navigation.tsx` + views | Modify — replace `/?login=true` with `buildLoginUrl()` |

---

### Task 1: Auth redirect helpers + tests

**Files:**
- Create: `frontend/src/lib/auth-redirect.ts`
- Create: `frontend/src/lib/auth-redirect.test.ts`

**Interfaces:**
- Produces:
  - `isSafeReturnPath(path: string): boolean`
  - `resolvePostLoginRedirect(next?: string | null): string`
  - `buildLoginUrl(returnPath?: string | null, options?: { reason?: string }): string`
  - `stashOAuthReturnPath(path: string): void`
  - `consumeOAuthReturnPath(): string | null`
  - `OAUTH_RETURN_PATH_KEY = 'yetai_auth_next'`

- [ ] **Step 1: Write failing tests**

```typescript
import {
  isSafeReturnPath,
  resolvePostLoginRedirect,
  buildLoginUrl,
  stashOAuthReturnPath,
  consumeOAuthReturnPath,
  OAUTH_RETURN_PATH_KEY,
} from './auth-redirect';

describe('isSafeReturnPath', () => {
  it('allows relative app paths with query', () => {
    expect(isSafeReturnPath('/bets')).toBe(true);
    expect(isSafeReturnPath('/predictions?sport=mlb')).toBe(true);
  });

  it('rejects open redirects and auth pages', () => {
    expect(isSafeReturnPath('https://evil.com')).toBe(false);
    expect(isSafeReturnPath('//evil.com')).toBe(false);
    expect(isSafeReturnPath('/\\evil')).toBe(false);
    expect(isSafeReturnPath('/login')).toBe(false);
    expect(isSafeReturnPath('/signup')).toBe(false);
    expect(isSafeReturnPath('/')).toBe(false);
    expect(isSafeReturnPath('/auth/callback')).toBe(false);
    expect(isSafeReturnPath('/verify-email')).toBe(false);
    expect(isSafeReturnPath('/forgot-password')).toBe(false);
    expect(isSafeReturnPath('/reset-password')).toBe(false);
  });
});

describe('resolvePostLoginRedirect', () => {
  it('returns next when safe, else /dashboard', () => {
    expect(resolvePostLoginRedirect('/bets')).toBe('/bets');
    expect(resolvePostLoginRedirect('/login')).toBe('/dashboard');
    expect(resolvePostLoginRedirect(null)).toBe('/dashboard');
  });
});

describe('buildLoginUrl', () => {
  it('encodes next and optional reason', () => {
    expect(buildLoginUrl('/predictions?sport=mlb')).toBe(
      '/login?next=%2Fpredictions%3Fsport%3Dmlb',
    );
    expect(buildLoginUrl('/bets', { reason: 'expired' })).toBe(
      '/login?next=%2Fbets&reason=expired',
    );
  });

  it('omits next when path is unsafe', () => {
    expect(buildLoginUrl('/login')).toBe('/login');
  });
});

describe('oauth return path stash', () => {
  beforeEach(() => sessionStorage.clear());

  it('stashes safe paths and consume clears', () => {
    stashOAuthReturnPath('/bets');
    expect(sessionStorage.getItem(OAUTH_RETURN_PATH_KEY)).toBe('/bets');
    expect(consumeOAuthReturnPath()).toBe('/bets');
    expect(consumeOAuthReturnPath()).toBeNull();
  });

  it('does not stash unsafe paths', () => {
    stashOAuthReturnPath('/login');
    expect(consumeOAuthReturnPath()).toBeNull();
  });
});
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd frontend && npm run test:unit -- src/lib/auth-redirect.test.ts
```

Expected: FAIL (module missing)

- [ ] **Step 3: Implement `auth-redirect.ts`**

```typescript
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
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd frontend && npm run test:unit -- src/lib/auth-redirect.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/auth-redirect.ts frontend/src/lib/auth-redirect.test.ts
git commit -m "feat(auth): add post-login return path helpers"
```

---

### Task 2: Wire endSession, login, callback, home

**Files:**
- Modify: `frontend/src/lib/auth-session.ts`
- Modify: `frontend/src/app/login/page.tsx`
- Modify: `frontend/src/app/auth/callback/page.tsx`
- Modify: `frontend/src/app/page.tsx`

**Interfaces:**
- Consumes: helpers from Task 1

- [ ] **Step 1: Update `endSession`**

Replace redirect block with:

```typescript
import { buildLoginUrl } from './auth-redirect';

// inside endSession, when !isPublicAuthPage:
window.location.href = buildLoginUrl(undefined, { reason });
```

(`buildLoginUrl(undefined)` uses current pathname+search.)

- [ ] **Step 2: Update `login/page.tsx`**

- Import `resolvePostLoginRedirect`, `stashOAuthReturnPath`, `isSafeReturnPath`
- Read `next` from `useSearchParams()`
- Already-authenticated + email success: `router.push(resolvePostLoginRedirect(next))`
- Google One-Tap success: `window.location.href = resolvePostLoginRedirect(next)`
- Before `window.location.href = data.authorization_url`: if `next` safe, `stashOAuthReturnPath(next)`

- [ ] **Step 3: Update `auth/callback/page.tsx`**

```typescript
import { consumeOAuthReturnPath, resolvePostLoginRedirect } from '@/lib/auth-redirect';
// on success:
window.location.href = resolvePostLoginRedirect(consumeOAuthReturnPath());
```

- [ ] **Step 4: Update `app/page.tsx` login redirect**

When `login=true`, build `/login` with forwarded `next` and `reason`:

```typescript
if (searchParams.get('login') === 'true') {
  const params = new URLSearchParams();
  const next = searchParams.get('next');
  const reason = searchParams.get('reason');
  if (next) params.set('next', next);
  if (reason) params.set('reason', reason);
  const qs = params.toString();
  router.push(qs ? `/login?${qs}` : '/login');
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/auth-session.ts frontend/src/app/login/page.tsx \
  frontend/src/app/auth/callback/page.tsx frontend/src/app/page.tsx
git commit -m "feat(auth): restore return path after login and OAuth"
```

---

### Task 3: Replace kick-to-login call sites

**Files:**
- Modify all files that `router.push('/?login=true')` (dashboard, bets, bet, chat, fantasy, help, leaderboard, parlays, predictions, predictions/stats, profile, upgrade, tools/*, Navigation, SportPredictionsPage, PlaceBetView, YetaiBetsView)

- [ ] **Step 1: Replace each occurrence**

```typescript
import { buildLoginUrl } from '@/lib/auth-redirect';
// ...
router.push(buildLoginUrl());
```

For Navigation Sign-in buttons that are intentional marketing-style entry (no protected target), `buildLoginUrl()` still works: current path if safe, else `/login` without `next`.

- [ ] **Step 2: Grep to confirm zero remaining `/?login=true` in `frontend/src`**

```bash
rg '/\?login=true' frontend/src
```

Expected: no matches

- [ ] **Step 3: Run unit tests + type-check + lint**

```bash
cd frontend && npm run test:unit -- src/lib/auth-redirect.test.ts && npm run type-check && npm run lint
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src
git commit -m "feat(auth): send protected routes to login with return path"
```

---

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| `?next=` + sessionStorage OAuth | 1–2 |
| Safe path validation | 1 |
| endSession preserves path | 2 |
| Login email + One-Tap + Google URL | 2 |
| Callback consume | 2 |
| Home forwards next/reason | 2 |
| Protected page call sites | 3 |
| Signup unchanged | (no change) |
| Unit tests | 1 |

## Execution

User requested build — execute inline (executing-plans) in this session.
