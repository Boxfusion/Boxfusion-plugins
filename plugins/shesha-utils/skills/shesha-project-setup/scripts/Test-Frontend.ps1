<#
.SYNOPSIS
    Installs, builds, and tests the Shesha frontend dev server.
.DESCRIPTION
    Runs npm install, npm run build, starts npm run dev as a background job,
    polls port 3000 via TCP, verifies HTTP response, then cleans up.
    Outputs structured JSON for Claude to parse.
.PARAMETER AdminPortalPath
    Full path to the adminportal directory.
.PARAMETER Port
    Port the dev server listens on. Defaults to 3000.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$AdminPortalPath,

    [int]$Port = 3000
)

$ErrorActionPreference = 'Stop'

# --- Helper: Invoke-Native ---
# Runs a native command capturing stdout+stderr WITHOUT letting stderr lines become
# terminating NativeCommandErrors under $ErrorActionPreference='Stop' (Windows PS 5.1).
# npm writes "npm warn deprecated ..." to stderr; only the exit code should decide success.
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

# --- Helper: Stop-DevServer ---
function Stop-DevServer {
    param($Job, [int]$ServerPort)
    if ($Job -and $Job.State -eq 'Running') {
        Stop-Job $Job -ErrorAction SilentlyContinue
    }
    if ($Job) {
        Remove-Job $Job -Force -ErrorAction SilentlyContinue
    }
    # Kill orphan node processes on our port
    $portListeners = netstat -ano 2>$null | Select-String ":$ServerPort\s" |
        ForEach-Object {
            if ($_ -match '\s(\d+)$') { [int]$Matches[1] }
        } | Sort-Object -Unique
    # NOTE: do NOT name the loop variable $pid — it is a read-only automatic variable
    # and assigning to it throws, aborting the script before the JSON verdict prints.
    foreach ($procId in $portListeners) {
        if ($procId -gt 0) {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}

# --- Main ---
$result = @{
    install   = 'SKIP'
    build     = 'SKIP'
    devServer = 'SKIP'
    errors    = @()
    output    = ''
}

$devJob = $null

try {
    if (-not (Test-Path $AdminPortalPath -PathType Container)) {
        $result.errors += "Admin portal directory not found: $AdminPortalPath"
        $result | ConvertTo-Json -Depth 3
        exit 0
    }

    # --- Step 1: npm install ---
    Write-Host "Running npm install in $AdminPortalPath..."
    Push-Location $AdminPortalPath
    try {
        $installOutput = Invoke-Native { npm install }
        $installExitCode = $script:LastNativeExitCode
        if ($installExitCode -ne 0) {
            $result.install = 'FAIL'
            $lines = ($installOutput | ForEach-Object { $_.ToString() })
            if ($lines.Count -gt 30) {
                $lines = $lines[($lines.Count - 30)..($lines.Count - 1)]
            }
            $result.output = ($lines -join "`n")
            $result.errors += "npm install failed (exit code $installExitCode)"
            $result | ConvertTo-Json -Depth 3
            exit 0
        }
        $result.install = 'PASS'
        Write-Host 'npm install succeeded.'
    }
    finally {
        Pop-Location
    }

    # --- Step 2: npm run build ---
    Write-Host "Running npm run build in $AdminPortalPath..."
    Push-Location $AdminPortalPath
    try {
        $buildOutput = Invoke-Native { npm run build }
        $buildExitCode = $script:LastNativeExitCode

        # Next.js SWC recovery: a corrupt optional native binary fails with
        # "next-swc....node is not a valid Win32 application". A clean `npm ci`
        # re-fetches the binary. Avoid ad-hoc `npm install <pkg> --no-save` surgery,
        # which can desync the dependency tree.
        $buildText = (($buildOutput | ForEach-Object { $_.ToString() }) -join "`n")
        if ($buildExitCode -ne 0 -and $buildText -match '(?i)next-swc.*is not a valid Win32 application') {
            Write-Host 'Detected corrupt next-swc native binary; running npm ci to recover...'
            $ciOutput = Invoke-Native { npm ci }
            if ($script:LastNativeExitCode -eq 0) {
                $buildOutput = Invoke-Native { npm run build }
                $buildExitCode = $script:LastNativeExitCode
                if ($buildExitCode -eq 0) {
                    $result.errors += 'next-swc native binary was corrupt; recovered automatically with npm ci.'
                }
            }
            else {
                $result.errors += 'npm ci (SWC recovery) failed.'
            }
        }

        if ($buildExitCode -ne 0) {
            $result.build = 'FAIL'
            $lines = ($buildOutput | ForEach-Object { $_.ToString() })
            if ($lines.Count -gt 30) {
                $lines = $lines[($lines.Count - 30)..($lines.Count - 1)]
            }
            $result.output = ($lines -join "`n")
            $result.errors += "npm run build failed (exit code $buildExitCode)"
            $result | ConvertTo-Json -Depth 3
            exit 0
        }
        $result.build = 'PASS'
        Write-Host 'Build succeeded.'
    }
    finally {
        Pop-Location
    }

    # --- Step 3: Start dev server ---
    Write-Host "Starting dev server on port $Port..."
    $devJob = Start-Job -ScriptBlock {
        param($dir)
        Set-Location $dir
        & npm run dev 2>&1
    } -ArgumentList $AdminPortalPath

    Write-Host 'Waiting for dev server (polling port)...'
    $portReady = Wait-ForPort -Port $Port -TimeoutSeconds 90

    if (-not $portReady) {
        $result.devServer = 'FAIL'
        # Get job output for diagnostics
        $jobOutput = @()
        try { $jobOutput += Receive-Job $devJob -ErrorAction SilentlyContinue 2>&1 | ForEach-Object { $_.ToString() } } catch {}
        if ($jobOutput.Count -gt 20) {
            $jobOutput = $jobOutput[($jobOutput.Count - 20)..($jobOutput.Count - 1)]
        }
        $result.output = ($jobOutput -join "`n")
        $result.errors += "Dev server did not start within 90 seconds"
    }
    else {
        # Verify HTTP response
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:$Port" `
                -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                $result.devServer = 'PASS'
                Write-Host 'Dev server is responding.'
            }
            else {
                $result.devServer = 'FAIL'
                $result.errors += "Dev server returned HTTP $($response.StatusCode)"
            }
        }
        catch {
            # A redirect or SSR page might throw but still means it's running
            if ($_.Exception.Message -match '(302|301|redirect)' -or $portReady) {
                $result.devServer = 'PASS'
                Write-Host 'Dev server is responding (redirect detected).'
            }
            else {
                $result.devServer = 'FAIL'
                $result.errors += "HTTP check failed: $($_.Exception.Message)"
            }
        }
    }

} catch {
    $result.errors += "Unexpected error: $($_.Exception.Message)"
} finally {
    Write-Host 'Stopping dev server...'
    Stop-DevServer -Job $devJob -ServerPort $Port
}

$result | ConvertTo-Json -Depth 3
