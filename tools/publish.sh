#!/usr/bin/env bash
# publish — stage benchmark results for peachq.org/benchmark and push them to the website.
#
# Builds, with pysrc/publishData.py, the summary the native page reads (data.js) and
# the re-skinned drill-down dashboard (full/), then copies both to the server:
#   /data/benchmark/full/   (the drill-down; replaced as a whole)
#   /data/benchmark/data.js (the native page's source of truth; LAST)
# Safe by default: DRY-RUN unless GO=1. Only verified results go live: GO=1 needs
# --verdicts (verify.sh output) and refuses --unverified.
#
# A verified publish also appends the run's MPH to artifacts/publish/history.psv: commit it.
#
# Usage: tools/publish.sh --results DIR --size SIZE (--verdicts FILE | --unverified) [--local DIR] [--stage DIR] [--page-solutions LIST] [--history FILE]
#   --local DIR   copy into DIR (a local preview's .../data/benchmark) instead of the server; it
#                 writes at once, since nothing leaves the machine
#   --page-solutions LIST, --history FILE   passed to publishData.py
#   GO=1          upload to $PEACHQ_HOST:$PEACHQ_ROOT
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

GO="${GO:-0}"
REMOTE_HOST="${PEACHQ_HOST:-root@timestored.com}"
REMOTE_ROOT="${PEACHQ_ROOT:-/srv/rsync/peachq.org/public_html}"
PYTHON="${PYTHON:-python3}"
RESULTS=""; SIZE=""; VERDICTS=""; UNVERIFIED=0; LOCAL=""; STAGE="build/publish"; EXTRA=()

usage() { sed -n 's/^# Usage: //p' "$0" >&2; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --results) RESULTS="${2:?}"; shift 2;;
    --size) SIZE="${2:?}"; shift 2;;
    --verdicts) VERDICTS="${2:?}"; shift 2;;
    --unverified) UNVERIFIED=1; shift;;
    --local) LOCAL="${2:?}"; shift 2;;
    --stage) STAGE="${2:?}"; shift 2;;
    --page-solutions|--history) EXTRA+=("$1" "${2:?}"); shift 2;;
    *) usage;;
  esac
done
[ -n "$RESULTS" ] && [ -n "$SIZE" ] || usage
if [ "$GO" = 1 ] && [ -n "$LOCAL" ]; then
  echo "publish: GO=1 is for the server; --local writes without it" >&2; exit 2
fi
if [ "$GO" = 1 ] && { [ -z "$VERDICTS" ] || [ "$UNVERIFIED" = 1 ]; }; then
  echo "publish: refusing GO=1 without a verdicts file: only results verify.sh marked ok are published" >&2; exit 1
fi
if [ -n "$VERDICTS" ] && [ "$UNVERIFIED" = 1 ]; then
  echo "publish: --verdicts and --unverified are exclusive" >&2; exit 2
fi
[ -n "$VERDICTS" ] || [ "$UNVERIFIED" = 1 ] || {
  echo "publish: pass --verdicts FILE, or --unverified for a dry run or a local preview" >&2; exit 2; }

if [ -n "$LOCAL" ]; then mode="LOCAL -> $LOCAL"
elif [ "$GO" = 1 ]; then mode="LIVE -> $REMOTE_HOST:$REMOTE_ROOT/data/benchmark"
else mode="DRY-RUN (GO=1 to upload) -> $REMOTE_HOST:$REMOTE_ROOT/data/benchmark"; fi
echo "== publish $SIZE $([ "$UNVERIFIED" = 1 ] && echo UNVERIFIED || echo "verified by $VERDICTS"): $mode =="

gate=(--unverified); [ -n "$VERDICTS" ] && gate=(--verdicts "$VERDICTS")
"$PYTHON" pysrc/publishData.py "$RESULTS" "$STAGE" --size "$SIZE" "${gate[@]}" ${EXTRA[@]+"${EXTRA[@]}"}
echo "-- staged under $STAGE: data.js, full/ --"

if [ -n "$LOCAL" ]; then
  mkdir -p "$LOCAL/full"
  rsync -rh --delete "$STAGE/full/" "$LOCAL/full/"
  rsync -rh "$STAGE/data.js" "$LOCAL/"
  echo "== publish done: $LOCAL/data.js =="
  exit 0
fi

RS=(rsync -rvh); [ "$GO" = 1 ] || RS+=(--dry-run)
DEST="$REMOTE_ROOT/data/benchmark"
if [ "$GO" = 1 ]; then
  ssh "$REMOTE_HOST" "mkdir -p $DEST/full && chown www-data:www-data $REMOTE_ROOT/data $DEST $DEST/full" </dev/null
fi
echo "-- 1. drill-down -> data/benchmark/full/ --"
"${RS[@]}" --delete "$STAGE/full/" "$REMOTE_HOST:$DEST/full/" </dev/null
echo "-- 2. data.js -> data/benchmark/ (LAST) --"
"${RS[@]}" "$STAGE/data.js" "$REMOTE_HOST:$DEST/" </dev/null
echo "== publish done. $([ "$GO" = 1 ] && echo 'LIVE -> https://peachq.org/benchmark' || echo 'DRY-RUN; re-run with GO=1 to upload.')"
