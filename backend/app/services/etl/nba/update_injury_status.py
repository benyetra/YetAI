"""Refresh pred_player_injury_status from CBS Sports + RotoWire scrapes.

Port of YetiBets/scripts/nba/update_injury_status.py. Both sources are HTML
scrapes; we de-duplicate by player_name (lowercase) and keep the more severe
status when two sources disagree. Players who have played in the last 7 days
with positive minutes are auto-cleared back to 'healthy'.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from sqlalchemy import func

from app.core.database import SessionLocal
from app.models.predictions_models import (
    PlayerInjuryStatus,
    RecentGames,
    TeamRoster,
)
from app.services.etl.nba._espn import now_eastern

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

STATUS_SEVERITY = {"ir": 4, "out": 3, "doubtful": 2, "questionable": 1, "healthy": 0}


def _normalize_status(status_str: str | None) -> str:
    if not status_str:
        return "healthy"
    s = status_str.lower().strip()
    if "out" in s or "o " in s:
        return "out"
    if "doubtful" in s or "d " in s:
        return "doubtful"
    if (
        "questionable" in s
        or "q " in s
        or "probable" in s
        or "p " in s
        or "gtd" in s
        or "game-time" in s
        or "day-to-day" in s
    ):
        return "questionable"
    if "ir" in s or "injured reserve" in s:
        return "ir"
    return "healthy"


def _strip_accents(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("ASCII")


def _clean_cbs_name(name: str) -> str:
    """CBS sometimes concatenates 'N. JokicNikola Jokic' — extract the full name."""
    name = _strip_accents(name)
    match = re.search(r"[A-Z]\.\s*[A-Z][a-z]+([A-Z][a-z]+.*)", name)
    if match:
        remaining = match.group(0)
        full_match = re.search(r"([A-Z][a-z]+)\s+([A-Z])", remaining)
        if full_match:
            idx = remaining.find(full_match.group(1))
            if idx > 3:
                return remaining[idx:].strip()
    return name.strip()


def _fetch_cbs() -> list[dict]:
    out: list[dict] = []
    try:
        r = requests.get(
            "https://www.cbssports.com/nba/injuries/", headers=HEADERS, timeout=30
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for table in soup.find_all("table", class_="TableBase-table"):
            for row in table.find_all("tr")[1:]:
                cells = row.find_all("td")
                if len(cells) < 5:
                    continue
                name = cells[0].get_text(strip=True)
                injury = cells[3].get_text(strip=True) if len(cells) > 3 else None
                status = cells[4].get_text(strip=True) if len(cells) > 4 else None
                if name and status:
                    out.append(
                        {
                            "player_name": name,
                            "injury_type": injury,
                            "status": _normalize_status(status),
                        }
                    )
        logger.info("injury_status: CBS returned %d entries", len(out))
    except Exception:
        logger.exception("injury_status: CBS scrape failed")
    return out


def _fetch_rotowire() -> list[dict]:
    out: list[dict] = []
    try:
        r = requests.get(
            "https://www.rotowire.com/basketball/nba-injury-report.php",
            headers=HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.find_all("div", class_="injury-item"):
            player_elem = item.find("a", class_="injury-item__player")
            status_elem = item.find("span", class_="injury-item__status")
            injury_elem = item.find("span", class_="injury-item__injury")
            if not (player_elem and status_elem):
                continue
            out.append(
                {
                    "player_name": player_elem.get_text(strip=True),
                    "injury_type": (
                        injury_elem.get_text(strip=True) if injury_elem else None
                    ),
                    "status": _normalize_status(status_elem.get_text(strip=True)),
                }
            )
        logger.info("injury_status: RotoWire returned %d entries", len(out))
    except Exception:
        logger.exception("injury_status: RotoWire scrape failed")
    return out


def _find_player_id(db, player_name: str) -> int | None:
    """Match injury-report name to TeamRoster.player_id. Tries exact, then full
    first+last match, then first-initial+last fallback. All case-insensitive
    and accent-stripped."""
    clean = _clean_cbs_name(player_name)
    row = (
        db.query(TeamRoster.player_id)
        .filter(func.lower(TeamRoster.player_name) == clean.lower())
        .first()
    )
    if row:
        return row[0]
    parts = clean.split()
    if len(parts) < 2:
        return None
    first, last = parts[0], parts[-1]
    roster = db.query(TeamRoster.player_id, TeamRoster.player_name).all()
    # full-name pass
    for pid, pname in roster:
        rp = _strip_accents(pname).split()
        if (
            len(rp) >= 2
            and rp[-1].lower() == last.lower()
            and rp[0].lower() == first.lower()
        ):
            return pid
    # initial+last fallback
    first_init = first[:1].lower()
    for pid, pname in roster:
        rp = _strip_accents(pname).split()
        if (
            len(rp) >= 2
            and rp[-1].lower() == last.lower()
            and rp[0][:1].lower() == first_init
        ):
            return pid
    return None


def _calc_games_missed(db, player_id: int) -> int:
    """Rough estimate from RecentGames: days since last game with min>0, ÷2,
    capped at 20. Returns 10 if no recent games at all (likely long-out)."""
    today = now_eastern().date()
    rg = (
        db.query(RecentGames.game_date, RecentGames.minutes)
        .filter_by(player_id=player_id)
        .order_by(RecentGames.game_date.desc())
        .limit(20)
        .all()
    )
    if not rg:
        return 0
    last_played = next((d for d, m in rg if m and m > 0), None)
    if not last_played:
        return 10
    return min((today - last_played).days // 2, 20)


def run() -> dict:
    all_injuries = _fetch_cbs() + _fetch_rotowire()
    if not all_injuries:
        return {
            "status": "ok",
            "reason": "no_sources_returned_data",
            "created": 0,
            "updated": 0,
            "cleared": 0,
        }

    # Dedup by name, keep more severe status.
    injury_map: dict[str, dict] = {}
    for inj in all_injuries:
        name = inj["player_name"].lower()
        if name not in injury_map or STATUS_SEVERITY.get(
            inj["status"], 0
        ) > STATUS_SEVERITY.get(injury_map[name]["status"], 0):
            injury_map[name] = inj

    created = 0
    updated = 0
    cleared = 0
    unmatched = 0
    today = now_eastern().date()

    db = SessionLocal()
    try:
        for name_lower, inj in injury_map.items():
            try:
                pid = _find_player_id(db, inj["player_name"])
                if not pid:
                    unmatched += 1
                    continue
                row = db.query(PlayerInjuryStatus).filter_by(player_id=pid).first()
                gm = _calc_games_missed(db, pid) if inj["status"] != "healthy" else 0
                if row:
                    row.status = inj["status"]
                    row.injury_type = inj.get("injury_type")
                    row.date_updated = datetime.utcnow()
                    row.games_missed = gm
                    if inj["status"] != "healthy" and not row.date_injured:
                        row.date_injured = today
                    updated += 1
                else:
                    db.add(
                        PlayerInjuryStatus(
                            player_id=pid,
                            player_name=inj["player_name"],
                            status=inj["status"],
                            injury_type=inj.get("injury_type"),
                            games_missed=gm,
                            date_updated=datetime.utcnow(),
                            date_injured=today if inj["status"] != "healthy" else None,
                        )
                    )
                    created += 1
                db.commit()
            except Exception:
                logger.exception(
                    "injury_status: failed to upsert %s", inj.get("player_name")
                )
                db.rollback()

        # Auto-clear: anyone currently flagged non-healthy who isn't in today's
        # scrape AND has played minutes in the last week.
        currently_injured = (
            db.query(PlayerInjuryStatus)
            .filter(PlayerInjuryStatus.status != "healthy")
            .all()
        )
        injured_names = set(injury_map.keys())
        cutoff = today - timedelta(days=7)
        for player in currently_injured:
            if player.player_name.lower() in injured_names:
                continue
            recent = (
                db.query(RecentGames)
                .filter_by(player_id=player.player_id)
                .order_by(RecentGames.game_date.desc())
                .first()
            )
            if (
                recent
                and recent.game_date >= cutoff
                and recent.minutes
                and recent.minutes > 0
            ):
                player.status = "healthy"
                player.date_updated = datetime.utcnow()
                player.games_missed = 0
                db.commit()
                cleared += 1

        return {
            "status": "ok",
            "cbs_plus_rotowire_raw": len(all_injuries),
            "unique_players": len(injury_map),
            "created": created,
            "updated": updated,
            "cleared": cleared,
            "unmatched_to_roster": unmatched,
        }
    finally:
        db.close()
