# Runs ON a Windows App Service (Kudu), detached via Start-Process by kudu-elmah.sh.
# Windows PowerShell 5.1 compatible. Keep this file ASCII-only (5.1 reads BOM-less files as ANSI).
# Counts, histograms or deletes Elmah XML error files, writing progress to $Work so callers can poll.
#
# Usage: elmah-xml-cleanup.ps1 <histogram|count|delete> <elmah-dir> <older-than-days> [work-dir]
#   older-than-days = 0 matches every file regardless of age (ignored by histogram).

param(
  [Parameter(Mandatory = $true)][string]$Mode,
  [Parameter(Mandatory = $true)][string]$Dir,
  [Parameter(Mandatory = $true)][int]$Days,
  [string]$Work = 'D:/home/LogFiles/elmah-cleanup'
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
New-Item -ItemType Directory -Force $Work | Out-Null
$Status = Join-Path $Work 'status'
$Progress = Join-Path $Work 'progress'
$PidFile = Join-Path $Work 'pid'
$Errors = Join-Path $Work 'errors.log'

function Now { (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }

if (Test-Path $PidFile) {
  $old = Get-Content $PidFile -ErrorAction SilentlyContinue
  if ($old -and (Get-Process -Id $old -ErrorAction SilentlyContinue)) { Write-Error "already running (pid $old)"; exit 1 }
}
Set-Content $PidFile $PID

if ($Mode -notin @('histogram', 'count', 'delete')) { Set-Content $Status "state=error message=unknown-mode-$Mode"; Remove-Item $PidFile; exit 2 }
if (-not (Test-Path $Dir)) { Set-Content $Status 'state=error message=dir-not-found'; Remove-Item $PidFile; exit 2 }

Set-Content $Status @("state=running", "mode=$Mode", "dir=$Dir", "older_than_days=$Days", "started_utc=$(Now)")
Set-Content $Progress 0

# EnumerateFiles streams entries instead of building the whole list, so memory stays flat with millions of files.
$cutoff = (Get-Date).ToUniversalTime().AddDays(-$Days)
$months = @{}
$n = 0
foreach ($f in [IO.DirectoryInfo]::new($Dir).EnumerateFiles('*.xml')) {
  if ($Mode -eq 'histogram') {
    $m = $f.LastWriteTimeUtc.ToString('yyyy-MM'); $months[$m] = 1 + [int]$months[$m]
  } else {
    if ($Days -gt 0 -and $f.LastWriteTimeUtc -ge $cutoff) { continue }
    if ($Mode -eq 'delete') {
      try { $f.Delete() } catch { Add-Content $Errors "$($f.Name): $($_.Exception.Message)"; continue }
    }
  }
  $n++
  if ($n % 5000 -eq 0) { Set-Content $Progress $n }
}
Set-Content $Progress $n

$remaining = 0
foreach ($f in [IO.Directory]::EnumerateFiles($Dir, '*.xml')) { $remaining++ }

$out = @("state=done", "mode=$Mode", "dir=$Dir", "older_than_days=$Days", "matched=$n", "xml_files_remaining=$remaining")
if ($Mode -eq 'histogram') { $out += 'files_by_month:'; $out += ($months.GetEnumerator() | Sort-Object Name | ForEach-Object { '{0,8} {1}' -f $_.Value, $_.Name }) }
$out += "finished_utc=$(Now)"
Set-Content $Status $out
Remove-Item $PidFile -ErrorAction SilentlyContinue
