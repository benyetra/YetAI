from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base


@pytest.fixture
def session():
    from app.services.ballpark_pal.models import (
        BppGameSnapshot,
        BppMatchupSnapshot,
        BppParkFactorSnapshot,
        BppPlayerProjSnapshot,
    )

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            BppGameSnapshot.__table__,
            BppPlayerProjSnapshot.__table__,
            BppParkFactorSnapshot.__table__,
            BppMatchupSnapshot.__table__,
        ],
    )
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()


def test_game_snapshot_upsert_is_idempotent_and_updates_json(session):
    from app.services.ballpark_pal.models import BppGameSnapshot
    from app.services.ballpark_pal.store import (
        load_game_snapshot,
        upsert_game_snapshot,
    )

    slate_date = date(2026, 8, 5)
    common = {
        "team_away_id": 108,
        "team_home_id": 136,
        "as_of": datetime(2026, 8, 5, 16, tzinfo=timezone.utc),
    }
    upsert_game_snapshot(
        session,
        slate_date,
        776345,
        averages={"homeRuns": 4.1},
        probabilities={"homeWin": 52},
        **common,
    )
    upsert_game_snapshot(
        session,
        slate_date,
        776345,
        averages={"homeRuns": 4.8},
        probabilities={"homeWin": 57},
        **common,
    )
    session.commit()

    assert session.query(BppGameSnapshot).count() == 1
    row = load_game_snapshot(session, 776345, slate_date)
    assert row.averages_json == {"homeRuns": 4.8}
    assert row.probabilities_json == {"homeWin": 57}


def test_player_projection_upsert_loads_by_player_date_and_role(session):
    from app.services.ballpark_pal.models import BppPlayerProjSnapshot
    from app.services.ballpark_pal.store import load_player_proj, upsert_player_projs

    slate_date = date(2026, 8, 5)
    first = [
        {
            "player_id": 42,
            "team_id": 108,
            "role": "batter",
            "averages": {"hits": 1.1},
            "selected_probs": {"homeRunProbability": 4.2},
        },
        {
            "team_id": 108,
            "role": "team",
            "averages": {"runs": 4.3},
            "selected_probs": {},
        },
    ]
    second = [{**first[0], "averages": {"hits": 1.4}}]

    assert upsert_player_projs(session, slate_date, 776345, first) == 2
    assert upsert_player_projs(session, slate_date, 776345, second) == 1
    session.commit()

    assert session.query(BppPlayerProjSnapshot).count() == 2
    assert load_player_proj(session, 42, slate_date, "batter").averages_json == {
        "hits": 1.4
    }
    assert load_player_proj(session, 108, slate_date, "team") is not None


def test_load_player_proj_filters_by_game_pk_for_doubleheader(session):
    from app.services.ballpark_pal.store import load_player_proj, upsert_player_projs

    slate_date = date(2026, 8, 5)
    upsert_player_projs(
        session,
        slate_date,
        776345,
        [
            {
                "role": "batter",
                "player_id": 42,
                "team_id": 108,
                "averages": {"hits": 1.1},
            }
        ],
    )
    upsert_player_projs(
        session,
        slate_date,
        776999,
        [
            {
                "role": "batter",
                "player_id": 42,
                "team_id": 108,
                "averages": {"hits": 2.2},
            }
        ],
    )
    session.commit()

    g1 = load_player_proj(session, 42, slate_date, "batter", game_pk=776345)
    g2 = load_player_proj(session, 42, slate_date, "batter", bpp_game_id=776999)
    assert g1 is not None and g1.averages_json == {"hits": 1.1}
    assert g2 is not None and g2.averages_json == {"hits": 2.2}


def test_park_factor_upsert_loads_hitter_with_optional_game_filter(session):
    from app.services.ballpark_pal.models import BppParkFactorSnapshot
    from app.services.ballpark_pal.store import (
        load_hitter_park_factor,
        upsert_park_factors,
    )

    slate_date = date(2026, 8, 5)
    rows = [
        {"scope": "game", "factors": {"runsPercent": 18}},
        {
            "scope": "hitter",
            "player_id": 42,
            "factors": {"homeRuns": 1.12},
        },
    ]
    assert upsert_park_factors(session, slate_date, 776345, rows) == 2
    assert (
        upsert_park_factors(
            session,
            slate_date,
            776345,
            [{**rows[1], "factors": {"homeRuns": 1.2}}],
        )
        == 1
    )
    session.commit()

    assert session.query(BppParkFactorSnapshot).count() == 2
    row = load_hitter_park_factor(session, 42, slate_date, 776345)
    assert row.factors_json == {"homeRuns": 1.2}


def test_matchup_upsert_loads_unique_batter_pitcher_for_date(session):
    from app.services.ballpark_pal.models import BppMatchupSnapshot
    from app.services.ballpark_pal.store import load_matchup, upsert_matchups

    slate_date = date(2026, 8, 5)
    first = [{"batter_id": 42, "pitcher_id": 99, "probs": {"hitProbability": 24}}]
    second = [{"batter_id": 42, "pitcher_id": 99, "probs": {"hitProbability": 27}}]

    assert upsert_matchups(session, slate_date, 776345, first) == 1
    assert upsert_matchups(session, slate_date, 776345, second) == 1
    session.commit()

    assert session.query(BppMatchupSnapshot).count() == 1
    row = load_matchup(session, 42, 99, slate_date)
    assert row.probs_json == {"hitProbability": 27}
