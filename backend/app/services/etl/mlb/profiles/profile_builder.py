from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from app.core.database import SessionLocal
from app.models.mlb_profile_models import (
    MlbBatterProfileSnapshot,
    MlbPitcherProfileSnapshot,
)
from app.services.etl.mlb.profiles.constants import (
    LEAGUE_WHIFF_BY_PITCH,
    PROFILE_VERSION,
    WINDOWS,
)
from app.services.etl.mlb.profiles.shrinkage import posterior_whiff_rate
from app.services.etl.mlb.statcast_ingest.s3_paths import base_prefix, read_manifest

logger = logging.getLogger(__name__)


def _window_mask(df: pd.DataFrame, as_of: date, window: str) -> pd.Series:
    gd = pd.to_datetime(df["game_date"]).dt.date
    strict = gd < as_of
    if window == "7d":
        return strict & (gd >= as_of - timedelta(days=7))
    if window == "30d":
        return strict & (gd >= as_of - timedelta(days=30))
    if window == "season":
        return strict & (pd.to_datetime(df["game_date"]).dt.year == as_of.year)
    if window == "3yr_decay":
        return strict & (gd >= as_of - timedelta(days=365 * 3))
    raise ValueError(f"unknown window: {window}")


def _decay_weights(df: pd.DataFrame, as_of: date) -> pd.Series:
    gd = pd.to_datetime(df["game_date"]).dt.date
    days_ago = [(as_of - d).days for d in gd]
    half_life = 365.0
    return pd.Series(
        [math.exp(-d / half_life) for d in days_ago], index=df.index, dtype=float
    )


def aggregate_pitcher(
    df: pd.DataFrame, pitcher_id: int, window: str, as_of_date: date
) -> dict | None:
    sub = df[(df["pitcher"] == pitcher_id) & _window_mask(df, as_of_date, window)]
    if window == "3yr_decay" and not sub.empty:
        w = _decay_weights(sub, as_of_date)
        sub = sub.copy()
        sub["_w"] = w
    else:
        sub = sub.copy()
        sub["_w"] = 1.0

    n = int(len(sub))
    if n == 0:
        return None

    hand = (
        sub["p_throws"].mode().iloc[0]
        if "p_throws" in sub.columns and not sub["p_throws"].mode().empty
        else None
    )
    usage: dict[str, float] = {}
    location: dict[str, dict[str, float]] = {}
    velo_by_pitch: dict[str, float] = {}
    has_velo = "release_speed" in sub.columns
    for pt, grp in sub.groupby("pitch_type_canon"):
        wsum = grp["_w"].sum()
        if wsum <= 0:
            continue
        usage[pt] = float(wsum / sub["_w"].sum())
        loc: dict[str, float] = {}
        for zone, zgrp in grp.groupby("zone_bucket"):
            loc[zone] = float(zgrp["_w"].sum() / wsum)
        location[pt] = loc
        if has_velo:
            speeds = grp["release_speed"].dropna()
            if not speeds.empty:
                # Weighted mean when decay weights present
                if (grp["_w"] != 1.0).any():
                    mask = grp["release_speed"].notna()
                    ww = grp.loc[mask, "_w"]
                    vv = grp.loc[mask, "release_speed"]
                    if ww.sum() > 0:
                        velo_by_pitch[pt] = float((vv * ww).sum() / ww.sum())
                else:
                    velo_by_pitch[pt] = float(speeds.mean())

    fb_keys = ("FF", "SI", "FC")
    fb_velos = [velo_by_pitch[k] for k in fb_keys if k in velo_by_pitch]
    if fb_velos:
        avg_fb_velo = float(sum(fb_velos) / len(fb_velos))
    elif velo_by_pitch:
        avg_fb_velo = float(sum(velo_by_pitch.values()) / len(velo_by_pitch))
    else:
        avg_fb_velo = None

    return {
        "usage": usage,
        "location": location,
        "velo_by_pitch": velo_by_pitch,
        "avg_fb_velo": avg_fb_velo,
        "n_pitches": n,
        "hand": hand,
    }


def aggregate_batter(
    df: pd.DataFrame, batter_id: int, vs_hand: str, window: str, as_of_date: date
) -> dict | None:
    sub = df[
        (df["batter"] == batter_id)
        & (df["p_throws"] == vs_hand)
        & _window_mask(df, as_of_date, window)
    ]
    if window == "3yr_decay" and not sub.empty:
        sub = sub.copy()
        sub["_w"] = _decay_weights(sub, as_of_date)
    else:
        sub = sub.copy()
        sub["_w"] = 1.0

    n = int(len(sub))
    if n == 0:
        return None

    whiff_by_pitch: dict[str, float] = {}
    reliability_by_pitch: dict[str, float] = {}
    cold_zones: dict[str, list[str]] = {}

    for pt, grp in sub.groupby("pitch_type_canon"):
        wsum = grp["_w"].sum()
        if wsum <= 0:
            continue
        observed = float((grp["is_whiff"] * grp["_w"]).sum() / wsum)
        post, rel = posterior_whiff_rate(observed, int(wsum), pt)
        whiff_by_pitch[pt] = post
        reliability_by_pitch[pt] = rel
        league = LEAGUE_WHIFF_BY_PITCH.get(pt, 0.25)
        cold = []
        for zone, zgrp in grp.groupby("zone_bucket"):
            zrate = float((zgrp["is_whiff"] * zgrp["_w"]).sum() / zgrp["_w"].sum())
            if zrate > league + 0.05:
                cold.append(zone)
        if cold:
            cold_zones[pt] = cold

    xwoba_by_pitch: dict[str, float] = {}
    iso_by_pitch: dict[str, float] = {}
    barrel_rate_by_pitch: dict[str, float] = {}

    for pt, grp in sub.groupby("pitch_type_canon"):
        wsum = grp["_w"].sum()
        if wsum <= 0:
            continue
        if "estimated_woba_using_speedangle" in grp.columns:
            xwoba_by_pitch[pt] = float(
                (grp["estimated_woba_using_speedangle"].fillna(0) * grp["_w"]).sum()
                / wsum
            )
        if "iso_value" in grp.columns:
            iso_by_pitch[pt] = float((grp["iso_value"] * grp["_w"]).sum() / wsum)
        if "is_barrel" in grp.columns:
            barrel_rate_by_pitch[pt] = float(
                (grp["is_barrel"].astype(float) * grp["_w"]).sum() / wsum
            )

    return {
        "whiff_by_pitch": whiff_by_pitch,
        "reliability_by_pitch": reliability_by_pitch,
        "cold_zones": cold_zones,
        "xwoba_by_pitch": xwoba_by_pitch,
        "iso_by_pitch": iso_by_pitch,
        "barrel_rate_by_pitch": barrel_rate_by_pitch,
        "n_pitches": n,
    }


def load_pitches(prefix: str | None = None) -> pd.DataFrame:
    """Load all parquet partitions listed in season manifests under prefix."""
    root = (prefix or base_prefix()).rstrip("/")
    frames: list[pd.DataFrame] = []
    if root.startswith("s3://"):
        import boto3
        from io import BytesIO
        from urllib.parse import urlparse

        client = boto3.client("s3")
        for year in range(2018, date.today().year + 1):
            for part in read_manifest(year):
                if not part.startswith("s3://"):
                    continue
                parsed = urlparse(part)
                obj = client.get_object(
                    Bucket=parsed.netloc, Key=parsed.path.lstrip("/")
                )
                # S3 StreamingBody is not seekable; pyarrow parquet requires it.
                frames.append(pd.read_parquet(BytesIO(obj["Body"].read())))
    else:
        base = Path(root)
        seasons = set()
        for manifest_path in base.glob("season=*/_manifest.json"):
            seasons.add(int(manifest_path.parent.name.split("=")[1]))
        if not seasons:
            seasons = {
                int(p.name.split("=")[1]) for p in base.glob("season=*") if p.is_dir()
            }
        for season in sorted(seasons):
            for part in read_manifest(season):
                p = Path(part)
                if p.is_file():
                    frames.append(pd.read_parquet(p))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def build_snapshots_for_date(
    df: pd.DataFrame, as_of_date: date, db=None
) -> dict[str, int]:
    """Aggregate all pitchers/batters for each window and insert snapshots."""
    if SessionLocal is None:
        raise RuntimeError("database not configured")
    own_session = db is None
    session = db or SessionLocal()
    pitcher_rows = 0
    batter_rows = 0
    try:
        for window in WINDOWS:
            for pid in df["pitcher"].dropna().unique():
                prof = aggregate_pitcher(df, int(pid), window, as_of_date)
                if not prof:
                    continue
                session.add(
                    MlbPitcherProfileSnapshot(
                        pitcher_id=int(pid),
                        as_of_date=as_of_date,
                        window=window,
                        profile_version=PROFILE_VERSION,
                        hand=prof.get("hand"),
                        n_pitches=prof["n_pitches"],
                        profile={
                            "usage": prof["usage"],
                            "location": prof["location"],
                            "velo_by_pitch": prof.get("velo_by_pitch") or {},
                            "avg_fb_velo": prof.get("avg_fb_velo"),
                        },
                        created_at=datetime.utcnow(),
                    )
                )
                pitcher_rows += 1

            for bid in df["batter"].dropna().unique():
                for hand in ("L", "R"):
                    prof = aggregate_batter(df, int(bid), hand, window, as_of_date)
                    if not prof:
                        continue
                    session.add(
                        MlbBatterProfileSnapshot(
                            batter_id=int(bid),
                            vs_hand=hand,
                            as_of_date=as_of_date,
                            window=window,
                            profile_version=PROFILE_VERSION,
                            n_pitches=prof["n_pitches"],
                            profile={
                                "whiff_by_pitch": prof["whiff_by_pitch"],
                                "reliability_by_pitch": prof["reliability_by_pitch"],
                                "cold_zones": prof["cold_zones"],
                                "xwoba_by_pitch": prof.get("xwoba_by_pitch", {}),
                                "iso_by_pitch": prof.get("iso_by_pitch", {}),
                                "barrel_rate_by_pitch": prof.get(
                                    "barrel_rate_by_pitch", {}
                                ),
                            },
                            created_at=datetime.utcnow(),
                        )
                    )
                    batter_rows += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if own_session:
            session.close()
    return {"pitchers": pitcher_rows, "batters": batter_rows}


def rebuild_all_profiles(
    as_of_date: date | None = None, prefix: str | None = None
) -> dict:
    as_of = as_of_date or date.today()
    logger.info(
        "rebuild_all_profiles as_of=%s profile_version=%s prefix=%s",
        as_of,
        PROFILE_VERSION,
        prefix,
    )
    df = load_pitches(prefix)
    if df.empty:
        logger.warning("no pitch data loaded for profile rebuild")
        return {
            "pitchers": 0,
            "batters": 0,
            "profile_version": PROFILE_VERSION,
            "as_of_date": as_of.isoformat(),
        }

    logger.info("loaded %s pitch rows for profile rebuild", len(df))
    if SessionLocal is None:
        raise RuntimeError("database not configured")
    db = SessionLocal()
    try:
        deleted_p = (
            db.query(MlbPitcherProfileSnapshot)
            .filter(
                MlbPitcherProfileSnapshot.as_of_date == as_of,
                MlbPitcherProfileSnapshot.profile_version == PROFILE_VERSION,
            )
            .delete(synchronize_session=False)
        )
        deleted_b = (
            db.query(MlbBatterProfileSnapshot)
            .filter(
                MlbBatterProfileSnapshot.as_of_date == as_of,
                MlbBatterProfileSnapshot.profile_version == PROFILE_VERSION,
            )
            .delete(synchronize_session=False)
        )
        db.commit()
        logger.info(
            "cleared prior snapshots as_of=%s version=%s pitchers=%s batters=%s",
            as_of,
            PROFILE_VERSION,
            deleted_p,
            deleted_b,
        )
        counts = build_snapshots_for_date(df, as_of, db=db)
        counts["profile_version"] = PROFILE_VERSION
        counts["as_of_date"] = as_of.isoformat()
        logger.info("rebuild_all_profiles wrote %s", counts)
        return counts
    finally:
        db.close()
