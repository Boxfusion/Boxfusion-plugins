<#
.SYNOPSIS
    Restores a .bacpac file to SQL Server using sqlpackage.
.DESCRIPTION
    Auto-installs sqlpackage via dotnet tool if missing.
    Uses /TargetTrustServerCertificate:True to avoid SSL errors.
    Runs natively in PowerShell to avoid Git Bash path escaping issues.
.PARAMETER BacpacPath
    Full path to the .bacpac file.
.PARAMETER TargetServer
    SQL Server instance name. Defaults to ".".
.PARAMETER TargetDatabase
    Target database name.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$BacpacPath,

    [string]$TargetServer = '.',

    [Parameter(Mandatory = $true)]
    [string]$TargetDatabase
)

$ErrorActionPreference = 'Stop'

$result = @{
    success             = $false
    sqlpackageInstalled = $false
    message             = ''
    output              = ''
}

try {
    # Check if bacpac file exists
    if (-not (Test-Path $BacpacPath)) {
        $result.message = "Bacpac file not found: $BacpacPath"
        $result | ConvertTo-Json -Depth 3
        exit 0
    }

    # Check if sqlpackage is available
    $sqlpackagePath = $null
    $existing = Get-Command sqlpackage -ErrorAction SilentlyContinue
    if ($existing) {
        $sqlpackagePath = $existing.Source
    }
    else {
        # Try dotnet tool path
        $dotnetToolPath = Join-Path (Join-Path (Join-Path $env:USERPROFILE '.dotnet') 'tools') 'sqlpackage.exe'
        if (Test-Path $dotnetToolPath) {
            $sqlpackagePath = $dotnetToolPath
        }
    }

    # Install if not found
    if (-not $sqlpackagePath) {
        Write-Host 'sqlpackage not found, installing via dotnet tool...'
        $installOutput = & dotnet tool install -g microsoft.sqlpackage 2>&1
        $result.sqlpackageInstalled = $true

        $dotnetToolPath = Join-Path (Join-Path (Join-Path $env:USERPROFILE '.dotnet') 'tools') 'sqlpackage.exe'
        if (Test-Path $dotnetToolPath) {
            $sqlpackagePath = $dotnetToolPath
        }
        else {
            $result.message = "Failed to install sqlpackage: $installOutput"
            $result | ConvertTo-Json -Depth 3
            exit 0
        }
    }

    # Run sqlpackage import
    Write-Host "Restoring $BacpacPath to $TargetServer\$TargetDatabase..."
    $spArgs = @(
        '/Action:Import',
        "/SourceFile:$BacpacPath",
        "/TargetServerName:$TargetServer",
        "/TargetDatabaseName:$TargetDatabase",
        '/TargetTrustServerCertificate:True'
    )

    $proc = Start-Process -FilePath $sqlpackagePath -ArgumentList $spArgs -NoNewWindow -Wait -PassThru -RedirectStandardOutput "$env:TEMP\sqlpackage_out.txt" -RedirectStandardError "$env:TEMP\sqlpackage_err.txt"

    $stdout = ''
    $stderr = ''
    if (Test-Path "$env:TEMP\sqlpackage_out.txt") {
        $stdout = Get-Content "$env:TEMP\sqlpackage_out.txt" -Raw -ErrorAction SilentlyContinue
    }
    if (Test-Path "$env:TEMP\sqlpackage_err.txt") {
        $stderr = Get-Content "$env:TEMP\sqlpackage_err.txt" -Raw -ErrorAction SilentlyContinue
    }

    # Truncate output to last 50 lines
    $allOutput = "$stdout`n$stderr".Trim()
    $lines = $allOutput -split "`n"
    if ($lines.Count -gt 50) {
        $lines = $lines[($lines.Count - 50)..($lines.Count - 1)]
    }
    $result.output = ($lines -join "`n")

    if ($proc.ExitCode -eq 0) {
        $result.success = $true
        $result.message = "Database '$TargetDatabase' restored successfully from bacpac."
    }
    else {
        $result.message = "sqlpackage exited with code $($proc.ExitCode)"
    }

    # Clean up temp files
    Remove-Item "$env:TEMP\sqlpackage_out.txt" -ErrorAction SilentlyContinue
    Remove-Item "$env:TEMP\sqlpackage_err.txt" -ErrorAction SilentlyContinue

} catch {
    $result.message = "Error: $($_.Exception.Message)"
}

$result | ConvertTo-Json -Depth 3
