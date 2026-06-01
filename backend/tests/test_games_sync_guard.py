"""Tests for the startup games-sync guard.

The API process can restart frequently (deploys, health checks, replica
cycling). The startup hook calls ``run_games_sync(force=False)``, which must
skip the ~12-credit Odds API pull when a sync completed within the cooldown
window. Celery beat / admin paths call with ``force=True`` and always sync.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import games_sync_service as gss


def _patch_common(stack, *, marker):
    """Patch cache + db + the actual sync so we can assert call behavior."""
    cache = MagicMock()
    cache.get = AsyncMock(return_value=marker)
    cache.set = AsyncMock()
    # run_games_sync imports the singleton lazily from this module.
    stack.enter_context(patch("app.services.cache_service.cache_service", cache))
    stack.enter_context(patch.object(gss, "get_db", return_value=iter([MagicMock()])))
    sync = stack.enter_context(
        patch.object(
            gss.GamesSyncService,
            "sync_all_games",
            new=AsyncMock(return_value={"total_games_fetched": 5}),
        )
    )
    return cache, sync


def test_startup_skips_when_recent_marker_present():
    from contextlib import ExitStack

    with ExitStack() as stack:
        cache, sync = _patch_common(stack, marker={"at": "2026-06-01T13:00:00+00:00"})
        result = asyncio.run(gss.run_games_sync(force=False))

    assert result["status"] == "skipped"
    assert result["reason"] == "recent_sync"
    sync.assert_not_called()  # no Odds API pull
    cache.set.assert_not_awaited()


def test_startup_runs_and_sets_marker_when_no_recent_sync():
    from contextlib import ExitStack

    with ExitStack() as stack:
        cache, sync = _patch_common(stack, marker=None)
        result = asyncio.run(gss.run_games_sync(force=False))

    assert result["total_games_fetched"] == 5
    sync.assert_awaited_once()
    cache.set.assert_awaited_once()  # marker written for next restart


def test_force_true_ignores_marker():
    from contextlib import ExitStack

    with ExitStack() as stack:
        cache, sync = _patch_common(stack, marker={"at": "2026-06-01T13:00:00+00:00"})
        asyncio.run(gss.run_games_sync(force=True))

    sync.assert_awaited_once()  # beat/admin always sync
    cache.set.assert_awaited_once()
