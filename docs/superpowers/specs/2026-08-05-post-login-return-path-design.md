# Post-login return path

**Date:** 2026-08-05  
**Status:** Approved  
**Scope:** Frontend only (`frontend/`)

## Problem

When a session expires, an API returns `401`, or a logged-out user hits a protected page, YetAI sends them toward login via `/?login=true` (then `/login`) and, after successful auth, always lands them on `/dashboard`. The page they were on (or trying to open) is lost.

## Goals

- After **login** (email/password or Google), restore the user to the page that triggered authentication when a safe return path exists.
- Preserve path **and query string** (e.g. `/predictions?sport=mlb`).
- Default to `/dashboard` when no safe return path exists.
- Keep **signup** on `/dashboard` (no return-path behavior).

## Non-goals

- Encoding return path in Google OAuth `state` on the backend.
- Server-side auth middleware / route guards.
- Signup return path.
- Hash (`#fragment`) restoration.

## Approach

**Query param `?next=` + `sessionStorage` bridge for OAuth.**

1. Every kick-to-login builds `/login?next=<encoded relative path>` (optionally with `reason`).
2. Email/password success (and already-authenticated visit to `/login`) reads `next` and redirects to the validated path.
3. Before leaving for Google OAuth, stash the validated `next` in `sessionStorage`; `/auth/callback` consumes it once and redirects.

## Helpers

Add small pure helpers (prefer `frontend/src/lib/auth-redirect.ts`, imported from `auth-session` / login / callback as needed):

| Helper | Behavior |
|--------|----------|
| `isSafeReturnPath(path)` | Accept only same-origin relative paths starting with a single `/`. Reject `//`, schemes (`http:`, `javascript:`), backslashes, and auth/public-auth pages: `/`, `/login`, `/signup`, `/auth/callback`, `/verify-email`, `/forgot-password`, `/reset-password` (prefix-aware where those routes are nested). |
| `resolvePostLoginRedirect(next?)` | Return validated path or `/dashboard`. |
| `buildLoginUrl(returnPath?, options?)` | Build `/login?next=…`. Default `returnPath` = current `window.location.pathname + search`. Optionally forward `reason` (`expired` \| `unauthorized`). |
| `stashOAuthReturnPath(path)` / `consumeOAuthReturnPath()` | Write/read/clear `sessionStorage` key `yetai_auth_next`. Consume is one-shot. Only stash if `isSafeReturnPath` passes. |

## Data flow

```text
Protected page / endSession
  → buildLoginUrl(currentPath[+search][, reason])
  → /login?next=…[&reason=…]

Home /?login=true[&next=][&reason=]
  → forward next + reason to /login (do not drop return path)

Email login success / already authenticated on /login
  → resolvePostLoginRedirect(searchParams.next)
  → navigate there

Google Sign-in start
  → stashOAuthReturnPath(validated next)
  → OAuth redirect

/auth/callback success
  → consumeOAuthReturnPath() || '/dashboard'
  → window.location.href = destination

Signup success
  → /dashboard (unchanged)
```

### Call-site updates

- `endSession` in `auth-session.ts`: redirect with `buildLoginUrl` instead of bare `/?login=true&reason=…`.
- Replace scattered `router.push('/?login=true')` (protected pages, Navigation, etc.) with `buildLoginUrl()` / `router.push(buildLoginUrl())`.
- `app/page.tsx`: when mapping `login=true` → `/login`, forward `next` and `reason`.
- `app/login/page.tsx`: use `resolvePostLoginRedirect` for email success, already-authenticated effect, and in-page Google One-Tap success (reads `next` from the URL). Stash only when navigating away to Google’s `authorization_url` (full redirect flow).
- `app/auth/callback/page.tsx`: consume stash instead of hardcoding `/dashboard`.

## Edge cases

| Case | Result |
|------|--------|
| Missing or invalid `next` | `/dashboard` |
| `next` is an auth page | `/dashboard` |
| Marketing visit to `/login` with no `next` | `/dashboard` |
| Manual logout then Sign in with no `next` | `/dashboard` |
| OAuth stash missing/corrupt | `/dashboard` (no throw) |
| Query string on return path | Preserved |
| Hash | Ignored (v1) |

## Testing

Unit tests for helpers:

- Allow safe paths with and without query strings.
- Reject open-redirect shapes and auth pages.
- `buildLoginUrl` encodes `next` and optional `reason`.
- OAuth consume clears storage after read.

## Success criteria

- Session expiry on `/bets` → login → back on `/bets`.
- Cold open of `/predictions?sport=mlb` while logged out → login → same URL.
- Google login honors the same return path via sessionStorage.
- Plain `/login` with no `next` → `/dashboard`.
- Signup still → `/dashboard`.
