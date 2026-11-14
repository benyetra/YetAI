#!/usr/bin/env python3
"""Historical NBA player-prop odds backfill: estimate / fetch raw files / load / summary.

Usage (from backend/):

    PYTHONPATH=. .venv/bin/python scripts/odds_history_backfill.py estimate [--quota]
    PYTHONPATH=. .venv/bin/python scripts/odds_history_backfill.py fetch --out DIR \\
        [--apply] [--floor 25000] [--rate 4] [--max-calls N]
    PYTHONPATH=. .venv/bin/python scripts/odds_history_backfill.py load --dir DIR [--apply]
    PYTHONPATH=. .venv/bin/python scripts/odds_history_backfill.py summary

Design args (estimate, fetch): --from 2025-11-01 --to 2026-04-12
--markets player_rebounds,player_assists --snapshots T-600,T-360,T-5 --bookmakers <10 books>.

Cost: events call = 1 per game date; event-odds call = 10 x markets returned x regions
(<= 10 bookmakers = 1 region). Games come from the DB (box scores), so planning is free.
Raw responses are saved as DIR/events/<d>.json and DIR/odds/<d>/<event>__<tag>.json; `load`
replays them through odds_snapshots.parse_historical + record_rows. The API key is read
from env ODDS_API_KEY, sent only in request params, and never logged or written.
Exit codes: 2 refused (load on a non-local DB), 3 credit floor reached, 4 cost mismatch.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import requests  # noqa: E402

from scripts._bootstrap_env import bootstrap_env  # noqa: E402

logger = logging.getLogger("odds_history_backfill")

API = "https://api.the-odds-api.com/v4"
SPORT = "basketball_nba"
DEFAULT_BOOKS = (
    "fanduel,draftkings,betmgm,williamhill_us,espnbet,betrivers,hardrockbet,"
    "pinnacle,novig,prophetx"
)
DEFAULT_MARKETS = "player_rebounds,player_assists"
DEFAULT_SNAPS = "T-600,T-360,T-5"
SEASON = ("2025-10-21", "2026-06-30")
HEADERS = ("x-requests-last", "x-requests-used", "x-requests-remaining")
BACKOFF = (2, 4, 8, 16, 32)


class Stop(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg


# ---------- planning (pure) ----------


def norm_team(name: str) -> str:
    n = (name or "").strip()
    return "LA Clippers" if n == "Los Angeles Clippers" else n


def regions_for(n_books: int) -> int:
    return max(1, math.ceil(n_books / 10))


def snap_minutes(tag: str) -> int:
    return int(tag.split("-", 1)[1])


def credits(n_dates: int, n_games: int, markets: int, snaps: int, regions: int) -> dict:
    odds_calls = n_games * snaps
    odds = 10 * markets * regions * odds_calls
    return {
        "events_calls": n_dates,
        "odds_calls": odds_calls,
        "events_credits": n_dates,
        "odds_credits": odds,
        "total": n_dates + odds,
    }


def games_in(games: list[dict], start: str, end: str) -> list[dict]:
    return [g for g in games if start <= g["date"].isoformat() <= end]


def plan_credits(games: list[dict], markets: int, snaps: int, regions: int) -> dict:
    return credits(len({g["date"] for g in games}), len(games), markets, snaps, regions)


def menu(games: list[dict], args, remaining: int, floor: int) -> list[tuple]:
    """[(label, games, markets, snaps, credits, fits)] for the standard menu."""
    reg = regions_for(len(args.bookmakers.split(",")))
    season = games_in(games, *SEASON)
    chosen = games_in(games, args.date_from, args.date_to)
    nm, ns = len(args.markets.split(",")), len(args.snapshots.split(","))
    rows = []
    for scope, gs in (("season", season), ("range", chosen)):
        for label, m, s in (
            ("minimum (reb+ast, T-360,T-5)", 2, 2),
            ("recommended (reb+ast, T-600,T-360,T-5)", 2, 3),
            ("full (+points)", 3, 3),
            ("chosen (args)", nm, ns),
        ):
            c = plan_credits(gs, m, s, reg)["total"]
            rows.append((f"{scope}: {label}", len(gs), m, s, c, c <= remaining - floor))
    return rows


def marginals(games: list[dict], args) -> list[tuple]:
    reg = regions_for(len(args.bookmakers.split(",")))
    gs = games_in(games, args.date_from, args.date_to)
    nm, ns = len(args.markets.split(",")), len(args.snapshots.split(","))
    base = plan_credits(gs, nm, ns, reg)
    per_market = 10 * reg * len(gs) * ns
    out = [
        (f"+{m}", per_market)
        for m in (
            "player_points",
            "player_threes",
            "player_points_rebounds_assists",
            "player_steals",
            "player_blocks",
        )
    ]
    out.append(("+1 snapshot", 10 * nm * reg * len(gs)))
    out.append(("+1 region", base["odds_credits"]))
    return out


# ---------- games from the DB ----------


def load_games(db, start: date, end: date) -> list[dict]:
    """[{date, home}] one per game with box scores: the home team = the away rows' opponent."""
    from app.models.predictions_models import RecentGames as G
    from app.models.predictions_models import TeamOffenseStats as T

    q = (
        db.query(G.game_date, T.team_name)
        .join(T, T.team_id == G.opponent_team_id)
        .filter(G.home_game.is_(False), G.game_date >= start, G.game_date <= end)
        .distinct()
    )
    return sorted(
        ({"date": d, "home": norm_team(n)} for d, n in q),
        key=lambda g: (g["date"], g["home"]),
    )


# ---------- HTTP + raw files ----------


def _write_atomic(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj))
    os.replace(tmp, path)


def _done(path: Path) -> bool:
    try:
        st = json.loads(path.read_text()).get("status")
    except (OSError, ValueError):
        return False
    return st == 200 or (isinstance(st, int) and 400 <= st < 500 and st != 429)


def markets_returned(body) -> int:
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return 0
    return len(
        {
            m.get("key")
            for b in data.get("bookmakers") or []
            for m in b.get("markets") or []
        }
    )


class Fetcher:
    def __init__(self, out: Path, args, key: str):
        self.out, self.args, self.key = out, args, key
        self.regions = regions_for(len(args.bookmakers.split(",")))
        self.interval = 1.0 / max(args.rate, 0.01)
        self.last_call = 0.0
        self.remaining: int | None = None
        self.paid = 0  # http calls made
        self.actual = self.upper = 0
        self.giveups = 0
        self.log_path = out / "calls.csv"

    def _pace(self) -> None:
        wait = self.last_call + self.interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last_call = time.monotonic()

    def call(self, kind: str, path: str, params: dict, file: Path, expected: int):
        """One paid HTTP call; returns the saved record (or None when given up)."""
        a = self.args
        if self.remaining is not None and self.remaining - expected < a.floor:
            raise Stop(
                3,
                f"stop: remaining {self.remaining} - cost {expected} < floor {a.floor}",
            )
        if a.max_calls is not None and self.paid >= a.max_calls:
            raise Stop(0, f"stop: --max-calls {a.max_calls} reached")
        resp = None
        for attempt in range(len(BACKOFF) + 1):
            self._pace()
            try:
                resp = requests.get(
                    API + path, params={**params, "apiKey": self.key}, timeout=60
                )
            except requests.RequestException as e:
                logger.warning("%s %s failed: %s", kind, path, type(e).__name__)
                return None
            self.paid += 1
            if resp.status_code != 429:
                break
            if attempt < len(BACKOFF):
                logger.warning("429 on %s, sleeping %ss", path, BACKOFF[attempt])
                time.sleep(BACKOFF[attempt])
        if resp.status_code == 429:
            self.giveups += 1
            logger.warning("giving up on %s after 429s", path)
            return None
        hdr = {h: resp.headers.get(h) for h in HEADERS}
        try:
            body = resp.json()
        except ValueError:
            body = None
        rec = {
            "kind": kind,
            "path": path,
            "params": params,
            "status": resp.status_code,
            "headers": hdr,
            "fetched_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "body": body,
        }
        _write_atomic(file, rec)
        try:
            self.remaining = int(hdr["x-requests-remaining"])
        except (TypeError, ValueError):
            pass
        n = markets_returned(body) if kind == "odds" else ""
        with open(self.log_path, "a", newline="") as f:
            csv.writer(f).writerow(
                [
                    rec["fetched_at"],
                    kind,
                    str(file.relative_to(self.out)),
                    resp.status_code,
                    expected,
                    hdr["x-requests-last"],
                    hdr["x-requests-used"],
                    hdr["x-requests-remaining"],
                    n,
                ]
            )
        if kind == "odds" and resp.status_code == 200:
            exp = 10 * n * self.regions
            self.actual += int(hdr["x-requests-last"] or 0)
            self.upper += expected
            if str(exp) != str(hdr["x-requests-last"]):
                raise Stop(
                    4,
                    f"stop: cost mismatch, expected {exp} "
                    f"(markets {n} x regions {self.regions}), x-requests-last "
                    f"{hdr['x-requests-last']}",
                )
        if self.paid % 50 == 0:
            ratio = self.actual / self.upper if self.upper else 0
            print(
                f"[{self.paid} calls] actual/upper-bound {ratio:.3f} "
                f"used {hdr['x-requests-used']} remaining {hdr['x-requests-remaining']}"
            )
        return rec


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def events_params(d: date) -> dict:
    t = datetime(d.year, d.month, d.day)
    return {
        "date": _iso(t + timedelta(hours=14)),
        "commenceTimeFrom": _iso(t + timedelta(hours=10)),
        "commenceTimeTo": _iso(t + timedelta(days=1, hours=9, minutes=59, seconds=59)),
    }


def run_fetch(games: list[dict], out: Path, args, key: str) -> int:
    f = Fetcher(out, args, key)
    tags = args.snapshots.split(",")
    reg = f.regions
    per_call = 10 * len(args.markets.split(",")) * reg
    by_date: dict[date, set] = defaultdict(set)
    for g in games:
        by_date[g["date"]].add(g["home"])
    out.mkdir(parents=True, exist_ok=True)
    unmatched: list[tuple] = []
    try:
        for d in sorted(by_date):
            efile = out / "events" / f"{d}.json"
            rec = None
            if _done(efile):
                rec = json.loads(efile.read_text())
            else:
                rec = f.call(
                    "events",
                    f"/historical/sports/{SPORT}/events",
                    events_params(d),
                    efile,
                    1,
                )
            events = []
            if rec and isinstance(rec.get("body"), dict):
                events = rec["body"].get("data") or []
            homes = {norm_team(e.get("home_team")): e for e in events}
            for h in sorted(by_date[d] - set(homes)):
                unmatched.append((d, "game_without_event", h))
            for h in sorted(set(homes) - by_date[d]):
                unmatched.append((d, "event_without_game", h))
            for h in sorted(by_date[d] & set(homes)):
                ev = homes[h]
                commence = datetime.strptime(ev["commence_time"], "%Y-%m-%dT%H:%M:%SZ")
                for tag in tags:
                    ofile = out / "odds" / str(d) / f"{ev['id']}__{tag}.json"
                    if _done(ofile):
                        continue
                    params = {
                        "date": _iso(commence - timedelta(minutes=snap_minutes(tag))),
                        "regions": ",".join(
                            ["us"] if reg == 1 else ["us", "us2"][:reg]
                        ),
                        "markets": args.markets,
                        "bookmakers": args.bookmakers,
                        "oddsFormat": "american",
                    }
                    f.call(
                        "odds",
                        f"/historical/sports/{SPORT}/events/{ev['id']}/odds",
                        params,
                        ofile,
                        per_call,
                    )
        code, msg = 0, "fetch complete"
    except Stop as s:
        code, msg = s.code, s.msg
    with open(out / "unmatched.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "kind", "home_team"])
        w.writerows(unmatched)
    print(
        f"{msg}; http calls {f.paid}, 429 give-ups {f.giveups}, unmatched {len(unmatched)}, "
        f"remaining {f.remaining}"
    )
    return code


# ---------- load ----------


def check_db_host(url: str, allow_prod: bool) -> None:
    host = (urlparse(url or "").hostname or "").lower()
    if host not in ("localhost", "127.0.0.1") and not allow_prod:
        raise Stop(2, f"refusing to load into host {host!r}; pass --i-mean-production")


def load_dir(db, directory: Path, apply: bool) -> dict:
    from app.models.predictions_models import OddsLineSnapshot as S
    from app.services import odds_snapshots as snaps

    parsed = []
    for p in sorted(directory.glob("odds/*/*.json")):
        rec = json.loads(p.read_text())
        if rec.get("status") != 200:
            continue
        ts, rows = snaps.parse_historical(SPORT, rec.get("body"))
        if ts is None or not rows:
            continue
        parsed.append((rows[0]["event_id"], ts, rows))
    parsed.sort(key=lambda x: (x[0], x[1]))
    c = {
        "files": len(parsed),
        "loaded": 0,
        "already_loaded": 0,
        "inserted": 0,
        "touched": 0,
    }
    for eid, ts, rows in parsed:
        markets = {r["market"] for r in rows}
        seen = (
            db.query(S.id)
            .filter(S.event_id == eid, S.market.in_(markets), S.last_seen_at >= ts)
            .first()
        )
        if seen:
            c["already_loaded"] += 1
            continue
        c["loaded"] += 1
        if apply:
            res = snaps.record_rows(db, rows, now=ts)
        else:
            res = {"inserted": len(rows), "touched": 0}
        c["inserted"] += res["inserted"]
        c["touched"] += res["touched"]
    return c


# ---------- summary ----------


def summarize(db) -> list[str]:
    from app.models.predictions_models import OddsLineSnapshot as S

    q = db.query(
        S.book, S.market, S.game_date, S.event_id, S.first_seen_at, S.last_seen_at
    ).filter(S.sport == SPORT)
    cells: dict[tuple, list] = defaultdict(lambda: [0, set()])
    times: dict[str, set] = defaultdict(set)
    for book, market, gd, eid, first, last in q:
        key = (book, market, gd.strftime("%Y-%m") if gd else "?")
        cells[key][0] += 1
        cells[key][1].add(eid)
        times[eid].update((first, last))
    lines = [f"{'book':<16}{'market':<34}{'month':<9}{'rows':>8}{'events':>8}"]
    for (book, market, month), (n, evs) in sorted(cells.items()):
        lines.append(f"{book:<16}{market:<34}{month:<9}{n:>8}{len(evs):>8}")
    med = statistics.median(len(v) for v in times.values()) if times else 0
    lines.append(f"events {len(times)}; median distinct snapshot times per event {med}")
    return lines


# ---------- CLI ----------


def _design(p) -> None:
    p.add_argument("--from", dest="date_from", default="2025-11-01")
    p.add_argument("--to", dest="date_to", default="2026-04-12")
    p.add_argument("--markets", default=DEFAULT_MARKETS)
    p.add_argument("--snapshots", default=DEFAULT_SNAPS)
    p.add_argument("--bookmakers", default=DEFAULT_BOOKS)


def _session():
    from app.core.database import SessionLocal

    if SessionLocal is None:
        raise SystemExit("no DATABASE_URL configured")
    return SessionLocal()


def _key() -> str:
    key = (os.environ.get("ODDS_API_KEY") or "").strip()
    if not key:
        from app.core.config import settings

        key = (settings.ODDS_API_KEY or "").strip()
    if not key:
        raise SystemExit("ODDS_API_KEY is not set")
    return key


def _quota() -> dict:
    r = requests.get(f"{API}/sports", params={"apiKey": _key()}, timeout=30)
    return {h: r.headers.get(h) for h in HEADERS}


def cmd_estimate(args) -> int:
    reg = regions_for(len(args.bookmakers.split(",")))
    quota = None
    if args.quota:
        quota = _quota()
        print("quota:", quota)
    remaining = args.quota_remaining
    if remaining is None:
        remaining = int(quota["x-requests-remaining"]) if quota else 100000
    db = _session()
    try:
        games = load_games(
            db, date.fromisoformat(SEASON[0]), date.fromisoformat(SEASON[1])
        )
    finally:
        db.close()
    chosen = games_in(games, args.date_from, args.date_to)
    nm, ns = len(args.markets.split(",")), len(args.snapshots.split(","))
    c = plan_credits(chosen, nm, ns, reg)
    print(
        f"games {len(chosen)} on {c['events_calls']} dates; events calls {c['events_calls']} "
        f"({c['events_credits']} credits); odds calls {c['odds_calls']}; regions {reg}; "
        f"odds credits (upper bound) {c['odds_credits']}; total {c['total']}"
    )
    print(
        f"budget: remaining {remaining} - floor {args.floor} = {remaining - args.floor}"
    )
    print(f"\n{'option':<52}{'games':>6}{'mkts':>5}{'snaps':>6}{'credits':>9}  fits")
    for label, n, m, s, cr, fits in menu(games, args, remaining, args.floor):
        print(f"{label:<52}{n:>6}{m:>5}{s:>6}{cr:>9}  {'yes' if fits else 'no'}")
    print("\nmarginal credits on the chosen range:")
    for label, cr in marginals(games, args):
        print(f"  {label:<36}{cr:>9}")
    return 0


def cmd_fetch(args) -> int:
    db = _session()
    try:
        games = games_in(
            load_games(
                db, date.fromisoformat(args.date_from), date.fromisoformat(args.date_to)
            ),
            args.date_from,
            args.date_to,
        )
    finally:
        db.close()
    reg = regions_for(len(args.bookmakers.split(",")))
    nm, tags = len(args.markets.split(",")), args.snapshots.split(",")
    c = plan_credits(games, nm, len(tags), reg)
    if not args.apply:
        print(
            f"dry run: {len(games)} games, {c['events_calls']} events calls, "
            f"{c['odds_calls']} odds calls, <= {c['total']} credits (floor {args.floor})"
        )
        planned = [f"events {d}" for d in sorted({g["date"] for g in games})]
        planned += [f"odds {g['date']} {g['home']} {t}" for g in games for t in tags]
        for line in planned[:10]:
            print("  ", line)
        return 0
    return run_fetch(games, Path(args.out), args, _key())


def cmd_load(args) -> int:
    check_db_host(os.environ.get("DATABASE_URL", ""), args.i_mean_production)
    db = _session()
    try:
        c = load_dir(db, Path(args.dir), args.apply)
    finally:
        db.close()
    mode = "applied" if args.apply else "dry run (no writes)"
    print(
        f"{mode}: files read {c['files']}, loaded {c['loaded']}, "
        f"already_loaded {c['already_loaded']}, rows inserted {c['inserted']}, "
        f"touched {c['touched']}"
    )
    return 0


def cmd_summary(_args) -> int:
    db = _session()
    try:
        print("\n".join(summarize(db)))
    finally:
        db.close()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("estimate")
    _design(e)
    e.add_argument("--quota", action="store_true")
    e.add_argument("--quota-remaining", type=int, default=None)
    e.add_argument("--floor", type=int, default=25000)
    f = sub.add_parser("fetch")
    _design(f)
    f.add_argument("--out", required=True)
    f.add_argument("--apply", action="store_true")
    f.add_argument("--floor", type=int, default=25000)
    f.add_argument("--rate", type=float, default=4)
    f.add_argument("--max-calls", type=int, default=None)
    ld = sub.add_parser("load")
    ld.add_argument("--dir", required=True)
    ld.add_argument("--apply", action="store_true")
    ld.add_argument("--i-mean-production", action="store_true")
    sub.add_parser("summary")
    args = ap.parse_args(argv)
    bootstrap_env()
    return {
        "estimate": cmd_estimate,
        "fetch": cmd_fetch,
        "load": cmd_load,
        "summary": cmd_summary,
    }[args.cmd](args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    try:
        sys.exit(main())
    except Stop as s:
        print(s.msg, file=sys.stderr)
        sys.exit(s.code)
