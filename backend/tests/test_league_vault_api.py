"""Public /api/vault/* — no auth, no PII."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.api.vault import router


@pytest.fixture
def client_and_db():
    from app.models import league_vault_events as ev
    from app.models import league_vault_models as m

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
            m.LvTransaction.__table__,
            m.LvDraft.__table__,
            m.LvDraftPick.__table__,
            m.LvRecord.__table__,
            m.LvSyncJob.__table__,
            ev.LvVaultEvent.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    db = Session()

    lineage = m.LvLeagueLineage(
        platform="sleeper",
        root_platform_league_id="r1",
        season_league_ids={"2024": "L"},
        created_at=datetime.utcnow(),
    )
    db.add(lineage)
    db.flush()
    site = m.LvSite(
        lineage_id=lineage.id,
        slug="mikes-hard",
        display_name="Mike's Hard",
        first_season=2024,
        latest_season=2024,
        is_public=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(site)
    mgr = m.LvManager(
        lineage_id=lineage.id,
        platform_user_id="secret-user-id-xyz",
        canonical_name="Alice",
        display_name="Alice",
        first_season=2024,
        last_season=2024,
        is_active=True,
    )
    db.add(mgr)
    db.flush()
    season = m.LvSeason(
        lineage_id=lineage.id,
        season=2024,
        platform_league_id="L",
        team_count=1,
        champion_manager_id=mgr.id,
    )
    db.add(season)
    db.commit()

    app = FastAPI()
    app.include_router(router)

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    client = TestClient(app)
    try:
        yield client, db, mgr
    finally:
        db.close()


def test_vault_meta_public(client_and_db):
    client, _db, _mgr = client_and_db
    r = client.get("/api/vault/mikes-hard/meta")
    assert r.status_code == 200
    assert r.json()["slug"] == "mikes-hard"
    assert r.json()["display_name"] == "Mike's Hard"


def test_vault_snapshot_hides_platform_user_id(client_and_db):
    client, _db, mgr = client_and_db
    r = client.get("/api/vault/mikes-hard")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "mikes-hard"
    assert "platform_user_id" not in str(body)
    assert mgr.platform_user_id not in str(body)
    assert "Cache-Control" in r.headers


def test_vault_404(client_and_db):
    client, _db, _mgr = client_and_db
    assert client.get("/api/vault/nope").status_code == 404


def test_vault_event_and_stats(client_and_db):
    client, _db, _mgr = client_and_db
    r = client.post(
        "/api/vault/mikes-hard/events",
        json={"path": "/vault/mikes-hard/records", "event_type": "page_view"},
    )
    assert r.status_code == 204
    stats = client.get("/api/vault/mikes-hard/stats")
    assert stats.status_code == 200
    body = stats.json()
    assert body["total_events"] >= 1
    assert "/vault/mikes-hard/records" in body["by_path"]
