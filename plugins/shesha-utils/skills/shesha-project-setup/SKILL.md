---
name: shesha-project-setup
description: Set up a Shesha-based project development environment aligned to Boxfusion development standards and best practices. Run this when a new Shesha project has just been created to verify and configure the dev environment.
disable-model-invocation: true
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, WebFetch, WebSearch, Task, AskUserQuestion, ToolSearch, EnterPlanMode, TaskCreate, TaskUpdate, TaskList
---

# Shesha Dev Environment Setup

You are setting up a Shesha-based project development environment aligned to Boxfusion development standards and best practices. Follow each phase below **in order**. Do NOT skip phases. If a phase fails, stop and resolve the issue before continuing.

Use `TaskCreate` and `TaskUpdate` to track progress through the phases.

> **This skill is Boxfusion-specific.** Every developer running it needs authenticated access to the private Azure DevOps feeds (`nuget.shesha.dev`, `nuget.boxfusion.co.za`, `npm.shesha.dev`). Phase 3 authenticates to these feeds and runs **unconditionally** — treat it as a baseline, not an edge case.

## Important Notes

### Script Invocation
All PowerShell scripts live in `.claude/skills/shesha-project-setup/scripts/`. **Always invoke them via PowerShell directly** to avoid Git Bash path mangling:

```
powershell -NoProfile -ExecutionPolicy Bypass -File "<script-path>" -ParamName "value"
```

**NEVER** run the scripts via `bash` or `sh`. Git Bash will mangle Windows paths and `/Switch:value` style CLI arguments (e.g., `/Action:Import` becomes `C:/Program Files/Git/Action:Import`). **This rule extends to `sqlpackage` and any other tool that takes `/Switch:value` arguments** — always invoke them from PowerShell, never through the Bash/Git-Bash tool.

### Script Output
All scripts output **structured JSON** (via `ConvertTo-Json`). Parse the JSON output to determine results. Scripts always exit 0 — check the `success`/`valid` field in JSON for actual pass/fail.

### No Blind Sleeps
Do NOT use `sleep` or `Start-Sleep` anywhere in this workflow. The PowerShell scripts use TCP port polling with configurable timeouts. First-run startup after a fresh database restore is slow (FluentMigrator migrations run on boot) — poll for `Now listening on` / `Application started` with a generous timeout (≥120s) rather than a fixed wait. The scripts already use a 120s poll.

---

## Phase 1: Validate Project Structure (and prerequisites)

Run the validation script:

```
powershell -NoProfile -ExecutionPolicy Bypass -File ".claude/skills/shesha-project-setup/scripts/Validate-Project.ps1" -ProjectRoot "<project-root>"
```

Parse the JSON output. Key fields:
- `valid` — if `false`, show the `errors` array and stop
- `applicationName`, `namespace`, `fullNamespace` — used throughout remaining phases
- `slnPath`, `webHostProject`, `adminPortalPath` — paths for scripts
- `bacpacPath` — path to database backup (may be empty)
- `databaseName` — extracted from connection string
- `backendUrl`, `backendPort` — from appsettings.json
- `directoryBuildPropsPath` — for analyzer setup
- `dotnetSdks` — installed .NET SDKs. **If empty, `valid` is `false`** (see below).
- `nugetConfigFound`, `nugetConfigPath` — whether a `NuGet.Config` is on the restore discovery path
- `warnings` — non-fatal issues (stray backup `.csproj`, missing discoverable `NuGet.Config`, etc.)

**If `valid` is `false`**, tell the user:

> "This does not appear to be a valid Shesha project. The following issues were found: {errors}. Please fix these and run `/shesha-project-setup` again."

Then **stop**.

### .NET SDK prerequisite (§ critical)
If `dotnetSdks` is empty, the machine has **no .NET SDK** (only runtimes, or it was removed mid-flight by a background installer). Halt with guidance: `winget install Microsoft.DotNet.SDK.8` (a .NET 10 SDK builds a `net8.0` target fine — pin only if policy requires it). **Warn the user** that an in-progress Visual Studio / .NET update can remove the SDK out from under a build, so a later "No SDKs were found" failure is **environmental, not a project defect**.

### Address warnings
- **Missing discoverable `NuGet.Config`** (`nugetConfigFound: false`): feeds defined only in `backend/.nuget/NuGet.Config` are **not** auto-discovered — NuGet walks **up** from the solution/project directory, and `.nuget/` is not an ancestor. Offer to create a `NuGet.Config` **next to the `.sln`** (`backend/NuGet.Config`) with:
  ```xml
  <?xml version="1.0" encoding="utf-8"?>
  <configuration>
    <packageSources>
      <clear />
      <add key="nuget.org" value="https://api.nuget.org/v3/index.json" protocolVersion="3" />
      <add key="DevExpress" value="https://nuget.devexpress.com/.../api" />
      <add key="nuget.boxfusion.co.za" value="https://pkgs.dev.azure.com/boxfusion/_packaging/nuget.boxfusion.co.za/nuget/v3/index.json" />
      <add key="nuget.shesha.dev" value="https://pkgs.dev.azure.com/boxfusion/_packaging/nuget.shesha.dev/nuget/v3/index.json" />
    </packageSources>
    <solution><add key="disableSourceControlIntegration" value="true" /></solution>
  </configuration>
  ```
  After writing it, confirm with `dotnet nuget list source` (run from the backend dir) that all feeds are enabled.
- **Stray backup `.csproj`** (`* - Backup*.csproj` / `*Copy*.csproj`): recommend the user delete them so they are not built/run by mistake.

Save all extracted variables for use in subsequent phases.

---

## Phase 2: Collect Credentials

Ask the user for a **login username and password** using the `AskUserQuestion` tool. **Mention the Shesha defaults upfront:**

> "What credentials should I use to test the backend? The Shesha default is `admin` / `123qwe`. If your project uses different credentials, please provide them."

Provide options:
1. **Use defaults** (`admin` / `123qwe`) — (Recommended)
2. **Provide custom credentials**

- If the username looks like an admin account (e.g. contains "admin", "sysadmin", "administrator"), **warn** the user:
  > "Using an admin account for development is not recommended for production projects. Consider creating a dedicated development user later."

Save the username and password for Phase 4 and Phase 5.

---

## Phase 3: Authenticate to Boxfusion Private Feeds

This phase runs **unconditionally** — all Boxfusion devs need it. The goal is to surface auth failures in their own clearly-labelled phase with actionable remediation, instead of letting them masquerade as build errors 200 lines deep (`NU1101` / `401` on NuGet, `E401` on npm).

> **PAT security reminder:** if the user pastes a PAT into the chat, remind them it is now in the transcript and they should **revoke it afterward**. Use a short-expiry PAT scoped to **Packaging: Read** only. Create one at `https://dev.azure.com/boxfusion/_usersSettings/tokens`.

### 3.1 Choose an auth path

State up front that **interactive browser/device login cannot be completed by the agent** — it only surfaces in the user's own terminal. Offer:

- **Interactive (recommended for humans):** ask the user to run, via the `!` prefix so it executes in-session:
  ```
  dotnet restore <sln> --interactive
  ```
  Completing the browser/device login once caches a token for all projects.
- **`az login` path (cleanest once Azure CLI is installed — see Phase 6):** `az login` plus the credential provider can mint feed tokens without a manually-managed PAT. **Prefer this for Boxfusion devs.** Run `az login` via the `!` prefix.
- **PAT (works headless / agent-driven):** the developer supplies a PAT and the helper script wires it.

### 3.2 Run the helper (installs cred provider, optionally wires a PAT, verifies)

```
powershell -NoProfile -ExecutionPolicy Bypass -File ".claude/skills/shesha-project-setup/scripts/Connect-Feeds.ps1" -SlnPath "{slnPath}" -AdminPortalPath "{adminPortalPath}"
```

To wire a PAT for headless auth, add `-Pat "<PAT>"`. The script:
- installs the Azure Artifacts credential provider (idempotent),
- (with `-Pat`) sets `VSS_NUGET_EXTERNAL_FEED_ENDPOINTS` for the restore process and writes the npm credentials into the user `~/.npmrc` (both registry path variants),
- verifies: `dotnet restore` exit 0 (`nugetRestore`) and `npm whoami` (`npmAuth`).

Parse the JSON: `credProviderInstalled`, `patWired`, `nugetRestore` (PASS/FAIL), `npmAuth` (PASS/FAIL), `errors`.

### 3.3 Verify before proceeding

**Do NOT continue to Phase 4 until both feeds authenticate.**
- If `nugetRestore` is `FAIL` with a `401`, stop and show the auth remediation (interactive / az login / PAT).
- If `npmAuth` is `FAIL` (E401), refresh via `npx vsts-npm-auth -config adminportal/.npmrc` (run via `!`) or re-run the helper with a PAT, then re-check.

---

## Phase 4: Test Backend & Frontend (PARALLEL)

**CRITICAL: Make TWO Bash tool calls in a SINGLE message.** This runs backend and frontend testing concurrently, saving ~2 minutes.

### Bash Call 1: Test Backend

```
powershell -NoProfile -ExecutionPolicy Bypass -File ".claude/skills/shesha-project-setup/scripts/Test-Backend.ps1" -SlnPath "{slnPath}" -WebHostProject "{webHostProject}" -BackendPort {backendPort} -Username "{username}" -Password "{password}" -BacpacPath "{bacpacPath}" -DatabaseName "{databaseName}" -ScriptsDir ".claude/skills/shesha-project-setup/scripts"
```

The backend script proactively checks the database exists **before** starting the server (Kestrel binds the port before ABP init, so a missing catalog still looks "ready"). If the catalog is missing and a `.bacpac` is present, it restores **before** the first start. It also restores reactively on a connection failure and on an auth-500 with a DB error signature in the log. All `sqlpackage` work happens inside `Restore-Database.ps1` (PowerShell, `/Action:` args intact).

### Bash Call 2: Test Frontend

```
powershell -NoProfile -ExecutionPolicy Bypass -File ".claude/skills/shesha-project-setup/scripts/Test-Frontend.ps1" -AdminPortalPath "{adminPortalPath}"
```

### Handling Results

Parse the JSON output from each script.

**Backend result fields:**
| Field | Values | Action on Failure |
|-------|--------|-------------------|
| `build` | PASS/FAIL | Show errors, ask user to fix, stop. If errors mention `NU1101`, this is usually a feed-auth gap (re-check Phase 3) or a stale `packages.lock.json` (see below). |
| `server` | PASS/FAIL | Check `serverOutput` for diagnostics. The script auto-restores the DB when missing; if a restore failed, surface its message. |
| `auth` | PASS/FAIL | Check `credentials.source` — if "default", note that defaults worked. If FAIL, ask user for correct credentials |
| `databaseRestored` | true/false | If true, inform user the database was auto-restored |
| `credentials` | object | Use `credentials.username` and `credentials.password` for Phase 5 (may differ from input if defaults were used) |

**Stale `packages.lock.json` recovery:** if the build fails with `NU1101` for packages that genuinely exist on the feed, check `git status` / `git diff --stat **/packages.lock.json`. If the lock file is dirty/truncated, offer to recover:
```
git checkout -- <path>/packages.lock.json     # if the committed lock is correct
# or
dotnet restore <sln> --force-evaluate          # regenerate from the project graph
```

**Frontend result fields:**
| Field | Values | Action on Failure |
|-------|--------|-------------------|
| `install` | PASS/FAIL | Show errors, ask user to fix. A confusing `E401` mid-install means the npm token expired — re-check Phase 3. |
| `build` | PASS/FAIL | Show errors. The script auto-recovers a corrupt `next-swc` native binary with `npm ci`; if that note appears in `errors` the build still passed. |
| `devServer` | PASS/FAIL | Check `output` for diagnostics |

---

## Phase 5: Save Configuration

### 5.1 Save credentials locally

Use the **final resolved credentials** from Phase 4 (which may be the defaults if the cascade picked them up).

Write `.sheshadev.local.json` in the **project root**:

```json
{
  "testcredentials": {
    "username": "{username}",
    "password": "{password}"
  }
}
```

### 5.2 Ensure .gitignore coverage

Run the gitignore update script:

```
powershell -NoProfile -ExecutionPolicy Bypass -File ".claude/skills/shesha-project-setup/scripts/Update-GitIgnore.ps1" -ProjectRoot "<project-root>"
```

Parse the JSON output:
- `added` — list of entries that were appended
- `alreadyPresent` — list of entries that already existed (no duplicates created)
- `success` — whether the operation completed without error

---

## Phase 6: MCP Servers & Azure CLI

> All commands below were verified live unless explicitly marked "doc-confirmed".

### 6.1 Azure CLI (replaces the Azure DevOps MCP)

Install the Azure CLI — it also underpins the cleanest feed-auth path (Phase 3, `az login`).

```powershell
# Detection: if `az version` returns 0, SKIP the install.
winget install --id Microsoft.AzureCLI -e --accept-source-agreements --accept-package-agreements
# DevOps support + login
az extension add --name azure-devops      # doc-confirmed
az login                                   # interactive — run via ! in-session
az devops configure --defaults organization=https://dev.azure.com/boxfusion
```

- If `az version` already succeeds, just ensure the `azure-devops` extension is added and the default org is set.
- **MSI-lock note:** `winget`/MSI installs fail with exit **1618** ("Another installation is already in progress") if Visual Studio Installer or a .NET update is running. **Treat 1618 as transient** — poll for the blocking `msiexec`/`setup`/VS-installer processes to finish (TCP-poll style, no blind sleeps) and retry, rather than failing the phase.

### 6.2 Playwright MCP

Check if already configured by looking for a `playwright` MCP entry. If **not installed**:

```bash
claude mcp add playwright -- npx -y @playwright/mcp
```

(Do **not** use `@anthropic-ai/mcp-playwright` — that package is a 404.)

### 6.3 Roslyn MCP (C# refactor/analysis)

[`JoshuaRamirez/RoslynMcpServer`](https://github.com/JoshuaRamirez/RoslynMcpServer) — Roslyn-powered C# refactor/analysis tools. NuGet package `RoslynMcp.Server`.

```powershell
dotnet tool install -g RoslynMcp.Server          # installs exe `roslyn-mcp` to ~/.dotnet/tools
```

**Runtime caveat:** `roslyn-mcp` targets **.NET 9**. **Probe the installed runtimes first** with `dotnet --list-runtimes`:
- If **no** `Microsoft.NETCore.App 9.x` is present, register with roll-forward (no extra install needed):
  ```bash
  claude mcp add roslyn-refactor -e DOTNET_ROLL_FORWARD=Major -- roslyn-mcp
  ```
- If a 9.x runtime **is** present, register without the env var:
  ```bash
  claude mcp add roslyn-refactor -- roslyn-mcp
  ```
- Alternatively install the runtime: `winget install Microsoft.DotNet.Runtime.9` (doc-confirmed).

### 6.4 HandMirror MCP (inspect .NET assemblies & NuGet packages)

[`rkttu/HandMirrorMcp`](https://github.com/rkttu/HandMirrorMcp) — lets agents inspect .NET assemblies & NuGet packages so they stop hallucinating APIs. **No global tool / NuGet package — build from source**, and clone to a **persistent** location (the server runs from these build outputs), NOT a temp dir. Suggested location: `%USERPROFILE%\.shesha-dev\mcp\HandMirrorMcp`.

```bash
git clone https://github.com/rkttu/HandMirrorMcp.git "<persistent-path>/HandMirrorMcp"
cd "<persistent-path>/HandMirrorMcp"
dotnet build -c Release          # main project: HandMirrorMcp/HandMirrorMcp.csproj (net8.0)
```

Register pointing at the built **dll** via `dotnet` (launching the bare `.exe` hits a Windows SxS/apphost error; `dotnet run --project` works but rebuilds every launch):

```bash
claude mcp add handmirror -- dotnet "<persistent-path>/HandMirrorMcp/HandMirrorMcp/bin/Release/net8.0/HandMirrorMcp.dll"
```

### 6.5 Check if restart is needed

If any **new** MCPs were installed, inform the user:

> "New MCP servers were installed. Please restart your Claude Code session and run `/shesha-project-setup` again to continue from Phase 7."

Then **stop**. If no new MCPs were installed, continue to Phase 7.

> **Removed:** the Azure DevOps MCP (replaced by the Azure CLI above) and the SSE Shesha MCP at `localhost:8000/sse` (deprecated). Do not add either.

---

## Phase 7: Dev Environment Configuration

### 7.1 CLAUDE.md

Check if a `CLAUDE.md` file exists in the project root.

- **If it does NOT exist**, create one with sections for: Project Overview, Build & Run Commands, Architecture, Key Conventions.
- **If it DOES exist**, update it (do not overwrite — merge new content).

**Ensure the following content is present:**

Under "Key Conventions" or similar:

```markdown
### Back-end Naming Conventions
- Two-letter acronyms should be ALL CAPS (e.g. `IO`, `DB`).
- Acronyms of three or more letters should only have the first letter capitalized (e.g. `Sla`, `Xml`, `Http`).
```

And:

```markdown
### Dev Credentials
- Test username and passwords for the backend can be found in `.sheshadev.local.json` in the project root. This file is excluded from version control.
```

And under "Skill Usage Rules" or similar:

```markdown
## Skill Usage Rules

- **Before implementing backend application services, DTOs, AutoMapper profiles, or the application layer**, always invoke the `shesha-developer:shesha-app-layer` skill first. It contains Shesha-specific patterns, base classes, and templates that must be followed.
- **Before creating or modifying domain entities, reference lists, or migrations**, always invoke the `shesha-developer:domain-model` skill first.
- **Before creating or modifying workflow artifacts**, always invoke the `shesha-developer:shesha-workflow` skill first.
- These skills must be invoked BEFORE any manual exploration or planning for the relevant task.
```

### 7.2 Add standard analyzers

Run the analyzer setup script:

```
powershell -NoProfile -ExecutionPolicy Bypass -File ".claude/skills/shesha-project-setup/scripts/Setup-Analyzers.ps1" -DirectoryBuildPropsPath "{directoryBuildPropsPath}" -SlnPath "{slnPath}"
```

Parse the JSON output:
- `added` — list of newly added analyzers
- `updated` — list of analyzers with version changes
- `unchanged` — list of analyzers already at target version
- `buildPass` — whether the build still passes
- If `buildPass` is false, check `errors` and address critical issues (warnings are acceptable)

---

## Phase 8: Summary Report

**Do NOT restart any servers.** Compile results from Phase 4 and Phase 7 into a summary:

```
========================================
  Shesha Dev Environment Setup Complete
========================================

Project:        {fullNamespace}
Application:    {applicationName}
Database:       {databaseName}

Feed Auth:
  - NuGet:       {feeds.nugetRestore}
  - npm:         {feeds.npmAuth}

Back-End:
  - Build:       {backend.build}
  - Server:      {backend.server}
  - Auth:        {backend.auth}
  - DB Restored: {backend.databaseRestored}

Front-End:
  - Install:     {frontend.install}
  - Build:       {frontend.build}
  - Dev Server:  {frontend.devServer}

MCP Servers:
  - playwright:       Connected / FAILED
  - roslyn-refactor:  Connected / FAILED
  - handmirror:       Connected / FAILED
  (Azure DevOps MCP removed → Azure CLI; Shesha MCP removed → deprecated)

Tooling:
  - Azure CLI:     Installed / Already Present / FAILED

Dev Environment:
  - CLAUDE.md:     Created / Updated
  - Analyzers:     {summary of added/updated/unchanged}
  - Credentials:   Saved to .sheshadev.local.json
  - .gitignore:    Updated (if needed)

Next Steps:
  1. Review CLAUDE.md and customize as needed
  2. Review analyzer warnings with: dotnet build backend/{fullNamespace}.sln
  3. Revoke any PAT pasted during feed auth
  4. Start developing!
========================================
```

If there were any failures, list them with suggested remediation steps.

---

## Notes & Troubleshooting

- **`dotnet run` port:** `dotnet run` binds Kestrel's default `http://localhost:5000` unless the launch profile is honored or `--urls`/`ASPNETCORE_URLS` is set. The backend test script passes `--urls`, so `:21021` lines up. For a manual verification run:
  ```
  ASPNETCORE_URLS=http://localhost:21021 dotnet run --project <Web.Host>.csproj --no-build --no-restore
  ```
- **First-run startup is slow:** after a fresh bacpac import the Web.Host runs FluentMigrator migrations on boot — poll for `Now listening on` / `Application started` with a generous timeout (≥120s).
- **Next.js SWC recovery:** if the frontend build fails with `next-swc….node is not a valid Win32 application` (corrupt optional native binary), recover with a clean `npm ci` (re-fetches the binary). The frontend test script does this automatically. Avoid ad-hoc `npm install <pkg> --no-save` surgery, which can desync the dependency tree.
- **VS/.NET installer churn:** a background Visual Studio / .NET installer can remove the SDK mid-session (`winget` returns 1618 while it runs). Treat "No SDKs were found" as environmental and retry once the installer finishes.

---

## Error Handling Reference

| Script | Failure | Claude's Action |
|--------|---------|-----------------|
| Validate-Project.ps1 | `valid: false` | Show errors, stop |
| Validate-Project.ps1 | `dotnetSdks` empty | Halt — install a .NET SDK (env issue, not project) |
| Connect-Feeds.ps1 | `nugetRestore: FAIL` (401) | Show auth remediation (interactive / az login / PAT), stop before build |
| Connect-Feeds.ps1 | `npmAuth: FAIL` (E401) | Refresh npm auth (`vsts-npm-auth` or PAT), re-check |
| Test-Backend.ps1 | `build: FAIL` | Show build errors; check for NU1101 (feed auth / stale lock file), ask user to fix, stop |
| Test-Backend.ps1 | `server: FAIL` + DB error | Auto-restore should have run; if not, surface restore message / ask user |
| Test-Backend.ps1 | `auth: FAIL` | Ask user for correct credentials, re-run backend test only |
| Test-Frontend.ps1 | `install: FAIL` | Show npm errors (E401 → re-check feed auth), ask user to fix |
| Test-Frontend.ps1 | `build: FAIL` | Show build errors (SWC corruption auto-recovers via npm ci) |
| Test-Frontend.ps1 | `devServer: FAIL` | Show output, suggest checking port 3000 conflicts |
| Update-GitIgnore.ps1 | `success: false` | Show error message, fall back to manual edit |
| Setup-Analyzers.ps1 | `buildPass: false` | Show errors, revert if critical, or note warnings are OK |
