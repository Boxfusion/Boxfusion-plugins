#!/usr/bin/env bash
# Local driver for app-log cleanup (App_Data/Logs: rolled log4net files and scheduled-job run logs)
# on an Azure App Service (Linux or Windows) through the Kudu (SCM) API.
# Requires: az (logged in), curl, iconv. Works in Git Bash, Linux and macOS.
#
# Usage: kudu-logs.sh <app> <resource-group> <subscription> <action> [args]
#   survey                                   size of the logs folder: top-level files + biggest job folders
#   start <count|delete> <dir> <days> [pattern]  upload the job script and run it detached
#                                            (recursive under <dir>; only files older than <days>, min 1)
#   status                                   print the job's status/progress files
#   stop                                     kill a running job
#   exec "<command>"                         run a short bash (Linux) or PowerShell (Windows) command
#                                            (Kudu kills requests after ~230s)

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
    --data-binary @- "$KUDU/api/vfs/LogFiles/log-cleanup/$(basename "$1")" < "$1"
}

if [ "$OS" = linux ]; then
  WORK=/home/LogFiles/log-cleanup
  case "$ACTION" in
    survey)
      kudu_exec 'd=$(find /home/site/wwwroot/App_Data -maxdepth 1 -type d -iname logs 2>/dev/null | head -1); [ -z "$d" ] && { echo "NOLOGS"; exit 0; }; cd "$d"; echo "DIR $d"; echo "TOTAL_MB $(du -sm . | cut -f1)"; echo "TOP $(find . -maxdepth 1 -type f | wc -l) files $(find . -maxdepth 1 -type f -printf "%s\n" | awk "{s+=\$1} END {printf \"%d\", s/1048576}") MB oldest $(find . -maxdepth 1 -type f -printf "%TY-%Tm\n" | sort 2>/dev/null | head -1)"; for j in */ jobs/*/; do [ -d "$j" ] && [ "$j" != "jobs/" ] && echo "SUB $(du -sm "$j" | cut -f1) MB $(find "$j" -type f | wc -l) files ${j%/} oldest $(find "$j" -type f -printf "%TY-%Tm\n" | sort 2>/dev/null | head -1)"; done | sort -k2 -rn | head -8; df -h /home | tail -1; true'
      ;;
    start)
      MODE="${1:?count|delete required}"; DIR="${2:?dir required}"; DAYS="${3:?days required}"; PAT="${4:-*}"
      kudu_exec "mkdir -p $WORK" >/dev/null
      vfs_put "$SCRIPT_DIR/log-cleanup.sh"
      kudu_exec "sed -i 's/\r$//' $WORK/log-cleanup.sh; rm -f $WORK/errors.log; nohup setsid bash $WORK/log-cleanup.sh '$MODE' '$DIR' '$DAYS' '$PAT' '$WORK' > $WORK/run.log 2>&1 < /dev/null & sleep 2; cat $WORK/run.log; cat $WORK/status"
      ;;
    status)
      kudu_exec "cat $WORK/status 2>/dev/null || echo 'no job has run'; echo \"progress_files_mb=\$(cat $WORK/progress 2>/dev/null)\"; [ -f $WORK/pid ] && kill -0 \$(cat $WORK/pid) 2>/dev/null && echo alive=yes || echo alive=no; tail -5 $WORK/errors.log 2>/dev/null; df -h /home | tail -1"
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
else
  WORK=D:/home/LogFiles/log-cleanup
  case "$ACTION" in
    survey)
      kudu_exec '$d = Get-ChildItem D:/home/site/wwwroot/App_Data -Directory -ErrorAction SilentlyContinue | Where-Object Name -eq "logs" | Select-Object -First 1; if (-not $d) { "NOLOGS"; exit 0 }; "DIR " + $d.FullName; $all = $d.GetFiles("*","AllDirectories"); "TOTAL_MB {0:N0}" -f (($all | Measure-Object Length -Sum).Sum/1MB); $top = $d.GetFiles(); "TOP {0} files {1:N0} MB oldest {2}" -f $top.Count, (($top | Measure-Object Length -Sum).Sum/1MB), ($top | Sort-Object LastWriteTime | Select-Object -First 1 | ForEach-Object { $_.LastWriteTime.ToString("yyyy-MM") }); $subs = @($d.GetDirectories() | Where-Object Name -ne "jobs"); $j = Join-Path $d.FullName "jobs"; if (Test-Path $j) { $subs += ([IO.DirectoryInfo]$j).GetDirectories() }; $subs | ForEach-Object { $f = $_.GetFiles("*","AllDirectories"); [pscustomobject]@{ mb = [int](($f | Measure-Object Length -Sum).Sum/1MB); n = $f.Count; name = $_.FullName.Substring($d.FullName.Length + 1); old = ($f | Sort-Object LastWriteTime | Select-Object -First 1 | ForEach-Object { $_.LastWriteTime.ToString("yyyy-MM") }) } } | Sort-Object mb -Descending | Select-Object -First 8 | ForEach-Object { "SUB {0} MB {1} files {2} oldest {3}" -f $_.mb, $_.n, $_.name, $_.old }; exit 0'
      ;;
    start)
      MODE="${1:?count|delete required}"; DIR="${2:?dir required}"; DAYS="${3:?days required}"; PAT="${4:-*}"
      kudu_exec "New-Item -ItemType Directory -Force '$WORK' | Out-Null" >/dev/null
      vfs_put "$SCRIPT_DIR/log-cleanup.ps1"
      kudu_exec "Remove-Item '$WORK/errors.log' -ErrorAction SilentlyContinue; Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','$WORK/log-cleanup.ps1','$MODE','$DIR','$DAYS','$PAT','$WORK' | Out-Null; Start-Sleep 3; Get-Content '$WORK/status'"
      ;;
    status)
      kudu_exec "if (Test-Path '$WORK/status') { Get-Content '$WORK/status' } else { 'no job has run' }; 'progress_files_mb=' + (Get-Content '$WORK/progress' -ErrorAction SilentlyContinue); \$p = Get-Content '$WORK/pid' -ErrorAction SilentlyContinue; if (\$p -and (Get-Process -Id \$p -ErrorAction SilentlyContinue)) { 'alive=yes' } else { 'alive=no' }; Get-Content '$WORK/errors.log' -Tail 5 -ErrorAction SilentlyContinue; exit 0"
      ;;
    stop)
      kudu_exec "\$p = Get-Content '$WORK/pid' -ErrorAction SilentlyContinue; if (\$p) { Stop-Process -Id \$p -Force -ErrorAction SilentlyContinue }; Remove-Item '$WORK/pid' -ErrorAction SilentlyContinue; 'stopped'"
      ;;
    exec)
      kudu_exec "${1:?command required}"
      ;;
    *)
      echo "Unknown action: $ACTION" >&2; exit 2
      ;;
  esac
fi
