# Runs ON a Windows App Service (Kudu), detached via Start-Process by kudu-elmah.sh.
# Windows PowerShell 5.1 compatible. Keep this file ASCII-only (5.1 reads BOM-less files as ANSI).
# Sizes, counts or deletes Shesha.Elmah rows (elmah.errors + orphaned elmah.error_refs) in the app's own
# SQL Server database, using the app's Default connection string. Never prints the connection string.
#
# Usage: elmah-sql.ps1 <histogram|count|delete> <older-than-days> [batch-size] [work-dir]

param(
  [Parameter(Mandatory = $true)][string]$Mode,
  [Parameter(Mandatory = $true)][int]$Days,
  [int]$Batch = 5000,
  [string]$Work = 'D:/home/LogFiles/elmah-sql'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
New-Item -ItemType Directory -Force $Work | Out-Null
$Status = Join-Path $Work 'status'
$Progress = Join-Path $Work 'progress'
$PidFile = Join-Path $Work 'pid'
$Errors = Join-Path $Work 'errors.log'

function Now { (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
function Fail($m) { Set-Content $Status @('state=error', "message=$m"); Remove-Item $PidFile -ErrorAction SilentlyContinue; exit 2 }

if (Test-Path $PidFile) {
  $old = Get-Content $PidFile -ErrorAction SilentlyContinue
  if ($old -and (Get-Process -Id $old -ErrorAction SilentlyContinue)) { Write-Error "already running (pid $old)"; exit 1 }
}
Set-Content $PidFile $PID

if ($Mode -notin @('histogram', 'count', 'delete')) { Fail "unknown-mode-$Mode" }
if ($Mode -eq 'delete' -and $Days -lt 1) { Fail 'days-must-be-at-least-1' }

# App Service exposes connection strings as env vars; fall back to the deployed appsettings.
$cs = $null
foreach ($k in 'SQLAZURECONNSTR_Default', 'SQLCONNSTR_Default', 'CUSTOMCONNSTR_Default', 'APPSETTING_ConnectionStrings__Default', 'ConnectionStrings__Default') {
  $v = [Environment]::GetEnvironmentVariable($k)
  if ($v) { $cs = $v; break }
}
if (-not $cs) {
  foreach ($f in 'appsettings.Production.json', 'appsettings.json') {
    $p = Join-Path 'D:/home/site/wwwroot' $f
    if (Test-Path $p) {
      try { $j = Get-Content $p -Raw | ConvertFrom-Json; if ($j.ConnectionStrings.Default) { $cs = $j.ConnectionStrings.Default; break } } catch {}
    }
  }
}
if (-not $cs) { Fail 'no-default-connection-string' }

$conn = New-Object System.Data.SqlClient.SqlConnection $cs
function Q($text, $params) {
  $cmd = $conn.CreateCommand(); $cmd.CommandText = $text; $cmd.CommandTimeout = 600
  if ($params) { foreach ($k in $params.Keys) { [void]$cmd.Parameters.AddWithValue($k, $params[$k]) } }
  $t = New-Object System.Data.DataTable
  $t.Load($cmd.ExecuteReader())
  , $t
}
function X($text, $params) {
  $cmd = $conn.CreateCommand(); $cmd.CommandText = $text; $cmd.CommandTimeout = 600
  foreach ($k in $params.Keys) { [void]$cmd.Parameters.AddWithValue($k, $params[$k]) }
  $cmd.ExecuteNonQuery()
}

try {
  $conn.Open()
  $db = (Q 'SELECT DB_NAME() AS name').Rows[0].name
  $header = @("mode=$Mode", "database=$db", "older_than_days=$Days")
  Set-Content $Status (@('state=running') + $header + "started_utc=$(Now)")
  Set-Content $Progress '0'

  if ((Q "SELECT OBJECT_ID('elmah.errors', 'U') AS id").Rows[0].id -is [DBNull]) {
    Set-Content $Status (@('state=done') + $header + 'elmah_table=missing' + "finished_utc=$(Now)")
    Remove-Item $PidFile -ErrorAction SilentlyContinue
    exit 0
  }

  $cutoff = (Get-Date).ToUniversalTime().AddDays(-$Days)
  $sizeSql = "SELECT CAST(SUM(a.total_pages) * 8 / 1024 AS int) AS mb FROM sys.partitions p JOIN sys.allocation_units a ON a.container_id = p.partition_id WHERE p.object_id IN (OBJECT_ID('elmah.errors'), OBJECT_ID('elmah.error_refs'))"
  $olderSql = 'SELECT COUNT_BIG(*) AS n FROM elmah.errors WHERE time_utc < @cutoff'

  if ($Mode -eq 'histogram') {
    $out = @('state=done') + $header
    $out += "elmah_mb=$((Q $sizeSql).Rows[0].mb)"
    $out += "db_mb=$((Q 'SELECT CAST(SUM(CAST(size AS bigint)) * 8 / 1024 AS int) AS mb FROM sys.database_files').Rows[0].mb)"
    $out += "refs=$((Q 'SELECT COUNT_BIG(*) AS n FROM elmah.error_refs').Rows[0].n)"
    $out += 'rows_by_application:'
    foreach ($r in (Q 'SELECT application, COUNT_BIG(*) AS n, MIN(time_utc) AS oldest, MAX(time_utc) AS newest FROM elmah.errors GROUP BY application ORDER BY n DESC').Rows) {
      $out += ('  {0} {1} {2:yyyy-MM-dd}..{3:yyyy-MM-dd}' -f $r.n, $r.application, $r.oldest, $r.newest)
    }
    $out += 'rows_by_month:'
    foreach ($r in (Q 'SELECT CONVERT(char(7), time_utc, 126) AS m, COUNT_BIG(*) AS n FROM elmah.errors GROUP BY CONVERT(char(7), time_utc, 126) ORDER BY m').Rows) {
      $out += ('  {0} {1}' -f $r.n, $r.m)
    }
    $types = Q "SELECT CASE WHEN time_utc < @cutoff THEN 'older' ELSE 'recent' END AS age, type, LEFT(message, 110) AS msg, COUNT_BIG(*) AS n FROM elmah.errors GROUP BY CASE WHEN time_utc < @cutoff THEN 'older' ELSE 'recent' END, type, LEFT(message, 110)" @{ cutoff = $cutoff }
    foreach ($age in 'older', 'recent') {
      $out += "top_types_${age}:"
      $types.Rows | Where-Object { $_.age -eq $age } | Sort-Object { [int64]$_.n } -Descending | Select-Object -First 10 |
        ForEach-Object { $out += ('  {0} {1} | {2}' -f $_.n, $_.type, ("$($_.msg)" -replace '\s+', ' ')) }
    }
    $out += "rows_older_than_cutoff=$((Q $olderSql @{ cutoff = $cutoff }).Rows[0].n)"
    $out += "finished_utc=$(Now)"
    Set-Content $Status $out
  }
  elseif ($Mode -eq 'count') {
    Set-Content $Status (@('state=done') + $header + "matched=$((Q $olderSql @{ cutoff = $cutoff }).Rows[0].n)" + "elmah_mb=$((Q $sizeSql).Rows[0].mb)" + "finished_utc=$(Now)")
  }
  else {
    # One application at a time so each batch seeks ix_errors_app_time_seq instead of scanning the heap.
    # Each batch is its own short transaction, so the live app keeps logging. TABLOCK lets the heap free its pages.
    $deleted = 0
    foreach ($app in ((Q 'SELECT DISTINCT application FROM elmah.errors').Rows | ForEach-Object { $_.application })) {
      do {
        $n = X 'DELETE TOP (@batch) FROM elmah.errors WITH (TABLOCK) WHERE application = @app AND time_utc < @cutoff' @{ batch = $Batch; app = $app; cutoff = $cutoff }
        $deleted += $n
        Set-Content $Progress $deleted
      } while ($n -gt 0)
    }
    # error_refs has no foreign key, so remove refs whose error is gone.
    $refs = 0
    do {
      $n = X 'DELETE TOP (@batch) r FROM elmah.error_refs r WHERE NOT EXISTS (SELECT 1 FROM elmah.errors e WHERE e.error_id = r.error_id)' @{ batch = $Batch }
      $refs += $n
    } while ($n -gt 0)
    Set-Content $Status (@('state=done') + $header + "deleted=$deleted" + "orphan_refs_deleted=$refs" +
      "rows_remaining=$((Q 'SELECT COUNT_BIG(*) AS n FROM elmah.errors').Rows[0].n)" + "elmah_mb=$((Q $sizeSql).Rows[0].mb)" + "finished_utc=$(Now)")
  }
}
catch {
  Add-Content $Errors "$(Now) $($_.Exception.Message)"
  Fail 'see-errors.log'
}
finally {
  $conn.Close()
}
Remove-Item $PidFile -ErrorAction SilentlyContinue
