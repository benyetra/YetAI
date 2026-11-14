"""CLI: ``python -m app.services.etl.nba.residual train --stat rebounds --start ...``"""

from __future__ import annotations

import argparse
import json
import sys

from app.services.etl.nba.residual import train as trainer


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="residual")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train", help="train, gate and (with --upload) upload")
    t.add_argument("--stat", required=True, choices=["rebounds", "assists"])
    t.add_argument("--start", required=True)
    t.add_argument("--end", required=True)
    t.add_argument("--upload", action="store_true")
    t.add_argument("--kind", default=None)
    t.add_argument("--save-local", default=None, help="dir for pickle + metadata")
    a = p.parse_args(argv)
    try:
        result = trainer.train(
            a.stat,
            a.start,
            a.end,
            upload=a.upload,
            kind=a.kind,
            save_local=a.save_local,
        )
    except Exception as exc:  # noqa: BLE001 - one JSON error line, exit 1
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
