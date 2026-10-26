#!/usr/bin/env bash
# Runs ON the App Service (Kudu container), detached via nohup/setsid by kudu-elmah.sh.
# Counts or deletes Elmah XML error files, writing progress to $WORK so callers can poll.
#
# Usage: elmah-xml-cleanup.sh <histogram|count|delete> <elmah-dir> <older-than-days> [work-dir]
#   older-than-days = 0 matches every file regardless of age (ignored by histogram).

set -u

MODE="${1:?mode required: count|delete}"
DIR="${2:?elmah dir required}"
DAYS="${3:?older-than-days required (0 = all)}"
WORK="${4:-/home/LogFiles/elmah-cleanup}"

mkdir -p "$WORK"
STATUS="$WORK/status"
PROGRESS="$WORK/progress"
PIDFILE="$WORK/pid"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "already running (pid $(cat "$PIDFILE"))" >&2
  exit 1
fi
echo $$ > "$PIDFILE"

if [ "$MODE" = "histogram" ]; then
  echo "state=running mode=histogram started_utc=$(date -u +%FT%TZ)" > "$STATUS"
  find "$DIR" -maxdepth 1 -type f -iname '*.xml' -printf '%TY-%Tm\n' 2>>"$WORK/errors.log" \
    | sort | uniq -c > "$WORK/histogram.tmp"
  { echo "state=done"; echo "mode=histogram"; echo "files_by_month:"; cat "$WORK/histogram.tmp"; echo "finished_utc=$(date -u +%FT%TZ)"; } > "$STATUS"
  rm -f "$WORK/histogram.tmp" "$PIDFILE"
  exit 0
fi

if [ "$MODE" != "count" ] && [ "$MODE" != "delete" ]; then
  echo "state=error message=unknown-mode-$MODE" > "$STATUS"
  rm -f "$PIDFILE"
  exit 2
fi

if [ ! -d "$DIR" ]; then
  echo "state=error message=dir-not-found" > "$STATUS"
  rm -f "$PIDFILE"
  exit 2
fi

AGE=()
[ "$DAYS" -gt 0 ] && AGE=(-mtime "+$DAYS")
ACTION=()
[ "$MODE" = "delete" ] && ACTION=(-delete)

{
  echo "state=running"
  echo "mode=$MODE"
  echo "dir=$DIR"
  echo "older_than_days=$DAYS"
  echo "started_utc=$(date -u +%FT%TZ)"
} > "$STATUS"
echo 0 > "$PROGRESS"

# -maxdepth 1 + streaming find: never globs or sorts, so it copes with millions of files.
# awk rewrites the progress file every 5000 matches so a poll shows live numbers.
find "$DIR" -maxdepth 1 -type f -iname '*.xml' "${AGE[@]}" "${ACTION[@]}" -print 2>>"$WORK/errors.log" \
  | awk -v f="$PROGRESS" 'NR % 5000 == 0 { print NR > f; close(f) } END { print NR + 0 > f; close(f) }'

REMAINING=$(find "$DIR" -maxdepth 1 -type f -iname '*.xml' | wc -l)
{
  echo "state=done"
  echo "mode=$MODE"
  echo "dir=$DIR"
  echo "older_than_days=$DAYS"
  echo "matched=$(cat "$PROGRESS")"
  echo "xml_files_remaining=$REMAINING"
  echo "finished_utc=$(date -u +%FT%TZ)"
} > "$STATUS"
rm -f "$PIDFILE"
