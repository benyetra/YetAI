"""Bullpen Fatigue Index Calculator.

Computes a weighted fatigue index for each MLB team's bullpen based on
recent usage (3/5/7-day innings pitched windows). Higher index = more fatigued.

PRD v2.0 §5.2 — Bullpen Usage Tracker (P1, Phase 1).
"""

import sys
import os

import logging
from datetime import date, timedelta
import statsapi as mlbstatsapi
from app.models.predictions_models import BullpenFatigue

from app.services.etl.mlb._db import db_session


logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# League-average bullpen IP baselines for normalization
AVG_BP_IP_3DAY = 9.0
AVG_BP_IP_5DAY = 15.0
AVG_BP_IP_7DAY = 21.0

# Fatigue weights (sum to 1.0)
W_3DAY = 0.50
W_5DAY = 0.30
W_7DAY = 0.20

CURRENT_SEASON = date.today().year


def get_all_team_ids():
    """Fetch all 30 MLB team IDs and names."""
    teams = mlbstatsapi.get("teams", {"sportId": 1, "season": CURRENT_SEASON})
    return [
        {"id": t["id"], "name": t["name"]}
        for t in teams.get("teams", [])
        if t.get("sport", {}).get("id") == 1
    ]


def fetch_team_bullpen_usage(team_id, target_date=None, lookback_days=7):
    """Fetch bullpen IP from recent games via MLB-StatsAPI boxscores.

    Returns dict with ip_last_3, ip_last_5, ip_last_7, high_leverage_ip_3,
    and reliever_details list.
    """
    if target_date is None:
        target_date = date.today()

    end_date = target_date - timedelta(days=1)  # Yesterday (most recent completed)
    start_date = target_date - timedelta(days=lookback_days)

    try:
        games = mlbstatsapi.schedule(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            team=team_id,
        )
    except Exception as e:
        logger.warning(f"Failed to fetch schedule for team {team_id}: {e}")
        return None

    # Track daily bullpen IP
    daily_ip = {}
    reliever_usage = {}

    for g in games:
        if g.get("status", "") not in ("Final", "Game Over", "Completed Early"):
            continue

        game_date = g.get("game_date", "")[:10]
        try:
            bs = mlbstatsapi.boxscore_data(g["game_id"])
        except Exception as e:
            logger.warning(f"Failed to fetch boxscore for game {g['game_id']}: {e}")
            continue

        side = "home" if g.get("home_id") == team_id else "away"
        pitchers_key = f"{side}Pitchers"
        pitchers = bs.get(pitchers_key, [])

        # Skip starter (index 0) and team totals (last entry)
        bullpen = pitchers[1:-1] if len(pitchers) > 2 else []
        game_bp_ip = 0.0

        for p in bullpen:
            ip_str = p.get("ip", "0") or "0"
            try:
                ip = float(ip_str)
            except (ValueError, TypeError):
                ip = 0.0
            game_bp_ip += ip

            p_name = p.get("name", "Unknown")
            if p_name not in reliever_usage:
                reliever_usage[p_name] = {"ip_total": 0.0, "appearances": 0}
            reliever_usage[p_name]["ip_total"] += ip
            reliever_usage[p_name]["appearances"] += 1

        daily_ip[game_date] = daily_ip.get(game_date, 0.0) + game_bp_ip

    # Compute rolling windows
    ip_3 = 0.0
    ip_5 = 0.0
    ip_7 = 0.0

    for gd_str, ip_val in daily_ip.items():
        try:
            gd = date.fromisoformat(gd_str)
        except ValueError:
            continue
        days_ago = (target_date - gd).days
        if days_ago <= 3:
            ip_3 += ip_val
        if days_ago <= 5:
            ip_5 += ip_val
        if days_ago <= 7:
            ip_7 += ip_val

    # Build reliever details
    reliever_details = [
        {
            "name": name,
            "ip": round(data["ip_total"], 1),
            "appearances": data["appearances"],
        }
        for name, data in sorted(
            reliever_usage.items(), key=lambda x: -x[1]["ip_total"]
        )
    ]

    return {
        "ip_last_3_days": round(ip_3, 1),
        "ip_last_5_days": round(ip_5, 1),
        "ip_last_7_days": round(ip_7, 1),
        "high_leverage_ip_last_3": round(
            ip_3 * 0.6, 1
        ),  # Approximate high-leverage portion
        "reliever_details": reliever_details,
    }


def compute_fatigue_index(ip_3, ip_5, ip_7):
    """Compute weighted composite fatigue score normalized to [0, 1].

    Uses league-average baselines for normalization. A value of 0.5 means
    league-average usage; >0.5 means overworked; <0.5 means well-rested.
    Normalization: divide by 2x league average so that league-avg maps to 0.5.
    """
    norm_3 = min(ip_3 / (AVG_BP_IP_3DAY * 2.0), 1.0)  # 0.5 at league avg
    norm_5 = min(ip_5 / (AVG_BP_IP_5DAY * 2.0), 1.0)
    norm_7 = min(ip_7 / (AVG_BP_IP_7DAY * 2.0), 1.0)

    raw = W_3DAY * norm_3 + W_5DAY * norm_5 + W_7DAY * norm_7
    return round(min(max(raw, 0.0), 1.0), 3)


def store_bullpen_fatigue(fatigue_data_list, target_date=None):
    """Upsert bullpen fatigue data for the target date."""
    if target_date is None:
        target_date = date.today()

    for data in fatigue_data_list:
        existing = (
            db_session.query(BullpenFatigue)
            .filter_by(date=target_date, team_id=data["team_id"])
            .first()
        )

        if existing:
            existing.ip_last_3_days = data["ip_last_3_days"]
            existing.ip_last_5_days = data["ip_last_5_days"]
            existing.ip_last_7_days = data["ip_last_7_days"]
            existing.high_leverage_ip_last_3 = data["high_leverage_ip_last_3"]
            existing.fatigue_index = data["fatigue_index"]
            existing.reliever_details = data["reliever_details"]
        else:
            entry = BullpenFatigue(
                date=target_date,
                team_name=data["team_name"],
                team_id=data["team_id"],
                ip_last_3_days=data["ip_last_3_days"],
                ip_last_5_days=data["ip_last_5_days"],
                ip_last_7_days=data["ip_last_7_days"],
                high_leverage_ip_last_3=data["high_leverage_ip_last_3"],
                fatigue_index=data["fatigue_index"],
                reliever_details=data["reliever_details"],
            )
            db_session.add(entry)

    db_session.commit()
    logger.info(
        f"Stored bullpen fatigue for {len(fatigue_data_list)} teams on {target_date}"
    )


def get_team_fatigue(team_id, target_date=None):
    """Retrieve fatigue index for a specific team. Returns 0.5 (league avg) as fallback."""
    if target_date is None:
        target_date = date.today()
    entry = (
        db_session.query(BullpenFatigue)
        .filter_by(date=target_date, team_id=team_id)
        .first()
    )
    return entry.fatigue_index if entry else 0.5


def main():
    """Compute and store bullpen fatigue for all 30 MLB teams."""
    from app.services.etl.mlb._db import close_session, init_session

    init_session()
    try:
        target_date = date.today()
        teams = get_all_team_ids()
        fatigue_data = []

        for team in teams:
            logger.info(f"Computing fatigue for {team['name']} (ID: {team['id']})")
            usage = fetch_team_bullpen_usage(team["id"], target_date)

            if usage is None:
                logger.warning(f"No usage data for %s, using defaults", team["name"])
                usage = {
                    "ip_last_3_days": 0.0,
                    "ip_last_5_days": 0.0,
                    "ip_last_7_days": 0.0,
                    "high_leverage_ip_last_3": 0.0,
                    "reliever_details": [],
                }

            fatigue_idx = compute_fatigue_index(
                usage["ip_last_3_days"],
                usage["ip_last_5_days"],
                usage["ip_last_7_days"],
            )

            fatigue_data.append(
                {
                    "team_id": team["id"],
                    "team_name": team["name"],
                    "fatigue_index": fatigue_idx,
                    **usage,
                }
            )

        store_bullpen_fatigue(fatigue_data, target_date)
        logger.info("Bullpen fatigue pipeline complete for %s", target_date)
    finally:
        close_session()


if __name__ == "__main__":
    main()
