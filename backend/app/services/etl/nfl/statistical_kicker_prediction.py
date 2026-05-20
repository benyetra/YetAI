"""
Statistical-Based Enhanced Kicking Predictions
Uses historical nflverse data with statistical analysis instead of ML models
More reliable and easier to integrate than complex ML pipeline
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


class StatisticalKickerPredictor:
    def __init__(self):
        self.historical_data = None
        self.weather_stats = None
        self.kicker_stats = None
        self.load_historical_data()

    def load_historical_data(self):
        """Load pre-processed historical data"""
        try:
            data_dir = "/Users/byetz/Development/YetAI/YetAI/backend/data/nfl"

            # Load field goal data
            fg_path = os.path.join(data_dir, 'field_goal_data.csv')
            if os.path.exists(fg_path):
                self.historical_data = pd.read_csv(fg_path)
                print(f"Loaded {len(self.historical_data)} historical field goal attempts")

            # Load weather stats
            weather_path = os.path.join(data_dir, 'weather_stats.csv')
            if os.path.exists(weather_path):
                self.weather_stats = pd.read_csv(weather_path)
                print(f"Loaded {len(self.weather_stats)} weather impact records")

            # Load kicker stats
            kicker_path = os.path.join(data_dir, 'kicker_stats.csv')
            if os.path.exists(kicker_path):
                self.kicker_stats = pd.read_csv(kicker_path)
                print(f"Loaded {len(self.kicker_stats)} kicker performance records")

        except Exception as e:
            print(f"Error loading historical data: {e}")
            print("Using default statistical baselines")

    def get_distance_success_rate(self, distance):
        """Get success rate for specific distance based on historical data"""
        if self.historical_data is None:
            # Default rates based on NFL averages
            if distance < 30:
                return 0.95
            elif distance < 40:
                return 0.90
            elif distance < 50:
                return 0.75
            elif distance < 60:
                return 0.55
            else:
                return 0.30

        # Use actual historical data
        distance_range = 5  # +/- 5 yards
        similar_kicks = self.historical_data[
            (self.historical_data['kick_distance'] >= distance - distance_range) &
            (self.historical_data['kick_distance'] <= distance + distance_range)
        ]

        if len(similar_kicks) > 10:  # Minimum sample size
            return similar_kicks['is_made'].mean()
        else:
            # Fall back to distance band
            if distance < 30:
                band_data = self.historical_data[self.historical_data['distance_band'] == '<30']
            elif distance < 40:
                band_data = self.historical_data[self.historical_data['distance_band'] == '30-39']
            elif distance < 50:
                band_data = self.historical_data[self.historical_data['distance_band'] == '40-49']
            elif distance < 60:
                band_data = self.historical_data[self.historical_data['distance_band'] == '50-59']
            else:
                band_data = self.historical_data[self.historical_data['distance_band'] == '60+']

            return band_data['is_made'].mean() if len(band_data) > 0 else 0.5

    def get_weather_adjustment(self, temperature=None, wind_speed=None, dome=False):
        """Calculate weather impact multiplier"""
        if dome:
            return 1.05  # Slight boost for dome conditions

        multiplier = 1.0

        # Temperature impact
        if temperature is not None:
            if temperature < 32:
                multiplier *= 0.92  # Cold weather penalty
            elif temperature < 45:
                multiplier *= 0.96  # Mild cold penalty
            elif temperature > 90:
                multiplier *= 0.98  # Extreme heat penalty

        # Wind impact
        if wind_speed is not None:
            if wind_speed > 20:
                multiplier *= 0.85  # High wind significant penalty
            elif wind_speed > 15:
                multiplier *= 0.90  # Strong wind penalty
            elif wind_speed > 10:
                multiplier *= 0.95  # Moderate wind penalty

        return multiplier

    def get_kicker_adjustment(self, kicker_data):
        """Calculate kicker-specific performance adjustment"""
        # Default to more realistic league average
        base_rate = 0.82

        # Use kicker's career percentage if available
        if 'career_fg_percentage' in kicker_data:
            base_rate = kicker_data['career_fg_percentage'] / 100
        elif 'fg_percentage' in kicker_data:
            base_rate = kicker_data['fg_percentage'] / 100

        # Adjust for experience (reduced bonuses/penalties)
        experience_bonus = 0
        if 'total_attempts' in kicker_data:
            attempts = kicker_data['total_attempts']
            if attempts > 100:
                experience_bonus = 0.01  # Veteran bonus (reduced from 0.02)
            elif attempts < 20:
                experience_bonus = -0.02  # Rookie penalty (reduced from -0.03)

        # Recent form adjustment (reduced bonuses/penalties)
        recent_bonus = 0
        if 'recent_form' in kicker_data:
            recent_form = kicker_data['recent_form']
            if recent_form > 0.90:
                recent_bonus = 0.015  # Hot streak (reduced from 0.03)
            elif recent_form < 0.70:
                recent_bonus = -0.025  # Cold streak (reduced from -0.05)

        # Cap the adjustment to realistic bounds
        final_rate = base_rate + experience_bonus + recent_bonus
        return max(0.70, min(0.95, final_rate))  # Keep between 70%-95%

    def calculate_situational_multiplier(self, game_context):
        """Calculate situational pressure multiplier"""
        multiplier = 1.0

        # Pressure situations
        if game_context.get('is_clutch', False):
            multiplier *= 0.92  # Clutch situation penalty

        if game_context.get('is_playoff', False):
            multiplier *= 0.94  # Playoff pressure penalty

        # Game state
        score_diff = game_context.get('score_differential', 0)
        if abs(score_diff) <= 3:  # Close game
            multiplier *= 0.96

        # Time remaining
        seconds_remaining = game_context.get('game_seconds_remaining', 1800)
        if seconds_remaining < 120:  # Last 2 minutes
            multiplier *= 0.93

        return multiplier

    def estimate_field_goal_attempts(self, team_data, weather_data=None):
        """Estimate number of field goal attempts per game"""
        base_attempts = 1.85  # More realistic NFL average

        # Team offensive efficiency (reduced multipliers)
        red_zone_eff = team_data.get('team_red_zone_efficiency', 60)
        if red_zone_eff > 70:
            base_attempts *= 0.85  # Efficient teams score more TDs (less aggressive)
        elif red_zone_eff < 50:
            base_attempts *= 1.15  # Inefficient teams attempt more FGs (less aggressive)

        # Third down conversion rate (reduced multipliers)
        third_down_rate = team_data.get('third_down_conversion_rate', 40)
        if third_down_rate > 45:
            base_attempts *= 0.95  # Good conversion = fewer FG attempts (less aggressive)
        elif third_down_rate < 35:
            base_attempts *= 1.08  # Poor conversion = more FG attempts (less aggressive)

        # Weather impact on attempts (reduced impact)
        weather_factor = 1.0
        if weather_data:
            temp = weather_data.get('temperature')
            wind = weather_data.get('wind_speed')

            if temp and temp < 35:  # Only very cold weather
                weather_factor *= 1.05  # More conservative (reduced from 1.1)
            if wind and wind > 18:  # Only high wind
                weather_factor *= 0.95  # Avoid long attempts (reduced from 0.9)

        # Cap the final result to realistic range
        final_attempts = base_attempts * weather_factor
        return min(2.5, max(1.2, final_attempts))  # Keep between 1.2-2.5 attempts

    def predict_kicker_performance(self, kicker_data, team_data, weather_data=None, game_context=None):
        """
        Main prediction function using statistical analysis

        Returns comprehensive kicking predictions
        """
        # Estimate attempts
        predicted_attempts = self.estimate_field_goal_attempts(team_data, weather_data)

        # Calculate success rates for different distances
        distance_predictions = {}
        total_success_probability = 0

        # Distance distribution based on historical data
        distance_weights = {
            25: 0.15,   # <30 yards
            35: 0.35,   # 30-39 yards
            45: 0.30,   # 40-49 yards
            55: 0.15,   # 50-59 yards
            65: 0.05    # 60+ yards
        }

        for distance, weight in distance_weights.items():
            # Base success rate for distance
            base_rate = self.get_distance_success_rate(distance)

            # Apply adjustments
            weather_adj = self.get_weather_adjustment(
                weather_data.get('temperature') if weather_data else None,
                weather_data.get('wind_speed') if weather_data else None,
                team_data.get('venue_type') == 'dome'
            )

            kicker_adj = self.get_kicker_adjustment(kicker_data)

            situational_adj = self.calculate_situational_multiplier(game_context or {})

            # Calculate final probability
            final_rate = min(0.99, base_rate * weather_adj * situational_adj)

            # Use kicker adjustment as a blend factor
            final_rate = (final_rate * 0.7) + (kicker_adj * 0.3)

            distance_predictions[f'{distance}yd'] = round(final_rate, 3)
            total_success_probability += final_rate * weight

        # Calculate overall metrics
        predicted_made = predicted_attempts * total_success_probability

        return {
            'predicted_attempts': round(predicted_attempts, 1),
            'predicted_made': round(predicted_made, 1),
            'overall_success_rate': round(total_success_probability, 3),
            'distance_specific': distance_predictions,
            'confidence': 0.85,  # High confidence in statistical approach
            'model_type': 'statistical_analysis',
            'data_source': 'nflverse_historical'
        }


# Global predictor instance
_predictor = None

def get_statistical_predictor():
    """Get or create the global statistical predictor instance"""
    global _predictor
    if _predictor is None:
        _predictor = StatisticalKickerPredictor()
    return _predictor


def calculate_enhanced_statistical_score(kicker_data, team_data, weather_data=None, game_context=None):
    """
    Enhanced statistical prediction function

    Args:
        kicker_data (dict): Kicker performance statistics
        team_data (dict): Team offensive statistics
        weather_data (dict): Weather conditions (optional)
        game_context (dict): Game situation context (optional)

    Returns:
        float: Projected field goals made
    """
    predictor = get_statistical_predictor()
    result = predictor.predict_kicker_performance(kicker_data, team_data, weather_data, game_context)
    return result['predicted_made']


# Backward compatibility with existing system
def calculate_combined_score(stats, upcoming_surface=None, upcoming_location=None):
    """
    Drop-in replacement for old calculate_combined_score function
    Now uses statistical analysis of historical nflverse data
    """
    # Convert old format to new format (more realistic defaults)
    kicker_data = {
        'career_fg_percentage': 82,  # More realistic NFL average
        'total_attempts': 35,        # Average experience level
        'recent_form': 0.80          # Average recent performance
    }

    team_data = {
        'team_red_zone_efficiency': stats.get('team_red_zone_efficiency', 60),
        'third_down_conversion_rate': stats.get('third_down_conversion_rate', 40),
        'venue_type': 'dome' if upcoming_location == 'indoors' else 'outdoor'
    }

    weather_data = None
    if 'wind_speed' in stats or 'temperature' in stats:
        weather_data = {
            'wind_speed': stats.get('wind_speed', 5),
            'temperature': stats.get('temperature', 70)
        }

    return calculate_enhanced_statistical_score(kicker_data, team_data, weather_data)


if __name__ == '__main__':
    # Test the statistical predictor
    predictor = StatisticalKickerPredictor()

    test_kicker_data = {
        'career_fg_percentage': 87.5,
        'total_attempts': 75,
        'recent_form': 0.90
    }

    test_team_data = {
        'team_red_zone_efficiency': 65,
        'third_down_conversion_rate': 42,
        'venue_type': 'outdoor'
    }

    test_weather = {
        'temperature': 45,
        'wind_speed': 12
    }

    test_context = {
        'is_clutch': False,
        'score_differential': -3,
        'game_seconds_remaining': 900
    }

    result = predictor.predict_kicker_performance(
        test_kicker_data, test_team_data, test_weather, test_context
    )

    print("Statistical Kicking Prediction Test:")
    print(f"Predicted attempts: {result['predicted_attempts']}")
    print(f"Predicted made: {result['predicted_made']}")
    print(f"Success rate: {result['overall_success_rate']}")
    print(f"Distance breakdown: {result['distance_specific']}")
    print(f"Confidence: {result['confidence']}")