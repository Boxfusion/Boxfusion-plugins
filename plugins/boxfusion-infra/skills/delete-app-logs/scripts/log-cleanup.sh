#!/usr/bin/env bash
# Runs ON a Linux App Service (Kudu container), detached via nohup/setsid by kudu-logs.sh.
# Counts or deletes log files older than N days under a folder (recursively), writing progress to $WORK.
#
# Usage: log-cleanup.sh <count|delete> <dir> <older-than-days> [name-pattern] [work-dir]
#   older-than-days must be >= 1 so a log that is still being written is never touched.

set -u

MODE="${1:?mode required: count|delete}"
DIR="${2:?dir required}"
DAYS="${3:?older-than-days required (>= 1)}"
PATTERN="${4:-*}"
WORK="${5:-/home/LogFiles/log-cleanup}"

mkdir -p "$WORK"
STATUS="$WORK/status"
PROGRESS="$WORK/progress"
PIDFILE="$WORK/pid"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "already running (pid $(cat "$PIDFILE"))" >&2
  exit 1
fi
echo $$ > "$PIDFILE"

fail() { echo "state=error message=$1" > "$STATUS"; rm -f "$PIDFILE"; exit 2; }
[ "$MODE" = "count" ] || [ "$MODE" = "delete" ] || fail "unknown-mode-$MODE"
[ -d "$DIR" ] || fail "dir-not-found"
[ "$DAYS" -ge 1 ] 2>/dev/null || fail "days-must-be-at-least-1"

ACTION=()
[ "$MODE" = "delete" ] && ACTION=(-delete)

{
  echo "state=running"
  echo "mode=$MODE"
  echo "dir=$DIR"
  echo "pattern=$PATTERN"
  echo "older_than_days=$DAYS"
  echo "started_utc=$(date -u +%FT%TZ)"
} > "$STATUS"
echo "0 0" > "$PROGRESS"

# -printf runs before -delete, so each matched file's size is recorded as it goes.
# awk rewrites "files MB" every 500 matches so a poll shows live numbers.
find "$DIR" -type f -name "$PATTERN" -mtime "+$DAYS" -printf '%s\n' "${ACTION[@]}" 2>>"$WORK/errors.log" \
  | awk -v f="$PROGRESS" '{ n++; b += $1 } n % 500 == 0 { printf "%d %d\n", n, b / 1048576 > f; close(f) }
                          END { printf "%d %d\n", n + 0, b / 1048576 > f; close(f) }'

read -r FILES MB < "$PROGRESS"
{
  echo "state=done"
  echo "mode=$MODE"
  echo "dir=$DIR"
  echo "pattern=$PATTERN"
  echo "older_than_days=$DAYS"
  echo "matched_files=$FILES"
  echo "matched_mb=$MB"
  echo "dir_mb_now=$(du -sm "$DIR" | cut -f1)"
  echo "finished_utc=$(date -u +%FT%TZ)"
} > "$STATUS"
rm -f "$PIDFILE"
