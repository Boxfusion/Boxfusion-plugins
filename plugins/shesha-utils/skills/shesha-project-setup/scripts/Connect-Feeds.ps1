<#
.SYNOPSIS
    Authenticates to the Boxfusion private Azure DevOps NuGet and npm feeds.
.DESCRIPTION
    Every Boxfusion developer needs authenticated access to the private feeds
    (nuget.shesha.dev, nuget.boxfusion.co.za, npm.shesha.dev). This helper:
      - installs the Azure Artifacts credential provider (idempotent),
      - optionally wires a PAT for headless / agent-driven auth (NuGet env endpoints + npm ~/.npmrc),
      - verifies auth before the build/test phases (dotnet restore exit code, npm whoami).

    Interactive browser/device login (`dotnet restore <sln> --interactive` or `az login`)
    CANNOT be completed by an agent — it only surfaces in the developer's own terminal.
    For that path, the developer should run the command via the `!` prefix in-session.

    SECURITY: if a PAT is passed here it may be retained in the agent transcript and is
    written (base64) into the user ~/.npmrc. Use a short-expiry PAT (Packaging: Read) and
    revoke it afterward.
.PARAMETER SlnPath
    Full path to the .sln file (used to verify a NuGet restore succeeds).
.PARAMETER AdminPortalPath
    Full path to the adminportal directory (used to verify npm auth).
.PARAMETER Pat
    Optional Azure DevOps PAT (Packaging: Read) for headless auth. If omitted, the script
    only installs the credential provider and verifies the current cached credentials.
.PARAMETER InstallCredProvider
    Force (re)installation of the Azure Artifacts credential provider.
.PARAMETER SkipVerify
    Skip the verification restore / npm whoami (just wire credentials).
#>
param(
    [string]$SlnPath = '',
    [string]$AdminPortalPath = '',
    [string]$Pat = '',
    [switch]$InstallCredProvider,
    [switch]$SkipVerify
)

$ErrorActionPreference = 'Stop'

$nugetShesha    = 'https://pkgs.dev.azure.com/boxfusion/_packaging/nuget.shesha.dev/nuget/v3/index.json'
$nugetBoxfusion = 'https://pkgs.dev.azure.com/boxfusion/_packaging/nuget.boxfusion.co.za/nuget/v3/index.json'
$npmRegistry    = 'https://pkgs.dev.azure.com/boxfusion/_packaging/npm.shesha.dev/npm/registry/'

$result = @{
    credProviderInstalled = $false
    patWired              = $false
    nugetRestore          = 'SKIP'
    npmAuth               = 'SKIP'
    messages              = @()
    errors                = @()
}

# --- Helper: Invoke-Native (exit code decides success, stderr is not fatal) ---
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

try {
    # --- Step 1: Credential provider (idempotent) ---
    $credProviderDir = Join-Path $env:USERPROFILE '.nuget\plugins'
    $alreadyInstalled = Test-Path $credProviderDir
    if ($InstallCredProvider -or -not $alreadyInstalled) {
        Write-Host 'Installing Azure Artifacts credential provider...'
        try {
            iex "& { $(irm https://aka.ms/install-artifacts-credprovider.ps1) }"
            $result.credProviderInstalled = $true
        }
        catch {
            $result.errors += "Credential provider install failed: $($_.Exception.Message)"
        }
    }
    else {
        $result.messages += 'Azure Artifacts credential provider already present.'
    }

    # --- Step 2: Wire PAT (optional, for headless / agent-driven auth) ---
    if ($Pat) {
        # NuGet: VSS_NUGET_EXTERNAL_FEED_ENDPOINTS is consumed by the credential provider
        # in this process (and child processes), so the verification restore below picks it up.
        $endpoints = @{
            endpointCredentials = @(
                @{ endpoint = $nugetShesha;    username = 'build'; password = $Pat },
                @{ endpoint = $nugetBoxfusion; username = 'build'; password = $Pat }
            )
        } | ConvertTo-Json -Compress -Depth 5
        $env:VSS_NUGET_EXTERNAL_FEED_ENDPOINTS = $endpoints

        # npm: write base64(PAT) into the user ~/.npmrc for BOTH registry path variants.
        $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Pat))
        $npmrcPath = Join-Path $env:USERPROFILE '.npmrc'
        $existing = ''
        if (Test-Path $npmrcPath) { $existing = Get-Content $npmrcPath -Raw }
        $lines = @(
            '//pkgs.dev.azure.com/boxfusion/_packaging/npm.shesha.dev/npm/registry/:username=VssSessionToken',
            "//pkgs.dev.azure.com/boxfusion/_packaging/npm.shesha.dev/npm/registry/:_password=$b64",
            '//pkgs.dev.azure.com/boxfusion/_packaging/npm.shesha.dev/npm/registry/:email=not-used@example.com',
            '//pkgs.dev.azure.com/boxfusion/_packaging/npm.shesha.dev/npm/:username=VssSessionToken',
            "//pkgs.dev.azure.com/boxfusion/_packaging/npm.shesha.dev/npm/:_password=$b64",
            '//pkgs.dev.azure.com/boxfusion/_packaging/npm.shesha.dev/npm/:email=not-used@example.com'
        )
        # Drop any prior entries for these keys, then append the fresh ones.
        $kept = @()
        if ($existing) {
            $kept = $existing -split "`r?`n" | Where-Object {
                $_ -and ($_ -notmatch 'npm\.shesha\.dev/npm')
            }
        }
        $newContent = (@($kept) + $lines | Where-Object { $_ -ne $null }) -join [Environment]::NewLine
        Set-Content -Path $npmrcPath -Value $newContent -Encoding UTF8
        $result.patWired = $true
        $result.messages += 'PAT wired (NuGet endpoint env var for this process + user ~/.npmrc). Remember to revoke the PAT afterward.'
    }

    # --- Step 3: Verify ---
    if (-not $SkipVerify) {
        if ($SlnPath -and (Test-Path $SlnPath)) {
            Write-Host 'Verifying NuGet auth via dotnet restore...'
            $restoreOut = Invoke-Native { dotnet restore $SlnPath }
            if ($script:LastNativeExitCode -eq 0) {
                $result.nugetRestore = 'PASS'
            }
            else {
                $result.nugetRestore = 'FAIL'
                $text = (($restoreOut | ForEach-Object { $_.ToString() }) -join "`n")
                if ($text -match '401') {
                    $result.errors += 'NuGet restore returned 401 (unauthorized). Authenticate to the Boxfusion feeds before building: run `dotnet restore <sln> --interactive` via the ! prefix, or pass a PAT to this script.'
                }
                elseif ($text -match 'NU1101') {
                    $result.errors += 'NuGet restore failed with NU1101. Check feed configuration (NuGet.Config on the discovery path) and/or a stale packages.lock.json.'
                }
                else {
                    $result.errors += 'NuGet restore failed. See output for details.'
                }
            }
        }

        if ($AdminPortalPath -and (Test-Path $AdminPortalPath)) {
            Write-Host 'Verifying npm auth via npm whoami...'
            $whoami = Invoke-Native { npm whoami --registry=$npmRegistry }
            if ($script:LastNativeExitCode -eq 0) {
                $result.npmAuth = 'PASS'
            }
            else {
                $result.npmAuth = 'FAIL'
                $result.errors += "npm auth failed (E401 likely). Refresh via 'npx vsts-npm-auth -config adminportal/.npmrc' or pass a PAT to this script."
            }
        }
    }
}
catch {
    $result.errors += "Unexpected error: $($_.Exception.Message)"
}

$result | ConvertTo-Json -Depth 5
