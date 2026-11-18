import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import retrain_summary as rs  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
GATE = {
    "n_lined": 120,
    "lined": {"model_mae": 4.1, "line_mae": 3.9, "side_hit_rate": 0.49},
    "champion": {"champion_mae": 4.0, "gain": -0.1, "required_gain": 0.05},
    "reason": "model worse than line",
}


def row(rc, result, noise=True):
    text = "INFO training\nWARNING something\n" if noise else ""
    text += result if isinstance(result, str) else json.dumps(result, indent=2)
    return rs.build_row("points", rc, text + "\n")


def test_points_rejected_by_line_gate_with_numbers():
    r = row(0, {"status": "rejected_by_line_gate", "metadata": {"promote_gate": GATE}})
    assert r["outcome"] == "rejected-by-line"
    assert (r["n_lined"], r["model_mae"], r["line_mae"]) == (120, 4.1, 3.9)
    assert (r["champion_mae"], r["gain"], r["required_gain"]) == (4.0, -0.1, 0.05)
    assert r["note"] == "model worse than line"


def test_one_line_error_json_is_error():
    r = row(1, '{"status": "error", "error": "boom"}')
    assert r["outcome"] == "error" and r["note"] == "boom"


def test_nonzero_rc_beats_ok_json():
    assert row(1, {"status": "ok"})["outcome"] == "error"


def test_promoted_and_champion_and_no_line():
    assert row(0, {"status": "uploaded"})["outcome"] == "promoted"
    assert (
        row(0, {"status": "rejected_by_champion"})["outcome"] == "rejected-by-champion"
    )
    assert row(0, {"status": "no_line_evidence"})["outcome"] == "no-line-evidence"
    assert row(0, {"status": "dry_run"})["outcome"] == "dry-run"
    assert row(0, {"status": "weird"})["outcome"] == "error"


def test_spread_below_baseline_market_numbers():
    meta = {
        "n_market_rows": 80,
        "market_test_mae": 10.5,
        "model_mae_on_market_rows": 11.0,
    }
    r = row(0, {"status": "below_baseline", "metadata": meta})
    assert r["outcome"] == "gate-failed"
    assert (r["n_lined"], r["model_mae"], r["line_mae"]) == (80, 11.0, 10.5)


def test_residual_gate_failed_and_line_gate():
    r = row(0, {"status": "gate_failed", "holdout_gate": GATE})
    assert r["outcome"] == "gate-failed" and r["model_mae"] == 4.1
    r = row(0, {"status": "rejected_by_line_gate", "gate": GATE})
    assert r["outcome"] == "rejected-by-line" and r["line_mae"] == 3.9


def test_no_json_is_error():
    assert row(0, "just logs\nmore logs")["outcome"] == "error"


def test_table_missing_expected_and_malformed(tmp_path):
    good = tmp_path / "summary-points.json"
    good.write_text(json.dumps(row(0, {"status": "rejected_by_champion"})))
    bad = tmp_path / "summary-assists.json"
    bad.write_text("not json")
    weird = tmp_path / "summary-spread.json"
    weird.write_text(
        json.dumps({"model": "spread", "outcome": "gate-failed", "model_mae": "abc"})
    )
    out = rs.table([good, bad, weird], ["points", "rebounds"])
    lines = out.splitlines()
    assert lines[0].startswith("| Model | Outcome")
    assert any(l.startswith("| rebounds | error (no summary)") for l in lines)
    assert any(l.startswith("| assists | error") for l in lines)
    assert any(l.startswith("| points | rejected-by-champion") for l in lines)
    assert any(l.startswith("| spread |") for l in lines)  # did not crash


def run_step(tmp_path, code):
    env = {**os.environ, "GITHUB_STEP_SUMMARY": str(tmp_path / "sum.md")}
    p = subprocess.run(
        [
            "bash",
            "-e",
            str(BACKEND / "scripts/retrain_step.sh"),
            "points",
            sys.executable,
            "-c",
            code,
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    return p, (tmp_path / "sum.md").read_text()


def test_step_gate_outcome_is_green(tmp_path):
    code = 'import sys,json; print(json.dumps({"status": "rejected_by_champion"})); sys.exit(0)'
    p, summary = run_step(tmp_path, code)
    assert p.returncode == 0
    assert "::notice::points rejected-by-champion (live model kept)" in p.stdout
    assert "rejected-by-champion" in summary


def test_step_crash_is_red(tmp_path):
    code = 'import sys,json; print(json.dumps({"status": "error"})); sys.exit(1)'
    p, summary = run_step(tmp_path, code)
    assert p.returncode == 1
    assert "| points | error" in summary
