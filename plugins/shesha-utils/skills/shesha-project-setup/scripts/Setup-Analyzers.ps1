<#
.SYNOPSIS
    Adds or updates .NET code analyzers in Directory.Build.props.
.DESCRIPTION
    Reads Directory.Build.props as XML, checks for existing analyzer entries,
    looks up latest versions via dotnet package search, adds/updates entries
    with PrivateAssets="all", runs dotnet build to verify.
    Outputs structured JSON for Claude to parse.
.PARAMETER DirectoryBuildPropsPath
    Full path to the Directory.Build.props file.
.PARAMETER SlnPath
    Full path to the .sln file (for build verification).
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$DirectoryBuildPropsPath,

    [Parameter(Mandatory = $true)]
    [string]$SlnPath
)

$ErrorActionPreference = 'Stop'

$analyzers = @(
    @{ Name = 'StyleCop.Analyzers'; FallbackVersion = '1.1.118' },
    @{ Name = 'SonarAnalyzer.CSharp'; FallbackVersion = '10.19.0.132793' },
    @{ Name = 'Microsoft.CodeAnalysis.NetAnalyzers'; FallbackVersion = '8.0.0' }
)

$result = @{
    added     = @()
    updated   = @()
    unchanged = @()
    versions  = @{}
    buildPass = $false
    errors    = @()
}

try {
    # --- Step 1: Resolve latest versions ---
    foreach ($analyzer in $analyzers) {
        $packageName = $analyzer.Name
        $latestVersion = $analyzer.FallbackVersion

        try {
            Write-Host "Looking up latest version of $packageName..."
            $searchOutput = & dotnet package search $packageName --exact-match --format json 2>&1
            $searchExitCode = $LASTEXITCODE

            if ($searchExitCode -eq 0) {
                $searchText = ($searchOutput | ForEach-Object { $_.ToString() }) -join ''
                # Try to parse JSON output
                try {
                    $searchJson = $searchText | ConvertFrom-Json
                    # Navigate the JSON structure to find the version
                    if ($searchJson.searchResult) {
                        foreach ($source in $searchJson.searchResult) {
                            foreach ($pkg in $source.packages) {
                                if ($pkg.id -eq $packageName -and $pkg.latestVersion) {
                                    $latestVersion = $pkg.latestVersion
                                    break
                                }
                            }
                        }
                    }
                }
                catch {
                    # JSON parse failed, try regex on raw output
                    if ($searchText -match '"latestVersion"\s*:\s*"([^"]+)"') {
                        $latestVersion = $Matches[1]
                    }
                }
            }
        }
        catch {
            Write-Host "Warning: Could not look up $packageName, using fallback version $latestVersion"
        }

        $result.versions[$packageName] = $latestVersion
    }

    # --- Step 2: Read/create Directory.Build.props ---
    if (-not (Test-Path $DirectoryBuildPropsPath)) {
        # Create minimal file
        $xmlContent = @"
<Project>
  <ItemGroup>
  </ItemGroup>
</Project>
"@
        Set-Content -Path $DirectoryBuildPropsPath -Value $xmlContent -Encoding UTF8
    }

    [xml]$xml = Get-Content $DirectoryBuildPropsPath -Raw

    # Find or create ItemGroup for analyzers
    $itemGroup = $null
    foreach ($ig in $xml.Project.ItemGroup) {
        # Check if this ItemGroup has PackageReference elements
        $refs = $ig.SelectNodes('PackageReference')
        if ($refs -and $refs.Count -gt 0) {
            $itemGroup = $ig
            break
        }
    }

    if (-not $itemGroup) {
        $itemGroup = $xml.CreateElement('ItemGroup')
        $xml.Project.AppendChild($itemGroup) | Out-Null
    }

    # --- Step 3: Add/update each analyzer ---
    foreach ($analyzer in $analyzers) {
        $packageName = $analyzer.Name
        $targetVersion = $result.versions[$packageName]

        # Check if already exists
        $existingRef = $itemGroup.SelectNodes("PackageReference[@Include='$packageName']")

        if ($existingRef -and $existingRef.Count -gt 0) {
            $existing = $existingRef[0]
            $currentVersion = $existing.GetAttribute('Version')

            if ($currentVersion -eq $targetVersion) {
                $result.unchanged += "$packageName ($currentVersion)"
            }
            else {
                $existing.SetAttribute('Version', $targetVersion)
                if (-not $existing.GetAttribute('PrivateAssets')) {
                    $existing.SetAttribute('PrivateAssets', 'all')
                }
                $result.updated += "$packageName ($currentVersion -> $targetVersion)"
            }
        }
        else {
            $newRef = $xml.CreateElement('PackageReference')
            $newRef.SetAttribute('Include', $packageName)
            $newRef.SetAttribute('Version', $targetVersion)
            $newRef.SetAttribute('PrivateAssets', 'all')
            $itemGroup.AppendChild($newRef) | Out-Null
            $result.added += "$packageName ($targetVersion)"
        }
    }

    # --- Step 4: Save file ---
    $xml.Save($DirectoryBuildPropsPath)
    Write-Host "Updated $DirectoryBuildPropsPath"

    # --- Step 5: Verify build ---
    Write-Host "Verifying build with analyzers..."
    $buildOutput = & dotnet build $SlnPath 2>&1
    $buildExitCode = $LASTEXITCODE

    if ($buildExitCode -eq 0) {
        $result.buildPass = $true
        Write-Host 'Build passed with analyzers.'
    }
    else {
        $result.buildPass = $false
        $lines = ($buildOutput | ForEach-Object { $_.ToString() })
        # Only capture error lines
        $errorLines = $lines | Where-Object { $_ -match '(?i)(error\s+(CS|MSB|NU)\d+)' }
        if ($errorLines.Count -eq 0) {
            if ($lines.Count -gt 20) {
                $errorLines = $lines[($lines.Count - 20)..($lines.Count - 1)]
            }
            else {
                $errorLines = $lines
            }
        }
        $result.errors += "Build failed after adding analyzers"
        $result.errors += ($errorLines -join "`n")
    }

} catch {
    $result.errors += "Unexpected error: $($_.Exception.Message)"
}

$result | ConvertTo-Json -Depth 5
