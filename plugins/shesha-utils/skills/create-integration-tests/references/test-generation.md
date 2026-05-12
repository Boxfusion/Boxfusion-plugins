# Test Generation Guide

After infrastructure scaffolding is confirmed or created, generate actual integration test classes.

## Table of Contents
- [Discovery: What to Test](#discovery-what-to-test)
- [Entity CRUD Tests](#entity-crud-tests)
- [Application Service Tests](#application-service-tests)
- [Entities with Required Relationships](#entities-with-required-relationships)
- [Test Naming Convention](#test-naming-convention)
- [Using Statements](#using-statements)

## Discovery: What to Test

Scan the project to identify testable targets:

1. **Domain entities**: Glob `backend/src/*Domain*/**/*.cs` and grep for `: Entity<Guid>`, `: FullAuditedEntity<Guid>`, or other ABP entity base classes. Each entity should get at least a basic CRUD test.

2. **Application services**: Glob `backend/src/*Application*/**/*AppService.cs`. Each service with custom business logic methods (beyond auto-generated CRUD) should get service-level tests.

3. **Reference lists**: Grep for `[ReferenceList]` attribute in domain entities. Reference list values should be used in test data to validate enum-style fields work correctly.

4. **Already-tested entities**: Grep for `_Tests.cs` files in the test project. Skip entities that already have test coverage.

```
# Find all domain entities
grep -rn "class \w+ : .*Entity<Guid>" backend/src/*Domain*/ --include="*.cs"
grep -rn "class \w+ : .*FullAuditedEntity<Guid>" backend/src/*Domain*/ --include="*.cs"

# Find all application services
find backend/src/*Application*/ -name "*AppService.cs" -type f

# Find existing tests
find backend/test/ -name "*_Tests.cs" -type f
```

## Entity CRUD Tests

For each domain entity, generate a test class with at minimum a `GetAll_Should_Return_{Entities}` test.

### File Placement

**Place each test class in a folder that mirrors the location of the main being tested in the source project.** Determine the relative folder path of the tested class within the source Domain project, then create the same folder path in the test project.

For example, if `Applicant.cs` lives at `backend/src/{Product}.Common.Domain/Enrollment/Applicant.cs`, the test should be at `backend/test/{Product}.Common.Domain.Tests/Enrollment/Applicant_Tests.cs` with namespace `{Product}.Common.Domain.Tests.Enrollment`.

### Simple Entity (no required foreign keys)

```csharp
using System;
using System.Linq;
using System.Threading.Tasks;
using Abp.Domain.Repositories;
using Abp.Domain.Uow;
using {Product}.Common.Tests;
using {Product}.Common.Tests.Fixtures;
using {Product}.Domain.{EntityNamespace};
using Shouldly;
using Xunit;

namespace {Product}.{TestProjectName}.{SubFolder}
{
    [Collection(LocalSqlServerCollection.Name)]
    public class {Entity}_Tests : SheshaNhTestBase
    {
        private readonly IRepository<{Entity}, Guid> _repository;
        private readonly IUnitOfWorkManager _uowManager;

        public {Entity}_Tests(LocalSqlServerFixture fixture) : base(fixture)
        {
            _repository = Resolve<IRepository<{Entity}, Guid>>();
            _uowManager = Resolve<IUnitOfWorkManager>();
        }

        [Fact]
        public async Task GetAll_Should_Return_{Entities}()
        {
            var id = Guid.NewGuid();

            // Arrange — insert test entity
            using (var uow = _uowManager.Begin())
            {
                await _repository.InsertAsync(new {Entity}
                {
                    Id = id,
                    Name = $"IntegrationTest-{id:N}",
                    // Set all required properties with test values
                });
                await uow.CompleteAsync();
            }

            // Act + Assert — verify it's retrievable
            using (var uow = _uowManager.Begin())
            {
                var all = await _repository.GetAllListAsync();
                all.ShouldNotBeNull();
                all.ShouldContain(e => e.Id == id);

                var entity = all.First(e => e.Id == id);
                entity.Name.ShouldStartWith("IntegrationTest-");
                await uow.CompleteAsync();
            }

            // Cleanup
            using (var uow = _uowManager.Begin())
            {
                await _repository.DeleteAsync(id);
                await uow.CompleteAsync();
            }
        }
    }
}
```

### How to Determine Required Properties

Read the entity class. Set values for:
- All properties without `?` (non-nullable) that aren't auto-set by the framework
- Properties with `[Required]` attribute
- Foreign key navigation properties that are non-nullable
- Skip: `Id` (set explicitly for cleanup), `CreationTime`, `CreatorUserId`, audit fields (auto-set)

For reference list properties (enums), use the first non-zero value from the reference list.

## Application Service Tests

For services with custom methods beyond basic CRUD:

```csharp
[Collection(LocalSqlServerCollection.Name)]
public class {Service}_Tests : SheshaNhTestBase
{
    private readonly {Service}AppService _service;
    private readonly IRepository<{Entity}, Guid> _entityRepo;
    private readonly IUnitOfWorkManager _uowManager;

    public {Service}_Tests(LocalSqlServerFixture fixture) : base(fixture)
    {
        _service = Resolve<{Service}AppService>();
        _entityRepo = Resolve<IRepository<{Entity}, Guid>>();
        _uowManager = Resolve<IUnitOfWorkManager>();
    }

    private string Unique(string prefix) => $"{prefix}_{Guid.NewGuid():N}";

    [Fact]
    public async Task {MethodName}_Should_{ExpectedBehavior}()
    {
        {Entity} testEntity = null;
        try
        {
            // Arrange — create prerequisite data
            using (var uow = _uowManager.Begin())
            {
                testEntity = new {Entity}
                {
                    Name = Unique("TestEntity"),
                    // ... required properties
                };
                await _entityRepo.InsertAsync(testEntity);
                await uow.CompleteAsync();
            }

            // Act — call the service method
            using (var uow = _uowManager.Begin())
            {
                var result = await _service.{MethodName}(/* input */);

                // Assert
                result.ShouldNotBeNull();
                // ... specific assertions for the method's expected output
                await uow.CompleteAsync();
            }
        }
        finally
        {
            // Cleanup — always runs even if test fails
            using (var uow = _uowManager.Begin())
            {
                if (testEntity != null)
                    await _entityRepo.DeleteAsync(testEntity);
                await uow.CompleteAsync();
            }
        }
    }
}
```

## Entities with Required Relationships

When an entity has required foreign keys (non-nullable navigation properties), you must create parent entities first and clean up in reverse order.

### Pattern: Parent-Child Cleanup

```csharp
[Fact]
public async Task GetAll_Should_Return_{ChildEntities}()
{
    {Parent} parent = null;
    {Child} child = null;
    try
    {
        // Create parent first
        using (var uow = _uowManager.Begin())
        {
            parent = new {Parent}
            {
                Name = $"Parent-{Guid.NewGuid():N}",
            };
            await _parentRepo.InsertAsync(parent);
            await uow.CompleteAsync();
        }

        // Create child referencing parent
        using (var uow = _uowManager.Begin())
        {
            child = new {Child}
            {
                Name = $"Child-{Guid.NewGuid():N}",
                {Parent} = parent,  // or {Parent}Id = parent.Id
            };
            await _childRepo.InsertAsync(child);
            await uow.CompleteAsync();
        }

        // Act + Assert
        using (var uow = _uowManager.Begin())
        {
            var all = await _childRepo.GetAllListAsync();
            all.ShouldContain(e => e.Id == child.Id);
            await uow.CompleteAsync();
        }
    }
    finally
    {
        // Cleanup: children first, then parents
        using (var uow = _uowManager.Begin())
        {
            if (child != null) await _childRepo.DeleteAsync(child);
            if (parent != null) await _parentRepo.DeleteAsync(parent);
            await uow.CompleteAsync();
        }
    }
}
```

### Deep Relationship Chains

For entities with multiple levels of relationships, create a private `Cleanup` helper:

```csharp
private async Task CleanupChain(Guid rootId)
{
    // Delete leaf entities first, then work up to root
    var leaves = await _leafRepo.GetAllListAsync(l => l.Branch.Root.Id == rootId);
    foreach (var leaf in leaves)
        await _leafRepo.DeleteAsync(leaf);

    var branches = await _branchRepo.GetAllListAsync(b => b.Root.Id == rootId);
    foreach (var branch in branches)
        await _branchRepo.DeleteAsync(branch);

    await _rootRepo.DeleteAsync(rootId);
}
```

## Test Naming Convention

- Test class: `{Entity}_Tests` or `{ServiceName}_Tests`
- Test file location: mirror the source project folder structure (e.g., `Enrollment/Applicant_Tests.cs`)
- Namespace: `{TestProjectName}.{SubFolder}` — matches the mirrored folder path
- Test methods: `{MethodOrAction}_Should_{ExpectedBehavior}`
- Examples:
  - `GetAll_Should_Return_TestCases`
  - `StartRun_Should_Create_Run_With_Cases`
  - `GetKpis_Should_Return_Dashboard_Data`
  - `CompleteRun_Should_Set_Status_Completed`

## Using Statements

### Framework Path (Shesha.Testing available)
```csharp
using {Product}.Common.Tests;            // SheshaNhTestBase
using {Product}.Common.Tests.Fixtures;   // LocalSqlServerCollection (local definition)
using Shesha.Testing.Fixtures;            // LocalSqlServerFixture (from package)
```

### Standalone Path (no Shesha.Testing)
```csharp
using {Product}.Common.Tests;            // SheshaNhTestBase, UnitTestHelper
using {Product}.Common.Tests.Fixtures;   // All fixture types (local definitions)
```

Note: On the Framework Path, test files need BOTH `using {Product}.Common.Tests.Fixtures;` (for `LocalSqlServerCollection.Name`) AND `using Shesha.Testing.Fixtures;` (for `LocalSqlServerFixture` type). However, if the collection class references `LocalSqlServerFixture` from `Shesha.Testing.Fixtures`, and test constructors take `LocalSqlServerFixture`, the test file only needs:
- `using {Product}.Common.Tests.Fixtures;` for the collection name constant
- `using Shesha.Testing.Fixtures;` for the fixture type in the constructor

Alternatively, keep it simple: just use `using Shesha.Testing.Fixtures;` since the `Name` constant resolves to the same string value regardless of which assembly's class is referenced.
