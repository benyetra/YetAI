"""Walk-forward evaluation of the NBA line-residual model (rebounds / assists).

    DATABASE_URL=... PYTHONPATH=. python scripts/nba_residual_eval.py \
        --stat all --out <dir> [--kind ridge|gbm|both] [--db-url URL]

Writes <out>/eval_<stat>.json (all numbers) and <out>/eval.md. Deterministic: model
seeds are fixed in residual/model.py, placebo seeds are 0..4. Reads only.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

from app.services.etl.nba.residual import evaluate as ev
from app.services.etl.nba.residual.dataset import (
    FEATURE_FAMILIES,
    STAT_COLUMN,
    build_rows,
    feature_columns,
    load_inputs,
)

START, SEASON_SPLIT = "2025-10-01", "2026-10-01"


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if np.isnan(o) or np.isinf(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (pd.Timestamp,)):
        return o.isoformat()
    return o


def evaluate_stat(df: pd.DataFrame, stat: str, kinds) -> dict:
    feats = feature_columns()
    counts = (
        df.assign(
            season=np.where(df["date"] >= SEASON_SPLIT, "2026-27", "2025-26"),
        )
        .groupby(["season", "line_source"])
        .size()
        .rename("n")
        .reset_index()
        .to_dict("records")
    )
    out = dict(stat=stat, rows=len(df), row_counts=counts, models={})
    for kind in kinds:
        sc = ev.walk_forward(df, feats, kind)
        base = float(sc["train_base"].mean()) if len(sc) else 0.5
        out["models"][kind] = dict(
            metrics=ev.metrics(sc, train_base_rate=base),
            train_base_rate=base,
            first_scored=sc["date"].min(),
            last_scored=sc["date"].max(),
        )
    k0 = "ridge" if "ridge" in kinds else kinds[0]
    out["ablation"] = ev.ablation(df, list(FEATURE_FAMILIES), k0)
    out["placebo"] = ev.placebo(df, feats, k0, seeds=range(5))
    out["ablation_placebo_kind"] = k0
    if {"ridge", "gbm"} <= set(kinds):
        r, g = (out["models"][k]["metrics"] for k in ("ridge", "gbm"))
        out["gbm_adopted"] = bool(
            g["mae_delta"] < r["mae_delta"] and g["slope"] > r["slope"]
        )
    adopted = "gbm" if out.get("gbm_adopted") else k0
    out["adopted"] = adopted
    out["verdict"] = ev.verdict(out["models"][adopted]["metrics"])
    return out


def _f(x, nd=3):
    return "-" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


def render(res: dict) -> str:
    L = [f"## {res['stat']}  (rows {res['rows']})", ""]
    L.append(
        f"**Verdict ({res['adopted']}): {res['verdict']}** (rule: ev.verdict docstring)"
    )
    L.append("")
    L.append(
        "Row counts: "
        + ", ".join(
            f"{c['season']} {c['line_source']}={c['n']}" for c in res["row_counts"]
        )
    )
    L += [
        "",
        "| model | n | slope (se) | corr | MAE line | MAE model | delta | hit>=0.5 (n) | ROI@-110 >=0.5 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for kind, m in res["models"].items():
        x = m["metrics"]
        c = next(c for c in x["cumulative"] if c["threshold"] == 0.5)
        L.append(
            f"| {kind} | {x['n']} | {_f(x['slope'])} ({_f(x['slope_se'])}) | {_f(x['corr'])} | "
            f"{_f(x['mae_line'])} | {_f(x['mae_model'])} | {_f(x['mae_delta'], 4)} | "
            f"{_f(c['hit_rate'])} ({c['n']}) | {_f(c['roi_units_110'], 1)} |"
        )
    if "gbm_adopted" in res:
        if res["gbm_adopted"] and res["models"]["gbm"]["metrics"]["mae_delta"] >= 0:
            L.append(
                "\nNote: GBM wins the rule against ridge but is still worse than the line."
            )
        L.append(
            f"\nGBM adopted: **{res['gbm_adopted']}** (needs lower MAE delta and higher slope than ridge)."
        )
    for kind, m in res["models"].items():
        x = m["metrics"]
        L += [
            "",
            f"### {kind}: calls by |pred_resid|",
            "",
            "| bucket | n | hit | Wilson 95% | ROI -110 | over/under | stored-price n | hit | ROI | med price | breakeven |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for b in x["buckets"]:
            sp = b["stored_price"]
            L.append(
                f"| [{b['lo']},{b['hi'] if b['hi'] is not None else 'inf'}) | {b['n']} | {_f(b['hit_rate'])} | "
                f"{_f(b['wilson_lo'])}-{_f(b['wilson_hi'])} | {_f(b['roi_units_110'], 1)} | {b['n_over']}/{b['n_under']} | "
                f"{sp['n']} | {_f(sp.get('hit_rate'))} | {_f(sp.get('roi_units'), 1)} | {sp.get('median_price', '-')} | {_f(sp.get('breakeven'))} |"
            )
        L += [
            "",
            "| cumulative | n | hit | Wilson 95% | ROI -110 | over/under | stored n | stored hit | stored ROI | always-under | base-side ("
            + x["baselines_all"]["base_side"]
            + ") |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for c in x["cumulative"]:
            sp, bl = c["stored_price"], c["baselines"]
            L.append(
                f"| >={c['threshold']} | {c['n']} | {_f(c['hit_rate'])} | {_f(c['wilson_lo'])}-{_f(c['wilson_hi'])} | "
                f"{_f(c['roi_units_110'], 1)} | {c['n_over']}/{c['n_under']} | {sp['n']} | {_f(sp.get('hit_rate'))} | "
                f"{_f(sp.get('roi_units'), 1)} | {_f(bl['always_under'])} | {_f(bl['always_train_base_side'])} |"
            )
        ca = x["calibration"]
        L += [
            "",
            f"Calibration ({kind}): mean |pred-obs| = {_f(ca['mean_abs_gap'], 4)}; Brier {_f(ca.get('brier'), 4)} "
            f"vs const-train-base {_f(ca.get('brier_const_train_base'), 4)} vs 0.5 {_f(ca.get('brier_half'), 4)}",
            "",
            "| p bin | n | mean pred | observed |",
            "|---|---|---|---|",
        ]
        L += [
            f"| {b['lo']:.2f} | {b['n']} | {_f(b['mean_pred'])} | {_f(b['observed'])} |"
            for b in ca["bins"]
        ]
        bm = x["benchmark_proj"]
        L += [
            "",
            f"Benchmark stored projection (published today), same rows: n={bm.get('n')}, slope {_f(bm.get('slope'))} "
            f"(se {_f(bm.get('slope_se'))}), corr {_f(bm.get('corr'))}, call hit {_f(bm.get('hit_rate'))} over {bm.get('calls')} calls.",
        ]
        L += [
            "",
            f"Sample size ({kind}), n at which a Wilson 95% lower bound clears breakeven:",
        ]
        for t, v in x["sample_size"].items():
            L.append(
                f"- >= {t}: hit {_f(v['hit_rate'])}, {v['calls_per_week']:.1f} calls/week; breakevens "
                + ", ".join(f"{b:.4f}" for b in v["breakevens"])
                + "; n needed "
                + ", ".join(
                    "none (hit <= breakeven)" if n is None else f"{n:.0f}"
                    for n in v["n_needed"]
                )
                + "; weeks "
                + ", ".join("-" if w is None else f"{w:.0f}" for w in v["weeks_needed"])
            )
    k0 = res["ablation_placebo_kind"]
    L += [
        "",
        f"### Ablation ({k0}; walk-forward per row)",
        "",
        "| family | mode | n | slope | corr | MAE delta | hit>=0.5 | n>=0.5 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    L += [
        f"| {a['family']} | {a['mode']} | {a['n']} | {_f(a.get('slope'))} | {_f(a.get('corr'))} | "
        f"{_f(a.get('mae_delta'), 4)} | {_f(a.get('hit_050'))} | {a.get('n_050')} |"
        for a in res["ablation"]
    ]
    L += [
        "",
        f"### Placebo ({k0}; resid and over shuffled within date)",
        "",
        "| seed | n | slope (se) | corr | MAE delta | hit>=0.5 | n>=0.5 |",
        "|---|---|---|---|---|---|---|",
    ]
    L += [
        f"| {p['seed']} | {p['n']} | {_f(p.get('slope'))} ({_f(p.get('slope_se'))}) | {_f(p.get('corr'))} | "
        f"{_f(p.get('mae_delta'), 4)} | {_f(p.get('hit_050'))} | {p.get('n_050')} |"
        for p in res["placebo"]
    ]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stat", default="all", choices=[*STAT_COLUMN, "all"])
    ap.add_argument("--db-url", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--kind", default="both", choices=["ridge", "gbm", "both"])
    a = ap.parse_args()
    if not a.db_url:
        raise SystemExit("--db-url or DATABASE_URL required")
    kinds = ["ridge", "gbm"] if a.kind == "both" else [a.kind]
    stats = list(STAT_COLUMN) if a.stat == "all" else [a.stat]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with create_engine(a.db_url).connect() as conn:
        end = pd.read_sql("SELECT max(game_date) AS d FROM pred_recent_games", conn)[
            "d"
        ][0]
        inputs = load_inputs(conn, START, end)
    md = [
        f"# NBA residual walk-forward evaluation (data through {pd.Timestamp(end).date()})\n"
    ]
    for stat in stats:
        df = build_rows(inputs, stat, start=START)
        res = _clean(evaluate_stat(df, stat, kinds))
        (out / f"eval_{stat}.json").write_text(json.dumps(res, indent=1))
        md.append(render(res))
    (out / "eval.md").write_text("\n".join(md))
    print(f"wrote {out}/eval.md")


if __name__ == "__main__":
    main()
