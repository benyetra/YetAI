"""Line-residual dataset: one row per lined NBA player-game, features known pre-game.

`load_inputs` reads the tables; `build_rows` (training) and `serve_rows` (today) share
one feature path (`_features`) so train and serve cannot drift. Every feature reads
only box/line/game rows dated strictly before the row's date; the spread and total of
the same game are pre-game market information and are allowed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import inspect, text

LOOKBACK_DAYS = 120
STAT_COLUMN = {"rebounds": "rebounds", "assists": "assists"}
PROJECTION_TABLE = {
    "rebounds": "pred_rebounds_projections",
    "assists": "pred_assists_projections",
}

# Odds snapshot table (written by the odds-capture work). Schema not final: the
# mapping and the query live here only. Values are the table's column names; the
# optional ones (game_start, is_closing) may be absent from the table.
ODDS_SNAPSHOT_TABLE = "nba_prop_odds_snapshots"
ODDS_SNAPSHOT_COLUMNS = {
    "game_date": "game_date",
    "stat": "stat",
    "player_id": "player_id",
    "line": "line",
    "over_price": "over_price",
    "under_price": "under_price",
    "snapshot_at": "snapshot_at",
    "game_start": "game_start",  # optional: pre-game filter
    "is_closing": "is_closing",  # optional: marks the closing line
}
_OPTIONAL_SNAPSHOT = ("game_start", "is_closing")

FEATURE_FAMILIES = {
    "line_": ["line_line", "line_minus_l10", "line_over_l10"],
    "hist_": ["hist_n_prior", "hist_resid_l10_shrunk", "hist_over_rate_shrunk"],
    "form_": [
        "form_l5",
        "form_l10",
        "form_season",
        "form_l5_minus_season",
        "form_rate_l10",
    ],
    "min_": ["min_l5", "min_last_minus_season", "min_l3_minus_l10", "min_starter"],
    "team_": [
        "team_n_out",
        "team_out_minutes",
        "team_out_stat",
        "team_with_without",
    ],
    "opp_": ["opp_allowed_rel", "opp_pace"],
    "game_": ["game_abs_spread", "game_is_fav", "game_total"],
    "sched_": ["sched_rest_days", "sched_b2b", "sched_home"],
}
TARGETS = ("actual", "resid", "over")
KEYS = ["date", "player_id", "team_id", "opponent_team_id", "stat"]
LINE_COLS = [
    "line",
    "over_price",
    "under_price",
    "price_side",
    "line_source",
    "close_line",
]


def feature_columns(families=None) -> list[str]:
    fams = (
        FEATURE_FAMILIES
        if families is None
        else {k: FEATURE_FAMILIES[k] for k in families}
    )
    return [c for cols in fams.values() for c in cols]


# ---------------------------------------------------------------- loading


def _norm_team(name) -> str:
    n = str(name).strip()
    return "LA Clippers" if n == "Los Angeles Clippers" else n


def _read(conn, sql: str, **params) -> pd.DataFrame:
    return pd.read_sql(text(sql), conn, params=params)


def _snapshot_query(conn, start: str, end: str) -> pd.DataFrame | None:
    """Rows of the odds snapshot table in canonical column names, or None if absent."""
    insp = inspect(conn)
    if not insp.has_table(ODDS_SNAPSHOT_TABLE):
        return None
    have = {c["name"] for c in insp.get_columns(ODDS_SNAPSHOT_TABLE)}
    cols = {
        k: v
        for k, v in ODDS_SNAPSHOT_COLUMNS.items()
        if k not in _OPTIONAL_SNAPSHOT or v in have
    }
    select = ", ".join(f"{v} AS {k}" for k, v in cols.items())
    dcol = ODDS_SNAPSHOT_COLUMNS["game_date"]
    return _read(
        conn,
        f"SELECT {select} FROM {ODDS_SNAPSHOT_TABLE} WHERE {dcol} >= :s AND {dcol} <= :e",
        s=start,
        e=end,
    )


def _snapshot_lines(snap: pd.DataFrame) -> pd.DataFrame:
    """One row per (stat, player, date): last pre-game snapshot (+ closing line)."""
    if snap is None or snap.empty:
        return pd.DataFrame()
    s = snap.copy()
    s["date"] = pd.to_datetime(s["game_date"])
    s["snapshot_at"] = pd.to_datetime(s["snapshot_at"])
    s = s[(s["line"] > 0) & s["player_id"].notna()]
    if "game_start" in s:
        s = s[s["snapshot_at"] < pd.to_datetime(s["game_start"])]
    closing = (
        s["is_closing"].fillna(False).astype(bool)
        if "is_closing" in s
        else pd.Series(False, index=s.index)
    )
    key = ["stat", "player_id", "date"]
    close = (
        s[closing]
        .sort_values("snapshot_at")
        .drop_duplicates(key, keep="last")
        .set_index(key)["line"]
        .rename("close_line")
    )
    open_ = s[~closing] if (~closing).any() else s
    out = open_.sort_values("snapshot_at").drop_duplicates(key, keep="last")
    out = out.join(close, on=key)
    if "close_line" not in out:
        out["close_line"] = np.nan
    out["price_side"] = "both"
    out["line_source"] = "snapshot"
    out["player_id"] = out["player_id"].astype(int)
    return out[["stat", "player_id", "date", *LINE_COLS]]


def _projection_lines(conn, stat: str, start: str, end: str) -> pd.DataFrame:
    df = _read(
        conn,
        f"SELECT id, player_id, date, fanduel_line, fanduel_price, fanduel_over_under "
        f"FROM {PROJECTION_TABLE[stat]} WHERE date >= :s AND date <= :e AND fanduel_line > 0",
        s=start,
        e=end,
    )
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("id").drop_duplicates(["player_id", "date"], keep="last")
    # stored as 'o' / 'u' in production (tests also use 'Over' / 'Under')
    side = (
        df["fanduel_over_under"]
        .str.lower()
        .str.strip()
        .str[:1]
        .map({"o": "over", "u": "under"})
    )
    price = df["fanduel_price"].astype(float)
    out = pd.DataFrame(
        {
            "stat": stat,
            "player_id": df["player_id"].astype(int),
            "date": df["date"],
            "line": df["fanduel_line"].astype(float),
            "over_price": price.where(side == "over"),
            "under_price": price.where(side == "under"),
            "price_side": side,
            "line_source": "fanduel_projection",
            "close_line": np.nan,
        }
    )
    return out


def load_inputs(conn, start, end) -> dict[str, pd.DataFrame]:
    """Tables for [start - LOOKBACK_DAYS, end]; every frame has a normalised `date`."""
    lo = (pd.Timestamp(start) - pd.Timedelta(days=LOOKBACK_DAYS)).date().isoformat()
    s, e = pd.Timestamp(start).date().isoformat(), pd.Timestamp(end).date().isoformat()
    box = _read(
        conn,
        "SELECT player_id, game_date AS date, opponent_team_id, minutes, rebounds, "
        "assists, points, offensive_rebounds, defensive_rebounds, home_game "
        "FROM pred_recent_games WHERE game_date >= :s AND game_date <= :e",
        s=lo,
        e=e,
    )
    teams = _read(conn, "SELECT team_id, team_name FROM pred_team_offense_stats")
    name_to_id = {_norm_team(n): int(t) for t, n in zip(teams.team_id, teams.team_name)}
    finals = _read(
        conn,
        "SELECT game_date AS date, home_team_name, away_team_name, home_score, "
        "away_score FROM pred_nba_spread_actuals WHERE game_date >= :s AND game_date <= :e",
        s=lo,
        e=e,
    )
    game_lines = _read(
        conn,
        "SELECT game_date AS date, home_team_id, away_team_id, home_team_name, "
        "away_team_name, spread_home, total FROM pred_nba_game_lines "
        "WHERE game_date >= :s AND game_date <= :e",
        s=lo,
        e=e,
    )
    for df in (box, finals, game_lines):
        df["date"] = pd.to_datetime(df["date"])
    finals["home_id"] = finals.home_team_name.map(
        lambda n: name_to_id.get(_norm_team(n))
    )
    finals["away_id"] = finals.away_team_name.map(
        lambda n: name_to_id.get(_norm_team(n))
    )
    for side in ("home", "away"):
        by_name = game_lines[f"{side}_team_name"].map(
            lambda n: name_to_id.get(_norm_team(n))
        )
        game_lines[f"{side}_id"] = game_lines[f"{side}_team_id"].fillna(by_name)
    lines = []
    snap = _snapshot_query(conn, lo, e)
    snap_lines = _snapshot_lines(snap)
    for stat in STAT_COLUMN:
        proj = _projection_lines(conn, stat, lo, e)
        if len(snap_lines):
            sl = snap_lines[snap_lines["stat"] == stat]
            proj = proj.merge(
                sl[["player_id", "date"]],
                on=["player_id", "date"],
                how="left",
                indicator=True,
            )
            proj = proj[proj["_merge"] == "left_only"].drop(columns="_merge")
            proj = pd.concat([proj, sl], ignore_index=True)
        lines.append(proj)
    return {
        "box": box,
        "lines": pd.concat(lines, ignore_index=True),
        "finals": finals,
        "game_lines": game_lines,
        "team_map": teams,
    }


def load_lines(conn, stat: str, start, end) -> pd.DataFrame:
    """Lines of record for ``stat`` (player_id, date, line, prices, line_source) in
    [start, end]: the snapshot table when present, else the projection row's line."""
    ln = load_inputs(conn, start, end)["lines"]
    ln = ln[(ln["stat"] == stat) & (ln["date"] >= pd.Timestamp(start))]
    return ln[ln["date"] <= pd.Timestamp(end)].reset_index(drop=True)


# ---------------------------------------------------------------- context


def _days(s) -> np.ndarray:
    return pd.to_datetime(s).values.astype("datetime64[D]").astype("int64")


def _season_start_day(day: int) -> int:
    ts = pd.Timestamp(np.datetime64(int(day), "D"))
    year = ts.year if ts.month >= 10 else ts.year - 1
    return int(np.datetime64(f"{year}-10-01", "D").astype("int64"))


class _Ctx:
    """Precomputed per-stat lookups over the (already truncated) inputs."""

    def __init__(self, inputs: dict, stat: str):
        self.stat = stat
        col = STAT_COLUMN[stat]
        self.games = _games(inputs)
        long = _long_games(self.games)
        self.long = long
        box = inputs["box"]
        box = box[box["minutes"].fillna(0) > 0].copy()
        box["d"] = _days(box["date"])
        box = box.merge(
            long[["d", "team_id", "opp_id"]].rename(
                columns={"opp_id": "opponent_team_id"}
            ),
            on=["d", "opponent_team_id"],
            how="left",
        )
        box["val"] = box[col].astype(float)
        box = box.drop_duplicates(["player_id", "d"]).sort_values(["player_id", "d"])
        self.box = box
        self.pbox = {p: g.reset_index(drop=True) for p, g in box.groupby("player_id")}
        self.tbox = {
            t: g.sort_values("d").reset_index(drop=True)
            for t, g in box[box.team_id.notna()].groupby("team_id")
        }
        self.tdates = {t: np.sort(g["d"].unique()) for t, g in long.groupby("team_id")}
        self.played = {
            (d, t): frozenset(g["player_id"])
            for (d, t), g in box[box.team_id.notna()].groupby(["d", "team_id"])
        }
        # opponent-allowed: stat summed over players facing each opponent, per game
        al = (
            box[box.opponent_team_id.notna()]
            .groupby(["opponent_team_id", "d"])["val"]
            .sum()
        )
        self.allowed = al.reset_index().rename(columns={"opponent_team_id": "team_id"})
        self.allowed_by_team = {
            t: g.sort_values("d") for t, g in self.allowed.groupby("team_id")
        }
        self.scores = {
            t: g.sort_values("d")
            for t, g in long.dropna(subset=["combined"]).groupby("team_id")
        }
        self.gmeta = long.set_index(["d", "team_id"])
        # lined history: line with actual (box row with minutes > 0), per player
        ln = inputs["lines"]
        ln = ln[ln["stat"] == stat].copy()
        ln["d"] = _days(ln["date"])
        ln = ln.merge(
            box[["player_id", "d", "val"]], on=["player_id", "d"], how="inner"
        )
        ln["r"] = ln["val"] - ln["line"]
        self.lined = {p: g.sort_values("d") for p, g in ln.groupby("player_id")}
        self._reg: dict = {}

    def regulars(self, team, day) -> pd.DataFrame:
        """Teammates who played >= 60% of the team's last 10 games at >= 15 min."""
        key = (team, day)
        if key in self._reg:
            return self._reg[key]
        td = self.tdates.get(team, np.array([], dtype="int64"))
        last = td[
            max(0, np.searchsorted(td, day, "left") - 10) : np.searchsorted(
                td, day, "left"
            )
        ]
        out = pd.DataFrame(columns=["player_id", "mins", "val"])
        if len(last) and team in self.tbox:
            tb = self.tbox[team]
            sub = tb[(tb["d"] >= last[0]) & (tb["d"] < day)]
            g = sub.groupby("player_id").agg(
                n=("d", "size"), mins=("minutes", "mean"), val=("val", "mean")
            )
            out = g[(g["n"] >= 0.6 * len(last)) & (g["mins"] >= 15)].reset_index()
        self._reg[key] = out
        return out


def _games(inputs: dict) -> pd.DataFrame:
    """One row per game: date, home_id, away_id, scores, spread_home, total."""
    f = inputs["finals"][["date", "home_id", "away_id", "home_score", "away_score"]]
    g = inputs["game_lines"][["date", "home_id", "away_id", "spread_home", "total"]]
    f = f.dropna(subset=["home_id", "away_id"]).astype({"home_id": int, "away_id": int})
    g = g.dropna(subset=["home_id", "away_id"]).astype({"home_id": int, "away_id": int})
    games = f.drop_duplicates(["date", "home_id", "away_id"]).merge(
        g.drop_duplicates(["date", "home_id", "away_id"]),
        on=["date", "home_id", "away_id"],
        how="outer",
    )
    return games


def _long_games(games: pd.DataFrame) -> pd.DataFrame:
    """One row per (date, team): opponent, home flag, spread for the team, combined score."""
    d = _days(games["date"]) if len(games) else np.array([], dtype="int64")
    comb = games["home_score"] + games["away_score"] if len(games) else []
    rows = []
    for me, opp, home, sign in (
        ("home_id", "away_id", 1, 1),
        ("away_id", "home_id", 0, -1),
    ):
        rows.append(
            pd.DataFrame(
                {
                    "d": d,
                    "team_id": games[me].values,
                    "opp_id": games[opp].values,
                    "home": home,
                    "spread": games["spread_home"].values * sign,
                    "total": games["total"].values,
                    "combined": np.asarray(comb, dtype=float),
                }
            )
        )
    return pd.concat(rows, ignore_index=True).drop_duplicates(["d", "team_id"])


# ---------------------------------------------------------------- features


def _mean(a):
    return float(np.mean(a)) if len(a) else np.nan


def _row_features(ctx: _Ctx, r, present: dict) -> dict:
    day, p, t, o = int(r.d), int(r.player_id), r.team_id, r.opponent_team_id
    line = float(r.line)
    f = dict.fromkeys(feature_columns(), np.nan)
    pb = ctx.pbox.get(p)
    if pb is not None:
        pb = pb[pb["d"] < day]
    vals = pb["val"].to_numpy() if pb is not None else np.array([])
    mins = pb["minutes"].to_numpy() if pb is not None else np.array([])
    dd = pb["d"].to_numpy() if pb is not None else np.array([])
    ss = _season_start_day(day)
    sv, sm = vals[dd >= ss], mins[dd >= ss]
    l10 = _mean(vals[-10:])
    # line_
    f["line_line"] = line
    f["line_minus_l10"] = line - l10
    f["line_over_l10"] = line / l10 if l10 and l10 > 0 else np.nan
    # form_
    f["form_l5"], f["form_l10"], f["form_season"] = _mean(vals[-5:]), l10, _mean(sv)
    f["form_l5_minus_season"] = f["form_l5"] - f["form_season"]
    f["form_rate_l10"] = vals[-10:].sum() / mins[-10:].sum() if len(vals) else np.nan
    # min_
    f["min_l5"] = _mean(mins[-5:])
    f["min_last_minus_season"] = mins[-1] - _mean(sm) if len(sm) else np.nan
    f["min_l3_minus_l10"] = _mean(mins[-3:]) - _mean(mins[-10:])
    # hist_
    lh = ctx.lined.get(p)
    lh = lh[lh["d"] < day] if lh is not None else None
    n = 0 if lh is None else len(lh)
    f["hist_n_prior"] = float(n)
    if n:
        f["hist_resid_l10_shrunk"] = lh["r"].iloc[-10:].sum() / (min(n, 10) + 5)
        np_ = lh[lh["r"] != 0]
        f["hist_over_rate_shrunk"] = ((np_["r"] > 0).sum() + 2.5) / (len(np_) + 5)
    else:
        f["hist_resid_l10_shrunk"], f["hist_over_rate_shrunk"] = 0.0, 0.5
    if pd.notna(t):
        t = int(t)
        _team_features(ctx, f, p, t, day, present, pb, mins)
        gm = ctx.gmeta.loc[(day, t)] if (day, t) in ctx.gmeta.index else None
        if gm is not None:
            if pd.notna(gm["spread"]):
                f["game_abs_spread"] = abs(gm["spread"])
                f["game_is_fav"] = float(gm["spread"] < 0)
            f["game_total"] = gm["total"]
            f["sched_home"] = float(gm["home"])
        td = ctx.tdates.get(t, np.array([], dtype="int64"))
        prev = td[td < day]
        rest = min(day - prev[-1], 7) if len(prev) else 7
        f["sched_rest_days"], f["sched_b2b"] = float(rest), float(rest == 1)
    if pd.notna(r.home) and pd.isna(f["sched_home"]):
        f["sched_home"] = float(r.home)
    if pd.notna(o):
        _opp_features(ctx, f, int(o), day)
    return f


def _team_features(ctx, f, p, t, day, present, pb, mins) -> None:
    # min_starter: mean-minutes rank among teammates over each one's last 5 games
    tb = ctx.tbox.get(t)
    if tb is not None and len(mins):
        recent = tb[(tb["d"] < day) & (tb["d"] >= day - 30)]
        means = recent.groupby("player_id")["minutes"].apply(
            lambda s: s.iloc[-5:].mean()
        )
        mine = _mean(mins[-5:])
        f["min_starter"] = float(1 + (means.drop(p, errors="ignore") > mine).sum() <= 5)
    reg = ctx.regulars(t, day)
    here = present.get((day, t), frozenset())
    out = reg[~reg["player_id"].isin(here | {p})]
    f["team_n_out"], f["team_out_minutes"] = float(len(out)), float(out["mins"].sum())
    f["team_out_stat"], f["team_with_without"] = float(out["val"].sum()), 0.0
    if len(out) and pb is not None and len(pb):
        q = int(out.sort_values("mins").iloc[-1]["player_id"])
        qb = ctx.pbox.get(q)
        if qb is None or qb.empty:
            return
        sub = pb[(pb["team_id"] == t) & (pb["d"] >= qb["d"].iloc[0])]
        qdays = set(qb["d"])
        wo = sub[~sub["d"].isin(qdays)]
        wi = sub[sub["d"].isin(qdays)]
        if len(wo) and len(wi):
            delta = (
                wo["val"].sum() / wo["minutes"].sum()
                - wi["val"].sum() / wi["minutes"].sum()
            )
            f["team_with_without"] = float(delta * len(wo) / (len(wo) + 5))


def _opp_features(ctx, f, o, day) -> None:
    al = ctx.allowed_by_team.get(o)
    if al is not None:
        last = al[al["d"] < day].iloc[-10:]
        if len(last):
            lg = ctx.allowed[
                (ctx.allowed["d"] >= last["d"].iloc[0]) & (ctx.allowed["d"] < day)
            ]
            f["opp_allowed_rel"] = (
                last["val"].mean() / lg["val"].mean() if len(lg) else np.nan
            )
    sc = ctx.scores.get(o)
    if sc is not None:
        last = sc[sc["d"] < day].iloc[-10:]
        if len(last):
            f["opp_pace"] = float(last["combined"].mean())


def _features(ctx: _Ctx, slots: pd.DataFrame, present: dict) -> pd.DataFrame:
    feats = [_row_features(ctx, r, present) for r in slots.itertuples()]
    return pd.DataFrame(feats, index=slots.index, columns=feature_columns())


def _line_frame(inputs: dict, stat: str) -> pd.DataFrame:
    ln = inputs["lines"]
    return ln[ln["stat"] == stat].copy()


# ---------------------------------------------------------------- public


def build_rows(inputs: dict, stat: str, *, start=None, end=None) -> pd.DataFrame:
    """Training rows: lined player-games with a played box row (minutes > 0)."""
    ctx = _Ctx(inputs, stat)
    ln = _line_frame(inputs, stat)
    ln["d"] = _days(ln["date"])
    slots = ln.merge(
        ctx.box[["player_id", "d", "team_id", "opponent_team_id", "val", "home_game"]],
        on=["player_id", "d"],
        how="inner",
    )
    slots = slots[slots["team_id"].notna()].rename(
        columns={"val": "actual", "home_game": "home"}
    )
    slots["home"] = slots["home"].astype(float)
    if start is not None:
        slots = slots[slots["date"] >= pd.Timestamp(start)]
    if end is not None:
        slots = slots[slots["date"] <= pd.Timestamp(end)]
    slots = slots.sort_values(["date", "player_id"]).reset_index(drop=True)
    out = _finish(slots, _features(ctx, slots, ctx.played), stat)
    out["resid"] = out["actual"] - out["line"]
    out["over"] = np.where(
        out["resid"] > 0, 1.0, np.where(out["resid"] < 0, 0.0, np.nan)
    )
    return out[[*KEYS, *LINE_COLS, *TARGETS, *feature_columns()]]


def _finish(slots: pd.DataFrame, feats: pd.DataFrame, stat: str) -> pd.DataFrame:
    out = slots.copy()
    out["stat"] = stat
    out["team_id"] = out["team_id"].astype(int)
    out["opponent_team_id"] = out["opponent_team_id"].astype(int)
    return pd.concat([out, feats], axis=1)


def serve_rows(inputs, stat, today, active_players, out_player_ids) -> pd.DataFrame:
    """Feature rows for today's lined players (no box row yet).

    active_players: DataFrame (player_id, team_id, opponent_team_id[, is_home_game]).
    Teammates out = regulars not in active_players, or listed in out_player_ids.
    """
    today = pd.Timestamp(today)
    ctx = _Ctx(inputs, stat)
    ln = _line_frame(inputs, stat)
    ln = ln[ln["date"] == today]
    ap = active_players.drop_duplicates("player_id").copy()
    ap["home"] = ap["is_home_game"].astype(float) if "is_home_game" in ap else np.nan
    slots = ln.merge(
        ap[["player_id", "team_id", "opponent_team_id", "home"]],
        on="player_id",
        how="inner",
    )
    slots["d"] = _days(slots["date"]) if len(slots) else np.array([], dtype="int64")
    slots = slots.sort_values("player_id").reset_index(drop=True)
    out_ids = set(out_player_ids)
    day = int(np.datetime64(today.date(), "D").astype("int64"))
    present = {
        (day, int(t)): frozenset(set(g["player_id"]) - out_ids)
        for t, g in ap.groupby("team_id")
    }
    return _finish(slots, _features(ctx, slots, present), stat).drop(columns=["d"])[
        [*KEYS, *LINE_COLS, *feature_columns()]
    ]
