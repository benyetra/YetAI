"""
Feature mapping for NFL kicker FG ML ensemble (ported from YetiBets).
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd


class MLFeatureMapper:
    def __init__(self) -> None:
        self.feature_order = [
            "kick_distance",
            "distance_squared",
            "distance_cubed",
            "score_differential",
            "qtr",
            "down",
            "ydstogo",
            "yardline_100",
            "game_seconds_remaining",
            "day_of_week",
            "month",
            "is_playoff",
            "late_in_game",
            "overtime",
            "close_game",
            "trailing",
            "leading",
            "is_clutch",
            "is_game_winning",
            "temp_filled",
            "wind_filled",
            "cold_weather",
            "hot_weather",
            "windy",
            "very_windy",
            "is_dome",
            "outdoor",
            "turf_surface",
            "kicker_experience",
            "rookie_kicker",
            "veteran_kicker",
            "kicker_distance_pct",
            "kicker_recent_success",
            "under_30_pct",
            "thirty_39_pct",
            "forty_49_pct",
            "fifty_59_pct",
            "sixty_plus_pct",
            "cold_weather_pct",
            "windy_pct",
            "dome_pct",
            "distance_x_wind",
            "distance_x_temp",
            "pressure_x_distance",
            "dist_30_39",
            "dist_40_49",
            "dist_50_59",
            "dist_60+",
            "dist_lt_30",
        ]
        self.feature_mapping = {
            f: f.replace("-", "_")
            .replace("<", "lt_")
            .replace(">", "gt_")
            .replace(" ", "_")
            for f in self.feature_order
        }

    def prepare_prediction_features(
        self,
        kicker_data: dict,
        team_data: dict,
        weather_data: dict | None = None,
        game_context: dict | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        game_context = game_context or {}
        features: dict = {
            "kick_distance": game_context.get("kick_distance", 40.0),
            "score_differential": game_context.get("score_differential", 0.0),
            "qtr": game_context.get("qtr", 2.0),
            "down": game_context.get("down", 4.0),
            "ydstogo": game_context.get("ydstogo", 5.0),
            "yardline_100": game_context.get("yardline_100", 22.0),
            "game_seconds_remaining": game_context.get(
                "game_seconds_remaining", 1800.0
            ),
        }
        features["distance_squared"] = features["kick_distance"] ** 2
        features["distance_cubed"] = features["kick_distance"] ** 3

        now = datetime.now()
        features["day_of_week"] = now.weekday()
        features["month"] = now.month
        features["is_playoff"] = game_context.get("is_playoff", 0)

        features.update(
            {
                "late_in_game": int(
                    features["qtr"] >= 4 and features["game_seconds_remaining"] <= 300
                ),
                "overtime": int(features["qtr"] > 4),
                "close_game": int(abs(features["score_differential"]) <= 7),
                "trailing": int(features["score_differential"] < 0),
                "leading": int(features["score_differential"] > 0),
                "is_clutch": int(features["late_in_game"] and features["close_game"]),
                "is_game_winning": int(
                    features["late_in_game"]
                    and features["score_differential"] <= 3
                    and features["score_differential"] >= -3
                ),
            }
        )

        temp = (weather_data or {}).get("temperature", 70)
        wind = (weather_data or {}).get("wind_speed", 5)
        features.update(
            {
                "temp_filled": temp,
                "wind_filled": wind,
                "cold_weather": int(temp < 40),
                "hot_weather": int(temp > 85),
                "windy": int(wind > 10),
                "very_windy": int(wind > 15),
            }
        )

        venue = (team_data or {}).get("venue_type", "outdoor")
        surface = (team_data or {}).get("surface_type", "grass")
        features["is_dome"] = int(venue == "dome")
        features["outdoor"] = int(venue != "dome")
        features["turf_surface"] = int("turf" in str(surface).lower())

        fg_pct = (kicker_data or {}).get("career_fg_percentage", 85) / 100.0
        attempts = (kicker_data or {}).get("total_attempts", 50)
        features["kicker_experience"] = attempts
        features["rookie_kicker"] = int(attempts < 20)
        features["veteran_kicker"] = int(attempts > 100)
        features["kicker_distance_pct"] = fg_pct
        features["kicker_recent_success"] = (kicker_data or {}).get(
            "recent_form", fg_pct
        )
        for band in (
            "under_30_pct",
            "thirty_39_pct",
            "forty_49_pct",
            "fifty_59_pct",
            "sixty_plus_pct",
        ):
            features[band] = fg_pct * 0.95
        features["cold_weather_pct"] = fg_pct * 0.90
        features["windy_pct"] = fg_pct * 0.85
        features["dome_pct"] = fg_pct * 1.05

        features["distance_x_wind"] = (
            features["kick_distance"] * features["wind_filled"]
        )
        features["distance_x_temp"] = (
            features["kick_distance"] * features["temp_filled"]
        )
        features["pressure_x_distance"] = (
            features["kick_distance"] * features["is_clutch"]
        )

        dist = features["kick_distance"]
        features["dist_30_39"] = int(30 <= dist < 40)
        features["dist_40_49"] = int(40 <= dist < 50)
        features["dist_50_59"] = int(50 <= dist < 60)
        features["dist_60+"] = int(dist >= 60)
        features["dist_lt_30"] = int(dist < 30)

        df_original = pd.DataFrame([features])[self.feature_order]
        df_mapped = df_original.rename(columns=self.feature_mapping)
        return df_original, df_mapped


_mapper: MLFeatureMapper | None = None


def get_feature_mapper() -> MLFeatureMapper:
    global _mapper
    if _mapper is None:
        _mapper = MLFeatureMapper()
    return _mapper
