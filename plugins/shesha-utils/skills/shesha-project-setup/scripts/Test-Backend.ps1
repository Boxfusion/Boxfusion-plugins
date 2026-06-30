<#
.SYNOPSIS
    Builds, starts, and tests the Shesha backend server.
.DESCRIPTION
    Builds the solution, starts the server with --urls flag, uses TCP port polling
    instead of blind sleeps, proactively checks the database exists (and restores
    from a .bacpac before the first start if it is missing), also detects DB errors
    after start / on an auth-500 and auto-restores, tests authentication with a
    credential cascade, then cleans up.
    Outputs structured JSON for Claude to parse.
.PARAMETER SlnPath
    Full path to the .sln file.
.PARAMETER WebHostProject
    Full path to the Web.Host project directory.
.PARAMETER BackendPort
    Port the backend listens on. Defaults to 21021.
.PARAMETER Username
    Login username. Defaults to 'admin'.
.PARAMETER Password
    Login password. Defaults to '123qwe'.
.PARAMETER BacpacPath
    Optional path to .bacpac file for database restore.
.PARAMETER DatabaseName
    Database name for restore operations.
.PARAMETER ScriptsDir
    Path to the scripts directory (for calling Restore-Database.ps1).
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$SlnPath,

    [Parameter(Mandatory = $true)]
    [string]$WebHostProject,

    [int]$BackendPort = 21021,

    [string]$Username = 'admin',

    [string]$Password = '123qwe',

    [string]$BacpacPath = '',

    [string]$DatabaseName = '',

    [string]$ScriptsDir = ''
)

$ErrorActionPreference = 'Stop'

# --- Helper: Invoke-Native ---
# Runs a native command capturing stdout+stderr WITHOUT letting stderr lines become
# terminating NativeCommandErrors under $ErrorActionPreference='Stop' (Windows PS 5.1).
# Only the exit code decides success. Returns the captured output lines.
function Invoke-Native {
    param([scriptblock]$Command)
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $Command 2>&1
        $script:LastNativeExitCode = $LASTEXITCODE
        return $out
    }
    finally {
        $ErrorActionPreference = $prevEAP
    }
}

# --- Helper: Wait-ForPort ---
function Wait-ForPort {
    param(
        [int]$Port,
        [int]$TimeoutSeconds = 120,
        [int]$IntervalSeconds = 2
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect('127.0.0.1', $Port)
            $tcp.Close()
            return $true
        }
        catch {
            Start-Sleep -Seconds $IntervalSeconds
        }
    }
    return $false
}

# --- Helper: Stop-ServerJob ---
function Stop-ServerJob {
    param($Job)
    if ($Job -and $Job.State -eq 'Running') {
        Stop-Job $Job -ErrorAction SilentlyContinue
    }
    if ($Job) {
        Remove-Job $Job -Force -ErrorAction SilentlyContinue
    }
    # Kill any orphan dotnet processes on our port.
    # NOTE: do NOT name the loop variable $pid — it is a read-only automatic variable
    # and assigning to it throws, aborting the script before the JSON verdict prints.
    $portListeners = netstat -ano 2>$null | Select-String ":$BackendPort\s" |
        ForEach-Object {
            if ($_ -match '\s(\d+)$') { [int]$Matches[1] }
        } | Sort-Object -Unique
    foreach ($procId in $portListeners) {
        if ($procId -gt 0) {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}

# --- Helper: Get-JobOutput ---
function Get-JobOutput {
    param($Job, [int]$TailLines = 30)
    $output = @()
    if ($Job) {
        try { $output += Receive-Job $Job -ErrorAction SilentlyContinue 2>&1 | ForEach-Object { $_.ToString() } } catch {}
    }
    if ($output.Count -gt $TailLines) {
        $output = $output[($output.Count - $TailLines)..($output.Count - 1)]
    }
    return ($output -join "`n")
}

# --- Helper: Test-DatabaseExists ---
# Returns $true / $false when sqlcmd can answer, or $null when it cannot be determined
# (e.g. sqlcmd not installed). Only an explicit $false should trigger a proactive restore.
function Test-DatabaseExists {
    param([string]$DatabaseName, [string]$Server = '.')
    $sqlcmd = Get-Command sqlcmd -ErrorAction SilentlyContinue
    if (-not $sqlcmd) { return $null }
    try {
        $out = Invoke-Native { sqlcmd -S $Server -E -C -h -1 -Q "SET NOCOUNT ON; SELECT CASE WHEN DB_ID('$DatabaseName') IS NULL THEN 0 ELSE 1 END" }
        $val = (($out | ForEach-Object { $_.ToString().Trim() }) -join '').Trim()
        if ($val -match '1') { return $true }
        if ($val -match '0') { return $false }
        return $null
    }
    catch { return $null }
}

# --- Helper: Invoke-BacpacRestore ---
function Invoke-BacpacRestore {
    param([string]$BacpacPath, [string]$DatabaseName, [string]$ScriptsDir)
    $restoreScript = Join-Path $ScriptsDir 'Restore-Database.ps1'
    if (-not (Test-Path $restoreScript)) {
        return @{ success = $false; message = 'Restore-Database.ps1 not found, cannot auto-restore' }
    }
    # Always invoke sqlpackage via PowerShell (Restore-Database.ps1), never Git Bash,
    # so /Action:Import style switches are not mangled.
    $restoreOutput = & powershell -NoProfile -ExecutionPolicy Bypass -File $restoreScript `
        -BacpacPath $BacpacPath `
        -TargetDatabase $DatabaseName 2>&1
    try {
        return (($restoreOutput | ForEach-Object { $_.ToString() }) -join '' | ConvertFrom-Json)
    }
    catch {
        return @{ success = $false; message = "Could not parse restore output" }
    }
}

# --- Helper: Test-Authentication ---
function Test-Authentication {
    param(
        [string]$Url,
        [string]$User,
        [string]$Pass
    )
    try {
        $body = @{
            userNameOrEmailAddress = $User
            password               = $Pass
        } | ConvertTo-Json

        $response = Invoke-WebRequest -Uri "$Url/api/TokenAuth/Authenticate" `
            -Method POST `
            -ContentType 'application/json' `
            -Body $body `
            -UseBasicParsing `
            -TimeoutSec 15 `
            -ErrorAction Stop

        $data = $response.Content | ConvertFrom-Json
        if ($data.success -or $data.result) {
            return @{ success = $true; message = 'Authentication successful' }
        }
        return @{ success = $false; message = "Unexpected response: $($response.StatusCode)" }
    }
    catch {
        $statusCode = 0
        if ($_.Exception.Response) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }
        return @{
            success = $false
            message = "Auth failed (HTTP $statusCode): $($_.Exception.Message)"
        }
    }
}

# --- Helper: Invoke-AuthWithCascade ---
# Tries the provided credentials, then falls back to admin/123qwe. Updates $Result.credentials
# in place (hashtables are passed by reference) when the default fallback succeeds.
function Invoke-AuthWithCascade {
    param([string]$Url, [string]$User, [string]$Pass, $Result)
    $authResult = Test-Authentication -Url $Url -User $User -Pass $Pass
    if (-not $authResult.success) {
        if ($User -ne 'admin' -or $Pass -ne '123qwe') {
            $defaultAuth = Test-Authentication -Url $Url -User 'admin' -Pass '123qwe'
            if ($defaultAuth.success) {
                $authResult = $defaultAuth
                $Result.credentials = @{
                    username = 'admin'
                    password = '123qwe'
                    source   = 'default'
                }
            }
        }
    }
    return $authResult
}

# --- Helper: Start-WebHost ---
function Start-WebHost {
    param([string]$ProjectArg, [int]$Port)
    return Start-Job -ScriptBlock {
        param($proj, $port)
        Set-Location (Split-Path $proj -Parent)
        & dotnet run --project $proj --urls "http://localhost:$port" --no-build 2>&1
    } -ArgumentList $ProjectArg, $Port
}

# --- Main ---
$result = @{
    build             = 'SKIP'
    server            = 'SKIP'
    auth              = 'SKIP'
    credentials       = @{
        username = $Username
        password = $Password
        source   = 'provided'
    }
    databaseRestored  = $false
    serverOutput      = ''
    errors            = @()
}

$serverJob = $null
$backendUrl = "http://localhost:$BackendPort"
$dbErrorRegex = '(?i)(cannot open database|login failed|connection.*refused|Initial Catalog|network-related|Invalid object name|database .* does not exist)'

try {
    # --- Step 1: Build ---
    Write-Host "Building solution: $SlnPath"
    $buildOutput = Invoke-Native { dotnet build $SlnPath }
    $buildExitCode = $script:LastNativeExitCode
    $buildLines = ($buildOutput | ForEach-Object { $_.ToString() })

    if ($buildExitCode -ne 0) {
        $result.build = 'FAIL'
        $buildText = ($buildLines -join "`n")
        # Capture last 30 lines
        if ($buildLines.Count -gt 30) {
            $buildLines = $buildLines[($buildLines.Count - 30)..($buildLines.Count - 1)]
        }
        $result.errors += "Build failed (exit code $buildExitCode)"
        # Stale/truncated packages.lock.json is a common cause of NU1101 for packages
        # that genuinely exist on the feed. Surface an actionable hint.
        if ($buildText -match 'NU1101') {
            $result.errors += "NU1101 detected. If a feed is configured this can be a stale packages.lock.json or a missing feed credential. Try: (1) authenticate to the Boxfusion feeds (see the feed-auth phase), (2) 'git checkout -- **/packages.lock.json' if the lock file is dirty, or (3) 'dotnet restore $SlnPath --force-evaluate'."
        }
        $result.serverOutput = ($buildLines -join "`n")
        $result | ConvertTo-Json -Depth 5
        exit 0
    }
    $result.build = 'PASS'
    Write-Host 'Build succeeded.'

    # --- Step 2: Resolve the Web.Host project ---
    # Prefer the real *.Web.Host.csproj and exclude backup/copy artefacts so an alphabetically
    # first "App - Backup.Web.Host.csproj" is not picked by mistake.
    $candidates = Get-ChildItem -Path $WebHostProject -Filter '*.csproj' |
        Where-Object { $_.Name -notmatch '(?i)\b(backup|copy)\b' }
    $webHostCsproj = $candidates | Where-Object { $_.Name -match '(?i)Web\.Host\.csproj$' } | Select-Object -First 1
    if (-not $webHostCsproj) { $webHostCsproj = $candidates | Select-Object -First 1 }
    if (($candidates | Measure-Object).Count -gt 1 -and $webHostCsproj) {
        Write-Host "WARNING: multiple .csproj in Web.Host; chose $($webHostCsproj.Name)"
    }
    $projectArg = if ($webHostCsproj) { $webHostCsproj.FullName } else { $WebHostProject }

    # --- Step 2.5: Proactive database check ---
    # Kestrel binds the port before ABP initialises, so a missing catalog still reports the
    # port as "ready" and the reactive (-not portReady) restore never fires. Check first.
    if ($DatabaseName) {
        $dbExists = Test-DatabaseExists -DatabaseName $DatabaseName -Server '.'
        if ($dbExists -eq $false) {
            if ($BacpacPath -and (Test-Path $BacpacPath)) {
                Write-Host "Database '$DatabaseName' is missing; restoring from bacpac before first start..."
                $restoreResult = Invoke-BacpacRestore -BacpacPath $BacpacPath -DatabaseName $DatabaseName -ScriptsDir $ScriptsDir
                if ($restoreResult.success) {
                    $result.databaseRestored = $true
                    Write-Host 'Database restored.'
                }
                else {
                    $result.errors += "Proactive database restore failed: $($restoreResult.message)"
                }
            }
            else {
                $result.errors += "Database '$DatabaseName' is missing and no .bacpac is available to restore it."
            }
        }
    }

    # --- Step 3: Start server ---
    Write-Host "Starting backend server on port $BackendPort..."
    $serverJob = Start-WebHost -ProjectArg $projectArg -Port $BackendPort

    Write-Host 'Waiting for server to start (polling port)...'
    $portReady = Wait-ForPort -Port $BackendPort -TimeoutSeconds 120

    if (-not $portReady) {
        $result.server = 'FAIL'
        $result.serverOutput = Get-JobOutput -Job $serverJob -TailLines 30
        $result.errors += 'Server did not start within 120 seconds'

        # Check for database errors (reactive restore for the connection-refused style failure)
        $isDbError = $result.serverOutput -match $dbErrorRegex

        if ($isDbError -and $BacpacPath -and $DatabaseName -and -not $result.databaseRestored) {
            Write-Host 'Detected database error, attempting restore...'
            Stop-ServerJob -Job $serverJob
            $serverJob = $null

            $restoreResult = Invoke-BacpacRestore -BacpacPath $BacpacPath -DatabaseName $DatabaseName -ScriptsDir $ScriptsDir
            if ($restoreResult.success) {
                $result.databaseRestored = $true
                Write-Host 'Database restored, restarting server...'
                $serverJob = Start-WebHost -ProjectArg $projectArg -Port $BackendPort
                $portReady = Wait-ForPort -Port $BackendPort -TimeoutSeconds 120
                if ($portReady) {
                    $result.server = 'PASS'
                    $result.errors = @($result.errors | Where-Object { $_ -notmatch 'did not start' })
                }
                else {
                    $result.serverOutput = Get-JobOutput -Job $serverJob -TailLines 30
                    $result.errors += 'Server failed to start after database restore'
                }
            }
            else {
                $result.errors += "Database restore failed: $($restoreResult.message)"
            }
        }

        if ($result.server -ne 'PASS') {
            $result | ConvertTo-Json -Depth 5
            Stop-ServerJob -Job $serverJob
            exit 0
        }
    }
    else {
        $result.server = 'PASS'
        Write-Host 'Server is listening.'
    }

    # --- Step 4: Authentication ---
    Write-Host "Testing authentication as '$Username'..."
    $authResult = Invoke-AuthWithCascade -Url $backendUrl -User $Username -Pass $Password -Result $result

    # Defence in depth: the server may bind the port and then fail ABP init because the DB is
    # missing, so auth returns HTTP 500. Treat 500 + a DB error signature in the log as a
    # restore trigger, then restart and retry auth.
    if (-not $authResult.success -and -not $result.databaseRestored -and $BacpacPath -and (Test-Path $BacpacPath) -and $DatabaseName) {
        $logSoFar = Get-JobOutput -Job $serverJob -TailLines 60
        if (($authResult.message -match 'HTTP 500') -and ($logSoFar -match $dbErrorRegex)) {
            Write-Host 'Auth returned HTTP 500 with a DB error signature; restoring database and retrying...'
            Stop-ServerJob -Job $serverJob
            $serverJob = $null
            $restoreResult = Invoke-BacpacRestore -BacpacPath $BacpacPath -DatabaseName $DatabaseName -ScriptsDir $ScriptsDir
            if ($restoreResult.success) {
                $result.databaseRestored = $true
                $serverJob = Start-WebHost -ProjectArg $projectArg -Port $BackendPort
                $portReady = Wait-ForPort -Port $BackendPort -TimeoutSeconds 120
                if ($portReady) {
                    $authResult = Invoke-AuthWithCascade -Url $backendUrl -User $Username -Pass $Password -Result $result
                }
                else {
                    $result.errors += 'Server failed to start after database restore'
                }
            }
            else {
                $result.errors += "Database restore failed: $($restoreResult.message)"
            }
        }
    }

    if ($authResult.success) {
        $result.auth = 'PASS'
        Write-Host 'Authentication successful.'
    }
    else {
        $result.auth = 'FAIL'
        $result.errors += $authResult.message
    }

    $result.serverOutput = Get-JobOutput -Job $serverJob -TailLines 15

} catch {
    $result.errors += "Unexpected error: $($_.Exception.Message)"
} finally {
    # --- Cleanup ---
    Write-Host 'Stopping server...'
    Stop-ServerJob -Job $serverJob
}

$result | ConvertTo-Json -Depth 5
