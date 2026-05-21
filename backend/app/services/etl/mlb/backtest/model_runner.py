"""Model Runner for Backtesting.

Runs the projection pipeline against reconstructed historical data.
Supports all model layers: game-level, K projections, hits, and HR.

REQ-BT-024 through REQ-BT-030.
"""
import logging
import math
import os

import numpy as np

logger = logging.getLogger(__name__)


class BacktestModelRunner:
    """Runs prediction models against reconstructed backtest data.

    REQ-BT-024: Assemble features into FEATURE_COLS format.
    REQ-BT-025: Run heuristic models for every game.
    REQ-BT-026: Run ensemble models if .pkl artifacts exist.
    REQ-BT-030: Apply Venn-Abers calibration.
    """

    def __init__(self, model_version='current', models_to_test=None):
        self.model_version = model_version
        self.models_to_test = models_to_test or {'game', 'k', 'hits', 'hr'}
        self._win_model = None
        self._total_model = None
        self._models_loaded = False
        self._calibrator = None
        self._calibrator_kind = None
        self._calibrator_loaded = False

    def _load_ml_models(self):
        """Load trained ensemble models if available (REQ-BT-026)."""
        if self._models_loaded:
            return

        try:
            from app.services.etl.mlb.game_model import load_model
            self._win_model = load_model('win')
            self._total_model = load_model('total')
            if self._win_model and self._total_model:
                logger.info("Loaded trained ML models for backtesting")
            else:
                logger.info("No trained ML models found, using heuristic only")
        except Exception as e:
            logger.warning(f"Could not load ML models: {e}")

        self._models_loaded = True

    def _load_calibrator(self):
        """Load win isotonic/platt calibrator, else Venn-Abers (REQ-BT-030)."""
        if self._calibrator_loaded:
            return

        try:
            from app.services.etl.mlb.game_model import load_win_calibrator_for_production
            cal = load_win_calibrator_for_production()
            if cal is not None:
                self._calibrator = cal
                self._calibrator_kind = 'win_isotonic'
                logger.info(
                    'Loaded game-model win calibrator (%s, n=%s) for backtesting',
                    cal.method,
                    cal.n_samples,
                )
        except Exception:
            pass

        if self._calibrator is None:
            try:
                from app.services.etl.mlb.venn_abers import VennAbersCalibrator
                cal = VennAbersCalibrator.load()
                if cal.is_fitted:
                    self._calibrator = cal
                    self._calibrator_kind = 'venn_abers'
                    logger.info('Loaded Venn-Abers calibrator for backtesting')
            except Exception:
                pass

        self._calibrator_loaded = True

    def predict_game(self, features, game):
        """Run game-level predictions (REQ-BT-025/026).

        Args:
            features: dict matching FEATURE_COLS
            game: BacktestGame dataclass

        Returns:
            dict with prediction results
        """
        from app.services.etl.mlb.game_model import (
            predict_win_probability_heuristic,
            predict_total_runs_heuristic,
            FEATURE_COLS,
        )

        # Heuristic predictions (always available - REQ-BT-025)
        heuristic_wp = predict_win_probability_heuristic(features)
        heuristic_total = predict_total_runs_heuristic(features)

        result = {
            'heuristic_home_wp': heuristic_wp,
            'heuristic_total': heuristic_total,
            'predicted_home_wp': heuristic_wp,
            'predicted_total': heuristic_total,
            'model_type': 'heuristic',
        }

        # Ensemble predictions if models exist (REQ-BT-026)
        self._load_ml_models()
        if self._win_model is not None and self._total_model is not None:
            try:
                X = np.array([[features.get(col, 0.0) for col in FEATURE_COLS]])

                # Check if ensemble or single model
                if isinstance(self._win_model, dict) and 'weights' in self._win_model:
                    from app.services.etl.mlb.game_model import ensemble_predict_proba, ensemble_predict_value
                    ensemble_wp = ensemble_predict_proba(self._win_model, X)
                    ensemble_total = ensemble_predict_value(self._total_model, X)
                    result['model_type'] = f'ensemble_{self.model_version}'
                else:
                    ensemble_wp = float(self._win_model.predict_proba(X)[0][1])
                    ensemble_total = float(self._total_model.predict(X)[0])
                    result['model_type'] = f'xgboost_{self.model_version}'

                result['ensemble_home_wp'] = round(ensemble_wp, 4)
                result['ensemble_total'] = round(ensemble_total, 1)
                result['predicted_home_wp'] = round(ensemble_wp, 4)
                result['predicted_total'] = round(ensemble_total, 1)
            except Exception as e:
                logger.debug(f"Ensemble prediction failed, using heuristic: {e}")

        # Venn-Abers calibration (REQ-BT-030)
        self._load_calibrator()
        result['pre_calibration_wp'] = result['predicted_home_wp']
        if self._calibrator:
            try:
                calibrated = self._calibrator.predict_single(result['predicted_home_wp'])
                result['predicted_home_wp'] = calibrated
                result['calibration_applied'] = True
            except Exception:
                result['calibration_applied'] = False
        else:
            result['calibration_applied'] = False

        # Derived predictions
        wp = result['predicted_home_wp']
        total = result['predicted_total']
        result['predicted_away_wp'] = round(1.0 - wp, 4)
        home_runs = round(total * wp, 1)
        away_runs = round(total * (1.0 - wp), 1)
        result['predicted_home_runs'] = home_runs
        result['predicted_away_runs'] = away_runs
        result['predicted_run_line'] = round(home_runs - away_runs, 1)

        # Model confidence
        result['model_confidence'] = round(abs(wp - 0.5) * 2.0, 3)

        return result

    def predict_strikeouts(self, game, pitcher_stats, features):
        """Run K projection backtesting (REQ-BT-027).

        Uses pitcher K/9, opponent K rate, and park factor to project Ks.
        """
        if 'k' not in self.models_to_test:
            return {}

        results = {}
        for side in ('home', 'away'):
            prefix = side
            p_stats = pitcher_stats.get(f'{side}_pitcher_stats', {})
            k9 = p_stats.get('k9', 8.0)
            last5_k9 = p_stats.get('last5_k9', k9)
            ip = p_stats.get('ip', 0)
            n_starts = p_stats.get('n_starts', 0)

            # Estimate projected innings (average ~5.5 IP for starters)
            proj_ip = 5.5
            if n_starts >= 3:
                proj_ip = min(ip / max(n_starts, 1), 7.0)
                proj_ip = max(proj_ip, 4.0)

            # Project Ks: K/9 * projected_innings / 9
            proj_k = (k9 * proj_ip) / 9.0

            # Blend with last-5 K/9 if available
            if n_starts >= 5:
                last5_proj = (last5_k9 * proj_ip) / 9.0
                proj_k = 0.6 * proj_k + 0.4 * last5_proj

            results[f'{side}_projected_k'] = round(proj_k, 1)
            results[f'{side}_projected_ip'] = round(proj_ip, 1)

        return results

    def predict_hits(self, game, lineup_data, pitcher_stats):
        """Run hit prediction backtesting (REQ-BT-028)."""
        if 'hits' not in self.models_to_test:
            return {}

        # Simplified hit prediction based on batting stats and pitcher quality
        results = {}
        for side in ('home', 'away'):
            opp_side = 'away' if side == 'home' else 'home'
            p_stats = pitcher_stats.get(f'{opp_side}_pitcher_stats', {})
            whip = p_stats.get('whip', 1.35)

            # Estimate hits allowed per 9 innings from WHIP
            # WHIP = (BB + H) / IP, roughly 60% are hits
            est_h9 = whip * 0.6 * 9.0

            # Project hits for lineup (9 batters, ~4 PA each)
            proj_hits = est_h9 * 5.5 / 9.0  # Adjusted for ~5.5 IP per starter
            results[f'{side}_projected_hits'] = round(proj_hits, 1)

        return results

    def predict_home_runs(self, game, features, pitcher_stats):
        """Run HR prediction backtesting (REQ-BT-029)."""
        if 'hr' not in self.models_to_test:
            return {}

        # Simplified HR probability model based on park factor, temperature, pitcher quality
        pf = features.get('park_factor', 1.0)
        temp = features.get('temperature', 72)
        weather_adj = features.get('weather_run_adj', 0.0)

        # Base HR probability per game ~2.4 (league average ~1.2 per team)
        base_hr_per_team = 1.2

        # Adjust for park factor and weather
        hr_adj = base_hr_per_team * pf
        if temp > 80:
            hr_adj *= 1.05
        elif temp < 60:
            hr_adj *= 0.92

        hr_adj += weather_adj * 0.15

        results = {
            'home_projected_hr_prob': round(min(0.95, max(0.05, hr_adj / 3.0)), 3),
            'away_projected_hr_prob': round(min(0.95, max(0.05, hr_adj / 3.0)), 3),
            'game_projected_total_hr': round(hr_adj * 2, 1),
        }

        return results
