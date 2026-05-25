# YetAI OpenAPI / Swagger design

**Date:** 2026-05-25  
**Status:** Approved (user: "go with your best recommendation")

## Goal

Provide Swagger/OpenAPI documentation for all YetAI APIs so developers and AI agents can discover, authenticate, and call endpoints without guessing.

## Decision summary

| Choice | Selection |
|--------|-----------|
| Spec split | **Two published specs** — `openapi-public.json` + `openapi-admin.json` |
| Implementation | **Enhance FastAPI in-place** (no full `main.py` router split in v1) |
| Artifacts | Committed under `docs/api/`, regenerated via `scripts/export_openapi.py` |
| Live UI | `/docs` (Swagger) + `/redoc` (ReDoc) |

## Architecture

- `app/openapi_config.py` — custom `openapi()` hook: tags, `operationId`, JWT security, error schemas, `x-audience`
- Path classification: `public` | `admin` | `debug` from URL prefix
- Mount previously orphaned routers: `fantasy_analytics` (`/api/v1/fantasy/analytics`), `sleeper_sync` (`/api/sleeper`)
- Agent guide: `docs/api/README.md`

## Out of scope (v1)

- Refactoring ~100 routes out of `main.py` into domain routers
- MCP server wrapper
- Hand-maintained YAML separate from code

## Verification

- `pytest tests/test_openapi_export.py`
- CI: export script + `git diff` on `docs/api/`
