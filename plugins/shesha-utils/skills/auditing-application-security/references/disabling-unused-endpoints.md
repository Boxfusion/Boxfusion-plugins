# Identifying and Disabling Unreferenced Entities and Endpoints

## Contents
- The goal and the risk
- Inputs required
- Safety gates — when NOT to recommend disabling
- The keep-list: infrastructure the SPA calls indirectly
- Classification procedure
- Dispositions
- How to disable an entity
- How to disable a single endpoint
- Verification after disabling
- Report format

## The goal and the risk

Every endpoint that nothing calls is attack surface with no offsetting benefit. Disabling it is the
cheapest security win available to a Shesha application, and the largest single reduction usually
comes from entities that received dynamic CRUD endpoints nobody asked for.

The risk runs the other way: a wrongly disabled endpoint returns 404 and breaks the application at
runtime, often in a screen nobody opens during testing. Shesha's indirection makes this easy to get
wrong — an endpoint can be called by a dialog, a subform, a reference list, an embedded script or a
scheduled job without its URL appearing anywhere.

So the standard is asymmetric. **Recommend disabling only where the evidence is positive and
complete.** Everything else is `REVIEW`, and `REVIEW` is a perfectly good outcome.

## Inputs required

Both catalogs, generated against the same running application:

- `catalog/{package}-endpoints.json` and `catalog/{package}-entities.json` — the surface with
  owner, effective access and permissions
- `catalog/{package}-configured-forms.json` and `catalog/{package}-custom-forms.json` — what the
  frontend references
- `catalog/_index.json` — the `stale-config`, `unresolvable`, `opaque` and `indeterminate` counts

If either is missing or was generated against a different backend state, regenerate it. Comparing
catalogs from different runs produces false unreferenced results.

## Safety gates — when NOT to recommend disabling

An endpoint is **excluded from any disable recommendation** if any of these holds. Record it as
`REVIEW` with the reason.

1. **It appears in the usage catalog's `indeterminate` list** — reachable through a reference the
   frontend builds dynamically.
2. **The usage catalog reported unresolvable references in a form that also binds this entity.**
   The script in that form may call it.
3. **It is on the infrastructure keep-list below.**
4. **A backend caller exists.** Endpoints are also called server-side. Before recommending a
   disable, search application source for the service or entity name:
   ```bash
   grep -rn "EntityName\|ServiceName" backend/src --include=*.cs | grep -v "/obj/"
   ```
   Workflow service tasks, scheduled jobs, notification senders, validators and specifications all
   reference entities without any frontend involvement.
5. **It is referenced by a package-owned form or page.** A package module's forms and coded
   pages are not in this repository's frontend scan but do call endpoints at runtime. With
   `scan_package_sources.py` run, these show up as `<source>-*` kinds in `referencedBy[]`.
   Where a package's source was **not** available, the row's `packageSourcesNotScanned` names
   it and the catalogue already recommends `REVIEW` — keep it there. Never convert such a row
   to a disable during review: "nothing we could see calls it" is not "nothing calls it".
6. **It plausibly serves an external integration.** Import and export endpoints, webhook receivers
   and anything named for a third-party system. Only the user knows; ask.
7. **The application has more than one frontend** — an admin portal plus a public portal, or a
   mobile app — and only one was scanned. Say so and downgrade every unreferenced result to
   `REVIEW`.
8. **Swagger was unavailable during cataloging**, so the endpoint list may be incomplete.

Gate 7 deserves emphasis. Check for sibling frontends before trusting any unreferenced result:

```bash
find . -maxdepth 2 -name "next.config.js" -not -path "*/node_modules/*"
```

## The keep-list: infrastructure the SPA calls indirectly

These are called by the Shesha React runtime rather than by application code, so they rarely appear
in a frontend scan yet are essential. Never recommend disabling them.

| Area | Endpoints |
|------|-----------|
| Authentication | the `TokenAuth` family, `Session/GetCurrentLoginInfo` |
| Password reset | the `User` reset and security-question family |
| Forms | `FormConfiguration/GetByName`, `CheckPermissions`, `GetAll` |
| Metadata | `Metadata/Get`, `Metadata/Specifications`, `Metadata/PropertiesAsync` |
| Reference lists | `ReferenceList/GetByName` |
| Settings | `Settings/GetValue`, `Settings/GetConfigurations` |
| Permissions | `PermissionedObject/*`, `Permission/IsPermissionGranted`, `ShaRole/IsRoleGranted` |
| Files and notes | `StoredFile/*`, the Notes service |
| Entity gateway | `Entities/Get`, `GetAll`, `QueryAll` |
| Configuration | `ConfigurationItem/*`, `Module/GetAll` — needed by the designer |
| Notifications | the notification and subscription services when the app sends notifications |
| Anti-forgery | `AntiForgery/GetToken` |

Configuration and designer endpoints are a judgement call: if the deployment does not expose the
Shesha designer to end users, restricting them to `app:Configurator` is better than disabling them,
because disabling breaks configuration import at deploy time.

## Classification procedure

For each endpoint in the catalog:

1. Referenced by the frontend, coded or via any resolved binding — `KEEP`.
2. Any safety gate applies — `REVIEW`, with the gate named.
3. On the keep-list — `KEEP-INFRA`.
4. Otherwise, unreferenced. Split by what it is:
   - all five CRUD actions of an entity are unreferenced — candidate `DISABLE-ENTITY`
   - some actions unreferenced, others used — candidate `DISABLE-ACTION` for the unused ones
   - a hand-coded service method — candidate `DISABLE-ENDPOINT`
5. Rank candidates by benefit: an unreferenced entity holding personal data that is currently
   anonymous or any-authenticated is the highest-value disable.

Write-side actions deserve separate attention. An entity whose `GetAll` is used by a read-only
report but whose `Create`, `Update` and `Delete` are unreferenced is a strong `DISABLE-ACTION`
candidate — that is a large reduction in risk with almost no chance of breaking a screen.

## Dispositions

| Disposition | Meaning | Action |
|-------------|---------|--------|
| `KEEP` | Referenced | None |
| `KEEP-INFRA` | Framework infrastructure | None; consider tightening permissions instead |
| `DISABLE-ENTITY` | No action on this entity is referenced | Stop generating CRUD, and set the entity record to Disable |
| `DISABLE-ACTION` | Specific CRUD actions unreferenced | Set those action records to Disable |
| `DISABLE-ENDPOINT` | A hand-coded method is unreferenced | Set its action record to Disable |
| `RESTRICT` | Referenced, but by a narrow audience | Raise to `RequiresPermissions` rather than disabling |
| `REVIEW` | A safety gate applies | Ask the user; do not act |

Prefer `RESTRICT` over `DISABLE` whenever an endpoint has any plausible caller. Restricting is
reversible in configuration and fails visibly as a 403; disabling returns 404 and looks like a bug.

## How to disable an entity

Two mechanisms, and they are not equivalent.

**Mechanism 1 — the entity configuration flag.** Set `GenerateAppService = false`, either through
`[Entity(GenerateApplicationService = DisableGenerateApplicationService)]` in application source or
through the entity configuration UI.

Verify it actually takes effect. In some framework versions dynamic controller registration does not
consult this flag, so the endpoints remain live. Probe after restarting:

```bash
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/api/dynamic/{module}/{Entity}/Crud/GetAll?maxResultCount=1"
```

If it still returns 200, the flag is inert on this version — use mechanism 2.

**Mechanism 2 — the permission record.** Set the `PermissionedObject` for the entity and its actions
to `Access = 1 (Disable)`. This is enforced by `ObjectPermissionChecker` regardless of version: the
endpoint returns 404 and `SwaggerDocumentFilter` removes it from the Swagger document.

Mechanism 2 is the reliable one. Prefer it, and use mechanism 1 alongside it to record the intent in
source.

Set it through the admin UI, or through the API:

```
PUT /api/services/app/PermissionedObject/Update
{ "object": "{Namespace}.{Entity}@{Action}", "type": "Shesha.Entity.Action", "access": 1 }
```

For a durable, reviewable change, prefer a FluentMigrator migration in the owning module so the
setting is version-controlled and applied to every environment. Do not rely on a manual UI change
for anything that matters — it exists only in the database it was made in.

## How to disable a single endpoint

Same mechanism, different object type. For a hand-coded service method, set the
`Shesha.WebApi.Action` record named `{ClassFullName}@{MethodName}` to `Access = 1`.

Remember the bootstrapper rule: a record whose access is still `Inherited` is re-seeded from code
attributes on every restart, but an explicit `Disable` with `hardcoded = false` persists. Setting
`Disable` is therefore durable, unless the endpoint carries `[AllowAnonymous]` or `[AbpAuthorize]`
in code, which makes it `hardcoded = true` and resets it on the next restart. For those, the
attribute must change in source — which is only possible for app-owned endpoints. For a package-owned
endpoint in that situation, record the limitation rather than promising a fix.

## Verification after disabling

Never report a disable as done without checking it. After applying and restarting:

1. The endpoint returns 404 for an authenticated user.
2. The application still works — exercise the screens that touch the same entity.
3. The Swagger document no longer lists it, if Swagger is reachable.
4. Re-run the catalogue phase (`collect.py` -> `analyze_forms.py` -> `build_catalogs.py`)
   and confirm no new broken references appeared.

Recommend disabling in batches by module, not all at once. A batch that breaks something is easy to
attribute; forty simultaneous changes are not.

## Report format

```markdown
## Unreferenced Endpoints and Entities

Frontends scanned: {list}          Confidence: {high | reduced, with reason}
Unresolvable references: {n}       Indeterminate endpoints: {n}

### Recommended for disabling — entities
| Entity | Owner | Module | Actions | Current Access | Sensitivity | Disposition | Mechanism |

### Recommended for disabling — individual endpoints
| Endpoint | Owner | Service | Current Access | Disposition | Mechanism |

### Recommended for restriction instead
| Endpoint | Owner | Current Access | Suggested Permission | Why not disable |

### Requires review before any action
| Endpoint | Owner | Safety gate that applied | What to confirm |

### Estimated reduction
Endpoints today: {n}. After the recommended disables: {n}.
Anonymous or any-authenticated endpoints removed: {n}.
Entities no longer exposing CRUD: {n}.
```

State the confidence line honestly. If only one of two frontends was scanned, or the usage catalog
carried a large unresolvable list, say that the unreferenced set is a starting point for review
rather than a list to apply.
