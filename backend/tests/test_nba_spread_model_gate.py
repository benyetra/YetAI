"""NBA spread ML: point-in-time features and the beat-Elo upload gate."""

from __future__ import annotations

import math
from datetime import date
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd

from app.services.etl.nba import _spread_ml_predict as smp
from app.services.etl.nba._spread_features import (
    SPREAD_MODEL_FEATURES,
    compute_game_features,
)
from app.services.etl.nba.ml_training import train_spread_model as tsm
from app.services.etl.nba.ml_training.build_spread_dataset import build_from_rows


def _g(d, home, away, hs, as_):
    return NS(
        game_date=d,
        home_team_name=home,
        away_team_name=away,
        home_score=hs,
        away_score=as_,
        actual_margin=hs - as_,
    )


GAMES = [
    _g(date(2025, 1, 1), "A", "B", 110, 100),
    _g(date(2025, 1, 3), "B", "C", 90, 100),
    _g(date(2025, 1, 4), "C", "A", 105, 95),
]


def test_features_point_in_time_rest_and_missing_market():
    f = compute_game_features(
        GAMES,
        game_date=date(2025, 1, 5),
        home_team_name="C",
        away_team_name="D",
        market_spread_home=None,
        market_total=220.5,
    )
    assert list(f) == SPREAD_MODEL_FEATURES
    assert f["home_rest_days"] == 1.0 and f["home_b2b"] == 1.0
    assert f["away_rest_days"] == 7.0  # no history → capped
    assert f["home_ppg_l10"] == 102.5 and f["home_margin_l10"] == 10.0
    assert math.isnan(f["away_ppg_l10"])
    assert math.isnan(f["market_spread_home"])  # missing line ≠ pick'em
    assert f["market_total"] == 220.5
    assert f["elo_diff"] > 0  # C won both games


def test_build_from_rows_only_uses_earlier_games_and_joins_lines():
    line = NS(spread_home=-3.5, total=221.0)
    feats, target = build_from_rows(
        GAMES,
        {(date(2025, 1, 4), "C", "A"): line},
        date(2025, 1, 3),
        date(2025, 1, 31),
    )
    assert list(target) == [-10.0, 10.0]  # 1/1 game is history only
    assert feats.iloc[0]["home_ppg_l10"] == 100.0  # B's 1/1 game, not 1/3
    assert feats.iloc[1]["market_spread_home"] == -3.5
    assert math.isnan(feats.iloc[0]["market_total"])


def _dataset(signal_from_market: bool, n=400):
    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {c: rng.normal(size=n) for c in SPREAD_MODEL_FEATURES},
        columns=SPREAD_MODEL_FEATURES,
    )
    df["base_margin"] = 0.0
    df["elo_pace_margin"] = 0.0
    if signal_from_market:
        y = -10 * df["market_spread_home"] + rng.normal(scale=0.5, size=n)
    else:
        # Elo is almost exact here, which a shallow regularized model can't match.
        df["base_margin"] = rng.normal(scale=10, size=n)
        y = pd.Series(df["base_margin"] + rng.normal(scale=0.5, size=n))
    return df, pd.Series(y, dtype=float)


def _run(monkeypatch, signal_from_market):
    uploads = []
    monkeypatch.setattr(tsm, "build", lambda s, e: _dataset(signal_from_market))
    monkeypatch.setattr(
        tsm, "upload_spread_model", lambda m, md: uploads.append(md) or {"k": 1}
    )
    out = tsm.run(
        season_start=date(2024, 10, 1), season_end=date(2026, 6, 30), upload=True
    )
    return out, uploads


def test_gate_blocks_model_that_loses_to_elo(monkeypatch):
    out, uploads = _run(monkeypatch, signal_from_market=False)
    assert out["status"] == "below_baseline"
    assert not uploads


def test_gate_uploads_model_that_beats_elo(monkeypatch):
    out, uploads = _run(monkeypatch, signal_from_market=True)
    assert out["status"] == "ok"
    assert uploads and uploads[0]["beats_baseline"] is True
    assert uploads[0]["split"] == "chronological"
    assert uploads[0]["test_mae"] < uploads[0]["baseline_test_mae"]


def test_predictor_refuses_models_without_baseline_win():
    assert not smp.beats_baseline({"test_mae": 11.7})  # pre-gate upload
    assert not smp.beats_baseline({"test_mae": 11.7, "baseline_test_mae": 11.2})
    win = {"test_mae": 10.1, "baseline_test_mae": 11.2}
    # A random-split win flatters the model, so only chronological ones count.
    assert not smp.beats_baseline(win)
    assert not smp.beats_baseline({**win, "split": "random"})
    assert smp.beats_baseline({**win, "split": "chronological"})


def test_predictor_ignores_ungated_model_on_load(monkeypatch):
    import json
    import pickle

    monkeypatch.setattr(smp, "_MODEL", None)
    monkeypatch.setattr(smp, "_METADATA", None)
    monkeypatch.setattr(smp, "_LOAD_FAILED", False)

    def download(key, path):
        if key.endswith(".pkl"):
            path.write_bytes(pickle.dumps({"fake": "model"}))
        else:
            path.write_text(json.dumps({"features": ["elo_diff"], "test_mae": 11.7}))

    monkeypatch.setattr(smp, "_download_artifact", download)
    assert smp.model_available() is False
    assert smp.predict_margin({"elo_diff": 1.0}) is None


def test_predictor_passes_missing_values_as_nan(monkeypatch):
    seen = {}

    class FakeModel:
        def predict(self, vec):
            seen["vec"] = vec
            return [1.0]

    monkeypatch.setattr(smp, "_LOAD_FAILED", False)
    monkeypatch.setattr(smp, "_MODEL", FakeModel())
    monkeypatch.setattr(
        smp, "_METADATA", {"features": ["elo_diff", "market_spread_home"]}
    )
    smp.predict_margin({"elo_diff": 2.0, "market_spread_home": None})
    assert seen["vec"][0][0] == 2.0 and math.isnan(seen["vec"][0][1])


def test_totals_blend_uses_last_season_then_shifts_to_this_one():
    from types import SimpleNamespace as G

    from app.services.etl.nba.totals_projector import (
        CURRENT_SEASON_PRIOR_GAMES,
        MIN_FORM_GAMES,
        blended_scoring,
    )

    def games(n, scored, allowed):
        return [
            G(
                home_team_name="A",
                away_team_name="B",
                home_score=scored,
                away_score=allowed,
            )
            for _ in range(n)
        ]

    last = games(40, 112, 108)
    assert blended_scoring(last, [], "A") == (112, 108)  # this season ignored
    n = CURRENT_SEASON_PRIOR_GAMES
    scored, allowed = blended_scoring(last, games(n, 122, 118), "A")
    assert (round(scored, 1), round(allowed, 1)) == (117.0, 113.0)  # 50/50
    assert blended_scoring(games(3, 100, 100), [], "A") is None  # no history
    cur = games(MIN_FORM_GAMES, 120, 110)
    assert blended_scoring([], cur, "A") == (120, 110)


def _final(d, home, away, hs, as_):
    from app.services.etl.nba.totals_baseline import Final

    return Final(d, home, away, hs, as_)


def test_totals_baseline_bias_recommend_and_record():
    from datetime import date, timedelta
    from types import SimpleNamespace as R

    from app.services.etl.nba import totals_baseline as tb

    # Last season: A and B each score/allow 110. This season they score 120.
    last = [
        _final(date(2026, 1, 1) + timedelta(days=i), "A", "B", 110, 110)
        for i in range(12)
    ]
    cur = [
        _final(date(2026, 10, 21) + timedelta(days=i), "A", "B", 125, 125)
        for i in range(6)
    ]
    finals = last + cur

    # Early in the season (inside the 14-day delay) the baseline is last season's.
    s = tb.baseline_scores(finals, "A", "B", date(2026, 10, 25))
    assert s == (110, 110)
    # ...so it under-projects by 30 total; the correction adds a shrunk share.
    bias, n = tb.recent_bias(finals, date(2026, 10, 25))
    # four errors of +30, shrunk by 10: 120 / 14.
    assert n == 4 and abs(bias - 120 / 14) < 1e-9
    assert tb.recent_bias(last, date(2026, 10, 25)) == (0.0, 0)

    # Calls: small edges are NO_PLAY; unproven calls carry 50% confidence.
    assert tb.recommend(2.0, (0, 0))[0] == "NO_PLAY"
    rec, conf, note = tb.recommend(-6.0, (0, 0))
    assert (rec, conf) == ("UNDER", 0.5) and "unproven" in note
    # A long losing record withholds calls; a winning one reports its rate.
    assert tb.recommend(-6.0, (40, 100))[0] == "NO_PLAY"
    rec, conf, _ = tb.recommend(6.0, (70, 100))
    assert rec == "OVER" and 0.58 <= conf <= 0.65

    # The record uses the edge's sign (not the shown call) and skips pushes.
    rows = [
        R(projected_total=220, market_total=226, actual_total=215),  # under, hit
        R(projected_total=232, market_total=226, actual_total=220),  # over, miss
        R(projected_total=224, market_total=226, actual_total=230),  # small edge
        R(projected_total=220, market_total=226, actual_total=226),  # push
    ]
    assert tb.pick_record(rows) == (1, 2)
