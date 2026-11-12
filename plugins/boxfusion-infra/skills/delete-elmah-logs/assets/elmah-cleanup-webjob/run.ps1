# Triggered WebJob: deletes Elmah XML error files older than N days on a Windows App Service.
# Windows PowerShell 5.1 compatible. Keep this file ASCII-only.
# Settings (optional app settings):
#   ELMAH_RETENTION_DAYS  days to keep (default 30, minimum 1)
#   ELMAH_LOG_DIR         folder to clean (default %HOME%\site\wwwroot\App_Data\ElmahLogs)
# Prints progress every 5000 files so the WebJob idle timeout never fires on huge folders.

$ErrorActionPreference = 'Continue'
$days = 30
if ($env:ELMAH_RETENTION_DAYS) { $days = [Math]::Max(1, [int]$env:ELMAH_RETENTION_DAYS) }
$dir = $env:ELMAH_LOG_DIR
if (-not $dir) { $dir = Join-Path $env:HOME 'site\wwwroot\App_Data\ElmahLogs' }

if (-not (Test-Path $dir)) { "Elmah folder not found: $dir - nothing to do"; exit 0 }

$cutoff = (Get-Date).ToUniversalTime().AddDays(-$days)
"Deleting *.xml in $dir last written before $($cutoff.ToString('yyyy-MM-dd HH:mm'))Z (retention $days days)"

$sw = [Diagnostics.Stopwatch]::StartNew()
$seen = 0; $deleted = 0; $failed = 0; $bytes = 0
# EnumerateFiles streams entries, so memory stays flat with millions of files.
foreach ($f in [IO.DirectoryInfo]::new($dir).EnumerateFiles('*.xml')) {
  $seen++
  if ($f.LastWriteTimeUtc -lt $cutoff) {
    try { $len = $f.Length; $f.Delete(); $deleted++; $bytes += $len }
    catch { $failed++; if ($failed -le 20) { "failed: $($f.Name): $($_.Exception.Message)" } }
  }
  if ($seen % 5000 -eq 0) { "progress: seen=$seen deleted=$deleted elapsed=$([int]$sw.Elapsed.TotalMinutes)m" }
}

"done: seen=$seen deleted=$deleted failed=$failed freed_mb=$([int]($bytes / 1MB)) kept=$($seen - $deleted) elapsed=$([int]$sw.Elapsed.TotalMinutes)m"
