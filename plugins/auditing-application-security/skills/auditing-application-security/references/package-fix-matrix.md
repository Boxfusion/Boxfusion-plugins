# Verifying Framework Fixes Without Framework Source

## Contents
- The problem
- The three verification methods, in order of authority
- Reading the pinned versions
- The framework hardening set
- Items that remain open in the framework
- Inspecting a compiled assembly with HandMirror
- Recording a verdict honestly

## The problem

An application repository consumes Shesha as compiled packages. The framework-repo audit greps
`shesha-core/src/` to confirm a fix is present; that is not available here. Substituting a guessed
"fixed in version X" table would be worse than useless, because a wrong version claim produces a
false PASS on a live vulnerability.

So this file does not assert which release fixed what beyond what has actually been verified. It
gives a verification **procedure** and a place to record the result.

## The three verification methods, in order of authority

**1. Live behavioural probe — authoritative.** An unauthenticated request against the running
application settles the question for that deployment regardless of version, source or configuration.
Where a check can be expressed as a probe, the probe is the verdict.

```bash
curl -s -o /dev/null -w "%{http_code}" $BASE_URL/api/services/Shesha/NHibernate/GetConventions
```

401 or 403 is secured. 200 is exposed. A 404 means the endpoint does not exist in this version,
which is also secure — but record it as "absent", not as "fixed", because the two differ if the
package is later downgraded.

**2. Compiled assembly inspection — explains the probe.** Reading the class-level attribute off the
DLL tells you whether the package intends the endpoint to be permissioned, which distinguishes
"secure because the package ships an attribute" from "secure because someone configured the DB
record". That distinction decides whether the protection survives a database reset.

**3. Pinned version — a hint only.** Useful for planning an upgrade, never sufficient to close a
finding on its own.

Never mark a check PASS on version evidence alone. If a probe was not possible (backend not
running), the verdict is SKIP with the reason, not PASS.

## Reading the pinned versions

```bash
cat backend/Directory.Build.props
```

A Shesha application typically centralises three version properties:

| Property | Governs |
|----------|---------|
| `SheshaVersion` | `Shesha.Framework`, `Shesha.Application`, `Shesha.Core`, `Shesha.NHibernate`, `Shesha.Web.FormsDesigner`, `Shesha.Scheduler`, `Shesha.Import`, `Shesha.Sms.Clickatell` |
| `EnterpriseVersion` | `Shesha.Enterprise.*`, `Shesha.Workflow` |
| `SaGovVersion` | `Boxfusion.SAGov.*`, `Boxfusion.Persal` |

Also read the frontend versions from `adminportal/package.json` — `@shesha-io/reactjs`,
`@shesha-io/enterprise`, `@shesha-io/workflow`. A frontend and backend on mismatched Shesha minor
versions is itself worth reporting: the frontend may call endpoint shapes the backend does not
implement, or miss a hardening change.

Record all of these in the report header. They are the context for every package-owned finding.

## The framework hardening set

These are the endpoint-authorization behaviours the framework hardened. Each row gives the probe
that settles it and the assembly check that explains it.

The **Verified present** column records the single fact actually established by direct source
inspection of the framework at `releases/0.43` @ v0.43.2 (2026-08-30). It does **not** mean the fix
first appeared in that version, and it says nothing about the version this application pins. Treat
it as "known to exist by then", and always run the probe.

| Check | Probe (expect 401/403) | Assembly check | Verified present |
|-------|----------------------|----------------|-----------------|
| Arbitrary HQL execution | `GET /api/services/Shesha/NHibernate/GetConventions`; `POST …/ExecuteHql` needs **multipart/form-data** | `Shesha.Services.NHibernateAppService` has class-level `SheshaAuthorize` requiring `app:Configurator` | 0.43.2 |
| Scheduled job triggering | `POST /api/services/Scheduler/ScheduledJob/EnqueueAll` | `ScheduledJobAppService`, `ScheduledJobExecutionAppService` require `pages:maintenance` | 0.43.2 |
| Settings write | `POST /api/services/app/Settings/UpdateValue` with `{}` | `SettingsAppService.UpdateValueAsync` requires `pages:maintenance` | 0.43.2 |
| Settings configuration listing | `GET /api/services/app/Settings/GetConfigurations` | `GetConfigurationsAsync` requires `pages:maintenance`, and carries no `AllowAnonymous` | 0.43.2 |
| Email sending | `POST /api/services/app/EmailSender/SendEmail` with `{}` | `EmailSenderAppService` requires `pages:maintenance` | 0.43.2 |
| Configuration package import | `POST /api/services/app/ConfigurationItem/ImportPackage` (**multipart/form-data**) | `ConfigurationItemAppService` requires `app:Configurator` | 0.43.2 |
| OTP settings | `GET /api/services/app/Otp/GetSettings` | `OtpAppService` requires `pages:maintenance` | 0.43.2 |
| Endpoint security write | `PUT /api/services/app/PermissionedObject/Update` | `PermissionedObjectAppService` requires `pages:maintenance` | 0.43.2 |
| Permission definition write | `POST /api/services/app/Permission/Create` | `PermissionAppService` write methods require `app:Configurator` | 0.43.2 |
| Model configuration write | `POST /api/ModelConfigurations` with `{}` | `ModelConfigurationsAppService` requires `app:Configurator` | 0.43.2 |
| Entity config | `GET /api/services/app/EntityConfig/GetMainDataList` | `EntityConfigAppService` requires `app:Configurator` | **DOES NOT HOLD at 0.43.37** — see below |
| Form configuration write | `POST /api/services/Shesha/FormConfiguration/UpdateMarkup` | `FormConfigurationAppService` requires `app:Configurator` | 0.43.2 |
| Endpoint listing | `GET /api/services/app/Api/Endpoints?term=&maxResultCount=3` | `ApiAppService` requires `app:Configurator` | 0.43.2 |
| Authorization settings | `POST /api/services/app/AuthorizationSettings/...` | `AuthorizationSettingsAppService` requires `app:Configurator` | 0.43.2 |
| Excel export permission check | `POST /api/services/Shesha/Entities/ExportToExcel` | `EntitiesAppService.ExportToExcelAsync` calls `CheckPermissionAsync(cfg, "Get")` | 0.43.2 |
| Entity reorder permission check | `PUT /api/services/Shesha/Entities/Reorder` with `{}` | `ReorderAsync` calls `CheckPermissionAsync(cfg, "Update")` | 0.43.2 |
| Specifications listing | **`POST /api/services/app/Entities/Specifications`** | `SpecificationsAsync` requires `app:Configurator` | 0.43.2 |
| OTP randomness | not probeable | `OtpGenerator` uses `RandomNumberGenerator`, not `System.Random` | 0.43.2 |
| `FrameworkController` removed | `GET /api/Framework/Assemblies` returns 404 | type `Shesha.Controllers.FrameworkController` absent | removed by 0.43.2 |
| `DefaultEndpointAccess` default | read the live setting, see below | `SheshaFrameworkModule` defaults it to `AnyAuthenticated` | 0.43.2 |
| Minimum password length | read the live setting | framework default raised to 6 | 0.43.2 |
| Swagger UI gate | `GET /swagger/index.html` returns 403 when disabled | `SwaggerUiAccessMiddleware` exists | 0.43.2 |

If a probe on any row returns 200, that is a live finding for this application regardless of the
pinned version — either the package predates the fix, or a database record overrides it. Check the
`PermissionedObject` record to tell which, and say which in the finding.

**Use `resources/probe_matrix.json` for the exact path, verb and content type of every row
above.** Several are easy to get wrong and each mistake produces a false pass:
`Entities/Specifications` is a POST under `app`, not a GET under `Shesha`; `ExecuteHql` and
`ImportPackage` take multipart; `RemoveConfigurationsOfMissingClasses` is a DELETE;
`FormConfiguration/UpdateMarkup` is a PUT. A 405 or 415 means the probe was malformed, not
that the endpoint is secure.

### Rows verified NOT to hold at 0.43.37

Established by reading the compiled assemblies, not inferred:

| Type | Assembly | What the assembly actually shows |
|------|----------|----------------------------------|
| `Shesha.DynamicEntities.EntityConfigAppService` | `shesha.application/0.43.37/lib/net8.0/Shesha.Application.dll` | **No class-level authorization attribute.** Only `SyncClientApiAsync` carries `[AllowAnonymous]`/`[AbpAllowAnonymous]`. All eleven action records resolve to `Inherited`, so `Create`, `Update`, `Delete` and `RemoveConfigurationsOfMissingClasses` fall through to `DefaultEndpointAccess`. |
| `Shesha.UserManagements.UserManagementAppService` | same | **No authorization attribute.** `Create` and `CompleteRegistration` resolve through `DefaultEndpointAccess`. |

Where a deployment appears to secure either of these, the protection is a database record and
will not survive a database reset. Say so in the finding.

### Shesha.Workflow — check this explicitly

`Shesha.Workflow.AppServices.Processes.ProcessAppService` ships `[AllowAnonymous]` on eight
methods (`hardcoded=true`, `access=5`): `Start`, `StartByName`, `Get`, `GetDetails`,
`GetMyActiveTodoItems`, `GetUserTaskDetails`, `CompleteUserTask`, `SaveUserTask`.

The routes do **not** match the record names — the module segment is `SheshaWorkflow`, and
`CompleteUserTask` is routed as `UserTaskComplete`, `SaveUserTask` as `UserTaskSave`,
`GetMyActiveTodoItems` as `MyActiveTodoItems`, `GetDetails` as `Details`,
`GetUserTaskDetails` as `UserTaskDetails`. Probing the record names returns 404 and reads as
"absent", which is how a run can miss all eight. The `workflow` group in
`probe_matrix.json` has the correct routes.

Because these are `hardcoded=true`, no database change survives a restart. The only
application-level mitigations are a reverse-proxy rule and an upstream request.

## Items that remain open in the framework

These were open at the same verification point. Do not report them as regressions of this
application, and do not expect an upgrade alone to resolve them. Verify whether they still apply to
the pinned version, and mitigate at application level.

| Item | Application-level mitigation |
|------|----------------------------|
| `UserManagementAppService` has no class-level authorization; `Create` resolves through `DefaultEndpointAccess` | If self-service registration is not used, set the `PermissionedObject` for `Shesha.UserManagements.UserManagementAppService@Create` to `Disable` or `RequiresPermissions` |
| `User.DefaultPassword` is still `123qwe` | Change the deployed admin password; the live authentication probe is the check |
| `EntityPermissionedObjectProvider` is commented out, so `Shesha.Entity` records are never bootstrapped | Configure entity action permissions explicitly for sensitive entities |
| `requireAll` is hardcoded false, so multiple permissions are OR'd | Do not model an AND requirement as two permissions on one object |
| No `Content-Security-Policy` and no HSTS in the framework's security headers | Add both in the application's own `Startup.cs` — see `app-vulnerability-baseline.md` |
| `UseSheshaElmah()` mounts the ElmahCore error log as middleware, outside the MVC filter pipeline, so `SheshaAuthorizationFilter` never sees it. Stored records include the full request header block — which means live `Bearer` tokens | Gate `UseSheshaElmah()` on the environment in the application's `Startup.cs`, or put an authorization filter on the `/elmah` path. Probe `GET /elmah/api/errors?i=0&s=5`; if it answers, decode a token's `exp` claim to establish whether it is still valid, and rotate the signing key to invalidate the whole store |
| `AppConsts.DefaultPassPhrase` is a hardcoded literal, deprecated in favour of a config key | Set `Authentication:EncryptionPassPhrase` in the application's configuration |

## Inspecting a compiled assembly with HandMirror

Use fully qualified tool names. Locate the assembly for the pinned package version, then read the
type:

- `mcp__handmirror__list_nuget_package_assemblies` — assemblies in a package version
- `mcp__handmirror__get_type_info` — a type's attributes and members
- `mcp__handmirror__inspect_assembly` — namespaces and types in an assembly
- `mcp__handmirror__search_nuget_types` — find a type when the assembly is unknown
- `mcp__handmirror__get_nuget_package_versions` — available versions, for upgrade advice

Ask for the class-level attributes of, for example, `Shesha.Services.NHibernateAppService` in
`Shesha.NHibernate` at the pinned `SheshaVersion`. The presence of a `SheshaAuthorize` attribute
with `RequiresPermissions` and a permission name confirms the package ships the protection.

If the assembly cannot be resolved — package not restored, tool unavailable — record the check as
probe-only. Do not guess.

## Recording a verdict honestly

| Verdict | Meaning |
|---------|---------|
| PASS | A live probe returned 401, 403 or 404, or the setting holds a safe value |
| FAIL | A live probe returned 200, or the setting holds an unsafe value |
| WARN | Secured, but only by a database record that the bootstrapper will reset, or a value that is safe but below the recommended target |
| SKIP | Could not be tested — backend not running, or the audit account lacked the permission. Never a PASS |
| UNKNOWN | The package version could not be verified and no probe was possible. Report it as an open question, not a pass |

For every package-owned FAIL, the remediation is one of: upgrade the package, set an explicit
`PermissionedObject` access level, or disable the endpoint. It is never "edit the source" — that
source is not in this repository.
