"""Summarise NBA retrain runs: one row per model, then a table across models.

  retrain_summary.py row --model M --rc RC --log PATH [--out row.json]
  retrain_summary.py table [--expect a,b,c] ROW.json...
"""

from __future__ import annotations

import argparse
import json
import sys

PROMOTED = {"ok", "uploaded", "first_upload"}
BY_STATUS = {
    "rejected_by_champion": "rejected-by-champion",
    "rejected_by_line_gate": "rejected-by-line",
    "no_line_evidence": "no-line-evidence",
    "gate_failed": "gate-failed",
    "below_baseline": "gate-failed",
}
COLUMNS = [
    "Model",
    "Outcome",
    "Lined rows",
    "Model MAE",
    "Line MAE",
    "Side hit",
    "Champion MAE",
    "Gain / needed",
    "Note",
]


def _loads(text):
    try:
        v = json.loads(text)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def find_result(text: str):
    """Last top-level JSON object in a log: a one-line object or a `{` ... `}` block."""
    lines = text.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if line.startswith("{") and line.endswith("}"):
            if (v := _loads(line)) is not None:
                return v
        if lines[i].rstrip() == "}":  # closing line of an indented dump
            for j in range(i - 1, -1, -1):
                if lines[j].rstrip() == "{":
                    if (v := _loads("\n".join(lines[j : i + 1]))) is not None:
                        return v
                    break
    return None


def _num(d, *path):
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
    return d if isinstance(d, (int, float)) and not isinstance(d, bool) else None


def build_row(model: str, rc: int, text: str) -> dict:
    res = find_result(text)
    status = res.get("status") if res else None
    if rc != 0 or res is None:
        outcome = "error"
    elif status in ("dry", "dry_run"):
        outcome = "dry-run"  # trained or counted rows, nothing uploaded
    elif status in PROMOTED:
        outcome = "promoted"
    else:
        outcome = BY_STATUS.get(status, "error")
    row = {"model": model, "outcome": outcome, "rc": rc, "status": status}
    if res is None:
        row["note"] = "no result JSON in log"
        return row
    meta = res.get("metadata") if isinstance(res.get("metadata"), dict) else {}
    gate = next(
        (
            g
            for g in (
                meta.get("promote_gate"),
                res.get("promote_gate"),
                res.get("gate"),
                res.get("holdout_gate"),
                meta.get("holdout_gate"),
            )
            if isinstance(g, dict)
        ),
        {},
    )
    row["n_lined"] = _num(gate, "n_lined")
    row["model_mae"] = _num(gate, "lined", "model_mae")
    row["line_mae"] = _num(gate, "lined", "line_mae")
    row["side_hit_rate"] = _num(gate, "lined", "side_hit_rate")
    row["champion_mae"] = _num(gate, "champion", "champion_mae")
    row["gain"] = _num(gate, "champion", "gain")
    row["required_gain"] = _num(gate, "champion", "required_gain")
    if row["n_lined"] is None and (n := _num(meta, "n_market_rows")) is not None:
        row["n_lined"] = n  # spread: market rows are its lined rows
        row["model_mae"] = _num(meta, "model_mae_on_market_rows")
        row["line_mae"] = _num(meta, "market_test_mae")
    note = gate.get("reason") or res.get("reason") or res.get("error") or ""
    row["note"] = str(note)
    return row


def _fmt(v, nd=3):
    if v is None:
        return "n/a"
    return str(v) if isinstance(v, int) else f"{v:.{nd}f}"


def render(row: dict) -> str:
    try:
        gain = (
            "n/a"
            if row.get("gain") is None
            else f"{_fmt(row['gain'])} / {_fmt(row.get('required_gain'))}"
        )
        cells = [
            str(row["model"]),
            str(row["outcome"]),
            _fmt(row.get("n_lined")),
            _fmt(row.get("model_mae")),
            _fmt(row.get("line_mae")),
            _fmt(row.get("side_hit_rate")),
            _fmt(row.get("champion_mae")),
            gain,
            str(row.get("note") or "").replace("|", "/").replace("\n", " "),
        ]
    except Exception:
        cells = [str(row.get("model", "?") if isinstance(row, dict) else "?"), "error"]
        cells += ["n/a"] * (len(COLUMNS) - 2) + ["malformed row"]
    return "| " + " | ".join(cells) + " |"


def table(paths, expect=()) -> str:
    rows = {}
    for p in paths:
        try:
            row = json.load(open(p))
            rows[str(row["model"])] = row
        except Exception:
            name = str(p).rsplit("summary-", 1)[-1].removesuffix(".json")
            rows[name] = {"model": name, "outcome": "error", "note": "unreadable row"}
    for m in expect:
        rows.setdefault(m, {"model": m, "outcome": "error (no summary)"})
    out = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    out += [render(rows[m]) for m in sorted(rows)]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("row")
    r.add_argument("--model", required=True)
    r.add_argument("--rc", type=int, required=True)
    r.add_argument("--log", required=True)
    r.add_argument("--out")
    t = sub.add_parser("table")
    t.add_argument("--expect", default="")
    t.add_argument("rows", nargs="*")
    a = ap.parse_args(argv)
    if a.cmd == "row":
        try:
            text = open(a.log, errors="replace").read()
        except OSError:
            text = ""
        row = build_row(a.model, a.rc, text)
        if a.out:
            with open(a.out, "w") as f:
                json.dump(row, f)
        print(render(row))
    else:
        print(table(a.rows, [m for m in a.expect.split(",") if m]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
