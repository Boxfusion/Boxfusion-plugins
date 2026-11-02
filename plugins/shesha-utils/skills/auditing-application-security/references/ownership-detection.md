# Ownership Detection — App-Owned vs Package-Imported

## Contents
- Why ownership matters
- Step 1: Detect application backend projects
- Step 2: Detect application Shesha modules
- Step 3: Detect application URL module segments
- Step 4: Classify an endpoint
- Step 5: Classify an entity
- Step 6: Classify a form
- Step 7: Classify a permission and a reference list
- Worked example
- Edge cases and failure modes

## Why ownership matters

A Shesha application consumes the framework and other Shesha modules as compiled NuGet and npm
packages. Its running API surface is therefore a union of:

- endpoints declared in this repository's own source (`backend/src/`), and
- endpoints contributed by packages — `Shesha.Framework`, `Shesha.Application`,
  `Shesha.Web.FormsDesigner`, `Shesha.Scheduler`, `Shesha.Enterprise.*`, `Boxfusion.SAGov.*`,
  `Boxfusion.Persal`, `Shesha.Workflow`, and so on.

The two need different remediation, so every catalog row and every audit finding carries an
`Owner` column:

| Owner | Meaning | How it gets fixed |
|-------|---------|-------------------|
| `app` | Declared in this repository's source | Edit the code in this repo, or configure the DB record |
| `package` | Contributed by a compiled Shesha package | Upgrade the package, or configure the DB record — the source is not editable here |

`package` never means "not your problem". A package endpoint left anonymous is live attack surface
for this application. It simply cannot be fixed by editing this repository.

## Step 1: Detect application backend projects

Parse the solution for project paths, then read each `.csproj`:

```bash
find backend/src -name "*.csproj" -not -path "*/obj/*" -not -path "*/bin/*"
```

For each project record:
- **Assembly name** — the `AssemblyName` element, defaulting to the `.csproj` file name stem.
- **Root namespace** — the `RootNamespace` element, defaulting to the assembly name.

Collect these into `appAssemblies` and `appNamespaces`. Any type whose full name starts with one
of `appNamespaces` is application code.

Record the package versions too — the audit needs them:

```bash
cat backend/Directory.Build.props
grep -rh "PackageReference" backend/src --include=*.csproj | sort -u
```

## Step 2: Detect application Shesha modules

A Shesha module is declared by a `SheshaModule` subclass exposing `SheshaModuleInfo`. The module
name is the configuration-item namespace that owns forms, reference lists, settings and permissions.

```bash
grep -rn "SheshaModuleInfo(" backend/src --include=*.cs | grep -v "/obj/"
```

Two forms occur — a string literal, and a constant:

```csharp
public override SheshaModuleInfo ModuleInfo => new SheshaModuleInfo("Shesha.Hcm") { };
public override SheshaModuleInfo ModuleInfo => new SheshaModuleInfo(Name) { };
```

The second passes a constant. Resolve it by reading the same class for its declaration:

```bash
grep -rn "const string Name" backend/src --include=*.cs | grep -v "/obj/"
```

Collect the resolved strings into `appModules`. Every other module name observed live — `Shesha`,
`Shesha.Enterprise`, `Boxfusion.SAGov`, `Shesha.Workflow`, and any module returned by
`Module/GetAll` that is not in `appModules` — is a package module.

## Step 3: Detect application URL module segments

ABP builds app-service routes as `/api/services/{moduleName}/{Service}/{Action}`. The segment comes
from the module's `PostInitialize`:

```bash
grep -rn "moduleName:" backend/src --include=*.cs | grep -v "/obj/"
```

```csharp
Configuration.Modules.AbpAspNetCore().CreateControllersForAppServices(
    typeof(HcmModule).Assembly, moduleName: "HcmCommon", useConventionalHttpVerbs: true);
```

Collect into `appUrlSegments`. These are **not** the same strings as `appModules` — a single
repository routinely has a Shesha module named `Shesha.Hcm` and a URL segment named `HcmCommon`.
Keep the two sets separate; conflating them misclassifies both endpoints and forms.

Dynamic entity CRUD routes use a different segment source: `/api/dynamic/{module}/{Entity}/Crud/...`
where the module is resolved from the entity's assembly module, falling back to `app`. Classify
those by entity namespace (Step 5), not by URL segment.

## Step 4: Classify an endpoint

Apply in order; first match wins:

1. The declaring class is found in this repository's source — classify as `app`.
   ```bash
   grep -rl "class MyService" backend/src --include=*.cs | grep -v "/obj/"
   ```
2. The endpoint's full type name starts with an `appNamespaces` prefix — `app`.
3. The URL is `/api/services/{seg}/...` and the segment is in `appUrlSegments` — `app`.
4. The URL is `/api/dynamic/{module}/{Entity}/Crud/...` — classify by the entity (Step 5).
5. Otherwise — `package`. Record which package, from the type's root namespace:
   a `Shesha.` prefix means framework, `Boxfusion.SAGov.` means SaGov, `Shesha.Enterprise.` means
   Enterprise.

Rule 1 beats rule 3 deliberately: an application can register its services under a segment that
looks framework-ish, and the source is the stronger signal.

## Step 5: Classify an entity

An entity is `app` when either holds:

- its `fullClassName` starts with a prefix in `appNamespaces`, or
- a source file declaring it exists under `backend/src/`.

Otherwise `package`. Entity ownership also determines the owner of that entity's dynamic CRUD
endpoints and of any `Shesha.Entity` or `Shesha.Entity.Action` permission records.

## Step 6: Classify a form

Forms live in the database, not the file system, so ownership comes from the form's **module**:

- form module in `appModules` — `app`
- otherwise — `package`

This correctly attributes forms that this repository ships through its own configuration packages.
Application form configuration is normally delivered as `.shaconfig` archives committed under
`ConfigMigrations/`:

```bash
find backend/src -name "*.shaconfig"
```

Those forms are imported at deploy time but are still **app-owned** — the repository is their
source of truth and they are editable here. A form is only `package` when its module belongs to a
compiled package.

A `.shaconfig` is a zip archive. To enumerate the forms one delivers without a running backend,
list its entries; the `shesha-utils:document-shaconfigs` skill does this and writes a CSV inventory.

## Step 7: Classify a permission and a reference list

Both are configuration items with a module, so use the same rule as forms: module in `appModules`
means `app`, otherwise `package`.

Permissions matter for the audit's remediation advice. A finding that says "grant this endpoint
`app:Configurator`" is only actionable if that permission exists; `app:Configurator` and
`pages:maintenance` are framework permissions and are always present.

## Worked example

Detected for the pd-Hcm repository. Treat this as an illustration of the shape of the output, not
as values to hard-code — re-derive them on every run.

```
appAssemblies   Shesha.Hcm.Domain, Shesha.Hcm.Application, Shesha.Leave.Domain,
                Shesha.Leave.Application, SaGov.Leave.Domain, SaGov.Leave.Application,
                Shesha.Pmds.Domain, Shesha.Pmds.Application, SaGov.Pmds.Domain,
                SaGov.Pmds.Application, Shesha.Qms.Domain, Shesha.Qms.Application,
                Shesha.Hcm.Web.Core, Shesha.Hcm.Web.Host

appModules      Shesha.Hcm, Shesha.Leave, Shesha.Pmds, Shesha.Qms,
                SaGov.Leave, SaGov.Pmds        (last two resolved from Name constants)

appUrlSegments  HcmCommon, Hcm, Leave, Pmds, Qms, SaGovLeave, SaGovPmds

packages        Shesha.Framework / Shesha.Application / Shesha.Web.FormsDesigner /
                Shesha.Scheduler / Shesha.NHibernate / Shesha.Import /
                Shesha.Sms.Clickatell            at SheshaVersion
                Shesha.Enterprise.* / Shesha.Workflow   at EnterpriseVersion
                Boxfusion.SAGov.* / Boxfusion.Persal    at SaGovVersion
```

So `/api/services/Leave/LeaveRequest/GetAll` is `app`;
`/api/services/app/Settings/GetValue` is `package` (framework);
`/api/dynamic/Shesha.Leave/LeaveRequest/Crud/GetAll` is `app` via its entity namespace.

## Edge cases and failure modes

**A package type subclassed in app source.** If this repository declares a service deriving from a
package service, the subclass is `app` and its inherited endpoints are exposed under the app's URL
segment. Classify by the declaring type of the concrete registered service, which is the app type.
Inherited methods are app-owned surface.

**An app entity with a package base class.** Ownership follows the concrete entity's namespace, not
the base. An entity deriving from `FullAuditedEntity` is app-owned.

**Manually-coded services overriding dynamic CRUD.** When the app declares an
`IEntityAppService` implementation for an entity, Shesha registers that service instead of
generating a dynamic CRUD controller. The endpoints are then `app` and authorized at service level
against `Shesha.WebApi.Action`, not entity level. Check for this before assuming an entity's CRUD
is generated.

**Same short class name in app and package.** A `grep -rl` on a class name can match both. Always
confirm the namespace, not just the class name, before classifying as `app`.

**Ownership is unresolvable.** Record `Owner = unknown` and list the row in the catalog's unresolved
section. Never silently default to `package` — an unclassified app endpoint is exactly the thing an
audit must not lose.
