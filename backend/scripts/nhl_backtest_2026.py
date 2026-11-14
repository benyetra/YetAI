"""As-of backtest of NHL shots on goal, game totals and goalie saves (YetAI-5p8).

Rebuilds every input from the season's box scores using only games played before each
game's date, scores candidate formulas against actuals and against the line stored by the
production writer, and prints one table per market.

Inputs (read-only):
  --box-dir   directory of NHL api-web boxscores ``<game_id>.json`` for the season plus
              ``skater_<prev>.json``, ``goalie_<prev>.json``, ``team_<prev>.json`` (stats
              REST summaries of the previous regular season, limit=-1). Fetch with
              ``--fetch`` (about 380 boxscore calls + 3 summary calls, ~3 minutes).
  --db-url    a database holding pred_nhl_player_shots_predictions and
              pred_nhl_team_totals_predictions (the stored lines and old projections).

  PYTHONPATH=. python scripts/nhl_backtest_2026.py --box-dir /tmp/nhl_box \
      --db-url postgresql://postgres@localhost:55433/nhl_before [--fetch]
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sqlalchemy import create_engine

SEASON = 20262027
PREV = SEASON - 10001
BREAKEVEN = 110 / 210  # -110 both sides
# The configuration each market's detail tables use (chosen from the grid above them).
TOT_K, TOT_PRIOR = 40, "prev"
SV_K, SV_PRIOR = 40, "prev"
LEAGUE_PRIOR_TEAM_GAMES = 64
WEB = "https://api-web.nhle.com/v1"
STATS = "https://api.nhle.com/stats/rest/en"


# ---------- fetch ----------


def _get(url):
    for i in range(4):
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            time.sleep(1 + i)
    raise RuntimeError(url)


def fetch(box: Path, through: str) -> int:
    """Download finished regular-season and preseason boxscores + last-season summaries."""
    box.mkdir(parents=True, exist_ok=True)
    calls = 1
    teams = [
        t["teamAbbrev"]["default"]
        for t in _get(f"{WEB}/standings/{through}")["standings"]
    ]
    ids = {}
    for a in teams:
        calls += 1
        for g in _get(f"{WEB}/club-schedule-season/{a}/{SEASON}")["games"]:
            if g["gameType"] in (1, 2, 3) and g["gameState"] in ("OFF", "FINAL"):
                ids[g["id"]] = g["gameDate"]
    for gid in ids:
        p = box / f"{gid}.json"
        if not p.exists():
            p.write_text(json.dumps(_get(f"{WEB}/gamecenter/{gid}/boxscore")))
            calls += 1
            time.sleep(0.15)
    for kind in ("skater", "goalie", "team"):
        url = (
            f"{STATS}/{kind}/summary?limit=-1"
            f"&cayenneExp=seasonId={PREV}%20and%20gameTypeId=2"
        )
        (box / f"{kind}_{PREV}.json").write_text(json.dumps(_get(url)))
        calls += 1
    return calls


# ---------- parse ----------


def _sec(toi: str) -> int:
    m, _, s = (toi or "0:00").partition(":")
    return int(m) * 60 + int(s or 0)


def load_box(box: Path):
    games, skaters, goalies = [], [], []
    for p in sorted(box.glob(f"{str(SEASON)[:4]}*.json")):
        b = json.loads(p.read_text())
        if b.get("gameState") not in ("OFF", "FINAL"):
            continue
        h, a = b["homeTeam"], b["awayTeam"]
        games.append(
            dict(
                game_id=b["id"],
                date=b["gameDate"],
                gtype=b["gameType"],
                home=h["id"],
                away=a["id"],
                hg=h["score"],
                ag=a["score"],
                hs=h["sog"],
                as_=a["sog"],
            )
        )
        for side, team, opp, home in (("homeTeam", h, a, 1), ("awayTeam", a, h, 0)):
            pg = b["playerByGameStats"][side]
            for grp in ("forwards", "defense"):
                for x in pg.get(grp, []):
                    skaters.append(
                        dict(
                            game_id=b["id"],
                            date=b["gameDate"],
                            gtype=b["gameType"],
                            team=team["id"],
                            opp=opp["id"],
                            home=home,
                            pid=x["playerId"],
                            name=x["name"]["default"],
                            pos="D" if grp == "defense" else "F",
                            sog=x.get("sog", 0),
                            toi=_sec(x.get("toi")),
                        )
                    )
            for x in pg.get("goalies", []):
                goalies.append(
                    dict(
                        game_id=b["id"],
                        date=b["gameDate"],
                        gtype=b["gameType"],
                        team=team["id"],
                        opp=opp["id"],
                        home=home,
                        gid=x["playerId"],
                        starter=bool(x.get("starter")),
                        toi=_sec(x.get("toi")),
                        sa=x.get("shotsAgainst", 0),
                        sv=x.get("saves", 0),
                    )
                )
    g = pd.DataFrame(games)
    return g, pd.DataFrame(skaters), pd.DataFrame(goalies)


def load_priors(box: Path):
    sk = pd.DataFrame(json.loads((box / f"skater_{PREV}.json").read_text())["data"])
    sk["pos"] = np.where(sk.positionCode == "D", "D", "F")
    sk["rate"] = sk.shots / sk.gamesPlayed
    pos_mean = (
        sk[sk.gamesPlayed >= 10]
        .groupby("pos")
        .apply(lambda x: x.shots.sum() / x.gamesPlayed.sum(), include_groups=False)
    )
    sk_prior = sk[sk.gamesPlayed >= 10].set_index("playerId").rate.to_dict()
    gl = pd.DataFrame(json.loads((box / f"goalie_{PREV}.json").read_text())["data"])
    lg_sv = gl.saves.sum() / gl.shotsAgainst.sum()
    gl_prior = (
        gl[gl.shotsAgainst >= 300]
        .set_index("playerId")
        .apply(lambda r: r.saves / r.shotsAgainst, axis=1)
        .to_dict()
    )
    tm = pd.DataFrame(json.loads((box / f"team_{PREV}.json").read_text())["data"])
    tm_prior = tm.set_index("teamId")[
        [
            "goalsForPerGame",
            "goalsAgainstPerGame",
            "shotsForPerGame",
            "shotsAgainstPerGame",
        ]
    ].to_dict("index")
    return dict(
        sk=sk_prior,
        pos=pos_mean.to_dict(),
        gl=gl_prior,
        lg_sv=lg_sv,
        tm=tm_prior,
    )


def load_lines(db_url: str):
    eng = create_engine(db_url)
    shots = pd.read_sql(
        "select distinct on (player_id, game_date) player_id, game_date, "
        "shots_line, predicted_shots, betting_recommendation from "
        "pred_nhl_player_shots_predictions order by player_id, game_date, id desc",
        eng,
    )
    tot = pd.read_sql(
        "select distinct on (home_team_id, away_team_id, game_date) home_team_id, "
        "away_team_id, game_date, draftkings_ou_line, predicted_total_goals, "
        "betting_recommendation from pred_nhl_team_totals_predictions "
        "order by home_team_id, away_team_id, game_date, id desc",
        eng,
    )
    for d in (shots, tot):
        d["game_date"] = d.game_date.astype(str)
    return shots, tot


# ---------- metrics ----------


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def score(df, proj, act="act", line="line"):
    x = df.dropna(subset=[proj, act])
    out = dict(
        n=len(x),
        mae=(x[act] - x[proj]).abs().mean(),
        bias=(x[act] - x[proj]).mean(),
        corr=x[act].corr(x[proj]),
    )
    y = x.dropna(subset=[line])
    out.update(
        n_line=len(y),
        mae_lined=(y[act] - y[proj]).abs().mean(),
        mae_line=(y[act] - y[line]).abs().mean(),
        corr_lined=y[act].corr(y[proj]),
        corr_line=y[act].corr(y[line]),
    )
    return out


def hits(df, proj, thresholds, act="act", line="line"):
    y = df.dropna(subset=[proj, act, line])
    y = y[(y[act] != y[line]) & (y[proj] != y[line])]
    e = y[proj] - y[line]
    hit = np.sign(e) == np.sign(y[act] - y[line])
    rows = []
    for t in thresholds:
        m = e.abs() >= t
        k, n = int(hit[m].sum()), int(m.sum())
        lo, hi = wilson(k, n)
        rows.append(
            dict(
                edge_ge=t,
                n=n,
                hit=k / n if n else float("nan"),
                lo=lo,
                hi=hi,
                over_share=float((e[m] > 0).mean()) if n else float("nan"),
                clears=bool(lo > BREAKEVEN) if n else False,
            )
        )
    return pd.DataFrame(rows)


def fmt(rows: dict) -> str:
    t = pd.DataFrame(rows).T
    return t.to_string(float_format=lambda v: f"{v:.3f}")


# ---------- as-of state ----------


def shrink(total, n, prior, k):
    return (total + k * prior) / (n + k) if (n + k) > 0 else prior


def team_rates(g, before, pri, k, prior="prev"):
    """Shrunk per-team GF/GA/SF/SA per game from regular-season games before ``before``.

    prior="prev": toward the team's last-season rate scaled to this season's league
    level (last-season rate / last-season league mean * current league mean);
    prior="league": toward the current league mean.
    """
    x = g[(g.gtype == 2) & (g.date < before)]
    rows = []
    for _, r in x.iterrows():
        rows.append((r.home, r.hg, r.ag, r.hs, r.as_, 1))
        rows.append((r.away, r.ag, r.hg, r.as_, r.hs, 0))
    t = pd.DataFrame(rows, columns=["team", "gf", "ga", "sf", "sa", "home"])
    prev_gf = np.mean([v["goalsForPerGame"] for v in pri["tm"].values()])
    prev_sf = np.mean([v["shotsForPerGame"] for v in pri["tm"].values()])
    lg = dict(
        # League level, itself shrunk toward last season by LEAGUE_PRIOR_TEAM_GAMES.
        gf=shrink(t.gf.sum(), len(t), prev_gf, LEAGUE_PRIOR_TEAM_GAMES),
        sf=shrink(t.sf.sum(), len(t), prev_sf, LEAGUE_PRIOR_TEAM_GAMES),
        home_gf=t[t.home == 1].gf.mean() if len(t) else prev_gf,
        away_gf=t[t.home == 0].gf.mean() if len(t) else prev_gf,
        home_sf=t[t.home == 1].sf.mean() if len(t) else prev_sf,
        away_sf=t[t.home == 0].sf.mean() if len(t) else prev_sf,
    )
    agg = t.groupby("team").agg(n=("gf", "size"), gf=("gf", "sum"), ga=("ga", "sum"),
                                sf=("sf", "sum"), sa=("sa", "sum"))  # fmt: skip
    scale = {"g": lg["gf"] / prev_gf, "s": lg["sf"] / prev_sf}
    out = {}
    for team in set(g.home) | set(g.away):
        p = pri["tm"].get(team, {})
        a = agg.loc[team] if team in agg.index else None
        n = a.n if a is not None else 0

        def s(col, key, lgv, unit):
            if prior == "prev" and key in p:
                pr = p[key] * scale[unit]
            else:
                pr = lgv
            return shrink(a[col] if a is not None else 0, n, pr, k)

        out[team] = dict(
            n=n,
            gf=s("gf", "goalsForPerGame", lg["gf"], "g"),
            ga=s("ga", "goalsAgainstPerGame", lg["gf"], "g"),
            sf=s("sf", "shotsForPerGame", lg["sf"], "s"),
            sa=s("sa", "shotsAgainstPerGame", lg["sf"], "s"),
        )
    return out, lg


# ---------- markets ----------


def shots_backtest(g, sk, pri, lines, dates):
    rows = []
    reg = sk[sk.gtype == 2]
    for d in dates:
        prior_games = reg[reg.date < d]
        agg = prior_games.groupby("pid").agg(
            n=("sog", "size"), s=("sog", "sum"), toi=("toi", "mean")
        )
        last = prior_games.sort_values("date").groupby("pid").tail(10)
        l10 = last.groupby("pid").agg(n10=("sog", "size"), s10=("sog", "sum"))
        last5 = prior_games.sort_values("date").groupby("pid").tail(5)
        t5 = last5.groupby("pid").toi.mean()
        last_team = prior_games.sort_values("date").groupby("pid").team.last()
        last_game_by_team = prior_games.groupby("team").game_id.max()
        dressed_last = set(
            prior_games[prior_games.game_id.isin(last_game_by_team.values)].pid
        )
        tr, lg = team_rates(g, d, pri, 10)
        pos_toi = prior_games.groupby("pos").toi.mean()
        today = reg[reg.date == d]
        for _, r in today.iterrows():
            if r.pid not in agg.index:
                continue
            a = agg.loc[r.pid]
            p0 = pri["sk"].get(r.pid, pri["pos"][r.pos])
            row = dict(
                date=d,
                pid=r.pid,
                team=r.team,
                pos=r.pos,
                home=r.home,
                n=a.n,
                act=r.sog,
                raw=a.s / a.n,
                p0=p0,
                same_team=last_team.get(r.pid) == r.team,
                dressed_last=r.pid in dressed_last,
            )
            for k in (3, 5, 10, 20, 40):
                row[f"k{k}"] = shrink(a.s, a.n, p0, k)
            base = row["k10"]
            # TOI trend: last-5 TOI vs season TOI (the information an ice-time term adds).
            row["k10_toi"] = base * (t5.get(r.pid, a.toi) / a.toi if a.toi else 1)
            # The old bucketed ice-time multiplier on top of a rate that already has it.
            toi = a.toi
            row["k10_oldtoi"] = base * (
                1.15 if toi > 1200 else 1.08 if toi > 1100 else 0.85 if toi < 800
                else 0.92 if toi < 900 else 1.0
            )  # fmt: skip
            opp = tr[r.opp]
            row["k10_opp"] = base * opp["sa"] / lg["sf"]
            hf = (lg["home_sf"] if r.home else lg["away_sf"]) / lg["sf"]
            row["k10_home"] = base * hf
            row["k10_opp_home"] = base * opp["sa"] / lg["sf"] * hf
            if r.pid in l10.index:
                b = l10.loc[r.pid]
                row["k10_l10"] = 0.5 * base + 0.5 * b.s10 / b.n10
            rows.append(row)
    df = pd.DataFrame(rows)
    ln = lines.rename(columns={"player_id": "pid", "game_date": "date"})
    df = df.merge(
        ln[["pid", "date", "shots_line", "predicted_shots"]], on=["pid", "date"],
        how="left",
    )  # fmt: skip
    df = df.rename(columns={"shots_line": "line", "predicted_shots": "old"})
    return df


def selection_backtest(sk, pri, lines, dates, min_games=5, per_team=6):
    """The writer's rule replayed: per team, skaters with >= min_games this season
    whose latest game was for that team (the roster as of that day), top ``per_team``
    by shrunk rate plus anyone with a stored line; did each one play?"""
    reg = sk[sk.gtype == 2]
    lined = set(zip(lines.player_id, lines.game_date, strict=False))
    lined = {k for k, v in zip(lined, [1] * len(lined), strict=False)}
    shot_lined = set(
        zip(
            lines.dropna(subset=["shots_line"]).player_id,
            lines.dropna(subset=["shots_line"]).game_date,
            strict=False,
        )
    )
    out = {k: [0, 0] for k in ("rule", "rule+dressed_last")}
    for d in dates:
        prior = reg[reg.date < d].sort_values(["date", "game_id"])
        today = reg[reg.date == d]
        if today.empty or prior.empty:
            continue
        agg = prior.groupby("pid").agg(n=("sog", "size"), s=("sog", "sum"),
                                       team=("team", "last"), pos=("pos", "last"))  # fmt: skip
        last_gid = prior.groupby("team").game_id.max()
        dressed = set(prior[prior.game_id.isin(last_gid.values)].pid)
        played = set(today.pid)
        teams = set(today.team)
        agg = agg[(agg.n >= min_games) & agg.team.isin(teams)]
        agg["rate"] = [
            shrink(r.s, r.n, pri["sk"].get(pid, pri["pos"][r.pos]), 10)
            for pid, r in agg.iterrows()
        ]
        for label, pool in (("rule", agg), ("rule+dressed_last",
                            agg[agg.index.isin(dressed)])):  # fmt: skip
            for team, x in pool.groupby("team"):
                top = set(x.sort_values("rate", ascending=False).index[:per_team])
                pick = top | {p for p in x.index if (p, d) in shot_lined}
                out[label][0] += len(pick)
                out[label][1] += sum(1 for p in pick if p not in played)
    _ = lined
    return pd.DataFrame(
        {k: dict(projected=v[0], no_actual=v[1], share=v[1] / v[0] if v[0] else None)
         for k, v in out.items()}
    ).T  # fmt: skip


def totals_backtest(g, pri, lines, dates, ks=(0, 5, 10, 20, 40)):
    rows = []
    reg = g[g.gtype == 2]
    for d in dates:
        today = reg[reg.date == d]
        if today.empty:
            continue
        for k, prior in [(k, pr) for k in ks for pr in ("prev", "league")]:
            tr, lg = team_rates(g, d, pri, k, prior)
            hadv = lg["home_gf"] / lg["gf"]
            aadv = lg["away_gf"] / lg["gf"]
            for _, r in today.iterrows():
                h, a = tr[r.home], tr[r.away]
                lh = h["gf"] * a["ga"] / lg["gf"]
                la = a["gf"] * h["ga"] / lg["gf"]
                rows.append(
                    dict(
                        date=d,
                        home=r.home,
                        away=r.away,
                        k=k,
                        prior=prior,
                        act=r.hg + r.ag,
                        lg=2 * lg["gf"],
                        model=lh + la,
                        model_home=lh * hadv + la * aadv,
                        n_home=h["n"],
                        n_away=a["n"],
                    )
                )
    df = pd.DataFrame(rows)
    ln = lines.rename(
        columns={"home_team_id": "home", "away_team_id": "away", "game_date": "date"}
    )
    df = df.merge(
        ln[["home", "away", "date", "draftkings_ou_line", "predicted_total_goals"]],
        on=["home", "away", "date"],
        how="left",
    ).rename(columns={"draftkings_ou_line": "line", "predicted_total_goals": "old"})
    for w in (0.25, 0.5):
        df[f"anchor{w}"] = np.where(
            df.line.notna(), w * df.model + (1 - w) * df.line, np.nan
        )
    return df


def saves_backtest(g, gl, pri, dates, ks=(0, 5, 10, 20, 40)):
    rows = []
    reg = gl[gl.gtype == 2]
    for d in dates:
        prior = reg[reg.date < d]
        lg_sv = prior.sv.sum() / prior.sa.sum() if prior.sa.sum() > 0 else pri["lg_sv"]
        ga = prior.groupby("gid").agg(sa=("sa", "sum"), sv=("sv", "sum"))
        starters = prior[prior.starter]
        lg_saves = starters.sv.mean() if len(starters) else 25.0
        today = reg[(reg.date == d) & reg.starter]
        for k, prior in [(k, pr) for k in ks for pr in ("prev", "league")]:
            tr, lg = team_rates(g, d, pri, k, prior)
            for _, r in today.iterrows():
                me, opp = tr[r.team], tr[r.opp]
                p_sv = pri["gl"].get(r.gid, lg_sv)
                a = ga.loc[r.gid] if r.gid in ga.index else None
                row = dict(
                    date=d,
                    gid=r.gid,
                    k=k,
                    prior=prior,
                    act=r.sv,
                    act_sa=r.sa,
                    full=r.toi >= 55 * 60,
                    const=lg_saves,
                    sa_opp=opp["sf"],
                    sa_both=opp["sf"] * me["sa"] / lg["sf"],
                )
                for ksv in (0, 300, 1000):
                    sv = shrink(a.sv if a is not None else 0,
                                a.sa if a is not None else 0, p_sv, ksv)  # fmt: skip
                    row[f"sv{ksv}"] = sv
                row["sv_lg"] = lg_sv
                for sa_k in ("sa_opp", "sa_both"):
                    for svk in ("sv0", "sv300", "sv1000", "sv_lg"):
                        row[f"{sa_k}*{svk}"] = row[sa_k] * row[svk]
                rows.append(row)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--box-dir", required=True)
    ap.add_argument("--db-url", required=True)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--through", default="2026-11-13")
    ap.add_argument("--out", default=None, help="write per-row CSVs here")
    args = ap.parse_args()
    box = Path(args.box_dir)
    if args.fetch:
        print("api calls:", fetch(box, args.through))
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    g, sk, gl = load_box(box)
    pri = load_priors(box)
    shots_lines, tot_lines = load_lines(args.db_url)
    dates = sorted(g[(g.gtype == 2) & (g.date <= args.through)].date.unique())
    print(
        f"games: {len(g)} ({(g.gtype == 2).sum()} regular, {(g.gtype == 1).sum()} "
        f"preseason), dates {dates[0]}..{dates[-1]}"
    )
    thresholds = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5)

    # ---- shots ----
    s = shots_backtest(g, sk, pri, shots_lines, dates)
    ev = s[s.n >= 5]
    print("\n=== SHOTS ON GOAL (skater-games, regular season, >=5 prior games) ===")
    cands = ["old", "raw", "k3", "k5", "k10", "k20", "k40", "k10_toi", "k10_oldtoi",
             "k10_opp", "k10_home", "k10_opp_home", "k10_l10"]  # fmt: skip
    print(fmt({c: score(ev, c) for c in cands}))
    lined = ev.dropna(subset=["line"])
    print(f"\nlined rows with >=5 prior games: {len(lined)}")
    print(fmt({c: score(lined.dropna(subset=["old"]), c) for c in cands}))
    for c in ("old", "k10", "k20"):
        print(f"\nhit rate vs stored line, {c}:")
        print(hits(ev, c, thresholds).to_string(float_format=lambda v: f"{v:.3f}"))
    print("\n== who gets projected: share of selected skaters with no actual")
    print(selection_backtest(sk, pri, shots_lines, dates).to_string())
    if args.out:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        s.to_csv(Path(args.out) / "shots_rows.csv", index=False)

    # ---- totals ----
    t = totals_backtest(g, pri, tot_lines, dates)
    print("\n=== GAME TOTALS (regular season) ===")
    res = {}
    for (k, pr), x in t.groupby(["k", "prior"]):
        res[f"model k={k} {pr}"] = score(x, "model")
        res[f"model+home k={k} {pr}"] = score(x, "model_home")
    x10 = t[(t.k == TOT_K) & (t.prior == TOT_PRIOR)]
    res["league mean"] = score(x10, "lg")
    res["old"] = score(x10, "old")
    res["anchor0.25"] = score(x10, "anchor0.25")
    res["anchor0.5"] = score(x10, "anchor0.5")
    print(fmt(res))
    lined = x10.dropna(subset=["line", "old"])
    print(f"\nlined games with an old projection: {len(lined)}")
    print(fmt({c: score(lined, c) for c in ("old", "lg", "model", "model_home")}))
    for c in ("old", "model", "model_home"):
        print(f"\nhit rate vs stored line, {c} (k={TOT_K} {TOT_PRIOR}):")
        print(
            hits(x10, c, (0.0, 0.1, 0.25, 0.5, 0.75)).to_string(
                float_format=lambda v: f"{v:.3f}"
            )
        )
    if args.out:
        t.to_csv(Path(args.out) / "totals_rows.csv", index=False)

    # ---- saves ----
    sv = saves_backtest(g, gl, pri, dates)
    print(
        "\n=== GOALIE SAVES (actual starters = confirmed starters, regular season) ==="
    )
    cols = ["const"] + [c for c in sv.columns if "*" in c]
    res = {}
    for (k, pr), x in sv.groupby(["k", "prior"]):
        for c in cols:
            if c == "const" and (k or pr == "league"):
                continue
            res[f"{c} k={k} {pr}"] = {
                kk: v for kk, v in score(x.assign(line=np.nan), c).items()
                if not kk.endswith(("line", "lined"))
            }  # fmt: skip
    print(fmt(res))
    full = sv[(sv.k == SV_K) & (sv.prior == SV_PRIOR) & sv.full]
    print(f"\nfull-game starters only (n={len(full)}):")
    print(
        fmt(
            {c: {kk: v for kk, v in score(full.assign(line=np.nan), c).items()
                 if not kk.endswith(("line", "lined"))}
             for c in ("const", "sa_opp*sv_lg", "sa_both*sv_lg", "sa_both*sv300")}
        )
    )  # fmt: skip
    if args.out:
        sv.to_csv(Path(args.out) / "saves_rows.csv", index=False)


if __name__ == "__main__":
    main()
