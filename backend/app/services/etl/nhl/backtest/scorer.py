"""Accuracy scorer for NHL backtests (goalie saves, player SOG, team totals)."""

from __future__ import annotations

from typing import Any

import numpy as np


def _ou_correct(predicted: float, actual: float, line: float) -> bool | None:
    """Return whether O/U pick matched outcome; None on push (actual == line)."""
    if actual == line:
        return None
    pred_over = predicted > line
    actual_over = actual > line
    return pred_over == actual_over


class NHLBacktestScorer:
    """MAE and O/U hit rate for goalie saves, player SOG, and team totals."""

    def __init__(self) -> None:
        self.goalie_results: list[dict[str, Any]] = []
        self.sog_results: list[dict[str, Any]] = []
        self.totals_results: list[dict[str, Any]] = []

    def add_goalie_result(
        self,
        predicted_saves: float,
        actual_saves: float | int,
        *,
        saves_line: float | None = None,
        game_date: str | None = None,
        goalie_id: int | None = None,
        ml_predicted_saves: float | None = None,
    ) -> None:
        actual_f = float(actual_saves)
        pred_f = float(predicted_saves)
        entry: dict[str, Any] = {
            "predicted_saves": pred_f,
            "actual_saves": actual_f,
            "saves_error": abs(pred_f - actual_f),
            "game_date": game_date,
            "goalie_id": goalie_id,
        }
        if saves_line is not None:
            entry["saves_line"] = float(saves_line)
            entry["ou_correct"] = _ou_correct(pred_f, actual_f, float(saves_line))
        if ml_predicted_saves is not None:
            ml_f = float(ml_predicted_saves)
            entry["ml_predicted_saves"] = ml_f
            entry["ml_saves_error"] = abs(ml_f - actual_f)
            if saves_line is not None:
                entry["ml_ou_correct"] = _ou_correct(ml_f, actual_f, float(saves_line))
        self.goalie_results.append(entry)

    def add_sog_result(
        self,
        predicted_shots: float,
        actual_shots: float | int,
        *,
        shots_line: float | None = None,
        game_date: str | None = None,
        player_id: int | None = None,
        ml_predicted_shots: float | None = None,
    ) -> None:
        actual_f = float(actual_shots)
        pred_f = float(predicted_shots)
        entry: dict[str, Any] = {
            "predicted_shots": pred_f,
            "actual_shots": actual_f,
            "shots_error": abs(pred_f - actual_f),
            "game_date": game_date,
            "player_id": player_id,
        }
        if shots_line is not None:
            entry["shots_line"] = float(shots_line)
            entry["ou_correct"] = _ou_correct(pred_f, actual_f, float(shots_line))
        if ml_predicted_shots is not None:
            ml_f = float(ml_predicted_shots)
            entry["ml_predicted_shots"] = ml_f
            entry["ml_shots_error"] = abs(ml_f - actual_f)
            if shots_line is not None:
                entry["ml_ou_correct"] = _ou_correct(ml_f, actual_f, float(shots_line))
        self.sog_results.append(entry)

    def add_totals_result(
        self,
        predicted_total: float,
        actual_total: float | int,
        *,
        ou_line: float | None = None,
        game_date: str | None = None,
        game_id: int | None = None,
        ml_predicted_total: float | None = None,
    ) -> None:
        actual_f = float(actual_total)
        pred_f = float(predicted_total)
        entry: dict[str, Any] = {
            "predicted_total": pred_f,
            "actual_total": actual_f,
            "total_error": abs(pred_f - actual_f),
            "game_date": game_date,
            "game_id": game_id,
        }
        if ou_line is not None:
            entry["ou_line"] = float(ou_line)
            entry["ou_correct"] = _ou_correct(pred_f, actual_f, float(ou_line))
        if ml_predicted_total is not None:
            ml_f = float(ml_predicted_total)
            entry["ml_predicted_total"] = ml_f
            entry["ml_total_error"] = abs(ml_f - actual_f)
            if ou_line is not None:
                entry["ml_ou_correct"] = _ou_correct(ml_f, actual_f, float(ou_line))
        self.totals_results.append(entry)

    @staticmethod
    def _ou_hit_rate(
        rows: list[dict[str, Any]], key: str = "ou_correct"
    ) -> tuple[float | None, int]:
        graded = [r[key] for r in rows if key in r and r[key] is not None]
        if not graded:
            return None, 0
        hits = sum(1 for ok in graded if ok)
        return round(hits / len(graded), 4), len(graded)

    def compute_goalie_metrics(self) -> dict[str, Any]:
        if not self.goalie_results:
            return {}
        mae = float(np.mean([r["saves_error"] for r in self.goalie_results]))
        ou_rate, ou_n = self._ou_hit_rate(self.goalie_results)
        out: dict[str, Any] = {
            "n_goalie": len(self.goalie_results),
            "goalie_mae": round(mae, 2),
        }
        if ou_rate is not None:
            out["goalie_ou_hit_rate"] = ou_rate
            out["goalie_ou_n"] = ou_n

        ml_rows = [r for r in self.goalie_results if "ml_saves_error" in r]
        methods: dict[str, Any] = {
            "heuristic": {"mae": round(mae, 2), "n": len(self.goalie_results)},
        }
        if ml_rows:
            ml_mae = float(np.mean([r["ml_saves_error"] for r in ml_rows]))
            out["goalie_ml_mae"] = round(ml_mae, 2)
            out["goalie_ml_n"] = len(ml_rows)
            methods["ml"] = {"mae": round(ml_mae, 2), "n": len(ml_rows)}
            ml_ou_rate, ml_ou_n = self._ou_hit_rate(ml_rows, key="ml_ou_correct")
            if ml_ou_rate is not None:
                methods["ml"]["ou_hit_rate"] = ml_ou_rate
                methods["ml"]["ou_n"] = ml_ou_n
                out["goalie_ml_ou_hit_rate"] = ml_ou_rate
                out["goalie_ml_ou_n"] = ml_ou_n
        out["methods"] = methods
        return out

    def compute_sog_metrics(self) -> dict[str, Any]:
        if not self.sog_results:
            return {}
        mae = float(np.mean([r["shots_error"] for r in self.sog_results]))
        ou_rate, ou_n = self._ou_hit_rate(self.sog_results)
        out: dict[str, Any] = {
            "n_sog": len(self.sog_results),
            "sog_mae": round(mae, 2),
        }
        if ou_rate is not None:
            out["sog_ou_hit_rate"] = ou_rate
            out["sog_ou_n"] = ou_n

        ml_rows = [r for r in self.sog_results if "ml_shots_error" in r]
        methods: dict[str, Any] = {
            "heuristic": {"mae": round(mae, 2), "n": len(self.sog_results)},
        }
        if ml_rows:
            ml_mae = float(np.mean([r["ml_shots_error"] for r in ml_rows]))
            out["sog_ml_mae"] = round(ml_mae, 2)
            out["sog_ml_n"] = len(ml_rows)
            methods["ml"] = {"mae": round(ml_mae, 2), "n": len(ml_rows)}
            ml_ou_rate, ml_ou_n = self._ou_hit_rate(ml_rows, key="ml_ou_correct")
            if ml_ou_rate is not None:
                methods["ml"]["ou_hit_rate"] = ml_ou_rate
                methods["ml"]["ou_n"] = ml_ou_n
                out["sog_ml_ou_hit_rate"] = ml_ou_rate
                out["sog_ml_ou_n"] = ml_ou_n
        out["methods"] = methods
        return out

    def compute_totals_metrics(self) -> dict[str, Any]:
        if not self.totals_results:
            return {}
        mae = float(np.mean([r["total_error"] for r in self.totals_results]))
        ou_rate, ou_n = self._ou_hit_rate(self.totals_results)
        out: dict[str, Any] = {
            "n_totals": len(self.totals_results),
            "totals_mae": round(mae, 2),
        }
        if ou_rate is not None:
            out["totals_ou_hit_rate"] = ou_rate
            out["totals_ou_n"] = ou_n

        ml_rows = [r for r in self.totals_results if "ml_total_error" in r]
        methods: dict[str, Any] = {
            "heuristic": {"mae": round(mae, 2), "n": len(self.totals_results)},
        }
        if ml_rows:
            ml_mae = float(np.mean([r["ml_total_error"] for r in ml_rows]))
            out["totals_ml_mae"] = round(ml_mae, 2)
            out["totals_ml_n"] = len(ml_rows)
            methods["ml"] = {"mae": round(ml_mae, 2), "n": len(ml_rows)}
            ml_ou_rate, ml_ou_n = self._ou_hit_rate(ml_rows, key="ml_ou_correct")
            if ml_ou_rate is not None:
                methods["ml"]["ou_hit_rate"] = ml_ou_rate
                methods["ml"]["ou_n"] = ml_ou_n
                out["totals_ml_ou_hit_rate"] = ml_ou_rate
                out["totals_ml_ou_n"] = ml_ou_n
        out["methods"] = methods
        return out

    def compute_aggregate_ou_metrics(self) -> dict[str, Any]:
        """Combined O/U hit rate across all markets with a line."""
        all_rows = self.goalie_results + self.sog_results + self.totals_results
        ou_rate, ou_n = self._ou_hit_rate(all_rows)
        if ou_rate is None:
            return {}
        return {"ou_hit_rate": ou_rate, "ou_n": ou_n}

    def compute_all_metrics(self) -> dict[str, Any]:
        return {
            "goalie_metrics": self.compute_goalie_metrics(),
            "sog_metrics": self.compute_sog_metrics(),
            "totals_metrics": self.compute_totals_metrics(),
            "aggregate_ou": self.compute_aggregate_ou_metrics(),
        }
