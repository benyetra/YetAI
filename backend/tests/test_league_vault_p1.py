"""League Vault P1 unit tests (SQLite StaticPool, inline Sleeper fixtures)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.league_vault_models import (
    LvLeagueLineage,
    LvManager,
    LvSeason,
    LvSite,
    LvTeam,
)
from app.services.league_vault.ingest.normalizer import (
    get_or_create_lineage_and_site,
    normalize_sleeper_season,
)


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        LvLeagueLineage.__table__,
        LvSite.__table__,
        LvManager.__table__,
        LvSeason.__table__,
        LvTeam.__table__,
    ]
    from app.models.league_vault_models import (
        LvDraft,
        LvDraftPick,
        LvMatchup,
        LvRecord,
        LvSyncJob,
        LvTransaction,
    )

    tables.extend(
        [
            LvMatchup.__table__,
            LvTransaction.__table__,
            LvDraft.__table__,
            LvDraftPick.__table__,
            LvRecord.__table__,
            LvSyncJob.__table__,
        ]
    )
    Base.metadata.create_all(engine, tables=tables)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()


def test_lineage_and_site_round_trip(session):
    lineage, site = get_or_create_lineage_and_site(
        session,
        platform="sleeper",
        root_platform_league_id="root-123",
        slug="test-league",
        display_name="Test League",
        tagline="For testing",
        last_place_label="Sacko",
    )
    session.commit()

    loaded_lineage = (
        session.query(LvLeagueLineage)
        .filter(LvLeagueLineage.root_platform_league_id == "root-123")
        .one()
    )
    loaded_site = session.query(LvSite).filter(LvSite.slug == "test-league").one()

    assert loaded_lineage.platform == "sleeper"
    assert loaded_site.display_name == "Test League"
    assert loaded_site.lineage_id == loaded_lineage.id
    assert loaded_site.last_place_label == "Sacko"


def test_normalize_sleeper_season_writes_12_teams(session):
    """Minimal inline Sleeper payload (2 teams) — no external fixtures required."""
    lineage, site = get_or_create_lineage_and_site(
        session,
        platform="sleeper",
        root_platform_league_id="inline-root",
        slug="inline-sleeper",
        display_name="Inline Sleeper",
    )

    league = {
        "league_id": "L1",
        "season": "2024",
        "total_rosters": 2,
        "settings": {"reg_season_count": 1, "playoff_teams": 2},
        "roster_positions": ["QB", "RB", "WR", "FLEX"],
    }
    users = [
        {"user_id": "u1", "display_name": "Alice", "avatar": "av1"},
        {"user_id": "u2", "display_name": "Bob", "avatar": "av2"},
    ]
    rosters = [
        {
            "roster_id": 1,
            "owner_id": "u1",
            "settings": {
                "wins": 1,
                "losses": 0,
                "ties": 0,
                "fpts": 100,
                "fpts_decimal": 50,
                "fpts_against": 90,
                "fpts_against_decimal": 0,
                "rank": 1,
            },
        },
        {
            "roster_id": 2,
            "owner_id": "u2",
            "settings": {
                "wins": 0,
                "losses": 1,
                "ties": 0,
                "fpts": 90,
                "fpts_decimal": 0,
                "fpts_against": 100,
                "fpts_against_decimal": 50,
                "rank": 2,
            },
        },
    ]
    matchups_by_week = {
        1: [
            {"matchup_id": 1, "roster_id": 1, "points": 105.5},
            {"matchup_id": 1, "roster_id": 2, "points": 98.0},
        ],
    }
    drafts = [
        {
            "draft_id": "d1",
            "type": "snake",
            "status": "complete",
            "picks": [
                {"round": 1, "pick_no": 1, "roster_id": 1, "player_id": "p1"},
                {"round": 1, "pick_no": 2, "roster_id": 2, "player_id": "p2"},
            ],
        }
    ]
    winners_bracket = [{"p": 1, "r": 1, "w": 1}]

    result = normalize_sleeper_season(
        session,
        lineage=lineage,
        site=site,
        season=2024,
        platform_league_id="L1",
        league=league,
        rosters=rosters,
        users=users,
        matchups_by_week=matchups_by_week,
        drafts=drafts,
        transactions=[],
        winners_bracket=winners_bracket,
    )
    session.commit()

    assert result["team_count"] == 2
    assert result["matchup_count"] >= 1
    assert result["draft_pick_count"] == 2
    assert result["manager_count"] == 2

    teams = session.query(LvTeam).join(LvSeason).filter(LvSeason.season == 2024).all()
    assert len(teams) == 2
    assert any(t.points_for == 100.5 for t in teams)

    season_row = session.query(LvSeason).filter(LvSeason.season == 2024).one()
    assert season_row.champion_manager_id is not None

    mgrs = session.query(LvManager).filter(LvManager.lineage_id == lineage.id).all()
    assert len(mgrs) == 2
