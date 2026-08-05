"""Pitcher archetypes for cold-start profile priors (usage + FB velo)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.mlb_archetype_models import MlbPitcherArchetype
from app.services.etl.mlb.profiles.constants import (
    PITCH_TYPES,
    PITCHER_ARCHETYPE_MIN_PITCHES,
    ZONE_KEYS,
)

# Taxonomy aligned with cluster_matchups.PITCHER_CLUSTERS (+ league_avg fallback).
PITCHER_ARCHETYPE_IDS = (
    "power_fastball",
    "finesse_control",
    "breaking_ball_heavy",
    "changeup_specialist",
    "sinker_groundball",
    "mixed_arsenal",
    "league_avg",
)

# Template usage mixes (sum ≈ 1.0) and typical FB velo for cold-start.
PITCHER_ARCHETYPE_PRIORS: dict[str, dict] = {
    "power_fastball": {
        "usage": {
            "FF": 0.55,
            "SL": 0.20,
            "CH": 0.08,
            "CU": 0.07,
            "SI": 0.05,
            "FC": 0.05,
        },
        "avg_fb_velo": 96.5,
        "velo_by_pitch": {"FF": 96.5, "SI": 95.0, "FC": 93.5, "SL": 86.0, "CH": 87.0},
    },
    "finesse_control": {
        "usage": {
            "FF": 0.40,
            "CH": 0.18,
            "CU": 0.15,
            "SL": 0.12,
            "FC": 0.10,
            "SI": 0.05,
        },
        "avg_fb_velo": 90.5,
        "velo_by_pitch": {"FF": 90.5, "SI": 89.0, "FC": 88.0, "CH": 82.0, "CU": 76.0},
    },
    "breaking_ball_heavy": {
        "usage": {
            "SL": 0.28,
            "CU": 0.15,
            "ST": 0.08,
            "FF": 0.35,
            "CH": 0.08,
            "SI": 0.06,
        },
        "avg_fb_velo": 93.0,
        "velo_by_pitch": {"FF": 93.0, "SL": 84.0, "CU": 78.0, "ST": 82.0},
    },
    "changeup_specialist": {
        "usage": {
            "CH": 0.28,
            "FF": 0.40,
            "SL": 0.12,
            "SI": 0.10,
            "CU": 0.05,
            "FS": 0.05,
        },
        "avg_fb_velo": 93.5,
        "velo_by_pitch": {"FF": 93.5, "CH": 84.0, "FS": 85.0, "SI": 92.0},
    },
    "sinker_groundball": {
        "usage": {
            "SI": 0.35,
            "FF": 0.20,
            "SL": 0.18,
            "CH": 0.12,
            "CU": 0.08,
            "FC": 0.07,
        },
        "avg_fb_velo": 92.5,
        "velo_by_pitch": {"SI": 92.5, "FF": 93.5, "SL": 84.0, "CH": 84.5},
    },
    "mixed_arsenal": {
        "usage": {
            "FF": 0.35,
            "SL": 0.20,
            "CH": 0.15,
            "SI": 0.12,
            "CU": 0.10,
            "FC": 0.08,
        },
        "avg_fb_velo": 93.0,
        "velo_by_pitch": {"FF": 93.0, "SI": 92.0, "SL": 84.5, "CH": 84.0},
    },
    "league_avg": {
        "usage": {
            "FF": 0.38,
            "SI": 0.12,
            "SL": 0.18,
            "CH": 0.12,
            "CU": 0.08,
            "FC": 0.07,
            "ST": 0.03,
            "FS": 0.02,
        },
        "avg_fb_velo": 93.0,
        "velo_by_pitch": {"FF": 93.5, "SI": 92.5, "FC": 90.0},
    },
}


def _neutral_location() -> dict[str, dict[str, float]]:
    equal = {z: 0.25 for z in ZONE_KEYS}
    return {pt: dict(equal) for pt in PITCH_TYPES}


def classify_pitcher_archetype(
    usage: dict[str, float],
    avg_fb_velo: float | None = None,
    hand: str | None = None,
) -> str:
    """Rule-based archetype from usage mix + FB velocity (cluster_matchups rules)."""
    if not usage:
        return "mixed_arsenal"

    # Normalize: cluster_matchups used 0–100 percentages; snapshots use 0–1 fractions.
    scale = 100.0 if max(float(v) for v in usage.values()) > 1.5 else 1.0

    def pct(keys: set[str]) -> float:
        return sum(float(usage.get(pt, 0.0)) for pt in keys) * (
            100.0 / scale if scale == 1.0 else 1.0
        )

    fb_pct = pct({"FF", "SI", "FC", "FA"})
    breaking_pct = pct({"SL", "CU", "KC", "ST", "SV"})
    changeup_pct = pct({"CH", "FS", "SC"})
    sinker_pct = pct({"SI", "FT"})

    velo = float(avg_fb_velo) if avg_fb_velo is not None else 93.0

    if sinker_pct >= 25:
        return "sinker_groundball"
    if fb_pct >= 65 and velo >= 95:
        return "power_fastball"
    if changeup_pct >= 25:
        return "changeup_specialist"
    if breaking_pct >= 40:
        return "breaking_ball_heavy"
    if fb_pct >= 60 and velo < 92:
        return "finesse_control"
    return "mixed_arsenal"


def archetype_pitcher_profile(archetype_id: str) -> dict:
    """Snapshot-shaped profile JSON for thin/missing pitcher cold-start."""
    prior = PITCHER_ARCHETYPE_PRIORS.get(
        archetype_id, PITCHER_ARCHETYPE_PRIORS["league_avg"]
    )
    usage = dict(prior["usage"])
    # Ensure all pitch types present with 0 so tensors iterate cleanly.
    for pt in PITCH_TYPES:
        usage.setdefault(pt, 0.0)
    total = sum(usage.values()) or 1.0
    usage = {k: float(v) / total for k, v in usage.items() if v > 0}
    return {
        "usage": usage,
        "location": _neutral_location(),
        "velo_by_pitch": dict(prior.get("velo_by_pitch") or {}),
        "avg_fb_velo": prior.get("avg_fb_velo"),
        "n_pitches": 0,
        "_archetype_id": archetype_id,
    }


def pitcher_snapshot_is_thin(
    n_pitches: int | None,
    usage: dict | None = None,
    *,
    min_pitches: int = PITCHER_ARCHETYPE_MIN_PITCHES,
) -> bool:
    """True when consumers should apply pitcher archetype priors."""
    if not n_pitches or n_pitches < min_pitches:
        return True
    if not usage:
        return True
    return False


def get_pitcher_archetype(
    db: Session, pitcher_id: int, season: int | None = None
) -> str | None:
    season = season or date.today().year
    row = (
        db.query(MlbPitcherArchetype)
        .filter(
            MlbPitcherArchetype.pitcher_id == pitcher_id,
            MlbPitcherArchetype.season == season,
        )
        .first()
    )
    return row.archetype_id if row else None


def assign_pitcher_archetype(
    db: Session,
    pitcher_id: int,
    archetype_id: str,
    season: int | None = None,
    n_pitches: int = 0,
    avg_fb_velo: float | None = None,
) -> None:
    season = season or date.today().year
    existing = (
        db.query(MlbPitcherArchetype)
        .filter(
            MlbPitcherArchetype.pitcher_id == pitcher_id,
            MlbPitcherArchetype.season == season,
        )
        .first()
    )
    if existing:
        existing.archetype_id = archetype_id
        existing.n_pitches = n_pitches
        existing.avg_fb_velo = avg_fb_velo
        existing.assigned_at = datetime.utcnow()
    else:
        db.add(
            MlbPitcherArchetype(
                pitcher_id=pitcher_id,
                season=season,
                archetype_id=archetype_id,
                n_pitches=n_pitches,
                avg_fb_velo=avg_fb_velo,
                assigned_at=datetime.utcnow(),
            )
        )


def resolve_pitcher_profile_for_matchup(
    db: Session | None,
    pitcher_id: int,
    pitcher_snap,
    as_of_date: date,
) -> tuple[dict, str]:
    """
    Return (profile_dict, pitcher_source_tag).

    Thick observed snapshots keep real usage (caller maps observed vs shrunk).
    Thin/missing → archetype prior tagged ``archetype``.
    """
    usage = (pitcher_snap.profile or {}).get("usage") if pitcher_snap else None
    n_pitches = int(getattr(pitcher_snap, "n_pitches", 0) or 0) if pitcher_snap else 0
    if (
        pitcher_snap
        and pitcher_snap.profile
        and not pitcher_snapshot_is_thin(n_pitches, usage)
    ):
        tag = "observed" if n_pitches >= PITCHER_ARCHETYPE_MIN_PITCHES else "shrunk"
        return pitcher_snap.profile, tag

    aid = "mixed_arsenal"
    if db is not None:
        try:
            aid = (
                get_pitcher_archetype(db, int(pitcher_id), as_of_date.year)
                or "mixed_arsenal"
            )
        except Exception:
            aid = "mixed_arsenal"
    return archetype_pitcher_profile(aid), "archetype"
