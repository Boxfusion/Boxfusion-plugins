# Fresh-database troubleshooting and upgrading old suites

A blank database is the first time many projects have had all their migrations and config packages applied from scratch. Some of those changes only ever worked against a developer's or production database. Failures on a blank DB are often **real deployment bugs** that would also hit any new environment, not just test problems. Report them as bugs; don't hide them in the test fixture.

## Contents
- Diagnosing a failure
- Migration failures that are swallowed
- Config package (`.shaconfig`) failures
- Test-data traps after cleanup
- Custom Respawn helpers
- Upgrading an existing (older) suite
- Environment

## Diagnosing a failure

1. **Read the test log for migration errors first.** FluentMigrator writes `!!! An error occured executing the following sql:` and then `The error was ...`. Find the last migration it started:
   ```bash
   grep -n "^[0-9]\{14\}: .* migrating" test.log | tail -1
   grep -n "^The error was" test.log | head -1
   ```
2. **Look for the startup exception.** `Application startup exception:` in the log. If login fails, the helper's response body is an HTML "An error occurred while starting the application" page with the real exception in it.
3. **The server-side error is in ELMAH, not the console.** A helper failure like `Create X failed: ... could not execute batch command.[SQL: SQL not available]` hides the real SQL error. Keep the container and read `elmah.errors`:
   ```powershell
   $env:TESTCONTAINERS_RYUK_DISABLED='true'; dotnet test <csproj> --filter "FullyQualifiedName~<Test>"
   $c = docker ps -a --filter "ancestor=robjomar/shesha-mssql-blank" -q | Select-Object -First 1
   docker start $c; Start-Sleep 15
   docker exec $c /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "Acc@12345" -C -h -1 -y 4000 -Q "SET NOCOUNT ON; USE Shesha_IntegrationTests; SELECT type+' | '+message FROM elmah.errors"
   ```
   Cleanup wipes `elmah.errors` between tests, so what's left belongs to the last test that ran. Remove the container afterwards (`docker rm -f $c`).
4. **Don't trust a "connection reset" after a failure.** `pre-login handshake ... forcibly closed` (error 10054) logged by Hangfire's `RemoveServer` happens during teardown. It's a symptom. Find the first error before the test failed.
5. **Test passes alone but fails in the full run** → the failure depends on state left by an earlier test. See *Test-data traps*.

## Migration failures that are swallowed

The app catches a failing migration and keeps starting, so **every later migration silently never runs**. The visible symptom is somewhere else entirely, for example "Invalid object name 'Core_NotificationChannelConfigs'" from a table a later migration would have created. Fix the first failing migration, rerun, repeat.

Common causes and the safe fix for each. These only change behaviour on a fresh DB: an existing DB has already applied the migration and FluentMigrator never re-runs a version.

| Cause | Example error | Fix |
|---|---|---|
| Drops a column or function that was only ever created by hand | `ALTER TABLE DROP COLUMN failed because column 'testing' does not exist` / `Cannot drop the function` | `IF COL_LENGTH('T','c') IS NOT NULL ALTER TABLE T DROP COLUMN c;` / `DROP FUNCTION IF EXISTS` |
| Joins or uses a column that a hand-made or legacy schema had | `Invalid column name 'TripId'` | Point it at the table or column the owning module actually creates (check that module's own migrations) |
| Drops a table that another module's FK still references | `Could not drop object ... referenced by a FOREIGN KEY constraint` | Drop the external FKs first (`sys.foreign_keys` where `referenced_object_id = OBJECT_ID(...)` and `parent <> referenced`) |

Ask the user before editing a production migration, and raise the class of problem as a bug.

## Config package (`.shaconfig`) failures

Symptom: startup fails in `ConfigurableModuleBootstrapper` with `Cannot insert duplicate key ... 'uq_Frwk_EntityProperties_Path'`. The importer in Shesha 0.43 (`EntityConfigImport.MapPropertiesAsync`) looks up entity properties by `Name` without checking `ParentProperty`. Exported entity configs with array properties (whose `ItemsType` child has the same name) or duplicate property rows then collide on a fresh DB.

**Never edit an already-shipped package.** `EmbeddedPackageSeeder` skips a package only when a successful import with the same **file name and MD5** exists. Any byte change, even re-zipping identical content, re-imports it on every environment. `FormConfigurationImport` then cancels Draft/Ready versions, retires the live version and makes the package's old content live again, rolling forms back. The same goes for reference lists, settings, roles and permissions.

Options to put to the user:
- **Remove the package** from the module (file plus its `None Remove` / `EmbeddedResource` csproj entries). Existing environments are unaffected. Fresh environments lose whatever only that package provided. Before deciding, list the items no later package also contains.
- **Fix in Shesha** (filter on `ParentProperty == null` in the importer). This is the root-cause fix, but it's a framework change.

Entity configs (`/entity/*.json`, `Source: 1`) are regenerated from code by the bootstrapper, so they are the least valuable part of a package. Entity configs for *other modules'* entities are a red flag.

## Test-data traps after cleanup

- **Configuration items survive `CleanAllAsync`.** `Frwk_ConfigurationItems` is kept, and some entities (for example ServiceManagement `CaseType` in 0.43) are configuration items with a unique live name. A test that creates one with a fixed name fails in the full run with `uq_Frwk_ConfigurationItems_LiveVersion` and passes on its own. Use unique names (`$"Test Case Type {Guid.NewGuid():N}"`).
- **Settings survive cleanup.** `Frwk_SettingValues` is kept, so a setting changed by one test stays changed for the next. Apply run-wide settings once in fixture initialisation, and have tests that change a setting set it explicitly.
- **Merging a setting value:** read the module's default first (`WithDefaultValue(...)` in its module class) before overwriting a list-style setting. For example, ServiceAutomation `ExcludedChannels` defaults to `"3"`, so use `"3,7"`, not `"7"`.
- **Renamed entities:** a fixture that configures another module's entity (`GetModelConfigurationsAsync`) fails with `Model configuration not found` when that module renames it (Dep `Contact` → `DirectoryContact`). Check the module source.
- **Guard property lookups:** `config.properties.FirstOrDefault(...) ?? throw new InvalidOperationException("<Class>.<Prop> property config not found")`, not a `NullReferenceException`.

## Custom Respawn helpers

Older suites have their own `ExtendedTestHelper : SheshaTestHelper` with a hand-written `TablesToIgnore` list. If you keep one:
- Add `SchemasToExclude = new[] { "HangFire" }`. Wiping the live Hangfire server's tables causes the deadlocks that the retry loop works around, and it silently drops recurring jobs.
- Run its raw SQL with **`Microsoft.Data.SqlClient`** (as Respawn does), so the deadlock retry, which catches `Microsoft.Data.SqlClient.SqlException` 1205, also catches it.
- But build the **app's** connection string with `System.Data.SqlClient.SqlConnectionStringBuilder`. The Microsoft builder emits keywords (`Trust Server Certificate`) that the app's `System.Data.SqlClient` rejects with `Keyword not supported`.
- Keep the ignore list in step with the schema. A listed table that no longer exists breaks only the raw SQL that references it, and a missing FK partner in the list causes FK conflicts. `Core_Notifications` must be ignored if `Core_NotificationTemplates` is.

## Upgrading an existing (older) suite

Extend mode on a pre-standard project. Bring it to the template in this order, running the happy-line test between steps:
1. Seeded image (`robjomar/shesha-mssql-<project>`) → `robjomar/shesha-mssql-blank`. A stale seeded snapshot can itself fail at startup (duplicate `Frwk_EntityProperties`).
2. Fix fresh-DB migration and package failures (above) until the app boots.
3. Static auth-bypass flags in production code (e.g. `HangFireAuth.disableHangfireAuth`) → `TestHangfireDashboardStartupFilter`; delete the flag.
4. Add the dynamic route refresh, `UseContentRoot`, throwing `SettingsHelpers`, and remove `appsettings` writes to other repos' Web.Host paths.
5. `CleanAllAsync`: Hangfire wait plus deadlock retry. Run one-off setup before the first Hangfire stats call (`/hangfire` fails against a server that hasn't been set up).
6. Fixture lifecycle: set the initialised flag only after setup succeeds; dispose the server before the container; dispose the container on constructor failure.
7. `TestingFrameworkVersion` in `Directory.Build.props` (reuse the project's existing version).
8. Remove committed credentials from test `appsettings.json`, and tell the user they need rotating (they are in git history).
9. Split the single catch-all file into fixture / helpers / models / base, and trim the copied `using` blocks.

## Environment

- About 5 GB of free RAM is the practical minimum (one SQL container plus the test host). Under memory pressure, Claude Code stops background commands, so run the suite in the foreground, in batches under 10 minutes if needed.
- Old `shesha-mssql-*` containers from earlier runs (left behind by `StopAsync`, or by Ryuk being disabled) hold 1-2 GB each. `docker ps -a --filter "ancestor=robjomar/shesha-mssql-blank"`. Ask before stopping or removing ones that aren't from the current session.
- A typical full run of about 20 tests takes around 5 minutes; the first start also pulls the image and runs every migration.
