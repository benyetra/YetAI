"""Classic NBA lottery odds + one-shot vault draft lottery."""

from __future__ import annotations

import random
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import league_vault_models as m
from app.services.league_vault.lottery.odds import (
    CLASSIC_NBA_COMBINATIONS,
    combinations_for_field,
    draw_weighted_order,
    odds_pct,
)
from app.services.league_vault.lottery.service import preview_lottery, run_lottery


def test_classic_combinations_sum_1000():
    assert sum(CLASSIC_NBA_COMBINATIONS) == 1000
    assert CLASSIC_NBA_COMBINATIONS[0] == 250


def test_combinations_for_field_scales_and_sums():
    six = combinations_for_field(6)
    assert len(six) == 6
    assert sum(six) == 1000
    assert six[0] > six[-1]
    assert combinations_for_field(0) == []


def test_draw_weighted_order_deterministic_with_seed():
    teams = ["A", "B", "C", "D"]
    odds = combinations_for_field(4)
    a = draw_weighted_order(teams, odds, lottery_picks=3, rng=random.Random(42))
    b = draw_weighted_order(teams, odds, lottery_picks=3, rng=random.Random(42))
    assert a == b
    assert sorted(a) == sorted(teams)
    assert len(set(a)) == 4


def test_odds_pct():
    assert odds_pct([250, 750]) == [25.0, 75.0]


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
            m.LvDraftLottery.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _seed_twelve_team_league(db):
    lineage = m.LvLeagueLineage(
        platform="sleeper",
        root_platform_league_id="root",
        season_league_ids={"2025": "L"},
        created_at=datetime.utcnow(),
    )
    db.add(lineage)
    db.flush()
    site = m.LvSite(
        lineage_id=lineage.id,
        slug="test-league",
        display_name="Test League",
        first_season=2025,
        latest_season=2025,
        is_public=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(site)
    managers = []
    for i in range(1, 13):
        mgr = m.LvManager(
            lineage_id=lineage.id,
            platform_user_id=f"u{i}",
            canonical_name=f"Manager{i}",
            display_name=f"Manager{i}",
            first_season=2025,
            last_season=2025,
            is_active=True,
        )
        db.add(mgr)
        managers.append(mgr)
    db.flush()
    season = m.LvSeason(
        lineage_id=lineage.id,
        season=2025,
        platform_league_id="L",
        team_count=12,
        playoff_teams=6,
        regular_season_weeks=14,
        champion_manager_id=managers[0].id,
        runner_up_manager_id=managers[1].id,
    )
    db.add(season)
    db.flush()
    teams = []
    for i, mgr in enumerate(managers):
        rank = i + 1
        team = m.LvTeam(
            season_id=season.id,
            manager_id=mgr.id,
            platform_roster_id=str(i),
            team_name=f"Team{i+1}",
            wins=12 - i,
            losses=i,
            ties=0,
            points_for=1500 - i * 10,
            points_against=1400,
            final_rank=rank,
            playoff_seed=rank if rank <= 6 else None,
        )
        db.add(team)
        teams.append(team)
    db.flush()
    # Playoff matchup so playoff set is clear
    db.add(
        m.LvMatchup(
            season_id=season.id,
            week=15,
            is_playoff=True,
            team_a_id=teams[0].id,
            team_b_id=teams[1].id,
            team_a_score=120,
            team_b_score=100,
            winner_team_id=teams[0].id,
            margin=20,
        )
    )
    db.commit()
    return site


def test_preview_and_run_lottery_once(db):
    site = _seed_twelve_team_league(db)
    preview = preview_lottery(db, site)
    assert preview["status"] == "ready"
    assert preview["source_season"] == 2025
    assert preview["upcoming_season"] == 2026
    assert len(preview["seed_snapshot"]["lottery_field"]) == 6
    assert len(preview["seed_snapshot"]["playoff_block"]) == 6
    assert preview["seed_snapshot"]["lottery_field"][0]["chance_pct"] > 0

    first = run_lottery(db, site)
    assert first["status"] == "drawn"
    assert first["already_drawn"] is False
    assert len(first["drawn_order"]) == 12
    assert first["drawn_order"][0]["pick"] == 1
    # Champion (Manager1) should be last among playoff block → overall last or near last
    last = first["drawn_order"][-1]
    assert last["group"] == "playoff"
    assert last["display_name"] == "Manager1"

    second = run_lottery(db, site)
    assert second["already_drawn"] is True
    assert second["drawn_order"] == first["drawn_order"]
    assert second["rng_seed"] == first["rng_seed"]

    again = preview_lottery(db, site)
    assert again["status"] == "drawn"
    assert again["drawn_order"] == first["drawn_order"]
