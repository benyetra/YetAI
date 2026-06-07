"""Tests for Sleeper draft pick resolution."""

from app.services.fantasy_draft_picks import (
    build_league_pick_registry,
    format_roster_tradeable_picks,
    infer_redraft_default_picks,
    lookup_pick_trade_value,
    merge_traded_and_default_picks,
    pick_owned_by_roster,
    stable_pick_id,
)


def _redraft_league(**overrides):
    base = {
        "season": "2025",
        "total_rosters": 2,
        "settings": {"type": 0, "draft_rounds": 2},
    }
    base.update(overrides)
    return base


def test_stable_pick_id_is_stable_for_slot():
    pid = stable_pick_id(2026, 1, 3)
    assert pid == stable_pick_id(2026, 1, 3)
    assert pid != stable_pick_id(2026, 2, 3)


def test_redraft_infers_default_picks_per_roster_slot():
    league = _redraft_league()
    defaults = infer_redraft_default_picks(league)
    assert len(defaults) == 4  # 2 rosters x 2 rounds
    owners = {(int(p["owner_id"]), int(p["round"])) for p in defaults}
    assert (1, 1) in owners
    assert (2, 2) in owners


def test_dynasty_uses_traded_picks_only():
    league = _redraft_league(settings={"type": 2, "draft_rounds": 3})
    traded = [{"season": "2026", "round": 1, "roster_id": 1, "owner_id": 2}]
    merged = merge_traded_and_default_picks(league, traded)
    assert len(merged) == 1


def test_redraft_merge_overlays_trades_on_defaults():
    league = _redraft_league()
    traded = [
        {
            "season": "2026",
            "round": 1,
            "roster_id": 1,
            "owner_id": 2,
            "previous_owner_id": 1,
        }
    ]
    merged = merge_traded_and_default_picks(league, traded)
    slot_one_r1 = next(
        p for p in merged if int(p["roster_id"]) == 1 and int(p["round"]) == 1
    )
    assert int(slot_one_r1["owner_id"]) == 2


def test_format_roster_tradeable_picks_redraft_defaults():
    league = _redraft_league()
    picks = format_roster_tradeable_picks(league, [], roster_id=1)
    assert len(picks) == 2
    assert all(p["roster_id"] == 1 for p in picks)
    assert all(p["trade_value"] > 0 for p in picks)


def test_pick_registry_lookup_and_ownership():
    league = _redraft_league()
    traded = [
        {
            "season": "2026",
            "round": 1,
            "roster_id": 1,
            "owner_id": 2,
            "previous_owner_id": 1,
        }
    ]
    registry = build_league_pick_registry(league, traded)
    pick_id = next(iter(registry))
    assert pick_owned_by_roster(pick_id, 2, registry)
    assert not pick_owned_by_roster(pick_id, 1, registry)
    assert lookup_pick_trade_value(pick_id, registry) > 0
