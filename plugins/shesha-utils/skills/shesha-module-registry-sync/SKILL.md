---
name: shesha-module-registry-sync
description: Scans a target project repository for its Shesha modules, looks up each module's full published version and dependency history on the private Boxfusion Azure Artifacts NuGet/npm feed, extracts its domain entities/APIs/settings/enums from its own C# source and auto-summarizes a description from them, and upserts everything into the Shesha.ModuleRegistry backend via the ModuleInfoSearch API (Pinecone-indexed on insert/update). Use when asked to register, sync, publish, or import a project's modules into the module registry.
---

# Shesha Module Registry Sync

Scan a repository for its Shesha modules and register/update them in the Module Registry, including their full NuGet/npm version and dependency history from the private Boxfusion Azure Artifacts feed, plus the domain entities, APIs and settings discovered in each module's own C# source code.

## Background

A "module" here means one conceptual Shesha module — typically a `{Name}.Domain` + `{Name}.Application` (+ optionally `{Name}.Web.Core`) csproj group, plus a matching npm package if the module ships a frontend package. **Not** one registry entry per csproj.

The Module Registry's `ModuleInfoSearchAppService` exposes:

| Method | Route | Purpose |
|--------|-------|---------|
| `POST` | `/api/services/ModuleRegistry/ModuleInfoSearch/Insert` | Create a module + its versions/dependencies, indexes it in Pinecone |
| `PUT`  | `/api/services/ModuleRegistry/ModuleInfoSearch/Update`  | Replace a module's fields + versions/dependencies, re-indexes in Pinecone |
| `GET`  | `/api/services/ModuleRegistry/ModuleInfoSearch/GetAll`  | Paginated list of registered modules (`?skipCount=&maxResultCount=`, 30/page by default), returns `{ totalCount, items }` — used to decide Insert vs Update |

Payload shape (`InsertModuleInfoInput` / `UpdateModuleInfoInput` also has `id`):

```json
{
  "moduleManifestName": "Shesha.Notifications",
  "description": "...",
  "limitations": "...",
  "nugetLocation": "https://dev.azure.com/boxfusion/_artifacts/feed/nuget.shesha.dev/NuGet/Shesha.Notifications/overview",
  "npmLocation": "https://dev.azure.com/boxfusion/_artifacts/feed/nuget.shesha.dev/Npm/@shesha-io/notifications/overview",
  "customComponents": "...",
  "skillName": "shesha-notifications",
  "skillLocation": "shesha-plugins/.../skills/shesha-notifications",
  "versions": [
    { "versionNumber": "1.2.0", "publishedDate": "2026-06-15T09:20:00Z", "dependencies": [ { "dependencyName": "Shesha.Core", "dependencyVersion": "0.45.1" } ] },
    { "versionNumber": "1.1.0", "publishedDate": "2026-04-02T14:05:00Z", "dependencies": [] }
  ],
  "entities": [
    { "entityName": "NotificationTemplate", "namespace": "Shesha.Notifications.Domain.NotificationTemplates", "baseClass": "FullAuditedEntity<Guid>", "properties": [ { "propertyName": "Subject", "propertyType": "string" } ] }
  ],
  "apis": [
    { "name": "NotificationTemplateCreate", "route": "/api/dynamic/Shesha.Notifications/NotificationTemplate/Crud/Create", "httpMethod": "POST", "category": "Crud" },
    { "name": "NotificationTemplateGet", "route": "/api/dynamic/Shesha.Notifications/NotificationTemplate/Crud/Get", "httpMethod": "GET", "category": "Crud" },
    { "name": "NotificationTemplateGetAll", "route": "/api/dynamic/Shesha.Notifications/NotificationTemplate/Crud/GetAll", "httpMethod": "GET", "category": "Crud" },
    { "name": "NotificationTemplateUpdate", "route": "/api/dynamic/Shesha.Notifications/NotificationTemplate/Crud/Update", "httpMethod": "PUT", "category": "Crud" },
    { "name": "NotificationTemplateDelete", "route": "/api/dynamic/Shesha.Notifications/NotificationTemplate/Crud/Delete", "httpMethod": "DELETE", "category": "Crud" },
    { "name": "Send", "route": "/api/services/Notifications/Notification/Send", "httpMethod": "POST", "category": "Custom" }
  ],
  "settings": [
    { "name": "DefaultChannel", "description": "The channel used when none is specified" }
  ],
  "enums": [
    { "enumName": "RefListNotificationChannel", "values": [ { "name": "Email", "value": 1 }, { "name": "Sms", "value": 2 } ] }
  ]
}
```

## Private feed

Packages are looked up on Boxfusion's private Azure Artifacts feeds, not the public nuget.org/npmjs.org registries. **NuGet and npm are two separate feeds in the same Azure DevOps org** — don't assume they share a feed name:

| Registry | Feed name | Default URL |
|----------|-----------|--------------|
| NuGet v3 service index | `nuget.shesha.dev` | `https://pkgs.dev.azure.com/boxfusion/_packaging/nuget.shesha.dev/nuget/v3/index.json` |
| npm registry | `npm.shesha.dev` | `https://pkgs.dev.azure.com/boxfusion/_packaging/npm.shesha.dev/npm/registry/` |

Both need a Personal Access Token (PAT) for the `boxfusion` Azure DevOps organization (Basic auth, empty username) — the same PAT works for both feeds as long as it has packaging-read scope org-wide. The script reads it from `-FeedPat` or the `SHESHA_FEED_PAT` environment variable — **prefer the environment variable** so the token never appears in shell history or gets typed into a chat. Never hardcode a PAT in the script or commit one anywhere.

The org name and feed name are parsed independently out of `-NugetFeedUrl` and `-NpmRegistryUrl` (`$azureOrg`/`$nugetAzureFeed`/`$npmAzureFeed` in the script) so the generated Azure DevOps package-overview links point at the correct feed for each ecosystem — never reuse one feed's name when building the other's link.

The script resolves the actual flat-container (package base address) URL dynamically from the NuGet v3 service index at `-NugetFeedUrl` rather than hardcoding it, since Azure Artifacts' internal resource URLs aren't a fixed shape — this is the standard NuGet v3 protocol discovery flow.

## Workflow

### Step 1: Gather required inputs from the user

**Never assume or hardcode any of these — always ask.** There are no defaults for the target environment, because silently defaulting to a local/dev backend or a stock admin login is exactly how you sync test data into the wrong environment:

- `RepoPath` — path to the repository to scan (use what the user gave, or ask if ambiguous)
- `BackendUrl` — base URL of the **specific** Shesha.ModuleRegistry backend to sync into (e.g. `http://localhost:21021`, or a staging/prod URL — ask which one, don't guess)
- `Username` / `Password` — admin credentials for that backend

If the user hasn't already supplied these in the conversation, ask for them explicitly before proceeding.

### Step 2: Copy the sync script into the target project

Write the script from [scripts/sync-module-registry.ps1](scripts/sync-module-registry.ps1) to:

```
{RepoPath}/.claude/skills/shesha-module-registry-sync/scripts/sync-module-registry.ps1
```

(skip this if that file already exists there and is up to date with the version in this skill).

### Step 3: Confirm before running

This script makes real network calls to the private Boxfusion Azure Artifacts feed and **writes real data** into the Module Registry (creating or updating records, which also re-indexes them in Pinecone) at whatever `BackendUrl` was given in Step 1 — mutating live data. Also confirm the user has a PAT available (via `SHESHA_FEED_PAT` or `-FeedPat`) — the script fails fast with a clear error if neither is set.

### Step 4: Run the script

```powershell
powershell -ExecutionPolicy Bypass -File "{RepoPath}/.claude/skills/shesha-module-registry-sync/scripts/sync-module-registry.ps1" `
  -RepoPath "{repoPath}" `
  -BackendUrl "{backendUrl from Step 1}" `
  -Username "{username from Step 1}" `
  -Password "{password from Step 1}"
```

`RepoPath`/`BackendUrl`/`Username`/`Password` are all **mandatory** — the script throws immediately if any is missing rather than falling back to a hardcoded environment. `NugetFeedUrl`/`NpmRegistryUrl` are optional and default to the `nuget.shesha.dev`/`npm.shesha.dev` feeds shown in [Private feed](#private-feed) above. `FeedPat` has no default; set `SHESHA_FEED_PAT` before running rather than passing `-FeedPat` on the command line.

The script will:
1. Recursively find `*.csproj` (excluding `bin`/`obj`) and group them into module names by stripping `.Domain`/`.Application`/`.Web.Core`/`.Web.Host`/`.Tests`-style suffixes, preferring each csproj's `<PackageId>`.
2. Recursively find `package.json` (excluding `node_modules`) and match each to a module by normalized name similarity; unmatched packages become their own npm-only module.
3. Recursively find `SKILL.md` files and match folder names to modules the same way, capturing `skillName`/`skillLocation` when found.
4. **Drop any candidate module that isn't actually Boxfusion/Shesha's** — a module only survives if its name starts with `shesha`/`boxfusion` (case-insensitive) or its npm scope is `@shesha-io/`. This matters because a repo can vendor a large third-party codebase alongside the real modules (e.g. `pd-chat` bundles Bot Framework Composer's own `@bfc/*`/`@botframework-composer/*` packages) — without this filter every vendored package would get registered too. Dropped candidates are logged, not silently discarded.
5. Resolve the feed's flat-container URL from the NuGet v3 service index, then for each surviving module query it for every published version, and fetch each version's `.nuspec` for its dependencies. **Within each version's dependency list, the same `shesha`/`boxfusion`/`@shesha-io/` name filter applies again** — public dependencies (`Abp`, `NHibernate`, `Microsoft.*`, etc.) are dropped, only Shesha/Boxfusion-owned dependencies are kept. Dropped counts are logged per module, not per dependency (too noisy otherwise). Each version's `publishedDate` is also resolved here, from the feed's `RegistrationsBaseUrl` resource (`catalogEntry.published` on that version's registration leaf) — a second, best-effort request per version; if the feed doesn't expose a registration resource, or a given lookup fails, `publishedDate` is left `null` rather than failing the sync.
6. Query the private npm registry doc for the matched package (one call returns every version + dependencies + a `time` map of version → publish timestamp), applying the same dependency filter and reading `publishedDate` straight out of that `time` map.
7. Merge NuGet + npm versions into one `versions` array per module (one entry per distinct version number; a version present in both ecosystems gets both dependency lists appended, and keeps NuGet's `publishedDate` over npm's if both resolved one). **The merged array is then sorted newest-first by `publishedDate`** (versions with no resolvable date sort last) — this is what "groups" the versions by date: same-day releases naturally end up adjacent, and the registry/UI don't need to re-sort them.
8. **Scan each surviving module's own source folders** (the directories containing its matched `.csproj` files - not the whole repo) for:
   - **Domain entities**: any `public class X : FullAuditedEntity<...>` (or `AuditedEntity`/`CreationAuditedEntity`/`Entity`) and its `public virtual {Type} {Name} { get; set; }` properties. Also captures `namespace` (the closest preceding `namespace X.Y { ... }` or file-scoped `namespace X.Y;` declaration in the same file) and `baseClass` (the matched base type plus its generic argument as written, e.g. `FullAuditedEntity<Guid>` or `Entity<int>`) — so the registry can show at a glance what each entity actually extends, not just that it's "an entity".
   - **APIs** are extracted into two categories, both stored in the same `apis` array with a `category` field so the registry (and its UI) can group them:
     - **`"Crud"`** — Shesha auto-generates a dynamic CRUD controller for every domain entity, so these aren't scanned for in source at all: for **every entity found in this same step**, 5 APIs are synthesized directly — `Create` (POST), `Get` (GET), `GetAll` (GET), `Update` (PUT), `Delete` (DELETE) — with route `/api/dynamic/{RouteModuleName}/{EntityName}/Crud/{Method}` and name `{EntityName}{Method}` (e.g. `NotificationTemplateCreate`). This guarantees every entity discovered shows a full CRUD API set, even if the entity has no hand-written controller at all.
     - **`"Custom"`** — any `*AppService` class's `[HttpGet]`/`[HttpPost]`/`[HttpPut]`/`[HttpDelete]`-attributed public methods, with the route reconstructed as `/api/services/{RouteModuleName}/{ServiceName}/{MethodName}`.
     - For `"Custom"` routes, `RouteModuleName` comes from the `moduleName: "X"` argument to `CreateControllersForAppServices(...)` found in the module's own `*Module.cs`/`*ApplicationModule.cs`, falling back to the module's own short name if not found.
     - For `"Crud"` routes, `RouteModuleName` instead comes from the module's own **Domain**-layer `*Module.cs` — specifically the name passed to `new SheshaModuleInfo("X")` on its `ModuleInfo` override, e.g. `public override SheshaModuleInfo ModuleInfo => new SheshaModuleInfo("boxfusion.chat");` yields `boxfusion.chat`. Only `*Module.cs` files found under a source folder whose name ends in `.Domain` are checked for this. If no such declaration is found, it falls back to the `"Custom"` route's `RouteModuleName`, then to the module's own short name.
   - **Settings**: any `interface IXSettings : ISettingAccessors` and its `[Setting(...)]`-decorated properties, using the `[Display(Name=..., Description=...)]` values when present.
   - **Enums**: any `public enum X { ... }` declaration (including Shesha's code-based `RefList*` reference-list convention, e.g. `[ReferenceList(...)] public enum RefListFoo : long { ... }`), capturing each member's name and its explicit numeric value if one is given (`null` otherwise). Member-level attributes like `[Description("...")]` and XML doc comments are stripped before parsing, so they don't interfere. An enum with an empty body (a purely data-driven reference list with no compile-time members) is still recorded, with an empty `values` array.

   This is regex/brace-matching heuristic extraction, not a full C# parser — it's tuned to how this codebase (and Shesha generally) actually writes these patterns, not arbitrary C#. Verified against this exact repo's own `ModuleInfo`/`ModuleInfoSearchAppService`/`IModuleRegistrySettings` (entities/APIs/settings) and against real `RefList*` enum files from `pd-chat` (enums, including a multi-value enum with `[Description]`/XML-doc-decorated members and an empty-body data-driven reference list).
9. **Always generate the module's `description` from what was just discovered in its own source** — domain entity names, a CRUD/custom API breakdown, setting names, and enum/reference-list names (e.g. *"Domain entities: NotificationTemplate. Exposes 5 CRUD endpoint(s) and custom endpoints (Send). Settings: DefaultChannel. Reference lists/enums: RefListNotificationChannel."*). This always overrides any description NuGet/npm might report for the package — the registry's summary tracks the code, not a possibly-stale package blurb — and is `null` only when the module has no entities/APIs/settings/enums at all.
10. Authenticate against the backend (`/api/TokenAuth/Authenticate`), list existing modules via `GetAll`, then `Update` (if a module with that manifest name already exists) or `Insert` (otherwise) for each discovered module.
11. Print a colored summary table: Created / Updated / Failed per module, with version/entity/API/setting/enum counts (API counts break down as `[N CRUD / M custom]`).

### Step 5: Present results

Report the summary table to the user, and flag any `Failed` rows with their error detail.

## Key Rules

- **No hardcoded target environment.** `BackendUrl`, `Username`, and `Password` are mandatory script parameters with no defaults — always ask the user which backend and which credentials, never assume a local-dev instance.
- **Module ≠ csproj.** Group by conceptual module first; never create separate registry entries for `.Domain` vs `.Application` of the same module.
- **Only Boxfusion/Shesha-owned packages get registered** — anything not matching the `shesha`/`boxfusion`/`@shesha-io/` naming filter is dropped and logged, never inserted. This applies at both the module level (whole packages) and the dependency level (a Shesha/Boxfusion module's public dependencies like `Abp`/`NHibernate`/`Microsoft.*` are recorded nowhere — only its Shesha/Boxfusion dependencies survive into `dependencies`).
- **A module not published anywhere is still registered** — with an empty `versions` array — rather than skipped, so it's discoverable even before its first release.
- **Entities/APIs/settings/enums are extracted per-module, not per-repo** — only the source folders belonging to that specific module's own `.csproj` files are scanned, so one module's entities never bleed into another's.
- **Every entity gets a full CRUD API set for free.** The 5 `Crud`-category APIs per entity are synthesized from the entity list itself, not scanned from source — so an entity with zero hand-written controller code still shows `Create`/`Get`/`GetAll`/`Update`/`Delete` in the registry. Only endpoints beyond that default set need a real `[Http*]`-attributed AppService method, and those are the ones tagged `Custom`.
- **Versions carry a `publishedDate` and are always sent newest-first.** The registry backend re-sorts by `publishedDate` on every read regardless of insertion order, so this is belt-and-suspenders, not the only place ordering is enforced — but the script still sorts before sending so the console summary and the payload itself read the same way. A version with no resolvable publish date (feed didn't expose one, or the lookup failed) still gets registered — with `publishedDate: null` — rather than being dropped.
- **Descriptions are always auto-generated from source, never taken from NuGet/npm.** Every insert/update writes a fresh documentation-style summary built from that module's own entities/APIs/settings/enums, so the registry always reflects the current code rather than a stale or missing package description.
- **Idempotent by design** — re-running against the same repo updates existing entries by exact (case-insensitive) `moduleManifestName` match rather than duplicating them. Since `GetAll` is paginated, the script pages through it (100 at a time) until a short page is returned, so this stays correct as the registry grows past one page.
- Transient NuGet/npm failures are retried once, then that specific version is skipped with a warning — the whole run never aborts because one version's lookup failed.
- Multi-targeted NuGet packages may list the same dependency more than once (once per target framework group) — the script doesn't de-duplicate across TFM groups; treat minor duplication in `dependencies` as a known limitation, not a bug.
- **Never hardcode the PAT.** Use `SHESHA_FEED_PAT`; the script throws immediately if no PAT is available from either source.
- Requires PowerShell 5+ (`Invoke-RestMethod` XML/JSON auto-parsing) and network access to `pkgs.dev.azure.com`.

Now run the sync based on: $ARGUMENTS
