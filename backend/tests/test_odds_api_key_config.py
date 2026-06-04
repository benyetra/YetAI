"""Odds API key must prefer ODDS_API_KEY env over ODDS_API placeholder aliases."""

import os
from unittest.mock import patch

from app.core.config import Settings, _clean_odds_api_key, _resolve_odds_api_key


def test_clean_rejects_template_placeholders():
    assert _clean_odds_api_key("your-odds-api-key") is None
    assert _clean_odds_api_key("your_odds_api_key_here") is None
    assert _clean_odds_api_key("  abc12345  ") == "abc12345"


def test_resolve_prefers_odds_api_key_env_over_odds_api_alias():
    with patch.dict(
        os.environ,
        {
            "ODDS_API_KEY": "real-key-from-railway",
            "ODDS_API": "your-odds-api-key",
        },
        clear=False,
    ):
        key, source = _resolve_odds_api_key("your-odds-api-key")
    assert key == "real-key-from-railway"
    assert source == "ODDS_API_KEY"


def test_settings_coalesce_uses_odds_api_key_when_alias_is_placeholder():
    with patch.dict(
        os.environ,
        {
            "ODDS_API_KEY": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "ODDS_API": "your-odds-api-key",
        },
        clear=False,
    ):
        s = Settings()
    assert s.ODDS_API_KEY == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_odds_api_env_diagnostics_without_key():
    with patch.dict(os.environ, {}, clear=True):
        s = Settings()
    diag = s.odds_api_env_diagnostics()
    assert diag["resolved_key_configured"] is False
    assert diag["resolved_key_length"] == 0
    assert diag["resolved_key_preview"] == "too_short"
