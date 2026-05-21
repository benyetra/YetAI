"""Accuracy Scorer for Backtesting.

Computes comprehensive accuracy metrics across all model layers,
matching the format used on /mlb/results and /mlb/game_results.

REQ-BT-035 through REQ-BT-051.
"""

import logging
import math
from collections import defaultdict

import numpy as np

logger = logging.getLogger(__name__)


class BacktestScorer:
    """Computes accuracy metrics for backtest results.

    REQ-BT-035: Brier Score by bucket.
    REQ-BT-036: Moneyline accuracy.
    REQ-BT-037: O/U accuracy.
    REQ-BT-038: Total runs MAE.
    REQ-BT-039: Run line accuracy.
    REQ-BT-040: Calibration table.
    REQ-BT-041-044: K projection metrics.
    REQ-BT-045: Hit prediction metrics.
    REQ-BT-046-047: HR prediction metrics.
    REQ-BT-048-049: Edge & market comparison.
    REQ-BT-050-051: Segmented analysis.
    """

    def __init__(self):
        self.game_results = []
        self.k_results = []
        self.hit_results = []
        self.hr_results = []
        self.market_comparisons = []

    def add_game_result(self, prediction, actuals, metadata):
        """Add a single game's prediction vs actual outcome."""
        wp = prediction["predicted_home_wp"]
        actual_win = 1 if actuals["actual_winner"] == "home" else 0

        result = {
            "predicted_home_wp": wp,
            "actual_winner": actuals["actual_winner"],
            "actual_win_binary": actual_win,
            "predicted_total": prediction["predicted_total"],
            "actual_total": actuals["actual_total"],
            "predicted_run_line": prediction.get("predicted_run_line", 0),
            "actual_margin": actuals["home_score"] - actuals["away_score"],
            "home_score": actuals["home_score"],
            "away_score": actuals["away_score"],
            "model_confidence": prediction.get("model_confidence", 0.5),
            "model_type": prediction.get("model_type", "heuristic"),
            "data_quality_score": metadata.get("data_quality_score", 0.0),
            "pre_calibration_wp": prediction.get("pre_calibration_wp", wp),
            "calibration_applied": prediction.get("calibration_applied", False),
            # Metadata for segmented analysis
            "game_date": metadata.get("game_date", ""),
            "venue_name": metadata.get("venue_name", ""),
            "temperature": metadata.get("temperature", 72),
            "used_estimated_weather": metadata.get("used_estimated_weather", True),
            "had_historical_odds": metadata.get("had_historical_odds", False),
            "pitcher_stats_available": metadata.get("pitcher_stats_available", False),
        }

        # Brier contribution (REQ-BT-035)
        result["brier_contribution"] = (wp - actual_win) ** 2

        # ML correct (REQ-BT-036)
        predicted_winner = "home" if wp > 0.5 else "away"
        result["ml_correct"] = predicted_winner == actuals["actual_winner"]

        # Total correct (REQ-BT-037)
        result["total_error"] = prediction["predicted_total"] - actuals["actual_total"]

        # Run line correct (REQ-BT-039)
        pred_margin_dir = 1 if prediction.get("predicted_run_line", 0) > 0 else -1
        actual_margin_dir = 1 if result["actual_margin"] > 0 else -1
        result["run_line_correct"] = pred_margin_dir == actual_margin_dir

        # Market comparison data (REQ-BT-048/049)
        market_prob = metadata.get("market_implied_prob")
        market_total = metadata.get("market_total")
        odds_data = metadata.get("odds_data", {})

        if market_prob is not None:
            actual_win = result["actual_win_binary"]
            self.market_comparisons.append(
                {
                    "model_home_wp": result["predicted_home_wp"],
                    "market_home_prob": market_prob,
                    "actual_win": actual_win,
                    "model_brier": (result["predicted_home_wp"] - actual_win) ** 2,
                    "market_brier": (market_prob - actual_win) ** 2,
                    "market_total": market_total,
                    "actual_total": actuals["actual_total"],
                }
            )
            result["market_home_prob"] = market_prob
            result["had_historical_odds"] = True
        elif odds_data:
            self._add_market_comparison(result, odds_data, actuals)

        self.game_results.append(result)

    def add_k_result(
        self,
        side,
        projected_k,
        actual_k,
        projected_ip=None,
        actual_ip=None,
        pitcher_k9=None,
        n_starts=None,
        fanduel_line=None,
    ):
        """Add a K projection result (REQ-BT-041-044)."""
        if projected_k is None or actual_k is None:
            return

        entry = {
            "side": side,
            "projected_k": projected_k,
            "actual_k": actual_k,
            "projected_ip": projected_ip,
            "actual_ip": actual_ip,
            "pitcher_k9": pitcher_k9,
            "n_starts": n_starts,
            "k_error": abs(projected_k - actual_k),
            "gold_standard": abs(projected_k - actual_k) <= 0.25,
            "fanduel_line": fanduel_line,
        }

        # vs-line accuracy (REQ-BT-043)
        if fanduel_line is not None:
            proj_over = projected_k > fanduel_line
            actual_over = actual_k > fanduel_line
            entry["k_vs_line_correct"] = proj_over == actual_over

        self.k_results.append(entry)

    def add_hit_result(self, side, projected_hits, actual_hits):
        """Add a hit prediction result (REQ-BT-045)."""
        if projected_hits is None or actual_hits is None:
            return

        self.hit_results.append(
            {
                "side": side,
                "projected_hits": projected_hits,
                "actual_hits": actual_hits,
                "hit_error": abs(projected_hits - actual_hits),
                "hit_correct": round(projected_hits) == actual_hits,
            }
        )

    def add_hr_result(self, projected_hr_prob, actual_hr, game_date=None):
        """Add an HR prediction result (REQ-BT-046/047)."""
        self.hr_results.append(
            {
                "projected_hr_prob": projected_hr_prob,
                "actual_hr": actual_hr,
                "had_hr": 1 if actual_hr > 0 else 0,
                "game_date": game_date,
            }
        )

    def _add_market_comparison(self, result, odds_data, actuals):
        """Compute market comparison metrics (REQ-BT-048/049)."""
        from app.services.etl.mlb.odds_utils import american_to_break_even_prob

        h2h = odds_data.get("h2h", {})
        if not h2h:
            return

        # Find home team odds
        home_odds = None
        for team, odds in h2h.items():
            # Assume first entry is away, second is home (typical ordering)
            home_odds = odds  # Will be overwritten, last one wins

        if home_odds is None:
            return

        market_home_prob = american_to_break_even_prob(home_odds)
        actual_win = result["actual_win_binary"]

        self.market_comparisons.append(
            {
                "model_home_wp": result["predicted_home_wp"],
                "market_home_prob": market_home_prob,
                "actual_win": actual_win,
                "model_brier": (result["predicted_home_wp"] - actual_win) ** 2,
                "market_brier": (market_home_prob - actual_win) ** 2,
                "market_total": odds_data.get("totals", {}).get("point"),
                "actual_total": actuals["actual_total"],
            }
        )

        result["market_home_prob"] = market_home_prob
        result["had_historical_odds"] = True

    def compute_game_metrics(self):
        """Compute all game-level accuracy metrics (REQ-BT-035-040)."""
        if not self.game_results:
            return {}

        n = len(self.game_results)

        # Brier Score (REQ-BT-035)
        brier = np.mean([r["brier_contribution"] for r in self.game_results])

        # ML Accuracy (REQ-BT-036)
        ml_correct = sum(1 for r in self.game_results if r["ml_correct"])
        ml_accuracy = ml_correct / n

        # Total runs MAE (REQ-BT-038)
        total_errors = [abs(r["total_error"]) for r in self.game_results]
        total_mae = np.mean(total_errors)

        # O/U Accuracy (REQ-BT-037)
        ou_results = []
        for r in self.game_results:
            proj = r["predicted_total"]
            actual = r["actual_total"]
            if proj != actual:  # Skip pushes
                ou_results.append(
                    (proj > actual and r["total_error"] > 0)
                    or (proj < actual and r["total_error"] < 0)
                )
        ou_accuracy = np.mean(ou_results) if ou_results else None
        ou_total = len(ou_results)

        # Run Line Accuracy (REQ-BT-039)
        rl_correct = sum(1 for r in self.game_results if r["run_line_correct"])
        rl_accuracy = rl_correct / n

        # Calibration table (REQ-BT-040)
        calibration = self._compute_calibration()

        # Brier by bucket (REQ-BT-035)
        brier_by_bucket = self._compute_brier_by_bucket()

        return {
            "n_games": n,
            "brier_score": round(brier, 5),
            "ml_accuracy": round(ml_accuracy, 4),
            "ml_correct": ml_correct,
            "ou_accuracy": round(ou_accuracy, 4) if ou_accuracy is not None else None,
            "ou_total": ou_total,
            "total_mae": round(total_mae, 2),
            "run_line_accuracy": round(rl_accuracy, 4),
            "rl_correct": rl_correct,
            "calibration": calibration,
            "brier_by_bucket": brier_by_bucket,
        }

    def _compute_calibration(self):
        """Compute calibration table (REQ-BT-040)."""
        # 5% bins from 0.35 to 0.70+
        bins = [
            (0.00, 0.35, "0.00-0.35"),
            (0.35, 0.45, "0.35-0.45"),
            (0.45, 0.55, "0.45-0.55"),
            (0.55, 0.65, "0.55-0.65"),
            (0.65, 1.01, "0.65+"),
        ]

        calibration = []
        for low, high, label in bins:
            bucket_results = [
                r for r in self.game_results if low <= r["predicted_home_wp"] < high
            ]
            if not bucket_results:
                continue

            predicted = np.mean([r["predicted_home_wp"] for r in bucket_results])
            actual = np.mean([r["actual_win_binary"] for r in bucket_results])
            deviation = abs(predicted - actual)

            calibration.append(
                {
                    "bucket": label,
                    "predicted": round(predicted, 3),
                    "actual": round(actual, 3),
                    "count": len(bucket_results),
                    "deviation": round(deviation, 3),
                    "status": "OK" if deviation <= 0.05 else "WARNING",
                }
            )

        return calibration

    def _compute_brier_by_bucket(self):
        """Compute Brier score by probability bucket (REQ-BT-035)."""
        buckets = {
            "0.35-0.45": [],
            "0.45-0.55": [],
            "0.55-0.65": [],
            "0.65+": [],
        }

        for r in self.game_results:
            wp = r["predicted_home_wp"]
            bc = r["brier_contribution"]
            if 0.35 <= wp < 0.45:
                buckets["0.35-0.45"].append(bc)
            elif 0.45 <= wp < 0.55:
                buckets["0.45-0.55"].append(bc)
            elif 0.55 <= wp < 0.65:
                buckets["0.55-0.65"].append(bc)
            elif wp >= 0.65:
                buckets["0.65+"].append(bc)

        return {k: round(np.mean(v), 5) if v else None for k, v in buckets.items()}

    def compute_k_metrics(self):
        """Compute K projection metrics (REQ-BT-041-044)."""
        if not self.k_results:
            return {}

        n = len(self.k_results)

        # K MAE (REQ-BT-041)
        k_mae = np.mean([r["k_error"] for r in self.k_results])

        # Gold standard rate (REQ-BT-042)
        gold = sum(1 for r in self.k_results if r["gold_standard"])
        gold_rate = gold / n

        # Offset effectiveness (REQ-BT-044) - track by n_starts
        by_experience = defaultdict(list)
        for r in self.k_results:
            ns = r.get("n_starts", 0) or 0
            if ns <= 5:
                by_experience["early_season"].append(r["k_error"])
            elif ns <= 15:
                by_experience["mid_season"].append(r["k_error"])
            else:
                by_experience["established"].append(r["k_error"])

        # K/9 tier breakdown (REQ-BT-051)
        by_k9 = defaultdict(list)
        for r in self.k_results:
            k9 = r.get("pitcher_k9", 8.0) or 8.0
            if k9 < 7.0:
                by_k9["low_k9"].append(r["k_error"])
            elif k9 <= 9.0:
                by_k9["mid_k9"].append(r["k_error"])
            else:
                by_k9["high_k9"].append(r["k_error"])

        # vs-line accuracy (REQ-BT-043)
        k_vs_line_results = [r for r in self.k_results if "k_vs_line_correct" in r]
        k_vs_line_correct = sum(1 for r in k_vs_line_results if r["k_vs_line_correct"])
        k_vs_line_accuracy = (
            k_vs_line_correct / len(k_vs_line_results) if k_vs_line_results else None
        )

        return {
            "n_pitchers": n,
            "k_mae": round(k_mae, 2),
            "k_gold_standard_rate": round(gold_rate, 4),
            "k_gold_standard_count": gold,
            "k_vs_line_accuracy": (
                round(k_vs_line_accuracy, 4) if k_vs_line_accuracy is not None else None
            ),
            "k_vs_line_total": len(k_vs_line_results),
            "by_experience": {
                k: round(np.mean(v), 2) for k, v in by_experience.items()
            },
            "by_k9_tier": {k: round(np.mean(v), 2) for k, v in by_k9.items()},
        }

    def compute_hit_metrics(self):
        """Compute hit prediction metrics (REQ-BT-045)."""
        if not self.hit_results:
            return {}

        n = len(self.hit_results)
        hit_mae = np.mean([r["hit_error"] for r in self.hit_results])
        hit_correct = sum(1 for r in self.hit_results if r["hit_correct"])

        return {
            "n_predictions": n,
            "hit_mae": round(hit_mae, 2),
            "hit_accuracy": round(hit_correct / n, 4),
            "hit_correct": hit_correct,
        }

    def compute_hr_metrics(self):
        """Compute HR prediction metrics (REQ-BT-046/047)."""
        if not self.hr_results:
            return {}

        # AUC-ROC (REQ-BT-047)
        try:
            probs = [r["projected_hr_prob"] for r in self.hr_results]
            actuals = [r["had_hr"] for r in self.hr_results]

            # Simple AUC computation (Mann-Whitney U statistic)
            pos = [(p, a) for p, a in zip(probs, actuals) if a == 1]
            neg = [(p, a) for p, a in zip(probs, actuals) if a == 0]

            if pos and neg:
                concordant = sum(
                    1 for p_pos, _ in pos for p_neg, _ in neg if p_pos > p_neg
                )
                tied = sum(
                    0.5 for p_pos, _ in pos for p_neg, _ in neg if p_pos == p_neg
                )
                auc = (concordant + tied) / (len(pos) * len(neg))
            else:
                auc = 0.5
        except Exception:
            auc = 0.5

        # Top-10 hit rate by game date (REQ-BT-046)
        by_date = defaultdict(list)
        for r in self.hr_results:
            by_date[r.get("game_date", "unknown")].append(r)

        top10_hits = 0
        top10_total = 0
        for dt, results in by_date.items():
            sorted_by_prob = sorted(
                results, key=lambda x: x["projected_hr_prob"], reverse=True
            )
            top10 = sorted_by_prob[:10]
            top10_total += 1
            if any(r["had_hr"] for r in top10):
                top10_hits += 1

        return {
            "n_predictions": len(self.hr_results),
            "hr_auc_roc": round(auc, 3),
            "hr_top10_hit_rate": round(top10_hits / max(top10_total, 1), 4),
            "hr_top10_hits": top10_hits,
            "hr_top10_total": top10_total,
        }

    def compute_market_metrics(self):
        """Compute edge & market comparison metrics (REQ-BT-048/049)."""
        if not self.market_comparisons:
            return {}

        n = len(self.market_comparisons)

        model_brier = np.mean([r["model_brier"] for r in self.market_comparisons])
        market_brier = np.mean([r["market_brier"] for r in self.market_comparisons])
        delta = model_brier - market_brier  # Negative = model better

        # Simulated ROI on "edge" bets (REQ-BT-048)
        # Simplified: if model > market by 3%, bet home; if model < market by 3%, bet away
        roi_results = []
        for r in self.market_comparisons:
            edge = r["model_home_wp"] - r["market_home_prob"]
            if abs(edge) > 0.03:
                bet_home = edge > 0
                won = (r["actual_win"] == 1) == bet_home
                roi_results.append(1.0 if won else -1.0)

        simulated_roi = np.mean(roi_results) if roi_results else 0.0

        return {
            "n_games_with_odds": n,
            "model_brier": round(model_brier, 5),
            "market_brier": round(market_brier, 5),
            "model_vs_market_brier": round(delta, 5),
            "simulated_roi": round(simulated_roi, 4),
            "simulated_bets": len(roi_results),
        }

    def compute_segmented_analysis(self):
        """Compute segmented breakdowns (REQ-BT-050/051)."""
        if not self.game_results:
            return {}

        # By month (REQ-BT-050)
        by_month = defaultdict(list)
        for r in self.game_results:
            gd = r.get("game_date", "")
            if len(gd) >= 7:
                month = int(gd[5:7])
                by_month[month].append(r)

        month_names = {
            3: "Mar",
            4: "Apr",
            5: "May",
            6: "Jun",
            7: "Jul",
            8: "Aug",
            9: "Sep",
            10: "Oct",
        }
        month_accuracy = {}
        for m, results in sorted(by_month.items()):
            correct = sum(1 for r in results if r["ml_correct"])
            name = month_names.get(m, str(m))
            month_accuracy[name] = {
                "ml_accuracy": round(correct / len(results), 3),
                "n_games": len(results),
            }

        # By temperature bracket (REQ-BT-050)
        temp_brackets = {"<60F": [], "60-80F": [], ">80F": []}
        for r in self.game_results:
            temp = r.get("temperature", 72)
            if temp < 60:
                temp_brackets["<60F"].append(r)
            elif temp <= 80:
                temp_brackets["60-80F"].append(r)
            else:
                temp_brackets[">80F"].append(r)

        temp_accuracy = {}
        for bracket, results in temp_brackets.items():
            if results:
                correct = sum(1 for r in results if r["ml_correct"])
                temp_accuracy[bracket] = {
                    "ml_accuracy": round(correct / len(results), 3),
                    "n_games": len(results),
                }

        # By data quality tier
        quality_tiers = {"high_quality": [], "medium_quality": [], "low_quality": []}
        for r in self.game_results:
            dq = r.get("data_quality_score", 0)
            if dq >= 0.75:
                quality_tiers["high_quality"].append(r)
            elif dq >= 0.5:
                quality_tiers["medium_quality"].append(r)
            else:
                quality_tiers["low_quality"].append(r)

        quality_accuracy = {}
        for tier, results in quality_tiers.items():
            if results:
                correct = sum(1 for r in results if r["ml_correct"])
                quality_accuracy[tier] = {
                    "ml_accuracy": round(correct / len(results), 3),
                    "n_games": len(results),
                }

        return {
            "by_month": month_accuracy,
            "by_temperature": temp_accuracy,
            "by_data_quality": quality_accuracy,
        }

    def compute_all_metrics(self):
        """Compute all metrics and return a comprehensive results dict."""
        return {
            "game_metrics": self.compute_game_metrics(),
            "k_metrics": self.compute_k_metrics(),
            "hit_metrics": self.compute_hit_metrics(),
            "hr_metrics": self.compute_hr_metrics(),
            "market_metrics": self.compute_market_metrics(),
            "segmented": self.compute_segmented_analysis(),
        }
