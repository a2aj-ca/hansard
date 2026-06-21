#!/usr/bin/env bash
#
# Minimal cron entry point for the weekly Hansard update.
#
# All real work happens in Python (pipeline.export.run_weekly). This wrapper just
# provides the things cron does NOT give you: the working directory, the venv
# interpreter, a single-run lock, and a timestamped log. Secrets (HF_TOKEN,
# GIT_SSH_COMMAND, ...) are read from .env by the Python code itself.
#
# Install: see docs/publishing.md. Any extra args are passed through to the
# Python entry point, e.g. `weekly_update.sh --no-publish`.

set -euo pipefail

REPO_DIR="/home/sr/a2aj-hansard"
VENV_PY="$REPO_DIR/.venv/bin/python"
LOG_DIR="$REPO_DIR/LOGS"

cd "$REPO_DIR"
mkdir -p "$LOG_DIR"

# Single-run lock: if last week's run is somehow still going, exit quietly.
# fd 9 stays open for the lifetime of this script (and the python child).
exec 9>"$LOG_DIR/.weekly.lock"
if ! flock -n 9; then
    echo "weekly_update: another run is in progress, exiting."
    exit 0
fi

TS="$(date +%Y%m%d-%H%M%S)"
"$VENV_PY" -m pipeline.export.run_weekly "$@" >> "$LOG_DIR/weekly_${TS}.log" 2>&1
