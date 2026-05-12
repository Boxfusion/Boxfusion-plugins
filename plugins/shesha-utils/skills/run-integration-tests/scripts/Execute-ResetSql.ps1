param(
    [Parameter(Mandatory=$true)]
    [string]$SqlFilePath,

    [Parameter(Mandatory=$true)]
    [string]$ServerInstance,

    [Parameter(Mandatory=$true)]
    [string]$DatabaseName
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

# --- Validation ---

Write-Step "Validating inputs..."

# Check sqlcmd is available
$sqlcmdCmd = Get-Command sqlcmd -ErrorAction SilentlyContinue
if (-not $sqlcmdCmd) {
    Write-Err "sqlcmd not found. Ensure SQL Server command-line tools are installed."
    Write-Err "Install via: winget install Microsoft.SqlServer.SqlCmd"
    exit 1
}

# Check SQL file exists
if (-not (Test-Path $SqlFilePath)) {
    Write-Err "Reset SQL file not found: $SqlFilePath"
    exit 1
}

Write-Ok "SQL file: $SqlFilePath"
Write-Ok "Server: $ServerInstance"
Write-Ok "Database: $DatabaseName"

# Verify database exists
$query = "SELECT CASE WHEN DB_ID(N'`$(DbName)') IS NOT NULL THEN 'YES' ELSE 'NO' END"
$result = sqlcmd -S $ServerInstance -C -Q $query -h -1 -W -v DbName="$DatabaseName" 2>$null
if (-not ($result -and ($result.Trim() -eq "YES"))) {
    Write-Err "Database '$DatabaseName' does not exist on server '$ServerInstance'."
    exit 1
}
Write-Ok "Database '$DatabaseName' found."

# --- Execute reset ---

Write-Step "Executing database reset on '$DatabaseName'..."
Write-Ok "Started at $(Get-Date -Format 'HH:mm:ss')"

$startTime = Get-Date

$output = sqlcmd -S $ServerInstance -d $DatabaseName -C -i $SqlFilePath -b 2>&1

$elapsed = (Get-Date) - $startTime

if ($LASTEXITCODE -ne 0) {
    Write-Err "Database reset failed (exit code $LASTEXITCODE)."
    Write-Err "Output: $output"
    exit 1
}

Write-Ok "Completed at $(Get-Date -Format 'HH:mm:ss') (took $([math]::Round($elapsed.TotalSeconds, 1))s)"

# Show summary
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Database reset successfully!" -ForegroundColor Green
Write-Host "  Server:   $ServerInstance" -ForegroundColor Cyan
Write-Host "  Database: $DatabaseName" -ForegroundColor Cyan
Write-Host "  Duration: $([math]::Round($elapsed.TotalSeconds, 1)) seconds" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

exit 0
