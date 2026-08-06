<#
.SYNOPSIS
  Scans a repo for Shesha modules, looks up their published NuGet/npm packages
  (full version + dependency history) on the private Boxfusion Azure Artifacts
  feed, and upserts them into the Module Registry via the ModuleInfoSearch API.

.PARAMETER RepoPath
  Path to the repository to scan.

.PARAMETER BackendUrl
  Base URL of the Shesha.ModuleRegistry backend to sync into. No default - the
  caller must always supply the target environment explicitly.

.PARAMETER Username
.PARAMETER Password
  Admin credentials used to authenticate against the backend. No defaults - the
  caller must always supply real credentials for the target environment.

.PARAMETER NugetFeedUrl
  NuGet v3 service index URL of the private feed.

.PARAMETER NpmRegistryUrl
  npm registry URL of the private feed.

.PARAMETER FeedPat
  Personal Access Token for the Azure DevOps organization that hosts the feed.
  Falls back to the $env:SHESHA_FEED_PAT environment variable if not supplied -
  prefer that over passing it on the command line so it doesn't end up in shell
  history. Never hardcode this value in the script.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    [Parameter(Mandatory = $true)]
    [string]$BackendUrl,

    [Parameter(Mandatory = $true)]
    [string]$Username,

    [Parameter(Mandatory = $true)]
    [string]$Password,

    [string]$NugetFeedUrl = "https://pkgs.dev.azure.com/boxfusion/_packaging/nuget.shesha.dev/nuget/v3/index.json",
    [string]$NpmRegistryUrl = "https://pkgs.dev.azure.com/boxfusion/_packaging/npm.shesha.dev/npm/registry/",
    [string]$FeedPat = $env:SHESHA_FEED_PAT
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

if (-not $FeedPat) {
    throw "No Personal Access Token supplied. Pass -FeedPat or set the SHESHA_FEED_PAT environment variable."
}

$feedAuthValue = [Convert]::ToBase64String([System.Text.Encoding]::ASCII.GetBytes(":$FeedPat"))
$feedHeaders = @{ Authorization = "Basic $feedAuthValue" }

$KnownSuffixes = @(
    "Common\.Domain\.Tests", "Domain\.Tests", "Application\.Tests",
    "Web\.Core", "Web\.Host", "Application", "Domain", "Tests"
)

function Get-NormalizedName {
    param([string]$Name)
    if (-not $Name) { return "" }
    return ($Name -replace '[^a-zA-Z0-9]', '').ToLowerInvariant()
}

function Test-IsOwnModule {
    param([string]$Name)
    if (-not $Name) { return $false }
    $lower = $Name.ToLowerInvariant()
    return $lower.StartsWith("shesha") -or $lower.StartsWith("boxfusion") -or $lower.StartsWith("@shesha-io/")
}

function Get-ModuleBaseName {
    param([string]$RawName)
    $name = $RawName
    $changed = $true
    while ($changed) {
        $changed = $false
        foreach ($suffix in $KnownSuffixes) {
            $pattern = "\.($suffix)$"
            if ($name -match $pattern) {
                $name = $name -replace $pattern, ''
                $changed = $true
            }
        }
    }
    return $name
}

function Invoke-JsonGet {
    param([string]$Url, [hashtable]$Headers = @{})
    try {
        return Invoke-RestMethod -Uri $Url -Method Get -Headers $Headers -ErrorAction Stop
    } catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) {
            return $null
        }
        Write-Warning "GET $Url failed: $($_.Exception.Message) (retrying once)"
        Start-Sleep -Seconds 1
        try {
            return Invoke-RestMethod -Uri $Url -Method Get -Headers $Headers -ErrorAction Stop
        } catch {
            Write-Warning "GET $Url failed again, skipping: $($_.Exception.Message)"
            return $null
        }
    }
}

function Clean-VersionRange {
    param($Range)
    if (-not $Range) { return "" }
    try {
        $v = [string]$Range -replace '[\[\]\(\)]', ''
        $v = ($v -split ',')[0].Trim()
        return $v
    } catch {
        return [string]$Range
    }
}

# ---------------------------------------------------------------------------
# Step 1: Discover modules in the repo
# ---------------------------------------------------------------------------

Write-Host "Scanning $RepoPath for modules..." -ForegroundColor Cyan

$csprojFiles = Get-ChildItem -Path $RepoPath -Recurse -Filter "*.csproj" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\(bin|obj|node_modules)\\' }

$modules = @{}  # moduleName -> @{ NugetCandidateIds = [string[]]; NpmPackage = $null; SkillName=$null; SkillLocation=$null }

foreach ($csproj in $csprojFiles) {
    $rawName = [System.IO.Path]::GetFileNameWithoutExtension($csproj.Name)
    $packageId = $rawName
    try {
        [xml]$xml = Get-Content -Path $csproj.FullName -Raw
        $pkgIdNode = $xml.SelectSingleNode("//PackageId")
        if ($pkgIdNode -and $pkgIdNode.InnerText.Trim()) {
            $packageId = $pkgIdNode.InnerText.Trim()
        }
    } catch {
        Write-Warning "Could not parse $($csproj.FullName): $($_.Exception.Message)"
    }

    $moduleName = Get-ModuleBaseName -RawName $rawName

    if (-not $modules.ContainsKey($moduleName)) {
        $modules[$moduleName] = [ordered]@{
            NugetCandidateIds = New-Object System.Collections.Generic.List[string]
            NpmPackage        = $null
            SkillName         = $null
            SkillLocation     = $null
        }
    }
    if (-not $modules[$moduleName].NugetCandidateIds.Contains($packageId)) {
        $modules[$moduleName].NugetCandidateIds.Add($packageId)
    }
    if (-not $modules[$moduleName].NugetCandidateIds.Contains($moduleName)) {
        $modules[$moduleName].NugetCandidateIds.Insert(0, $moduleName)
    }
}

$packageJsonFiles = Get-ChildItem -Path $RepoPath -Recurse -Filter "package.json" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\node_modules\\' }

foreach ($pkgFile in $packageJsonFiles) {
    try {
        $pkgJson = Get-Content -Path $pkgFile.FullName -Raw | ConvertFrom-Json
    } catch {
        continue
    }
    if (-not $pkgJson.name) { continue }
    $npmName = $pkgJson.name
    $normalizedNpm = Get-NormalizedName -Name ($npmName -replace '^@[^/]+/', '')

    $matchedModule = $null
    foreach ($key in $modules.Keys) {
        $normalizedModule = Get-NormalizedName -Name $key
        if ($normalizedModule -and $normalizedNpm -and
            ($normalizedModule.Contains($normalizedNpm) -or $normalizedNpm.Contains($normalizedModule))) {
            $matchedModule = $key
            break
        }
    }

    if ($matchedModule) {
        $modules[$matchedModule].NpmPackage = $npmName
    } elseif (-not $modules.ContainsKey($npmName)) {
        $modules[$npmName] = [ordered]@{
            NugetCandidateIds = New-Object System.Collections.Generic.List[string]
            NpmPackage        = $npmName
            SkillName         = $null
            SkillLocation     = $null
        }
    }
}

$skillFiles = Get-ChildItem -Path $RepoPath -Recurse -Filter "SKILL.md" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\node_modules\\' }

foreach ($key in @($modules.Keys)) {
    $normalizedModule = Get-NormalizedName -Name $key
    foreach ($skillFile in $skillFiles) {
        $skillFolderName = $skillFile.Directory.Name
        $normalizedSkill = Get-NormalizedName -Name $skillFolderName
        if ($normalizedSkill -and $normalizedModule -and
            ($normalizedSkill.Contains($normalizedModule) -or $normalizedModule.Contains($normalizedSkill))) {
            $modules[$key].SkillName = $skillFolderName
            $modules[$key].SkillLocation = $skillFile.FullName.Substring($RepoPath.TrimEnd('\', '/').Length + 1) -replace '\\', '/'
            break
        }
    }
}

Write-Host "Discovered $($modules.Count) candidate module(s) before filtering: $($modules.Keys -join ', ')" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# Step 1.75: Keep only modules that actually belong to Boxfusion/Shesha (name
# starts with "shesha"/"boxfusion", or npm scope "@shesha-io/") - drops any
# vendored third-party code discovered alongside the real modules.
# ---------------------------------------------------------------------------

$droppedModules = @($modules.Keys | Where-Object { -not (Test-IsOwnModule -Name $_) })
foreach ($dropped in $droppedModules) {
    $modules.Remove($dropped)
}
if ($droppedModules.Count -gt 0) {
    Write-Host "Dropped $($droppedModules.Count) non-Boxfusion/Shesha candidate(s): $($droppedModules -join ', ')" -ForegroundColor DarkGray
}
Write-Host "Registering $($modules.Count) module(s): $($modules.Keys -join ', ')" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# Step 1.5: Resolve the private feed's flat-container (package base address)
# resource from its NuGet v3 service index, and derive the Azure DevOps
# organization/feed names for building package overview links.
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Resolving NuGet feed resources from $NugetFeedUrl ..." -ForegroundColor Cyan
$serviceIndex = Invoke-JsonGet -Url $NugetFeedUrl -Headers $feedHeaders
if (-not $serviceIndex) {
    throw "Could not read the NuGet service index at $NugetFeedUrl - check the URL and PAT."
}
$flatContainerResource = $serviceIndex.resources | Where-Object { $_.'@type' -like 'PackageBaseAddress*' } | Select-Object -First 1
if (-not $flatContainerResource) {
    throw "The NuGet service index at $NugetFeedUrl has no PackageBaseAddress resource."
}
$flatContainerBase = $flatContainerResource.'@id'.TrimEnd('/')

$azureOrg = $null
$nugetAzureFeed = $null
if ($NugetFeedUrl -match 'pkgs\.dev\.azure\.com/([^/]+)/_packaging/([^/]+)/') {
    $azureOrg = $Matches[1]
    $nugetAzureFeed = $Matches[2]
}

$npmAzureFeed = $null
if ($NpmRegistryUrl -match 'pkgs\.dev\.azure\.com/([^/]+)/_packaging/([^/]+)/') {
    if (-not $azureOrg) { $azureOrg = $Matches[1] }
    $npmAzureFeed = $Matches[2]
}

# ---------------------------------------------------------------------------
# Step 2: Look up published packages on NuGet + npm
# ---------------------------------------------------------------------------

$payloads = @()

foreach ($moduleName in $modules.Keys) {
    $info = $modules[$moduleName]
    Write-Host ""
    Write-Host "=== $moduleName ===" -ForegroundColor Yellow

    $versions = @{}  # versionNumber -> List[ @{dependencyName; dependencyVersion} ]
    $description = $null
    $nugetLocation = $null
    $npmLocation = $null

    # --- NuGet (private feed) ---
    $resolvedNugetId = $null
    foreach ($candidateId in $info.NugetCandidateIds) {
        $indexUrl = "$flatContainerBase/$($candidateId.ToLowerInvariant())/index.json"
        $index = Invoke-JsonGet -Url $indexUrl -Headers $feedHeaders
        if ($index -and $index.versions) {
            $resolvedNugetId = $candidateId
            break
        }
    }

    if ($resolvedNugetId) {
        $idLower = $resolvedNugetId.ToLowerInvariant()
        $indexUrl = "$flatContainerBase/$idLower/index.json"
        $index = Invoke-JsonGet -Url $indexUrl -Headers $feedHeaders
        if ($azureOrg -and $nugetAzureFeed) {
            $nugetLocation = "https://dev.azure.com/$azureOrg/_artifacts/feed/$nugetAzureFeed/NuGet/$resolvedNugetId/overview"
        }
        Write-Host "  NuGet: $resolvedNugetId ($($index.versions.Count) version(s))" -ForegroundColor Green
        $nugetDroppedDepsCount = 0

        foreach ($version in $index.versions) {
            $versionLower = $version.ToLowerInvariant()
            $nuspecUrl = "$flatContainerBase/$idLower/$versionLower/$idLower.nuspec"
            try {
                $nuspecRaw = Invoke-RestMethod -Uri $nuspecUrl -Method Get -Headers $feedHeaders -ErrorAction Stop
                # The feed may serve this without a charset, so PowerShell can mis-decode the
                # leading UTF-8 BOM into garbage characters that break XML parsing. Strip
                # anything before the first '<' regardless of what it decoded to.
                $nuspecRaw = [string]$nuspecRaw -replace '^[^<]*', ''
                [xml]$nuspecXml = $nuspecRaw
            } catch {
                Write-Warning "  Could not fetch/parse nuspec for $resolvedNugetId $version, skipping this version's dependencies"
                if (-not $versions.ContainsKey($version)) {
                    $versions[$version] = New-Object System.Collections.Generic.List[object]
                }
                continue
            }

            if (-not $description) {
                $descNode = $nuspecXml.SelectSingleNode("//*[local-name()='description']")
                if ($descNode -and $descNode.InnerText.Trim()) {
                    $description = $descNode.InnerText.Trim()
                }
            }

            $depList = New-Object System.Collections.Generic.List[object]
            $depNodes = $nuspecXml.SelectNodes("//*[local-name()='dependency']")
            foreach ($depNode in $depNodes) {
                try {
                    $depId = $depNode.GetAttribute("id")
                    $depVersion = Clean-VersionRange -Range $depNode.GetAttribute("version")
                    if ($depId -and (Test-IsOwnModule -Name $depId)) {
                        $depList.Add([ordered]@{
                            dependencyName    = $depId
                            dependencyVersion = $depVersion
                        })
                    } elseif ($depId) {
                        $nugetDroppedDepsCount++
                    }
                } catch {
                    Write-Warning "  Skipping one malformed dependency entry for $resolvedNugetId $version : $($_.Exception.Message)"
                }
            }
            $versions[$version] = $depList
        }
        if ($nugetDroppedDepsCount -gt 0) {
            Write-Host "  Kept only Shesha/Boxfusion dependencies - dropped $nugetDroppedDepsCount public dependency reference(s) across all versions" -ForegroundColor DarkGray
        }
    } else {
        Write-Host "  NuGet: not published" -ForegroundColor DarkGray
    }

    # --- npm (private feed) ---
    if ($info.NpmPackage) {
        $npmPackageSegment = $info.NpmPackage -replace '/', '%2f'
        $npmDoc = Invoke-JsonGet -Url "$($NpmRegistryUrl.TrimEnd('/'))/$npmPackageSegment" -Headers $feedHeaders
        if ($npmDoc -and $npmDoc.versions) {
            if ($azureOrg -and $npmAzureFeed) {
                $npmLocation = "https://dev.azure.com/$azureOrg/_artifacts/feed/$npmAzureFeed/Npm/$($info.NpmPackage)/overview"
            }
            $npmVersionNames = $npmDoc.versions | Get-Member -MemberType NoteProperty | ForEach-Object { $_.Name }
            Write-Host "  npm: $($info.NpmPackage) ($($npmVersionNames.Count) version(s))" -ForegroundColor Green
            $npmDroppedDepsCount = 0

            if (-not $description -and $npmDoc.description) {
                $description = $npmDoc.description
            }

            foreach ($versionName in $npmVersionNames) {
                $versionDoc = $npmDoc.versions.$versionName
                $depList = New-Object System.Collections.Generic.List[object]
                if ($versionDoc.dependencies) {
                    foreach ($dep in ($versionDoc.dependencies | Get-Member -MemberType NoteProperty)) {
                        try {
                            if (Test-IsOwnModule -Name $dep.Name) {
                                $depList.Add([ordered]@{
                                    dependencyName    = $dep.Name
                                    dependencyVersion = Clean-VersionRange -Range $versionDoc.dependencies.($dep.Name)
                                })
                            } else {
                                $npmDroppedDepsCount++
                            }
                        } catch {
                            Write-Warning "  Skipping one malformed dependency entry for $($info.NpmPackage) $versionName : $($_.Exception.Message)"
                        }
                    }
                }
                if (-not $versions.ContainsKey($versionName)) {
                    $versions[$versionName] = $depList
                } else {
                    $versions[$versionName].AddRange($depList)
                }
            }
            if ($npmDroppedDepsCount -gt 0) {
                Write-Host "  Kept only Shesha/Boxfusion dependencies - dropped $npmDroppedDepsCount public dependency reference(s) across all versions" -ForegroundColor DarkGray
            }
        } else {
            Write-Host "  npm: not published" -ForegroundColor DarkGray
        }
    } else {
        Write-Host "  npm: no matching package.json found" -ForegroundColor DarkGray
    }

    if ($versions.Count -eq 0) {
        Write-Host "  No published versions found on either registry - registering with empty version history" -ForegroundColor DarkYellow
    }

    $versionsArray = @()
    foreach ($versionNumber in $versions.Keys) {
        try {
            $versionsArray += [ordered]@{
                versionNumber = $versionNumber
                dependencies  = $versions[$versionNumber]
            }
        } catch {
            Write-Warning "  Skipping malformed version entry '$versionNumber' for $moduleName : $($_.Exception.Message)"
        }
    }

    $payloads += [ordered]@{
        moduleManifestName = $moduleName
        description        = $description
        limitations        = $null
        nugetLocation      = $nugetLocation
        npmLocation        = $npmLocation
        customComponents   = $null
        skillName          = $info.SkillName
        skillLocation      = $info.SkillLocation
        versions           = $versionsArray
    }
}

# ---------------------------------------------------------------------------
# Step 3: Authenticate against the Module Registry backend
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Authenticating against $BackendUrl ..." -ForegroundColor Cyan

$authBody = @{ userNameOrEmailAddress = $Username; password = $Password } | ConvertTo-Json
$authResponse = Invoke-RestMethod -Uri "$BackendUrl/api/TokenAuth/Authenticate" -Method Post -Body $authBody -ContentType "application/json"
$token = $authResponse.result.accessToken
if (-not $token) {
    throw "Authentication failed - no access token returned."
}
$headers = @{ Authorization = "Bearer $token" }

# ---------------------------------------------------------------------------
# Step 4: Load existing modules and upsert
# ---------------------------------------------------------------------------

$existingByName = @{}
$existingPageSize = 100
$existingSkip = 0
do {
    $existing = Invoke-RestMethod -Uri "$BackendUrl/api/services/ModuleRegistry/ModuleInfoSearch/GetAll?skipCount=$existingSkip&maxResultCount=$existingPageSize" -Method Get -Headers $headers
    $existingItems = @()
    if ($existing.success -and $existing.result -and $existing.result.items) {
        $existingItems = $existing.result.items
        foreach ($m in $existingItems) {
            $existingByName[$m.moduleManifestName.ToLowerInvariant()] = $m.id
        }
    }
    $existingSkip += $existingPageSize
} while ($existingItems.Count -eq $existingPageSize)

$summary = @()

foreach ($payload in $payloads) {
    $key = $payload.moduleManifestName.ToLowerInvariant()
    $bodyJson = $payload | ConvertTo-Json -Depth 10

    try {
        if ($existingByName.ContainsKey($key)) {
            $updatePayload = [ordered]@{}
            foreach ($k in $payload.Keys) { $updatePayload[$k] = $payload[$k] }
            $updatePayload["id"] = $existingByName[$key]
            $updateJson = $updatePayload | ConvertTo-Json -Depth 10
            $response = Invoke-RestMethod -Uri "$BackendUrl/api/services/ModuleRegistry/ModuleInfoSearch/Update" -Method Put -Headers $headers -Body $updateJson -ContentType "application/json"
            $action = "Updated"
        } else {
            $response = Invoke-RestMethod -Uri "$BackendUrl/api/services/ModuleRegistry/ModuleInfoSearch/Insert" -Method Post -Headers $headers -Body $bodyJson -ContentType "application/json"
            $action = "Created"
        }

        if ($response.success) {
            $summary += [ordered]@{ Module = $payload.moduleManifestName; Action = $action; Versions = $payload.versions.Count; Detail = "" }
        } else {
            $summary += [ordered]@{ Module = $payload.moduleManifestName; Action = "Failed"; Versions = $payload.versions.Count; Detail = $response.error.message }
        }
    } catch {
        $summary += [ordered]@{ Module = $payload.moduleManifestName; Action = "Failed"; Versions = $payload.versions.Count; Detail = $_.Exception.Message }
    }
}

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
$summary | ForEach-Object {
    $color = switch ($_.Action) { "Created" { "Green" }; "Updated" { "Yellow" }; default { "Red" } }
    Write-Host ("{0,-10} {1,-30} {2,3} version(s)  {3}" -f $_.Action, $_.Module, $_.Versions, $_.Detail) -ForegroundColor $color
}
