# --- scripts/mlb/odds_utils.py ---
def american_to_break_even_prob(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return (-odds) / ((-odds) + 100)

def normalize_two_sided(p_over_raw: float, p_under_raw: float):
    s = (p_over_raw or 0.0) + (p_under_raw or 0.0)
    if s <= 0: return 0.5, 0.5
    return p_over_raw / s, p_under_raw / s

def profit_per_unit(odds: int) -> float:
    return (odds / 100.0) if odds > 0 else (100.0 / abs(odds))

def expected_value(prob: float, odds: int) -> float:
    return prob * profit_per_unit(odds) - (1 - prob)
