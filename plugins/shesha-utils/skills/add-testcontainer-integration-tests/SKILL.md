---
name: add-testcontainer-integration-tests
description: Adds API-level integration tests to a Shesha/ABP .NET backend using Testcontainers (a throwaway SQL Server container per test run), an in-process ASP.NET TestServer booted from the project's own Web.Host Startup, and the Boxfusion.Common.Tests.TestingFramework NuGet helpers (login, dynamic CRUD, users, stored files, Hangfire jobs, database reset). Scaffolds a new *.Tests.Integration project wired to Directory.Build.props versions, or extends an existing one with new test models, helpers and test classes, then asks which entity to cover first and writes a happy-line create test. Use when the user asks to add, scaffold or extend integration tests, API tests, Testcontainers tests or end-to-end backend tests for a Shesha project, or to add tests for a specific entity or app service.
---

# Add Testcontainer Integration Tests

Each test boots the real application (`UseStartup<Startup>` from the Web.Host project) against a SQL Server container started by Testcontainers, then drives it through HTTP with `HttpClient`. Nothing is mocked: routing, auth, NHibernate, migrations, validators and Hangfire all run for real.

Reference implementation: `pd-content` → `backend/test/boxfusion.content.Domain.Tests.Integration`.

## Files in this skill

| File | Use |
|---|---|
| `assets/Tests.Integration.csproj.template` | New test project file |
| `assets/IntegrationTestBase.cs.template` | Fixture, collection, base class, test server |
| `assets/TestModels.cs.template` | Starting file for test DTOs |
| `assets/EntityTests.cs.template` | First happy-line test class |
| [references/versions-and-build-props.md](references/versions-and-build-props.md) | **Read before touching any .csproj or Directory.Build.props** |
| [references/testing-framework-api.md](references/testing-framework-api.md) | What the TestingFramework package provides — read before writing any helper |
| [references/test-patterns.md](references/test-patterns.md) | Patterns for happy line, validation, update, delete, permissions, jobs, files, custom app services |
| [references/fresh-db-troubleshooting.md](references/fresh-db-troubleshooting.md) | **Read when a test fails on the blank DB, or before upgrading an older suite**: finding the real error (ELMAH), swallowed migration failures, `.shaconfig` traps, cleanup traps, upgrade order |

Placeholders in templates use `{{Name}}`. Replace every one; grep the output for `{{` before building.

## Workflow

### Step 1: Discover the backend

Run from the repo root. Record every value — later steps use them.

```bash
find . -name "Directory.Build.props" -not -path "*/node_modules/*"      # → BackendDir (its folder)
find <BackendDir> -maxdepth 1 -name "*.sln"                             # → SolutionFile
find <BackendDir>/src -name "*.Web.Host.csproj"                          # → WebHostProject
find <BackendDir>/src -name "*.Web.Core.csproj"                          # → WebCoreProject
grep -rln "class Startup" <BackendDir>/src --include=*.cs                # → StartupNamespace
grep -rn "new SheshaModuleInfo(\"" <BackendDir>/src --include=*.cs       # → module names (CRUD route segment)
grep -rln "Boxfusion.Common.Tests.TestingFramework" <BackendDir> --include=*.csproj
```

Derive:
- `RootNamespace` — the Web.Host project name minus `.Web.Host` (e.g. `boxfusion.content`).
- `TestProjectName` — `{RootNamespace}.Domain.Tests.Integration` unless the repo already has a different `*.Tests.Integration` naming convention.
- `ModuleNames` — every string passed to `new SheshaModuleInfo("...")`. `CrudHelperBase<T>(module, entity)` builds `/api/dynamic/{module}/{entity}/Crud/`; routing is case-insensitive, so the module info name works as-is. Framework entities (Person, User, ShaRole, Notification …) use module `"Shesha"`.

### Step 2: Choose mode

- **Extend** — a test project already references `Boxfusion.Common.Tests.TestingFramework` and has a `DatabaseFixture`. Read its `IntegrationTestBase.cs` and two existing test classes first. Match their conventions exactly: where test models live, helper-getter naming (`GetTest{Entity}Helper()`), login style, assert style. Do not re-scaffold infrastructure. Still run the Step 3 version checks. If the existing suite predates this standard (seeded image, auth-bypass flag in production code, no route refresh, one catch-all file), follow *Upgrading an existing suite* in [references/fresh-db-troubleshooting.md](references/fresh-db-troubleshooting.md). On a blank DB, expect to find real migration and config-package bugs that the seeded image hid.
- **Scaffold** — no such project. Continue with Steps 3–5.

An existing NUnit/xUnit unit-test project (e.g. `*.Common.Domain.Tests` using `Abp.TestBase`/SQLite) is not this kind of project — leave it alone and scaffold a new one beside it.

### Step 3: Versions and Directory.Build.props

Follow [references/versions-and-build-props.md](references/versions-and-build-props.md). In short:
- `TestingFrameworkVersion` lives in `Directory.Build.props` next to `SheshaVersion`; the csproj references `$(TestingFrameworkVersion)` — never a literal.
- Reuse a value the repo already has. Otherwise use the pinned default from the reference file.
- Keep all other package versions identical to the reference csproj so every Boxfusion project runs the same stack.

### Step 4: Project-side prerequisites (scaffold mode)

Check each; change source only where required and tell the user what changed.

1. **Hangfire dashboard auth — nothing to change in the app.** `CleanAllAsync` and the job helpers call the `/hangfire` stats endpoints, which the app's dashboard authorization blocks (401 → `Reserve Vehicle failed:` with an empty body). The template handles this entirely on the test side: `GetTestServer` registers `TestHangfireDashboardStartupFilter`, an `IStartupFilter` that maps its own `/hangfire` dashboard with an allow-all filter ahead of the app's pipeline. Startup filters run before `Startup.Configure`, so the test dashboard answers those calls and the app's dashboard and its filter are never reached in tests. Do not add bypass flags to the project's `HangfireAuthorizationFilter` or edit `Startup` — this works whichever filter Startup uses (project or Shesha's `Shesha.Scheduler.Hangfire.HangfireAuthorizationFilter`).
   - Check the app uses Hangfire: `grep -rn "AddHangfire(" <BackendDir>/src --include=*.cs`. The test dashboard needs the `JobStorage` that `AddHangfire` registers.
   - No Hangfire in the project → remove the `TestHangfireDashboardStartupFilter` registration and classes, the `Hangfire`/`Hangfire.Dashboard` usings, and the `WaitForHangfireNotProcessingAsync` call in `CleanAllAsync`.
2. **Dynamic route refresh.** On a blank DB the dynamic CRUD controllers are registered before the entity configs exist, so every `/api/dynamic/...` call 404s. The template fixes this with `SheshaActionDescriptorChangeProvider` (namespace `Shesha.DynamicEntities`, in `Shesha.Application` 0.39–0.44). Check it exists for the project's `SheshaVersion`:
   ```bash
   grep -c SheshaActionDescriptorChangeProvider ~/.nuget/packages/shesha.application/<SheshaVersion>/lib/net8.0/Shesha.Application.dll
   ```
   Missing → delete `RefreshDynamicRoutesAsync`, its call in `GetServerAsync`, and the `.ConfigureServices(...)` block in `GetTestServer`; warn the user that dynamic CRUD tests may 404 on a blank DB.
3. **appsettings.json** reaches the test `bin` through the Web.Host project reference; the fixture overwrites `ConnectionStrings:Default` there. Nothing to add.
4. **Docker** must be running locally (Testcontainers). The image is `robjomar/shesha-mssql-blank`; the database is `Shesha_IntegrationTests` and the app's migrations build the schema on first boot. Default admin is `admin` / `123qwe`.

### Step 5: Scaffold the project (scaffold mode)

1. Create `<BackendDir>/test/{{TestProjectName}}/` with:
   - `{{TestProjectName}}.csproj` from `assets/Tests.Integration.csproj.template`
   - `IntegrationTestBase.cs` from `assets/IntegrationTestBase.cs.template`
   - `TestModels.cs` from `assets/TestModels.cs.template`
2. Set the `ProjectReference` paths to the actual Web.Core and Web.Host csproj files (relative, backslashes as in the other csproj files of the repo).
3. Add one `const string _{module}NameSpace = "<module name>";` per module in `IntegrationTestBase`.
4. Add to the solution under the existing test solution folder (usually `Tests`):
   ```bash
   dotnet sln <SolutionFile> add <path/to/csproj> --solution-folder Tests
   ```
5. `dotnet build <csproj>` — fix all errors and analyzer warnings before writing tests (AsyncFixer and VSTHRD200 require the `Async` suffix on every async method, including test methods).

### Step 6: Ask which entity to test first

List candidate entities from the domain projects:

```bash
grep -rnE "class \w+ : (FullAudited|Audited|Creation)?Entity<Guid>|class \w+ : \w+Base\b" <BackendDir>/src/Module --include=*.cs
```

Skip abstract classes, join entities and entities marked `GenerateApplicationService = ...Disable...` (no dynamic CRUD). Use AskUserQuestion with up to 4 of the most central entities (the ones other entities reference most), each labelled with its module; the user can type another.

If the entity is normally created through a custom app service (e.g. `ContentActions/CreateLibrary`) rather than dynamic CRUD, ask which endpoint the happy line should use — see *Custom app service helper* in [references/test-patterns.md](references/test-patterns.md).

### Step 7: Write the happy-line create test

1. Read the entity class, its base classes and any validator (`grep -rn "AbstractValidator<{Entity}>\|IValidator<{Entity}>"`) to find required properties and value rules.
2. Add `Test{Entity} : TestGuidEntity` to the test models file:
   - Scalars and reference-list enums: same name and type, nullable where the entity is nullable. Reference-list enums can be used directly from the domain assembly.
   - Entity references: `TestGuidEntity` (send `new TestGuidEntity { id = ... }`).
   - Skip audit fields, collections, `[SaveAsJson]` objects and anything read-only.
3. Add `GetTest{Entity}Helper()` returning `new CrudHelperBase<Test{Entity}>(_{module}NameSpace, "{Entity}")` to `IntegrationTestBase`.
4. Create `{Entity}Tests.cs` from `assets/EntityTests.cs.template`. The happy line: clean DB → create server → login as admin → create any referenced prerequisites → `CreateAsync` → `GetAsync(id)` → assert every property that was sent.
5. Build and run just that test:
   ```bash
   dotnet test <csproj> --filter "FullyQualifiedName~{Entity}Tests"
   ```
   First run pulls the image and runs migrations (several minutes). If it fails, read the exception text from the helper (`Create ... failed: {server response}`) and fix the DTO or prerequisites — do not weaken assertions to make it pass. If the message is vague (`SQL not available`, `Login failed` with an HTML page, a connection reset), the real error is in the log or in `elmah.errors`. See [references/fresh-db-troubleshooting.md](references/fresh-db-troubleshooting.md).

### Step 8: Offer the rest of the suite

After the happy line passes, offer to add for the same entity (pattern for each in [references/test-patterns.md](references/test-patterns.md)):
- validation `[Theory]` for each required field
- update happy line
- delete
- access as a non-admin user
- any custom app service endpoints or background jobs the entity uses

Then offer the next entity. Report which tests were added and the pass/fail output of the last run.
