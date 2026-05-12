<#
.SYNOPSIS
    Ensures required entries are present in .gitignore.
.DESCRIPTION
    Reads the .gitignore file, checks for each required entry,
    and appends any missing entries grouped by section.
    Outputs structured JSON for Claude to parse.
.PARAMETER ProjectRoot
    The root directory of the project. Defaults to current directory.
#>
param(
    [string]$ProjectRoot = (Get-Location).Path
)

$ErrorActionPreference = 'Stop'

$sections = @(
    @{
        Header  = '# General'
        Entries = @(
            'nul',
            '.claude/settings.local.json'
        )
    },
    @{
        Header  = '# Local dev credentials'
        Entries = @(
            '.sheshadev.local.json'
        )
    },
    @{
        Header  = '# Backend build and IDE artifacts'
        Entries = @(
            'backend/**/.vs/',
            'backend/**/bin/',
            'backend/**/obj/',
            'backend/**/*.user',
            'backend/**/*.suo',
            'backend/**/*.sln.docstates',
            'backend/**/TestResults/',
            'backend/**/_ReSharper*/',
            'backend/**/.idea/',
            'backend/**/.vscode/',
            'backend/**/app_data/'
        )
    }
)

$result = @{
    success     = $false
    added       = @()
    alreadyPresent = @()
    message     = ''
}

try {
    $gitignorePath = Join-Path $ProjectRoot '.gitignore'

    # Read existing content or start empty
    $existingLines = @()
    if (Test-Path $gitignorePath) {
        $existingLines = @(Get-Content $gitignorePath)
    }

    # Normalize existing entries for comparison (trim whitespace)
    $existingSet = @{}
    foreach ($line in $existingLines) {
        $trimmed = $line.Trim()
        if ($trimmed -ne '') {
            $existingSet[$trimmed] = $true
        }
    }

    $toAppend = @()

    foreach ($section in $sections) {
        $sectionMissing = @()
        foreach ($entry in $section.Entries) {
            if ($existingSet.ContainsKey($entry)) {
                $result.alreadyPresent += $entry
            }
            else {
                $sectionMissing += $entry
                $result.added += $entry
            }
        }

        if ($sectionMissing.Count -gt 0) {
            # Add section header if not already present
            if (-not $existingSet.ContainsKey($section.Header)) {
                $toAppend += ''
                $toAppend += $section.Header
            }
            $toAppend += $sectionMissing
        }
    }

    if ($toAppend.Count -gt 0) {
        # Ensure file ends with newline before appending
        if ($existingLines.Count -gt 0) {
            $lastLine = $existingLines[$existingLines.Count - 1]
            if ($lastLine.Trim() -ne '') {
                $toAppend = @('') + $toAppend
            }
        }

        Add-Content -Path $gitignorePath -Value ($toAppend -join "`n") -Encoding UTF8 -NoNewline
        # Add trailing newline
        Add-Content -Path $gitignorePath -Value '' -Encoding UTF8
        $result.message = "Added $($result.added.Count) entries to .gitignore"
    }
    else {
        $result.message = 'All entries already present in .gitignore'
    }

    $result.success = $true

} catch {
    $result.message = "Error: $($_.Exception.Message)"
}

$result | ConvertTo-Json -Depth 3
