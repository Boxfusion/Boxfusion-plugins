#!/usr/bin/env bash
# Local driver for Elmah cleanup on an Azure App Service (Linux or Windows) through the Kudu (SCM) API:
# XML files on disk, or Shesha.Elmah rows in the app's SQL Server database.
# Requires: az (logged in), curl, iconv. Works in Git Bash, Linux and macOS.
#
# Usage: kudu-elmah.sh <app> <resource-group> <subscription> <action> [args]
#   probe                          locate Elmah folders and show disk usage
#   start <histogram|count|delete> <dir> <days>  upload the job script and run it detached
#   status                         print the job's status/progress files
#   stop                           kill a running job
#   sql-start <histogram|count|delete> <days> [batch]  same for the elmah.errors table in the app's
#                                  Default database (runs on the app side, so no SQL firewall rule needed)
#   sql-status | sql-stop          poll / kill the SQL job
#   exec "<command>"               run a short bash (Linux) or PowerShell (Windows) command
#                                  (Kudu kills requests after ~230s)

set -euo pipefail
export MSYS_NO_PATHCONV=1   # stop Git Bash rewriting /home/... and /subscriptions/... into Windows paths

APP="${1:?app name required}"
RG="${2:?resource group required}"
SUB="${3:?subscription required}"
ACTION="${4:?action required}"
shift 4

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

INFO=$(az webapp show --subscription "$SUB" -g "$RG" -n "$APP" \
  --query "[kind, hostNameSslStates[?hostType=='Repository'].name | [0]]" -o tsv 2>/dev/null | tr -d '\r')
KIND=$(printf '%s\n' "$INFO" | sed -n 1p)
HOST=$(printf '%s\n' "$INFO" | sed -n 2p)
[ -n "$HOST" ] || { echo "Could not resolve SCM host for $APP" >&2; exit 1; }
KUDU="https://$HOST"
TOKEN=$(az account get-access-token --subscription "$SUB" --resource https://management.azure.com \
  --query accessToken -o tsv 2>/dev/null)

case "$KIND" in *linux*) OS=linux ;; *) OS=windows ;; esac

kudu_post() {
  curl -sS -m 220 -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -X POST "$KUDU/api/command" -d "$1" \
    | sed -e 's/^{"OutputValidator":null,//' -e 's/^{"Output":"//' -e 's/^"Output":"//' \
          -e 's/","Error":"#< CLIXML.*","ExitCode":/\n--- exit: /' \
          -e 's/","Error":"/\n--- stderr:\n/' -e 's/","ExitCode":/\n--- exit: /' -e 's/}$//' \
    | sed -e 's/\\r//g' -e 's/\\n/\n/g' -e 's/\\t/\t/g' -e 's/\\"/"/g' -e 's/\\\\/\\/g'
}

# Commands travel encoded so no quoting survives the layers (JSON, Kudu, shell):
# base64 piped into bash on Linux, -EncodedCommand (UTF-16LE base64) on Windows.
kudu_exec() {
  local b64
  if [ "$OS" = linux ]; then
    b64=$(printf '%s' "$1" | base64 | tr -d '\r\n')
    kudu_post "$(printf '{"command":"bash -c \\"echo %s | base64 -d | bash\\"","dir":"/home"}' "$b64")"
  else
    b64=$(printf '%s' "\$ProgressPreference='SilentlyContinue'; $1" | iconv -f utf-8 -t utf-16le | base64 | tr -d '\r\n')
    kudu_post "$(printf '{"command":"powershell -NoProfile -NonInteractive -EncodedCommand %s","dir":"site"}' "$b64")"
  fi
}

vfs_put() {
  # stdin rather than @path: with MSYS_NO_PATHCONV a native Windows curl can't open /c/... paths
  curl -sS -m 60 -H "Authorization: Bearer $TOKEN" -H "If-Match: *" -X PUT \
    --data-binary @- "$KUDU/api/vfs/LogFiles/${2:-elmah-cleanup}/$(basename "$1")" < "$1"
}

if [ "$OS" = linux ]; then
  WORK=/home/LogFiles/elmah-cleanup
  SQLWORK=/home/LogFiles/elmah-sql
  case "$ACTION" in
    probe)
      kudu_exec "df -h /home | tail -1; echo '--- elmah folders:'; find /home/site/wwwroot /home/LogFiles /home/data -maxdepth 3 -type d -iname '*elmah*' ! -name elmah-cleanup 2>/dev/null | sort -u; echo '--- appsettings mentioning elmah:'; grep -il elmah /home/site/wwwroot/appsettings*.json 2>/dev/null; true"
      ;;
    start)
      MODE="${1:?histogram|count|delete required}"; DIR="${2:?dir required}"; DAYS="${3:?days required}"
      kudu_exec "mkdir -p $WORK" >/dev/null
      vfs_put "$SCRIPT_DIR/elmah-xml-cleanup.sh"
      kudu_exec "sed -i 's/\r$//' $WORK/elmah-xml-cleanup.sh; rm -f $WORK/errors.log; nohup setsid bash $WORK/elmah-xml-cleanup.sh '$MODE' '$DIR' '$DAYS' '$WORK' > $WORK/run.log 2>&1 < /dev/null & sleep 2; cat $WORK/run.log; cat $WORK/status"
      ;;
    status)
      kudu_exec "cat $WORK/status 2>/dev/null || echo 'no job has run'; echo progress=\$(cat $WORK/progress 2>/dev/null); [ -f $WORK/pid ] && kill -0 \$(cat $WORK/pid) 2>/dev/null && echo alive=yes || echo alive=no; tail -5 $WORK/errors.log 2>/dev/null; df -h /home | tail -1"
      ;;
    stop)
      kudu_exec "[ -f $WORK/pid ] && pkill -P \$(cat $WORK/pid); kill \$(cat $WORK/pid) 2>/dev/null; rm -f $WORK/pid; echo stopped"
      ;;
    sql-start)
      MODE="${1:?histogram|count|delete required}"; DAYS="${2:?days required}"; BATCH="${3:-5000}"
      kudu_exec "mkdir -p $SQLWORK" >/dev/null
      vfs_put "$SCRIPT_DIR/elmah-sql.js" elmah-sql
      # elmah-sql.js installs the mssql npm package into $SQLWORK on first run (state=installing-mssql).
      kudu_exec "cd $SQLWORK; rm -f errors.log status; nohup setsid node $SQLWORK/elmah-sql.js '$MODE' '$DAYS' '$BATCH' '$SQLWORK' > run.log 2>&1 < /dev/null & sleep 5; cat run.log; cat status 2>/dev/null"
      ;;
    sql-status)
      kudu_exec "cat $SQLWORK/status 2>/dev/null || echo 'no job has run'; echo progress=\$(cat $SQLWORK/progress 2>/dev/null); [ -f $SQLWORK/pid ] && kill -0 \$(cat $SQLWORK/pid) 2>/dev/null && echo alive=yes || echo alive=no; tail -5 $SQLWORK/errors.log 2>/dev/null; true"
      ;;
    sql-stop)
      kudu_exec "[ -f $SQLWORK/pid ] && kill \$(cat $SQLWORK/pid) 2>/dev/null; rm -f $SQLWORK/pid; echo stopped"
      ;;
    exec)
      kudu_exec "${1:?command required}"
      ;;
    *)
      echo "Unknown action: $ACTION" >&2; exit 2
      ;;
  esac
else
  WORK=D:/home/LogFiles/elmah-cleanup
  SQLWORK=D:/home/LogFiles/elmah-sql
  case "$ACTION" in
    probe)
      # Windows Kudu reports drive usage as 0; use the FileSystemUsage metric for disk size instead.
      kudu_exec "'--- elmah folders:';foreach (\$r in 'D:/home/site/wwwroot','D:/home/LogFiles','D:/home/data') { if (Test-Path \$r) { Get-ChildItem \$r -Directory -Recurse -Depth 2 -Filter '*elmah*' -ErrorAction SilentlyContinue | Where-Object Name -ne 'elmah-cleanup' | ForEach-Object FullName } }; '--- appsettings mentioning elmah:'; Select-String -Path D:/home/site/wwwroot/appsettings*.json, D:/home/site/wwwroot/web.config -Pattern elmah -List -ErrorAction SilentlyContinue | ForEach-Object Path"
      ;;
    start)
      MODE="${1:?histogram|count|delete required}"; DIR="${2:?dir required}"; DAYS="${3:?days required}"
      kudu_exec "New-Item -ItemType Directory -Force '$WORK' | Out-Null" >/dev/null
      vfs_put "$SCRIPT_DIR/elmah-xml-cleanup.ps1"
      kudu_exec "Remove-Item '$WORK/errors.log' -ErrorAction SilentlyContinue; Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','$WORK/elmah-xml-cleanup.ps1','$MODE','$DIR','$DAYS','$WORK' | Out-Null; Start-Sleep 3; Get-Content '$WORK/status'"
      ;;
    status)
      kudu_exec "if (Test-Path '$WORK/status') { Get-Content '$WORK/status' } else { 'no job has run' }; 'progress=' + (Get-Content '$WORK/progress' -ErrorAction SilentlyContinue); \$p = Get-Content '$WORK/pid' -ErrorAction SilentlyContinue; if (\$p -and (Get-Process -Id \$p -ErrorAction SilentlyContinue)) { 'alive=yes' } else { 'alive=no' }; Get-Content '$WORK/errors.log' -Tail 5 -ErrorAction SilentlyContinue; exit 0"
      ;;
    stop)
      kudu_exec "\$p = Get-Content '$WORK/pid' -ErrorAction SilentlyContinue; if (\$p) { Stop-Process -Id \$p -Force -ErrorAction SilentlyContinue }; Remove-Item '$WORK/pid' -ErrorAction SilentlyContinue; 'stopped'"
      ;;
    sql-start)
      MODE="${1:?histogram|count|delete required}"; DAYS="${2:?days required}"; BATCH="${3:-5000}"
      kudu_exec "New-Item -ItemType Directory -Force '$SQLWORK' | Out-Null" >/dev/null
      vfs_put "$SCRIPT_DIR/elmah-sql.ps1" elmah-sql
      kudu_exec "Remove-Item '$SQLWORK/errors.log','$SQLWORK/status' -ErrorAction SilentlyContinue; Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','$SQLWORK/elmah-sql.ps1','$MODE','$DAYS','$BATCH','$SQLWORK' | Out-Null; Start-Sleep 5; Get-Content '$SQLWORK/status' -ErrorAction SilentlyContinue; exit 0"
      ;;
    sql-status)
      kudu_exec "if (Test-Path '$SQLWORK/status') { Get-Content '$SQLWORK/status' } else { 'no job has run' }; 'progress=' + (Get-Content '$SQLWORK/progress' -ErrorAction SilentlyContinue); \$p = Get-Content '$SQLWORK/pid' -ErrorAction SilentlyContinue; if (\$p -and (Get-Process -Id \$p -ErrorAction SilentlyContinue)) { 'alive=yes' } else { 'alive=no' }; Get-Content '$SQLWORK/errors.log' -Tail 5 -ErrorAction SilentlyContinue; exit 0"
      ;;
    sql-stop)
      kudu_exec "\$p = Get-Content '$SQLWORK/pid' -ErrorAction SilentlyContinue; if (\$p) { Stop-Process -Id \$p -Force -ErrorAction SilentlyContinue }; Remove-Item '$SQLWORK/pid' -ErrorAction SilentlyContinue; 'stopped'"
      ;;
    exec)
      kudu_exec "${1:?command required}"
      ;;
    *)
      echo "Unknown action: $ACTION" >&2; exit 2
      ;;
  esac
fi
