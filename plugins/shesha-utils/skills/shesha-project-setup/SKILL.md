---
name: shesha-project-setup
description: Set up a Shesha-based project development environment aligned to Boxfusion development standards and best practices. Run this when a new Shesha project has just been created to verify and configure the dev environment.
disable-model-invocation: true
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, WebFetch, WebSearch, Task, AskUserQuestion, ToolSearch, EnterPlanMode, TaskCreate, TaskUpdate, TaskList
---

# Shesha Dev Environment Setup

You are setting up a Shesha-based project development environment aligned to Boxfusion development standards and best practices. Follow each phase below **in order**. Do NOT skip phases. If a phase fails, stop and resolve the issue before continuing.

Use `TaskCreate` and `TaskUpdate` to track progress through the phases.

## Important Notes

### Script Invocation
All PowerShell scripts live in `.claude/skills/setup-shesha-dev/scripts/`. **Always invoke them via PowerShell directly** to avoid Git Bash path mangling:

```
powershell -NoProfile -ExecutionPolicy Bypass -File "<script-path>" -ParamName "value"
```

**NEVER** run the scripts via `bash` or `sh`. Git Bash will mangle Windows paths (e.g., `/Action:Import` becomes `C:/Git/Action:Import`).

### Script Output
All scripts output **structured JSON** (via `ConvertTo-Json`). Parse the JSON output to determine results. Scripts always exit 0 — check the `success`/`valid` field in JSON for actual pass/fail.

### No Blind Sleeps
Do NOT use `sleep` or `Start-Sleep` anywhere in this workflow. The PowerShell scripts use TCP port polling with configurable timeouts.

---

## Phase 1: Validate Project Structure

Run the validation script:

```
powershell -NoProfile -ExecutionPolicy Bypass -File ".claude/skills/setup-shesha-dev/scripts/Validate-Project.ps1" -ProjectRoot "<project-root>"
```

Parse the JSON output. Key fields:
- `valid` — if `false`, show the `errors` array and stop
- `applicationName`, `namespace`, `fullNamespace` — used throughout remaining phases
- `slnPath`, `webHostProject`, `adminPortalPath` — paths for scripts
- `bacpacPath` — path to database backup (may be empty)
- `databaseName` — extracted from connection string
- `backendUrl`, `backendPort` — from appsettings.json
- `directoryBuildPropsPath` — for analyzer setup

**If `valid` is `false`**, tell the user:

> "This does not appear to be a valid Shesha project. The following issues were found: {errors}. Please fix these and run `/setup-shesha-dev` again."

Then **stop**.

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

Save the username and password for Phase 3 and Phase 4.

---

## Phase 3: Test Backend & Frontend (PARALLEL)

**CRITICAL: Make TWO Bash tool calls in a SINGLE message.** This runs backend and frontend testing concurrently, saving ~2 minutes.

### Bash Call 1: Test Backend

```
powershell -NoProfile -ExecutionPolicy Bypass -File ".claude/skills/setup-shesha-dev/scripts/Test-Backend.ps1" -SlnPath "{slnPath}" -WebHostProject "{webHostProject}" -BackendPort {backendPort} -Username "{username}" -Password "{password}" -BacpacPath "{bacpacPath}" -DatabaseName "{databaseName}" -ScriptsDir ".claude/skills/setup-shesha-dev/scripts"
```

### Bash Call 2: Test Frontend

```
powershell -NoProfile -ExecutionPolicy Bypass -File ".claude/skills/setup-shesha-dev/scripts/Test-Frontend.ps1" -AdminPortalPath "{adminPortalPath}"
```

### Handling Results

Parse the JSON output from each script.

**Backend result fields:**
| Field | Values | Action on Failure |
|-------|--------|-------------------|
| `build` | PASS/FAIL | Show errors, ask user to fix, stop |
| `server` | PASS/FAIL | Check `serverOutput` for diagnostics. If DB error and `databaseRestored` is false, ask user if they want manual restore |
| `auth` | PASS/FAIL | Check `credentials.source` — if "default", note that defaults worked. If FAIL, ask user for correct credentials |
| `databaseRestored` | true/false | If true, inform user the database was auto-restored |
| `credentials` | object | Use `credentials.username` and `credentials.password` for Phase 4 (may differ from input if defaults were used) |

**Frontend result fields:**
| Field | Values | Action on Failure |
|-------|--------|-------------------|
| `install` | PASS/FAIL | Show errors, ask user to fix |
| `build` | PASS/FAIL | Show errors, ask user to fix |
| `devServer` | PASS/FAIL | Check `output` for diagnostics |

---

## Phase 4: Save Configuration

### 4.1 Save credentials locally

Use the **final resolved credentials** from Phase 3 (which may be the defaults if the cascade picked them up).

Write `.sheshadev.local.json` in the **project root**:

```json
{
  "testcredentials": {
    "username": "{username}",
    "password": "{password}"
  }
}
```

### 4.2 Ensure .gitignore coverage

Run the gitignore update script:

```
powershell -NoProfile -ExecutionPolicy Bypass -File ".claude/skills/setup-shesha-dev/scripts/Update-GitIgnore.ps1" -ProjectRoot "<project-root>"
```

Parse the JSON output:
- `added` — list of entries that were appended
- `alreadyPresent` — list of entries that already existed (no duplicates created)
- `success` — whether the operation completed without error

---

## Phase 5: MCP Tool Installation

### 5.1 Azure DevOps MCP

Check if already configured by reading `.claude/settings.local.json` for an `azure-devops` MCP entry.

If **not installed**:
```bash
claude mcp add azure-devops -- npx -y @azure-devops/mcp Boxfusion
```

### 5.2 Playwright MCP

Check if already configured by looking for a `playwright` MCP entry.

If **not installed**:
```bash
claude mcp add playwright -- npx -y @anthropic-ai/mcp-playwright
```

### 5.3 Shesha MCP

Configure the Shesha MCP using the resolved credentials and database name from Phase 3:

```bash
claude mcp add shesha --transport sse --url http://localhost:8000/sse --header "backend_url:{backendUrl}" --header "backend_username:{username}" --header "backend_password:{password}" --header "db_server:." --header "db_database:{databaseName}"
```

After adding, attempt to verify connectivity (try `ToolSearch` for shesha-related tools).

- **If not reachable**, inform the user:
  > "I could not connect to the Shesha MCP at `http://localhost:8000/sse`. This is normal if it is not running locally. You can start it later."

### 5.4 Check if restart is needed

If any **new** MCPs were installed (Azure DevOps or Playwright), inform the user:

> "New MCP servers were installed. Please restart your Claude Code session and run `/setup-shesha-dev` again to continue from Phase 6."

Then **stop**.

If no new MCPs were installed, continue to Phase 6.

---

## Phase 6: Dev Environment Configuration

### 6.1 CLAUDE.md

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

### 6.2 Add standard analyzers

Run the analyzer setup script:

```
powershell -NoProfile -ExecutionPolicy Bypass -File ".claude/skills/setup-shesha-dev/scripts/Setup-Analyzers.ps1" -DirectoryBuildPropsPath "{directoryBuildPropsPath}" -SlnPath "{slnPath}"
```

Parse the JSON output:
- `added` — list of newly added analyzers
- `updated` — list of analyzers with version changes
- `unchanged` — list of analyzers already at target version
- `buildPass` — whether the build still passes
- If `buildPass` is false, check `errors` and address critical issues (warnings are acceptable)

---

## Phase 7: Summary Report

**Do NOT restart any servers.** Compile results from Phase 3 and Phase 6 into a summary:

```
========================================
  Shesha Dev Environment Setup Complete
========================================

Project:        {fullNamespace}
Application:    {applicationName}
Database:       {databaseName}

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
  - Azure DevOps:  Installed / Already Present / FAILED
  - Playwright:    Installed / Already Present / FAILED
  - Shesha:        Connected / Not Reachable (start manually)

Dev Environment:
  - CLAUDE.md:     Created / Updated
  - Analyzers:     {summary of added/updated/unchanged}
  - Credentials:   Saved to .sheshadev.local.json
  - .gitignore:    Updated (if needed)

Next Steps:
  1. Ensure the Shesha MCP is running at http://localhost:8000/sse
  2. Review CLAUDE.md and customize as needed
  3. Review analyzer warnings with: dotnet build backend/{fullNamespace}.sln
  4. Start developing!
========================================
```

If there were any failures, list them with suggested remediation steps.

---

## Error Handling Reference

| Script | Failure | Claude's Action |
|--------|---------|-----------------|
| Validate-Project.ps1 | `valid: false` | Show errors, stop |
| Test-Backend.ps1 | `build: FAIL` | Show build errors, ask user to fix, stop |
| Test-Backend.ps1 | `server: FAIL` + DB error | Check if auto-restore ran; if not, ask user |
| Test-Backend.ps1 | `auth: FAIL` | Ask user for correct credentials, re-run backend test only |
| Test-Frontend.ps1 | `install: FAIL` | Show npm errors, ask user to fix |
| Test-Frontend.ps1 | `build: FAIL` | Show build errors, ask user to fix |
| Test-Frontend.ps1 | `devServer: FAIL` | Show output, suggest checking port 3000 conflicts |
| Update-GitIgnore.ps1 | `success: false` | Show error message, fall back to manual edit |
| Setup-Analyzers.ps1 | `buildPass: false` | Show errors, revert if critical, or note warnings are OK |
