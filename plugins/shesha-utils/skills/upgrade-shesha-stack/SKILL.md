---
name: upgrade-shesha-stack
description: Upgrades Shesha framework dependencies in both frontend and backend projects to a specified BoxStack version. Handles monorepo and standard project structures. Use when user wants to upgrade, update, or migrate Shesha/BoxStack versions.
---

# Upgrade Shesha Stack

Upgrade Shesha framework dependencies to a specified BoxStack version across frontend (React) and backend (.NET) projects.

## Instructions

This skill performs a coordinated upgrade of Shesha dependencies across your entire stack:

1. **Ask for target BoxStack version** using AskUserQuestion
2. **Read version mappings** from local ModulesAirtable.csv file
3. **Upgrade frontend** packages in `/adminportal` folder (using Shesha.Enterprise version)
4. **Upgrade backend** packages in `/backend` folder (using Shesha.Core version)
5. **Verify and report** all changes made
6. **Build backend** and investigate any build errors

### Key Rules

- Always ask user for target BoxStack version before proceeding
- Read version mappings from `ModulesAirtable.csv` in the skill's directory
- Frontend: Update `@shesha-io/reactjs` to the Shesha.Enterprise version from CSV
- Backend: Update `SheshaVersion` to the Shesha.Core version from CSV
- Only modify `directory.build.props` for backend, never individual `.csproj` files
- Handle both monorepo (with `packages/` subfolder) and standard structures
- Check for package-lock.json or yarn.lock to determine package manager
- Report all version changes clearly

## Workflow

### Step 1: Ask for Target BoxStack Version

Use `AskUserQuestion` to get the desired BoxStack version:

```
What BoxStack version would you like to upgrade to?
Example: 37, 36, 35, etc. (or BoxStack-37, BoxStack-36, etc.)
```

### Step 2: Read Version Mappings from CSV

1. **Locate the CSV file:**
   - Path: `plugins/shesha-developer/skills/upgrade-shesha-stack/ModulesAirtable.csv`
   - This file contains BoxStack version mappings

2. **Find the BoxStack entry:**
   - Search for the row where Module="BoxStack" and Release No matches the user's version
   - Example: For BoxStack 37, find the row with Module="BoxStack" and Release No="37"

3. **Parse ALL Dependencies from the field:**
   - The Dependencies field contains a comma-separated list of ALL packages in this BoxStack release
   - Extract each dependency in format: `PackageName-Version`
   - Example from BoxStack-37: `Shesha.Core-0.43.25,boxfusion.devexpressreporting-2.6.14,Shesha.Enterprise-5.0.14,Boxfusion.PublicPortal-0.8.16`

   **Key dependencies to extract:**
   - **Shesha.Core version** (backend core): `0.43.25`
   - **Shesha.Enterprise version** (frontend): `5.0.14`
   - **boxfusion.devexpressreporting version** (if present): `2.6.14`
   - **Boxfusion.PublicPortal version** (if present): `0.8.16`
   - Any other Boxfusion.* or Shesha.* packages

4. **Create a version map:**
   - Build a dictionary of package names to versions
   - Use this map to update all matching dependencies in both frontend and backend

5. **Package name mapping (CSV → NuGet/npm):**
   - `Shesha.Core-X.X.X` → Backend NuGet: Use version for `SheshaVersion` property
   - `Shesha.Enterprise-X.X.X` → Frontend npm: Use version for `@shesha-io/reactjs`
   - `boxfusion.devexpressreporting-X.X.X` → Backend NuGet: `Boxfusion.DevExpressReporting` version X.X.X
   - `Boxfusion.PublicPortal-X.X.X` → Backend NuGet: `Boxfusion.PublicPortal` version X.X.X
   - **Pattern:** Convert lowercase package names to PascalCase for NuGet packages

**CSV Structure:**
- Name: Full package name with version (e.g., "BoxStack-37")
- Module: Module name (e.g., "BoxStack")
- Release No: Version number (e.g., "37")
- Dependencies: Comma-separated list of ALL dependencies with versions in the BoxStack release

**Fallback:** If BoxStack version not found in CSV, list available BoxStack versions and ask user to choose a valid one.

### Step 3: Upgrade Frontend Dependencies

**Location:** `/adminportal` folder

1. **Find ALL package.json files using Glob tool:**
   - **CRITICAL:** Use Glob to search for all package.json files, don't assume locations
   - Search patterns to use:
     - `adminportal/package.json` (main)
     - `adminportal/packages/*/package.json` (monorepo subprojects)
     - `adminportal/packages/*/*/package.json` (nested subprojects)
   - **List all found files** before starting updates to ensure nothing is missed
   - Common locations:
     - Main: `adminportal/package.json`
     - Subprojects: `adminportal/packages/app1/package.json`, `adminportal/packages/app2/package.json`, etc.

2. **For EACH package.json file found, perform the following updates:**

3. **Update `@shesha-io/reactjs`:**
   - Set to the Shesha.Enterprise version from CSV (Step 2)
   - Example: For BoxStack-37 with Shesha.Enterprise-5.0.14: `"@shesha-io/reactjs": "5.0.14"`
   - **Note:** `@shesha-io/reactjs` is the main frontend package (NOT `@shesha-io/enterprise`)

4. **Update other `@shesha-io/*` packages in both `dependencies` AND `devDependencies`:**
   - Find all dependencies starting with `@shesha-io/` in both sections
   - Update to the same Shesha.Enterprise version or compatible versions
   - **IMPORTANT:** Check BOTH `dependencies` and `devDependencies` sections
   - Check npm registry or use `npm view @shesha-io/{package} peerDependencies` if needed

5. **Verify all files were updated:**
   - After updates, list all package.json files that were modified
   - Ensure count matches the number found in step 1
   - If any files were skipped, update them explicitly

6. **Determine package manager:**
   - Check in main `adminportal` directory
   - If `package-lock.json` exists → npm
   - If `yarn.lock` exists → yarn
   - If `pnpm-lock.yaml` exists → pnpm

7. **Note the detected package manager** for use in Step 5a if the user opts to install dependencies.

**Packages to update (typical list):**
- `@shesha-io/reactjs` (main frontend framework - use Shesha.Enterprise version)
- `@shesha-io/pd-publicholidays`
- `@shesha-io/pd-core`
- Any other `@shesha-io/*` packages found in `dependencies` or `devDependencies` (update to compatible versions)

**Critical Notes:**
- **Must update ALL package.json files**, including those in `adminportal/packages/` subdirectories
- Always check BOTH `dependencies` and `devDependencies` sections for `@shesha-io/*` packages
- Use Glob tool to discover all package.json files - don't rely on assumptions about structure

### Step 4: Upgrade Backend Dependencies

**Location:** `/backend` folder

1. **Find directory.build.props:**
   - Path: `backend/directory.build.props`
   - This file contains centralized version management for all NuGet packages
   - Reference: See `plugins/shesha-developer/skills/create-module/reference/ProjectFiles.md` for structure

2. **Update Shesha version property:**
   - Look for property like `<SheshaVersion>X.X.X</SheshaVersion>`
   - Update to the Shesha.Core version from CSV (Step 2)
   - Example: For BoxStack-37 with Shesha.Core-0.43.25: `<SheshaVersion>0.43.25</SheshaVersion>`

3. **Update Shesha package references:**
   - Find all `<PackageReference>` elements with `Include` or `Update` starting with `Shesha.*`
   - Ensure they reference `$(SheshaVersion)` variable
   - **IMPORTANT:** Only modify versions in `directory.build.props`, NOT in `.csproj` files

4. **Update Boxfusion package references:**
   - Find all `<PackageReference>` elements for Boxfusion packages
   - Update to the versions specified in BoxStack Dependencies (Step 2)
   - Common packages (update if present):
     - `Boxfusion.DevExpressReporting` → Use `boxfusion.devexpressreporting` version from BoxStack
     - `Boxfusion.PublicPortal` → Use `Boxfusion.PublicPortal` version from BoxStack
     - Any other `Boxfusion.*` packages found in BoxStack Dependencies

5. **Version property patterns:**
   - Shesha packages use: `Version="$(SheshaVersion)"`
   - Boxfusion packages use: Explicit version or separate property (e.g., `Version="2.6.14"`)

**Example for BoxStack-37:**
- `SheshaVersion`: `0.43.25`
- `Boxfusion.DevExpressReporting`: `2.6.14` (from `boxfusion.devexpressreporting-2.6.14`)
- `Boxfusion.PublicPortal`: `0.8.16` (from `Boxfusion.PublicPortal-0.8.16`)

**Example directory.build.props structure:**

```xml
<Project>
  <PropertyGroup>
    <SheshaVersion>0.43.25</SheshaVersion>
  </PropertyGroup>

  <ItemGroup>
    <!-- Shesha packages use $(SheshaVersion) -->
    <PackageReference Update="Shesha.Application" Version="$(SheshaVersion)" />
    <PackageReference Update="Shesha.Core" Version="$(SheshaVersion)" />
    <PackageReference Update="Shesha.Framework" Version="$(SheshaVersion)" />
    <PackageReference Update="Shesha.NHibernate" Version="$(SheshaVersion)" />

    <!-- Boxfusion packages use explicit versions from BoxStack -->
    <PackageReference Update="Boxfusion.DevExpressReporting" Version="2.6.14" />
    <PackageReference Update="Boxfusion.PublicPortal" Version="0.8.16" />
  </ItemGroup>
</Project>
```

### Step 5: Verify and Report

After making changes:

1. **List all files modified:**
   - **Frontend:** List ALL package.json files updated with their paths
     - Example: Updated 3 files: `adminportal/package.json`, `adminportal/packages/app1/package.json`, `adminportal/packages/app2/package.json`
   - **Backend:** List directory.build.props path
   - **CRITICAL:** Verify the count matches the number found in Step 3

2. **Show version changes:**
   - Before → After for each package
   - **Frontend changes (per file):**
     - `@shesha-io/reactjs: 5.0.13 → 5.0.14` (Shesha.Enterprise version)
     - Other `@shesha-io/*` packages updated in both `dependencies` and `devDependencies`
     - Show file path for each set of changes
   - **Backend changes:**
     - `SheshaVersion: 0.43.24 → 0.43.25` (Shesha.Core version)
     - `Boxfusion.DevExpressReporting: 2.6.13 → 2.6.14` (if present)
     - `Boxfusion.PublicPortal: 0.8.15 → 0.8.16` (if present)
     - Any other Boxfusion packages updated
   - Show the BoxStack version and all dependency versions from the release

3. **Summary format:**
   ```
   Upgraded to BoxStack-37:
   - Frontend: Updated 3 package.json files to Shesha.Enterprise 5.0.14
     - adminportal/package.json
     - adminportal/packages/app1/package.json
     - adminportal/packages/app2/package.json
   - Backend: Shesha.Core 0.43.25
   - Additional modules:
     - Boxfusion.DevExpressReporting 2.6.14
     - Boxfusion.PublicPortal 0.8.16
   ```

4. **Ask about next steps using `AskUserQuestion` (multi-select):**

   Present the following options and let the user choose one or more:
   - **Install frontend dependencies** — Run `npm install` (or `yarn`/`pnpm`) in `adminportal`
   - **Build backend** — Run `dotnet restore` + `dotnet build` and resolve any errors

   Only perform the selected actions. Proceed to the relevant sub-steps below based on the user's choices.

#### Step 5a: Install Frontend Dependencies (if selected)

Run the appropriate install command in the `adminportal` folder based on the lock file detected in Step 3:
- npm: `cd adminportal && npm install`
- yarn: `cd adminportal && yarn install`
- pnpm: `cd adminportal && pnpm install`

Report the outcome (success or errors).

### Step 6: Build and Verify Backend (if selected)

After updating backend dependencies, build the solution to catch any breaking changes or compatibility issues.

**Location:** `/backend` folder

1. **Restore NuGet packages:**
   ```bash
   cd backend
   dotnet restore
   ```

2. **Build the entire solution:**
   ```bash
   dotnet build
   ```
   - This will compile all projects in the solution
   - Build output will show any compilation errors or warnings

3. **Investigate build errors (if any occur):**

   **Common error types after version upgrade:**

   a. **Missing or obsolete APIs:**
      - Error: "does not contain a definition for..."
      - Error: "is obsolete"
      - **Action:** Read the error message carefully
      - Check Shesha/BoxStack release notes for breaking changes
      - Update code to use new API patterns

   b. **Namespace changes:**
      - Error: "type or namespace name could not be found"
      - **Action:** Add missing `using` statements or update namespace references

   c. **Package version conflicts:**
      - Warning: "Package X depends on Y >= Z"
      - **Action:** Update related packages in `directory.build.props` to compatible versions

   d. **Migration or configuration issues:**
      - Errors in migration files or startup configuration
      - **Action:** Review migration code and update to match new framework patterns

4. **For each build error found:**
   - Read the full error message and file path
   - Use Read tool to examine the affected file
   - Identify if it's a breaking change from the version upgrade
   - Fix the issue or report it to the user with recommendations

5. **Report build results:**
   - If build succeeds: "✓ Backend build successful - no errors found"
   - If build fails: List all errors with file paths and recommendations for fixes
   - Show any warnings that might indicate potential issues

6. **Final recommendations:**
   - Test the application thoroughly
   - Review breaking changes in BoxStack/Shesha release notes
   - Check if any database migrations need to be applied

## Quick Reference

### Frontend Files to Update

| File | Purpose | Pattern |
|------|---------|---------|
| `adminportal/package.json` | Main frontend dependencies and devDependencies | `@shesha-io/*` packages in both `dependencies` and `devDependencies` sections |
| `adminportal/packages/*/package.json` | Monorepo subprojects (first level) | `@shesha-io/*` packages in both `dependencies` and `devDependencies` |
| `adminportal/packages/*/*/package.json` | Nested subprojects (if exists) | `@shesha-io/*` packages in both `dependencies` and `devDependencies` |

**Important:** Use Glob tool with pattern `adminportal/**/package.json` to find ALL package.json files recursively.

### Backend Files to Update and Verify

| File | Purpose | Pattern |
|------|---------|---------|
| `backend/directory.build.props` | Centralized NuGet versions | `Shesha.*` with `$(SheshaVersion)`, `Boxfusion.*` with explicit versions |
| `backend/*.sln` | Solution file for building | Used by `dotnet build` command |

**Post-Update:** Backend solution must be built to verify compatibility and catch breaking changes.

### Version Property Patterns

**Frontend (package.json):**
```json
{
  "dependencies": {
    "@shesha-io/reactjs": "5.0.14",
    "@shesha-io/pd-publicholidays": "^5.0.14"
  },
  "devDependencies": {
    "@shesha-io/pd-core": "^5.0.14"
  }
}
```

**Backend (directory.build.props):**
```xml
<PropertyGroup>
  <SheshaVersion>0.43.25</SheshaVersion>
</PropertyGroup>
<ItemGroup>
  <!-- Shesha packages -->
  <PackageReference Update="Shesha.Application" Version="$(SheshaVersion)" />
  <PackageReference Update="Shesha.Core" Version="$(SheshaVersion)" />
  <PackageReference Update="Shesha.Framework" Version="$(SheshaVersion)" />
  <PackageReference Update="Shesha.NHibernate" Version="$(SheshaVersion)" />

  <!-- Boxfusion packages from BoxStack -->
  <PackageReference Update="Boxfusion.DevExpressReporting" Version="2.6.14" />
  <PackageReference Update="Boxfusion.PublicPortal" Version="0.8.16" />
</ItemGroup>
```

**Version Mapping Example (BoxStack-37):**
- BoxStack version: 37
- Frontend uses Shesha.Enterprise version: 5.0.14
- Backend uses Shesha.Core version: 0.43.25
- Additional dependencies:
  - Boxfusion.DevExpressReporting: 2.6.14
  - Boxfusion.PublicPortal: 0.8.16

**Note:** BoxStack releases coordinate versions across multiple packages (Shesha.Core, Shesha.Enterprise, Boxfusion.* modules).

## Safety Checks

Before proceeding:
- [ ] Backup current versions (or ensure git is clean)
- [ ] Verify BoxStack version exists in ModulesAirtable.csv
- [ ] Verify target Shesha.Core and Shesha.Enterprise versions exist on npm and NuGet
- [ ] Check for breaking changes in BoxStack release notes
- [ ] Ensure no uncommitted changes (recommend `git status`)

After upgrading:
- [ ] Run `npm install` / `yarn install` in adminportal
- [ ] Run `dotnet restore` in backend
- [ ] Run `dotnet build` in backend
- [ ] Investigate and fix any compilation errors
- [ ] Review breaking changes and update code as needed
- [ ] Run tests if available
- [ ] Verify `@shesha-io/reactjs` is properly installed
- [ ] Verify backend builds successfully without errors

## Error Handling

**If BoxStack version not found in CSV:**
- Read the CSV file and list available BoxStack versions
- Show the most recent BoxStack versions (e.g., BoxStack-37, BoxStack-36, BoxStack-35)
- Ask user to confirm or provide a valid BoxStack version

**If version not found on npm or NuGet:**
- Inform user that the Shesha.Core or Shesha.Enterprise version doesn't exist
- Ask user to verify the BoxStack version or provide alternative versions
- Check available versions: `npm view @shesha-io/reactjs versions` or NuGet package page

**If ModulesAirtable.csv not found:**
- The file should be at `plugins/shesha-developer/skills/upgrade-shesha-stack/ModulesAirtable.csv`
- Ask user to provide the BoxStack version mappings manually
- User should specify both Shesha.Core and Shesha.Enterprise versions

**If package.json not found:**
- Verify `/adminportal` path exists
- Check if frontend is in different location
- Use Glob tool to search for all package.json files: `**/package.json`

**If subproject package.json files are missed:**
- Use Glob tool with pattern: `adminportal/**/package.json` to find all files recursively
- Verify each found file contains `@shesha-io/*` dependencies before updating
- List all files that will be updated before making changes

**If directory.build.props not found:**
- Verify `/backend` path exists
- Check if using different versioning strategy
- Look for individual `.csproj` files (warn user about manual update needed)

**If version mismatch errors:**
- Check peer dependencies
- Verify version compatibility
- Suggest using exact versions instead of ranges

**If backend build fails after upgrade:**
- Carefully read all error messages and warnings
- Identify which files have errors (use file paths from error messages)
- Use Read tool to examine affected files
- Common fixes:
  - Update obsolete API calls to new patterns
  - Add missing using statements
  - Update configuration code to match new framework version
  - Fix migration files if necessary
- Check BoxStack/Shesha release notes for documented breaking changes
- Report unresolved errors to user with context and recommendations

## Example Usage

**User request:** "Upgrade to BoxStack version 37"

**Workflow:**
1. Ask: "Confirm upgrade to BoxStack 37?"
2. Read `ModulesAirtable.csv` and find BoxStack-37 entry
3. Parse Dependencies:
   - `Shesha.Core-0.43.25`
   - `Shesha.Enterprise-5.0.14`
   - `boxfusion.devexpressreporting-2.6.14`
   - `Boxfusion.PublicPortal-0.8.16`
4. Use Glob to find all frontend package.json files:
   - `adminportal/package.json`
   - `adminportal/packages/app1/package.json`
   - `adminportal/packages/app2/package.json`
   - (and any other subprojects)
5. Update ALL found package.json files:
   - `@shesha-io/reactjs: "5.0.14"`
   - Other `@shesha-io/*` packages to compatible versions
   - Update both `dependencies` and `devDependencies` sections
6. Update `backend/directory.build.props`:
   - `<SheshaVersion>0.43.25</SheshaVersion>`
   - `Boxfusion.DevExpressReporting`: `2.6.14`
   - `Boxfusion.PublicPortal`: `0.8.16`
7. Report changes:
   - Frontend: Updated 3 package.json files to Shesha.Enterprise 5.0.14
   - Backend: Updated to Shesha.Core 0.43.25
   - Boxfusion.DevExpressReporting: 2.6.14
   - Boxfusion.PublicPortal: 0.8.16
   - BoxStack version: 37
8. Ask next steps (AskUserQuestion multi-select):
   - "Install frontend dependencies" → run `npm install` in `adminportal`
   - "Build backend" → run `dotnet restore` + `dotnet build` in `/backend`
9. Execute only the selected actions:
   - If frontend install selected: run install command, report outcome
   - If build backend selected: run dotnet build, investigate and fix errors or report to user

## Important Notes

- **BoxStack releases are coordinated package bundles** that specify compatible versions across the entire stack
- Version mappings are stored in `ModulesAirtable.csv` in the skill's directory
- Each BoxStack release includes:
  - **Shesha.Core** (backend framework) - e.g., 0.43.25
  - **Shesha.Enterprise** (frontend framework) - e.g., 5.0.14
  - **Boxfusion modules** (optional add-ons) - e.g., DevExpressReporting, PublicPortal
- **Frontend** uses Shesha.Enterprise version for `@shesha-io/reactjs` package
- **Backend** uses:
  - Shesha.Core version for `SheshaVersion` property (applies to all Shesha.* packages)
  - Explicit versions for Boxfusion.* packages (from BoxStack dependencies)
- **CRITICAL: Finding all frontend files**
  - **ALWAYS use Glob tool** to find all package.json files: `adminportal/**/package.json`
  - **DO NOT assume** there's only one package.json file
  - Monorepo projects often have multiple subprojects in `adminportal/packages/` directory
  - **Must update ALL package.json files** that contain `@shesha-io/*` dependencies
  - **Verify count** of files found matches files updated
- **Always update ALL dependencies** specified in the BoxStack release to ensure compatibility
- **Update both `dependencies` and `devDependencies`** in all package.json files
- **MUST build backend after upgrade** to catch breaking changes and compatibility issues
  - Run `dotnet restore` to restore NuGet packages
  - Run `dotnet build` to compile the solution
  - Investigate and fix any build errors before completing the upgrade
  - Breaking changes are common in framework upgrades and must be addressed
- Verify all versions exist on npm and NuGet before upgrading
- Package name mapping:
  - CSV: `boxfusion.devexpressreporting` → NuGet: `Boxfusion.DevExpressReporting`
  - CSV: `Boxfusion.PublicPortal` → NuGet: `Boxfusion.PublicPortal`

Now perform the upgrade based on user's requirements.
