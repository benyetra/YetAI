"""Batter archetypes for cold-start profile priors (Phase 6)."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.mlb_archetype_models import MlbPlayerArchetype
from app.services.etl.mlb.profiles.constants import LEAGUE_WHIFF_BY_PITCH, PITCH_TYPES

# League-tier archetype priors (whiff rate by pitch type).
ARCHETYPE_PRIORS: dict[str, dict[str, float]] = {
    "power_rhb": {
        "FF": 0.26,
        "SL": 0.30,
        "CH": 0.28,
        "SI": 0.22,
        "FC": 0.25,
        "CU": 0.27,
        "KC": 0.26,
        "FS": 0.29,
        "ST": 0.31,
        "UNK": 0.25,
    },
    "contact_rhb": {
        "FF": 0.18,
        "SL": 0.24,
        "CH": 0.22,
        "SI": 0.16,
        "FC": 0.20,
        "CU": 0.21,
        "KC": 0.20,
        "FS": 0.23,
        "ST": 0.25,
        "UNK": 0.20,
    },
    "power_lhb": {
        "FF": 0.24,
        "SL": 0.32,
        "CH": 0.30,
        "SI": 0.20,
        "FC": 0.26,
        "CU": 0.29,
        "KC": 0.28,
        "FS": 0.30,
        "ST": 0.33,
        "UNK": 0.25,
    },
    "contact_lhb": {
        "FF": 0.17,
        "SL": 0.26,
        "CH": 0.24,
        "SI": 0.15,
        "FC": 0.19,
        "CU": 0.22,
        "KC": 0.21,
        "FS": 0.24,
        "ST": 0.27,
        "UNK": 0.19,
    },
    "league_avg": LEAGUE_WHIFF_BY_PITCH,
}


def classify_archetype_from_whiff(
    whiff_by_pitch: dict[str, float], stand: str = "R"
) -> str:
    """Simple rule-based archetype from observed whiff tensor."""
    ff = float(whiff_by_pitch.get("FF", 0.22))
    power = ff >= 0.24
    lefty = str(stand).upper().startswith("L")
    if lefty:
        return "power_lhb" if power else "contact_lhb"
    return "power_rhb" if power else "contact_rhb"


def archetype_batter_profile(archetype_id: str) -> dict:
    """Profile JSON fragment for matchup_k when no snapshot exists."""
    priors = ARCHETYPE_PRIORS.get(archetype_id, ARCHETYPE_PRIORS["league_avg"])
    return {
        "whiff_by_pitch": dict(priors),
        "reliability_by_pitch": {pt: 0.0 for pt in PITCH_TYPES},
        "cold_zones": {},
        "n_pitches": 0,
        "_archetype_id": archetype_id,
    }


def get_player_archetype(
    db: Session, player_id: int, season: int | None = None
) -> str | None:
    season = season or date.today().year
    row = (
        db.query(MlbPlayerArchetype)
        .filter(
            MlbPlayerArchetype.player_id == player_id,
            MlbPlayerArchetype.season == season,
        )
        .first()
    )
    return row.archetype_id if row else None


def assign_archetype(
    db: Session,
    player_id: int,
    archetype_id: str,
    season: int | None = None,
    n_pitches: int = 0,
) -> None:
    season = season or date.today().year
    existing = (
        db.query(MlbPlayerArchetype)
        .filter(
            MlbPlayerArchetype.player_id == player_id,
            MlbPlayerArchetype.season == season,
        )
        .first()
    )
    if existing:
        existing.archetype_id = archetype_id
        existing.n_pitches = n_pitches
    else:
        from datetime import datetime

        db.add(
            MlbPlayerArchetype(
                player_id=player_id,
                season=season,
                archetype_id=archetype_id,
                n_pitches=n_pitches,
                assigned_at=datetime.utcnow(),
            )
        )
