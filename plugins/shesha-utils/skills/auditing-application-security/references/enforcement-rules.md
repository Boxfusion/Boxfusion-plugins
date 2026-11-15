# Shesha Endpoint Enforcement Rules

## Contents
- How to read this file from an application repository
- The authorization chain
- The CrudMethods dictionary
- Which entities get dynamic CRUD endpoints
- PermissionedObject type mapping
- Bootstrap versus runtime
- The definitive precedence model
- Classification table for the catalog
- Retired classifications
- Verifying the chain without framework source

## How to read this file from an application repository

This describes how the **compiled Shesha framework** enforces endpoint authorization at runtime.
An application repository cannot grep the framework source to confirm any of it, so treat this file
as the model and confirm behaviour three ways instead:

1. **Live probe** — an unauthenticated request against a running backend is the ground truth and
   outranks everything else in this file.
2. **Package version** — the framework version pinned in `backend/Directory.Build.props` determines
   which behaviours apply. See `package-fix-matrix.md` in this directory.
3. **Assembly inspection** — read attributes off the compiled DLL when a version check is ambiguous
   (see the last section).

The model below reflects Shesha 0.43.2 and later. Where an older package is pinned, the differences
are called out inline.

## The authorization chain

```
HTTP Request
  |
  +- SheshaAuthorizationFilter (global MVC filter, registered in the app's Startup.cs)
  |   +- Not a controller action? -> SKIP
  |   +- ResolveAll ISheshaAuthorizationHelper -> call AuthorizeAsync on each
  |
  |       There is NO [AllowAnonymous] short-circuit in this filter.
  |       Anonymous access is decided by the PermissionedObject record and the
  |       DefaultEndpointAccess / replaceInherited fallback -- never by the filter.
  |       |
  |       +- ApiAuthorizationHelper
  |       |   +- hasCodeAllowAnonymous = [AllowAnonymous] or [AbpAllowAnonymous]
  |       |   |     on class or method   <- recorded, does NOT cause a skip
  |       |   +- type is not ControllerBase AND does not implement IApplicationService? -> SKIP
  |       |   +- type.IsSheshaDynamicCrudAppService() AND methodName (minus "Async")
  |       |   |     is in CrudMethods? -> SKIP (EntityCrudAuthorizationHelper takes it)
  |       |   +- ObjectPermissionChecker.AuthorizeAsync(
  |       |         requireAll: false,
  |       |         typeName, methodName, "Shesha.WebApi.Action", isAuthenticated,
  |       |         replaceInherited: hasCodeAllowAnonymous
  |       |                             ? AllowAnonymous
  |       |                             : DefaultEndpointAccess)
  |       |
  |       +- EntityCrudAuthorizationHelper
  |           +- methodName (minus "Async") NOT in CrudMethods? -> SKIP
  |           +- NOT type.IsSheshaDynamicCrudAppService()? -> SKIP
  |           +- No entity type resolved from the AbpCrudAppService base generic? -> SKIP
  |           +- No EntityConfig found for the entity? -> SKIP
  |           +- ObjectPermissionChecker.AuthorizeAsync(
  |                 requireAll: false,
  |                 entityFullName, crudMethod, "Shesha.Entity.Action", isAuthenticated,
  |                 replaceInherited: DefaultEndpointAccess)
  |
  +- ObjectPermissionChecker.AuthorizeAsync(...)
      +- Authorization disabled globally? -> ALLOW
      +- Map method via CrudMethods -> build "{object}@{method}"
      +- Lookup PermissionedObject from DB/cache (GetOrDefaultAsync)
      |   +- Not found? -> returns a default DTO with Access=Inherited
      +- Resolve actualAccess:
      |   +- If replaceInherited is set AND ActualAccess == Inherited -> use replaceInherited
      |   +- Otherwise -> use ActualAccess as-is
      +- permission is null? -> ALLOW
      +- actualAccess == AllowAnonymous? -> ALLOW
      +- actualAccess == AnyAuthenticated AND authenticated? -> ALLOW
      +- NOT authenticated? -> THROW 401
      +- actualAccess == Disable? -> THROW 404
      +- actualAccess == RequiresPermissions + no permissions? -> THROW 403
      +- actualAccess == RequiresPermissions + permissions? ->
          ShaPermissionChecker.AuthorizeAsync(requireAll=false, permissions)
```

### Consequences

| Consequence | Why |
|-------------|-----|
| `[AllowAnonymous]` is a **fallback**, not an override | It only supplies `replaceInherited`. A PermissionedObject with an explicit non-Inherited access level wins at runtime. |
| Entity CRUD obeys `DefaultEndpointAccess` | `EntityCrudAuthorizationHelper` passes it. If the setting is `AllowAnonymous (5)`, every unconfigured entity CRUD endpoint is anonymous. Flag CRITICAL when found. |
| No method is skipped by both helpers | Both gate on `IsSheshaDynamicCrudAppService()`. |
| Hand-coded CRUD services are service-authorized | `SheshaCrudServiceBase` and `AbpCrudAppService` subclasses do **not** implement `IDynamicCrudAppService`. Their CRUD methods resolve against `Shesha.WebApi.Action`, not the entity record. |
| Coverage includes `IApplicationService` | Services implementing the interface without deriving from ABP's `ApplicationService` are authorized. |

## The CrudMethods dictionary

Methods in this dictionary are handled by `EntityCrudAuthorizationHelper` at entity level. Methods
not in it are handled by `ApiAuthorizationHelper` at service level.

```
GetAll   -> Get        Create    -> Create
QueryAll -> Get        CreateGql -> Create
Get      -> Get        Update    -> Update
Query    -> Get        UpdateGql -> Update
                       Delete    -> Delete
```

Not mapped, so service-level only: `ExportToExcel`, `Specifications`, `Reorder`, and any custom
method. The name match is exact after removing the `Async` suffix — `GetAll` matches,
`GetAllLeaveRequests` does not.

The dictionary is only a routing decision, and `ApiAuthorizationHelper` honours it **only** when the
service implements `IDynamicCrudAppService`.

## Which entities get dynamic CRUD endpoints

This is the single most important section for an application audit, because it determines how much
unintended surface the application exposes.

**Phase 1 — EntityConfig bootstrapping.** At startup the bootstrapper scans loaded assemblies for
NHibernate-mapped entity types. For each new entity it creates an `EntityConfig` row. Whether
`GenerateAppService` defaults to true depends on the framework version and on the entity's
`[Entity(GenerateApplicationService = ...)]` attribute. For an existing row, the value is preserved
unless the attribute explicitly forces it.

**Phase 2 — Dynamic controller registration.** `DynamicEntityControllerFeatureProvider` first
registers manually-coded services implementing `IEntityAppService`, then loads `EntityConfig` rows
and generates a `DynamicCrudAppService` controller for each remaining entity.

**The consequence to check on every audit:** in framework versions before the generation filter was
added, controller registration did **not** consult `GenerateAppService`. Every entity with an
`EntityConfig` row got CRUD endpoints regardless of the flag. Do not assume the flag is being
honoured — verify against the live endpoint list. If an entity with `GenerateAppService = false`
still answers on `/api/dynamic/.../Crud/GetAll`, the flag is not being enforced by the pinned
framework version, and disabling must be done through the `PermissionedObject` record instead.

An entity gets CRUD endpoints when all of these hold: it inherits from an entity base class, it has
an `EntityConfig` row, the type is loadable, it has an `Id`, and no manually-coded
`IEntityAppService` is registered for it.

**Route:** `api/dynamic/{moduleName}/{EntityTypeName}/Crud/{ActionName}` — module resolved from the
entity's assembly module, falling back to `app`; controller named `{EntityTypeName}Crud` unless
overridden by `[Entity(ApplicationServiceName = "...")]`.

| Action | HTTP | Route suffix |
|--------|------|-------------|
| `Get` | GET | `/Crud/Get?id={id}` |
| `GetAll` | GET | `/Crud/GetAll` |
| `Create` | POST | `/Crud/Create` |
| `Update` | PUT | `/Crud/Update` |
| `Delete` | DELETE | `/Crud/Delete?id={id}` |
| `CreateGql` / `UpdateGql` | POST / PUT | hidden from Swagger |

## PermissionedObject type mapping

| Endpoint pattern | Type | Object name format |
|-----------------|------|--------------------|
| App service, service level | `Shesha.WebApi` | `{Namespace}.{ClassName}` |
| App service, action level | `Shesha.WebApi.Action` | `{Namespace}.{ClassName}@{MethodName}` |
| Dynamic CRUD, entity level | `Shesha.Entity` | `{EntityNamespace}.{EntityName}` |
| Dynamic CRUD, action level | `Shesha.Entity.Action` | `{EntityNamespace}.{EntityName}@{CrudAction}` |
| CRUD app service, service level | `Shesha.WebCrudApi` | `{EntityNamespace}.{EntityName}` |
| CRUD app service, action level | `Shesha.WebCrudApi.Action` | `{EntityNamespace}.{EntityName}@{CrudAction}` |
| Form configuration | `Shesha.Form` | `{FormModule}/{FormName}` |

## Bootstrap versus runtime

**Bootstrap (startup).** `ApiPermissionedObjectProvider` scans controllers and app services and
writes PermissionedObject rows:

- `[AllowAnonymous]` / `[AbpAllowAnonymous]` — `access=5`, `hardcoded=true`
- `[AbpAuthorize("p")]` / `[AbpMvcAuthorize("p")]` — `access=4`, `permissions=["p"]`, `hardcoded=true`
- `[SheshaAuthorize(access)]` — the given access, `hardcoded=false`
- no attribute — `access=2` (Inherited), `hardcoded=false`

`PermissionedObjectsBootstrapper` then reconciles code against the database:

```csharp
if (item.Hardcoded == true || dbItem.Access == RefListPermissionedAccess.Inherited)
{
    dbItem.Access      = item.Access ?? Inherited;
    dbItem.Permissions = string.Join(",", item.Permissions);
    dbItem.Hardcoded   = item.Hardcoded ?? false;
}
```

So: new objects are inserted; `hardcoded` objects are overwritten every restart; **objects still at
`Inherited` are overwritten from code every restart**; objects with an explicit non-Inherited access
and `hardcoded=false` are left alone and admin changes persist.

This matters for remediation advice. If an object is currently `Inherited`, telling the user to
change it in the admin UI is wrong for a `hardcoded` object and only durable for a non-hardcoded one
once an explicit level is set.

**Runtime.** No code attribute is a bypass. `[SheshaAuthorize]` and `[AbpAuthorize]` are not read
per-request at all. `[AllowAnonymous]` only supplies the `Inherited` fallback, and
`EntityCrudAuthorizationHelper` ignores it entirely. The database `actualAccess` is what is enforced.

## The definitive precedence model

```
STEP 1: Which helper handles this endpoint?

  Is the declaring type a ControllerBase subclass, OR does it implement IApplicationService?
    NO  -> Neither helper applies. "Unknown (not a Shesha endpoint)"
    YES -> continue

  Does the type implement IDynamicCrudAppService?
  (SheshaCrudServiceBase and AbpCrudAppService do NOT.)

    YES, and methodName (minus "Async") is an exact CrudMethods key
      -> EntityCrudAuthorizationHelper handles it:
           objectType       = "Shesha.Entity.Action"
           objectName       = "{entityFullName}@{mappedCrudMethod}"
           replaceInherited = DefaultEndpointAccess

    Anything else
      -> ApiAuthorizationHelper handles it:
           objectType       = "Shesha.WebApi.Action"
           objectName       = "{classFullName}@{methodName}"
           replaceInherited = [AllowAnonymous] on class or method
                                ? AllowAnonymous
                                : DefaultEndpointAccess

STEP 2: Look up the PermissionedObject
  Record exists?  YES -> use it
                  NO  -> default DTO with Access = Inherited, Parent = the "{...}" before "@"
  Resolve actualAccess:
    Access != Inherited                                  -> actualAccess = Access
    Access == Inherited AND parent resolves non-Inherited -> actualAccess = parent's (recursive)
    Access == Inherited AND no parent resolves            -> actualAccess = Inherited

STEP 3: Apply replaceInherited
  IF replaceInherited is set AND actualAccess == Inherited:
      actualAccess = replaceInherited

  DefaultEndpointAccess is therefore the single effective default for BOTH hand-coded endpoints
  and entity CRUD. Setting it to AllowAnonymous (5) exposes every unconfigured entity CRUD
  endpoint anonymously.

STEP 4: Enforce, first match wins
  4a. permission is null                                  -> ALLOW
  4b. actualAccess == AllowAnonymous (5)                  -> ALLOW
  4c. actualAccess == AnyAuthenticated (3) AND logged in   -> ALLOW
  4d. NOT logged in                                       -> DENY 401
  4e. actualAccess == Disable (1)                         -> DENY 404
  4f. actualAccess == RequiresPermissions (4), empty perms -> DENY 403
  4g. actualAccess == RequiresPermissions (4), has perms   -> ShaPermissionChecker, OR logic
  4h. actualAccess still Inherited (2), logged in          -> ALLOW (configuration anomaly)

STEP 5: Additional per-method checks
  EntitiesAppService.Get / GetAll / QueryAll -> CheckPermissionAsync(cfg, "Get")
  EntitiesAppService.ExportToExcel           -> CheckPermissionAsync(cfg, "Get")
  EntitiesAppService.Reorder                 -> CheckPermissionAsync(cfg, "Update")
  EntitiesAppService.Specifications          -> [SheshaAuthorize(RequiresPermissions,
                                                  "app:Configurator")]
```

## Classification table for the catalog

Classify on the resolved database access plus the helper's `replaceInherited`, never on a code
attribute alone.

| Condition | Auth Level | Enforcement |
|-----------|-----------|-------------|
| `actualAccess` 5, `hardcoded=true` | Anonymous (code to DB, hardcoded) | Written to DB at bootstrap; resets on restart |
| `actualAccess` 5, `hardcoded=false` | Anonymous (DB, configurable) | DB record; admin changes persist |
| `actualAccess` 2, no parent resolves, `[AllowAnonymous]`, non-dynamic-CRUD | Anonymous (code fallback) | `replaceInherited = AllowAnonymous` |
| `actualAccess` 2, no parent resolves, no `[AllowAnonymous]` | resolved via `DefaultEndpointAccess` | `replaceInherited = DefaultEndpointAccess` |
| `actualAccess` 3, `hardcoded=true` | Authenticated (DB, hardcoded) | Resets on restart |
| `actualAccess` 3, `hardcoded=false` | Authenticated (DB, configurable) | Admin changes persist |
| `actualAccess` 2 + parent resolves | parent's level (inherited, resolved) | Inheritance |
| `actualAccess` 4, non-empty permissions | Permissioned (DB) | ShaPermissionChecker, OR logic |
| `actualAccess` 4, empty permissions | Permissioned (DB, empty = deny-all) | Blocks everyone, admins included |
| `actualAccess` 1 | Disabled (DB) | 404, and removed from Swagger |
| Not a ControllerBase and not an `IApplicationService` | Unknown (not a Shesha endpoint) | No Shesha enforcement |

**Multiple permissions use OR logic.** `requireAll` is false at every call site. An endpoint
requiring two permissions grants access to a user holding either.

## Retired classifications

Do not emit these — they describe behaviour that no longer exists:

| Retired | Why |
|---------|-----|
| `Anonymous (code override)` | `[AllowAnonymous]` is a fallback for `Inherited` only |
| `Authenticated (accidental)` | Entity CRUD resolves deliberately via `DefaultEndpointAccess` |
| `Authenticated (CRUD method bypass)` | Both helpers no longer skip the same method |

## Verifying the chain without framework source

The application repository owns `Startup.cs`, so the one piece of the chain that **is** greppable
here is the filter registration. Confirm it:

```bash
grep -rn "SheshaAuthorizationFilter" backend/src --include=*.cs | grep -v "/obj/"
```

Expect `options.Filters.AddService(typeof(SheshaAuthorizationFilter))` inside `ConfigureServices`.
If it is missing or commented out, **all** Shesha endpoint authorization is inert and every finding
in the catalog is moot — report it as the single highest-severity finding and stop.

For everything inside the packages, use the HandMirror MCP tools against the resolved assembly in
the NuGet cache rather than guessing from the version number:

- `mcp__handmirror__get_type_info` — read a type's attributes and members, for example to confirm
  `Shesha.Services.NHibernateAppService` carries a class-level `SheshaAuthorize`.
- `mcp__handmirror__list_nuget_package_assemblies` and `mcp__handmirror__inspect_assembly` — locate
  and open the assembly for a pinned package version.
- `mcp__handmirror__search_nuget_types` — find a type when its assembly is not known.

A live anonymous probe still outranks assembly inspection. Inspection explains *why* a probe
behaves as it does; it does not replace the probe.
