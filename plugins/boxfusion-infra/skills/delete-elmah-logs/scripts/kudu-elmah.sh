#!/usr/bin/env bash
# Local driver for Elmah XML cleanup on a Linux Azure App Service through the Kudu (SCM) API.
# Requires: az (logged in), curl. Works in Git Bash, Linux and macOS.
#
# Usage: kudu-elmah.sh <app> <resource-group> <subscription> <action> [args]
#   probe                          locate Elmah folders and show disk usage
#   start <histogram|count|delete> <dir> <days>  upload elmah-xml-cleanup.sh and run it detached
#   status                         print the job's status/progress files
#   stop                           kill a running job
#   exec "<shell command>"         run a short command (Kudu kills requests after ~230s)

set -euo pipefail

APP="${1:?app name required}"
RG="${2:?resource group required}"
SUB="${3:?subscription required}"
ACTION="${4:?action required}"
shift 4

WORK=/home/LogFiles/elmah-cleanup
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HOST=$(az webapp show --subscription "$SUB" -g "$RG" -n "$APP" \
  --query "hostNameSslStates[?hostType=='Repository'].name | [0]" -o tsv 2>/dev/null)
[ -n "$HOST" ] || { echo "Could not resolve SCM host for $APP" >&2; exit 1; }
KUDU="https://$HOST"
TOKEN=$(az account get-access-token --subscription "$SUB" --resource https://management.azure.com \
  --query accessToken -o tsv 2>/dev/null)

# The command travels base64-encoded so no quoting survives three layers (JSON, Kudu, bash).
kudu_exec() {
  local b64 body
  b64=$(printf '%s' "$1" | base64 | tr -d '\r\n')
  body=$(printf '{"command":"bash -c \\"echo %s | base64 -d | bash\\"","dir":"/home"}' "$b64")
  curl -sS -m 220 -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -X POST "$KUDU/api/command" -d "$body" \
    | sed -e 's/^{"Output":"//' -e 's/","Error":"/\n--- stderr:\n/' -e 's/","ExitCode":/\n--- exit: /' -e 's/}$//' \
    | sed -e 's/\\n/\n/g' -e 's/\\t/\t/g' -e 's/\\"/"/g' -e 's/\\\\/\\/g'
}

case "$ACTION" in
  probe)
    kudu_exec "df -h /home | tail -1; echo '--- elmah folders:'; find /home/site/wwwroot /home/LogFiles /home/data -maxdepth 3 -type d -iname '*elmah*' ! -name elmah-cleanup 2>/dev/null | sort -u; echo '--- appsettings mentioning elmah:'; grep -il elmah /home/site/wwwroot/appsettings*.json 2>/dev/null; true"
    ;;
  start)
    MODE="${1:?histogram|count|delete required}"; DIR="${2:?dir required}"; DAYS="${3:?days required}"
    kudu_exec "mkdir -p $WORK" >/dev/null
    curl -sS -m 60 -H "Authorization: Bearer $TOKEN" -H "If-Match: *" -X PUT \
      --data-binary "@$SCRIPT_DIR/elmah-xml-cleanup.sh" "$KUDU/api/vfs/LogFiles/elmah-cleanup/elmah-xml-cleanup.sh"
    kudu_exec "sed -i 's/\r$//' $WORK/elmah-xml-cleanup.sh; rm -f $WORK/errors.log; nohup setsid bash $WORK/elmah-xml-cleanup.sh '$MODE' '$DIR' '$DAYS' '$WORK' > $WORK/run.log 2>&1 < /dev/null & sleep 2; cat $WORK/run.log; cat $WORK/status"
    ;;
  status)
    kudu_exec "cat $WORK/status 2>/dev/null || echo 'no job has run'; echo progress=\$(cat $WORK/progress 2>/dev/null); [ -f $WORK/pid ] && kill -0 \$(cat $WORK/pid) 2>/dev/null && echo alive=yes || echo alive=no; tail -5 $WORK/errors.log 2>/dev/null; df -h /home | tail -1"
    ;;
  stop)
    kudu_exec "[ -f $WORK/pid ] && pkill -P \$(cat $WORK/pid); kill \$(cat $WORK/pid) 2>/dev/null; rm -f $WORK/pid; echo stopped"
    ;;
  exec)
    kudu_exec "${1:?command required}"
    ;;
  *)
    echo "Unknown action: $ACTION" >&2; exit 2
    ;;
esac
