# Runs ON a Windows App Service (Kudu), detached via Start-Process by kudu-logs.sh.
# Windows PowerShell 5.1 compatible. Keep this file ASCII-only (5.1 reads BOM-less files as ANSI).
# Counts or deletes log files older than N days under a folder (recursively), writing progress to $Work.
#
# Usage: log-cleanup.ps1 <count|delete> <dir> <older-than-days> [name-pattern] [work-dir]
#   older-than-days must be >= 1 so a log that is still being written is never touched.

param(
  [Parameter(Mandatory = $true)][string]$Mode,
  [Parameter(Mandatory = $true)][string]$Dir,
  [Parameter(Mandatory = $true)][int]$Days,
  [string]$Pattern = '*',
  [string]$Work = 'D:/home/LogFiles/log-cleanup'
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
New-Item -ItemType Directory -Force $Work | Out-Null
$Status = Join-Path $Work 'status'
$Progress = Join-Path $Work 'progress'
$PidFile = Join-Path $Work 'pid'
$Errors = Join-Path $Work 'errors.log'

function Now { (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
function Fail($m) { Set-Content $Status "state=error message=$m"; Remove-Item $PidFile -ErrorAction SilentlyContinue; exit 2 }

if (Test-Path $PidFile) {
  $old = Get-Content $PidFile -ErrorAction SilentlyContinue
  if ($old -and (Get-Process -Id $old -ErrorAction SilentlyContinue)) { Write-Error "already running (pid $old)"; exit 1 }
}
Set-Content $PidFile $PID

if ($Mode -notin @('count', 'delete')) { Fail "unknown-mode-$Mode" }
if (-not (Test-Path $Dir)) { Fail 'dir-not-found' }
if ($Days -lt 1) { Fail 'days-must-be-at-least-1' }

Set-Content $Status @("state=running", "mode=$Mode", "dir=$Dir", "pattern=$Pattern", "older_than_days=$Days", "started_utc=$(Now)")
Set-Content $Progress '0 0'

# EnumerateFiles streams entries, so memory stays flat however many files there are.
$cutoff = (Get-Date).ToUniversalTime().AddDays(-$Days)
$n = 0; $bytes = 0
foreach ($f in [IO.DirectoryInfo]::new($Dir).EnumerateFiles($Pattern, 'AllDirectories')) {
  if ($f.LastWriteTimeUtc -ge $cutoff) { continue }
  $len = $f.Length
  if ($Mode -eq 'delete') {
    try { $f.Delete() } catch { Add-Content $Errors "$($f.FullName): $($_.Exception.Message)"; continue }
  }
  $n++; $bytes += $len
  if ($n % 500 -eq 0) { Set-Content $Progress ('{0} {1}' -f $n, [int64]($bytes / 1MB)) }
}
Set-Content $Progress ('{0} {1}' -f $n, [int64]($bytes / 1MB))

$left = 0
foreach ($f in [IO.DirectoryInfo]::new($Dir).EnumerateFiles('*', 'AllDirectories')) { $left += $f.Length }

Set-Content $Status @("state=done", "mode=$Mode", "dir=$Dir", "pattern=$Pattern", "older_than_days=$Days",
  "matched_files=$n", ('matched_mb={0}' -f [int64]($bytes / 1MB)), ('dir_mb_now={0}' -f [int64]($left / 1MB)), "finished_utc=$(Now)")
Remove-Item $PidFile -ErrorAction SilentlyContinue
