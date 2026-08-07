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
from app.services.league_vault.lottery.seed import build_seed_snapshot
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
    """
    12-team league where final_rank is regular-season standing (not playoff
    finish), playoff_seed is unset, and playoff weeks include toilet-bowl
    games for non-playoff teams — matching Sleeper Mike's Hard 2025 shape.

    Playoff field (top 6 by RS): seed order 1..6 = Mgr1..Mgr6
    Results: Mgr5 champ, Mgr2 runner-up, Mgr3 3rd, Mgr1 4th, Mgr6 5th, Mgr4 6th
    """
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
        champion_manager_id=managers[4].id,  # Manager5
        runner_up_manager_id=managers[1].id,  # Manager2
    )
    db.add(season)
    db.flush()
    teams = []
    for i, mgr in enumerate(managers):
        rank = i + 1
        team = m.LvTeam(
            season_id=season.id,
            manager_id=mgr.id,
            platform_roster_id=str(i + 1),
            team_name=f"Team{i+1}",
            wins=12 - i,
            losses=i,
            ties=0,
            points_for=1500 - i * 10,
            points_against=1400,
            final_rank=rank,  # regular-season standing only
            playoff_seed=None,
        )
        db.add(team)
        teams.append(team)
    db.flush()

    def add_game(week, a_idx, b_idx, winner_idx):
        db.add(
            m.LvMatchup(
                season_id=season.id,
                week=week,
                is_playoff=True,
                team_a_id=teams[a_idx].id,
                team_b_id=teams[b_idx].id,
                team_a_score=120 if winner_idx == a_idx else 100,
                team_b_score=120 if winner_idx == b_idx else 100,
                winner_team_id=teams[winner_idx].id,
                margin=20,
            )
        )

    # Round 1 (seeds 3/6 and 4/5); 1 & 2 on bye
    add_game(15, 2, 5, 2)  # Mgr3 beat Mgr6
    add_game(15, 4, 3, 4)  # Mgr5 beat Mgr4
    # Semis
    add_game(16, 2, 1, 1)  # Mgr2 beat Mgr3
    add_game(16, 0, 4, 4)  # Mgr5 beat Mgr1
    # 5th place
    add_game(16, 3, 5, 5)  # Mgr6 beat Mgr4 → 5th / 6th
    # Championship + 3rd place
    add_game(17, 4, 1, 4)  # Mgr5 beat Mgr2 → champ / runner
    add_game(17, 2, 0, 2)  # Mgr3 beat Mgr1 → 3rd / 4th
    # Toilet bowl (must NOT pull these into playoff field)
    add_game(15, 6, 11, 6)
    add_game(16, 7, 10, 7)
    add_game(17, 8, 9, 8)

    db.commit()
    return site, season, teams, managers


def test_preview_and_run_lottery_once(db):
    site, _, _, _ = _seed_twelve_team_league(db)
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
    # Champion (Manager5) last overall
    last = first["drawn_order"][-1]
    assert last["group"] == "playoff"
    assert last["display_name"] == "Manager5"
    assert last["playoff_finish"] == 1

    second = run_lottery(db, site)
    assert second["already_drawn"] is True
    assert second["drawn_order"] == first["drawn_order"]
    assert second["rng_seed"] == first["rng_seed"]

    again = preview_lottery(db, site)
    assert again["status"] == "drawn"
    assert again["drawn_order"] == first["drawn_order"]


def test_playoff_block_uses_results_not_regular_season_rank(db):
    _, season, _, _ = _seed_twelve_team_league(db)
    snap = build_seed_snapshot(db, season)

    lottery_names = [e["display_name"] for e in snap["lottery_field"]]
    assert lottery_names == [
        "Manager12",
        "Manager11",
        "Manager10",
        "Manager9",
        "Manager8",
        "Manager7",
    ]

    # Reverse playoff finish: 6th → … → champion
    playoff_names = [e["display_name"] for e in snap["playoff_block"]]
    assert playoff_names == [
        "Manager4",  # 6th
        "Manager6",  # 5th
        "Manager1",  # 4th (RS #1 seed, lost 3rd-place game)
        "Manager3",  # 3rd
        "Manager2",  # runner-up
        "Manager5",  # champion
    ]
    finishes = [e["playoff_finish"] for e in snap["playoff_block"]]
    assert finishes == [6, 5, 4, 3, 2, 1]


def test_winners_bracket_place_games_override_standings(db):
    """When bracket place games exist, use p=1/3/5 — not final_rank."""
    _, season, teams, _ = _seed_twelve_team_league(db)
    # Clear weekly playoff games among top 6; add explicit winners-bracket places
    db.query(m.LvMatchup).filter_by(season_id=season.id).delete()
    # p=1 title: Manager5 over Manager2
    db.add(
        m.LvMatchup(
            season_id=season.id,
            week=3,
            is_playoff=True,
            bracket="winners",
            playoff_round=1,
            team_a_id=teams[4].id,
            team_b_id=teams[1].id,
            winner_team_id=teams[4].id,
            team_a_score=110,
            team_b_score=100,
            margin=10,
        )
    )
    # p=3: Manager3 over Manager1
    db.add(
        m.LvMatchup(
            season_id=season.id,
            week=3,
            is_playoff=True,
            bracket="winners",
            playoff_round=3,
            team_a_id=teams[2].id,
            team_b_id=teams[0].id,
            winner_team_id=teams[2].id,
            team_a_score=110,
            team_b_score=100,
            margin=10,
        )
    )
    # p=5: Manager6 over Manager4
    db.add(
        m.LvMatchup(
            season_id=season.id,
            week=2,
            is_playoff=True,
            bracket="winners",
            playoff_round=5,
            team_a_id=teams[5].id,
            team_b_id=teams[3].id,
            winner_team_id=teams[5].id,
            team_a_score=110,
            team_b_score=100,
            margin=10,
        )
    )
    db.commit()

    snap = build_seed_snapshot(db, season)
    assert [e["display_name"] for e in snap["playoff_block"]] == [
        "Manager4",
        "Manager6",
        "Manager1",
        "Manager3",
        "Manager2",
        "Manager5",
    ]
