<#
.SYNOPSIS
    Validates a Shesha project structure and extracts key variables.
.DESCRIPTION
    Finds .sln file, extracts Namespace/ApplicationName/FullNamespace,
    reads appsettings.json for connection string, database name, backend URL/port,
    checks for adminportal/, backend/src/, .bacpac, .backup files.
    Outputs structured JSON for Claude to parse.
.PARAMETER ProjectRoot
    The root directory of the Shesha project. Defaults to current directory.
#>
param(
    [string]$ProjectRoot = (Get-Location).Path
)

$ErrorActionPreference = 'Stop'

$result = @{
    valid                  = $false
    applicationName        = ''
    namespace              = ''
    fullNamespace          = ''
    slnPath                = ''
    bacpacPath             = ''
    backupPath             = ''
    databaseName           = ''
    backendUrl             = ''
    backendPort            = 0
    webHostProject         = ''
    adminPortalPath        = ''
    directoryBuildPropsPath = ''
    dotnetSdks             = @()
    nugetConfigFound       = $false
    nugetConfigPath        = ''
    warnings               = @()
    errors                 = @()
}

try {
    # --- Prerequisite: a .NET SDK must be present ---
    # An in-progress Visual Studio / .NET update can remove the SDK out from under a build,
    # so a "No SDKs were found" failure later is environmental, not a project defect.
    $sdkList = @()
    try {
        $sdkOutput = & dotnet --list-sdks 2>$null
        $sdkList = @($sdkOutput | Where-Object { $_ -and $_.Trim() -ne '' } | ForEach-Object { $_.ToString().Trim() })
    }
    catch {}
    $result.dotnetSdks = $sdkList
    if ($sdkList.Count -eq 0) {
        $result.errors += 'No .NET SDK found (dotnet --list-sdks returned nothing). Install one, e.g. `winget install Microsoft.DotNet.SDK.8`. NOTE: an in-progress VS/.NET update can temporarily remove the SDK.'
    }

    # Find .sln file
    $slnFiles = Get-ChildItem -Path $ProjectRoot -Filter '*.sln' -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '\\(bin|obj|node_modules)\\' }

    if ($slnFiles.Count -eq 0) {
        $result.errors += 'No .sln file found in project'
    }
    elseif ($slnFiles.Count -gt 1) {
        # Pick the one directly under backend/ if possible
        $backendSln = $slnFiles | Where-Object { $_.FullName -match '\\backend\\' } | Select-Object -First 1
        if ($backendSln) {
            $slnFiles = @($backendSln)
        }
        else {
            $slnFiles = @($slnFiles[0])
            $result.errors += "Multiple .sln files found, using: $($slnFiles[0].Name)"
        }
    }

    if ($slnFiles.Count -gt 0) {
        $sln = $slnFiles[0]
        $result.slnPath = $sln.FullName

        # Extract namespace and application name from sln filename
        # Pattern: {Namespace}.{ApplicationName}.sln
        $baseName = [System.IO.Path]::GetFileNameWithoutExtension($sln.Name)
        $parts = $baseName -split '\.'
        if ($parts.Count -ge 2) {
            $result.namespace = $parts[0]
            $result.applicationName = ($parts[1..($parts.Count - 1)] -join '.')
            $result.fullNamespace = $baseName
        }
        else {
            $result.namespace = $baseName
            $result.applicationName = $baseName
            $result.fullNamespace = $baseName
            $result.errors += "Could not parse namespace from sln filename: $baseName"
        }
    }

    # Check adminportal
    $adminPortal = Join-Path $ProjectRoot 'adminportal'
    if (Test-Path $adminPortal -PathType Container) {
        $result.adminPortalPath = $adminPortal
    }
    else {
        $result.errors += 'adminportal/ directory not found'
    }

    # Check backend/src
    $backendSrc = Join-Path (Join-Path $ProjectRoot 'backend') 'src'
    if (-not (Test-Path $backendSrc -PathType Container)) {
        $result.errors += 'backend/src/ directory not found'
    }

    # Find .bacpac file
    $bacpacFiles = Get-ChildItem -Path $ProjectRoot -Filter '*.bacpac' -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($bacpacFiles) {
        $result.bacpacPath = $bacpacFiles.FullName
    }

    # Find .backup file (PostgreSQL)
    $backupFiles = Get-ChildItem -Path $ProjectRoot -Filter '*.backup' -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($backupFiles) {
        $result.backupPath = $backupFiles.FullName
    }

    # Find Web.Host project
    if ($result.fullNamespace) {
        $webHostDir = Join-Path $backendSrc "$($result.fullNamespace).Web.Host"
        if (Test-Path $webHostDir -PathType Container) {
            $result.webHostProject = $webHostDir
        }
        else {
            # Try to find it by pattern
            $webHostDirs = Get-ChildItem -Path $backendSrc -Filter '*.Web.Host' -Directory -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($webHostDirs) {
                $result.webHostProject = $webHostDirs.FullName
            }
            else {
                $result.errors += 'Web.Host project directory not found'
            }
        }
    }

    # Find Directory.Build.props
    $dbpPath = Join-Path (Join-Path $ProjectRoot 'backend') 'Directory.Build.props'
    if (Test-Path $dbpPath) {
        $result.directoryBuildPropsPath = $dbpPath
    }

    # NuGet.Config discoverability check.
    # NuGet walks UP from the project/solution directory. A NuGet.Config that only lives in
    # backend/.nuget/ is NOT on that discovery path (it is not an ancestor of the projects),
    # so its feeds are silently ignored by `dotnet restore`. Confirm a NuGet.Config sits next
    # to the .sln or on an ancestor directory.
    if ($result.slnPath) {
        $dir = Split-Path $result.slnPath -Parent
        $found = $false
        while ($dir -and -not $found) {
            $candidate = Get-ChildItem -Path $dir -Filter 'NuGet.Config' -File -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($candidate) {
                $result.nugetConfigFound = $true
                $result.nugetConfigPath = $candidate.FullName
                $found = $true
                break
            }
            $parent = Split-Path $dir -Parent
            if ($parent -eq $dir) { break }
            $dir = $parent
        }
        if (-not $found) {
            $result.warnings += 'No NuGet.Config found on the restore discovery path (next to the .sln or an ancestor). Feeds defined only in backend/.nuget/NuGet.Config are NOT auto-discovered. The skill should offer to create a NuGet.Config beside the .sln with the Boxfusion feeds.'
        }
    }

    # Flag stray backup/copy .csproj files in the Web.Host project — they can be picked up
    # by mistake during build/run. Suggest deleting them.
    if ($result.webHostProject -and (Test-Path $result.webHostProject)) {
        $strayProjects = Get-ChildItem -Path $result.webHostProject -Filter '*.csproj' -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '(?i)\b(backup|copy)\b' }
        foreach ($stray in $strayProjects) {
            $result.warnings += "Stray project file '$($stray.Name)' in Web.Host; consider deleting it so it is not built/run by mistake."
        }
    }

    # Read appsettings.json
    if ($result.webHostProject) {
        $appSettingsPath = Join-Path $result.webHostProject 'appsettings.json'
        if (Test-Path $appSettingsPath) {
            $appSettings = Get-Content $appSettingsPath -Raw | ConvertFrom-Json

            # Connection string
            $connStr = ''
            if ($appSettings.ConnectionStrings -and $appSettings.ConnectionStrings.Default) {
                $connStr = $appSettings.ConnectionStrings.Default
            }

            # Extract database name from connection string
            if ($connStr) {
                if ($connStr -match 'Initial Catalog\s*=\s*([^;]+)') {
                    $result.databaseName = $Matches[1].Trim()
                }
                elseif ($connStr -match 'Database\s*=\s*([^;]+)') {
                    $result.databaseName = $Matches[1].Trim()
                }
            }

            # Backend URL
            if ($appSettings.App -and $appSettings.App.ServerRootAddress) {
                $result.backendUrl = $appSettings.App.ServerRootAddress
                if ($result.backendUrl -match ':(\d+)$') {
                    $result.backendPort = [int]$Matches[1]
                }
                elseif ($result.backendUrl -match ':(\d+)/') {
                    $result.backendPort = [int]$Matches[1]
                }
            }
        }
        else {
            $result.errors += 'appsettings.json not found in Web.Host project'
        }
    }

    # Determine validity
    $criticalErrors = $result.errors | Where-Object {
        $_ -match 'No .sln' -or $_ -match 'backend/src/' -or $_ -match 'Web.Host project' -or $_ -match 'No .NET SDK'
    }
    $result.valid = ($criticalErrors.Count -eq 0 -and $result.fullNamespace -ne '')

} catch {
    $result.errors += "Unexpected error: $($_.Exception.Message)"
}

$result | ConvertTo-Json -Depth 5
