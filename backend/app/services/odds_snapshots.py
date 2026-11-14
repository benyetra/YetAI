"""Line-snapshot store: every Odds API odds payload the ETL already fetches, kept per book.

``record_response`` is called by ``odds_api_sync.sync_odds_get`` for each successful
american-odds response from ``/v4/sports/{sport}/odds`` or
``/v4/sports/{sport}/events/{id}/odds``, so capture costs no extra credits. Rows are
append-only observations; a fetch that sees exactly what the latest observation of an
identity (event, market, player, book) saw only moves its ``last_seen_at``.

Definitions (plan.md section 1): opening = earliest observation held; at projection = the
latest observation first seen at or before ``projected_at``; closing = the latest observation
first seen before the game's ``commence_time``.
"""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, Optional
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from app.services.odds_math import Quote

logger = logging.getLogger(__name__)

EASTERN = ZoneInfo("America/New_York")
_ODDS_PATH = re.compile(r"/v4/sports/([^/]+)/(?:events/[^/]+/)?odds/?$")
_OVER = {"Over": "over_price", "Yes": "over_price"}
_UNDER = {"Under": "under_price", "No": "under_price"}
_VALUES = ("line", "over_price", "under_price", "home_price", "away_price")


def enabled() -> bool:
    return os.getenv("ODDS_SNAPSHOTS_ENABLED", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _naive_utc(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _price(v: Any) -> Optional[int]:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _point(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def player_key(name: Optional[str]) -> str:
    from app.services.etl.nba._api_sports import normalize_player_name

    return normalize_player_name(name) if name else ""


def parse_event(sport: str, event: dict) -> list[dict]:
    """Snapshot row dicts (no timestamps of ours) for one Odds API event payload."""
    commence = _naive_utc(event.get("commence_time"))
    game_day = (
        commence.replace(tzinfo=timezone.utc).astimezone(EASTERN).date()
        if commence
        else None
    )
    home, away = event.get("home_team"), event.get("away_team")
    base = {
        "sport": sport,
        "event_id": event.get("id"),
        "commence_time": commence,
        "game_date": game_day,
        "home_team": home,
        "away_team": away,
    }
    if not base["event_id"]:
        return []
    rows: list[dict] = []
    for bk in event.get("bookmakers") or []:
        book = (bk.get("key") or "").strip().lower()
        if not book:
            continue
        for mkt in bk.get("markets") or []:
            market = mkt.get("key")
            if not market:
                continue
            head = {
                **base,
                "market": market,
                "book": book,
                "book_updated_at": _naive_utc(mkt.get("last_update")),
            }
            outcomes = mkt.get("outcomes") or []
            if market in ("h2h", "spreads"):
                row = {**head, "player_name": None, "player_key": "", "line": None}
                for o in outcomes:
                    side = {home: "home", away: "away"}.get(o.get("name"))
                    if side is None:
                        continue  # draw, or a name that matches neither team
                    row[f"{side}_price"] = _price(o.get("price"))
                    if market == "spreads" and side == "home":
                        row["line"] = _point(o.get("point"))
                if (
                    row.get("home_price") is not None
                    or row.get("away_price") is not None
                ):
                    rows.append(row)
                continue
            grouped: dict[tuple, dict] = {}
            for o in outcomes:
                col = _OVER.get(o.get("name")) or _UNDER.get(o.get("name"))
                if col is None:
                    continue
                who = o.get("description")
                key = (who or "", _point(o.get("point")))
                row = grouped.setdefault(
                    key,
                    {
                        **head,
                        "player_name": who,
                        "player_key": player_key(who),
                        "line": key[1],
                    },
                )
                row[col] = _price(o.get("price"))
            rows.extend(grouped.values())
    return rows


def parse_payload(sport: str, data: Any) -> list[dict]:
    events = (
        data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    )
    out: list[dict] = []
    for ev in events:
        if isinstance(ev, dict):
            out.extend(parse_event(sport, ev))
    return out


def _identity(r) -> tuple:
    get = r.get if isinstance(r, dict) else lambda k: getattr(r, k)
    return (get("event_id"), get("market"), get("player_key") or "", get("book"))


def _values(r) -> tuple:
    get = r.get if isinstance(r, dict) else lambda k: getattr(r, k)
    return tuple(get(k) for k in _VALUES)


def record_rows(db, rows: list[dict], now: Optional[datetime] = None) -> dict:
    """Insert changed observations, touch unchanged ones; commits. Returns counts."""
    from app.models.predictions_models import OddsLineSnapshot as S

    now = now or datetime.utcnow()
    if not rows:
        return {"inserted": 0, "touched": 0}
    new_by_id: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        new_by_id[_identity(r)].append(r)
    events = {k[0] for k in new_by_id}
    markets = {k[1] for k in new_by_id}
    latest: dict[tuple, list] = {}
    for s in db.query(S).filter(S.event_id.in_(events), S.market.in_(markets)).all():
        k = _identity(s)
        cur = latest.get(k)
        if cur is None or s.first_seen_at > cur[0].first_seen_at:
            latest[k] = [s]
        elif s.first_seen_at == cur[0].first_seen_at:
            cur.append(s)
    inserted = touched = 0
    for k, new in new_by_id.items():
        prev = latest.get(k)
        new_vals = {_values(r) for r in new}
        if prev is not None and {_values(s) for s in prev} == new_vals:
            for s in prev:
                s.last_seen_at = now
            touched += len(prev)
            continue
        seen = set()
        for r in new:
            if _values(r) in seen:
                continue
            seen.add(_values(r))
            db.add(S(**r, first_seen_at=now, last_seen_at=now))
            inserted += 1
    db.commit()
    return {"inserted": inserted, "touched": touched}


def record_response(
    url: str, params: Optional[dict], data: Any, now: Optional[datetime] = None
) -> Optional[dict]:
    """Record one Odds API response if it is an american-odds odds payload; never raises."""
    if not enabled():
        return None
    try:
        parsed = urlparse(url)
        m = _ODDS_PATH.search(parsed.path)
        if not m or "/historical/" in parsed.path:
            return None
        query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
        fmt = (params or {}).get("oddsFormat") or query.get("oddsFormat")
        if fmt != "american":
            return None
        rows = parse_payload(m.group(1), data)
        if not rows:
            return None
        from app.core.database import SessionLocal

        if SessionLocal is None:
            return None
        db = SessionLocal()
        try:
            return record_rows(db, rows, now)
        finally:
            db.close()
    except Exception:
        logger.exception("odds_snapshots: could not record %s", url.split("?")[0])
        return None


# ---------- reads ----------


def _latest_per_book(rows: Iterable, keep: Callable[[Any], bool]) -> list:
    """Rows of each book's latest observation among ``rows`` passing ``keep``."""
    best: dict[str, list] = {}
    for r in rows:
        if not keep(r):
            continue
        cur = best.get(r.book)
        if cur is None or r.first_seen_at > cur[0].first_seen_at:
            best[r.book] = [r]
        elif r.first_seen_at == cur[0].first_seen_at:
            cur.append(r)
    return [r for obs in best.values() for r in obs]


def _rows(db, start: date, end: date, markets: Iterable[str], player_keys=None):
    from app.models.predictions_models import OddsLineSnapshot as S

    q = db.query(S).filter(
        S.game_date >= start, S.game_date <= end, S.market.in_(list(markets))
    )
    if player_keys is not None:
        q = q.filter(S.player_key.in_(list(player_keys)))
    return q.all()


def closing_index(
    db, start: date, end: date, markets: Iterable[str]
) -> dict[tuple, list]:
    """{(game_date, market, player_key, event_id): closing rows, one observation per book}
    for games on [start, end]; only observations first seen before the start count."""
    groups: dict[tuple, list] = defaultdict(list)
    for r in _rows(db, start, end, markets):
        groups[(r.game_date, r.market, r.player_key, r.event_id)].append(r)
    out = {}
    for k, rows in groups.items():
        close = _latest_per_book(
            rows,
            lambda r: r.commence_time is not None and r.first_seen_at < r.commence_time,
        )
        if close:
            out[k] = close
    return out


def closing_quotes(db, game_date: date, market: str, name_or_key: str) -> list:
    """Closing rows (one observation per book) for one player prop on one date."""
    key = player_key(name_or_key)
    idx = closing_index(db, game_date, game_date, [market])
    return [r for (d, m, p, _e), rows in idx.items() if p == key for r in rows]


def quotes_at(db, game_date: date, market: str, name_or_key: str, at: datetime) -> list:
    """Each book's observation in effect at ``at`` (first seen at or before it)."""
    key = player_key(name_or_key)
    rows = _rows(db, game_date, game_date, [market], [key])
    return _latest_per_book(rows, lambda r: r.first_seen_at <= at)


def to_quotes(rows: Iterable) -> list[Quote]:
    return [Quote(r.book, r.line, r.over_price, r.under_price) for r in rows]
