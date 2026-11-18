#!/usr/bin/env bash
# Run one retrain job without letting the trainer's exit code hide the summary.
# Usage: retrain_step.sh MODEL TRAINER_COMMAND...   (run from backend/)
# Gate outcomes (trainer exit 0) stay green; crashes (exit 1) stay red.
set +e -uo pipefail  # a failing trainer must not skip the summary
model="$1"; shift
here="$(cd "$(dirname "$0")" && pwd)"
log="${RETRAIN_LOG:-train.log}"
"$@" >"$log" 2>&1
rc=$?
cat "$log"
summary="${GITHUB_STEP_SUMMARY:-/dev/null}"
python3 "$here/retrain_summary.py" row --model "$model" --rc "$rc" --log "$log" \
  --out "summary-$model.json" >/dev/null
python3 "$here/retrain_summary.py" table "summary-$model.json" >>"$summary"
if [ "$rc" -eq 0 ]; then
  outcome="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["outcome"])' "summary-$model.json")"
  if [ "$outcome" = "error" ] || [ -z "$outcome" ]; then
    # exit 0 but no readable result (or an unknown status): not a success
    echo "::error::$model exited 0 without a usable result"
    exit 1
  fi
  if [ "$outcome" != "promoted" ]; then
    echo "::notice::$model $outcome (live model kept)"
  fi
fi
exit "$rc"
