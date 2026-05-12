# extract-shaconfig.ps1
# Finds all .shaconfig files in a project, extracts their contents, and generates a CSV report.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File extract-shaconfig.ps1 [-ProjectRoot <path>] [-OutputCsv <path>]
#
# Parameters:
#   -ProjectRoot  Root directory to search (default: current directory)
#   -OutputCsv    Output CSV file path (default: shaconfig-report.csv in current directory)

param(
    [string]$ProjectRoot = (Get-Location).Path,
    [string]$OutputCsv = "shaconfig-report.csv"
)

$TempDir = Join-Path $env:TEMP "shaconfig-extract-$(Get-Random)"

# --- Cleanup on exit ---
trap {
    if (Test-Path $TempDir) { Remove-Item -Recurse -Force $TempDir -ErrorAction SilentlyContinue }
}

# --- Setup temp dir ---
New-Item -ItemType Directory -Path $TempDir | Out-Null
Write-Host "Temp dir: $TempDir"

# --- Exclusion patterns ---
$excludeSegments = @(
    "App_Data\Upload",
    "App_Data/Upload",
    [System.IO.Path]::Combine("bin", ""),
    [System.IO.Path]::Combine("obj", "")
)

function Should-Exclude($path) {
    foreach ($seg in $excludeSegments) {
        if ($path -like "*$seg*") { return $true }
    }
    return $false
}

# --- Find .shaconfig files ---
Write-Host "Searching for .shaconfig files in: $ProjectRoot"
$shaconfigFiles = Get-ChildItem -Path $ProjectRoot -Recurse -Filter "*.shaconfig" -ErrorAction SilentlyContinue |
    Where-Object { -not (Should-Exclude $_.FullName) }

Write-Host "Found $($shaconfigFiles.Count) .shaconfig file(s) (excluding Upload/bin/obj)"

# --- Helper: extract project name from path ---
function Get-ProjectName($filePath, $root) {
    $rel = $filePath.Replace($root, "").TrimStart([System.IO.Path]::DirectorySeparatorChar, '/')
    $parts = $rel -split "[/\\]"
    # Walk parts looking for a segment containing a dot (likely a .NET project name)
    foreach ($part in $parts) {
        if ($part -match "\." -and $part -notmatch "^(shaconfig|config|packages?)$") {
            return $part
        }
    }
    # Fallback: return immediate parent folder
    return Split-Path (Split-Path $filePath -Parent) -Leaf
}

function Get-RelativeFolder($filePath, $root) {
    $dir  = (Split-Path $filePath -Parent).Replace('/', '\').TrimEnd('\')
    $base = $root.Replace('/', '\').TrimEnd('\')
    if ($dir.StartsWith($base, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $dir.Substring($base.Length).TrimStart('\', '/')
    }
    return $dir
}

# --- Process each .shaconfig ---
$results = [System.Collections.Generic.List[PSCustomObject]]::new()
$filesProcessed = 0
$filesErrored = 0

foreach ($file in $shaconfigFiles) {
    $project = Get-ProjectName $file.FullName $ProjectRoot
    $folder   = Get-RelativeFolder $file.FullName $ProjectRoot

    $extractPath = Join-Path $TempDir $file.BaseName
    New-Item -ItemType Directory -Path $extractPath -Force | Out-Null

    # Expand-Archive only accepts .zip extension — copy with .zip suffix first
    $zipCopy = Join-Path $TempDir "$($file.BaseName).zip"
    Copy-Item -Path $file.FullName -Destination $zipCopy -Force

    try {
        Expand-Archive -Path $zipCopy -DestinationPath $extractPath -Force
        $filesProcessed++
    } catch {
        Write-Warning "Could not extract '$($file.Name)': $_"
        $filesErrored++
        continue
    } finally {
        Remove-Item $zipCopy -ErrorAction SilentlyContinue
    }

    $jsonFiles = Get-ChildItem -Path $extractPath -Recurse -Filter "*.json" -ErrorAction SilentlyContinue

    foreach ($jsonFile in $jsonFiles) {
        try {
            $content = Get-Content $jsonFile.FullName -Raw | ConvertFrom-Json

            $results.Add([PSCustomObject]@{
                ShaConfigFile = $file.Name
                Project       = $project
                Folder        = $folder
                Module        = $content.ModuleName
                Type          = $content.ItemType
                Name          = $content.Name
                Label         = $content.Label
            })
        } catch {
            Write-Warning "Could not parse JSON '$($jsonFile.FullName)': $_"
        }
    }
}

# --- Export CSV ---
$results | Export-Csv -Path $OutputCsv -NoTypeInformation -Encoding UTF8

# --- Summary ---
Write-Host ""
Write-Host "=========================================="
Write-Host "  shaconfig Report"
Write-Host "=========================================="
Write-Host "  .shaconfig files found:     $($shaconfigFiles.Count)"
Write-Host "  .shaconfig files extracted: $filesProcessed"
if ($filesErrored -gt 0) {
    Write-Host "  .shaconfig files errored:  $filesErrored"
}
Write-Host "  Total config items:         $($results.Count)"
Write-Host ""

# Breakdown by type
$results | Group-Object Type | Sort-Object Count -Descending | ForEach-Object {
    Write-Host ("  {0,-30} {1,4}" -f $_.Name, $_.Count)
}

Write-Host ""
Write-Host "  Output CSV: $OutputCsv"
Write-Host "=========================================="

# --- Cleanup ---
Remove-Item -Recurse -Force $TempDir -ErrorAction SilentlyContinue
