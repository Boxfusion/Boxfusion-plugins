---
name: create-integration-tests
description: Creates and scaffolds integration test projects for Shesha framework .NET applications. Sets up xUnit test infrastructure with NHibernate, database fixtures, test modules, and base classes. Detects whether Shesha.Testing NuGet package is available and adapts accordingly — using the package when present, or scaffolding local infrastructure when not. Use when the user asks to create, add, scaffold, implement, or set up integration tests, test projects, or test infrastructure for a Shesha project.
---

# Shesha Integration Tests

Scaffolds integration test infrastructure and creates integration tests for Shesha framework applications.

## Step 0: Inventory Source and Test Projects

Before scaffolding, build a map of all source projects and their corresponding test projects.

### 0a. Discover all source projects

```
# List all source projects (Domain, Application, etc.)
find backend/src/ -name "*.csproj" -type f
```

Identify the projects that contain testable code — typically Domain and Application projects (e.g., `{Product}.{Module}.Application`, `{Product}.{Module}.Domain`).

### 0b. Discover existing test projects

```
# Look for existing test projects
find backend/test/ -name "*Tests.csproj" -type f
# Look for existing test modules
grep -rn "SheshaModule" backend/test/ --include="*.cs" -l
# Look for existing test base classes
grep -rn "SheshaNhTestBase" backend/test/ --include="*.cs" -l
```

### 0c. Map source projects to test projects

For each source project, check whether a corresponding `*.Tests` project already exists under `backend/test/`. The convention is `{SourceProjectName}.Tests` — for example:

| Source project | Expected test project |
|---|---|
| `{Product}.Common.Domain` | `{Product}.Common.Domain.Tests` |
| `{Product}.Common.Application` | `{Product}.Common.Application.Tests` |
| `{Product}.Foo.Domain` | `{Product}.Foo.Domain.Tests` |

Classify each source project as:
- **Covered** — a matching `*.Tests` project exists
- **Uncovered** — no matching test project exists

**If ALL relevant source projects are covered**: skip to [Test Generation](#test-generation) (Phase 2 in Workflow).

**If some source projects are uncovered**: proceed to [Test Project Strategy](#test-project-strategy) before scaffolding.

## Test Project Strategy

**Ideally, each source project that contains testable code should have its own dedicated test project.** This keeps test dependencies focused and mirrors the solution's modular structure.

When uncovered source projects are found, **ask the user before creating new test projects**. Present the mapping and let them choose:

> The following source projects do not have a corresponding test project:
> - `{Product}.Foo.Domain` (no `{Product}.Foo.Domain.Tests` found)
> - `{Product}.Common.Application` (no `{Product}.Common.Application.Tests` found)
>
> Options:
> 1. **Create dedicated test projects** for each uncovered source project (recommended — mirrors solution structure)
> 2. **Add tests to an existing test project** (e.g., `{Product}.Common.Domain.Tests`) — simpler but mixes concerns
>
> Which approach would you prefer?

If the user chooses option 2, add the necessary project references to the existing test project's `.csproj` and ensure its test module `DependsOn` includes the modules from the newly covered source projects. Tests still follow the [mirrored folder placement](#test-file-placement) convention within whichever test project they land in.

If the user chooses option 1, scaffold each new test project using the steps below. New test projects can share infrastructure (fixtures, base classes) from an existing test project by adding a project reference to it, or scaffold their own — prefer sharing when a `{Product}.Common.Tests` or `{Product}.Common.Domain.Tests` project already provides `SheshaNhTestBase` and fixtures.

## Step 1: Shesha.Testing Available?

Before generating scaffolding code, determine which path to follow:

1. Check if the project references `Shesha.Testing` as a NuGet package or project reference
2. Check if `Shesha.Testing` namespace is resolvable (grep for `Shesha.Testing` in `.csproj` files)
3. Check if `SheshaTestModuleHelper.ConfigureForTesting` exists in referenced packages

**If Shesha.Testing IS available** (framework version with the package): use the **Framework Path**. See [references/framework-path.md](references/framework-path.md).

**If Shesha.Testing is NOT available** (older framework version): use the **Standalone Path**. See [references/standalone-path.md](references/standalone-path.md).

## Detection Script

```
# Check in the .csproj files of the solution
grep -r "Shesha.Testing" --include="*.csproj" backend/
# Also check NuGet package cache
grep -r "SheshaTestModuleHelper" --include="*.cs" backend/
```

If neither grep returns results, use the Standalone Path.

## Project Structure (both paths)

```
backend/test/{Product}.Common.Domain.Tests/
├── {Product}CommonDomainTestModule.cs   ← SheshaModule, test configuration
├── appsettings.Test.json                ← DB connection + DBMS type
├── log4net.config                       ← Logging config
├── Fixtures/
│   ├── LocalSqlServerCollection.cs      ← xUnit collection definition
│   └── (Standalone only: IDatabaseFixture.cs, LocalSqlServerFixture.cs)
├── DependencyInjection/
│   └── ServiceCollectionRegistrar.cs    ← Identity bridge (standalone only)
├── (Standalone only infrastructure files)
└── {MirroredFolders}/                   ← Mirrors source project structure
    └── {Entity}_Tests.cs
```

### Test File Placement

**Test classes must be placed in a folder structure that mirrors the source project being tested.** This keeps tests organized and easy to locate.

To determine the correct folder, look at the namespace/folder of the class under test in the source project (e.g., `backend/src/{Product}.Common.Domain/`), then replicate that relative folder path inside the test project.

**Example:** If the source project has:
```
backend/src/{Product}.Common.Domain/
├── Enrollment/
│   ├── Applicant.cs
│   └── Application.cs
├── Assessments/
│   └── TestCase.cs
└── Scheduling/
    └── Appointment.cs
```

Then the test project should mirror it:
```
backend/test/{Product}.Common.Domain.Tests/
├── Enrollment/
│   ├── Applicant_Tests.cs
│   └── Application_Tests.cs
├── Assessments/
│   └── TestCase_Tests.cs
└── Scheduling/
    └── Appointment_Tests.cs
```

The namespace of each test class should reflect this folder path (e.g., `{Product}.Common.Domain.Tests.Enrollment`).

## Core Conventions

### Naming
- Test project: `{SourceProjectName}.Tests` — mirrors the source project name (e.g., `{Product}.Common.Domain.Tests`, `{Product}.Foo.Application.Tests`)
- Test module: `{SourceProjectName}TestModule` with dots removed (e.g., `{Product}CommonDomainTestModule`)
- Namespace: `{SourceProjectName}.Tests` (infrastructure), `{SourceProjectName}.Tests.{SubFolder}` (test classes — matches mirrored folder path)
- Test DB name: `{ProductShort}-IntegrationTest` (shared across all test projects — they use the same database)

### Test Class Pattern
```csharp
[Collection(LocalSqlServerCollection.Name)]
public class {Entity}_Tests : SheshaNhTestBase
{
    private readonly IRepository<{Entity}, Guid> _repo;
    private readonly IUnitOfWorkManager _uowManager;

    public {Entity}_Tests(LocalSqlServerFixture fixture) : base(fixture)
    {
        _repo = Resolve<IRepository<{Entity}, Guid>>();
        _uowManager = Resolve<IUnitOfWorkManager>();
    }

    [Fact]
    public async Task GetAll_Should_Return_{Entities}()
    {
        var id = Guid.NewGuid();

        // Arrange
        using (var uow = _uowManager.Begin())
        {
            await _repo.InsertAsync(new {Entity} { Id = id, /* ... */ });
            await uow.CompleteAsync();
        }

        // Act + Assert
        using (var uow = _uowManager.Begin())
        {
            var all = await _repo.GetAllListAsync();
            all.ShouldContain(e => e.Id == id);
            await uow.CompleteAsync();
        }

        // Cleanup
        using (var uow = _uowManager.Begin())
        {
            await _repo.DeleteAsync(id);
            await uow.CompleteAsync();
        }
    }
}
```

### Key Rules
- Each DB operation in its own `using (var uow = _uowManager.Begin())` block
- Always `await uow.CompleteAsync()` to flush NHibernate
- Use `try/finally` for cleanup when test data has relationships
- Resolve services in constructor via `Resolve<T>()`
- Use `Shouldly` assertions (`ShouldBe`, `ShouldNotBeNull`, `ShouldContain`)
- Unique test data names: `$"{prefix}_{Guid.NewGuid():N}"`

### Test Module DependsOn (minimum)
```csharp
[DependsOn(
    typeof({Product}ApplicationModule),  // Your app module
    typeof({Product}Module),             // Your domain module
    typeof(AbpKernelModule),
    typeof(AbpTestBaseModule),
    typeof(AbpAspNetCoreModule),
    typeof(SheshaApplicationModule),
    typeof(SheshaNHibernateModule),
    typeof(SheshaFrameworkModule),
    typeof(SheshaWorkflowModule)         // Required if any entities reference workflow types
)]
```

**Important:** Include `SheshaWorkflowModule` if domain entities reference any types from `Shesha.Workflow` (e.g. workflow-related entities, approval processes). Without it, NHibernate mapping fails with: `The given key 'Shesha.Workflow, Version=...' was not present in the dictionary`.

### appsettings.Test.json
```json
{
  "DbmsType": "SQLServer",
  "ConnectionStrings": {
    "Default": "Data Source=.;Initial Catalog={ProductShort}-IntegrationTest;Integrated Security=True;TrustServerCertificate=True",
    "TestDB": "Data Source=.;Initial Catalog={ProductShort}-IntegrationTest;Integrated Security=True;TrustServerCertificate=True"
  }
}
```

Both `Default` and `TestDB` keys must be present and identical.

### csproj Essentials
```xml
<PackageReference Include="Abp.Castle.Log4Net" Version="9.0.0" />
<PackageReference Include="Abp.TestBase" Version="9.0.0" />
<PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.8.0" />
<PackageReference Include="Moq" Version="4.20.70" />
<PackageReference Include="NSubstitute" Version="5.1.0" />
<PackageReference Include="Shouldly" Version="4.2.1" />
<PackageReference Include="xunit" Version="2.6.3" />
<PackageReference Include="xunit.extensibility.execution" Version="2.6.3" />
<PackageReference Include="xunit.runner.visualstudio" Version="2.5.5" />
```

Plus project references to the Application and Domain projects.

### Notification Channel Senders

If the code under test sends notifications (e.g. approval workflows, notification services), you must register concrete `INotificationChannelSender` implementations in `ServiceCollectionRegistrar`. Without this, tests fail with: `NotificationSender waiting for INotificationChannelSender`.

```csharp
// Add to ServiceCollectionRegistrar.Register() before WindsorRegistrationHelper call
services.AddTransient<INotificationChannelSender, EmailChannelSender>();
services.AddTransient<INotificationChannelSender, SmsChannelSender>();
```

Use concrete implementations (not mocks) for integration tests — the goal is to verify the full code path works end-to-end.

## Workflow

### Phase 1: Infrastructure

1. **Inventory** — discover all source projects and existing test projects (Step 0 above)
2. **Map coverage** — identify which source projects are covered and which are uncovered
3. **Ask the user** — if uncovered source projects exist, present the mapping and ask whether to create dedicated test projects or add tests to an existing project (see [Test Project Strategy](#test-project-strategy)). **Do not create new test projects without user confirmation.**
4. **Detect Shesha.Testing availability** (Step 1 above)
5. Read [references/framework-path.md](references/framework-path.md) or [references/standalone-path.md](references/standalone-path.md)
6. **For each test project to scaffold** (may be one or many depending on user's choice):
   - Create the test project directory and csproj (with project references to the source project it covers)
   - Create appsettings.Test.json and log4net.config (copy from [assets/log4net.config](assets/log4net.config))
   - Create the test module class (DependsOn must include modules from the source project being tested)
   - Create fixture and collection classes (or reference them from an existing test project that already has them)
   - Create infrastructure files (standalone path only)
   - Add the test project to the solution
7. **Build to verify** — `dotnet build` all test projects to confirm infrastructure compiles

### Phase 2: Test Generation (ALWAYS execute this phase)

This phase runs whether infrastructure was just scaffolded or already existed. Repeat for each test project.

8. **Discover testable targets** — read [references/test-generation.md](references/test-generation.md) for discovery commands and patterns
9. **Scan domain entities** — glob `backend/src/*Domain*/**/*.cs`, grep for entity base classes
10. **Scan application services** — glob `backend/src/*Application*/**/*AppService.cs`
11. **Check existing coverage** — grep for `*_Tests.cs` across all test projects, skip entities/services already tested
12. **Create entity CRUD test classes** — one `{Entity}_Tests.cs` per untested entity with at least a `GetAll` test. Place in the test project that corresponds to the entity's source project, in a folder that mirrors the entity's location (see [Test File Placement](#test-file-placement))
13. **Create service test classes** — one `{Service}_Tests.cs` per untested service with custom methods. Place in the matching test project with mirrored folder structure
14. **Build and verify** — `dotnet build` all test projects to confirm all tests compile

## Test Generation

After infrastructure is confirmed or scaffolded, **always** generate actual test classes. See [references/test-generation.md](references/test-generation.md) for:
- How to discover entities and services to test
- Entity CRUD test template
- Handling entities with required foreign key relationships
- Parent-child cleanup patterns
- Test naming conventions

Key principle: every domain entity gets at least one test class verifying CRUD via repository. Every application service with custom business logic gets a test class exercising its methods.

## Service-Level Test Pattern

For testing application services (not just repositories):

```csharp
[Collection(LocalSqlServerCollection.Name)]
public class Dashboard_Tests : SheshaNhTestBase
{
    private readonly DashboardAppService _dashboardService;
    private readonly IRepository<TestCase, Guid> _testCaseRepo;
    private readonly IUnitOfWorkManager _uowManager;

    public Dashboard_Tests(LocalSqlServerFixture fixture) : base(fixture)
    {
        _dashboardService = Resolve<DashboardAppService>();
        _testCaseRepo = Resolve<IRepository<TestCase, Guid>>();
        _uowManager = Resolve<IUnitOfWorkManager>();
    }

    private string Unique(string prefix) => $"{prefix}_{Guid.NewGuid():N}";

    [Fact]
    public async Task GetKpis_Should_Return_Dashboard_Data()
    {
        Entity entity = null;
        try
        {
            using (var uow = _uowManager.Begin())
            {
                entity = new Entity { Name = Unique("Test"), /* ... */ };
                await _repo.InsertAsync(entity);
                await uow.CompleteAsync();
            }

            using (var uow = _uowManager.Begin())
            {
                var result = await _dashboardService.GetKpis();
                result.ShouldNotBeNull();
                // assertions...
                await uow.CompleteAsync();
            }
        }
        finally
        {
            using (var uow = _uowManager.Begin())
            {
                if (entity != null) await _repo.DeleteAsync(entity);
                await uow.CompleteAsync();
            }
        }
    }
}
```
