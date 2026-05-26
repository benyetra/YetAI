from app.services.etl.mlb.profiles.constants import mlb_profiles_enabled


def test_mlb_profiles_enabled_default(monkeypatch):
    monkeypatch.delenv("MLB_PROFILES_ENABLED", raising=False)
    assert mlb_profiles_enabled() is False


def test_mlb_profiles_disabled(monkeypatch):
    monkeypatch.setenv("MLB_PROFILES_ENABLED", "0")
    assert mlb_profiles_enabled() is False
