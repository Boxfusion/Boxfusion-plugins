# Access Control Implementation Patterns

Code templates and patterns for implementing Shesha access control.

**Every code sample below that touches `ICurrentUser`, `ShaSpecification<T>`, or a permission
checker is illustrative, not a verified API contract.** The exact members differ across Shesha
versions (see a confirmed real-world mismatch in § Global Specification Pattern below — an async
`ICurrentUser.HasPermissionAsync`/`GetPermissionScope` and `BuildExpressionAsync()` that turned out
not to exist in a project on `Shesha.Framework` 0.43.37, where the real API was a synchronous
`BuildExpression()` and `IShaPermissionChecker.IsGranted(...)`). **Reflect against the target
project's actual referenced package versions before writing this code for real** — see SKILL.md §
Key Rules, "Verify the framework API shape" — and before adding any new helper method, check
whether `Shesha.Core`, `Shesha.Enterprise`, or the app's own Domain/Application layers already
provide it.

---

## Folder Structure

All access control artifacts (permission constants, role constants, authorizer interfaces and implementations, **and permission-based global specifications**) are placed under an `AccessControl/` folder in the application layer module. Only specifications encoding domain/business rules (not permission checks) remain in the Domain layer alongside their entities.

```
{ModuleName}.Application/
  AccessControl/
    {Module}Permissions.cs              # Permission name constants
    {Module}Roles.cs                    # Role name constants
    Authorizers/
      I{Entity}Authorizer.cs           # Authorizer interface
      {Entity}Authorizer.cs            # Authorizer implementation
      I{Entity2}Authorizer.cs          # One interface per entity
      {Entity2}Authorizer.cs           # One implementation per entity
    Specifications/
      {Entity}PermissionsSpecification.cs       # Permission-based data filtering
      {ChildEntity}PermissionsSpecification.cs  # Child entity permission filtering
  Services/{EntityNamePlural}/
    {Entity}AppService.cs              # Application service (consumes authorizers)

{ModuleName}.Domain/
  Domain/{EntityNamePlural}/
    {Entity}.cs                         # Entity class
    {Entity}SomeBusinessSpecification.cs # Domain/business rule specifications (NOT permission-based)
```

**Key placement rules:**
- `{Module}Permissions.cs` and `{Module}Roles.cs` go directly under `AccessControl/` — one file each for the entire module
- Authorizer interfaces and implementations go under `AccessControl/Authorizers/` — one pair per entity that needs complex authorization
- **Permission-based global specifications** (those that check `ICurrentUser` permissions to filter data) go under `AccessControl/Specifications/` — these are access control concerns, not domain logic
- Domain/business rule specifications (e.g., "only show active records", "filter by tenant") remain in the Domain layer alongside their entities
- Application services remain in `Services/{EntityNamePlural}/` and inject the authorizers they need

---

## Authorizer Pattern

Use dedicated authorizer classes for entities with complex (hybrid) authorization logic. This centralizes authorization, making it reusable across application services and testable in isolation.

**Same caveat as § Global Specification Pattern**: `ICurrentUser.HasPermissionAsync` and
`ICurrentUser.IsPermissionScopedToEntity` below are illustrative. On `Shesha.Framework` 0.43.37
neither exists (nor does the underlying Resource-Based/"`-where-Scoped-to-`" role-scoping
infrastructure at all — no `ICurrentUser.GetPermissionScope`, no `ShaRoleAppointedPerson.PermissionedEntity*`).
Verify before use. The confirmed-real alternative for a permission check in a normal (non-`ShaSpecification`)
class is ABP's standard, ubiquitous `IPermissionChecker.IsGrantedAsync(name)` (inject `IPermissionChecker`,
not `ICurrentUser`); for a project genuinely on a version with Resource-Based scoping, confirm the
real method names by reflection first rather than assuming `IsPermissionScopedToEntity` is one of them.
Also consider whether a bespoke authorizer class is even needed at all: if the project's
`[GlobalSpecification]` mechanism applies to every repository query (not just `GetAll` listing —
verify this too), a specification alone may already cover read/update/delete-targeting
authorization for an entity, making a separate authorizer redundant for anything but action-verb
distinctions (e.g. blocking delete specifically) it can't express.

### Authorizer Interface

File: `{ModuleName}.Application/AccessControl/Authorizers/I{Entity}Authorizer.cs`

```csharp
// {ModuleName}.Application/AccessControl/Authorizers/I{Entity}Authorizer.cs
public interface I{Entity}Authorizer
{
    Task<bool> CanView{Entity}({Entity} entity);
    Task<bool> CanCreate{Entity}({ParentEntity} parent);  // or Guid parentId
    Task<bool> CanUpdate{Entity}({Entity} entity);
    Task<bool> CanDelete{Entity}({Entity} entity);
    // Add domain-specific actions as needed:
    // Task<bool> CanApprove{Entity}({Entity} entity);
    // Task<bool> CanDeployTo{Entity}({Entity} entity);
}
```

### Authorizer Implementation

File: `{ModuleName}.Application/AccessControl/Authorizers/{Entity}Authorizer.cs`

```csharp
// {ModuleName}.Application/AccessControl/Authorizers/{Entity}Authorizer.cs
public class {Entity}Authorizer : I{Entity}Authorizer
{
    private readonly ICurrentUser _currentUser;

    public {Entity}Authorizer(ICurrentUser currentUser)
    {
        _currentUser = currentUser;
    }

    public async Task<bool> CanView{Entity}({Entity} entity)
    {
        // Check in order: RBAC → Resource-Based → ABAC

        // 1. RBAC: Global permission (fastest)
        if (await _currentUser.HasPermissionAsync("{Entity}-View"))
            return true;

        // 2. Resource-Based: Direct scoping
        if (_currentUser.IsPermissionScopedToEntity(
            "{Entity}-View-where-Scoped", entity.Id))
            return true;

        // 3. Resource-Based: Hierarchical scoping (if applicable)
        if (entity.{Parent} != null
            && _currentUser.IsPermissionScopedToEntity(
                "{Entity}-View-where-Scoped-to-{Parent}", entity.{Parent}.Id))
            return true;

        // 4. ABAC: Condition-based (if applicable)
        if (await _currentUser.HasPermissionAsync("{Entity}-View-if-Owner")
            && entity.Owner != null
            && entity.Owner.Id == _currentUser.Person?.Id)
            return true;

        return false;
    }

    public async Task<bool> CanCreate{Entity}({ParentEntity} parent)
    {
        // 1. RBAC: Global permission
        if (await _currentUser.HasPermissionAsync("{Entity}-Create"))
            return true;

        // 2. Resource-Based: Scoped to parent
        if (_currentUser.IsPermissionScopedToEntity(
            "{Entity}-Create-where-Scoped-to-{Parent}", parent.Id))
            return true;

        return false;
    }

    public async Task<bool> CanUpdate{Entity}({Entity} entity)
    {
        // 1. RBAC: Global permission
        if (await _currentUser.HasPermissionAsync("{Entity}-Update"))
            return true;

        // 2. Resource-Based: Direct scoping
        if (_currentUser.IsPermissionScopedToEntity(
            "{Entity}-Update-where-Scoped", entity.Id))
            return true;

        // 3. Resource-Based: Hierarchical scoping
        if (entity.{Parent} != null
            && _currentUser.IsPermissionScopedToEntity(
                "{Entity}-Update-where-Scoped-to-{Parent}", entity.{Parent}.Id))
            return true;

        return false;
    }

    public async Task<bool> CanDelete{Entity}({Entity} entity)
    {
        // 1. RBAC: Global permission
        if (await _currentUser.HasPermissionAsync("{Entity}-Delete"))
            return true;

        // 2. Resource-Based: Direct scoping
        if (_currentUser.IsPermissionScopedToEntity(
            "{Entity}-Delete-where-Scoped", entity.Id))
            return true;

        return false;
    }
}
```

### Registering the Authorizer

Register in the application module's `Initialize()` or `PreInitialize()`:

```csharp
IocManager.Register<I{Entity}Authorizer, {Entity}Authorizer>(DependencyLifeStyle.Transient);
```

Or use `[Dependency(DependencyLifeStyle.Transient)]` attribute if auto-registration is enabled.

---

## Global Specification Pattern

**This section's code samples are illustrative, not verified.** They show one plausible shape of
`ShaSpecification<T>`/`ICurrentUser` (an async `BuildExpressionAsync()`, `ICurrentUser.HasPermissionAsync`/
`GetPermissionScope`). A real project on `Shesha.Framework` 0.43.37 turned out to have a **different**,
**synchronous** shape instead: `ShaSpecification<T>.BuildExpression()` (not `Async`), with permission
checks done via `IShaPermissionChecker.IsGranted(userId, permissionName, entityRef)` resolved from
`IocManager` (the injectable `ICurrentUser.HasPermissionAsync`/`GetPermissionScope` used below did not
exist in that package version at all). **Reflect against the project's actual referenced package
version before assuming either shape** — see SKILL.md § Key Rules, "Verify the framework API shape".
The "Verified-real pattern" subsection below shows the confirmed-working alternative; prefer it once
you've confirmed it matches the project's own Shesha version, and adapt as needed if it doesn't.

### Parent Entity Specification (illustrative — verify first)

File: `{ModuleName}.Application/AccessControl/Specifications/{Entity}PermissionsSpecification.cs`

```csharp
// {ModuleName}.Application/AccessControl/Specifications/{Entity}PermissionsSpecification.cs
[Description("Limits visibility of {Entity} based on user permissions.")]
[GlobalSpecification]
public class {Entity}PermissionsSpecification : ShaSpecification<{Entity}>
{
    private readonly ICurrentUser _currentUser;

    public {Entity}PermissionsSpecification(ICurrentUser currentUser)
    {
        _currentUser = currentUser;
    }

    public override async Task<Expression<Func<{Entity}, bool>>> BuildExpressionAsync()
    {
        // CRITICAL: Always check Person first
        if (_currentUser.Person == null)
            return entity => false;

        // 1. RBAC: Global permission — return true early for performance
        if (await _currentUser.HasPermissionAsync("{Entity}-View"))
            return entity => true;

        // 2. Resource-Based: Collect ALL scoped IDs before building expression
        var scopedEntityIds = _currentUser.GetPermissionScope("{Entity}-View-where-Scoped");
        var scopedParentIds = _currentUser.GetPermissionScope("{Entity}-View-where-Scoped-to-{Parent}");

        // 3. ABAC: Resolve boolean flags before building expression
        var canViewIfOwner = await _currentUser.HasPermissionAsync("{Entity}-View-if-Owner");

        var currentPersonId = _currentUser.Person.Id;

        // 4. Build combined expression
        return entity =>
            // Resource-Based checks
            scopedEntityIds.Contains(entity.Id)
            || (entity.{Parent} != null && scopedParentIds.Contains(entity.{Parent}.Id))
            // ABAC checks
            || (canViewIfOwner && entity.Owner != null
                && entity.Owner.Id == currentPersonId);
    }
}
```

### Parent Entity Specification — verified-real pattern (Shesha.Framework 0.43.37 + Shesha.Enterprise 5.1.7)

Confirmed by reflecting against the actual NuGet packages (not documentation) in a real project.
`ShaSpecification<T>` exposes `AbpSession` and `IocManager` (property-injected — no constructor
needed), and `BuildExpression()` is **synchronous**. Rather than reimplementing person/permission
resolution via raw repository queries, use the confirmed real framework services — see SKILL.md §
Key Rules, "Reuse framework helpers", for the full menu (current-person, current-position,
different-person's-position, is-granted) and which package each comes from:

```csharp
// {ModuleName}.Application/AccessControl/Specifications/{Entity}PermissionsSpecification.cs
[Description("Limits visibility of {Entity} based on user permissions.")]
[GlobalSpecification]
public class {Entity}PermissionsSpecification : ShaSpecification<{Entity}>
{
    public override Expression<Func<{Entity}, bool>> BuildExpression()
    {
        if (AbpSession.UserId == null)
            return entity => false;

        var permissionChecker = IocManager.Resolve<IShaPermissionChecker>();

        // 1. RBAC: Global permission — return true early for performance
        if (permissionChecker.IsGranted(AbpSession.UserId.Value, "{Entity}-View", null))
            return entity => true;

        // 2. ABAC: current Person via the real Enterprise session. NOT the sync
        //    EnterpriseSessionBase.PersonId property -- that one is an override-scope-only value
        //    that is null for every ordinary request (confirmed live: see SKILL.md § "Reuse
        //    framework helpers", Current Person). Use GetLoggedInPersonAsync() (async only) and
        //    block on it -- safe here for the same reason as the position-appointment call below.
        Guid? currentPersonId;
#pragma warning disable VSTHRD002 // Synchronously waiting on tasks or awaiters may cause deadlocks
        try
        {
            var enterpriseSession = (Shesha.Enterprise.Session.EnterpriseSessionBase)AbpSession;
            currentPersonId = enterpriseSession.GetLoggedInPersonAsync().GetAwaiter().GetResult()?.Id;
        }
        catch (Abp.AbpException)
        {
            currentPersonId = null;
        }
#pragma warning restore VSTHRD002
        if (currentPersonId == null)
            return entity => false;

        return entity => entity.Owner != null && entity.Owner.Id == currentPersonId;
    }
}
```

### Correlating against a different entity type — never a nested `IQueryable` closure

Sometimes the entity being filtered has no direct FK to the thing you actually need to check
ownership/permission against (e.g. a reporting/flattened view that carries the source record's Id as
a plain `Guid` column, not a real navigation property) — so the owner check has to look the related
record up in a *different* repository. **Do not resolve a second repository's `GetAll()` and call
`.Any(...)`/`.Where(...)` on it from inside the returned expression** — confirmed as a real
performance problem on a live project:

```csharp
// WRONG — flagged as a genuine performance risk on a real project, do not use this shape
var otherRepo = IocManager.Resolve<IRepository<OtherEntity, Guid>>();
var otherEntities = otherRepo.GetAll();               // IQueryable, tied to its own session/context
return entity =>
    entity.OtherEntityId != null && otherEntities.Any(o =>  // <- nested queryable inside a closure
        o.Id == entity.OtherEntityId && o.Owner.Id == currentPersonId);
```

The problem: `otherEntities` is a *live* `IQueryable` created independently of the outer query being
built for `entity`. NHibernate's LINQ provider generally cannot fold two independently-created
queryables into a single correlated SQL subquery — depending on the provider and query shape, this
either throws at translation time or silently falls back to loading the *entire* `OtherEntity` table
into memory on every single query against the entity this specification protects (which, for a
`[GlobalSpecification]`, is every `Get`/`GetAll` — including paginated list views hit repeatedly).

**Instead, run one small, already-correlated query up front, then use `Contains` against the
materialized result:**

```csharp
// RIGHT — one targeted query, materialized once, then a plain Contains
var ownedOtherEntityIds = IocManager.Resolve<IRepository<OtherEntity, Guid>>()
    .GetAll()
    .Where(o => o.Owner != null && o.Owner.Id == currentPersonId)
    .Select(o => o.Id)
    .ToList();

return entity =>
    entity.OtherEntityId != null && ownedOtherEntityIds.Contains(entity.OtherEntityId.Value);
```

This still only runs once per `BuildExpression()` call (same as the broken version — `BuildExpression()`
itself is called once per query, not once per row), but the eager query is now small and properly
filtered server-side by the owner condition (typically a handful of rows: "this person's own
records"), and the outer expression becomes a plain `Contains` against an in-memory list, which every
LINQ provider — NHibernate included — translates to a cheap SQL `IN (...)`. Apply the same pattern
any time a spec needs to correlate against a second entity type; never leave a second repository's
live `IQueryable` captured inside the returned expression.

### Child Entity Specification (Inheriting Parent Permissions)

File: `{ModuleName}.Application/AccessControl/Specifications/{ChildEntity}PermissionsSpecification.cs`

```csharp
// {ModuleName}.Application/AccessControl/Specifications/{ChildEntity}PermissionsSpecification.cs
[Description("Filters {ChildEntity} based on user's {ParentEntity} permissions.")]
[GlobalSpecification]
public class {ChildEntity}PermissionsSpecification : ShaSpecification<{ChildEntity}>
{
    private readonly ICurrentUser _currentUser;

    public {ChildEntity}PermissionsSpecification(ICurrentUser currentUser)
    {
        _currentUser = currentUser;
    }

    public override async Task<Expression<Func<{ChildEntity}, bool>>> BuildExpressionAsync()
    {
        if (_currentUser.Person == null)
            return child => false;

        // Inherit from parent: {ParentEntity} permissions

        // 1. RBAC: Global permission on parent
        if (await _currentUser.HasPermissionAsync("{ParentEntity}-View"))
            return child => true;

        // 2. Resource-Based: Parent-scoped permissions
        var scopedParentIds = _currentUser.GetPermissionScope("{ParentEntity}-View-where-Scoped");
        var scopedGrandparentIds = _currentUser.GetPermissionScope(
            "{ParentEntity}-View-where-Scoped-to-{Grandparent}");

        // 3. Build expression navigating to parent
        return child =>
            child.{Parent} != null && (
                scopedParentIds.Contains(child.{Parent}.Id)
                || (child.{Parent}.{Grandparent} != null
                    && scopedGrandparentIds.Contains(child.{Parent}.{Grandparent}.Id))
            );
    }
}
```

### Child Entity Specification (With Extra Security Layer)

For child entities needing MORE restrictive access than their parent:

File: `{ModuleName}.Application/AccessControl/Specifications/{ChildEntity}PermissionsSpecification.cs`

```csharp
// {ModuleName}.Application/AccessControl/Specifications/{ChildEntity}PermissionsSpecification.cs
[Description("Filters {ChildEntity} based on parent {ParentEntity} permissions AND child-specific restrictions.")]
[GlobalSpecification]
public class {ChildEntity}PermissionsSpecification : ShaSpecification<{ChildEntity}>
{
    private readonly ICurrentUser _currentUser;

    public {ChildEntity}PermissionsSpecification(ICurrentUser currentUser)
    {
        _currentUser = currentUser;
    }

    public override async Task<Expression<Func<{ChildEntity}, bool>>> BuildExpressionAsync()
    {
        if (_currentUser.Person == null)
            return child => false;

        // Check child-specific permission first (more restrictive)
        if (await _currentUser.HasPermissionAsync("{ChildEntity}-View"))
            return child => true;

        // Fall through to parent permissions for basic visibility
        if (await _currentUser.HasPermissionAsync("{ParentEntity}-View"))
        {
            // Parent permission only grants limited child access
            // e.g., can see child exists but not sensitive details
            return child => child.{Parent} != null;
        }

        var scopedParentIds = _currentUser.GetPermissionScope("{ParentEntity}-View-where-Scoped");

        return child =>
            child.{Parent} != null && scopedParentIds.Contains(child.{Parent}.Id);
    }
}
```

---

## Disabling CRUD Generation Entirely (not just restricting who can call it)

Two different needs get confused easily — pick the right one:
- **Restrict who can call an action** (e.g. only Administrators can delete): use a `[GlobalSpecification]`
  for read-side filtering, plus the `PermissionedObject` API for action-verb-specific rules a
  specification can't express (see SKILL.md § Step 4f and api-reference.md § PermissionedObject API).
- **The endpoint(s) shouldn't exist at all** (e.g. "CRUD disabled entirely" in a spec, or "no one
  should ever be able to list/create/update/delete this") — that's what this section covers.

### Entity defined in the project's own source

Add `[Entity(GenerateApplicationService = GenerateApplicationServiceState.DisableGenerateApplicationService)]`
directly to the entity class:

```csharp
// {ModuleName}.Domain/Domain/{EntityNamePlural}/{Entity}.cs
[Discriminator]
[Entity(GenerateApplicationService = GenerateApplicationServiceState.DisableGenerateApplicationService)]
public class {Entity} : FullAuditedEntity<Guid>
{
    // ...
}
```

Confirmed end-to-end in a real project: this attribute causes no application service (and
therefore no REST endpoint at all — no Get/GetAll/Create/Update/Delete) to be generated for that
entity, and it correctly seeds a matching `EntityConfig` row (`generateAppService: false`, with the
entity's module intact) — no separate runtime configuration step needed. Internal code (other
domain/application services in the project) can still read/write the entity directly via its
repository; only the dynamic-CRUD REST surface is removed.

### Entity NOT defined in the project's own source (e.g. compiled into a referenced package)

There's no class to attach the attribute to. Use one of:

1. **Frontend admin UI (recommended)** — log in to the admin portal, go to **Configurations →
   Entity Configuration** (the exact menu path may vary by project theme/version — it's the screen
   backed by the `EntityConfig` API below), find the entity by name, and toggle its "Generate
   Application Service" (or equivalently-labelled) setting off. A human using the form is far less
   likely to trigger the module-corruption bug described next, since form validation/UX typically
   prevents submitting a broken module reference in the first place.
2. **`EntityConfig` REST API** — see api-reference.md § EntityConfig API and § Common Pitfalls #8
   **before** using this. `PUT /api/services/app/EntityConfig/Update` has a confirmed bug where
   changing `generateAppService` via this endpoint can silently null out the entity's `ModuleId` in
   the database, with no known safe request body that avoids it. If you must use it, immediately
   verify `moduleId` didn't get wiped afterward and be ready to fix it via direct SQL (documented
   there, including a gotcha where a sandboxed shell tool may refuse to run the fix even after
   explicit user confirmation — try a different available tool, e.g. PowerShell if Bash was denied,
   rather than concluding the fix isn't possible).

---

## Finding and Disabling Unused APIs

When asked to "disable APIs that aren't used" or similar cleanup, this is a **detect, then decide,
then disable** workflow — never skip straight to disabling:

1. **Detect.** This skill doesn't itself catalogue endpoint usage — the `auditing-application-security`
   skill (if available in this project) builds an endpoint-usage catalogue by cross-referencing
   backend routes against actual frontend form/API calls, and flags `isUnreferenced=true` results.
   Treat every such result as a **review item, not an apply-safely item** — "no reference found in
   the forms this run scanned" is not proof nothing calls it (a mobile client, an integration, or a
   form outside the scanned set could still depend on it). If that skill isn't available, the
   discovery still has to happen some way before disabling anything — searching the frontend's API
   call sites, checking any integration/API-consumer documentation, and asking whoever owns the
   project are all reasonable substitutes; don't disable an entity's API surface based on a code
   search of this repo alone.
2. **Decide, per candidate, with the user.** Present what would be disabled and its blast radius
   before acting — this mirrors the "measure twice" rule that applies to any destructive,
   hard-to-reverse, live-system-affecting change. Confirm scope explicitly rather than assuming
   "unused" and "safe to remove" mean the same thing; they don't when the evidence for "unused" is
   incomplete.
3. **Disable, using the right mechanism for what "disable" means here:**
   - The whole entity's CRUD surface should not exist → § Disabling CRUD Generation Entirely, above.
   - Only some actions, or only for some permission holders → the `PermissionedObject` API (SKILL.md
     § Step 4f, api-reference.md § PermissionedObject API) — e.g. set a specific action to
     `access: 1` (`Disable`) to block it for everyone, or `access: 4` (`RequiresPermissions`) with a
     permission nobody holds.
   - A confirmed-unused **permission itself** (not an entity/action, the permission definition) —
     § Migration Pattern: Deleting Unused Permissions, below, if the target project uses
     FluentMigrator (check for a `Migrations/` folder in its Domain projects first); otherwise the
     Permission/ShaRole APIs directly (api-reference.md § Permission API, § Role API), one
     environment at a time.
4. **Verify.** Re-fetch the entity/action's `EntityConfig`/`PermissionedObject` state after the
   change and confirm it matches what was intended — both APIs involved here have confirmed bugs
   (see api-reference.md § Common Pitfalls #3 and #8) where a write can silently do something other
   than what was asked.

---

## Module-Wide Entity Sweep

Different task from § Finding and Disabling Unused APIs above: that section is about deciding
whether a *specific* entity/action should be disabled. This one is for "go through every entity in
this module and either disable it or lock its permissions down" — a request to cover the whole
module's `EntityConfig` surface, not one entity at a time. Confirmed end-to-end on a real project
covering ~50 entities across two Shesha modules; do it as a scripted sweep, not by opening each
entity individually in the admin UI or issuing one `GetAllTree`-then-inspect round trip per entity.

### 1. Pull both APIs in full, once

```
GET /api/services/app/EntityConfig/GetAll?maxResultCount=1000
GET /api/services/app/PermissionedObject/GetAll?maxResultCount=2000
```

Both can be large (hundreds of KB) — dump each to a file rather than trying to read the raw response
inline, then process with a short Python/Node script. Do not re-query per entity; the whole point of
pulling both lists up front is that everything else is a client-side join.

### 2. Build one row per entity

Filter `EntityConfig` results to the target module(s) (`module` field), **drop every row with
`notImplemented: true`** (dead metadata for a class that no longer resolves — see api-reference.md §
EntityConfig API; grep the repo for the class name if you want to double-check before trusting the
flag), and watch for the same stale-duplicate-namespace pattern documented for `PermissionedObject`
(an extra/missing `.Domain.` segment) turning up here too — one copy `notImplemented: true`, the real
one `false`.

For each remaining `fullClassName`, look up `{fullClassName}`, `{fullClassName}@Get`,
`@Create`, `@Update`, `@Delete` in the `PermissionedObject` list (index it by `object` string first —
a dict/map lookup, not a linear scan per entity) and record each node's `access`/`permissions` if
present. **A missing node is not "already restricted" — it means open at the framework default**;
see api-reference.md's note under § "Set an object's required permission/access" for why (rows are
written on demand, never auto-synced by the framework).

### 3. Classify each entity, then fix

- **Already has an explicit, correct override** (from earlier work in the same design) → skip.
- **Has a hand-written AppService or Controller in the codebase** (grep for it) → "used". Read that
  class's own `[SheshaAuthorize]`/class-level permission requirement and apply the **same
  permission** to the entity's `Create`/`Update`/`Delete` `PermissionedObject` nodes (§ Global
  Specification Pattern's pitfall-9 note) — leave `Get` at Inherited (SKILL.md § Step 4f). If several
  entities share one AppService/base class (e.g. a family of `*ImportResult` entities all written by
  subclasses of one `ImportAppServiceBase`), they all get that same base class's permission — check
  the base class once, not each subclass's call sites individually.
- **No AppService/Controller anywhere** (confirmed by grepping the whole repo for the class name, not
  just its own folder) → "unused". Disable entirely per § Disabling CRUD Generation Entirely above,
  the same as any other confirmed-unused entity.
- **No exact permission concept exists for a lookup/reference entity** (e.g. a simple admin-managed
  dropdown table with no dedicated AppService of its own) → don't invent a new permission for it;
  reuse whichever existing "manage this category of config/reference data" permission is the closest
  fit (matching a sibling entity already gated the same way), and say explicitly in the design doc
  that this was a judgment call, not derived from an existing code gate, so it's easy to revisit.

### 4. Apply as a batch, then verify as a batch

Build one small JSON payload file per `PermissionedObject/Update` call (see § "Set an object's
required permission/access" in api-reference.md — no pre-existing `id` is needed for a node that
doesn't exist yet), loop over them with the same tool, and check every response's `success`. Re-fetch
`PermissionedObject.GetAll` once at the end and confirm the full set of intended changes actually
landed — don't trust the individual `success: true` responses alone as final confirmation; a
follow-up read is cheap and catches anything that silently didn't take (e.g. a typo'd `object` name
creating an orphan node instead of updating the intended one).

### 5. Document what you found, including corrections

If part of the sweep contradicts an earlier assumption in the project's design doc (e.g. "this
entity has no live endpoint" turns out to be wrong once you understand rows are on-demand, not
auto-synced), say so explicitly and correct the earlier text rather than leaving both the wrong and
right statements in the document — a design doc with two contradictory claims about the same entity
is worse than one that's openly been revised.

---

## Migration Pattern: Deleting Unused Permissions

Only applicable to a project that already uses **FluentMigrator** for its own schema/data changes
(check for a `Migrations/` folder under its Domain projects, and confirm the base class/attribute
shape shown below against one of that project's own recent migrations — don't assume this exact
shape carries over unmodified). Where it applies, a migration is usually the **better** choice than
repeating manual API calls per environment for a permission-catalog deletion: it runs automatically,
exactly once, wherever and whenever that environment's normal deployment pipeline applies pending
migrations — no separate script or manual UI pass needed per environment.

**Verify the actual DB behavior on the target project before writing this** — it was confirmed on
one project (see api-reference.md § "How `Permission/Delete` and role-permission removal actually
behave") that deleting a permission is a **soft delete** on `Frwk_ConfigurationItems` (joined
through `Frwk_PermissionDefinitions` — **never match by `Name` alone**, since a role can share a
permission's exact name), while removing it from a role's grants is a **hard delete** on
`Core_ShaRolePermissions`. Confirm both by inspecting the target project's own database the same
way (a live before/after check via its own Permission/Role APIs) before trusting this template.

```csharp
// {ModuleName}.Domain/Migrations/M{yyyyMMddHHmmss}.cs
using FluentMigrator;
using Shesha.FluentMigrator;

namespace {ModuleName}.Domain.Migrations
{
    /// <summary>
    /// Removes permissions that fell outside the {ModuleName} access-control design (see
    /// src/docs/design/access-control-design.md) and the role grants that referenced them, so
    /// every environment converges on the same permission catalog without a manual pass per
    /// environment.
    /// </summary>
    [Migration({yyyyMMddHHmmss})]
    public class M{yyyyMMddHHmmss} : OneWayMigration
    {
        private static readonly string[] PermissionsToDelete =
        {
            "{Permission-Name-1}",
            "{Permission-Name-2}",
            // ...
        };

        public override void Up()
        {
            foreach (var name in PermissionsToDelete)
            {
                var escaped = name.Replace("'", "''");

                // Role grants referencing this permission: hard-delete -- matches what removing
                // a permission from a role's grants actually does at the DB level (verified; see
                // api-reference.md). SET QUOTED_IDENTIFIER guards against the "SET options
                // incorrect" error some ConfigurationItemBase-derived tables raise without it
                // (seen when running the equivalent UPDATE by hand via sqlcmd -- confirm whether
                // the migration runner's own connection already sets this before assuming it's
                // needed here too, but including it is harmless if not).
                Execute.Sql($@"
SET QUOTED_IDENTIFIER ON;
DELETE FROM Core_ShaRolePermissions WHERE Permission = '{escaped}';
");

                // The permission definition itself: soft-delete, joined through
                // Frwk_PermissionDefinitions specifically -- Frwk_ConfigurationItems is shared
                // with ShaRole, and a role can have the exact same Name as a permission.
                Execute.Sql($@"
SET QUOTED_IDENTIFIER ON;
UPDATE ci
SET ci.IsDeleted = 1, ci.DeletionTime = GETDATE(), ci.DeleterUserId = NULL
FROM Frwk_ConfigurationItems ci
JOIN Frwk_PermissionDefinitions pd ON pd.Id = ci.Id
WHERE ci.Name = '{escaped}' AND ci.IsDeleted = 0;
");
            }
        }
    }
}
```

Notes:
- `DeleterUserId = NULL` — a migration isn't an interactive user action, so there's no real "who
  deleted this" to record; adjust if the target project's convention expects otherwise (e.g. a
  well-known system/service account id).
- This only removes the **permission definition** and **role grants**. It does not touch any
  `[SheshaAuthorize]`/`PermissionedObject` reference to that permission name left in code or
  runtime config — those become dead references (harmless: a permission nobody can ever hold just
  means that check always fails) but confirm nothing still depends on the permission actually
  existing before relying on removing it.
- Never write this migration speculatively. Every name in `PermissionsToDelete` should be there
  because a "detect → decide with the user → disable" pass (above) already confirmed it, the same
  as any other disabling action in this skill.

### Extending the pattern: renaming or merging permissions, not just deleting

A permission-catalog reconciliation (§1a-style: a brief's exact names vs. a live catalog that
already covers the same concepts under different/finer-grained names) is usually **rename and
merge**, not pure deletion — confirmed necessary and applied on a real project. The Permission API
has no in-place rename (`Name` doubles as the primary key, confirmed via the API: `id` and `name`
are always identical in every response), so a rename is: create the new name, re-point every role
holding the old name onto the new one, then soft-delete the old permission. A merge (N old
permissions → 1 new one) is the same, just re-pointing from multiple old names onto the one new
name. Add these two helper methods alongside `PermissionsToDelete`'s loop in `Up()`:

```csharp
/// <summary>
/// Re-points every role currently granted <paramref name="oldName"/> onto <paramref name="newName"/>:
/// insert-if-missing then hard-delete the old grant row (matches the confirmed DB behavior above --
/// a role's permission removal is a hard delete, not a soft one).
/// </summary>
private void RepointRoles(string oldName, string newName)
{
    var oldEscaped = oldName.Replace("'", "''");
    var newEscaped = newName.Replace("'", "''");

    Execute.Sql($@"
SET QUOTED_IDENTIFIER ON;
INSERT INTO Core_ShaRolePermissions (Id, CreationTime, IsDeleted, Permission, IsGranted, ShaRoleId)
SELECT NEWID(), GETDATE(), 0, '{newEscaped}', rp.IsGranted, rp.ShaRoleId
FROM Core_ShaRolePermissions rp
WHERE rp.Permission = '{oldEscaped}' AND rp.IsDeleted = 0
  AND NOT EXISTS (
      SELECT 1 FROM Core_ShaRolePermissions rp2
      WHERE rp2.ShaRoleId = rp.ShaRoleId AND rp2.Permission = '{newEscaped}' AND rp2.IsDeleted = 0
  );

DELETE FROM Core_ShaRolePermissions WHERE Permission = '{oldEscaped}';
");
}

/// <summary>
/// Creates a permission (in both Frwk_ConfigurationItems and Frwk_PermissionDefinitions -- a
/// Permission is split across the two tables) if it doesn't already exist, under the given module.
/// </summary>
private void CreatePermission(string moduleName, string name, string displayName, string description)
{
    var nameEscaped = name.Replace("'", "''");
    var displayEscaped = displayName.Replace("'", "''");
    var descEscaped = description.Replace("'", "''");

    Execute.Sql($@"
SET QUOTED_IDENTIFIER ON;
IF NOT EXISTS (SELECT 1 FROM Frwk_ConfigurationItems WHERE Name = '{nameEscaped}' AND IsDeleted = 0)
BEGIN
    DECLARE @id UNIQUEIDENTIFIER = NEWID();
    DECLARE @moduleId UNIQUEIDENTIFIER = (SELECT TOP 1 Id FROM Frwk_Modules WHERE Name = '{moduleName}');

    INSERT INTO Frwk_ConfigurationItems
        (Id, CreationTime, IsDeleted, ModuleId, Name, Label, Description, ItemType, VersionNo, VersionStatusLkp, IsLast, Suppress)
    VALUES
        (@id, GETDATE(), 0, @moduleId, '{nameEscaped}', '{displayEscaped}', '{descEscaped}', 'permission-definition', 1, 3, 1, 0);

    INSERT INTO Frwk_PermissionDefinitions (Id, Parent)
    VALUES (@id, NULL);
END
");
}
```

`Up()` order matters: **create every new/renamed-to name first** (so nothing is ever left pointing
at a name that doesn't exist yet), **then re-point roles**, **then** run the plain-deletion loop
above for both the genuinely-unused names and every old renamed-from/merged-from name. Confirmed
`Frwk_ConfigurationItems` columns for the `CreatePermission` insert (verify on the target project —
column sets do vary by Shesha version): `Id, CreationTime, CreatorUserId, LastModificationTime,
LastModifierUserId, IsDeleted, DeletionTime, DeleterUserId, TenantId, Description, Name, VersionNo,
VersionStatusLkp, BaseItemId, CreatedByImportId, ModuleId, ParentVersionId, ItemType, IsLast,
Label, OriginId, Suppress, ApplicationId` — only the non-nullable/relevant subset is set above.
`Frwk_PermissionDefinitions` itself is just `(Id, Parent)` — `Id` matches the `Frwk_ConfigurationItems`
row, `Parent` is the parent permission's name for a hierarchical permission (`NULL` otherwise).

---

## API Authorization Patterns

### Simple RBAC-Only Endpoint

```csharp
[AbpAuthorize("{Entity}-View")]
[HttpGet, Route("[action]")]
public async Task<{Entity}Dto> Get{Entity}(Guid id)
{
    var entity = await _repository.GetAsync(id);
    return ObjectMapper.Map<{Entity}Dto>(entity);
}
```

### Hybrid Authorization with Authorizer

```csharp
[HttpPost, Route("[action]")]
public async Task<{Entity}Dto> Update{Entity}(Update{Entity}Input input)
{
    var entity = await _repository.GetAsync(input.Id);

    if (!await _authorizer.CanUpdate{Entity}(entity))
        throw new AbpAuthorizationException(
            "User does not have permission to update this {entity}.");

    // Map input to entity and save...
    ObjectMapper.Map(input, entity);
    await _repository.UpdateAsync(entity);

    return ObjectMapper.Map<{Entity}Dto>(entity);
}
```

### Child Entity Mutation (Using Parent Permissions)

```csharp
[HttpPost, Route("[action]")]
public async Task<{ChildEntity}Dto> Update{ChildEntity}(Update{ChildEntity}Input input)
{
    // Specification ensures user can only access authorized child entities
    var childEntity = await _childRepo.GetAsync(input.Id);

    // Check PARENT entity permissions for mutation
    var parent = childEntity.{Parent};
    if (!await _parentAuthorizer.CanUpdate{Parent}(parent))
        throw new AbpAuthorizationException(
            "User does not have permission to update this {childEntity}.");

    // Business logic...
    ObjectMapper.Map(input, childEntity);
    await _childRepo.UpdateAsync(childEntity);

    return ObjectMapper.Map<{ChildEntity}Dto>(childEntity);
}
```

### Environment/Type-Sensitive Authorization

For entities where access depends on a type or classification attribute:

```csharp
public async Task<bool> CanDeployToEnvironment(ScEnvironment environment)
{
    // 1. RBAC: Global deployment permission
    if (await _currentUser.HasPermissionAsync("Deployment-Execute"))
        return true;

    // 2. Resource-Based: Project-scoped (all environment types)
    if (environment.Project != null &&
        _currentUser.IsPermissionScopedToEntity(
            "Deployment-Execute-where-Scoped-to-Project", environment.Project.Id))
        return true;

    // 3. Hybrid: Type-specific + project-scoped
    bool isProduction = environment.Type == RefListEnvironmentType.Production;

    if (environment.Project != null)
    {
        if (isProduction &&
            _currentUser.IsPermissionScopedToEntity(
                "Deployment-Execute-if-Production-where-Scoped-to-Project",
                environment.Project.Id))
            return true;

        if (!isProduction &&
            _currentUser.IsPermissionScopedToEntity(
                "Deployment-Execute-if-NonProduction-where-Scoped-to-Project",
                environment.Project.Id))
            return true;
    }

    return false;
}
```

---

## Permission Definition Pattern

### Permission Constants Class

File: `{ModuleName}.Application/AccessControl/{Module}Permissions.cs`

```csharp
// {ModuleName}.Application/AccessControl/{Module}Permissions.cs
public static class {Module}Permissions
{
    // Account permissions
    public const string AccountView = "Account-View";
    public const string AccountCreate = "Account-Create";
    public const string AccountUpdate = "Account-Update";
    public const string AccountDelete = "Account-Delete";
    public const string AccountViewWhereScoped = "Account-View-where-Scoped";
    public const string AccountViewWhereScopedToRegion = "Account-View-where-Scoped-to-Region";
    public const string AccountViewIfOwner = "Account-View-if-Owner";

    // WorkOrder permissions
    public const string WorkOrderView = "WorkOrder-View";
    public const string WorkOrderManage = "WorkOrder-Manage";
    public const string WorkOrderCompleteIfAssigned = "WorkOrder-Complete-if-Assigned";
}
```

### Role Constants Class

File: `{ModuleName}.Application/AccessControl/{Module}Roles.cs`

```csharp
// {ModuleName}.Application/AccessControl/{Module}Roles.cs
public static class {Module}Roles
{
    public const string Administrator = "Administrator";
    public const string RegionalManager = "Regional Manager";
    public const string AccountManager = "Account Manager";
    public const string User = "User";
}
```

---

## Billing/Sensitive Data Isolation Pattern

For domains with strict separation of concerns (e.g., billing vs technical):

File: `{ModuleName}.Application/AccessControl/Authorizers/BillingAuthorizer.cs`

```csharp
// {ModuleName}.Application/AccessControl/Authorizers/BillingAuthorizer.cs
public class BillingAuthorizer : IBillingAuthorizer
{
    private readonly ICurrentUser _currentUser;

    public async Task<bool> CanViewBilling(Guid accountId)
    {
        // Check ONLY billing-specific permissions — no technical permissions
        if (await _currentUser.HasPermissionAsync("Billing-View"))
            return true;

        if (_currentUser.IsPermissionScopedToEntity(
            "Billing-View-where-Scoped-to-Account", accountId))
            return true;

        return false;
    }

    public async Task<bool> CanManageBilling(Guid accountId)
    {
        // Billing Admin should NOT have any technical permissions
        if (await _currentUser.HasPermissionAsync("Billing-Manage"))
            return true;

        if (_currentUser.IsPermissionScopedToEntity(
            "Billing-Manage-where-Scoped-to-Account", accountId))
            return true;

        return false;
    }
}
```
