# Test Patterns

All examples assume a class deriving from `IntegrationTestBase` with the constructor `public XTests(DatabaseFixture fixture) : base(fixture) { }`.

## Contents
- Test skeleton and naming
- Happy line create
- Validation theory
- Update
- Delete
- Non-admin user
- Custom app service helper
- Background jobs
- Stored files
- Filtering with GetAllAsync
- Pitfalls

## Test skeleton and naming

Name: `{Action}{Entity}_{Scenario}Async` — e.g. `CreateLibrary_HappyLineAsync`, `CreateLibrary_WithoutMinimumRequirementsAsync`. The `Async` suffix is required by the analyzers.

Every test starts the same way — tests share one container and one server, so each test must reset the data first:

```csharp
await this.CleanAllAsync();
var server = await CreateServerAsync();
using var client = server.CreateClient();
await LoginAsAdminAsync(client);
```

## Happy line create

```csharp
[Fact]
public async Task CreateFilePlanGroup_HappyLineAsync()
{
    await this.CleanAllAsync();
    var server = await CreateServerAsync();
    using var client = server.CreateClient();
    await LoginAsAdminAsync(client);

    var added = await GetFilePlanGroupHelper().CreateAsync(client, new TestFilePlanGroup
    {
        Name = "HR File Plan",
    });

    var loaded = await GetFilePlanGroupHelper().GetAsync(client, added.id);

    Assert.NotEqual(Guid.Empty, added.id);
    Assert.Equal("HR File Plan", loaded.Name);
}
```

Always reload with `GetAsync` and assert on the reloaded entity — the create response can echo input that was never persisted.

Reference properties: create the referenced entity first, then send `new TestGuidEntity { id = parent.id }`. On reload the reference comes back as an object with `id`; assert `loaded.Parent.id`.

`TestGuidEntity` only fits Guid-keyed entities. `User` (and other ABP entities) have a `long` id; typing the reference as `TestGuidEntity` fails with `The JSON value could not be converted to System.Guid. Path: $.result.user.id`. Add a small model for it:

```csharp
public class TestLongEntity
{
    public long id { get; set; }
}
```

Dates: send `DateTime` values truncated to seconds, or compare with `ConvertToISODateNoMilli(...)` — SQL Server rounds milliseconds.

## Validation theory

```csharp
[Theory]
[InlineData(null, "'Name' must not be empty")]
[InlineData("", "'Name' must not be empty")]
public async Task CreateLibrary_WithoutMinimumRequirementsAsync(string? name, string expectedError)
{
    // ...clean, server, login...
    var ex = await Assert.ThrowsAnyAsync<Exception>(() =>
        GetTestLibraryHelper().CreateAsync(client, new TestLibrary { Name = name }));
    Assert.Contains(expectedError, ex.Message);
}
```

Take the expected message from the entity's validator or `[Required]` attribute, not from a guess — run the test once and read the real message if unsure.

## Update

Create → modify the returned object (keep `id`) → `UpdateAsync` → `GetAsync` → assert changed and unchanged fields.

## Delete

Create → `DeleteAsync(client, id)` → assert `GetAsync` throws, or `GetAllAsync` no longer contains the id. Shesha entities are usually soft-deleted, so the row stays in the DB but the API stops returning it.

## Non-admin user

```csharp
await LoginAsAdminAsync(client);
var personId = await CoreTestHelper.AddUserAsync(client, "bob", "test@bob.com", "test@123");
// grant roles/permissions here while still admin
var token = await CoreTestHelper.LoginWithTokenAsync(client, "bob", "test@123");
client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
```

Roles: create `TestShaRole` via `CrudHelperBase<TestShaRole>("Shesha", "ShaRole")`, look it up first with `GetAllAsync(client, name)` so a re-run doesn't duplicate it, then appoint with `ShaRoleAppointedPerson`. Denied access: `Assert.ThrowsAnyAsync` and check the message contains the 403/authorization text.

## Custom app service helper

When an entity is created through an app service (`/api/services/{module}/{Service}/{Method}`), add a helper class next to the test models, matching the framework's error style:

```csharp
public class TestFilePlanActionHelper
{
    public async Task<TestFilePlanGroup> CreateGroupAsync(HttpClient client, string name)
    {
        using var response = await client.PostAsJsonAsync("/api/services/FilePlan/FilePlanSeries/CreateGroup", new { name });
        if (response.IsSuccessStatusCode)
            return (await response.Content.ReadFromJsonAsync<EntityAddResponse<TestFilePlanGroup>>())!.result;
        throw new Exception("Create FilePlanGroup failed: " + await response.Content.ReadAsStringAsync());
    }
}
```

Expose it from `IntegrationTestBase` with `public TestFilePlanActionHelper GetFilePlanActionHelper() => new();`. Find the route from the app service: the `[Route]`/`[AbpApiController]` attribute or the service name convention `/api/services/{ModuleAccessor}/{ServiceNameWithoutAppService}/{Method}`; confirm in Swagger if unsure. Use `PutAsJsonAsync` for `Update*` methods, `GetAsync` with query string for `Get*`, `PostAsync(url, null)` for id-only actions.

## Background jobs

Scheduled jobs are started by their id (the GUID in `[ScheduledJob("...")]`). Store the id as a `protected readonly Guid _{job}JobId` in `IntegrationTestBase`.

```csharp
await RunJobAsAdminAsync(client, _filePlanSeriesImportJobId);
```

Always start jobs through `RunJobAsAdminAsync`, never `CoreTestHelper.StartJobAndWaitForCompleteAsync` directly. The helper polls `ScheduledJobExecution/Get`, which needs the Maintenance permission. It swallows each failed poll and only returns after its 30 s timeout. A test logged in as a normal user still passes, because the job does run, but it spends ~30 s waiting on a job that finished in milliseconds. `RunJobAsAdminAsync` switches to admin for the job and restores the test's login afterwards.

If the app code also enqueues the job itself, the enqueued run may win the race and the test's run finds nothing to do. Poll the domain state (status endpoint or `GetAsync`) until it reaches a terminal value with a timeout rather than asserting straight after the job call.

## Stored files

```csharp
var file = await GetTestStoredFileHelper().UploadAsync(client, new TestStoredFile
{
    file = await File.ReadAllTextAsync(Path.Combine(AppContext.BaseDirectory, "TestFiles", "sample.csv")),
    filesCategory = Guid.NewGuid().ToString(),
});
```

Put fixture files in a folder in the test project and add to the csproj:

```xml
<ItemGroup>
  <Content Include="TestFiles\**\*">
    <CopyToOutputDirectory>PreserveNewest</CopyToOutputDirectory>
  </Content>
</ItemGroup>
```

## Filtering with GetAllAsync

```csharp
var all = await helper.GetAllAsync(client);                                   // everything
var byName = await helper.GetAllAsync(client, "HR");                          // quick search
var filtered = await helper.GetAllAsync(client, "", "", "{\"==\":[{\"var\":\"name\"},\"HR\"]}"); // JsonLogic
var spec = await helper.GetAllAsync(client, "", "My.Namespace.MySpecification");            // specification
```

## Pitfalls

- **Forgetting `CleanAllAsync`** — data leaks between tests; failures depend on run order.
- **Hardcoded lookups on a blank DB** — the container starts empty apart from migrations and seeders. Create every prerequisite (types, roles, users) in the test.
- **Entity 404 on `/api/dynamic/...`** — the entity has no dynamic CRUD (app service generation disabled) or the route refresh in the fixture was removed. Use a custom helper or restore the refresh.
- **Hangfire 401/redirect in `CleanAllAsync`** — the `TestHangfireDashboardStartupFilter` registration in `GetTestServer` was removed or never added, so the app's own dashboard authorization handles `/hangfire`; see SKILL.md Step 4.
- **Tests that take ~31 s each** — a job wait or `WaitForHangfireNotProcessingAsync` is hitting its silent 30 s timeout. The usual cause is starting a job as a non-admin user (job status returns 403 `Required permissions are not granted ... Maintenance`). Use `RunJobAsAdminAsync`. To find slow tests, run with `--logger "trx"` and sort by duration.
- **Passes alone, fails in the full run with a unique-index error** — the entity is a configuration item (`Frwk_ConfigurationItems` survives cleanup), so a fixed name collides with the earlier test's copy. Use a unique name per test. Settings (`Frwk_SettingValues`) survive cleanup too. See [fresh-db-troubleshooting.md](fresh-db-troubleshooting.md).
- **Serialization mismatches** — a test model property whose type doesn't match the API (e.g. `long` ref list vs enum, `string` vs object) fails deserialization with a JSON error. Mirror the DTO the endpoint actually returns.
