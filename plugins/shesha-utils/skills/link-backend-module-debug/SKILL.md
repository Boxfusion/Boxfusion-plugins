---
name: link-backend-module-debug
description: Links a Shesha backend module as a local project reference for debugging, or unlinks it back to NuGet. Reads Directory.Build.props to detect available modules, creates or updates a Debug solution file, toggles UseLocal* flags, and wraps PackageReference entries in MSBuild Choose/When/Otherwise conditional blocks. Use when asked to "link module for debug", "debug shesha locally", "add project reference for debugging", "switch to local project reference", or "unlink module".
---

# Link Backend Module for Debug

Switch a Shesha backend NuGet dependency to a local project reference for debugging using the MSBuild `Choose/When/Otherwise` conditional pattern controlled by `UseLocal*` flags in `Directory.Build.props`.

## Workflow

### Step 1 — Read Directory.Build.props

Read `backend/Directory.Build.props`. Extract:
- All `<*Version>` properties (these identify available modules)
- All `<UseLocal*>` flags and their current values (`true`/`false`)

Build a module list pairing each `UseLocal*` flag with its version property/properties.

### Step 2 — Present options and confirm mode

Show the user a table of detected modules with their current `UseLocal*` status. Ask:
1. Which module to link (or unlink)?
2. Link (enable local project references) or Unlink (revert to NuGet)?

### Step 3 — Ensure Debug solution exists

Check `backend/` for a `*.Debug.sln` file.
- **If none exists**: copy the production `.sln` file to `{SolutionName}.Debug.sln` (read the `.sln`, write to the new name — never modify the production `.sln`).
- **If it exists**: open it for editing.

### Step 4 — Ask for sibling repo path (link only)

Ask: "What is the path to the `{module}` repository relative to the `backend/` folder?"
- Example for Chat: `../../pd-chat` (so `backend/../../pd-chat` = sibling of the project root)
- Use this path to locate the module's `.csproj` files at `{siblingPath}/backend/src/Module/*/`

### Step 5 — Update Directory.Build.props

**Link**: set `<UseLocal{Module}>true</UseLocal{Module}>`
**Unlink**: set `<UseLocal{Module}>false</UseLocal{Module}>`

If the `UseLocal*` property doesn't exist yet, add it to the `<PropertyGroup>` with a comment: `<!-- Always change to false before pushing/committing -->`

### Step 6 — Update Debug solution file (link only)

Find all `.csproj` files in `{siblingPath}/backend/src/Module/`. For each one, add to the Debug `.sln`:
1. A `Project(...)` line — see [patterns.md](patterns.md) §2
2. Config entries in `GlobalSection(ProjectConfigurationPlatforms)` for Debug, DebugLocalShesha, and Release
3. A `NestedProjects` entry linking it to the module's solution folder

Also add the solution folder entry (`{2150E333-8FDC-42A3-9474-1A3956D46DE8}`) if not already present.

Generate new GUIDs for any new entries (uppercase, format `{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}`).

### Step 7 — Update .csproj files

Scan `backend/src/**/*.csproj` for `<PackageReference>` entries whose `Version` attribute references the module's version variable (e.g., `Version="$(ChatVersion)"`).

For each affected `.csproj`:
- **If a `<Choose>` block already exists** for this module's flag: update the `<When>` `<ItemGroup>` with `<ProjectReference>` paths pointing to `{siblingPath}/backend/src/Module/{ProjectName}/{ProjectName}.csproj`. Paths must be relative from the `.csproj` file's location.
- **If no `<Choose>` block exists**: extract the matching `<PackageReference>` entries from their `<ItemGroup>`, wrap them in a `<Choose>/<When>/<Otherwise>` block. See [patterns.md](patterns.md) §1.

### Step 8 — Report

List all files modified. Remind the user:
> **Remember to set `UseLocal{Module}` back to `false` in `Directory.Build.props` before pushing or committing.**

## Key rules

- Never modify the production `.sln` — only the `.Debug.sln`.
- Project reference paths in `.csproj` must be relative from that `.csproj`'s directory to the target `.csproj`.
- The `<Otherwise>` block must preserve exact original `<PackageReference>` entries with their `Version="$(VarName)"` references.
- The `UseLocal*` flag name must exactly match what appears in the `<When Condition>` in `.csproj` files.
- External projects in the solution use type GUID `{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}`.
- Solution folders use type GUID `{2150E333-8FDC-42A3-9474-1A3956D46DE8}`.

## Module map (this project)

| UseLocal Flag | Version Property/ies | Packages pattern | Sibling repo |
|---|---|---|---|
| `UseLocalChat` | `ChatVersion`, `SheshaSignalRVersion` | `boxfusion.chat.*`, `Shesha.SignalR`, `Boxfusion.BotMiddleware`, etc. | `pd-chat` |

Now execute the link/unlink workflow based on: $ARGUMENTS
