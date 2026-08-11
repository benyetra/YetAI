"""Historical NFL player_pass_yds via The Odds API (credit-aware + SQLite cache).

Cost model (paid plan, measured):
  - GET /v4/historical/sports/americanfootball_nfl/events?date=... → **1 credit**
    (returns the slate near that timestamp)
  - GET /v4/historical/.../events/{id}/odds?markets=player_pass_yds&regions=us
    → **10 credits** (1 region × 1 market × 1 event)

Efficiency rules:
  - Cache every response forever in ``scripts/nfl_odds_cache.db``
  - One events call per unique gameday (not per game)
  - One props call per event; skip if already cached
  - Prefer seasons/games that lack a stored ``ou_line`` / index row
  - Snapshot props at ``commence_time`` (closest ≤ kickoff)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

from app.services.etl.nfl.team_names import normalize_team_name

logger = logging.getLogger(__name__)

SPORT = "americanfootball_nfl"
EVENTS_URL = f"https://api.the-odds-api.com/v4/historical/sports/{SPORT}/events"
EVENT_ODDS_URL = f"https://api.the-odds-api.com/v4/historical/sports/{SPORT}/events/{{event_id}}/odds"

CREDITS_EVENTS = 1
CREDITS_PROPS = 10  # regions=us × markets=player_pass_yds

PREFERRED_BOOKS = ("draftkings", "fanduel", "betmgm", "williamhill_us")

_BACKEND = Path(__file__).resolve().parents[4]
CACHE_DB_PATH = _BACKEND / "scripts" / "nfl_odds_cache.db"
LINES_INDEX_PATH = _BACKEND / "models" / "nfl" / "pass_yds_lines.json"


def resolve_odds_api_key() -> str | None:
    key = (os.getenv("ODDS_API_KEY") or os.getenv("ODDS_API") or "").strip()
    if key and key not in ("your_odds_api_key_here", "your-odds-api-key"):
        return key
    try:
        from app.core.config import settings

        key = (settings.ODDS_API_KEY or "").strip()
        if key and key not in ("your_odds_api_key_here", "your-odds-api-key"):
            return key
    except Exception:
        pass
    return None


def _conn() -> sqlite3.Connection:
    CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CACHE_DB_PATH))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_cache (
            cache_key TEXT PRIMARY KEY,
            endpoint TEXT NOT NULL,
            params_json TEXT,
            response_json TEXT NOT NULL,
            credits_last INTEGER,
            created_at REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _cache_key(endpoint: str, params: dict[str, Any]) -> str:
    raw = f"{endpoint}|{json.dumps(params, sort_keys=True, default=str)}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_cached(endpoint: str, params: dict[str, Any]) -> Any | None:
    key = _cache_key(endpoint, params)
    try:
        conn = _conn()
        row = conn.execute(
            "SELECT response_json FROM api_cache WHERE cache_key = ?", (key,)
        ).fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except Exception as exc:
        logger.debug("cache read: %s", exc)
    return None


def set_cached(
    endpoint: str,
    params: dict[str, Any],
    response: Any,
    *,
    credits_last: int | None = None,
) -> None:
    key = _cache_key(endpoint, params)
    try:
        conn = _conn()
        conn.execute(
            """INSERT OR REPLACE INTO api_cache
               (cache_key, endpoint, params_json, response_json, credits_last, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                key,
                endpoint,
                json.dumps(params, sort_keys=True, default=str),
                json.dumps(response, default=str),
                credits_last,
                time.time(),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("cache write: %s", exc)


def normalize_player_key(name: str) -> str:
    """Last-name + first-initial key for Odds ↔ nflverse matching."""
    cleaned = re.sub(r"[^a-zA-Z\s.]", " ", str(name or ""))
    cleaned = cleaned.replace(".", " ")
    parts = [p for p in cleaned.lower().split() if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0][0]}|{parts[-1]}"


def _http_get(
    url: str,
    params: dict[str, Any],
    *,
    endpoint: str,
    cache_only: bool = False,
) -> tuple[Any | None, int]:
    """Return (json_payload, credits_spent_this_call)."""
    # Strip apiKey from cache identity; keep event_id etc.
    cache_params = {k: v for k, v in params.items() if k != "apiKey"}
    # bookmakers filter is for request only — include in cache key for fidelity
    cached = get_cached(endpoint, cache_params)
    if cached is not None:
        return cached, 0
    if cache_only:
        return None, 0

    api_key = params.get("apiKey") or resolve_odds_api_key()
    if not api_key:
        logger.error("ODDS_API_KEY missing")
        return None, 0

    # event_id is path param — don't send as query if present
    call_params = {k: v for k, v in params.items() if k not in ("apiKey", "event_id")}
    call_params["apiKey"] = api_key
    time.sleep(0.15)  # be gentle; historical calls are expensive to retry
    try:
        resp = requests.get(url, params=call_params, timeout=45)
    except Exception as exc:
        logger.warning("HTTP %s failed: %s", endpoint, exc)
        return None, 0

    cost = int(resp.headers.get("x-requests-last") or 0)
    remaining = resp.headers.get("x-requests-remaining")
    if resp.status_code != 200:
        logger.warning(
            "%s HTTP %s cost=%s rem=%s body=%s",
            endpoint,
            resp.status_code,
            cost,
            remaining,
            (resp.text or "")[:180],
        )
        # Cache empty miss for 404-ish to avoid burning credits? Don't cache errors.
        return None, cost

    payload = resp.json()
    set_cached(endpoint, cache_params, payload, credits_last=cost)
    logger.info(
        "%s ok cost=%s remaining=%s",
        endpoint,
        cost,
        remaining,
    )
    return payload, cost


def fetch_historical_events(
    snapshot_date: date,
    *,
    snapshot_hour_utc: int = 16,
    cache_only: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """Events slate for a calendar day. ~1 credit when uncached."""
    ts = f"{snapshot_date.isoformat()}T{snapshot_hour_utc:02d}:00:00Z"
    payload, cost = _http_get(
        EVENTS_URL,
        {"date": ts, "dateFormat": "iso"},
        endpoint="hist_nfl_events",
        cache_only=cache_only,
    )
    if not payload:
        return [], cost
    data = payload.get("data") if isinstance(payload, dict) else payload
    return list(data or []), cost


def fetch_event_pass_yds(
    event_id: str,
    commence_time_iso: str,
    *,
    cache_only: bool = False,
) -> tuple[dict[str, Any] | None, int]:
    """Player pass yards props for one event. ~10 credits when uncached."""
    # Closest snapshot ≤ kickoff. event_id must be in cache params (not only URL).
    payload, cost = _http_get(
        EVENT_ODDS_URL.format(event_id=event_id),
        {
            "event_id": event_id,
            "regions": "us",
            "markets": "player_pass_yds",
            "oddsFormat": "american",
            "dateFormat": "iso",
            "date": commence_time_iso,
            "bookmakers": "draftkings,fanduel,betmgm",
        },
        endpoint="hist_nfl_pass_yds",
        cache_only=cache_only,
    )
    if not payload:
        return None, cost
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        return data, cost
    return None, cost


def extract_pass_yds_lines(event_odds: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """player_name → consensus {line, book, over_price, under_price}."""
    by_player: dict[str, list[dict[str, Any]]] = {}
    for bm in event_odds.get("bookmakers") or []:
        book = str(bm.get("key") or "")
        for market in bm.get("markets") or []:
            if market.get("key") != "player_pass_yds":
                continue
            overs: dict[str, dict[str, Any]] = {}
            unders: dict[str, dict[str, Any]] = {}
            for o in market.get("outcomes") or []:
                player = str(o.get("description") or "").strip()
                if not player or o.get("point") is None:
                    continue
                side = str(o.get("name") or "").lower()
                row = {
                    "line": float(o["point"]),
                    "price": o.get("price"),
                    "book": book,
                }
                if side == "over":
                    overs[player] = row
                elif side == "under":
                    unders[player] = row
            for player, over in overs.items():
                under = unders.get(player) or {}
                by_player.setdefault(player, []).append(
                    {
                        "line": over["line"],
                        "book": book,
                        "over_price": over.get("price"),
                        "under_price": under.get("price"),
                    }
                )

    out: dict[str, dict[str, Any]] = {}
    for player, rows in by_player.items():
        rows_sorted = sorted(
            rows,
            key=lambda r: (
                PREFERRED_BOOKS.index(r["book"]) if r["book"] in PREFERRED_BOOKS else 99
            ),
        )
        pick = rows_sorted[0]
        # Median line across books for stability when preferred missing
        lines = sorted(float(r["line"]) for r in rows)
        median = lines[len(lines) // 2]
        out[player] = {
            "line": float(pick["line"]),
            "line_median": float(median),
            "book": pick["book"],
            "over_price": pick.get("over_price"),
            "under_price": pick.get("under_price"),
            "n_books": len(rows),
        }
    return out


def schedule_reg_games(seasons: Iterable[int]) -> list[dict[str, Any]]:
    import nfl_data_py as nfl
    import pandas as pd

    seasons_l = [int(s) for s in seasons]
    sched = nfl.import_schedules(seasons_l)
    if "game_type" in sched.columns:
        sched = sched[sched["game_type"] == "REG"]
    out: list[dict[str, Any]] = []
    for _, row in sched.iterrows():
        gameday = row.get("gameday")
        try:
            gd = pd.to_datetime(gameday).date()
        except Exception:
            continue
        # Props historical from ~2023-05-03
        if gd < date(2023, 5, 3):
            continue
        home = str(row.get("home_team") or "").upper()
        away = str(row.get("away_team") or "").upper()
        kickoff = row.get("gametime")
        # Build commence ISO from gameday + gametime when possible
        commence = None
        if row.get("gametime") and gameday is not None:
            try:
                # nflverse gametime is local ET-ish "13:00"
                ht = str(kickoff)
                if re.match(r"^\d{1,2}:\d{2}", ht):
                    hh, mm = ht.split(":")[:2]
                    # Treat as America/New_York → UTC approx EST/EDT: use 4h offset winter / 4h — rough
                    # Prefer odds events commence_time after match; store local hint only
                    commence = f"{gd.isoformat()}T{int(hh):02d}:{int(mm):02d}:00"
            except Exception:
                commence = None
        out.append(
            {
                "season": int(row["season"]),
                "week": int(row["week"]),
                "gameday": gd,
                "home_abbr": home,
                "away_abbr": away,
                "home_name": normalize_team_name(home),
                "away_name": normalize_team_name(away),
                "gametime_local": str(kickoff) if kickoff is not None else None,
                "commence_hint": commence,
            }
        )
    return out


def match_event(
    game: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any] | None:
    home = normalize_team_name(game["home_name"])
    away = normalize_team_name(game["away_name"])
    gameday: date | None = game.get("gameday")
    candidates: list[dict[str, Any]] = []
    for ev in events:
        eh = normalize_team_name(str(ev.get("home_team") or ""))
        ea = normalize_team_name(str(ev.get("away_team") or ""))
        if not ((eh == home and ea == away) or (eh == away and ea == home)):
            continue
        if gameday is not None:
            try:
                commence = datetime.fromisoformat(
                    str(ev.get("commence_time") or "").replace("Z", "+00:00")
                )
                # Allow UTC/ET day skew for evening games
                if abs((commence.date() - gameday).days) > 1:
                    continue
            except Exception:
                pass
        candidates.append(ev)
    if not candidates:
        return None
    if len(candidates) == 1 or gameday is None:
        return candidates[0]

    # Prefer commence date closest to gameday
    def _dist(ev: dict[str, Any]) -> int:
        try:
            commence = datetime.fromisoformat(
                str(ev.get("commence_time") or "").replace("Z", "+00:00")
            )
            return abs((commence.date() - gameday).days)
        except Exception:
            return 99

    return min(candidates, key=_dist)


def load_lines_index(path: Path | None = None) -> dict[str, Any]:
    p = path or LINES_INDEX_PATH
    if not p.is_file():
        return {"version": 1, "lines": [], "by_key": {}}
    try:
        payload = json.loads(p.read_text())
    except Exception:
        return {"version": 1, "lines": [], "by_key": {}}
    # Always rebuild by_key (committed JSON may omit it to save space)
    by_key: dict[str, Any] = {}
    for row in payload.get("lines") or []:
        key = _line_key(row)
        if key:
            by_key[key] = row
    payload["by_key"] = by_key
    return payload


def _line_key(row: dict[str, Any]) -> str:
    season = row.get("season")
    week = row.get("week")
    pkey = row.get("player_key") or normalize_player_key(
        str(row.get("player_name") or "")
    )
    event_id = str(row.get("event_id") or "")
    if season is None or week is None or not pkey or not event_id:
        return ""
    return f"{season}|{week}|{pkey}|{event_id}"


def save_lines_index(payload: dict[str, Any], path: Path | None = None) -> Path:
    p = path or LINES_INDEX_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    # rebuild by_key
    by_key: dict[str, Any] = {}
    for row in payload.get("lines") or []:
        key = _line_key(row)
        if key:
            by_key[key] = row
    payload["by_key"] = by_key
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(payload, indent=2, default=str))
    return p


def lookup_pass_yds_line(
    *,
    season: int,
    week: int,
    player_name: str,
    team_abbr: str | None = None,
    index: dict[str, Any] | None = None,
) -> float | None:
    idx = index if index is not None else load_lines_index()
    pkey = normalize_player_key(player_name)
    team = str(team_abbr or "").upper()
    by_key = idx.get("by_key") or {}
    prefix = f"{season}|{week}|{pkey}|"
    candidates = [row for key, row in by_key.items() if key.startswith(prefix)]
    if not candidates:
        return None
    if team:
        for row in candidates:
            sides = {
                str(row.get("home_abbr") or "").upper(),
                str(row.get("away_abbr") or "").upper(),
                str(row.get("team_abbr") or "").upper(),
            }
            if team in sides and row.get("line") is not None:
                return float(row["line"])
    row = candidates[0]
    return float(row["line"]) if row.get("line") is not None else None


def rebuild_lines_index_from_cache(
    *,
    seasons: list[int],
) -> dict[str, Any]:
    """Re-walk schedule using only SQLite cache; rewrite pass_yds_lines.json."""
    games = schedule_reg_games(seasons)
    by_day: dict[date, list[dict[str, Any]]] = {}
    for g in games:
        by_day.setdefault(g["gameday"], []).append(g)

    rows: list[dict[str, Any]] = []
    row_by_key: dict[str, Any] = {}
    matched = 0
    missing_events = 0
    missing_props = 0
    for day in sorted(by_day.keys()):
        events, _ = fetch_historical_events(day, cache_only=True)
        if not events:
            missing_events += len(by_day[day])
            continue
        for game in by_day[day]:
            ev = match_event(game, events)
            if not ev:
                missing_events += 1
                continue
            matched += 1
            event_id = str(ev.get("id") or "")
            commence = str(ev.get("commence_time") or "")
            odds, _ = fetch_event_pass_yds(event_id, commence, cache_only=True)
            if not odds:
                missing_props += 1
                continue
            for player, meta in extract_pass_yds_lines(odds).items():
                row = {
                    "season": game["season"],
                    "week": game["week"],
                    "gameday": game["gameday"].isoformat(),
                    "event_id": event_id,
                    "home_abbr": game["home_abbr"],
                    "away_abbr": game["away_abbr"],
                    "player_name": player,
                    "player_key": normalize_player_key(player),
                    "team_abbr": "",
                    "line": meta["line"],
                    "line_median": meta.get("line_median"),
                    "book": meta.get("book"),
                    "n_books": meta.get("n_books"),
                    "source": "odds_api_historical",
                }
                key = _line_key(row)
                if not key:
                    continue
                # Prefer first; allow overwrite with same key
                if key not in row_by_key:
                    rows.append(row)
                row_by_key[key] = row

    payload = {
        "version": 1,
        "seasons": seasons,
        "lines": list(row_by_key.values()),
        "source": "rebuild_from_cache",
    }
    path = save_lines_index(payload)
    return {
        "games": len(games),
        "games_matched": matched,
        "missing_events": missing_events,
        "missing_props": missing_props,
        "lines": len(row_by_key),
        "unique_events": len({r["event_id"] for r in row_by_key.values()}),
        "index_path": str(path),
    }


def _team_for_player(
    player_name: str,
    event: dict[str, Any],
    game: dict[str, Any],
) -> str:
    """Best-effort team abbr: prefer home/away from matching roster not available — leave blank."""
    _ = player_name, event
    return ""


def backfill_pass_yds_odds(
    *,
    seasons: list[int],
    max_credits: int = 5000,
    cache_only: bool = False,
    dry_run: bool = False,
    skip_indexed: bool = True,
) -> dict[str, Any]:
    """Fetch + index historical pass-yards lines under a credit budget."""
    games = schedule_reg_games(seasons)
    index = load_lines_index()
    existing_keys = set((index.get("by_key") or {}).keys())

    # Group by gameday
    by_day: dict[date, list[dict[str, Any]]] = {}
    for g in games:
        by_day.setdefault(g["gameday"], []).append(g)

    plan_events = 0
    plan_props = 0
    # Estimate uncached work
    for day, day_games in sorted(by_day.items()):
        events_cached = (
            get_cached(
                "hist_nfl_events",
                {
                    "date": f"{day.isoformat()}T16:00:00Z",
                    "dateFormat": "iso",
                },
            )
            is not None
        )
        if not events_cached:
            plan_events += 1
        # props estimate: assume each game needs a call unless indexed
        for g in day_games:
            # Without event id yet, count as needed if season/week not fully covered
            # Conservative: count game if no indexed line for either team that week
            if skip_indexed:
                # We'll know after events match; count as potential
                plan_props += 1
            else:
                plan_props += 1

    report: dict[str, Any] = {
        "seasons": seasons,
        "games": len(games),
        "gamedays": len(by_day),
        "est_credits_upper": plan_events * CREDITS_EVENTS + plan_props * CREDITS_PROPS,
        "max_credits": max_credits,
        "dry_run": dry_run,
        "cache_only": cache_only,
        "credits_spent": 0,
        "events_calls": 0,
        "props_calls": 0,
        "props_cached_hits": 0,
        "games_matched": 0,
        "lines_added": 0,
        "lines_total": len(index.get("lines") or []),
    }

    if dry_run:
        # Refine estimate: days uncached + games without any indexed line for that matchup week
        uncached_days = 0
        need_props = 0
        for day, day_games in by_day.items():
            if (
                get_cached(
                    "hist_nfl_events",
                    {"date": f"{day.isoformat()}T16:00:00Z", "dateFormat": "iso"},
                )
                is None
            ):
                uncached_days += 1
            for g in day_games:
                # skip if we already have ≥1 line for this season/week/home or away
                has = False
                if skip_indexed:
                    for key in existing_keys:
                        if key.startswith(f"{g['season']}|{g['week']}|") and (
                            key.endswith(f"|{g['home_abbr']}")
                            or key.endswith(f"|{g['away_abbr']}")
                        ):
                            has = True
                            break
                if not has:
                    need_props += 1
        report["est_uncached_event_days"] = uncached_days
        report["est_uncached_prop_games"] = need_props
        report["est_credits"] = (
            uncached_days * CREDITS_EVENTS + need_props * CREDITS_PROPS
        )
        return report

    credits_left = max_credits
    lines_rows: list[dict[str, Any]] = list(index.get("lines") or [])
    # de-dupe map
    row_by_key = dict(index.get("by_key") or {})
    indexed_events = {
        str(r.get("event_id")) for r in row_by_key.values() if r.get("event_id")
    }

    stopped = False
    for day in sorted(by_day.keys()):
        events, cost = fetch_historical_events(
            day,
            cache_only=cache_only or (credits_left < CREDITS_EVENTS and not cache_only),
        )
        if cost:
            report["events_calls"] += 1
            report["credits_spent"] += cost
            credits_left -= cost

        for game in by_day[day]:
            if credits_left < CREDITS_PROPS and not cache_only:
                report["stopped_reason"] = "max_credits"
                stopped = True
                break
            ev = match_event(game, events)
            if not ev:
                continue
            report["games_matched"] += 1
            event_id = str(ev.get("id") or "")
            commence = str(ev.get("commence_time") or "")
            if not event_id or not commence:
                continue

            if skip_indexed and event_id in indexed_events:
                report["props_cached_hits"] += 1
                continue

            odds, cost = fetch_event_pass_yds(
                event_id,
                commence,
                cache_only=cache_only
                or (credits_left < CREDITS_PROPS and not cache_only),
            )
            if cost:
                report["props_calls"] += 1
                report["credits_spent"] += cost
                credits_left -= cost
            elif odds is not None:
                report["props_cached_hits"] += 1
            if not odds:
                continue

            extracted = extract_pass_yds_lines(odds)
            for player, meta in extracted.items():
                row = {
                    "season": game["season"],
                    "week": game["week"],
                    "gameday": game["gameday"].isoformat(),
                    "event_id": event_id,
                    "home_abbr": game["home_abbr"],
                    "away_abbr": game["away_abbr"],
                    "player_name": player,
                    "player_key": normalize_player_key(player),
                    "team_abbr": "",
                    "line": meta["line"],
                    "line_median": meta.get("line_median"),
                    "book": meta.get("book"),
                    "n_books": meta.get("n_books"),
                    "source": "odds_api_historical",
                }
                key = _line_key(row)
                if key and key not in row_by_key:
                    row_by_key[key] = row
                    lines_rows.append(row)
                    report["lines_added"] += 1
            indexed_events.add(event_id)

        if stopped:
            break

    index["lines"] = lines_rows
    index["seasons"] = seasons
    index["credits_spent_last_run"] = report["credits_spent"]
    path = save_lines_index(index)
    report["index_path"] = str(path)
    report["lines_total"] = len(row_by_key)
    report["credits_remaining_budget"] = credits_left
    return report


def assign_teams_from_actuals(
    *,
    seasons: list[int] | None = None,
) -> dict[str, int]:
    """Refine team_abbr on index rows using pred_qb_actuals names (optional)."""
    from app.core.database import SessionLocal
    from app.models.predictions_models import QBActuals

    index = load_lines_index()
    session = SessionLocal()
    updated = 0
    try:
        q = session.query(QBActuals)
        if seasons:
            q = q.filter(QBActuals.season.in_(seasons))
        actuals = q.all()
        by_sw_key: dict[tuple[int, int, str], str] = {}
        for a in actuals:
            pk = normalize_player_key(a.qb_player_name or "")
            if not pk:
                continue
            by_sw_key[(int(a.season), int(a.week), pk)] = str(a.team_name or "").upper()

        new_rows = []
        seen = set()
        for row in index.get("lines") or []:
            pk = row.get("player_key") or normalize_player_key(
                row.get("player_name") or ""
            )
            team = by_sw_key.get((int(row["season"]), int(row["week"]), pk))
            if team:
                row = dict(row)
                row["team_abbr"] = team
                row["player_key"] = pk
                updated += 1
            key = _line_key(row)
            if key and key not in seen:
                seen.add(key)
                new_rows.append(row)
        index["lines"] = new_rows
        save_lines_index(index)
    finally:
        session.close()
    return {"updated": updated, "lines": len(index.get("lines") or [])}
