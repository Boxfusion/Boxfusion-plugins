---
name: document-shaconfigs
description: Documents Shesha .shaconfig configuration packages by extracting their contents and generating a CSV inventory report. Use when asked to document, inventory, audit, list, or report on .shaconfig files, Shesha configuration packages, or Shesha configuration items (forms, permission definitions, reference lists, etc.).
---

# Document Shaconfigs

Generate a CSV inventory report of all `.shaconfig` files in the project by extracting and analysing their contents.

## Background

A `.shaconfig` file is a ZIP archive of Shesha framework configuration items. Each entry inside is a JSON file whose path follows the pattern:

```
{module}/{type}/{name}.json
```

JSON fields used for reporting:

| JSON field    | Meaning                                         | Example                       |
|---------------|-------------------------------------------------|-------------------------------|
| `ModuleName`  | Shesha module the item belongs to               | `boxfusion.content`           |
| `ItemType`    | Configuration item type                         | `form`, `permission-definition`, `reference-list` |
| `Name`        | Programmatic name                               | `ManageContentLibraries`      |
| `Label`       | Human-readable display label                   | `Manage Content Libraries`    |

Source-controlled `.shaconfig` files live in `Config_Packages/` directories and are embedded as `EmbeddedResource` in `.csproj` files. **Exclude** runtime-uploaded copies found under `App_Data/Upload/` and build output under `bin/` or `obj/`.

## Workflow

### Step 1: Determine project root

Use the current working directory or ask the user if ambiguous. Typically the root of the repository (e.g. `C:/Projects/Boxfusion/pd-content`).

### Step 2: Write the extraction script to disk

Write the script from [scripts/extract-shaconfig.ps1](scripts/extract-shaconfig.ps1) to:

```
{projectRoot}/.claude/skills/document-shaconfigs/scripts/extract-shaconfig.ps1
```

The script is already present in this skill directory — no need to recreate it unless it is missing.

### Step 3: Run the script

```powershell
powershell -ExecutionPolicy Bypass -File ".claude/skills/document-shaconfigs/scripts/extract-shaconfig.ps1" `
  -ProjectRoot "{projectRoot}" `
  -OutputCsv "shaconfig-report.csv"
```

The script will:
1. Find all `.shaconfig` files (excluding `App_Data/Upload/`, `bin/`, `obj/`)
2. Copy and extract each one to a temp directory
3. Parse every JSON file inside
4. Write a CSV to `shaconfig-report.csv` in the current directory
5. Print a summary with item counts broken down by type
6. Clean up the temp directory

### Step 4: Read and present results

After the script completes:
1. Read `shaconfig-report.csv` using the Read tool
2. Display a summary table to the user showing:
   - Total `.shaconfig` files found
   - Total configuration items
   - Counts per type (forms, permission-definitions, reference-lists, etc.)
   - Counts per project
3. Show the path to the generated CSV

## CSV Output Columns

| Column         | Source       | Description                                              |
|----------------|--------------|----------------------------------------------------------|
| `ShaConfigFile`| File name    | The `.shaconfig` filename                                |
| `Project`      | File path    | The .NET project folder containing the file              |
| `Folder`       | File path    | Relative folder path within the project root             |
| `Module`       | JSON field   | Shesha module name (e.g. `boxfusion.content`)            |
| `Type`         | JSON field   | Item type (e.g. `form`, `permission-definition`)         |
| `Name`         | JSON field   | Programmatic item name                                   |
| `Label`        | JSON field   | Human-readable display label                             |

## Key Rules

- **Always exclude** `App_Data/Upload/` — runtime-uploaded files, not source-controlled config
- **Always exclude** `bin/` and `obj/` — build output copies
- The output CSV is written to the **current working directory** by default
- If the script fails to extract a file it logs a warning and continues — check warnings in output
- On Windows use `powershell` or `pwsh`; the script uses `Expand-Archive` (requires PowerShell 5+)

Now run the documentation based on: $ARGUMENTS
