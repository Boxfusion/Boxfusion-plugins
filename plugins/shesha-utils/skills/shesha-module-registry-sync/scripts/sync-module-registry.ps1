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

function Get-BraceBody {
    # Returns the text between the first '{' at/after $StartIndex and its matching '}'.
    param([string]$Content, [int]$StartIndex)
    $openIndex = $Content.IndexOf('{', $StartIndex)
    if ($openIndex -lt 0) { return $null }
    $depth = 0
    for ($i = $openIndex; $i -lt $Content.Length; $i++) {
        $ch = $Content[$i]
        if ($ch -eq '{') { $depth++ }
        elseif ($ch -eq '}') {
            $depth--
            if ($depth -eq 0) {
                return $Content.Substring($openIndex + 1, $i - $openIndex - 1)
            }
        }
    }
    return $Content.Substring($openIndex + 1)
}

function Strip-CsComments {
    param([string]$Content)
    $Content = [regex]::Replace($Content, '//.*', '')
    $Content = [regex]::Replace($Content, '/\*.*?\*/', '', [System.Text.RegularExpressions.RegexOptions]::Singleline)
    return $Content
}

function Get-EntitiesFromContent {
    # Regex/brace-matching heuristic extraction of Shesha domain entities - not a full C# parser,
    # but matches the conventions this codebase (and Shesha generally) actually uses.
    param([string]$Content)
    $Content = Strip-CsComments -Content $Content
    $results = @()
    $classMatches = [regex]::Matches($Content, 'public\s+class\s+(\w+)\s*:\s*(?:FullAuditedEntity|AuditedEntity|CreationAuditedEntity|Entity)\s*<')
    foreach ($m in $classMatches) {
        $entityName = $m.Groups[1].Value
        $body = Get-BraceBody -Content $Content -StartIndex $m.Index
        if (-not $body) { continue }
        $properties = @()
        $propMatches = [regex]::Matches($body, 'public\s+virtual\s+([\w\.<>\[\],\s]+?)\s+(\w+)\s*\{\s*get;\s*set;\s*\}')
        foreach ($p in $propMatches) {
            $properties += [ordered]@{ propertyName = $p.Groups[2].Value; propertyType = $p.Groups[1].Value.Trim() }
        }
        $results += [ordered]@{ entityName = $entityName; properties = $properties }
    }
    return $results
}

function Get-RouteModuleNameFromContent {
    # Finds the moduleName: "X" passed to CreateControllersForAppServices(...) in a *Module.cs /
    # *ApplicationModule.cs file, which determines the /api/services/{X}/... route segment.
    param([string]$Content)
    if ($Content -match 'CreateControllersForAppServices\(\s*[\s\S]*?moduleName:\s*"([^"]+)"') {
        return $Matches[1]
    }
    return $null
}

function Get-ApisFromContent {
    # Custom APIs - explicit [HttpGet]/[HttpPost]/etc-attributed AppService methods. Tagged
    # "Custom" so the registry can group them separately from the auto-generated CRUD set.
    param([string]$Content, [string]$RouteModuleName)
    $Content = Strip-CsComments -Content $Content
    $results = @()
    $classMatches = [regex]::Matches($Content, 'public\s+class\s+(\w*AppService)\b[^{]*')
    foreach ($m in $classMatches) {
        $serviceName = $m.Groups[1].Value -replace 'AppService$', ''
        $body = Get-BraceBody -Content $Content -StartIndex $m.Index
        if (-not $body) { continue }
        $methodMatches = [regex]::Matches($body, '\[Http(Get|Post|Put|Delete)\]\s*(?:\[[^\]]*\]\s*)*public\s+(?:async\s+)?[\w<>\[\],\.\s]+?\s+(\w+?)(?:Async)?\s*\(')
        foreach ($mm in $methodMatches) {
            $results += [ordered]@{
                name       = $mm.Groups[2].Value
                httpMethod = $mm.Groups[1].Value.ToUpperInvariant()
                route      = "/api/services/$RouteModuleName/$serviceName/$($mm.Groups[2].Value)"
                category   = "Custom"
            }
        }
    }
    return $results
}

function Get-CrudApisForEntities {
    # Shesha auto-generates a dynamic CRUD controller for every domain entity - these APIs
    # exist regardless of any hand-written AppService, so they're derived directly from the
    # entities already found by Get-EntitiesFromContent rather than scanned for separately.
    # Route shape: /api/dynamic/{RouteModuleName}/{EntityName}/Crud/{Method}
    param([array]$Entities, [string]$RouteModuleName)
    $crudMethods = [ordered]@{
        Create = 'POST'
        Get    = 'GET'
        GetAll = 'GET'
        Update = 'PUT'
        Delete = 'DELETE'
    }
    $results = @()
    foreach ($entity in $Entities) {
        foreach ($method in $crudMethods.Keys) {
            $results += [ordered]@{
                name       = "$($entity.entityName)$method"
                httpMethod = $crudMethods[$method]
                route      = "/api/dynamic/$RouteModuleName/$($entity.entityName)/Crud/$method"
                category   = "Crud"
            }
        }
    }
    return $results
}

function Get-SettingsFromContent {
    param([string]$Content)
    $Content = Strip-CsComments -Content $Content
    $results = @()
    $ifaceMatches = [regex]::Matches($Content, 'interface\s+I(\w+)\s*:\s*ISettingAccessors')
    foreach ($m in $ifaceMatches) {
        $body = Get-BraceBody -Content $Content -StartIndex $m.Index
        if (-not $body) { continue }
        $propMatches = [regex]::Matches($body, '(?:\[Display\(([^\)]*)\)\]\s*)?\[Setting\([^\)]*\)\]\s*ISettingAccessor<[^>]+>\s+(\w+)\s*\{')
        foreach ($p in $propMatches) {
            $displayArgs = $p.Groups[1].Value
            $name = $p.Groups[2].Value
            $desc = $null
            if ($displayArgs -match 'Name\s*=\s*"([^"]*)"') { $name = $Matches[1] }
            if ($displayArgs -match 'Description\s*=\s*"([^"]*)"') { $desc = $Matches[1] }
            $results += [ordered]@{ name = $name; description = $desc }
        }
    }
    return $results
}

function Get-EnumsFromContent {
    # Regex/brace-matching heuristic extraction of plain C# enum declarations (including
    # Shesha's code-based reference-list convention, where each member carries a
    # [Display(Name = "...")] attribute) - not a full C# parser.
    param([string]$Content)
    $Content = Strip-CsComments -Content $Content
    $results = @()
    $enumMatches = [regex]::Matches($Content, 'public\s+enum\s+(\w+)\s*(?::\s*\w+\s*)?(?=\{)')
    foreach ($m in $enumMatches) {
        $enumName = $m.Groups[1].Value
        $body = Get-BraceBody -Content $Content -StartIndex $m.Index
        if (-not $body) { continue }
        # Strip member attributes like [Display(Name = "Low")] before splitting members.
        $cleanBody = [regex]::Replace($body, '\[[^\]]*\]', '')
        $values = @()
        foreach ($token in ($cleanBody -split ',')) {
            $t = $token.Trim()
            if (-not $t) { continue }
            if ($t -match '^(\w+)\s*(?:=\s*(-?\d+))?$') {
                $entry = [ordered]@{ name = $Matches[1]; value = $null }
                if ($Matches[2]) { $entry.value = [long]$Matches[2] }
                $values += $entry
            }
        }
        $results += [ordered]@{ enumName = $enumName; values = $values }
    }
    return $results
}

function Get-ModuleSourceCode {
    # Scans a module's source folders once and returns everything needed to build its
    # entities/apis/settings/enums, plus the resolved route module name for API paths.
    param([System.Collections.Generic.List[string]]$SourceFolders, [string]$FallbackRouteModuleName)

    $entities = @()
    $settings = @()
    $enums = @()
    $routeModuleName = $null
    $allContent = @()

    foreach ($folder in $SourceFolders) {
        $files = Get-ChildItem -Path $folder -Recurse -Filter "*.cs" -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -notmatch '\\(bin|obj)\\' }
        foreach ($file in $files) {
            try {
                $content = Get-Content -Path $file.FullName -Raw -ErrorAction Stop
            } catch {
                continue
            }
            if (-not $content) { continue }
            $allContent += [ordered]@{ Path = $file.FullName; Content = $content }

            $entities += Get-EntitiesFromContent -Content $content
            $settings += Get-SettingsFromContent -Content $content
            $enums += Get-EnumsFromContent -Content $content

            if (-not $routeModuleName) {
                $routeModuleName = Get-RouteModuleNameFromContent -Content $content
            }
        }
    }

    if (-not $routeModuleName) {
        $routeModuleName = $FallbackRouteModuleName
    }

    # Crud APIs first (one group per entity), then Custom APIs discovered on AppServices -
    # keeps the two categories visually grouped in the payload sent to the registry.
    $apis = @()
    $apis += Get-CrudApisForEntities -Entities $entities -RouteModuleName $routeModuleName
    foreach ($item in $allContent) {
        $apis += Get-ApisFromContent -Content $item.Content -RouteModuleName $routeModuleName
    }

    return [ordered]@{ Entities = $entities; Apis = $apis; Settings = $settings; Enums = $enums }
}

function Get-ModuleSummary {
    # Best-effort auto-description built from what was actually discovered in the source code -
    # only used as a fallback when no description was found on NuGet/npm.
    param($Entities, $Apis)
    $parts = @()
    if ($Entities.Count -gt 0) {
        $entityNames = ($Entities | ForEach-Object { $_.entityName }) -join ", "
        $parts += "Provides domain entities: $entityNames."
    }
    if ($Apis.Count -gt 0) {
        $apiNames = ($Apis | ForEach-Object { $_.name } | Select-Object -Unique) -join ", "
        $parts += "Exposes APIs: $apiNames."
    }
    if ($parts.Count -eq 0) { return $null }
    return ($parts -join " ")
}

# ---------------------------------------------------------------------------
# Step 1: Discover modules in the repo
# ---------------------------------------------------------------------------

Write-Host "Scanning $RepoPath for modules..." -ForegroundColor Cyan

$csprojFiles = Get-ChildItem -Path $RepoPath -Recurse -Filter "*.csproj" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\(bin|obj|node_modules)\\' }

$modules = @{}  # moduleName -> @{ NugetCandidateIds = [string[]]; NpmPackage = $null; SkillName=$null; SkillLocation=$null; SourceFolders=[string[]] }

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
            SourceFolders     = New-Object System.Collections.Generic.List[string]
        }
    }
    if (-not $modules[$moduleName].NugetCandidateIds.Contains($packageId)) {
        $modules[$moduleName].NugetCandidateIds.Add($packageId)
    }
    if (-not $modules[$moduleName].NugetCandidateIds.Contains($moduleName)) {
        $modules[$moduleName].NugetCandidateIds.Insert(0, $moduleName)
    }
    if (-not $modules[$moduleName].SourceFolders.Contains($csproj.DirectoryName)) {
        $modules[$moduleName].SourceFolders.Add($csproj.DirectoryName)
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
            SourceFolders     = New-Object System.Collections.Generic.List[string]
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

    # --- Domain entities, APIs and settings, extracted from the module's own source code ---
    $fallbackRouteModuleName = ($moduleName -replace '^(shesha|boxfusion)\.', '') -replace '[^a-zA-Z0-9]', ''
    $sourceCode = Get-ModuleSourceCode -SourceFolders $info.SourceFolders -FallbackRouteModuleName $fallbackRouteModuleName

    if ($sourceCode.Entities.Count -gt 0 -or $sourceCode.Apis.Count -gt 0 -or $sourceCode.Settings.Count -gt 0 -or $sourceCode.Enums.Count -gt 0) {
        $crudApiCount = ($sourceCode.Apis | Where-Object { $_.category -eq 'Crud' }).Count
        $customApiCount = ($sourceCode.Apis | Where-Object { $_.category -eq 'Custom' }).Count
        Write-Host "  Source: $($sourceCode.Entities.Count) entity(ies), $($sourceCode.Apis.Count) API(s) [$crudApiCount CRUD / $customApiCount custom], $($sourceCode.Settings.Count) setting(s), $($sourceCode.Enums.Count) enum(s)" -ForegroundColor Green
    }

    if (-not $description) {
        $description = Get-ModuleSummary -Entities $sourceCode.Entities -Apis $sourceCode.Apis
        if ($description) {
            Write-Host "  No description found on NuGet/npm - generated one from entities/APIs" -ForegroundColor DarkGray
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
        entities           = $sourceCode.Entities
        apis               = $sourceCode.Apis
        settings           = $sourceCode.Settings
        enums              = $sourceCode.Enums
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
            $summary += [ordered]@{ Module = $payload.moduleManifestName; Action = $action; Versions = $payload.versions.Count; Entities = $payload.entities.Count; Apis = $payload.apis.Count; Settings = $payload.settings.Count; Enums = $payload.enums.Count; Detail = "" }
        } else {
            $summary += [ordered]@{ Module = $payload.moduleManifestName; Action = "Failed"; Versions = $payload.versions.Count; Entities = $payload.entities.Count; Apis = $payload.apis.Count; Settings = $payload.settings.Count; Enums = $payload.enums.Count; Detail = $response.error.message }
        }
    } catch {
        $summary += [ordered]@{ Module = $payload.moduleManifestName; Action = "Failed"; Versions = $payload.versions.Count; Entities = $payload.entities.Count; Apis = $payload.apis.Count; Settings = $payload.settings.Count; Enums = $payload.enums.Count; Detail = $_.Exception.Message }
    }
}

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
$summary | ForEach-Object {
    $color = switch ($_.Action) { "Created" { "Green" }; "Updated" { "Yellow" }; default { "Red" } }
    Write-Host ("{0,-10} {1,-30} {2,3} version(s)  {3,3} entities  {4,3} APIs  {5,3} settings  {6,3} enums  {7}" -f $_.Action, $_.Module, $_.Versions, $_.Entities, $_.Apis, $_.Settings, $_.Enums, $_.Detail) -ForegroundColor $color
}
