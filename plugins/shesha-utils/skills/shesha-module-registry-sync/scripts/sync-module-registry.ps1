<#
.SYNOPSIS
  Scans a repo for Shesha modules, looks up their published NuGet/npm packages
  (full version + dependency history) on the private Boxfusion Azure Artifacts
  feed, and upserts them into the Module Registry via the ModuleInfoSearch API.

.PARAMETER RepoPath
  Path to the repository to scan.

.PARAMETER BackendUrl
  Base URL of the Shesha.ModuleRegistry backend to sync into. Defaults to the
  shesha-moduleregisty-api-test environment; pass -BackendUrl to target a
  different one.

.PARAMETER Username
.PARAMETER Password
  Admin credentials used to authenticate against the backend. No defaults - the
  caller must always supply real credentials for the target environment. Not
  required when -ExportOnly is set.

.PARAMETER NugetFeedUrl
  NuGet v3 service index URL of the private feed.

.PARAMETER NpmRegistryUrl
  npm registry URL of the private feed.

.PARAMETER FeedPat
  Personal Access Token for the Azure DevOps organization that hosts the feed.
  Falls back to the $env:SHESHA_FEED_PAT environment variable if not supplied -
  prefer that over passing it on the command line so it doesn't end up in shell
  history. Never hardcode this value in the script. Not required when -ExportOnly
  is set.

.PARAMETER ExportOnly
  Scans each module's own source (entities/APIs/settings/enums) and writes it to
  -ExportPath, then stops - no NuGet/npm lookups and no backend calls are made.
  A regex scan can list what a module contains but can't explain what it's for,
  so this lets a human/Claude read the actual source and author a real
  description per module before running the real sync with -DescriptionsFile.

.PARAMETER ExportPath
  Output path for the -ExportOnly scan JSON. Required when -ExportOnly is set.

.PARAMETER DescriptionsFile
  Path to a JSON file of { "moduleManifestName": "description text", ... }. When
  a module's name has an entry here, that authored description is sent to the
  registry verbatim instead of the mechanical entities/APIs/settings/enums
  listing that Get-ModuleDescription falls back to.

.PARAMETER SourceRef
  A git ref (branch/tag) to scan source from instead of the live working tree,
  read via git plumbing (ls-tree/show) rather than the filesystem. Required,
  and forced to be required, for the shesha-io/shesha-framework repo specifically
  (pass e.g. "releases/0.44" or "releases/0.45") - that repo is also auto-switched
  to the public NuGet/npm registries regardless of -NugetFeedUrl/-NpmRegistryUrl's
  defaults. Every other repo is unaffected by any of this and keeps scanning the
  working tree against the private Boxfusion feed as before.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    [string]$BackendUrl = "https://shesha-moduleregisty-api-test.shesha.app/",
    [string]$Username,
    [string]$Password,

    [string]$NugetFeedUrl = "https://pkgs.dev.azure.com/boxfusion/_packaging/nuget.shesha.dev/nuget/v3/index.json",
    [string]$NpmRegistryUrl = "https://pkgs.dev.azure.com/boxfusion/_packaging/npm.shesha.dev/npm/registry/",
    [string]$FeedPat = $env:SHESHA_FEED_PAT,

    [switch]$ExportOnly,
    [string]$ExportPath,
    [string]$DescriptionsFile,
    [string]$SourceRef
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

if ($ExportOnly -and -not $ExportPath) {
    throw "-ExportPath is required when -ExportOnly is set."
}

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

function Get-NugetPublishedDate {
    # Reads the publish date off the NuGet v3 registration leaf for one package version
    # (standard protocol, e.g. {registrationBase}/{id}/{version}.json -> catalogEntry.published).
    # Best-effort: returns $null on any failure rather than aborting the sync over a missing date.
    param([string]$RegistrationBase, [string]$IdLower, [string]$VersionLower, [hashtable]$Headers)
    if (-not $RegistrationBase) { return $null }
    try {
        $leaf = Invoke-RestMethod -Uri "$RegistrationBase/$IdLower/$VersionLower.json" -Method Get -Headers $Headers -ErrorAction Stop
        $published = if ($leaf.catalogEntry.published) { $leaf.catalogEntry.published } else { $leaf.published }
        if (-not $published) { return $null }
        return ([datetime]$published).ToString("o")
    } catch {
        return $null
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

function Get-NamespaceAtIndex {
    # Finds the namespace a given position in a file falls under - the closest preceding
    # "namespace X.Y { ... }" (classic) or "namespace X.Y;" (C# 10+ file-scoped) declaration.
    param([string]$Content, [int]$Index)
    $namespaceMatches = [regex]::Matches($Content, 'namespace\s+([\w\.]+)\s*[{;]')
    $result = $null
    foreach ($nsMatch in $namespaceMatches) {
        if ($nsMatch.Index -ge $Index) { break }
        $result = $nsMatch.Groups[1].Value
    }
    return $result
}

function Get-EntitiesFromAllContent {
    # Regex/brace-matching heuristic extraction of Shesha domain entities - not a full C# parser,
    # but matches the conventions this codebase (and Shesha generally) actually uses.
    #
    # Runs as a fixed-point pass across every file in the module TOGETHER (not per-file), because
    # a domain entity commonly extends another domain entity rather than FullAuditedEntity/
    # AuditedEntity/CreationAuditedEntity/Entity directly (e.g. `class SpecialWidget : Widget`),
    # and that parent can live in a different file. Each pass adds any newly matched entity name
    # to the set of recognized base names, so subclasses-of-subclasses are picked up too, however
    # many inheritance levels deep - it keeps re-scanning until a full pass finds nothing new.
    #
    # Allows abstract/sealed/partial/static modifiers between "public" and "class" (a shared
    # abstract base entity - `public abstract class BaseWidget : FullAuditedEntity<Guid>` - is a
    # common Shesha pattern; without this, BaseWidget itself would never match, which would in
    # turn keep anything extending BaseWidget from matching either) and an optional namespace
    # qualifier in front of the base name (e.g. `Abp.Domain.Entities.Auditing.FullAuditedEntity`).
    # Known remaining gaps: non-public (internal/no-modifier) entity classes, and entities that
    # extend a base class defined in a DIFFERENT module (out of scope for this module's own scan
    # by design - see Key Rules).
    param([array]$AllContent)
    $results = @()
    $seenNames = New-Object System.Collections.Generic.HashSet[string]
    $baseNames = @('FullAuditedEntity', 'AuditedEntity', 'CreationAuditedEntity', 'Entity')
    $changed = $true
    while ($changed) {
        $changed = $false
        $alternation = ($baseNames | ForEach-Object { [regex]::Escape($_) }) -join '|'
        foreach ($item in $AllContent) {
            $content = Strip-CsComments -Content $item.Content
            $classMatches = [regex]::Matches($content, "public\s+((?:(?:abstract|sealed|partial|static)\s+)*)class\s+(\w+)\s*:\s*(?:[\w]+\.)*($alternation)\s*(?:<([^<>]+)>)?")
            foreach ($m in $classMatches) {
                $entityName = $m.Groups[2].Value
                if ($seenNames.Contains($entityName)) { continue }
                $isAbstract = $m.Groups[1].Value -match 'abstract'
                $parentName = $m.Groups[3].Value
                $genericArg = $m.Groups[4].Value
                $baseClass = if ($genericArg) { "$parentName<$($genericArg.Trim())>" } else { $parentName }
                $namespaceName = Get-NamespaceAtIndex -Content $content -Index $m.Index
                $body = Get-BraceBody -Content $content -StartIndex $m.Index
                if (-not $body) { continue }
                $properties = @()
                $propMatches = [regex]::Matches($body, 'public\s+virtual\s+([\w\.<>\[\],\s]+?)\s+(\w+)\s*\{\s*get;\s*set;\s*\}')
                foreach ($p in $propMatches) {
                    $properties += [ordered]@{ propertyName = $p.Groups[2].Value; propertyType = $p.Groups[1].Value.Trim() }
                }
                $results += [ordered]@{ entityName = $entityName; namespace = $namespaceName; baseClass = $baseClass; isAbstract = $isAbstract; properties = $properties }
                [void]$seenNames.Add($entityName)
                $baseNames += $entityName
                $changed = $true
            }
        }
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

function Get-CrudRouteModuleNameFromContent {
    # Finds the name passed to `new SheshaModuleInfo("X")` on the ModuleInfo override in the
    # module's own Module.cs (Domain layer), e.g.
    #   public override SheshaModuleInfo ModuleInfo => new SheshaModuleInfo("boxfusion.chat");
    # This is the RouteModuleName used specifically for the auto-generated
    # /api/dynamic/{RouteModuleName}/{EntityName}/Crud/{Method} CRUD routes.
    param([string]$Content)
    if ($Content -match 'ModuleInfo\s*=>\s*new\s+SheshaModuleInfo\(\s*"([^"]+)"') {
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
    # entities already found by Get-EntitiesFromAllContent rather than scanned for separately.
    # Route shape: /api/dynamic/{RouteModuleName}/{EntityName}/Crud/{Method}
    # Abstract entities are skipped - they can't be instantiated, so Shesha never exposes a
    # dynamic CRUD controller for one; only its concrete subclasses actually get real endpoints.
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
        if ($entity.isAbstract) { continue }
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
    # Reads via the live filesystem by default, or via a specific git ref when -SourceRef is set.
    param([System.Collections.Generic.List[string]]$SourceFolders, [string]$FallbackRouteModuleName, [string]$RepoPath, [string]$SourceRef)

    $settings = @()
    $enums = @()
    $routeModuleName = $null
    $crudRouteModuleName = $null
    $allContent = @()

    foreach ($folder in $SourceFolders) {
        $isDomainFolder = (Split-Path -Path $folder -Leaf) -match '\.Domain$'
        $files = Get-SourceFiles -RepoPath $RepoPath -SourceRef $SourceRef -RootFolder $folder -NamePattern '\.cs$' -ExcludePattern '[\\/](bin|obj)[\\/]'
        foreach ($file in $files) {
            $content = Read-SourceFile -RepoPath $RepoPath -SourceRef $SourceRef -Path $file.FullName
            if (-not $content) { continue }
            $allContent += [ordered]@{ Path = $file.FullName; Content = $content }

            $settings += Get-SettingsFromContent -Content $content
            $enums += Get-EnumsFromContent -Content $content

            if (-not $routeModuleName) {
                $routeModuleName = Get-RouteModuleNameFromContent -Content $content
            }
            if ($isDomainFolder -and -not $crudRouteModuleName) {
                $crudRouteModuleName = Get-CrudRouteModuleNameFromContent -Content $content
            }
        }
    }

    # Wrapped in @(...) because a PowerShell function returning a zero-element array collapses to
    # $null at the call site otherwise - without this, a module with no entities would serialize
    # its "entities" field as a JSON object instead of an empty array, which the backend rejects.
    $entities = @(Get-EntitiesFromAllContent -AllContent $allContent)

    if (-not $routeModuleName) {
        $routeModuleName = $FallbackRouteModuleName
    }
    if (-not $crudRouteModuleName) {
        $crudRouteModuleName = if ($routeModuleName) { $routeModuleName } else { $FallbackRouteModuleName }
    }

    # Crud APIs first (one group per entity), then Custom APIs discovered on AppServices -
    # keeps the two categories visually grouped in the payload sent to the registry.
    $apis = @()
    $apis += Get-CrudApisForEntities -Entities $entities -RouteModuleName $crudRouteModuleName
    foreach ($item in $allContent) {
        $apis += Get-ApisFromContent -Content $item.Content -RouteModuleName $routeModuleName
    }

    return [ordered]@{ Entities = $entities; Apis = $apis; Settings = $settings; Enums = $enums }
}

function Get-ModuleDescription {
    # Mechanical fallback only - a regex scan can enumerate what a module contains but can't
    # explain what it's for, so this is just a listing of entity/API/setting/enum names. Real
    # descriptions should be authored by reading the module's actual source (see -ExportOnly /
    # -DescriptionsFile) and passed in; this only fires for a module with no authored override.
    param($Entities, $Apis, $Settings, $Enums)
    $parts = @()

    if ($Entities.Count -gt 0) {
        $entityNames = ($Entities | ForEach-Object { $_.entityName }) -join ", "
        $parts += "Domain entities: $entityNames."
    }

    $crudCount = @($Apis | Where-Object { $_.category -eq 'Crud' }).Count
    $customApis = @($Apis | Where-Object { $_.category -eq 'Custom' })
    if ($crudCount -gt 0 -or $customApis.Count -gt 0) {
        $apiParts = @()
        if ($crudCount -gt 0) { $apiParts += "$crudCount CRUD endpoint(s)" }
        if ($customApis.Count -gt 0) {
            $customNames = ($customApis | ForEach-Object { $_.name } | Select-Object -Unique) -join ", "
            $apiParts += "custom endpoints ($customNames)"
        }
        $parts += "Exposes " + ($apiParts -join " and ") + "."
    }

    if ($Settings.Count -gt 0) {
        $settingNames = ($Settings | ForEach-Object { $_.name }) -join ", "
        $parts += "Settings: $settingNames."
    }

    if ($Enums.Count -gt 0) {
        $enumNames = ($Enums | ForEach-Object { $_.enumName }) -join ", "
        $parts += "Reference lists/enums: $enumNames."
    }

    if ($parts.Count -eq 0) { return $null }
    return ($parts -join " ")
}

# ---------------------------------------------------------------------------
# Step 0.5: Detect the shesha-io/shesha-framework repo specifically. Only for
# that repo: switch to the public NuGet/npm registries (no PAT needed) and
# require a -SourceRef so entities/APIs/settings/enums are extracted from that
# git ref instead of the live working tree. Every other repo is untouched by
# this and keeps using the private Boxfusion feed + the working tree as before.
# ---------------------------------------------------------------------------

function Test-IsSheshaFrameworkRepo {
    param([string]$RepoPath)
    try {
        $remoteUrl = git -C $RepoPath config --get remote.origin.url 2>$null
    } catch {
        return $false
    }
    if (-not $remoteUrl) { return $false }
    return [bool]($remoteUrl -match 'shesha-io/shesha-framework(\.git)?/?$')
}

function Get-GitRefFileList {
    # Lists every file tracked at $SourceRef (git ls-tree -r), cached per run - avoids re-listing
    # the whole tree once per module/folder when scanning by git ref instead of disk.
    param([string]$RepoPath, [string]$SourceRef)
    if ($null -ne $script:GitRefFileListCache) { return $script:GitRefFileListCache }
    $raw = git -C $RepoPath ls-tree -r --name-only $SourceRef 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) {
        throw "Could not list files at git ref '$SourceRef' in '$RepoPath' - fetch it first (e.g. 'git fetch origin $SourceRef') and check the ref name."
    }
    $script:GitRefFileListCache = @($raw)
    return $script:GitRefFileListCache
}

function Get-GitRefFileContent {
    # Reads one file's content as it exists at $SourceRef, without touching the working tree.
    param([string]$RepoPath, [string]$SourceRef, [string]$RelativePath)
    $posixPath = $RelativePath -replace '\\', '/'
    $content = git -C $RepoPath show "${SourceRef}:$posixPath" 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    return ($content -join "`n")
}

function Get-SourceFiles {
    # Returns file entries as @{ FullName; Name; DirectoryName; Directory=@{Name} } from either the
    # live filesystem (default) or a specific git ref (when $SourceRef is set), so every downstream
    # discovery loop works unchanged in both modes.
    param([string]$RepoPath, [string]$SourceRef, [string]$RootFolder, [string]$NamePattern, [string]$ExcludePattern)
    if ($SourceRef) {
        $allFiles = Get-GitRefFileList -RepoPath $RepoPath -SourceRef $SourceRef
        $rootPrefix = if ($RootFolder -and $RootFolder -ne $RepoPath) {
            ($RootFolder.TrimEnd('\', '/') -replace '\\', '/') + '/'
        } else { '' }
        $results = @()
        foreach ($relPath in $allFiles) {
            if ($rootPrefix -and -not $relPath.StartsWith($rootPrefix)) { continue }
            $leaf = [System.IO.Path]::GetFileName($relPath)
            if ($NamePattern -and $leaf -notmatch $NamePattern) { continue }
            if ($ExcludePattern -and $relPath -match $ExcludePattern) { continue }
            $dirName = [System.IO.Path]::GetDirectoryName($relPath) -replace '\\', '/'
            $results += [ordered]@{
                FullName      = $relPath
                Name          = $leaf
                DirectoryName = $dirName
                Directory     = [ordered]@{ Name = (Split-Path -Path $dirName -Leaf) }
            }
        }
        return $results
    } else {
        $searchRoot = if ($RootFolder) { $RootFolder } else { $RepoPath }
        $items = Get-ChildItem -Path $searchRoot -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match $NamePattern -and (-not $ExcludePattern -or $_.FullName -notmatch $ExcludePattern) }
        return @($items | ForEach-Object {
            [ordered]@{
                FullName      = $_.FullName
                Name          = $_.Name
                DirectoryName = $_.DirectoryName
                Directory     = [ordered]@{ Name = $_.Directory.Name }
            }
        })
    }
}

function Read-SourceFile {
    # Reads one file's content, dispatching to the git-ref reader when $SourceRef is set.
    param([string]$RepoPath, [string]$SourceRef, [string]$Path)
    if ($SourceRef) {
        return Get-GitRefFileContent -RepoPath $RepoPath -SourceRef $SourceRef -RelativePath $Path
    }
    try {
        # -Encoding UTF8 is required: Get-Content's default in Windows PowerShell 5.1 is the
        # system codepage, not UTF-8, so any BOM-less UTF-8 source file (the common default for
        # .cs/.json in modern tooling) with non-ASCII characters - accented names, em-dashes,
        # curly quotes in XML doc comments or string literals - gets silently corrupted into
        # mojibake without this, which then gets sent to the registry as garbled text.
        return Get-Content -Path $Path -Raw -Encoding UTF8 -ErrorAction Stop
    } catch {
        return $null
    }
}

$script:GitRefFileListCache = $null
$PublicNugetFeedUrl = "https://api.nuget.org/v3/index.json"
$PublicNpmRegistryUrl = "https://registry.npmjs.org/"
$isSheshaFrameworkRepo = Test-IsSheshaFrameworkRepo -RepoPath $RepoPath

if ($isSheshaFrameworkRepo) {
    Write-Host "Detected shesha-io/shesha-framework - using the public NuGet/npm registries; source will be scanned from a specific git ref, not the working tree." -ForegroundColor Cyan
    if (-not $SourceRef) {
        throw "This repo is shesha-io/shesha-framework - pass -SourceRef 'releases/0.44' or -SourceRef 'releases/0.45' (whichever release you're syncing) to select which branch to scan."
    }
    if (-not $PSBoundParameters.ContainsKey('NugetFeedUrl'))   { $NugetFeedUrl = $PublicNugetFeedUrl }
    if (-not $PSBoundParameters.ContainsKey('NpmRegistryUrl')) { $NpmRegistryUrl = $PublicNpmRegistryUrl }
}

if (-not $ExportOnly) {
    if (-not $BackendUrl) { throw "-BackendUrl is required (unless -ExportOnly is set)." }
    if (-not $Username)   { throw "-Username is required (unless -ExportOnly is set)." }
    if (-not $Password)   { throw "-Password is required (unless -ExportOnly is set)." }
    if (-not $isSheshaFrameworkRepo -and -not $FeedPat) {
        throw "No Personal Access Token supplied. Pass -FeedPat or set the SHESHA_FEED_PAT environment variable."
    }
}

$feedAuthValue = if ($FeedPat -and -not $isSheshaFrameworkRepo) { [Convert]::ToBase64String([System.Text.Encoding]::ASCII.GetBytes(":$FeedPat")) } else { $null }
$feedHeaders = if ($feedAuthValue) { @{ Authorization = "Basic $feedAuthValue" } } else { @{} }

# ---------------------------------------------------------------------------
# Step 1: Discover modules in the repo
# ---------------------------------------------------------------------------

Write-Host "Scanning $RepoPath for modules..." -ForegroundColor Cyan

$csprojFiles = Get-SourceFiles -RepoPath $RepoPath -SourceRef $SourceRef -RootFolder $RepoPath -NamePattern '\.csproj$' -ExcludePattern '[\\/](bin|obj|node_modules)[\\/]'

$modules = @{}  # moduleName -> @{ NugetCandidateIds = [string[]]; NpmPackage = $null; SkillName=$null; SkillLocation=$null; SourceFolders=[string[]] }

foreach ($csproj in $csprojFiles) {
    $rawName = [System.IO.Path]::GetFileNameWithoutExtension($csproj.Name)
    $packageId = $rawName
    try {
        [xml]$xml = Read-SourceFile -RepoPath $RepoPath -SourceRef $SourceRef -Path $csproj.FullName
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

$packageJsonFiles = Get-SourceFiles -RepoPath $RepoPath -SourceRef $SourceRef -RootFolder $RepoPath -NamePattern '^package\.json$' -ExcludePattern '[\\/]node_modules[\\/]'

foreach ($pkgFile in $packageJsonFiles) {
    try {
        $pkgJson = (Read-SourceFile -RepoPath $RepoPath -SourceRef $SourceRef -Path $pkgFile.FullName) | ConvertFrom-Json
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

$skillFiles = Get-SourceFiles -RepoPath $RepoPath -SourceRef $SourceRef -RootFolder $RepoPath -NamePattern '^SKILL\.md$' -ExcludePattern '[\\/]node_modules[\\/]'

foreach ($key in @($modules.Keys)) {
    $normalizedModule = Get-NormalizedName -Name $key
    foreach ($skillFile in $skillFiles) {
        $skillFolderName = $skillFile.Directory.Name
        $normalizedSkill = Get-NormalizedName -Name $skillFolderName
        if ($normalizedSkill -and $normalizedModule -and
            ($normalizedSkill.Contains($normalizedModule) -or $normalizedModule.Contains($normalizedSkill))) {
            $modules[$key].SkillName = $skillFolderName
            $modules[$key].SkillLocation = if ($SourceRef) { $skillFile.FullName } else { $skillFile.FullName.Substring($RepoPath.TrimEnd('\', '/').Length + 1) -replace '\\', '/' }
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
# Step 1.8: Export-only mode - scan each surviving module's own source (the
# same extraction Step 2 normally does) and write it to -ExportPath, then stop.
# No NuGet/npm lookups and no backend calls happen in this mode.
# ---------------------------------------------------------------------------

if ($ExportOnly) {
    Write-Host ""
    Write-Host "Export-only mode: scanning source code only (no NuGet/npm/backend calls)..." -ForegroundColor Cyan
    $scanResults = @()
    foreach ($moduleName in $modules.Keys) {
        $info = $modules[$moduleName]
        $fallbackRouteModuleName = ($moduleName -replace '^(shesha|boxfusion)\.', '') -replace '[^a-zA-Z0-9]', ''
        $sourceCode = Get-ModuleSourceCode -SourceFolders $info.SourceFolders -FallbackRouteModuleName $fallbackRouteModuleName -RepoPath $RepoPath -SourceRef $SourceRef
        $scanResults += [ordered]@{
            moduleManifestName = $moduleName
            sourceFolders      = @($info.SourceFolders)
            entities           = $sourceCode.Entities
            apis               = $sourceCode.Apis
            settings           = $sourceCode.Settings
            enums              = $sourceCode.Enums
        }
    }
    $scanResults | ConvertTo-Json -Depth 10 | Set-Content -Path $ExportPath -Encoding utf8
    Write-Host "Wrote scan results for $($scanResults.Count) module(s) to $ExportPath" -ForegroundColor Green
    Write-Host "Next: for each module, read its actual source (using sourceFolders as a starting point) and write a real 2-4 sentence description of what it does and what it's for - not a list of entity/API names. Save as { moduleManifestName: description } JSON, then re-run this script without -ExportOnly, passing that file via -DescriptionsFile." -ForegroundColor Cyan
    exit 0
}

$descriptionOverrides = @{}
if ($DescriptionsFile) {
    if (-not (Test-Path $DescriptionsFile)) {
        throw "-DescriptionsFile '$DescriptionsFile' not found."
    }
    # -Encoding UTF8 is required here too - see the comment in Read-SourceFile. Authored
    # descriptions are free text (Step 4b) and very likely to contain an em-dash, a curly quote,
    # or similar; without this, Get-Content's system-codepage default corrupts them into mojibake
    # before they're ever sent to the registry.
    $rawDescriptions = Get-Content -Path $DescriptionsFile -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($prop in $rawDescriptions.PSObject.Properties) {
        $descriptionOverrides[$prop.Name] = $prop.Value
    }
    Write-Host "Loaded $($descriptionOverrides.Count) authored description(s) from $DescriptionsFile" -ForegroundColor Cyan
}

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

# RegistrationsBaseUrl exposes each version's publish date (catalogEntry.published) - optional,
# since publish dates are a nice-to-have, not required for the rest of the sync to work.
$registrationResource = $serviceIndex.resources | Where-Object { $_.'@type' -like 'RegistrationsBaseUrl*' } | Select-Object -First 1
$registrationBase = if ($registrationResource) { $registrationResource.'@id'.TrimEnd('/') } else { $null }
if (-not $registrationBase) {
    Write-Warning "The NuGet service index at $NugetFeedUrl has no RegistrationsBaseUrl resource - NuGet-sourced versions will have no publishedDate."
}

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
# Step 2: Authenticate against the Module Registry backend, and load its
# existing modules - done up front, before scanning any module, so each
# module can be upserted immediately after it's processed (see Step 3) rather
# than batching every Insert/Update until the very end.
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Authenticating against $BackendUrl ..." -ForegroundColor Cyan

$authBody = @{ userNameOrEmailAddress = $Username; password = $Password } | ConvertTo-Json
# Invoke-RestMethod -Body <string> on Windows PowerShell 5.1 encodes the body using the system
# codepage's "best fit" table, which silently downgrades non-ASCII characters (an em-dash becomes
# a plain hyphen, smart quotes become straight ones) rather than sending real UTF-8 - passing an
# explicit UTF-8 byte array (with a matching charset on the header) avoids that entirely.
$authResponse = Invoke-RestMethod -Uri "$BackendUrl/api/TokenAuth/Authenticate" -Method Post -Body ([System.Text.Encoding]::UTF8.GetBytes($authBody)) -ContentType "application/json; charset=utf-8"
$token = $authResponse.result.accessToken
if (-not $token) {
    throw "Authentication failed - no access token returned."
}
$headers = @{ Authorization = "Bearer $token" }

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

# ---------------------------------------------------------------------------
# Step 3: For each module, look up its published NuGet/npm packages, scan its
# source, and upsert it into the registry immediately - not after every
# module has been processed. If the job is killed mid-run, every module
# synced so far is already safely in the registry; re-running just re-syncs
# from the top, which is safe (never duplicates) since Insert-vs-Update is
# decided by an exact moduleManifestName match.
# ---------------------------------------------------------------------------

$summary = @()

foreach ($moduleName in $modules.Keys) {
    $info = $modules[$moduleName]
    Write-Host ""
    Write-Host "=== $moduleName ===" -ForegroundColor Yellow

    $versions = @{}  # versionNumber -> List[ @{dependencyName; dependencyVersion} ]
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
        } elseif ($isSheshaFrameworkRepo) {
            $nugetLocation = "https://www.nuget.org/packages/$resolvedNugetId"
        }
        Write-Host "  NuGet: $resolvedNugetId ($($index.versions.Count) version(s))" -ForegroundColor Green
        $nugetDroppedDepsCount = 0

        foreach ($version in $index.versions) {
            $versionLower = $version.ToLowerInvariant()
            $nuspecUrl = "$flatContainerBase/$idLower/$versionLower/$idLower.nuspec"
            try {
                $nuspecResponse = Invoke-RestMethod -Uri $nuspecUrl -Method Get -Headers $feedHeaders -ErrorAction Stop
                if ($nuspecResponse -is [System.Xml.XmlDocument]) {
                    # nuget.org (and possibly other feeds) serve .nuspec as Content-Type: text/xml,
                    # which Invoke-RestMethod auto-parses into an XmlDocument rather than returning
                    # the raw string - use it directly rather than running it through ToString(),
                    # which would yield the literal string "System.Xml.XmlDocument", not XML.
                    $nuspecXml = $nuspecResponse
                } else {
                    # The feed may serve this without a charset, so PowerShell can mis-decode the
                    # leading UTF-8 BOM into garbage characters that break XML parsing. Strip
                    # anything before the first '<' regardless of what it decoded to.
                    $nuspecRaw = [string]$nuspecResponse -replace '^[^<]*', ''
                    [xml]$nuspecXml = $nuspecRaw
                }
            } catch {
                Write-Warning "  Could not fetch/parse nuspec for $resolvedNugetId $version, skipping this version's dependencies"
                if (-not $versions.ContainsKey($version)) {
                    $versions[$version] = [ordered]@{
                        Dependencies  = New-Object System.Collections.Generic.List[object]
                        PublishedDate = Get-NugetPublishedDate -RegistrationBase $registrationBase -IdLower $idLower -VersionLower $versionLower -Headers $feedHeaders
                    }
                }
                continue
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
            $versions[$version] = [ordered]@{
                Dependencies  = $depList
                PublishedDate = Get-NugetPublishedDate -RegistrationBase $registrationBase -IdLower $idLower -VersionLower $versionLower -Headers $feedHeaders
            }
        }
        if ($nugetDroppedDepsCount -gt 0) {
            Write-Host "  Kept only Shesha/Boxfusion dependencies - dropped $nugetDroppedDepsCount public dependency reference(s) across all versions" -ForegroundColor DarkGray
        }
    } else {
        Write-Host "  NuGet: not published" -ForegroundColor DarkGray
    }

    # --- npm ---
    if ($info.NpmPackage) {
        $npmPackageSegment = $info.NpmPackage -replace '/', '%2f'
        $npmDoc = Invoke-JsonGet -Url "$($NpmRegistryUrl.TrimEnd('/'))/$npmPackageSegment" -Headers $feedHeaders
        if ($npmDoc -and $npmDoc.versions) {
            if ($azureOrg -and $npmAzureFeed) {
                $npmLocation = "https://dev.azure.com/$azureOrg/_artifacts/feed/$npmAzureFeed/Npm/$($info.NpmPackage)/overview"
            } elseif ($isSheshaFrameworkRepo) {
                $npmLocation = "https://www.npmjs.com/package/$($info.NpmPackage)"
            }
            $npmVersionNames = $npmDoc.versions | Get-Member -MemberType NoteProperty | ForEach-Object { $_.Name }
            Write-Host "  npm: $($info.NpmPackage) ($($npmVersionNames.Count) version(s))" -ForegroundColor Green
            $npmDroppedDepsCount = 0

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
                $npmPublishedProp = if ($npmDoc.time) { $npmDoc.time.PSObject.Properties[$versionName] } else { $null }
                $npmPublished = if ($npmPublishedProp) { $npmPublishedProp.Value } else { $null }
                if (-not $versions.ContainsKey($versionName)) {
                    $versions[$versionName] = [ordered]@{
                        Dependencies  = $depList
                        PublishedDate = $npmPublished
                    }
                } else {
                    $versions[$versionName].Dependencies.AddRange($depList)
                    # NuGet's registration date wins if both ecosystems published this version -
                    # only fall back to npm's when NuGet didn't already resolve one.
                    if (-not $versions[$versionName].PublishedDate) {
                        $versions[$versionName].PublishedDate = $npmPublished
                    }
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
                publishedDate = $versions[$versionNumber].PublishedDate
                dependencies  = $versions[$versionNumber].Dependencies
            }
        } catch {
            Write-Warning "  Skipping malformed version entry '$versionNumber' for $moduleName : $($_.Exception.Message)"
        }
    }
    # Group/order newest-first so multiple releases on the same day naturally sit together;
    # versions with no resolvable publish date sort last rather than breaking the sort.
    $versionsArray = @($versionsArray | Sort-Object -Descending -Property @{
        Expression = { if ($_.publishedDate) { [datetime]$_.publishedDate } else { [datetime]::MinValue } }
    })

    # --- Domain entities, APIs and settings, extracted from the module's own source code ---
    $fallbackRouteModuleName = ($moduleName -replace '^(shesha|boxfusion)\.', '') -replace '[^a-zA-Z0-9]', ''
    $sourceCode = Get-ModuleSourceCode -SourceFolders $info.SourceFolders -FallbackRouteModuleName $fallbackRouteModuleName -RepoPath $RepoPath -SourceRef $SourceRef

    if ($sourceCode.Entities.Count -gt 0 -or $sourceCode.Apis.Count -gt 0 -or $sourceCode.Settings.Count -gt 0 -or $sourceCode.Enums.Count -gt 0) {
        $crudApiCount = ($sourceCode.Apis | Where-Object { $_.category -eq 'Crud' }).Count
        $customApiCount = ($sourceCode.Apis | Where-Object { $_.category -eq 'Custom' }).Count
        Write-Host "  Source: $($sourceCode.Entities.Count) entity(ies), $($sourceCode.Apis.Count) API(s) [$crudApiCount CRUD / $customApiCount custom], $($sourceCode.Settings.Count) setting(s), $($sourceCode.Enums.Count) enum(s)" -ForegroundColor Green
    }

    if ($descriptionOverrides.ContainsKey($moduleName)) {
        $description = $descriptionOverrides[$moduleName]
        Write-Host "  Using authored description" -ForegroundColor Green
    } else {
        $description = Get-ModuleDescription -Entities $sourceCode.Entities -Apis $sourceCode.Apis -Settings $sourceCode.Settings -Enums $sourceCode.Enums
        if ($description) {
            Write-Host "  No authored description provided - using a mechanical fallback listing entities/APIs/settings/enums" -ForegroundColor DarkYellow
        } else {
            Write-Host "  No entities/APIs/settings/enums found in source - description left blank" -ForegroundColor DarkGray
        }
    }

    $payload = [ordered]@{
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

    # --- Upsert this module right now, rather than collecting it for a batch at the end - so a
    # kill mid-run loses at most the module currently in flight, never any module already synced.
    $key = $moduleName.ToLowerInvariant()
    $bodyJson = $payload | ConvertTo-Json -Depth 10

    try {
        if ($existingByName.ContainsKey($key)) {
            $updatePayload = [ordered]@{}
            foreach ($k in $payload.Keys) { $updatePayload[$k] = $payload[$k] }
            $updatePayload["id"] = $existingByName[$key]
            $updateJson = $updatePayload | ConvertTo-Json -Depth 10
            # See the comment on the Authenticate call above - encoding to UTF-8 bytes explicitly
            # avoids Invoke-RestMethod's lossy system-codepage "best fit" string encoding, which
            # would otherwise silently mangle any non-ASCII text (e.g. an authored description
            # containing an em-dash or curly quotes) before it reaches the registry.
            $response = Invoke-RestMethod -Uri "$BackendUrl/api/services/ModuleRegistry/ModuleInfoSearch/Update" -Method Put -Headers $headers -Body ([System.Text.Encoding]::UTF8.GetBytes($updateJson)) -ContentType "application/json; charset=utf-8"
            $action = "Updated"
        } else {
            $response = Invoke-RestMethod -Uri "$BackendUrl/api/services/ModuleRegistry/ModuleInfoSearch/Insert" -Method Post -Headers $headers -Body ([System.Text.Encoding]::UTF8.GetBytes($bodyJson)) -ContentType "application/json; charset=utf-8"
            $action = "Created"
        }

        if ($response.success) {
            Write-Host "  Synced ($action)" -ForegroundColor Green
            $summary += [ordered]@{ Module = $payload.moduleManifestName; Action = $action; Versions = $payload.versions.Count; Entities = $payload.entities.Count; Apis = $payload.apis.Count; Settings = $payload.settings.Count; Enums = $payload.enums.Count; Detail = "" }
        } else {
            Write-Host "  Sync failed: $($response.error.message)" -ForegroundColor Red
            $summary += [ordered]@{ Module = $payload.moduleManifestName; Action = "Failed"; Versions = $payload.versions.Count; Entities = $payload.entities.Count; Apis = $payload.apis.Count; Settings = $payload.settings.Count; Enums = $payload.enums.Count; Detail = $response.error.message }
        }
    } catch {
        Write-Host "  Sync failed: $($_.Exception.Message)" -ForegroundColor Red
        $summary += [ordered]@{ Module = $payload.moduleManifestName; Action = "Failed"; Versions = $payload.versions.Count; Entities = $payload.entities.Count; Apis = $payload.apis.Count; Settings = $payload.settings.Count; Enums = $payload.enums.Count; Detail = $_.Exception.Message }
    }
}

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
$summary | ForEach-Object {
    $color = switch ($_.Action) { "Created" { "Green" }; "Updated" { "Yellow" }; default { "Red" } }
    Write-Host ("{0,-10} {1,-30} {2,3} version(s)  {3,3} entities  {4,3} APIs  {5,3} settings  {6,3} enums  {7}" -f $_.Action, $_.Module, $_.Versions, $_.Entities, $_.Apis, $_.Settings, $_.Enums, $_.Detail) -ForegroundColor $color
}
