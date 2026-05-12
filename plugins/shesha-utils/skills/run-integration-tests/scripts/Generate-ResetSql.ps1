param(
    [Parameter(Mandatory=$true)]
    [string]$ServerInstance,

    [Parameter(Mandatory=$true)]
    [string]$DatabaseName,

    [Parameter(Mandatory=$true)]
    [string]$OutputPath,

    [Parameter(Mandatory=$true)]
    [string]$TestProjectPath
)

$ErrorActionPreference = "Stop"

# --- Helpers ---

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host ">> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "   $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "   $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host "   $Message" -ForegroundColor Red
}

function Invoke-SqlQuery {
    param(
        [string]$Server,
        [string]$Database,
        [string]$Query
    )
    $result = sqlcmd -S $Server -d $Database -C -Q $Query -h -1 -W -s "|" -b 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "sqlcmd query failed (exit code $LASTEXITCODE): $result"
    }
    return $result
}

# --- Validation ---

Write-Step "Validating inputs..."

Write-Ok "Server: $ServerInstance"
Write-Ok "Database: $DatabaseName"
Write-Ok "Output: $OutputPath"
Write-Ok "Test project: $TestProjectPath"

$sqlcmdCmd = Get-Command sqlcmd -ErrorAction SilentlyContinue
if (-not $sqlcmdCmd) {
    Write-Err "sqlcmd not found. Ensure SQL Server command-line tools are installed."
    Write-Err "Install via: winget install Microsoft.SqlServer.SqlCmd"
    exit 1
}

# Verify database exists
$query = "SELECT CASE WHEN DB_ID(N'`$(DbName)') IS NOT NULL THEN 'YES' ELSE 'NO' END"
$result = sqlcmd -S $ServerInstance -C -Q $query -h -1 -W -v DbName="$DatabaseName" 2>$null
if (-not ($result -and ($result.Trim() -eq "YES"))) {
    Write-Err "Database '$DatabaseName' does not exist on server '$ServerInstance'."
    exit 1
}
Write-Ok "Database '$DatabaseName' found."

# --- Step 1: Discover all user tables ---

Write-Step "Discovering user tables..."

$tablesQuery = @"
SELECT s.name + '|' + t.name
FROM sys.tables t
INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
WHERE t.type = 'U'
ORDER BY s.name, t.name
"@

$tableLines = Invoke-SqlQuery -Server $ServerInstance -Database $DatabaseName -Query $tablesQuery
$allTables = @()
foreach ($line in $tableLines) {
    $trimmed = $line.Trim()
    if ($trimmed -and $trimmed -ne "" -and $trimmed -notmatch "^\(\d+ rows? affected\)$") {
        $parts = $trimmed -split "\|", 2
        if ($parts.Count -eq 2 -and $parts[0] -and $parts[1]) {
            $allTables += @{ Schema = $parts[0].Trim(); Table = $parts[1].Trim() }
        }
    }
}

Write-Ok "Found $($allTables.Count) user tables."

# --- Step 2: Classify tables ---

Write-Step "Classifying tables (preserve vs clean)..."

$preservePatterns = @(
    "^Abp",
    "^Frwk_",
    "^Core_",
    "^__MigrationHistory$",
    "^VersionInfo$",
    "^Hangfire",
    "^sysdiagrams$",
    "^vw_"
)

$preserveTables = @()
$cleanTables = @()

foreach ($t in $allTables) {
    $tableName = $t.Table
    $isPreserve = $false
    foreach ($pattern in $preservePatterns) {
        if ($tableName -match $pattern) {
            $isPreserve = $true
            break
        }
    }
    if ($isPreserve) {
        $preserveTables += $t
    } else {
        $cleanTables += $t
    }
}

Write-Ok "Preserve (framework/system): $($preserveTables.Count) tables"
Write-Ok "Clean (application data): $($cleanTables.Count) tables"

if ($cleanTables.Count -eq 0) {
    Write-Warn "No application tables found to clean. Generating empty reset script."
    $scriptContent = @"
-- Integration Test Database Reset Script
-- Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
-- Database: $DatabaseName
-- No application tables found to clean.
PRINT 'No application tables to reset.';
"@
    $outputDir = Split-Path -Parent $OutputPath
    if (-not (Test-Path $outputDir)) {
        New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    }
    Set-Content -Path $OutputPath -Value $scriptContent -Encoding UTF8
    Write-Ok "Empty reset script written to: $OutputPath"
    exit 0
}

# --- Step 3: Build FK dependency graph ---

Write-Step "Building FK dependency graph..."

$fkQuery = @"
SELECT
    ps.name + '|' + pt.name + '|' + cs.name + '|' + ct.name
FROM sys.foreign_keys fk
INNER JOIN sys.tables pt ON fk.referenced_object_id = pt.object_id
INNER JOIN sys.schemas ps ON pt.schema_id = ps.schema_id
INNER JOIN sys.tables ct ON fk.parent_object_id = ct.object_id
INNER JOIN sys.schemas cs ON ct.schema_id = cs.schema_id
WHERE pt.type = 'U' AND ct.type = 'U'
"@

$fkLines = Invoke-SqlQuery -Server $ServerInstance -Database $DatabaseName -Query $fkQuery

# Build adjacency list: parent -> list of children
# For deletion order, children must be deleted before parents
$fkEdges = @()
foreach ($line in $fkLines) {
    $trimmed = $line.Trim()
    if ($trimmed -and $trimmed -ne "" -and $trimmed -notmatch "^\(\d+ rows? affected\)$") {
        $parts = $trimmed -split "\|"
        if ($parts.Count -eq 4) {
            $parentKey = "$($parts[0].Trim()).$($parts[1].Trim())"
            $childKey = "$($parts[2].Trim()).$($parts[3].Trim())"
            $fkEdges += @{ Parent = $parentKey; Child = $childKey }
        }
    }
}

Write-Ok "Found $($fkEdges.Count) foreign key relationships."

# --- Step 4: Topological sort (children first) ---

Write-Step "Computing deletion order (topological sort)..."

# Build table key set for clean tables only
$cleanTableKeys = @{}
foreach ($t in $cleanTables) {
    $key = "$($t.Schema).$($t.Table)"
    $cleanTableKeys[$key] = $true
}

# Build adjacency: for each clean table, track which other clean tables reference it (children)
# In-degree = number of clean tables this table references (parents it depends on)
$inDegree = @{}
$dependents = @{}  # parent -> list of children (clean tables only)

foreach ($key in $cleanTableKeys.Keys) {
    $inDegree[$key] = 0
    $dependents[$key] = @()
}

# Filter FK edges to only those between clean tables
foreach ($edge in $fkEdges) {
    $parent = $edge.Parent
    $child = $edge.Child
    if ($cleanTableKeys.ContainsKey($parent) -and $cleanTableKeys.ContainsKey($child)) {
        # child references parent, so child must be deleted before parent
        # In deletion order: child has a dependency on parent being deleted later
        # We model: parent depends on child being deleted first → child should come first
        # So in-degree of parent increases (parent waits for child)
        if ($parent -ne $child) {  # skip self-referencing FKs
            $inDegree[$parent] = $inDegree[$parent] + 1
            $dependents[$child] = $dependents[$child] + @($parent)
        }
    }
}

# Kahn's algorithm for topological sort
$queue = New-Object System.Collections.Generic.Queue[string]
foreach ($key in $cleanTableKeys.Keys) {
    if ($inDegree[$key] -eq 0) {
        $queue.Enqueue($key)
    }
}

$sortedOrder = @()
while ($queue.Count -gt 0) {
    $current = $queue.Dequeue()
    $sortedOrder += $current
    foreach ($dep in $dependents[$current]) {
        $inDegree[$dep] = $inDegree[$dep] - 1
        if ($inDegree[$dep] -eq 0) {
            $queue.Enqueue($dep)
        }
    }
}

# Check for circular dependencies
$circularTables = @()
if ($sortedOrder.Count -lt $cleanTableKeys.Count) {
    Write-Warn "Circular FK dependencies detected. Some tables will use DISABLE/ENABLE constraints."
    foreach ($key in $cleanTableKeys.Keys) {
        if ($sortedOrder -notcontains $key) {
            $circularTables += $key
        }
    }
    Write-Warn "Circular tables: $($circularTables -join ', ')"
}

Write-Ok "Deletion order computed: $($sortedOrder.Count) tables sorted, $($circularTables.Count) circular."

# --- Step 5: Detect identity columns ---

Write-Step "Detecting identity columns..."

$identityQuery = @"
SELECT s.name + '|' + t.name + '|' + ic.name
FROM sys.identity_columns ic
INNER JOIN sys.tables t ON ic.object_id = t.object_id
INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
WHERE t.type = 'U'
"@

$identityLines = Invoke-SqlQuery -Server $ServerInstance -Database $DatabaseName -Query $identityQuery

$identityTables = @{}
foreach ($line in $identityLines) {
    $trimmed = $line.Trim()
    if ($trimmed -and $trimmed -ne "" -and $trimmed -notmatch "^\(\d+ rows? affected\)$") {
        $parts = $trimmed -split "\|"
        if ($parts.Count -eq 3) {
            $key = "$($parts[0].Trim()).$($parts[1].Trim())"
            if ($cleanTableKeys.ContainsKey($key)) {
                $identityTables[$key] = $true
            }
        }
    }
}

Write-Ok "Found $($identityTables.Count) application tables with identity columns."

# --- Step 6: Generate SQL script ---

Write-Step "Generating reset SQL script..."

$sb = New-Object System.Text.StringBuilder

[void]$sb.AppendLine("-- ============================================================")
[void]$sb.AppendLine("-- Integration Test Database Reset Script")
[void]$sb.AppendLine("-- Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
[void]$sb.AppendLine("-- Database: $DatabaseName")
[void]$sb.AppendLine("-- Server: $ServerInstance")
[void]$sb.AppendLine("-- Preserved tables (framework/system): $($preserveTables.Count)")
[void]$sb.AppendLine("-- Cleaned tables (application data): $($cleanTables.Count)")
[void]$sb.AppendLine("-- ============================================================")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("SET NOCOUNT ON;")
[void]$sb.AppendLine("SET QUOTED_IDENTIFIER ON;")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("BEGIN TRY")
[void]$sb.AppendLine("    BEGIN TRANSACTION;")
[void]$sb.AppendLine("")

# Handle circular dependency tables first — disable constraints, delete, re-enable
if ($circularTables.Count -gt 0) {
    [void]$sb.AppendLine("    -- Circular FK tables: disable constraints, delete, re-enable")
    foreach ($tKey in $circularTables) {
        $parts = $tKey -split "\.", 2
        [void]$sb.AppendLine("    ALTER TABLE [$($parts[0])].[$($parts[1])] NOCHECK CONSTRAINT ALL;")
    }
    [void]$sb.AppendLine("")
    foreach ($tKey in $circularTables) {
        $parts = $tKey -split "\.", 2
        [void]$sb.AppendLine("    DELETE FROM [$($parts[0])].[$($parts[1])];")
    }
    [void]$sb.AppendLine("")
    foreach ($tKey in $circularTables) {
        $parts = $tKey -split "\.", 2
        [void]$sb.AppendLine("    ALTER TABLE [$($parts[0])].[$($parts[1])] WITH CHECK CHECK CONSTRAINT ALL;")
    }
    [void]$sb.AppendLine("")
}

# Delete in topological order (children first)
[void]$sb.AppendLine("    -- Delete in dependency order (children first)")
foreach ($tKey in $sortedOrder) {
    $parts = $tKey -split "\.", 2
    [void]$sb.AppendLine("    DELETE FROM [$($parts[0])].[$($parts[1])];")
}
[void]$sb.AppendLine("")

# Reseed identity columns for all clean tables that have them
$allCleanKeys = $sortedOrder + $circularTables
$reseedTables = @()
foreach ($tKey in $allCleanKeys) {
    if ($identityTables.ContainsKey($tKey)) {
        $reseedTables += $tKey
    }
}

if ($reseedTables.Count -gt 0) {
    [void]$sb.AppendLine("    -- Reseed identity columns")
    foreach ($tKey in $reseedTables) {
        $parts = $tKey -split "\.", 2
        [void]$sb.AppendLine("    DBCC CHECKIDENT ('[$($parts[0])].[$($parts[1])]', RESEED, 0);")
    }
    [void]$sb.AppendLine("")
}

[void]$sb.AppendLine("    COMMIT TRANSACTION;")
[void]$sb.AppendLine("    PRINT 'Database reset completed successfully. $($cleanTables.Count) tables cleaned.';")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("END TRY")
[void]$sb.AppendLine("BEGIN CATCH")
[void]$sb.AppendLine("    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;")
[void]$sb.AppendLine("    DECLARE @ErrMsg NVARCHAR(4000) = ERROR_MESSAGE();")
[void]$sb.AppendLine("    DECLARE @ErrSev INT = ERROR_SEVERITY();")
[void]$sb.AppendLine("    DECLARE @ErrState INT = ERROR_STATE();")
[void]$sb.AppendLine("    RAISERROR(@ErrMsg, @ErrSev, @ErrState);")
[void]$sb.AppendLine("END CATCH")

$scriptContent = $sb.ToString()

# --- Write script to file ---

$outputDir = Split-Path -Parent $OutputPath
if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}
Set-Content -Path $OutputPath -Value $scriptContent -Encoding UTF8
Write-Ok "Reset script written to: $OutputPath"

# --- Step 7: Self-test — execute to verify ---

Write-Step "Self-testing reset script against '$DatabaseName'..."

$testResult = sqlcmd -S $ServerInstance -d $DatabaseName -C -i $OutputPath -b 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Self-test failed. Attempting fallback with constraint disabling..."

    # Regenerate with all constraints disabled for safety
    $sb2 = New-Object System.Text.StringBuilder
    [void]$sb2.AppendLine("-- ============================================================")
    [void]$sb2.AppendLine("-- Integration Test Database Reset Script (constraint-safe)")
    [void]$sb2.AppendLine("-- Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    [void]$sb2.AppendLine("-- Database: $DatabaseName")
    [void]$sb2.AppendLine("-- Server: $ServerInstance")
    [void]$sb2.AppendLine("-- Preserved tables (framework/system): $($preserveTables.Count)")
    [void]$sb2.AppendLine("-- Cleaned tables (application data): $($cleanTables.Count)")
    [void]$sb2.AppendLine("-- NOTE: Uses constraint disabling due to complex FK dependencies")
    [void]$sb2.AppendLine("-- ============================================================")
    [void]$sb2.AppendLine("")
    [void]$sb2.AppendLine("SET NOCOUNT ON;")
    [void]$sb2.AppendLine("SET QUOTED_IDENTIFIER ON;")
    [void]$sb2.AppendLine("")
    [void]$sb2.AppendLine("BEGIN TRY")
    [void]$sb2.AppendLine("    BEGIN TRANSACTION;")
    [void]$sb2.AppendLine("")
    [void]$sb2.AppendLine("    -- Disable all FK constraints on application tables")

    $allClean = $sortedOrder + $circularTables
    foreach ($tKey in $allClean) {
        $parts = $tKey -split "\.", 2
        [void]$sb2.AppendLine("    ALTER TABLE [$($parts[0])].[$($parts[1])] NOCHECK CONSTRAINT ALL;")
    }

    [void]$sb2.AppendLine("")
    [void]$sb2.AppendLine("    -- Delete all application data")
    foreach ($tKey in $allClean) {
        $parts = $tKey -split "\.", 2
        [void]$sb2.AppendLine("    DELETE FROM [$($parts[0])].[$($parts[1])];")
    }

    [void]$sb2.AppendLine("")
    [void]$sb2.AppendLine("    -- Re-enable all FK constraints")
    foreach ($tKey in $allClean) {
        $parts = $tKey -split "\.", 2
        [void]$sb2.AppendLine("    ALTER TABLE [$($parts[0])].[$($parts[1])] WITH CHECK CHECK CONSTRAINT ALL;")
    }

    if ($reseedTables.Count -gt 0) {
        [void]$sb2.AppendLine("")
        [void]$sb2.AppendLine("    -- Reseed identity columns")
        foreach ($tKey in $reseedTables) {
            $parts = $tKey -split "\.", 2
            [void]$sb2.AppendLine("    DBCC CHECKIDENT ('[$($parts[0])].[$($parts[1])]', RESEED, 0);")
        }
    }

    [void]$sb2.AppendLine("")
    [void]$sb2.AppendLine("    COMMIT TRANSACTION;")
    [void]$sb2.AppendLine("    PRINT 'Database reset completed successfully. $($cleanTables.Count) tables cleaned.';")
    [void]$sb2.AppendLine("")
    [void]$sb2.AppendLine("END TRY")
    [void]$sb2.AppendLine("BEGIN CATCH")
    [void]$sb2.AppendLine("    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;")
    [void]$sb2.AppendLine("    DECLARE @ErrMsg NVARCHAR(4000) = ERROR_MESSAGE();")
    [void]$sb2.AppendLine("    DECLARE @ErrSev INT = ERROR_SEVERITY();")
    [void]$sb2.AppendLine("    DECLARE @ErrState INT = ERROR_STATE();")
    [void]$sb2.AppendLine("    RAISERROR(@ErrMsg, @ErrSev, @ErrState);")
    [void]$sb2.AppendLine("END CATCH")

    $fallbackContent = $sb2.ToString()
    Set-Content -Path $OutputPath -Value $fallbackContent -Encoding UTF8
    Write-Ok "Regenerated with constraint disabling."

    # Retry self-test
    $testResult2 = sqlcmd -S $ServerInstance -d $DatabaseName -C -i $OutputPath -b 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Self-test still failed after fallback:"
        Write-Err "$testResult2"
        exit 1
    }
}

Write-Ok "Self-test passed."

# Show summary
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Reset script generated successfully!" -ForegroundColor Green
Write-Host "  Database:  $DatabaseName" -ForegroundColor Cyan
Write-Host "  Tables:    $($cleanTables.Count) cleaned, $($preserveTables.Count) preserved" -ForegroundColor Cyan
Write-Host "  File:      $OutputPath" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

exit 0
