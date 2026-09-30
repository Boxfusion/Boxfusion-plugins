# Boxfusion.Common.Tests.TestingFramework API

Namespace: `Boxfusion.Common.Tests.TestingFramework`. Every helper throws `Exception("<Action> failed: <server response body>")` on a non-success status, so a failing call's message carries the server's validation error.

## Contents
- CrudHelperBase<T>
- CoreTestHelper
- SheshaTestHelper
- StoredFileHelper
- Response wrappers
- Ready-made test models

## CrudHelperBase<T>

`new CrudHelperBase<T>(string module, string entityName)` → base URL `/api/dynamic/{module}/{entityName}/Crud/`.

| Method | Notes |
|---|---|
| `Task<T> CreateAsync(HttpClient, T)` | POST Create |
| `Task<T> GetAsync(HttpClient, Guid id)` | GET Get |
| `Task<T> UpdateAsync(HttpClient, T)` | PUT Update — send `id` |
| `Task DeleteAsync(HttpClient, Guid id)` | DELETE |
| `Task<List<T>> GetAllAsync(HttpClient, string quickSearch = "", string specifications = "", string filter = "")` | `filter` is a JsonLogic string; `specifications` is a full specification class name |

`T` needs a `Guid id` for Get/Update/Delete — derive from `TestGuidEntity`.

## CoreTestHelper (static)

| Method | Use |
|---|---|
| `LoginWithTokenAsync(client, user, pass)` → `string` token | set `client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token)` |
| `AddUserAsync(client, username, email, password, mobileNumber = "")` → `Guid` person id | requires an admin token on the client |
| `StartJobAsync(client, jobId)` / `StartJobAndWaitForCompleteAsync(client, jobId)` / `GetJobExecutionSatusAsync(client, jobId)` | Shesha scheduled jobs by their `[ScheduledJob("<guid>")]` id. Status reads need the Maintenance permission; the wait helper swallows the 403 and times out after 30 s, so call it through `RunJobAsAdminAsync` |
| `WaitForHangfireNotProcessingAsync(client)` / `GetHangFireStatsAsync(client)` | calls `/hangfire/stats`; served by the fixture's `TestHangfireDashboardStartupFilter`. Also times out silently after 30 s |
| `GetAllNotificationsAsync(client)` / `GetAllNotificationMessagesAsync(client)` | assert notifications were sent |
| `GetModelConfigurationsAsync(client, module, className)` / `SaveModelConfigurationsAsync(client, config)` | entity config metadata |
| `OtpAuthenticateSendPinAsync`, `OtpAuthenticateAsync`, `OTPSendPinAsync`, `OTPVertifyPinAsync`, `OTPGetAsync` | OTP flows |

## SheshaTestHelper

`new SheshaTestHelper(connectionString).CleanDatabaseAsync()` — Respawn reset of data tables, keeping framework/config data. Only runs against a database whose name marks it as a test DB, which is why the fixture sets `InitialCatalog = "Shesha_IntegrationTests"`.

## StoredFileHelper

`new StoredFileHelper().UploadAsync(client, new TestStoredFile { file = "content", filesCategory = Guid.NewGuid().ToString(), ownerId = ..., ownerType = ..., propertyName = ... })` → uploaded `TestStoredFile` with `id`.

## Response wrappers

Use these when writing custom app service helpers so JSON shapes match ABP responses:

| Type | Shape |
|---|---|
| `EntityAddResponse<T>` | `{ result: T }` — any single-object ABP result |
| `ResulListContainer<T>` | `{ result: List<T> }` |
| `ResultItemsContainer<T>` | `{ result: { items: List<T> } }` — paged results |
| `SingleResult<T>` | single value |

## Ready-made test models

Base: `TestGuidEntity { Guid id }`. Reuse these instead of redefining:

`TestPerson`, `TestPersonWithId`, `TestUser`, `TestOrganisation`, `TestOrganisationPerson`, `TestSite`, `TestContact`, `TestAccount`, `TestStoredFile`, `TestNotification`, `TestNotificationMessage`, `TestNotificationTemplate`, `TestNotificationTypeConfig`, `TestNotificationChannelConfig`, `TestShesaNotification`, plus Service Management models (`TestCase`, `TestCaseType`, `TestCaseRouting`, `TestCaseInteraction`, `TestSLAPolicy`, `TestSLATarget`, `TestSlaPolicyCondition`).

Enums: `RefListPersonTitle`, `PreferredContactMethodEnum`, `PriorityEnum`, `TestRefListNotificationStatus`, `TestRefListNotificationDirection`, and others.

To see the full surface for the version in use, reflect over `bin/Debug/net8.0/Boxfusion.Common.Tests.TestingFramework.dll` from a small net8.0 console app (Windows PowerShell 5.1 cannot load net8 assemblies).
