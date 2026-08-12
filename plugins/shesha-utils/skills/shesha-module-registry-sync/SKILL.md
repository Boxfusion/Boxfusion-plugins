---
name: shesha-module-registry-sync
description: Scans a target project repository for its Shesha modules, looks up each module's full published version and dependency history on the private Boxfusion Azure Artifacts NuGet/npm feed (or the public nuget.org/npmjs.org registries, plus a specific git ref for source extraction, when the repo is specifically shesha-io/shesha-framework), extracts its domain entities/APIs/settings/enums from its own C# source, has a real "what does this module do and what's it for" description authored per module by reading the actual code (falling back to a mechanical name listing only if skipped), and upserts everything into the Shesha.ModuleRegistry backend via the ModuleInfoSearch API (Pinecone-indexed on insert/update). Use when asked to register, sync, publish, or import a project's modules into the module registry.
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
  "description": "Manages templated multi-channel notifications (email, SMS, push) with per-channel default settings, letting other modules trigger a notification by template rather than composing message content themselves.",
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

## Special case: shesha-io/shesha-framework

This one specific repo — **https://github.com/shesha-io/shesha-framework** — is handled differently, automatically, and *only* this repo. The script detects it itself (`git config --get remote.origin.url` on `-RepoPath`, matched against `shesha-io/shesha-framework`); nothing needs to be passed to opt in, and every other repo is completely unaffected by anything in this section.

When detected:
- **Public registries, not the private Boxfusion feed.** `-NugetFeedUrl`/`-NpmRegistryUrl` are silently switched to `https://api.nuget.org/v3/index.json` and `https://registry.npmjs.org/` (unless the caller explicitly passed different values) — shesha-framework's own packages are published publicly, not to the Boxfusion Azure Artifacts feed. No PAT is required or sent for this repo.
- **`-SourceRef` becomes mandatory.** Entities/APIs/settings/enums are extracted from a specific git ref (branch or tag) rather than whatever happens to be checked out in the working tree — the script reads file trees and content straight from git (`git ls-tree`/`git show`) and never touches the working copy. **Ask the user which release to sync** — typically `releases/0.44` or `releases/0.45` — and pass it as `-SourceRef "releases/0.44"` (or `"releases/0.45"`); don't guess or default silently. If the ref hasn't been fetched locally, `git fetch origin <ref>` first.
- Package overview links (`nugetLocation`/`npmLocation`) point at `nuget.org`/`npmjs.com` package pages instead of an Azure DevOps feed overview.
- Everything else — module discovery/grouping, entity/API/setting/enum extraction rules, the `-ExportOnly`/`-DescriptionsFile` description workflow (Step 4 below) — works exactly the same, just sourced from the chosen git ref instead of disk.
- **Dependency extraction handles nuget.org's `.nuspec` responses differently under the hood, but the output is identical.** nuget.org serves `.nuspec` with `Content-Type: text/xml`, which makes `Invoke-RestMethod` auto-parse it into an `XmlDocument` instead of a raw string — the script detects that case and reads the `XmlDocument` directly rather than running it through the private feed's raw-string BOM-stripping path (which would silently turn it into the literal text `"System.Xml.XmlDocument"`, fail to parse, and produce zero dependencies for every version). If a future feed's dependency counts all come back empty, check this first.

```powershell
powershell -ExecutionPolicy Bypass -File "{RepoPath}/.claude/skills/shesha-module-registry-sync/scripts/sync-module-registry.ps1" `
  -RepoPath "{path to a local clone of shesha-io/shesha-framework}" `
  -SourceRef "releases/0.44" `
  -ExportOnly `
  -ExportPath "{scratchpad}/module-scan.json"
```

## Workflow

### Step 1: Gather required inputs from the user

- `RepoPath` — path to the repository to scan (use what the user gave, or ask if ambiguous).
- `Username` / `Password` — admin credentials for the backend. **Always ask** — these have no default and the script throws immediately if either is missing (for any run except `-ExportOnly`, which needs neither).
- `BackendUrl` — defaults to the `shesha-moduleregisty-api-test` environment (`https://shesha-moduleregisty-api-test.shesha.app/`) baked into the script. Only ask if the user wants a different target; if they do, pass `-BackendUrl` explicitly to override.

If the user hasn't already supplied `Username`/`Password` in the conversation, ask for them explicitly before proceeding.

If `RepoPath` turns out to be a clone of `shesha-io/shesha-framework` (see [Special case](#special-case-shesha-ioshesha-framework) above), also ask **which release branch** to sync — `releases/0.44` or `releases/0.45` — before running anything; this becomes `-SourceRef`.

### Step 2: Copy the sync script into the target project

Write the script from [scripts/sync-module-registry.ps1](scripts/sync-module-registry.ps1) to:

```
{RepoPath}/.claude/skills/shesha-module-registry-sync/scripts/sync-module-registry.ps1
```

(skip this if that file already exists there and is up to date with the version in this skill).

### Step 3: Confirm before running

This script makes real network calls to the private Boxfusion Azure Artifacts feed and **writes real data** into the Module Registry (creating or updating records, which also re-indexes them in Pinecone) — by default into `shesha-moduleregisty-api-test`, or whatever `BackendUrl` was overridden to in Step 1 — mutating live data, one module at a time as each finishes (see Step 4's numbered list, step 11). Also confirm the user has a PAT available (via `SHESHA_FEED_PAT` or `-FeedPat`) — the script fails fast with a clear error if neither is set.

### Step 4: Scan first, then author real descriptions, then sync

A regex scan can enumerate a module's entity/API/setting/enum *names*, but it has no idea what the module is actually *for* — that takes reading the code. So this runs in three passes instead of one:

**4a. Export-only scan** — no backend/NuGet/npm calls, just the source scan:

```powershell
powershell -ExecutionPolicy Bypass -File "{RepoPath}/.claude/skills/shesha-module-registry-sync/scripts/sync-module-registry.ps1" `
  -RepoPath "{repoPath}" `
  -ExportOnly `
  -ExportPath "{scratchpad}/module-scan.json"
```

Add `-SourceRef "releases/0.44"` (or whichever branch was chosen in Step 1) if `RepoPath` is `shesha-io/shesha-framework` — see [Special case](#special-case-shesha-ioshesha-framework); every other repo omits it.

This writes one entry per discovered module — `moduleManifestName`, `sourceFolders`, `entities`, `apis`, `settings`, `enums` — to `module-scan.json` and exits without touching the registry.

**4b. Author a real description per module** — read `module-scan.json`, then, for each module, actually open its source (starting from `sourceFolders`: the module's `*Module.cs`, its main entity/AppService files, any XML doc comments or README) and write a genuine 2–4 sentence description of **what the module does and what it's for** — its purpose and role in the system — not a restated list of entity/API names. Bad: *"Provides domain entities: NotificationTemplate. Exposes 5 CRUD endpoints and custom endpoint Send."* Good: *"Manages templated multi-channel notifications (email, SMS, push) with per-channel default settings, letting other modules trigger a notification by template rather than composing message content themselves."* Save the results as `{ "moduleManifestName": "description text", ... }` to `descriptions.json`.

**4c. Run the real sync**, passing that file so the authored descriptions are used verbatim instead of the mechanical fallback:

```powershell
powershell -ExecutionPolicy Bypass -File "{RepoPath}/.claude/skills/shesha-module-registry-sync/scripts/sync-module-registry.ps1" `
  -RepoPath "{repoPath}" `
  -Username "{username from Step 1}" `
  -Password "{password from Step 1}" `
  -DescriptionsFile "{scratchpad}/descriptions.json"
```

Add `-BackendUrl` only if targeting somewhere other than the default `shesha-moduleregisty-api-test` environment (see Step 1). Again, add `-SourceRef "releases/0.44"` (same value used in 4a) when syncing `shesha-io/shesha-framework` — the script requires it for that repo and throws immediately if it's missing.

`RepoPath` is always mandatory. `Username`/`Password` are always mandatory for this real-sync run too — no defaults, the script throws immediately if either is missing — but neither is required for the `-ExportOnly` pass in 4a. `BackendUrl` defaults to `shesha-moduleregisty-api-test`. A PAT (`SHESHA_FEED_PAT` or `-FeedPat`) is mandatory as well, **except** for `shesha-io/shesha-framework`, which uses the public registries and needs none. `NugetFeedUrl`/`NpmRegistryUrl` default to the `nuget.shesha.dev`/`npm.shesha.dev` feeds shown in [Private feed](#private-feed) above, unless the repo is auto-detected as `shesha-io/shesha-framework`, in which case they default to the public nuget.org/npmjs.org registries instead (see [Special case](#special-case-shesha-ioshesha-framework)). `-DescriptionsFile` is optional — a module with no entry in it (or if the whole step is skipped) falls back to the mechanical entities/APIs/settings/enums listing rather than failing, but that fallback should be treated as a last resort, not the goal.

The full run (4c) will (all of steps 1–3 and 8 read from `-SourceRef` via `git ls-tree`/`git show` instead of the filesystem when the repo is `shesha-io/shesha-framework` — see [Special case](#special-case-shesha-ioshesha-framework) — otherwise from the live working tree exactly as described):
1. Recursively find `*.csproj` (excluding `bin`/`obj`) and group them into module names by stripping `.Domain`/`.Application`/`.Web.Core`/`.Web.Host`/`.Tests`-style suffixes, preferring each csproj's `<PackageId>`.
2. Recursively find `package.json` (excluding `node_modules`) and match each to a module by normalized name similarity; unmatched packages become their own npm-only module.
3. Recursively find `SKILL.md` files and match folder names to modules the same way, capturing `skillName`/`skillLocation` when found.
4. **Drop any candidate module that isn't actually Boxfusion/Shesha's** — a module only survives if its name starts with `shesha`/`boxfusion` (case-insensitive) or its npm scope is `@shesha-io/`. This matters because a repo can vendor a large third-party codebase alongside the real modules (e.g. `pd-chat` bundles Bot Framework Composer's own `@bfc/*`/`@botframework-composer/*` packages) — without this filter every vendored package would get registered too. Dropped candidates are logged, not silently discarded.
5. **Authenticate against the backend** (`/api/TokenAuth/Authenticate`) and list its existing modules via `GetAll` (paginated, 100 at a time) into a `moduleManifestName` → `id` map. This happens once, up front, before any module's NuGet/npm lookup or source scan — not at the end — specifically so each module can be upserted immediately once its own turn finishes (step 11).
6. Resolve the feed's flat-container URL from the NuGet v3 service index (the private Boxfusion feed, or nuget.org for `shesha-io/shesha-framework`), then for each surviving module query it for every published version, and fetch each version's `.nuspec` for its dependencies. **Within each version's dependency list, the same `shesha`/`boxfusion`/`@shesha-io/` name filter applies again** — public dependencies (`Abp`, `NHibernate`, `Microsoft.*`, etc.) are dropped, only Shesha/Boxfusion-owned dependencies are kept. Dropped counts are logged per module, not per dependency (too noisy otherwise). Each version's `publishedDate` is also resolved here, from the feed's `RegistrationsBaseUrl` resource (`catalogEntry.published` on that version's registration leaf) — a second, best-effort request per version; if the feed doesn't expose a registration resource, or a given lookup fails, `publishedDate` is left `null` rather than failing the sync.
7. Query the private npm registry doc for the matched package (one call returns every version + dependencies + a `time` map of version → publish timestamp), applying the same dependency filter and reading `publishedDate` straight out of that `time` map.
8. Merge NuGet + npm versions into one `versions` array per module (one entry per distinct version number; a version present in both ecosystems gets both dependency lists appended, and keeps NuGet's `publishedDate` over npm's if both resolved one). **The merged array is then sorted newest-first by `publishedDate`** (versions with no resolvable date sort last) — this is what "groups" the versions by date: same-day releases naturally end up adjacent, and the registry/UI don't need to re-sort them.
9. **Scan each surviving module's own source folders** (the directories containing its matched `.csproj` files - not the whole repo) for:
   - **Domain entities**: any `public class X : FullAuditedEntity<...>` (or `AuditedEntity`/`CreationAuditedEntity`/`Entity`, generic argument optional, `abstract`/`sealed`/`partial`/`static` modifiers and a namespace-qualified base name like `Abp.Domain.Entities.Auditing.FullAuditedEntity` all tolerated) and its own `public virtual {Type} {Name} { get; set; }` properties (not inherited ones). Also captures `namespace`, `baseClass` (the matched base type plus its generic argument as written, e.g. `FullAuditedEntity<Guid>` or `Entity<int>`), and `isAbstract`. **Entities that extend another domain entity, not one of those four base classes directly** (e.g. `public class SpecialWidget : Widget`, including through an `abstract` intermediate base like `public abstract class BaseWidget : FullAuditedEntity<Guid>`), are also picked up: this runs as a fixed-point pass across every `.cs` file in the module together — once a class is recognized as an entity, its name becomes a valid base name for the next pass, so subclasses (and subclasses of those) are found too, however many inheritance levels deep and regardless of which file declares which class or what order they're scanned in. `baseClass` for these is just the parent's name (e.g. `"Widget"`), since there's no generic argument to report. Abstract entities are still recorded (`isAbstract: true`) but don't get a synthesized CRUD API set in the `"Crud"` category below, since Shesha can't expose dynamic CRUD for a type that can't be instantiated — only concrete entities do.
   - **Known entity-extraction gaps** (heuristic regex scan, not a compiler): a non-`public` entity class (`internal class X : FullAuditedEntity<...>`, or no modifier at all) is never matched, and an entity extending a base class declared in a *different* module is never matched either — module scanning is intentionally scoped to that module's own source folders (see Key Rules), so a parent entity outside that scope can't be recognized as a valid base name.
   - **APIs** are extracted into two categories, both stored in the same `apis` array with a `category` field so the registry (and its UI) can group them:
     - **`"Crud"`** — Shesha auto-generates a dynamic CRUD controller for every domain entity, so these aren't scanned for in source at all: for **every entity found in this same step**, 5 APIs are synthesized directly — `Create` (POST), `Get` (GET), `GetAll` (GET), `Update` (PUT), `Delete` (DELETE) — with route `/api/dynamic/{RouteModuleName}/{EntityName}/Crud/{Method}` and name `{EntityName}{Method}` (e.g. `NotificationTemplateCreate`). This guarantees every entity discovered shows a full CRUD API set, even if the entity has no hand-written controller at all.
     - **`"Custom"`** — any `*AppService` class's `[HttpGet]`/`[HttpPost]`/`[HttpPut]`/`[HttpDelete]`-attributed public methods, with the route reconstructed as `/api/services/{RouteModuleName}/{ServiceName}/{MethodName}`.
     - For `"Custom"` routes, `RouteModuleName` comes from the `moduleName: "X"` argument to `CreateControllersForAppServices(...)` found in the module's own `*Module.cs`/`*ApplicationModule.cs`, falling back to the module's own short name if not found.
     - For `"Crud"` routes, `RouteModuleName` instead comes from the module's own **Domain**-layer `*Module.cs` — specifically the name passed to `new SheshaModuleInfo("X")` on its `ModuleInfo` override, e.g. `public override SheshaModuleInfo ModuleInfo => new SheshaModuleInfo("boxfusion.chat");` yields `boxfusion.chat`. Only `*Module.cs` files found under a source folder whose name ends in `.Domain` are checked for this. If no such declaration is found, it falls back to the `"Custom"` route's `RouteModuleName`, then to the module's own short name.
   - **Settings**: any `interface IXSettings : ISettingAccessors` and its `[Setting(...)]`-decorated properties, using the `[Display(Name=..., Description=...)]` values when present.
   - **Enums**: any `public enum X { ... }` declaration (including Shesha's code-based `RefList*` reference-list convention, e.g. `[ReferenceList(...)] public enum RefListFoo : long { ... }`), capturing each member's name and its explicit numeric value if one is given (`null` otherwise). Member-level attributes like `[Description("...")]` and XML doc comments are stripped before parsing, so they don't interfere. An enum with an empty body (a purely data-driven reference list with no compile-time members) is still recorded, with an empty `values` array.

   This is regex/brace-matching heuristic extraction, not a full C# parser — it's tuned to how this codebase (and Shesha generally) actually writes these patterns, not arbitrary C#. Verified against this exact repo's own `ModuleInfo`/`ModuleInfoSearchAppService`/`IModuleRegistrySettings` (entities/APIs/settings) and against real `RefList*` enum files from `pd-chat` (enums, including a multi-value enum with `[Description]`/XML-doc-decorated members and an empty-body data-driven reference list).
10. **Set the module's `description`** — if `-DescriptionsFile` (Step 4b) has an entry for this module, that authored, understanding-based description is used verbatim. Otherwise it falls back to a mechanical listing of entity/API/setting/enum names (e.g. *"Domain entities: NotificationTemplate. Exposes 5 CRUD endpoint(s) and custom endpoints (Send). Settings: DefaultChannel. Reference lists/enums: RefListNotificationChannel."*) — a last resort, not the goal, since it's `null` when there's nothing to list. Either way this never falls back to whatever NuGet/npm reports for the package — the registry's summary should track what the module actually does, not a possibly-stale package blurb.
11. **Upsert this module right now** — `Update` if its name was already in the map built in step 5, `Insert` otherwise — before moving on to the next module, rather than collecting every module's payload and upserting all of them in one batch at the very end. This is what makes the sync resumable: if the process is killed partway through, every module synced so far is already committed to the registry, not lost; simply re-running the same command re-syncs from the top, and re-processing an already-synced module just updates it again (exact `moduleManifestName` match) rather than duplicating it — so nothing already done is lost, and nothing already done blocks the rest from finishing.
12. Print a colored summary table: Created / Updated / Failed per module, with version/entity/API/setting/enum counts (API counts break down as `[N CRUD / M custom]`).

### Step 5: Present results

Report the summary table to the user, and flag any `Failed` rows with their error detail.

## Key Rules

- **`BackendUrl` defaults to `shesha-moduleregisty-api-test`; `Username`/`Password` never do.** The URL is baked in by explicit request — don't ask the user for it unless they want a different target, pass `-BackendUrl` to override. Credentials are different: always ask for `Username`/`Password` before running (Step 1) — they have no default and the script throws immediately if either is missing for a real sync run. Don't hardcode credentials into the script under any circumstances; if asked to, flag it and confirm first, the same as any other risky, hard-to-reverse change.
- **Immediate per-module upsert, not a batch at the end.** Authentication and the existing-modules lookup (step 5) happen once, up front, before any module is scanned — then each module is `Insert`ed/`Update`d as soon as its own processing finishes (step 11), not accumulated into one array upserted after every module is done. This makes the sync resilient to being killed mid-run: whatever's already synced is already committed, and re-running from the top is always safe (idempotent by `moduleManifestName`) rather than something that duplicates or has to be "resumed" by hand.
- **Module ≠ csproj.** Group by conceptual module first; never create separate registry entries for `.Domain` vs `.Application` of the same module.
- **Only Boxfusion/Shesha-owned packages get registered** — anything not matching the `shesha`/`boxfusion`/`@shesha-io/` naming filter is dropped and logged, never inserted. This applies at both the module level (whole packages) and the dependency level (a Shesha/Boxfusion module's public dependencies like `Abp`/`NHibernate`/`Microsoft.*` are recorded nowhere — only its Shesha/Boxfusion dependencies survive into `dependencies`).
- **A module not published anywhere is still registered** — with an empty `versions` array — rather than skipped, so it's discoverable even before its first release.
- **Entities/APIs/settings/enums are extracted per-module, not per-repo** — only the source folders belonging to that specific module's own `.csproj` files are scanned, so one module's entities never bleed into another's.
- **Every entity gets a full CRUD API set for free.** The 5 `Crud`-category APIs per entity are synthesized from the entity list itself, not scanned from source — so an entity with zero hand-written controller code still shows `Create`/`Get`/`GetAll`/`Update`/`Delete` in the registry. Only endpoints beyond that default set need a real `[Http*]`-attributed AppService method, and those are the ones tagged `Custom`.
- **Versions carry a `publishedDate` and are always sent newest-first.** The registry backend re-sorts by `publishedDate` on every read regardless of insertion order, so this is belt-and-suspenders, not the only place ordering is enforced — but the script still sorts before sending so the console summary and the payload itself read the same way. A version with no resolvable publish date (feed didn't expose one, or the lookup failed) still gets registered — with `publishedDate: null` — rather than being dropped.
- **Descriptions should be authored by actually reading the module's source, never taken from NuGet/npm.** Run the `-ExportOnly` scan (Step 4a), read each module's real source to write a genuine "what does this do and what's it for" summary (Step 4b), then pass it via `-DescriptionsFile` (Step 4c). A module with no authored entry falls back to a mechanical entities/APIs/settings/enums listing — acceptable as a last resort, but never the intended outcome.
- **Idempotent by design** — re-running against the same repo updates existing entries by exact (case-insensitive) `moduleManifestName` match rather than duplicating them. Since `GetAll` is paginated, the script pages through it (100 at a time) until a short page is returned, so this stays correct as the registry grows past one page.
- Transient NuGet/npm failures are retried once, then that specific version is skipped with a warning — the whole run never aborts because one version's lookup failed.
- Multi-targeted NuGet packages may list the same dependency more than once (once per target framework group) — the script doesn't de-duplicate across TFM groups; treat minor duplication in `dependencies` as a known limitation, not a bug.
- **Never hardcode the PAT.** Use `SHESHA_FEED_PAT`; the script throws immediately if no PAT is available from either source — except for `shesha-io/shesha-framework`, which needs none.
- **The public-registry / git-ref behavior is scoped to exactly one repo, auto-detected, never opt-in via a flag.** Only `shesha-io/shesha-framework` (matched off `git remote get-url origin`) switches to public NuGet/npm and mandatory `-SourceRef` git-ref scanning — see [Special case](#special-case-shesha-ioshesha-framework). Every other repo — including any other Boxfusion/Shesha repo — keeps using the private feed and the live working tree exactly as before; don't pass `-SourceRef` for those.
- Requires PowerShell 5+ (`Invoke-RestMethod` XML/JSON auto-parsing), `git` on `PATH`, and network access to `pkgs.dev.azure.com` (or `api.nuget.org`/`registry.npmjs.org` for the shesha-framework case).

Now run the sync based on: $ARGUMENTS
