# Catalogue Schemas — the six JSON artefacts, field by field

`build_catalogs.py` writes these into `<run>/catalog/`. This file is the contract: what each
field means, how it was derived, and what it does **not** mean. Read the "does not mean"
column before quoting a field in a report — most wrong findings in an audit of this shape come
from over-reading a boolean.

**The format itself is declared in `resources/catalog_schema.py`.** That module lists every
row field in order, with its type and default. This file explains what the fields mean.
`build_catalogs.py` normalises every row against the declaration before writing, so:

- **every row carries every field, in the same order, on every run.** A field that applies
  only to some rows is still present on the others, holding its default: `reviewed: false`,
  `reviewNote: null`, `reviewTheme: null`, `observedAnonymous: false`, and in
  `authorizationRules` `perAction: null`, `entityConfigPermissions: null` and
  `effectiveAccessBeforeProbe: null`. Test the value, not whether the key exists.
- **row lists are sorted by their natural key**: endpoints by `path`, entities by `entity`,
  configured forms by `form`, custom forms by `file`, roles by `role`, permissions by
  `permission`, and findings by `id` (natural order, so `ANO-2` sorts before `ANO-10`).
- **nullable fields stay nullable.** `accessConfig` is null when a form has no record of its
  own; `label`, `modelType`, `tableName`, `className`, `description` and similar values come
  straight from live configuration and may be null.

`verify_run.py`'s `catalog-schema` check fails a run whose files differ from the declaration
in fields, order, types, header or sorting. To change the format, change `catalog_schema.py`
first, then this file, then the builder.

What does still vary between runs, by design: a package's file is only written when it has
rows of that artefact, so the set of files depends on the application.

## Contents
- What a "package" is
- File naming, and `_index.json`
- Fields shared by every artefact
- `{package}-roles-and-permissions.json`
- `{package}-configured-forms.json`
- `{package}-custom-forms.json`
- `{package}-endpoints.json`
- `{package}-entities.json`
- `{package}-other-findings.json`
- The internal `_` packages
- Rules for reading the catalogue

## What a "package" is

The unit that owns an artefact and would fix it:

| Package kind | Example | Owns |
|---|---|---|
| App-owned Shesha module | `Shesha.Hcm`, `SaGov.Leave` | Endpoints, entities, forms, permissions declared in this repository |
| Imported Shesha module | `Shesha`, `Shesha.Enterprise`, `Shesha.Workflow`, `Boxfusion.SAGov` | Everything a compiled NuGet package contributes. Fixed by configuration or an upgrade, never by editing this repository |
| Front-end code package | `adminportal`, `adminportal/packages/hcm` | Coded screens, routes and components |

`package` never means "not your problem". A package endpoint left anonymous is this
application's live exposure; only the remediation route differs.

Attribution is recorded, not assumed. Every endpoint row carries `attributedBy` naming the
evidence used, in this order of strength: the PermissionedObject record's own module → the
namespace prefix of that record → the service class name seen in another record → an entity
of the same name → the project that declares the class → the URL segment the module
registered → the namespace root matching a known module name (weak). Rows that reach none of
these land in `_unattributed` and must be reconciled by hand.

Findings about a file are attributed to the module of the project containing it. A project
that declares no module of its own (an `*.Application` or `*.Web.Host` project) rolls up to
the module its sibling declares, so `Startup.cs` findings appear under the application's
primary module rather than in a bucket named after the host project.

## File naming, and `_index.json`

```
<run>/catalog/
  _index.json
  Shesha.Hcm-roles-and-permissions.json
  Shesha.Hcm-configured-forms.json
  Shesha.Hcm-endpoints.json
  Shesha.Hcm-entities.json
  Shesha.Hcm-other-findings.json
  adminportal-custom-forms.json
  ...
```

A file is written only when the package has at least one row of that kind — an empty file
implies "checked and clean" when the truth is "nothing of that kind exists here". Package
names are sanitised for the filesystem (`/` becomes `-`); the unsanitised name is in the
`package` field.

`_index.json` is the manifest and the honesty record:

| Field | Meaning |
|-------|---------|
| `packages` | Package name → `{owner, files[]}` |
| `totals` | Row counts across all packages |
| `inputsMissing` | Cache files that were absent. Each one caps what the catalogue can claim |
| `confidence.frontendsDetected` / `frontendsScanned` | Scanning fewer than all of them caps every unreferenced result at REVIEW |
| `confidence.opaqueFormReferences` / `formsWithOpaqueReferences` | Runtime-built URLs in form scripts. The honest measure of how far `isUnreferenced` can be trusted |
| `confidence.roleGrantsResolved` | False means `rolesAssignedTo` is empty everywhere because the data was not readable — **not** that no role holds the permission |
| `confidence.entityPermissionsCollected` | False means entity `authorizationRules` fell back to the global default only |
| `confidence.swaggerAvailable` | False means the endpoint surface is incomplete and 404s cannot be interpreted |

## Fields shared by every artefact

| Field | Meaning |
|-------|---------|
| `package`, `artifact` | Which file this is |
| `generated`, `backend` | When, and against which backend |
| `defaultEndpointAccess` | The global fallback in force, and its name. Almost every access decision refers to it |
| `definitions` | The same definitions as this file, embedded so the JSON is self-describing |
| `inputsMissing` | Copied from the index, so a single file is never read out of context |

Two fields recur on rows and are **always** heuristics:

- **`sensitivity`** — `{rating: HIGH|MEDIUM|LOW, basis, reviewRequired: true}`. Derived from
  the artefact's *name* only. `reviewRequired` is always true because a name is not data:
  confirm what the entity actually holds before writing "exposes salary information".
- **`recommendedAction`** with **`recommendationBasis`** — a mechanical disposition from the
  access level, the reference state and the sensitivity rating. The review phase confirms or
  overrides each one. Values: `KEEP`, `KEEP-INFRA`, `RESTRICT`, `SET-EXPLICIT-ACCESS`,
  `FIX-EMPTY-PERMISSION-SET`, `ADD-GLOBAL-SPECIFICATION`, `DISABLE-ACTION`,
  `DISABLE-ENTITY`, `DISABLE-ENDPOINT`, `REVIEW-FOR-REMOVAL`, `REMOVE-OR-WIRE-UP`,
  `GRANT-TO-A-ROLE`, `REVIEW`.

## `{package}-roles-and-permissions.json`

Header: `roleCount`, `permissionCount`, `unreferencedPermissions`.

### `permissions[]`

| Field | Derived from | Does not mean |
|-------|--------------|---------------|
| `permission`, `displayName`, `module`, `owner`, `isDbPermission`, `parentName` | `Permission/GetAll` | — |
| `isUnreferenced` | every count below is zero | Not that it is safe to delete — another repository's forms may use it |
| `guardsNothing` | no PermissionedObject row and no form names it | It may still be checked in code by hand |
| `rolesAssignedTo[]` | per-role grants (`GetRoleForEdit`) | An empty array is meaningless when `confidence.roleGrantsResolved` is false |
| `numReferencesByFormConfig` | form markup `permissions` / `requiredPermissions` keys, plus `Shesha.Form` rows | — |
| `numReferencesByWebApiConfig` | `Shesha.WebApi` + `Shesha.WebApi.Action` rows naming it | — |
| `numReferencesByEntityConfig` | `Shesha.Entity*` / `Shesha.WebCrudApi*` rows, plus entity-configuration permission fields | — |
| `numReferencesByAppServiceCode` | occurrences in `*AppService.cs` / `*Controller.cs` | A string match, so a comment counts |
| `numReferencesBySpecificationCode` | occurrences in specification classes | Guards **rows**, not endpoints |
| `numReferencesByOtherBackendCode` | occurrences in any other `.cs` | Usually the constant's own declaration |
| `numReferencesByCustomForm` | occurrences in scanned front-end source | — |
| `totalReferences` | sum of the above | — |

### `roles[]`

`role`, `id`, `module`, `description`, `permissions[]`, `permissionCount`,
`grantsResolved`, `holdsNoPermissions`. `grantsResolved: false` means the grants could not be
read for that role — treat `permissions: []` as unknown, not as empty.

## `{package}-configured-forms.json`

Header: `formCount`, `unreferenced`, `anonymous`.

One row per **live** form version (`isLastVersion`), keyed `module/name`.

| Field | Derived from | Does not mean |
|-------|--------------|---------------|
| `form`, `module`, `name`, `label`, `modelType`, `owner` | `FormConfiguration/GetAll` | — |
| `isUnreferenced` | not in the main menu, not referenced by another form, not opened by a coded screen | Not unreachable — any form can be opened by URL at `/dynamic/{module}/{name}` |
| `isReferencedByMainMenu` | `Shesha.MainMenuSettings` | False when `mainmenu.json` is in `inputsMissing`, which is missing data rather than a finding |
| `isReferencedByOtherForm`, `referencedByForms[]` | `formId` / `formIdentifier` in another form's markup (subforms, dialogs) | — |
| `isReferencedByCustomForm`, `referencedByCustomForms[]` | `formId` in front-end source | — |
| `endPointsReferenced[]` | resolved entries `{url, resolved: true}`, plus opaque entries `{resolved: false, opaque: true, reason, markupKey, snippet, guessedUrl}` | An opaque entry is a *lead*: `guessedUrl` is a guess and `snippet` is the code that builds the URL, windowed around the match |
| `formsReferenced[]`, `entitiesReferenced[]`, `referenceListsReferenced[]`, `ownerBindings[]` | the nine mechanisms in `form-reference-mechanisms.md` | — |
| `staleEndpoints[]` | bindings on the inactive branch of a source-type discriminator | Not live references. Do not count them as usage |
| `externalUrls[]` | absolute URLs to other hosts | Worth a look: data leaving the application |
| `accessConfig`, `hasPermissionedObjectConfig` | the `Shesha.Form` row | `access: 5` means the form opens without a login |
| `permissionsReferenced[]` | permission names in the markup | Form-level gating hides UI; it does not protect the endpoints behind it |

## `{package}-custom-forms.json`

The same questions asked of coded screens. One row per scanned front-end source file.

| Field | Meaning |
|-------|---------|
| `file`, `frontend`, `package`, `kind`, `route` | `kind` is `route-page`, `screen`, `designer-component`, `component`, `api-module`, `provider`, `route-table`, `constants` or `other`. `route` is the Next.js App Router path, or null |
| `isUnreferenced` | No route, nothing imports it, no menu entry. For a component that is dead code; check it is not exported for another package first |
| `isReferencedByMainMenu`, `isReferencedByOtherForm`, `referencedByCustomForms[]` | Menu URL match; the import graph |
| `endPointsReferenced[]` | Same shape as configured forms, including opaque entries |
| `formsReferenced[]`, `entitiesReferenced[]`, `permissionsReferenced[]` | `permissionsReferenced` is filtered against the live permission list, so look-alike strings are dropped |
| `routesDeclared[]` | Route constants a route table declares |
| `usesDataHooks` | The file calls `useGet`/`useMutate`-style hooks, so it talks to the backend even where no literal URL was found |

## `{package}-endpoints.json`

Header: `endpointCount`, `anonymous`, `anyAuthenticated`, `permissioned`, `unreferenced`.

**Dynamic entity CRUD is deliberately excluded** — those endpoints are catalogued per entity
in `{package}-entities.json`, because the fix is per entity, not per URL.

| Field | Derived from | Does not mean |
|-------|--------------|---------------|
| `path` | the OpenAPI document, original casing | — |
| `matchKey` | the lowercased path used for every cross-reference | Do not put this in a report |
| `attributedBy` | see "What a package is" | — |
| `methods[]`, `service`, `action` | OpenAPI plus the PermissionedObject record | — |
| `owner` | `app` or `package` | — |
| `isWriteOperation` | verb, or an action name that starts with a write verb | — |
| `isUnreferenced` | not in the crossref referenced set, and no form or coded file names it | Says nothing about back-end callers, integrations or scheduled jobs. Check `backendCodeReferences` and the safety gates |
| `referenceIndeterminate` | an opaque reference could reach it | Possibly used. **Never** report as unused |
| `referencedBy[]`, `referencedByForms[]`, `referencedByCustomForms[]` | the reference kinds and the specific forms/files | — |
| `hasPermissionedObjectConfig` | a `Shesha.WebApi.Action` row exists | A row can exist and still decide nothing — see `authorizationRules.resolvedVia` |
| `authorizationRules` | the precedence model in `enforcement-rules.md` | `effectiveAccess` is what is enforced. `recordAccess: 2` (Inherited) means the row decided nothing and the global default applies. `hardcoded: true` means a configuration change will be re-seeded away on the next restart |
| `authorizationMethod` | `configuration`, `code`, `both`, or `none` | `none` means nothing decides and `DefaultEndpointAccess` applies — the most common state, and the reason the global default matters so much |
| `grantedToRoles[]` | the roles holding any required permission | Empty with a non-empty `permissions` list means nobody can call it |
| `backendCodeReferences`, `backendCodeFiles[]` | the service class named in another `.cs` file | A safety gate against disabling something a job calls |
| `referencedByPackageSource[]` | `kind: file:line` where the framework's or Enterprise's own source calls it (`scan_package_sources.py`), up to five | Evidence for a `<source>-frontend`, `<source>-backend` or `<source>-packaged-form` entry in `referencedBy[]` |
| `packageSourcesNotScanned[]` | package-owned rows only: imported front-end packages whose source was not scanned, plus the owning module if none of its projects were | Non-empty means an unreferenced verdict is unproven. The recommendation is capped at `REVIEW`. Also on entities and configured forms |
| `packageBackendCodeReferences`, `packageBackendCodeFiles[]` | the service class used in-process by framework/Enterprise back-end code | Not an HTTP caller, so it does not clear `isUnreferenced` — it rules out a disable |
| `hasGlobalSpecifications`, `specificationEntity` | the entity the service is named after (`LeaveRequestAppService` → `…Domain.LeaveRequest`), and whether that entity has a global filter | **`null` means no entity could be matched, not "no filter".** Do not report a null as a missing control |
| `probeResults[]` | live probes, per principal, with the verdict | `NOT-FOUND` and `INCONCLUSIVE` are **not** passes |

## `{package}-entities.json`

Header: `entityCount`, `withCrudEndpoints`, `anonymous`, `unreferenced`,
`withoutGlobalSpecification`.

One row per `EntityConfig`, whether or not it has live endpoints.

| Field | Derived from | Does not mean |
|-------|--------------|---------------|
| `entity`, `className`, `module`, `owner`, `tableName` | `EntityConfig/GetMainDataList` | — |
| `CRUDEndpoints` | letters for the actions **live in the OpenAPI surface**: `C`reate, `R`ead, `U`pdate, `D`elete. `"R"` means read only; `""` means no dynamic CRUD route | — |
| `crudActions` | per action: URL, whether referenced, and by what | — |
| `generateAppService`, `declaredDisableGenerateApplicationService` | the entity configuration row and the `[Entity(...)]` attribute | The declared intent may not be honoured — compare with `CRUDEndpoints`. If the flag says "no service" and letters are present, the flag is inert on this framework version |
| `unreferencedActions[]`, `unreferencedWriteActions[]` | per-action reference state | Write actions unreferenced while read is used is the safest, highest-value disable available |
| `isUnreferenced` | has CRUD routes, none referenced, no form binding, no coded reference | — |
| `referenceIndeterminate` | as for endpoints | — |
| `backendCodeReferences`, `backendCodeFiles[]` | the entity class named in `.cs` files | Almost always non-zero: the entity is used *in code*. It is a gate against disabling, not evidence the API is used |
| `hasPermissionedObjectConfig` | a `Shesha.Entity` or `Shesha.Entity.Action` row exists | On 0.43.x these tables are normally empty, so false is the norm and the global default decides |
| `authorizationRules` | entity row, else action rows (with `perAction`), else the global default. `entityConfigPermissions` carries what the entity configuration UI declares | — |
| `hasGlobalSpecifications`, `specifications[]` | `[GlobalSpecification]` on a `ShaSpecification<T>` for this entity, from source | False on a sensitive entity reachable by any authenticated user means every user can list everybody's rows |

## `{package}-other-findings.json`

Everything that is not about reducing the endpoint or entity surface: host configuration,
secrets, token policy, rate limiting, dependencies, live probe results and object-level
authorization.

Header: `findingCount`, `bySeverityHint`.

| Field | Meaning |
|-------|---------|
| `id` | Stable within the file, e.g. `WEB-1` |
| `category` | `web-host-configuration`, `settings-and-secrets`, `committed-secret`, `controller-without-authorization`, `row-level-security`, `token-policy`, `rate-limiting`, `dependency-advisory`, `anonymous-access`, `authenticated-access`, `object-level-authorization` |
| `title` | One line, naming the check id where there is one |
| `severityHint` | `CRITICAL`/`HIGH`/`MEDIUM`/`WARN`/`INFO`. A **hint**: rate by impact on this application's data, using the severity guidance in `app-vulnerability-baseline.md` |
| `status` | `FAIL`, `REVIEW` or `SKIP`. A `SKIP` is never a pass — it must appear in the report's skipped-checks section |
| `evidence[]` | `file:line`, or the probe and its status. Cite these, never a line number from memory |
| `recommendationHint` | Points at the section of `remediation-guide.md` that fixes it |
| `reviewRequired` | Always true |
| `checkId`, `anchor` | The registered CHECK-ID (`references/check-registry.md`, with `G1`→`B7` and `D1`/`D2`→`K1`/`K2`) and its symbol/key anchor. `findings.py` forms the stable id `<checkId>@<anchor>` from these. Null on a finding with no registered check |
| `locator` | `file:line` display only — the line number lives here, never in `anchor`, so it stays out of the reproducibility diff |
| `evidenceLevel` | `REPRODUCED`/`VERIFIED-ARTEFACT`/`CODE-ONLY`/`NOT-ASSESSED` etc. (`determinism-standard.md` §3), a separate axis from severity |
| `severityScore` | Derived band (`Critical`…`Low`) from `impactClass`+`reachability`+`dataSensitivity` (`determinism-standard.md` §4). Not asserted — recompute, don't edit |
| `impactClass`, `reachability`, `dataSensitivity` | The three declared severity inputs |
| `planId`, `rootCause`, `subArea` | Templated remediation id, `RC-sec-*` root cause, and the team-split sub-area |
| `nonDeterministic` | `true` for a check a text scan cannot make reproducible (live probe, advisory DB). `normalize_findings.py` drops these from the acceptance diff |

## `review-overrides.json`

The review phase's decisions, applied by the next `build_catalogs.py` run. The first run
writes an empty template; the second folds in whatever the review put there. Running
`build_catalogs.py` only once means the report and the catalogue disagree.

```json
{
  "endpoints":   { "/api/services/Hcm/HcmHealthCheck/Check": { ... } },
  "entities":    { "Shesha.Leave.Domain.LeaveRequest":       { ... } },
  "forms":       { "Shesha.Hcm/hcm-profile-table":            { ... } },
  "customForms": { "src/components/NavCard.tsx":              { ... } },
  "permissions": { "Leave-Balance-Manage":                    { ... } },
  "findings":    { "Shesha.Hcm:WEB-1":                        { ... } }
}
```

Each value may set `sensitivity` (`HIGH`/`MEDIUM`/`LOW`), `recommendedAction`,
`severityHint`, `status`, `package` (to re-attribute a row that landed in `_unattributed`)
and `note`. **`note` is required** — it becomes the row's `recommendationBasis` and
`reviewNote`, and it is what tells the next audit why the heuristic was overridden.

An overridden row carries `reviewed: true` and `reviewRequired: false`; every other row
carries `reviewed: false` and `reviewNote: null`. Anything in the
report that came from a row **without** `reviewed: true` is still a machine guess; either
review it or leave it out.

`_index.json`'s `review` block records how many overrides applied, any that matched nothing —
an unmatched override is a typo, and it means a decision was silently lost — and
`staleFilesRemoved`, the catalogue files a rebuild deleted because their package no longer has
any rows. A reviewer re-attributing the last endpoint out of `_unattributed` empties that
package, and without the sweep the previous build's file survives and keeps asserting rows
that have moved.

`verify_run.py` checks all of this, and it is the gate before anyone reads the run:

```bash
python resources/verify_run.py --run-dir security-audits/YYMMDD-HHMM --repo-root .
```

It fails the run when a report's numbers disagree with the catalogue, when a quoted path
exists nowhere, when secret material reached the output, when a missing input was not
disclosed, when an override matched nothing, when a posture group has no result, or when
`findings.json` is stale. A `reviewed-citations` warning — prose resting on an unreviewed
heuristic — is normal to carry for low-severity rows and should be driven to zero for anything
rated CRITICAL or HIGH.

## The internal `_` packages

| Package | Contents | What to do with it |
|---------|----------|--------------------|
| `_unattributed` | Package-owned endpoints whose module could not be determined | Reconcile by hand; report the count. Never silently drop them |
| `_app-unattributed` | The same for endpoints under an app URL segment | These matter more — an unclassified app endpoint is exactly what an audit must not lose |
| `_probe-findings` | Live probe verdicts needing a human call | Fold each into the package that owns the endpoint while writing the report |
| `_object-authorization` | IDOR / list-scope / file-ownership exposures | Fold into the owning entity's package |
| `_repository` | Repository-wide findings with no single owning project — dependency advisories, git history, absence of any global specification | Report under a "whole application" heading |

## Rules for reading the catalogue

1. **`isUnreferenced` is not permission to delete.** It means the scanned front-end does not
   reach it. Run every safety gate in `disabling-unused-endpoints.md` first.
2. **`referenceIndeterminate: true` outranks `isUnreferenced: true`.** Report it as
   `REVIEW`, never as unused.
3. **A missing input is not a clean result.** Anything in `inputsMissing` caps what can be
   claimed, and the report has to say so.
4. **`hardcoded: true` changes the remediation, not the severity.** A configuration change
   will be re-seeded away; for a package-owned endpoint the honest advice is a proxy rule
   plus an upstream request.
5. **`sensitivity` and `recommendedAction` are inputs to judgement, not conclusions.**
   Confirm each one that reaches the report.
6. **Numbers appear once.** Every count in a report comes from these files or from
   `digest.py`. Two independent computations of the same number is how one earlier audit
   reported an orphaned-permission count of 32 in one document and 29 in another.
