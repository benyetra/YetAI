"""League-specific ML training configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class LeagueMLConfig:
    """Parameters for shared prop-model training (one row per league).

    ``feature_builder_path`` documents the import path for operators; runtime
    uses ``feature_builder`` (the resolved callable).
    """

    table_prefix: str
    s3_prefix: str
    feature_builder_path: str
    feature_builder: Callable[..., Optional[dict[str, Any]]]
    recent_games_model: type
    mae_gate: dict[str, float]
    supported_stats: tuple[str, ...]
