---
name: shesha-access-control
description: Designs, documents, and implements access control for Shesha framework applications. Covers discovery of existing roles/permissions, access control design documentation, permission and role creation, API-level authorization, and data-level filtering via global specifications. Use when the user asks to design, implement, audit, review, or document access control, permissions, roles, authorization, security specifications, or data-level filtering in a Shesha project. Also use when implementing features from a PRD or specification that require new or modified roles, permissions, or authorization logic.
---

# Shesha Access Control Designer & Implementer

Design and implement comprehensive access control for Shesha-based enterprise applications using Shesha's hybrid authorization model (RBAC + Resource-Based + ABAC).

## When to Use This Skill

- **Auditing** existing roles, permissions, and authorization logic
- **Designing** access control models for new or existing applications
- **Documenting** access control requirements and design decisions
- **Implementing** roles, permissions, API authorization, and data-level filtering
- **Reviewing** authorization logic for security gaps or best practice violations
- **Disabling** unused, dead, or intentionally-unwanted API surface — either specific actions (via `PermissionedObject`) or CRUD generation entirely for an entity (via the `[Entity(GenerateApplicationService = ...)]` attribute, the `EntityConfig` API, or the admin UI's Configurations screen)
- **Removing unused permissions** from the catalog — via a FluentMigrator migration (if the project already uses one) so the change applies automatically across every environment, or via the Permission/Role APIs directly otherwise

## Key Rules

**Shesha Hybrid Model**: Shesha supports three authorization models that can be combined. Always choose the simplest model that meets the requirement. See [reference/access-control-guide.md](reference/access-control-guide.md) for full documentation.

**Permission Naming Conventions** — follow these strictly:
- RBAC: `{Entity}-{Action}` (e.g., `Account-View`, `User-Manage`)
- Resource-Based: `{Entity}-{Action}-where-Scoped[-to-{ScopeEntity}]` (e.g., `Account-View-where-Scoped-to-Region`)
- ABAC: `{Entity}-{Action}-if-{Condition}` (e.g., `Ticket-View-if-Assigned`)

**Authorization Check Order**: Always check permissions in order: RBAC (fastest) → Resource-Based → ABAC (slowest). Return early when permission is granted.

**Global Specifications are MANDATORY**: Every entity (parent AND child) that needs access control MUST have a `[GlobalSpecification]` class. This is the primary defense against information leakage.

**Child Entity Security**: Child entities should inherit parent permissions by default. Only create child-specific permissions when there is a clear, documented business justification (independent workflows, different security classifications, cross-cutting concerns).

**Module Association is MANDATORY**: Every permission and role created via the API MUST be associated with a module. Find the module GUID first (see [reference/api-reference.md](reference/api-reference.md) § Finding the Module ID), then include it in every Create/Update call. For permissions, use `"module": {"id": "guid"}` (EntityReferenceDto object). For roles, use `"module": "guid"` (plain string). Never use `moduleId` on permission writes — it is read-only and silently ignored.

**Avoid Permission Redundancy**: Do not create duplicate permissions (e.g., `System-View-All-Accounts` when `Account-View` exists). Consolidate granular permissions where they are always assigned together (e.g., combine Create/Update/Delete into `Manage`).

**DateTime Rule**: Always use `DateTime.Now` instead of `DateTime.UtcNow` per project conventions.

**File Placement**: All access control artifacts MUST be placed under an `AccessControl/` folder in the application layer module. This includes permission constants, role constants, authorizer interfaces/implementations, and permission-based global specifications (data-level access control). Only specifications that encode domain/business rules (not permission checks) belong in the Domain layer. See [reference/implementation-patterns.md](reference/implementation-patterns.md) § Folder Structure for the full layout.

**Verify the framework API shape before writing a single line of specification/authorizer code — do not trust this skill's code samples as-is.** The exact members of `ShaSpecification<T>`, `ICurrentUser`/`IShaPermissionChecker`, and whether `BuildExpression`/`BuildExpressionAsync` is sync or async, differ across Shesha versions and have been wrong in this skill's own examples before (an older pass assumed `ICurrentUser.HasPermissionAsync`/`GetPermissionScope`/`IsPermissionScopedToEntity` and an async `BuildExpressionAsync()` existed in a project that actually shipped `Shesha.Framework` 0.43.37, where none of that is true — the real, verified members were `ShaSpecification<T>.BuildExpression()` (synchronous) and `IShaPermissionChecker.IsGranted(userId, permissionName, entityRef)`). Before implementing:
1. Find the exact `Shesha.Framework`/`Shesha.Core`/`Shesha.Enterprise` package versions the project references (its `.csproj`/`Directory.Build.props`).
2. Confirm the real shape of `ShaSpecification<T>`, the permission-checker interface, and any current-person/current-position resolution helpers by reflecting against those exact package versions in the local NuGet cache (load the assembly, list the type's members) — don't guess from documentation or from a different Shesha version's behavior.
3. Only once verified, write code against the real API.

**Reflecting on a type's members (signatures) only tells you a method exists — it does not tell you what it actually does.** When the *behavior* of a framework method matters (not just its shape) — e.g. does `IsGranted` actually call out to a project's custom checker, in what order, under what condition — plain `System.Reflection` (`GetMethods()`, `GetProperties()`, etc.) cannot show you a method body. **Decompile it**: `dotnet tool install -g ilspycmd`, then `ilspycmd -t {Full.Type.Name} {path-to-dll}` prints real, readable C# for that type, including method bodies. This is how a real, load-bearing, project-wide bug was found on a real project (see api-reference.md's note on `ICustomPermissionChecker`) — reflection alone confirmed `IShaPermissionChecker`'s shape and its implementing class, but only decompiling that class's `IsGranted` method body revealed it calls out to every registered `ICustomPermissionChecker` when RBAC alone doesn't already grant the permission, which in turn led to finding that the project's own custom checker threw `NotImplementedException` instead of returning `false`. Don't stop at "the method exists with this signature" when the question is really "what does calling this method actually do".

**A minimal, reusable reflection-probe scaffold** (a throwaway console app, not part of the target project) is worth setting up once per session rather than guessing with `Assembly.LoadFrom` repeatedly: `new AssemblyLoadContext(...)`, with a `Resolving` handler that (a) indexes every package referenced by the real project via its `obj/project.assets.json` (`{package}/{version}/lib/{tfm}/*.dll`, preferring `net8.0` but falling back to whatever TFM folder exists — many core dependencies like `Abp` itself only ship `netstandard2.0`, and skipping that fallback silently drops huge swaths of types with no error), and (b) falls back to `AssemblyLoadContext.Default.LoadFromAssemblyName(name)` for shared-framework assemblies (ASP.NET Core, etc., which live under `dotnet/shared/`, not the NuGet cache). Wrap `GetTypes()` in try/catch for `ReflectionTypeLoadException` and use `ex.Types.Where(t => t != null)` — a single unresolvable dependency shouldn't blank out an entire assembly's type list. A resolver that's missing either half of this (no `netstandard2.0` fallback, or no shared-framework fallback) will silently and confusingly fail to find types that definitely exist, which looks identical to "this type doesn't exist" — confirm a negative result via the compiled target project's own output DLL (read its `TypeReferences` table with `System.Reflection.Metadata.PEReader`/`MetadataReader` to see exactly which assembly a referenced type resolves to) before concluding a type is genuinely absent.

**Reuse framework helpers — do not write a bespoke query/helper class speculatively, and do not re-derive this from scratch each run: the answer for "current person"/"current position"/"is granted" is already known.** Confirmed by reflecting against the actual referenced package versions (`Shesha.Enterprise.Domain`/`.Domain.Service` 5.1.7, `Shesha.Core`/`Shesha.Framework` 0.43.37) in a real project — if the target project references `Shesha.Enterprise.Domain.Service` (check its `.csproj`/`obj/project.assets.json`; a Shesha app with organisational/position structure almost always does), use these directly instead of writing a new helper:

- **Current Person**: **not** `Shesha.Enterprise.Session.EnterpriseSessionBase.PersonId` — that property looks like exactly the right thing (a plain sync `Guid?`) and was used that way in an earlier pass of this skill, but it's wrong and was confirmed live to always return `null` for a normal user on a normal request. Decompiling `EnterpriseSessionBase` (`ilspycmd`, see the reflection-probe note above) shows why: its base class, `Shesha.Session.ClaimsShaSession` (`Shesha.Application`), has its own `virtual Guid? PersonId` that correctly reads the logged-in user's Person from a JWT claim — but `EnterpriseSessionBase` **overrides** it with `EnterpriseOverrides?.PersonId`, an ambient-scope value that is only non-null *inside* an explicit `Use(...)`/`RunUsingPositionAppointmentAsync(...)` "act as this person/position" scope. An ordinary request never establishes that scope, so the property is `null` unconditionally for every normal user — virtual dispatch means casting the reference to `ClaimsShaSession` doesn't bypass this either; the runtime type's override always wins. **Use `EnterpriseSessionBase.GetLoggedInPersonAsync()` instead** (async only — no sync alternative): it checks the override scope first (so a genuine "act as" operation is still respected) and otherwise falls back to the same claims-based lookup. It throws `AbpException` rather than returning null when there's no logged-in user or no linked Person, so wrap it: `try { return (await session.GetLoggedInPersonAsync())?.Id; } catch (AbpException) { return null; }` — for a sync caller (e.g. `ShaSpecification.BuildExpression()`), block on it the same way as the position-appointment call below. **This exact bug (reading a property that looks obviously right but is an override-only value) silently made every owner/ABAC check in every specification on a real project always evaluate as "not the owner"** — invisible when testing as an admin account whose own session may resolve a Person a different way, or not need the owner path at all since RBAC already grants everything; it only surfaces once a real least-privilege test user's specs are actually exercised. Don't trust a property name/shape alone — verify behavior (decompile if needed) before relying on it in every specification a project has.
- **Current active Position** (via the person's current `PositionAppointment`): `Shesha.Enterprise.Domain.Session.IEnterpriseSession.GetCurrentPositionAppointmentAsync()` / `GetCurrentPositionAppointmentIdAsync()` (async only — no sync property exists for this one). `abpSession as IEnterpriseSession` gives you this interface from the same session object as above. For a *different* person's (not the current user's) active position — e.g. a supervisor-chain check about someone else — use `Shesha.Enterprise.Domain.Service.Positions.IPositionAppointmentsManager.GetActiveAppointmentAsync(Person)`/`GetActiveAppointmentOrNullAsync(Person)` (resolve via `IocManager`), or `.GetSupervisorPersonAsync(Person)`/`GetSupervisorPersonOrNullAsync(Person)` on the same manager if what you actually need is "this person's supervisor" rather than a raw position/appointment.
- **Permission check**: `Shesha.Authorization.IShaPermissionChecker.IsGranted(userId, permissionName, entityRef)` (sync) / `IsGrantedAsync(...)` — already covered above; `ICustomPermissionChecker`/`ShaCustomPermissionChecker` in `Shesha.Core` expose the identical `IsGranted`/`IsGrantedAsync(long, string[, EntityReferenceDto<string>])` shape if a project's DI graph resolves that interface instead.

**Check every project-specific `ICustomPermissionChecker` implementation for a `NotImplementedException` before trusting that any permission check actually works — testing as `admin` will never catch this.** `ShaPermissionChecker` (the real `IShaPermissionChecker`, confirmed by decompiling it on a real project) checks standard RBAC first and returns `true` immediately if that already grants the permission — it only falls through to `IocManager.ResolveAll<ICustomPermissionChecker>()` and asks every registered custom checker **when RBAC alone says no**. If a project registers its own `ICustomPermissionChecker` (grep for `ICustomPermissionChecker` in `*Module.cs` files) and that implementation throws `NotImplementedException` on any overload instead of returning `false` — confirmed as a real, live, project-wide bug on a real project (`HcmPermissionChecker`, three of its four `IsGranted`/`IsGrantedAsync` overloads unconditionally threw) — then **every permission check for a permission the current user doesn't already hold via RBAC crashes the request** instead of cleanly denying it. This is invisible during any testing done as an admin/superuser (they hold every permission directly via RBAC, so they always short-circuit before reaching the custom checker) and only surfaces for a real least-privilege test account — which is exactly why it's easy to ship a whole access-control design that looks correct and complete but is silently broken for every non-admin user. Before considering any `[GlobalSpecification]`/`[SheshaAuthorize]` work done:
1. Grep the project for `ICustomPermissionChecker` registrations (`Component.For<ICustomPermissionChecker>()...` or equivalent DI registration).
2. If one exists, read every method on the concrete class — any `throw new NotImplementedException()` on an `IsGranted`/`IsGrantedAsync` overload is a live bug; it should return `false` instead (a custom checker declining to grant something extra is not the same as an error).
3. Test at least one permission check as a **non-admin account holding some but not all of the relevant permissions** — this is the only way to actually exercise the RBAC-denies-then-falls-through-to-custom-checker path and catch this class of bug. A full test-scenario account (a real person/position/role setup, not just an API call as admin) is worth the setup cost specifically because of this.

Only if a target project's own reflection check (do this — package versions and DI wiring vary) shows it does **not** reference `Shesha.Enterprise.Domain.Service`, fall back to `Shesha.Core`'s `DomainService.GetCurrentPersonAsync()` extension (needs a `DomainService`-derived caller, or resolve one via `IocManager` and call it, blocking if the caller is sync) or an app-specific manager the codebase already has (e.g. `ChangeOfSupervisorWorkflowManager.GetLoggedInPositionAsync`) before writing anything new. A project-specific "AccessQueries"-style utility class, when still needed at all, should be a thin wrapper around framework calls like these — not a reimplementation of person/position/permission resolution via raw repository queries.

**Blocking on an async framework call from a required-synchronous override (e.g. `ShaSpecification.BuildExpression()`) is sometimes unavoidable and is safe under ASP.NET Core** (no captured `SynchronizationContext` in Kestrel's pipeline) — but the project's analyzers will very likely flag `.GetAwaiter().GetResult()`/`.Result` as an error (`VSTHRD002`) if `TreatWarningsAsErrors` is on (common in Shesha projects). Suppress narrowly with a comment explaining why no async path exists, rather than restructuring around it or disabling the analyzer project-wide:
```csharp
#pragma warning disable VSTHRD002 // Synchronously waiting on tasks or awaiters may cause deadlocks
var result = someAsyncFrameworkCall().GetAwaiter().GetResult();
#pragma warning restore VSTHRD002
```

## Reference Documentation

Detailed patterns, examples, and the full access control guide:

- [reference/access-control-guide.md](reference/access-control-guide.md) — Complete Shesha authorization model documentation (RBAC, Resource-Based, ABAC, child entity security, naming conventions, specifications)
- [reference/implementation-patterns.md](reference/implementation-patterns.md) — Code templates for authorizers, specifications, API authorization, and permission checks
- [reference/design-template.md](reference/design-template.md) — Template for access control design documents
- [reference/api-reference.md](reference/api-reference.md) — Shesha Permission, Role, Role Assignment, and PermissionedObject (per-action permission requirements) API endpoints, DTOs, and programmatic role management patterns

## Workflow

### Step 1: Discover Context

Determine what mode the user needs:
- **Audit**: Review existing roles, permissions, and authorization in the codebase
- **Design**: Create an access control design document for new or modified requirements
- **Implement**: Write code for roles, permissions, authorization checks, and specifications
- **Full cycle**: Design then implement (most common)

If the user provides a PRD, specification, or description, read it to understand requirements.

### Step 2: Analyze the Existing Codebase

Before designing or implementing, always understand what exists:

**2a. Find existing permissions and roles:**
- Search for `AbpAuthorize` attributes across the codebase
- Search for `HasPermissionAsync` and `IsPermissionScopedToEntity` calls
- Look for permission definition/seed classes
- Look for role definition/seed classes or configuration
- If the backend is running, query the Permission and Role APIs to discover what's registered at runtime. See [reference/api-reference.md](reference/api-reference.md) for endpoints (`GET /api/services/app/Permission/GetAll`, `GET /api/services/app/ShaRole/GetAll`)

**2b. Find existing authorization patterns:**
- Search for `[GlobalSpecification]` classes (data-level filtering)
- Search for authorizer classes (e.g., `IProjectAuthorizer`, `*Authorizer`)
- Search for `AbpAuthorizationException` throws
- Search for `ICurrentUser` usage

**2c. Identify the domain model:**
- List all domain entities and their relationships
- Identify parent-child entity hierarchies
- Map entity relationships (which entities reference which)

**2d. Present findings:**
Report a summary of:
- All discovered permissions (grouped by entity)
- All discovered roles
- All entities with/without global specifications
- Authorization gaps (entities without specifications, unsecured endpoints)

### Step 3: Design Access Control

If the user needs a design document or the task requires new permissions/roles:

**3a. Entity-Action Mapping**

For each protected entity, create a matrix:
```
Entity: {EntityName}
Actions: View, Create, Update, Delete, [domain-specific actions]
Current Authorization: [what exists]
Required Authorization: [what's needed]
Authorization Model: RBAC / Resource-Based / ABAC / Hybrid
```

**3b. Choose Authorization Model**

Apply the decision tree for each entity-action:
1. Does permission apply globally to ALL instances? → **RBAC**
2. Is access based on organizational structure or specific assignments? → **Resource-Based**
3. Is access based on dynamic relationships/conditions? → **ABAC**
4. Multiple approaches needed? → **Hybrid** (combine, check in order: RBAC → Resource-Based → ABAC)

**3c. Define Permissions**

Create a permission catalog following naming conventions. Read [reference/access-control-guide.md](reference/access-control-guide.md) § Permission Naming Convention Summary for the exact format.

**3d. Define Roles**

For each role, specify:
- Role name and display name
- Role type (Standard Role, Organization Specific, Account Specific, or custom)
- Assigned permissions list
- Description and purpose

**3e. Design Child Entity Security**

For each child entity, determine:
- Does it inherit parent permissions? (default — most cases)
- Does it need independent permissions? (justify why)
- What global specification does it need? (ALWAYS required)

**3f. Create Design Document**

Generate a design document at `src/docs/design/access-control-design.md` (or update the existing one) using the template in [reference/design-template.md](reference/design-template.md). Include:
- Permission catalog with types and descriptions
- Role catalog with assigned permissions
- Entity-action authorization matrix
- Role-permission matrix
- Justification for model choices

### Step 4: Implement Authorization

All access control artifacts go under `AccessControl/` in the application layer module. See [reference/implementation-patterns.md](reference/implementation-patterns.md) § Folder Structure for the full layout.

**Before writing any specification or authorizer**, do the framework-verification and reuse pass described in Key Rules above (verify `ShaSpecification`/permission-checker API shape against the actual referenced package version; search `Shesha.Core`/`Shesha.Enterprise`/the app's own Domain layer for existing current-person/current-position/permission-check helpers before writing new ones). Skipping this step is what produces a bespoke `AccessQueries`-style file that duplicates methods the framework or the app already provides.

```
{ModuleName}.Application/
  AccessControl/
    {Module}Permissions.cs          # Permission name constants
    {Module}Roles.cs                # Role name constants
    Authorizers/
      I{Entity}Authorizer.cs       # Authorizer interface
      {Entity}Authorizer.cs        # Authorizer implementation
    Specifications/
      {Entity}PermissionsSpecification.cs   # Data-level access control specification
```

**4a. Find the Module ID (prerequisite for API creation)**

Before creating any permissions or roles via the API, you MUST determine the correct module GUID. See [reference/api-reference.md](reference/api-reference.md) § Finding the Module ID for discovery approaches. Every permission and role must include the module in its Create/Update payload.

**4b. Create/Update Permission Definitions**

Create a `{Module}Permissions` static class with string constants under `AccessControl/`. Follow existing patterns in the codebase for seed data. Permissions can also be created at runtime via the Permission API (`POST /api/services/app/Permission/Create`) — always include `"module": {"id": "guid"}` in the payload. See [reference/api-reference.md](reference/api-reference.md) § Permission API and § Common Pitfalls.

**4c. Create/Update Role Definitions**

Create a `{Module}Roles` static class with string constants under `AccessControl/`. Define roles with their role types and permission assignments. Roles and their permission assignments can also be managed at runtime via the Role API (`POST /api/services/app/ShaRole/Create` with `"module": "guid"`, `PUT /api/services/app/ShaRole/Update` with `permissions` array). See [reference/api-reference.md](reference/api-reference.md) § Role API.

**4d. Implement Authorizer Classes**

For entities with complex authorization (hybrid models), create dedicated authorizer interfaces and implementations under `AccessControl/Authorizers/`. Read [reference/implementation-patterns.md](reference/implementation-patterns.md) § Authorizer Pattern for the template.

Key rules for authorizers:
- Create an `I{Entity}Authorizer` interface with methods for each action
- Implementation checks permissions in order: RBAC → Resource-Based → ABAC
- Return `bool` — callers throw `AbpAuthorizationException`
- Register in DI container

**4e. Secure API Endpoints**

For each application service endpoint:

*Simple RBAC-only endpoints:*
```csharp
[AbpAuthorize("{Entity}-{Action}")]
[HttpPost, Route("[action]")]
public async Task<EntityDto> GetEntity(Guid id) { ... }
```

*Complex hybrid authorization:*
```csharp
[HttpPost, Route("[action]")]
public async Task<EntityDto> UpdateEntity(UpdateEntityInput input)
{
    var entity = await _repo.GetAsync(input.Id);
    if (!await _authorizer.CanUpdateEntity(entity))
        throw new AbpAuthorizationException("User does not have permission to update this entity.");
    // Business logic...
}
```

**4f. Implement Global Specifications (Data-Level Filtering)**

Create a `[GlobalSpecification]` for EVERY entity requiring access control. Read [reference/implementation-patterns.md](reference/implementation-patterns.md) § Global Specification Pattern for the template.

Critical specification rules (concepts — see implementation-patterns.md for the verified-real method calls):
- Always check for "no logged-in person" first → return `entity => false`
- Check RBAC first → return `entity => true` for global permissions (performance)
- Collect all scoped entity IDs before building the expression
- Handle null navigation properties safely
- Build efficient expressions that minimize database queries

**Specifications can't express action-verb-specific rules** (e.g. "everyone in scope can read, but
nobody can delete"; "Administrators get crud, but the create/update/delete-only actions need a
manage permission the entity has no bespoke AppService to attach `[SheshaAuthorize]` to") — a
`[GlobalSpecification]` filters *which rows* a query can see/target, not *which action* is being
performed. For that, use the PermissionedObject API (`PUT /api/services/app/PermissionedObject/Update`
— see [reference/api-reference.md](reference/api-reference.md) § PermissionedObject API) to set the
required permission or `access` (including `Disable`, to block an action entirely) on the specific
`@Create`/`@Update`/`@Delete` action node for that entity.

**If a specification needs to correlate against a different entity type (no direct FK, e.g. a
reporting view carrying a source record's Id as a plain column), never capture a second repository's
live `IQueryable` inside the returned expression** (e.g. `otherRepo.GetAll()` referenced via
`.Any(...)` in a closure) — NHibernate generally can't fold two independently-created queryables into
one correlated SQL subquery and either fails to translate or loads the whole second table on every
query. Run one small, already-correlated query up front instead (`.Where(...).Select(id).ToList()`)
and use `Contains` against that materialized list in the returned expression. Confirmed as a real,
flagged performance problem on a live project — see
[reference/implementation-patterns.md](reference/implementation-patterns.md) § "Correlating against a
different entity type" for the full before/after.

**Check for a parallel, unguarded dynamic-CRUD surface whenever an entity also has a hand-written
AppService.** A custom AppService's `[SheshaAuthorize]`/authorizer logic only protects its own
routes — if `EntityConfig.generateAppService` is still `true` for that entity, Shesha *also*
generates a generic `Create`/`Update`/`Delete`/`Get` on the raw entity type, and that second surface
has its own, independent `PermissionedObject` permission requirement (defaulting to wide open if
never set). Confirmed live on a real project — see
[reference/api-reference.md](reference/api-reference.md) § Common Pitfalls #9. Don't assume a
properly-authorized AppService is the only way into an entity; check the entity's own
`{FullName}@Create` etc. nodes too.

**Leave `Get`/`GetAll` `PermissionedObject` nodes at `access: 2` (Inherited) — don't gate reads with
a permission the way you gate mutations.** These are two different mechanisms answering two
different questions, and confusing them breaks self-service access: `PermissionedObject` on an
action answers "can this be attempted at all" (checked before anything runs), while a
`[GlobalSpecification]` answers "which rows does this caller get back" (a filter, not a gate).
`Create`/`Update`/`Delete` need an explicit `PermissionedObject` permission because a specification
can't protect them — there's no existing row to filter for `Create`, and specs aren't
action-aware. `Get`/`GetAll` already have their real protection in the specification (RBAC tier OR
owner-match, per whatever that entity's spec implements) — setting `@Get` to
`RequiresPermissions: ["X-Manage"]` on top of that would reject a plain owner (who holds `X-User`,
not `X-Manage`) before the specification ever gets to say "let them see their own row," breaking
self-service reads entirely. A real, confirmed-live example of getting this wrong: a `@Get` node set
to `RequiresPermissions` with an **empty** permission list, which rejects everyone including admins,
since nothing satisfies an empty requirement — always double check `permissions` is non-empty on any
node you set to `access: 4`, and default new `Get`/`GetAll` nodes to Inherited unless a genuine
"nobody may even attempt to read this" requirement exists.

**4g. Implement Child Entity Specifications**

For child entities, specifications navigate the parent relationship:
```csharp
// Child inherits parent permissions
return childEntity =>
    childEntity.Parent != null && scopedParentIds.Contains(childEntity.Parent.Id);
```

**4h. Disable CRUD Generation Entirely (when the requirement is "no API at all", not "restrict who can call it")**

Different from 4e/4f above — those restrict access to an endpoint that still exists; this removes
the endpoint. Read [reference/implementation-patterns.md](reference/implementation-patterns.md) §
Disabling CRUD Generation Entirely and § Finding and Disabling Unused APIs before doing this:
- For an entity defined in the project's own source: `[Entity(GenerateApplicationService = GenerateApplicationServiceState.DisableGenerateApplicationService)]` on the class.
- For an entity from a referenced package (no class to attach the attribute to): the frontend admin
  UI's **Configurations → Entity Configuration** screen (preferred), or the `EntityConfig` API
  directly — but read api-reference.md § Common Pitfalls #8 first, it has a confirmed data-corrupting
  bug on write.
- If the goal is "find and disable whatever's unused across the project" rather than a specific
  named entity: this is a detect → decide-with-the-user → disable → verify workflow, not a single
  step — see implementation-patterns.md § Finding and Disabling Unused APIs for how each phase
  works and which existing skill (`auditing-application-security`, if present) handles detection.
- To remove **permissions** confirmed unused (not entities/actions): if the project uses
  FluentMigrator (check for a `Migrations/` folder in its Domain projects), prefer writing a
  migration — see implementation-patterns.md § Migration Pattern: Deleting Unused Permissions —
  since it applies automatically on every environment's next deploy instead of needing a manual
  pass per environment. **Verify the confirmed DB behavior in that section against the target
  project first** (soft-delete vs. hard-delete semantics differ between the permission definition
  and its role grants, and were only confirmed on one project's version).

**4i. Module-Wide CRUD/Permission Sweep** (when asked to "go through every entity/API under
Entity Configuration" for a module, not just a specific named entity)

This is a distinct, larger task from 4f/4h above — instead of fixing one entity you already know
about, you're finding every entity in a module that needs fixing. Don't do this one entity at a time
by hand; script it. See [reference/implementation-patterns.md](reference/implementation-patterns.md)
§ Module-Wide Entity Sweep for the full worked method (query shape, classification logic, the
`notImplemented` filter, batching the fixes). In short:
1. Pull `EntityConfig.GetAll` and `PermissionedObject.GetAll` in full (both are large — page or dump
   to a file, don't read the raw response inline) and cross-reference them client-side (a short
   Python/Node script, not by re-querying per entity) into one table per entity: module, class,
   `generateAppService`, `notImplemented`, and the current `access`/`permissions` on its
   `Create`/`Update`/`Delete`/`Get` `PermissionedObject` nodes.
2. Drop every `notImplemented: true` row — dead metadata for a class that no longer resolves, not a
   live entity (see api-reference.md § EntityConfig API).
3. For everything left, classify by finding what actually consumes it: a hand-written
   AppService/Controller in the codebase → it's "used", so match the same permission that
   AppService's own `[SheshaAuthorize]` already requires (apply to the entity's raw dynamic
   `Create`/`Update`/`Delete` per 4f above — leave `Get` alone). No AppService/Controller anywhere,
   confirmed by grepping the whole repo for the class name → it's unused, disable it entirely (4h).
4. A `PermissionedObject` node **absent** for an entity does not mean it's already locked down — see
   api-reference.md's note under § "Set an object's required permission/access": rows are written on
   demand, never auto-synced, so absence means open-by-default. Don't skip an entity just because it
   has no existing override to look at.
5. Re-fetch `PermissionedObject.GetAll` after applying fixes and confirm every intended change
   actually landed, the same way you'd verify any other batch of live API writes.

### Step 5: Validate and Document

**5a. Review checklist:**
- [ ] All entity-action combinations analyzed
- [ ] Appropriate authorization model chosen for each case
- [ ] Permission naming follows conventions
- [ ] No redundant permissions
- [ ] RBAC checked first in all authorization logic
- [ ] Global specifications return `entity => true` for global permissions
- [ ] All null references handled safely
- [ ] `AbpAuthorizationException` thrown with descriptive messages
- [ ] ALL entities (parent and child) have global specifications
- [ ] Child entities inherit parent permissions by default
- [ ] Complex authorization extracted into authorizer classes
- [ ] Any entity/endpoint disabled entirely (not just access-restricted) was confirmed unused with the user first, and verified afterward that the disabling change (EntityConfig/PermissionedObject) didn't corrupt an unrelated field (see api-reference.md § Common Pitfalls #3, #8)
- [ ] `Get`/`GetAll` `PermissionedObject` nodes were left at Inherited (or otherwise verified to have a non-empty `permissions` list if deliberately restricted) — not accidentally gated to a permission the row-level specification's owner-tier callers won't hold
- [ ] After a module-wide sweep (4i), every entity's fix was re-verified against a fresh `PermissionedObject.GetAll`, not assumed from the request payload alone

**5b. Identify test scenarios:**
For each permission, outline test cases:
- User WITH permission → expected access granted
- User WITHOUT permission → expected access denied
- Edge cases (null references, multiple roles, scoped assignments)
- Information leakage scenarios for child entities

**5c. Report implementation summary:**
Present a clear summary of all changes made, new files created, and any remaining items.
