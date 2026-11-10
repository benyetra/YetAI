from app.services.etl.nfl.recv_yds_model import (
    DEFAULT_RECV_ANCHOR_ALPHA,
    expected_targets,
    model_receiving_yards,
    published_recv_yards,
    recv_anchor_alpha,
    soft_anchor_recv_yards,
)


def test_recv_anchor_alpha_defaults_to_quarter(monkeypatch):
    monkeypatch.delenv("NFL_RECV_ANCHOR_ALPHA", raising=False)
    assert DEFAULT_RECV_ANCHOR_ALPHA == 0.25
    assert recv_anchor_alpha() == 0.25


def test_recv_anchor_alpha_clamps_and_handles_nan(monkeypatch):
    monkeypatch.setenv("NFL_RECV_ANCHOR_ALPHA", "1.5")
    assert recv_anchor_alpha() == 1.0
    monkeypatch.setenv("NFL_RECV_ANCHOR_ALPHA", "-0.2")
    assert recv_anchor_alpha() == 0.0
    monkeypatch.setenv("NFL_RECV_ANCHOR_ALPHA", "nan")
    assert recv_anchor_alpha() == 0.25
    monkeypatch.setenv("NFL_RECV_ANCHOR_ALPHA", "nope")
    assert recv_anchor_alpha() == 0.25


def test_soft_anchor_recv_yards_spec_example():
    # Spec: model=100, line=80, α=0.25 → 85.0
    assert soft_anchor_recv_yards(model_yards=100.0, ou_line=80.0, alpha=0.25) == 85.0
    assert soft_anchor_recv_yards(model_yards=100.0, ou_line=80.0, alpha=1.0) == 100.0
    assert soft_anchor_recv_yards(model_yards=100.0, ou_line=80.0, alpha=0.0) == 80.0


def test_expected_targets_from_share_times_attempts():
    assert expected_targets(target_share=0.25, team_pass_attempts=36.0) == 9.0


def test_expected_targets_never_invents_from_missing_usage():
    assert expected_targets(target_share=None, team_pass_attempts=36.0) is None
    assert expected_targets(target_share=0.25, team_pass_attempts=None) is None
    assert expected_targets(target_share=0.0, team_pass_attempts=36.0) is None


def test_model_receiving_yards_multiplicative():
    yards = model_receiving_yards(
        expected_targets=8.0,
        yards_per_target=8.0,
        depth_adj=1.05,
        pace_adj=0.95,
        matchup_adj=1.1,
    )
    assert abs(yards - (8.0 * 8.0 * 1.05 * 0.95 * 1.1)) < 1e-9


def test_model_receiving_yards_uses_yards_per_target_not_per_reception():
    # 8 targets, 5 catches, 60 yards: 12.0 yards per reception, 7.5 per target.
    # Targets x yards-per-reception would say 96 for a 60-yard day.
    assert model_receiving_yards(expected_targets=8.0, yards_per_target=7.5) == 60.0


def test_published_recv_yards_soft_anchors_when_line_and_model():
    yards, method = published_recv_yards(
        model_yards=100.0, ou_line=80.0, line_is_real=True, anchor_alpha=0.25
    )
    assert yards == 85.0
    assert method == "soft_anchor"
    assert yards != 80.0


def test_published_recv_yards_skips_without_model_or_line():
    yards, method = published_recv_yards(
        model_yards=None, ou_line=80.0, line_is_real=True
    )
    assert yards is None and method is None
    yards, method = published_recv_yards(
        model_yards=100.0, ou_line=None, line_is_real=False
    )
    assert yards is None and method is None
