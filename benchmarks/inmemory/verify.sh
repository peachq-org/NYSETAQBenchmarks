#!/usr/bin/env bash
# Checks a run's -q outputs against the consensus golden (docs/verification.md); never part of a timed run.
set -euo pipefail
exec ${PYRUN:-uv run} "$(dirname "${BASH_SOURCE[0]}")/../../pysrc/verify/main.py" "$@"
