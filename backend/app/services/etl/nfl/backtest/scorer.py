"""Accuracy scorer for NFL backtests (QB passing yards, kicker FG made)."""

from __future__ import annotations

from typing import Any

import numpy as np

KICKER_OU_LINE = 1.5


def _ou_correct(predicted: float, actual: float, line: float) -> bool | None:
    if actual == line:
        return None
    return (predicted > line) == (actual > line)


def _kicker_ou_correct(projected_made: float, actual_made: float) -> bool | None:
    """O/U on field goals made vs 1.5 line (same rules as collect_kicker_actuals)."""
    if actual_made == KICKER_OU_LINE:
        return None
    pred_over = projected_made >= 1.75
    pred_under = projected_made < 1.25
    if not pred_over and not pred_under:
        return None
    actual_over = actual_made >= 2
    if pred_over:
        return actual_over
    return not actual_over


class NFLBacktestScorer:
    """MAE and O/U for QB yards and kicker projected FGs."""

    def __init__(self) -> None:
        self.qb_results: list[dict[str, Any]] = []
        self.kicker_results: list[dict[str, Any]] = []

    def add_qb_result(
        self,
        predicted_yards: float,
        actual_yards: float | int,
        *,
        ou_line: float | None = None,
        season: int | None = None,
        week: int | None = None,
        qb_player_id: str | None = None,
        prediction_method: str | None = None,
    ) -> None:
        actual_f = float(actual_yards)
        pred_f = float(predicted_yards)
        entry: dict[str, Any] = {
            "predicted_yards": pred_f,
            "actual_yards": actual_f,
            "yards_error": abs(pred_f - actual_f),
            "season": season,
            "week": week,
            "qb_player_id": qb_player_id,
            "prediction_method": prediction_method,
        }
        if ou_line is not None:
            entry["ou_line"] = float(ou_line)
            entry["ou_correct"] = _ou_correct(pred_f, actual_f, float(ou_line))
        self.qb_results.append(entry)

    def add_kicker_result(
        self,
        projected_fg_made: float,
        actual_fg_made: float | int,
        *,
        season: int | None = None,
        week: int | None = None,
        kicker_player_id: str | None = None,
    ) -> None:
        actual_f = float(actual_fg_made)
        pred_f = float(projected_fg_made)
        entry: dict[str, Any] = {
            "projected_fg_made": pred_f,
            "actual_fg_made": actual_f,
            "fg_made_error": abs(pred_f - actual_f),
            "season": season,
            "week": week,
            "kicker_player_id": kicker_player_id,
            "ou_correct": _kicker_ou_correct(pred_f, actual_f),
        }
        self.kicker_results.append(entry)

    @staticmethod
    def _ou_hit_rate(
        rows: list[dict[str, Any]], key: str = "ou_correct"
    ) -> tuple[float | None, int]:
        graded = [r[key] for r in rows if key in r and r[key] is not None]
        if not graded:
            return None, 0
        hits = sum(1 for ok in graded if ok)
        return round(hits / len(graded), 4), len(graded)

    def compute_qb_metrics(self) -> dict[str, Any]:
        if not self.qb_results:
            return {}
        mae = float(np.mean([r["yards_error"] for r in self.qb_results]))
        ou_rate, ou_n = self._ou_hit_rate(self.qb_results)
        out: dict[str, Any] = {
            "n_qb": len(self.qb_results),
            "qb_mae": round(mae, 2),
        }
        if ou_rate is not None:
            out["qb_ou_hit_rate"] = ou_rate
            out["qb_ou_n"] = ou_n
        methods: dict[str, Any] = {}
        by_method: dict[str, list[dict[str, Any]]] = {}
        for row in self.qb_results:
            method = row.get("prediction_method") or "unknown"
            by_method.setdefault(str(method), []).append(row)
        for method, rows in by_method.items():
            methods[method] = {
                "mae": round(float(np.mean([r["yards_error"] for r in rows])), 2),
                "n": len(rows),
            }
            m_ou, m_n = self._ou_hit_rate(rows)
            if m_ou is not None:
                methods[method]["ou_hit_rate"] = m_ou
                methods[method]["ou_n"] = m_n
        out["methods"] = methods
        return out

    def compute_kicker_metrics(self) -> dict[str, Any]:
        if not self.kicker_results:
            return {}
        mae = float(np.mean([r["fg_made_error"] for r in self.kicker_results]))
        ou_rate, ou_n = self._ou_hit_rate(self.kicker_results)
        out: dict[str, Any] = {
            "n_kicker": len(self.kicker_results),
            "kicker_mae": round(mae, 2),
        }
        if ou_rate is not None:
            out["kicker_ou_hit_rate"] = ou_rate
            out["kicker_ou_n"] = ou_n
        return out

    def compute_aggregate_ou_metrics(self) -> dict[str, Any]:
        all_rows = self.qb_results + self.kicker_results
        ou_rate, ou_n = self._ou_hit_rate(all_rows)
        if ou_rate is None:
            return {}
        return {"ou_hit_rate": ou_rate, "ou_n": ou_n}

    def compute_all_metrics(self) -> dict[str, Any]:
        return {
            "qb_metrics": self.compute_qb_metrics(),
            "kicker_metrics": self.compute_kicker_metrics(),
            "aggregate_ou": self.compute_aggregate_ou_metrics(),
        }
