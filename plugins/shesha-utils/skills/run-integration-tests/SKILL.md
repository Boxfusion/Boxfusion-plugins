---
name: run-integration-tests
description: Runs integration tests against a dedicated test database. Handles database provisioning, fast resets, config updates, and test execution. Use when the user wants to run integration tests, test against a real database, or mentions "run integration tests", "run tests", "integration test", or "test database".
---

# Run Integration Tests

Runs the backend integration tests against a dedicated `{ApplicationName}-IntegrationTest` database, ensuring it is always reset to a clean state before tests execute.

## Arguments

- `--update-reset-sql` — regenerate the reset script before executing (use after schema/migration changes)
- `--skip-db` — skip all database preparation steps, just run `dotnet test`

## Workflow

### Step 1: Resolve Configuration

1. Glob for `backend/**/appsettings.json` (exclude `bin/`, `obj/`). Parse `ConnectionStrings.Default` to extract:
   - `Initial Catalog` → `ApplicationName`
   - `Data Source` → `ServerInstance` (default `.` if missing)
2. Compute `IntegrationTestDbName` = `{ApplicationName}-IntegrationTest`
3. Glob for `backend/test/**/*.csproj` → `TestProjectPath`
4. Find `appsettings.Test.json` in the same directory as the `.csproj` → `TestConfigPath`
5. Set `ResetSqlPath` = `backend/test/IntegrationTestDB-Reset.sql`

If `--skip-db` was passed: jump directly to **Step 7**, then **Step 8**.

### Step 2: Check if Integration Test DB Exists

Use sqlcmd with `DB_ID()` check (same pattern as backup/restore skills):

```
powershell -NoProfile -ExecutionPolicy Bypass -Command "sqlcmd -S <ServerInstance> -C -Q \"SELECT CASE WHEN DB_ID(N'<IntegrationTestDbName>') IS NOT NULL THEN 'YES' ELSE 'NO' END\" -h -1 -W"
```

- **YES** → Step 3
- **NO** → Step 5

### Step 3: DB Exists — Check for Reset Script

Check if `backend/test/IntegrationTestDB-Reset.sql` exists via Glob or Read.

- **Not exists** → Step 4
- **Exists + `--update-reset-sql` flag** → Step 6 (regenerate), then execute via `Execute-ResetSql.ps1`, then Step 7
- **Exists + no flag** → execute directly:

```
powershell -NoProfile -ExecutionPolicy Bypass -File "<skill-base-dir>/scripts/Execute-ResetSql.ps1" -SqlFilePath "<repo-root>/backend/test/IntegrationTestDB-Reset.sql" -ServerInstance "<server>" -DatabaseName "<IntegrationTestDbName>"
```

  - On **success**: tip the user about `--update-reset-sql` for future schema changes → Step 7
  - On **failure**: use `AskUserQuestion` with header "Reset failed":
    - **Regenerate the reset script** (recommended) — the schema may have changed
    - **Restore from backup** — slower but guarantees exact state
    - **Abort** — stop execution

  Regenerate → Step 6 → re-execute → Step 7.
  Restore → Step 5.
  Abort → stop.

### Step 4: No Reset Script — Ask User

Use `AskUserQuestion` with header "DB reset":

- **Generate a DB reset script** (recommended) — faster for repeated test runs
- **Restore from backup** — slower but guarantees exact state

Generate → Step 6 → execute via `Execute-ResetSql.ps1` → Step 7.
Restore → Step 5.

### Step 5: Import from Backup

1. Look for `backend/{ApplicationName}.bacpac`
2. If not found, look for `dbbackups/{ApplicationName}.bacpac`
3. If neither found, use `AskUserQuestion` with header "Bacpac source":
   - **Create backup from main DB** (recommended) — runs the backup-bacpac skill's script
   - **Specify a bacpac path** — user provides the path
   - **Abort** — stop execution

   If "Create backup from main DB": run the sibling backup script:
   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File "<backup-bacpac-skill-dir>/scripts/Backup-Bacpac.ps1" -DatabaseName "<ApplicationName>" -ServerInstance "<server>" -OutputPath "<repo-root>/backend/<ApplicationName>.bacpac"
   ```
   Timeout: 600000ms.

4. Import the bacpac using the sibling restore script:
   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File "<restore-bacpac-skill-dir>/scripts/Restore-Bacpac.ps1" -BacpacPath "<bacpac-path>" -DatabaseName "<IntegrationTestDbName>" -ServerInstance "<server>" [-DropExisting]
   ```
   Add `-DropExisting` if the database already exists (i.e., we came from Step 3 failure path).
   Timeout: 600000ms.

5. After successful import → Step 6 (generate reset script for future fast runs) → Step 7.

### Step 6: Generate/Update Reset SQL

Run the generation script:

```
powershell -NoProfile -ExecutionPolicy Bypass -File "<skill-base-dir>/scripts/Generate-ResetSql.ps1" -ServerInstance "<server>" -DatabaseName "<IntegrationTestDbName>" -OutputPath "<repo-root>/backend/test/IntegrationTestDB-Reset.sql" -TestProjectPath "<TestProjectPath>"
```

Timeout: 120000ms (2 minutes). If the script exits non-zero, show the error and abort.

### Step 7: Update Test Config

Read the `appsettings.Test.json` file found in Step 1. Ensure it has the correct connection string pointing to the integration test database:

```json
{
  "ConnectionStrings": {
    "TestDB": "Data Source=<ServerInstance>;Initial Catalog=<IntegrationTestDbName>;Integrated Security=True;TrustServerCertificate=True"
  }
}
```

Use the Edit tool to update it if the `Initial Catalog` doesn't match `IntegrationTestDbName`. Report whether it was updated or already correct.

### Step 8: Execute Tests

Run the tests:

```bash
dotnet test <TestProjectPath> --no-restore --verbosity normal
```

Timeout: 600000ms. If the command fails with restore-related errors, retry once without `--no-restore`:

```bash
dotnet test <TestProjectPath> --verbosity normal
```

### Step 9: Report Results

Parse the dotnet test output for the summary line containing Total/Passed/Failed/Skipped counts. Present a clear summary:

- Total, Passed, Failed, Skipped counts
- If any tests failed, show the failure details (test name + error message)
- Remind the user about `--update-reset-sql` if they haven't used it recently and there were failures that might be schema-related
