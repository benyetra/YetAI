# YetAI API documentation

Machine-readable OpenAPI specs and live Swagger UI for the YetAI backend (FastAPI).

## Spec files

| File | Audience | Description |
|------|----------|-------------|
| [openapi-public.json](./openapi-public.json) | Apps, partners, **AI agents** | Auth, bets, predictions, fantasy, subscriptions, odds |
| [openapi-admin.json](./openapi-admin.json) | Operators | `/api/admin/*`, Celery ops, pipelines, debug/test |
| [openapi.json](./openapi.json) | Full catalog | Union of public + admin + debug |

Regenerate after API changes:

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/export_openapi.py
```

## Live interactive docs

When the API is running:

| URL | UI |
|-----|-----|
| `/docs` | Swagger UI |
| `/redoc` | ReDoc |
| `/openapi.json` | Raw OpenAPI (enhanced metadata) |

Local default: `http://localhost:8000/docs`

Production: `https://api.yetai.app/docs` (if exposed; some deployments restrict admin routes).

## Authentication (agents & developers)

1. **Register or login**
   - `POST /api/auth/register` — body: email, username, password
   - `POST /api/auth/login` — body: `email_or_username`, `password`
2. Read `access_token` from the JSON response.
3. Send on protected routes:

```http
Authorization: Bearer <access_token>
```

Unauthenticated routes are listed in the public spec (health, login, register, odds, platform stats, Stripe webhook, etc.).

### Subscription tiers

- **Predictions** (`/api/v1/predictions/*`) require PRO or ELITE (`subscription_tier` on the user).
- **Admin** routes require `is_admin` on the user JWT.

## Using with AI agents

1. Load **`openapi-public.json`** as the tool/schema source (smaller, no admin noise).
2. Use **`operationId`** values as stable tool names (e.g. `auth_login_post`, `predictions_mlb_strikeouts_get`).
3. On **401**, re-authenticate via `/api/auth/login`.
4. On **403**, check tier (predictions) or admin flag.
5. On **503**, retry with backoff — a backing service is temporarily unavailable.

Extension fields:

- `x-audience` on each operation: `public` | `admin` | `debug`
- `info.x-authentication` — short auth summary
- `info.x-agent-documentation` — this file

## Tag overview (public spec)

| Tag | Domain |
|-----|--------|
| `auth` | JWT, OAuth, profile |
| `bets` | YetAI picks, user bets, live betting |
| `predictions` | MLB/NFL/NBA/NHL/WNBA ML tables |
| `fantasy` | Sleeper connect, leagues, recommendations |
| `fantasy-analytics` | Historical player analytics (`/api/v1/fantasy/analytics/*`) |
| `sleeper` | Sleeper sync (`/api/sleeper/*`) |
| `subscriptions` | Stripe checkout and webhooks |
| `tools` | Owen's Betting Corner |
| `odds` | Game odds |
| `users` | Profile, avatar, leaderboard |

## Admin spec

Use **`openapi-admin.json`** for back-office automation. Authenticate with an **admin** user JWT (same login flow as public).

Admin spec does not repeat auth endpoints; use the public spec or live `/docs` for `POST /api/auth/login`.

## CI

Backend CI runs `scripts/export_openapi.py` and `tests/test_openapi_export.py` to ensure the export succeeds and committed specs still cover the same route catalog (path counts and `operationId` coverage).
