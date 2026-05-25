"""Legacy demo YetAI bets seeded when the table was empty (removed from app init)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.database_models import YetAIBet

# Exact ``title`` values from the old _create_sample_bets_if_needed() seeder.
DEMO_MATCHUP_TITLES = frozenset(
    {
        "Chiefs vs Bills",
        "Lakers vs Warriors",
        "Dodgers vs Padres",
        "Rangers vs Bruins",
    }
)

# Fallback when title was edited but description still matches the seed copy.
DEMO_REASONING_MARKERS = (
    "Padres bullpen fatigued from extra innings yesterday",
    "Rangers excellent in back-to-back games",
    "Chiefs have excellent road record vs top defenses",
    "Lakers missing defensive anchor, Warriors at home average 118 PPG",
)


def _bet_text(value: object) -> str:
    """Coerce optional bet text fields; ignore non-str values (e.g. test mocks)."""
    return value.strip() if isinstance(value, str) else ""


def is_demo_yetai_bet(bet: "YetAIBet") -> bool:
    title = _bet_text(bet.title)
    if title in DEMO_MATCHUP_TITLES:
        return True
    text = " ".join(
        filter(
            None,
            [
                _bet_text(bet.description),
                _bet_text(bet.reasoning),
                _bet_text(bet.selection),
            ],
        )
    )
    if any(marker in text for marker in DEMO_REASONING_MARKERS):
        return True
    return False
