from app.models.mlb_profile_models import (
    MlbBatterProfileSnapshot,
    MlbPitcherProfileSnapshot,
)


def test_batter_snapshot_tablename():
    assert MlbBatterProfileSnapshot.__tablename__ == "mlb_batter_profile_snapshots"


def test_pitcher_snapshot_tablename():
    assert MlbPitcherProfileSnapshot.__tablename__ == "mlb_pitcher_profile_snapshots"
