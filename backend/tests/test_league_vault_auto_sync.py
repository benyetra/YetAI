"""League Vault weekly refresh + stale recompute."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import league_vault_models as m
from app.services.league_vault.compute.ensure import (
    ensure_pilot_computed,
    records_stale_after_sync,
)
from app.services.league_vault.sync.refresh import (
    auto_sync_enabled,
    discover_sleeper_successor_tip,
    refresh_all_public_sites,
    refresh_site,
    sleeper_tip_from_season_map,
    sleeper_tip_league_id,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            m.LvLeagueLineage.__table__,
            m.LvSite.__table__,
            m.LvManager.__table__,
            m.LvSeason.__table__,
            m.LvTeam.__table__,
            m.LvMatchup.__table__,
            m.LvRecord.__table__,
            m.LvSyncJob.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _seed_site(db, *, platform="sleeper", slug="mikes-hard"):
    lineage = m.LvLeagueLineage(
        platform=platform,
        root_platform_league_id="root-1",
        season_league_ids={"2023": "old-tip", "2024": "tip-2024"},
        created_at=datetime.utcnow(),
        last_synced=datetime.utcnow() - timedelta(days=7),
    )
    db.add(lineage)
    db.flush()
    site = m.LvSite(
        lineage_id=lineage.id,
        slug=slug,
        display_name="Test League",
        first_season=2023,
        latest_season=2024,
        is_public=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(site)
    mgr = m.LvManager(
        lineage_id=lineage.id,
        platform_user_id="u1",
        canonical_name="Alice",
        display_name="Alice",
        first_season=2023,
        last_season=2024,
        is_active=True,
    )
    db.add(mgr)
    db.flush()
    season = m.LvSeason(
        lineage_id=lineage.id,
        season=2024,
        platform_league_id="tip-2024",
        team_count=2,
        champion_manager_id=mgr.id,
    )
    db.add(season)
    db.flush()
    team = m.LvTeam(
        season_id=season.id,
        manager_id=mgr.id,
        platform_roster_id="1",
        team_name="Aces",
        wins=1,
        losses=0,
        ties=0,
        points_for=100.0,
        points_against=80.0,
        final_rank=1,
    )
    db.add(team)
    db.commit()
    return site, lineage, mgr, season


def test_sleeper_tip_from_season_map_picks_newest():
    assert sleeper_tip_from_season_map({"2021": "a", "2024": "z", "2022": "b"}) == "z"
    assert sleeper_tip_from_season_map({}) is None


def test_discover_sleeper_successor_tip():
    client = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = [
        {"league_id": "tip-2025", "previous_league_id": "tip-2024"},
    ]
    resp.raise_for_status = MagicMock()
    client.get.return_value = resp
    found = discover_sleeper_successor_tip(
        client,
        tip_league_id="tip-2024",
        manager_platform_ids=["u1"],
        season_year=2025,
    )
    assert found == "tip-2025"


def test_sleeper_tip_league_id_uses_stored_tip(db):
    site, lineage, _mgr, _season = _seed_site(db)
    with patch(
        "app.services.league_vault.sync.refresh.discover_sleeper_successor_tip",
        return_value=None,
    ):
        tip = sleeper_tip_league_id(db, site, lineage)
    assert tip == "tip-2024"


def test_records_stale_after_sync(db):
    site, lineage, _mgr, _season = _seed_site(db)
    assert records_stale_after_sync(db, lineage.id) is True  # no records yet

    older = datetime.utcnow() - timedelta(days=2)
    newer = datetime.utcnow() - timedelta(hours=1)
    db.add(
        m.LvRecord(
            lineage_id=lineage.id,
            record_key="career_wins",
            scope="career",
            season=None,
            manager_id=None,
            team_id=None,
            value=1,
            context={},
            computed_at=newer,
        )
    )
    lineage.last_synced = older
    db.commit()
    assert records_stale_after_sync(db, lineage.id) is False

    lineage.last_synced = datetime.utcnow()
    db.commit()
    assert records_stale_after_sync(db, lineage.id) is True


def test_ensure_recomputes_when_stale(db):
    site, lineage, mgr, season = _seed_site(db)
    db.add(
        m.LvRecord(
            lineage_id=lineage.id,
            record_key="career_wins",
            scope="career",
            season=None,
            manager_id=mgr.id,
            team_id=None,
            value=1,
            context={},
            computed_at=datetime.utcnow() - timedelta(days=3),
        )
    )
    lineage.last_synced = datetime.utcnow()
    db.commit()

    with (
        patch(
            "app.services.league_vault.compute.ensure.compute_all_play_for_lineage",
            return_value={"teams": 1},
        ) as ap,
        patch(
            "app.services.league_vault.compute.ensure.compute_records_for_lineage",
            return_value=[object(), object()],
        ) as rec,
        patch("app.services.league_vault.compute.ensure.heal_site_branding"),
        patch("app.services.league_vault.compute.ensure.heal_manager_display_names"),
    ):
        out = ensure_pilot_computed(db, site, force=False)
    assert out["skipped"] is False
    assert out.get("stale") is True
    ap.assert_called_once()
    rec.assert_called_once()


def test_ensure_skips_when_fresh(db):
    site, lineage, mgr, _season = _seed_site(db)
    now = datetime.utcnow()
    db.add(
        m.LvRecord(
            lineage_id=lineage.id,
            record_key="career_wins",
            scope="career",
            season=None,
            manager_id=mgr.id,
            team_id=None,
            value=1,
            context={},
            computed_at=now,
        )
    )
    lineage.last_synced = now - timedelta(hours=1)
    db.commit()

    with (
        patch(
            "app.services.league_vault.compute.ensure.compute_all_play_for_lineage"
        ) as ap,
        patch(
            "app.services.league_vault.compute.ensure.compute_records_for_lineage"
        ) as rec,
        patch("app.services.league_vault.compute.ensure.heal_site_branding"),
        patch("app.services.league_vault.compute.ensure.heal_manager_display_names"),
    ):
        out = ensure_pilot_computed(db, site, force=False)
    assert out["skipped"] is True
    ap.assert_not_called()
    rec.assert_not_called()


def test_refresh_site_calls_ingest_then_force_compute(db):
    site, _lineage, _mgr, _season = _seed_site(db)
    with (
        patch(
            "app.services.league_vault.sync.refresh.ingest_sleeper_league",
            return_value={"seasons": [{"season": 2024}]},
        ) as ingest,
        patch(
            "app.services.league_vault.sync.refresh.ensure_pilot_computed",
            return_value={"skipped": False, "records": 3},
        ) as ensure,
        patch(
            "app.services.league_vault.sync.refresh.sleeper_tip_league_id",
            return_value="tip-2024",
        ),
    ):
        out = refresh_site(db, site, reingest=True, force_compute=True)
    ingest.assert_called_once()
    ensure.assert_called_once()
    assert ensure.call_args.kwargs.get("force") is True
    assert out["slug"] == "mikes-hard"


def test_refresh_all_public_sites_continues_on_error(db):
    _seed_site(db, slug="a")
    _seed_site(db, slug="b", platform="espn")
    # second site espn — make sure both exist as public
    calls = {"n": 0}

    def _boom(db, site, **kwargs):
        calls["n"] += 1
        if site.slug == "a":
            raise RuntimeError("fail a")
        return {"slug": site.slug, "ok": True}

    with patch(
        "app.services.league_vault.sync.refresh.refresh_site",
        side_effect=_boom,
    ):
        summary = refresh_all_public_sites(db)
    assert summary["sites"] == 2
    assert summary["errors"] == 1
    assert summary["ok"] == 1


def test_auto_sync_enabled_env(monkeypatch):
    monkeypatch.delenv("LEAGUE_VAULT_AUTO_SYNC", raising=False)
    assert auto_sync_enabled() is True
    monkeypatch.setenv("LEAGUE_VAULT_AUTO_SYNC", "false")
    assert auto_sync_enabled() is False
    monkeypatch.setenv("LEAGUE_VAULT_AUTO_SYNC", "1")
    assert auto_sync_enabled() is True


def test_celery_task_respects_disable(monkeypatch):
    monkeypatch.setenv("LEAGUE_VAULT_AUTO_SYNC", "false")
    from app.tasks.league_vault_sync import sync_all_vault_sites

    out = sync_all_vault_sites()
    assert out["status"] == "skipped"
