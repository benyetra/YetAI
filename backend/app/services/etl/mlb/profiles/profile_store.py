from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.mlb_profile_models import (
    MlbBatterProfileSnapshot,
    MlbPitcherProfileSnapshot,
)
from app.services.etl.mlb.profiles.constants import (
    PROFILE_VERSION,
    PROFILE_VERSION_PREV,
)


class ProfileStore:
    """Read API for versioned batter/pitcher profile snapshots."""

    def __init__(self, db: Session):
        self.db = db

    def get_pitcher(
        self,
        pitcher_id: int,
        as_of_date: date,
        window: str = "season",
        profile_version: str = PROFILE_VERSION,
    ) -> MlbPitcherProfileSnapshot | None:
        row = (
            self.db.query(MlbPitcherProfileSnapshot)
            .filter(
                MlbPitcherProfileSnapshot.pitcher_id == pitcher_id,
                MlbPitcherProfileSnapshot.window == window,
                MlbPitcherProfileSnapshot.profile_version == profile_version,
                MlbPitcherProfileSnapshot.as_of_date <= as_of_date,
            )
            .order_by(MlbPitcherProfileSnapshot.as_of_date.desc())
            .first()
        )
        if row is None and profile_version == PROFILE_VERSION:
            row = (
                self.db.query(MlbPitcherProfileSnapshot)
                .filter(
                    MlbPitcherProfileSnapshot.pitcher_id == pitcher_id,
                    MlbPitcherProfileSnapshot.window == window,
                    MlbPitcherProfileSnapshot.profile_version == PROFILE_VERSION_PREV,
                    MlbPitcherProfileSnapshot.as_of_date <= as_of_date,
                )
                .order_by(MlbPitcherProfileSnapshot.as_of_date.desc())
                .first()
            )
        return row

    def get_batter(
        self,
        batter_id: int,
        vs_hand: str,
        as_of_date: date,
        window: str = "season",
        profile_version: str = PROFILE_VERSION,
    ) -> MlbBatterProfileSnapshot | None:
        row = (
            self.db.query(MlbBatterProfileSnapshot)
            .filter(
                MlbBatterProfileSnapshot.batter_id == batter_id,
                MlbBatterProfileSnapshot.vs_hand == vs_hand,
                MlbBatterProfileSnapshot.window == window,
                MlbBatterProfileSnapshot.profile_version == profile_version,
                MlbBatterProfileSnapshot.as_of_date <= as_of_date,
            )
            .order_by(MlbBatterProfileSnapshot.as_of_date.desc())
            .first()
        )
        if row is None and profile_version == PROFILE_VERSION:
            row = (
                self.db.query(MlbBatterProfileSnapshot)
                .filter(
                    MlbBatterProfileSnapshot.batter_id == batter_id,
                    MlbBatterProfileSnapshot.vs_hand == vs_hand,
                    MlbBatterProfileSnapshot.window == window,
                    MlbBatterProfileSnapshot.profile_version == PROFILE_VERSION_PREV,
                    MlbBatterProfileSnapshot.as_of_date <= as_of_date,
                )
                .order_by(MlbBatterProfileSnapshot.as_of_date.desc())
                .first()
            )
        return row
