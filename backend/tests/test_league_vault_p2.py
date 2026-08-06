"""League Vault P2 — identity, all-play/luck, records, snapshot."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base


@pytest.fixture
def session():
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
        ],
    )
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()


def _seed_two_team_season(session):
    """Two managers, one season, three weeks of matchups for compute tests."""
    from app.models.league_vault_models import (
        LvLeagueLineage,
        LvManager,
        LvMatchup,
        LvSeason,
        LvSite,
        LvTeam,
    )

    lineage = LvLeagueLineage(
        platform="sleeper",
        root_platform_league_id="root1",
        season_league_ids={"2024": "L2024"},
        created_at=datetime.utcnow(),
    )
    session.add(lineage)
    session.flush()
    site = LvSite(
        lineage_id=lineage.id,
        slug="test-league",
        display_name="Test League",
        first_season=2024,
        latest_season=2024,
        is_public=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(site)
    session.flush()
    alice = LvManager(
        lineage_id=lineage.id,
        platform_user_id="alice",
        canonical_name="Alice",
        display_name="Alice",
        first_season=2024,
        last_season=2024,
        is_active=True,
    )
    bob = LvManager(
        lineage_id=lineage.id,
        platform_user_id="bob",
        canonical_name="Bob",
        display_name="BobAlias",
        first_season=2024,
        last_season=2024,
        is_active=True,
    )
    session.add_all([alice, bob])
    session.flush()
    season = LvSeason(
        lineage_id=lineage.id,
        season=2024,
        platform_league_id="L2024",
        team_count=2,
        playoff_teams=2,
        regular_season_weeks=3,
        champion_manager_id=alice.id,
        runner_up_manager_id=bob.id,
        last_place_manager_id=bob.id,
    )
    session.add(season)
    session.flush()
    t_a = LvTeam(
        season_id=season.id,
        manager_id=alice.id,
        platform_roster_id="1",
        team_name="Alice FC",
        wins=2,
        losses=1,
        ties=0,
        points_for=300.0,
        points_against=250.0,
        final_rank=1,
    )
    t_b = LvTeam(
        season_id=season.id,
        manager_id=bob.id,
        platform_roster_id="2",
        team_name="Bob FC",
        wins=1,
        losses=2,
        ties=0,
        points_for=250.0,
        points_against=300.0,
        final_rank=2,
    )
    session.add_all([t_a, t_b])
    session.flush()
    # Week 1: Alice 120, Bob 100 — Alice wins
    # Week 2: Alice 80, Bob 110 — Bob wins
    # Week 3: Alice 100, Bob 40 — Alice wins (blowout)
    weeks = [(1, 120.0, 100.0), (2, 80.0, 110.0), (3, 100.0, 40.0)]
    for week, sa, sb in weeks:
        winner = t_a.id if sa > sb else t_b.id
        session.add(
            LvMatchup(
                season_id=season.id,
                week=week,
                platform_matchup_id=str(week),
                is_playoff=False,
                team_a_id=t_a.id,
                team_b_id=t_b.id,
                team_a_score=sa,
                team_b_score=sb,
                winner_team_id=winner,
                margin=abs(sa - sb),
            )
        )
    session.commit()
    return {
        "lineage": lineage,
        "site": site,
        "alice": alice,
        "bob": bob,
        "season": season,
        "team_a": t_a,
        "team_b": t_b,
    }


def test_identity_override_renames_manager(session):
    from app.services.league_vault.identity.resolver import apply_identity_overrides

    seeded = _seed_two_team_season(session)
    report = apply_identity_overrides(
        session,
        lineage_id=seeded["lineage"].id,
        overrides=[
            {
                "platform_user_id": "bob",
                "canonical_name": "Robert",
                "display_name": "Robert",
                "merge_into_platform_user_id": None,
            }
        ],
    )
    session.refresh(seeded["bob"])
    assert seeded["bob"].canonical_name == "Robert"
    assert seeded["bob"].display_name == "Robert"
    assert report["updated"] == 1


def test_all_play_and_luck_populated(session):
    from app.services.league_vault.compute.standings import compute_all_play_for_lineage

    seeded = _seed_two_team_season(session)
    compute_all_play_for_lineage(session, seeded["lineage"].id)
    session.refresh(seeded["team_a"])
    session.refresh(seeded["team_b"])
    # 2 teams: each week all-play is just the head-to-head result
    assert seeded["team_a"].all_play_wins == 2
    assert seeded["team_a"].all_play_losses == 1
    assert seeded["team_b"].all_play_wins == 1
    assert seeded["team_b"].all_play_losses == 2
    assert seeded["team_a"].luck_differential is not None


def test_records_include_blowout_and_champ(session):
    from app.services.league_vault.compute.records import compute_records_for_lineage

    seeded = _seed_two_team_season(session)
    records = compute_records_for_lineage(session, seeded["lineage"].id)
    keys = {r.record_key for r in records}
    assert "highest_single_week_score" in keys
    assert "biggest_blowout" in keys
    assert "titles" in keys
    blowout = next(r for r in records if r.record_key == "biggest_blowout")
    assert blowout.value == 60.0
    assert blowout.context.get("manager_a_id") == seeded["alice"].id
    assert blowout.context.get("manager_b_id") == seeded["bob"].id
    closest = next(r for r in records if r.record_key == "closest_game")
    assert closest.context.get("manager_a_id") is not None
    assert closest.context.get("manager_b_id") is not None
    titles = next(r for r in records if r.record_key == "titles")
    assert titles.manager_id == seeded["alice"].id
    assert titles.value == 1.0


def test_snapshot_contains_pages_payload(session):
    from app.services.league_vault.compute.records import compute_records_for_lineage
    from app.services.league_vault.compute.standings import compute_all_play_for_lineage
    from app.services.league_vault.publish.snapshot import build_site_snapshot

    seeded = _seed_two_team_season(session)
    compute_all_play_for_lineage(session, seeded["lineage"].id)
    compute_records_for_lineage(session, seeded["lineage"].id)
    snap = build_site_snapshot(session, slug="test-league")
    assert snap["slug"] == "test-league"
    assert snap["display_name"] == "Test League"
    assert len(snap["seasons"]) == 1
    assert snap["seasons"][0]["champion"]["display_name"] == "Alice"
    assert "records" in snap
    assert "managers" in snap
    assert "h2h" in snap
    closest = next(r for r in snap["records"] if r["record_key"] == "closest_game")
    assert closest["context"]["manager_a_id"] == seeded["alice"].id
    assert closest["context"]["manager_b_id"] == seeded["bob"].id
    # No PII
    blob = str(snap)
    assert "alice" not in blob or "platform_user_id" not in blob


def test_snapshot_draft_picks_include_team_and_player(session):
    from app.models.league_vault_models import LvDraft, LvDraftPick
    from app.services.league_vault.publish.snapshot import build_site_snapshot

    seeded = _seed_two_team_season(session)
    draft = LvDraft(
        season_id=seeded["season"].id,
        platform_draft_id="d1",
        draft_type="snake",
        settings={"status": "complete"},
    )
    session.add(draft)
    session.flush()
    session.add_all(
        [
            LvDraftPick(
                draft_id=draft.id,
                round=1,
                pick_no=1,
                draft_slot=1,
                team_id=seeded["team_a"].id,
                player_id="4866",
            ),
            LvDraftPick(
                draft_id=draft.id,
                round=1,
                pick_no=2,
                draft_slot=2,
                team_id=seeded["team_b"].id,
                player_id="7588",
            ),
        ]
    )
    session.commit()

    snap = build_site_snapshot(session, slug="test-league")
    draft_out = snap["seasons"][0]["drafts"][0]
    picks = draft_out["picks"]
    assert len(picks) == 2
    assert picks[0]["team_id"] == seeded["team_a"].id
    assert picks[0]["player_id"] == "4866"
    assert picks[1]["team_id"] == seeded["team_b"].id
    assert picks[1]["player_id"] == "7588"
    assert "player_name" in picks[0]
    assert draft_out["status"] == "complete"
    assert draft_out["picks_made"] == 2


def test_snapshot_pending_draft_strips_placeholder_player_ids(session):
    from app.models.league_vault_models import LvDraft, LvDraftPick
    from app.services.league_vault.publish.snapshot import build_site_snapshot

    seeded = _seed_two_team_season(session)
    draft = LvDraft(
        season_id=seeded["season"].id,
        platform_draft_id="d-pending",
        draft_type="snake",
        settings={"status": "pending"},
    )
    session.add(draft)
    session.flush()
    session.add_all(
        [
            LvDraftPick(
                draft_id=draft.id,
                round=1,
                pick_no=1,
                draft_slot=1,
                team_id=seeded["team_a"].id,
                player_id="-1",
            ),
            LvDraftPick(
                draft_id=draft.id,
                round=1,
                pick_no=2,
                draft_slot=2,
                team_id=seeded["team_b"].id,
                player_id="-1",
            ),
        ]
    )
    session.commit()

    snap = build_site_snapshot(session, slug="test-league")
    draft_out = snap["seasons"][0]["drafts"][0]
    assert draft_out["status"] == "pending"
    assert draft_out["picks_made"] == 0
    assert all(p["player_id"] is None for p in draft_out["picks"])
    assert len(draft_out["picks"]) == 2


def test_snapshot_transaction_summary(session):
    from app.models.league_vault_models import LvTransaction
    from app.services.league_vault.publish.snapshot import build_site_snapshot

    seeded = _seed_two_team_season(session)
    session.add_all(
        [
            LvTransaction(
                season_id=seeded["season"].id,
                week=3,
                platform_transaction_id="t1",
                type="trade",
                status="complete",
                team_ids=["1", "2"],
            ),
            LvTransaction(
                season_id=seeded["season"].id,
                week=4,
                platform_transaction_id="t2",
                type="waiver",
                status="complete",
                team_ids=["1"],
            ),
            LvTransaction(
                season_id=seeded["season"].id,
                week=5,
                platform_transaction_id="t3",
                type="waiver",
                status="complete",
                team_ids=["2"],
            ),
        ]
    )
    session.commit()

    snap = build_site_snapshot(session, slug="test-league")
    season = snap["seasons"][0]
    assert season["transaction_count"] == 3
    assert season["transaction_summary"]["trade"] == 1
    assert season["transaction_summary"]["waiver"] == 2
    assert len(season["transactions_recent"]) == 3
    assert any(
        "Alice FC" in (r.get("team_names") or []) for r in season["transactions_recent"]
    )
