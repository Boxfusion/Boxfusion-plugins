# ORM and Shesha checks

Shesha lets people build systems quickly without deep database knowledge, and that is its strength. The cost is that the easy way to fetch data is often the expensive way, and it stays invisible until the data grows. These checks find where the system asks the database for far more than it needs, resolves records by the wrong key, or crosses a transaction boundary it should not.

**This file obeys `${CLAUDE_PLUGIN_ROOT}/shared/operating-standard.md`.** Every check is a decision procedure: **INPUT → PREDICATE (boolean) → VERDICT → ANCHOR**, then **REMEDIATION (plan_id + template) → REGRESSION TEST → SEVERITY INPUTS**. A finding is raised **iff** the predicate is true and an anchor exists — no anchor ⇒ no finding, no anchor-less "smell". IDs are `ORM-X@<anchor>` (operating-standard §3) — **never** `ORM-X-1/-2/-3`; multiplicity is carried by the anchor (N anchors ⇒ N findings that collapse by identical string). Severity is scored intrinsically from the operating-standard §5 table (evidence level is a separate axis, not a severity input).

**ORM findings are overwhelmingly forward-looking.** On starter/near-empty data with no App Insights, nothing here can be *reproduced* as an incident; the honest level is `CODE-ONLY` and the wording is "the query grows with the table…", never "this is slow in production". Severity is still the intrinsic badness *if the table grows as designed* (ground rule 4), scored against the manifest's `severity_target`, and is **never** read off the copy's row count.

**Best proof source (capability-gated):** App Insights `dependencies` (SQL calls) per request (`${CLAUDE_PLUGIN_ROOT}/shared/appinsights-queries.kql` §3 SQL-calls-per-request, §4 heaviest statements). They show directly how many queries one page load makes and how many rows travel. Code reading says what *might* happen; telemetry shows what *does*. Absent App Insights ⇒ the telemetry dimension is a first-class `NOT-ASSESSED(no-app-insights)` record, never a silent pass.

**Shesha 0.43 markup facts that help detection:** the form's data loader is in `formSettings.dataLoaderType`; post-load scripts are in `onAfterDataLoad`; entity permissions appear as `Shesha.Entity` (five rows per entity) and `Shesha.Entity.Action` permissioned objects. Business form markup usually lives in the **DB** (starter data), not the repo — only framework scaffolding forms ship in `App_Data/Upload/*.shaconfig`. When markup is not in the repo, the form-level dimensions of ORM-A/B/C/H are `NOT-ASSESSED(form-markup-not-in-repo)`, a stated gap, never a clear.

**Pins (from the manifest, operating-standard §1):** `$SHA` = `$(SheshaVersion)` from `backend/Directory.Build.props`; `$DLL` = the `Shesha.Application/$SHA` path resolved from `Web.Host/obj/project.assets.json` (every decompile targets this exact path). `$BASE` = the backend URL when `backend_running`. `$SRC` = `backend/src` (all greps below run under it unless stated).

## Capability-gating table (operating-standard §1 — absent capability ⇒ first-class NOT-ASSESSED, never a silent pass)
| Capability absent | Dimensions that become `NOT-ASSESSED(reason)` (fixed anchors) |
|---|---|
| `app_insights` | per-request SQL-count / row-volume proof of ORM-A/D/I → `ORM-A@telemetry`, `ORM-D@telemetry`, `ORM-I@telemetry` `NOT-ASSESSED(no-app-insights)`; the static code predicate still runs at CODE-ONLY |
| `db_copy` not production-representative (starter / near-empty — manifest `db_copy.identity`) | row-count proof of ORM-C/E and the seed-past-one-page proof of ORM-H → `ORM-C@db`, `ORM-E@db`, `ORM-H@db` `NOT-ASSESSED(starter-data)`; static predicate still CODE-ONLY |
| `low_priv_account` | ORM-E restricted-user `Crud/GetAll` count-compare → `ORM-E@authz-probe` `NOT-ASSESSED(no-low-priv-user)` (handover reachability to SEC-C) |
| `form_markup_in_repo` (business markup lives in the DB) | ORM-A list-form shape / ORM-B quickSearch markup / ORM-C `maxResultCount=-1|2147483647` in markup / ORM-H page-as-total scripts → `ORM-A@forms`, `ORM-B@forms`, `ORM-C@forms`, `ORM-H@forms` `NOT-ASSESSED(form-markup-not-in-repo)` |
| `backend_running` | any live row-count probe folds into the `@db`/`@telemetry` NOT-ASSESSED records above; it never upgrades a CODE-ONLY static finding |

All capability-gated NOT-ASSESSED records are **MANDATORY fixed anchors** — every operator emits every one, always, so two runs' NOT-ASSESSED sets match exactly. They carry `severity: "Info"` and never enter the fix-order list (operating-standard §5/§6).

## Determinism pins (apply exactly; these remove cross-operator divergence)

**Fixed `root_cause` per check (enumerated `RC-orm-*`, never free text — see §3 vocabulary addition in the notes).**
| root_cause | checks |
|---|---|
| `RC-over-fetch` | ORM-A, ORM-I, ORM-K |
| `RC-unbounded-query` | ORM-C, ORM-H |
| `RC-in-memory-filtering` | ORM-D |
| `RC-non-sargable-search` | ORM-B |
| `RC-generic-crud-exposure` | ORM-E |
| `RC-transaction-boundary` | ORM-F |
| `RC-name-based-lookup` | ORM-G |
| `RC-tracking-session` | ORM-J |
`fix_order_rank` is a pure function of `{severity, root_cause, anchor}` (operating-standard §6) — never hand-sequenced, so it matches across runs. ORM-E findings handed to Security carry the Security `root_cause` (`RC-sec-no-authz`) in the SEC-C record; the ORM-side custom-base record keeps `RC-generic-crud-exposure`.

**Fixed severity-inputs per check (impact_class + data_sensitivity are FIXED properties of the check; reachability resolves from the call-site rule below).** Author these exactly so two operators compute the same band.
| Check (sub-predicate) | impact_class | data_sensitivity | typical reachability → band |
|---|---|---|---|
| ORM-A over-fetch for display | dos | business | any_authenticated → Medium |
| ORM-B non-sargable multi-field search | dos | business | any_authenticated → Medium (paged type-ahead, ≤2 explicit fields → local_only → Low note) |
| ORM-C unbounded materialise (hot request path) | dos | business | any_authenticated → Medium |
| ORM-C unbounded materialise (batch / import path) | dos | business | admin_only → Low |
| ORM-D-a fetch-all-then-filter | dos | business | any_authenticated → Medium |
| ORM-D-b DB-call-inside-mapper (hidden N+1 + service-locator) | dos | business | any_authenticated → Medium |
| ORM-D-c bounded per-row lazy dot-walk | maintainability | business | local_only → Low *(non_deterministic — quarantined)* |
| ORM-E custom CRUD-base re-exposing a whole table | data_exposure_pii | popia_special | any_authenticated → Critical (handover SEC-C) |
| ORM-F-a side effect inside the save path | data_integrity | business | any_authenticated → High |
| ORM-F-b sequence drawn on a separate session in the save path | maintainability | business | admin_only → Low |
| ORM-G-a name lookup that crashes on not-found (request path) | data_integrity | business | any_authenticated → High |
| ORM-G-b versioned config/template by Name, no live-version filter (sender/job) | data_integrity | business | admin_only → Medium |
| ORM-G-c name lookup with a graceful not-found guard / roles-by-name | data_integrity | business | local_only → Low |
| ORM-H page used as a total driving a decision | data_integrity | business | any_authenticated → High |
| ORM-I lazy load at serialisation (raw entity / entity-nav DTO returned) | dos | business | any_authenticated → Medium |
| ORM-J no read-only session discipline (solution-wide) | dos | business | any_authenticated → Medium |
| ORM-K cartesian from ≥2 sibling collections in one query | dos | business | any_authenticated → Medium |
Empty-verdict (`ORM-x@…=none`, `ORM-x@none`) and NOT-ASSESSED records: `evidence_level=CODE-ONLY`/`NOT-ASSESSED(reason)`, `severity: "Info"` (operating-standard §5).

**Reachability resolver (ORM — deterministic from the call site, not judgement; replaces any auth-gate reading).** Resolve in priority order; first match wins:
1. `local_only` — the pattern is **latent** (no caller wires it / not reachable) OR **guarded** so it cannot misbehave (explicit not-found throw, or a per-row walk bounded by exactly one parent record).
2. `admin_only` — the call site is a background job, scheduled job, import/batch service, PDF/report generator, or notification/template sender (system-initiated, not an interactive hot path).
3. `any_authenticated` — the call site is an interactive request-serving app-service/controller action on a hot path.
4. `anonymous` — only if the endpoint itself is anonymous (rare for ORM; the dynamic-CRUD default is authenticated — that is SEC-C's axis, recorded there).

**Quarantined sub-predicates (operating-standard §9 — emit tagged `non_deterministic:true`; the normalizer drops them from the acceptance diff until a semantic analyzer lands).** A text grep genuinely cannot make these reproducible:
- **ORM-D-c (per-row lazy dot-walk).** `rg "MapFrom\(\s*\w+\s*=>\s*\w+\.\w+\.\w+"` finds multi-level navigation walks, but **whether a `.Fetch`/`ProjectTo` plan already covers the navigation** needs NHibernate fetch-plan resolution — operators diverge on "covered or lazy?". Deterministic replacement = a Roslyn/NHibernate fetch-plan analyzer. (ORM-D-a and ORM-D-b stay deterministic.)
- **ORM-I DTO-shape refinement.** "A `...Dto` that *still exposes entity-typed navigation properties*" needs type resolution across the DTO graph (a name ending `Dto` is not proof it is flat). The **raw-entity / `List<Entity>` return** sub-predicate stays deterministic; the DTO-holds-navigations sub-predicate is quarantined pending the same analyzer.

**Exact greps (replace described predicates; one command → one result). All run under `$SRC`, `--type cs` unless stated, excluding `obj`/`bin`/test projects (`| grep -vi "/obj/\|/bin/\|\.tests\?/"`).**
- **ORM-C high-value token (materialising, unfiltered):** `rg -n "GetAllListAsync\(\)|\.GetAllList\(\)|GetAllList\(\s*[^)]*=>\s*[^)]*\)"` — flag a hit with no entity-scoping predicate, or one that **ignores an id parameter it was given**. Bounded small fixed-lookup loads (config tables) are excluded by reading the entity.
- **ORM-D-a fetch-all-then-filter:** a `GetAllListAsync()`/`GetAllList()` hit (above) followed by an **in-memory** `.Where(`/`.Any(`/`.FirstOrDefault(`/`.Count(` with no DB predicate.
- **ORM-D-b DB-call-inside-mapper:** `rg -n "CreateMap<|ForMember\("` ∩ a mapping body that resolves a repo/service — `IocManager\.(Instance\.)?Resolve|GetRequiredService|_\w+Repository\.|\.GetAsync\(`.
- **ORM-E custom CRUD base:** `rg -n ":\s*\w*CrudAppService<|:\s*\w*CrudServiceBase<|AsyncCrudAppService|DynamicCrudAppService"` — one finding per match, naming entity `T`. No match → `ORM-E@custom-crud-base=none`.
- **ORM-F-b sequence in save path:** `rg -n "GetNextSequenceNo|new SequenceManager\(|ISessionFactory\.OpenSession|IocManager\.Instance\.Resolve<ISequenceManager>"` inside a Create/Update/Save method body.
- **ORM-G name lookup:** `rg -n "\.Name\s*==|Name\.Contains\(|ToLower\(\)\.Contains\("` ∩ a config-item/template/role/workflow-step resolution **without** a `VersionStatus`/`IsLast`/live filter on the same query.
- **ORM-J read-only discipline (absence grep):** `rg -n "IStatelessSession|SetReadOnly\(true\)|AsNoTracking\(\)"` — **no matches** ⇒ one solution-level finding `ORM-J@sln:readonly-session-discipline` (body carries the count of reporting/PDF/display reads running on the tracking session). Matches present ⇒ assess each reporting read individually.
- **ORM-K cartesian:** `rg -n "\.Fetch\(|FetchMany\(|ThenFetch\(|JoinQueryOver|JoinAlias"` — a single query (same statement chain) fetching **≥2 collection** navigations on one root. One collection fetch is fine. No ≥2-collection query → `ORM-K@none`.
- **ORM-A / ORM-B / ORM-C-markup / ORM-H (form markup):** `rg -n "maxResultCount\s*[:=]\s*(-1|2147483647|800)" ` and `rg -n "\.filter\([^)]*\)\.length|\.items\.length|globalState\.\w+\.items|\.selectedRow|\.tableData"` over form markup **only when `form_markup_in_repo`** — else the fixed `@forms` NOT-ASSESSED record. **Do NOT anchor on `onAfterDataLoad`**: it exists (often empty) on nearly every form — pure noise.

**Anchors (operating-standard §3 — narrowest named symbol, no ordinal, no raw line number).**
- Code finding: `ORM-x@<path>#<Type>.<Member>` (method when the finding is about a method; `#Type` only when genuinely type-wide). Overloads carry `#Type.Member(argTypeList)`.
- **Anchor GRANULARITY is pinned per check — no operator discretion (this closes the `#Type.*` vs `#Type.Member` split):**
  - **Per-METHOD checks — emit one finding per qualifying method, with that method's REAL name** (`#<Type>.<Member>`): **ORM-A, ORM-B, ORM-C, ORM-D, ORM-F, ORM-G, ORM-H (backend-count form), ORM-I, ORM-K.** Eight methods with the defect ⇒ eight findings. **Never collapse a type's methods to one record, and NEVER use a wildcard member such as `#Type.*` — the `.*` form is illegal and must never be emitted** (if a whole type is affected, that is still N per-method records, one per qualifying method).
  - **Type-LEVEL records (bare `#<Type>`, no member):** ONLY `ORM-E@<path>#<Type>` (the custom-CRUD-base inheritance — the class *is* the defect). No other check uses a bare-type anchor for a real code finding.
  - **Solution / fixed / gated anchors** keep their literal fixed tokens (`ORM-J@sln:readonly-session-discipline`, `ORM-E@dynamic-crud`, `@db`, `@forms`, `@telemetry`, `@authz-probe`, `…=none`).
- Solution-wide: the fixed token `sln` — `ORM-J@sln:readonly-session-discipline` (never a module/assembly name).
- Capability-gated dimension: its own fixed anchor — `ORM-A@telemetry`, `ORM-D@telemetry`, `ORM-I@telemetry`, `ORM-C@db`, `ORM-E@db`, `ORM-H@db`, `ORM-E@authz-probe`, `ORM-A@forms`, `ORM-B@forms`, `ORM-C@forms`, `ORM-H@forms`.
- Empty verdict: `ORM-E@custom-crud-base=none`, `ORM-K@none`, `ORM-B@sql-handover=none`, etc.
- Dynamic-CRUD handover: fixed `ORM-E@dynamic-crud` (the framework whole-table surface — a SEC-C handover, Info on the ORM side).
Path normalization is the normalizer's job (repo-relative, `/`, lowercase path, keep `#Member` verbatim); line numbers may appear only in a prose `Where:` field.

---

## ORM-A: Fetching the whole object graph for a display. **impact_class=dos, data_sensitivity=business, RC-over-fetch.**
A list/search returns full entities with every reference and nested object when the screen shows a handful of columns. Every extra column and joined entity is read, serialised and parsed for every row; lists that were instant at 100 rows take seconds at 100,000.
- **INPUT:** enumerate list/search actions — `rg -n "Task<[^>]*>\s+(GetAll|Search|GetList|Query)\w*Async\s*\("`. For each, read the return type and body. Dynamic CRUD / GraphQL calls from forms with no `properties` list are the markup dimension (`ORM-A@forms`, gated).
- **PREDICATE:** a list/search action returns a mapped **entity**, `List<Entity>`/`IEnumerable<Entity>`, OR a DTO that inherits the entity / `FullAuditedEntityDto<>` with no slim hand-projection (no `select new …Dto { … }` / `ProjectTo` limiting columns). A hand-projected flat DTO (e.g. `RatingSheetDto` built field-by-field) is **fine — not a finding**.
- **VERDICT/ANCHOR:** `ORM-A@<path>#<Type>.<Member>` per qualifying action + fixed `ORM-A@telemetry` `NOT-ASSESSED(no-app-insights)` (response-size/duration proof) + fixed `ORM-A@forms` `NOT-ASSESSED(form-markup-not-in-repo)` when markup absent.
- **EVIDENCE:** CODE-ONLY (static); App Insights response-size+duration for the list endpoint → CONFIRMED-IN-LOGS; a live row-count call on a production-representative copy → REPRODUCED.
- **REMEDIATION `PLAN-ORM-A`:** a slim list endpoint/query projecting only displayed fields (ideally in SQL); request `properties` explicitly in forms/table components. *Seen in dispatcher: the incident list returned full incident DTOs; a slim `GetIncidentList` cut the payload drastically.*
- **REGRESSION TEST:** `ListEndpoint_ReturnsSlimProjectionNotEntityGraph_Test` — asserts the list action's response contains only the allow-listed columns and no entity navigation.
- **SEVERITY:** dos × any_authenticated, +business → **Medium**.

## ORM-B: Wildcard search on every field. **impact_class=dos, data_sensitivity=business, RC-non-sargable-search.**
`quickSearch`/"global search" builds `LIKE '%term%'` across every text property. A leading `%` stops SQL Server using an index, so every search reads every row of every searched column; ten columns multiplies that by ten.
- **INPUT:** `rg -n "quickSearch|QuickSearch|\.Contains\(|ToLower\(\)\.Contains\("` (code) and `rg -n "'%'\s*\+|LIKE\s+'%"` over migration/TVF/proc SQL (SQL handover). quickSearch-all-fields in form markup is the `ORM-B@forms` gated dimension.
- **PREDICATE (pinned, emits a record iff ALL true):** the search builds `LIKE '%…%'` over **>1** text field **AND** has **no** explicit field allow-list **AND** has **no** paging/type-ahead bound. If any one fails — paged/type-ahead search, OR ≤2 explicit fields (reachability local_only) — **emit NO `ORM-B@<Type>.<Member>` record** (it is below the raise bar; mention it only in the solution-level ORM-B body prose, never as a finding object, never a "Low" record). This removes the A/B split where one operator emitted a Low record for a paged type-ahead and the other suppressed it. Raw `'%'+@QuickSearch+'%'` in migration SQL → `ORM-B@<path>#<migration>` **handover to SQL** (its own record, not scored under ORM).
- **VERDICT/ANCHOR:** `ORM-B@<path>#<Type>.<Member>` per qualifying search + `ORM-B@sql-handover` (listing the migration sites) + `ORM-B@forms` `NOT-ASSESSED(form-markup-not-in-repo)`.
- **EVIDENCE:** CODE-ONLY; duration + logical reads with `SET STATISTICS IO ON` on a production-representative copy → REPRODUCED.
- **REMEDIATION `PLAN-ORM-B`:** search only the fields users search on (reference number, phone); prefix matches / a dedicated search column or index / full-text search where justified.
- **REGRESSION TEST:** `Search_OnlyIndexedFieldsNoLeadingWildcard_Test`.
- **SEVERITY:** dos × any_authenticated, +business → **Medium**. (A bounded paged type-ahead / ≤2-field search is local_only and, per the pinned predicate, emits **no record at all** — it is not a Low finding.)

## ORM-C: Unbounded queries (no paging, no cap). **impact_class=dos, data_sensitivity=business, RC-unbounded-query.**
The materialising **`GetAllListAsync()`/`GetAllList()`** pulls the whole table into memory and is the pattern that bites (`GetAll()` alone returns `IQueryable` and is usually bounded by a following `.Where`/`.Take` — a weak smell, many benign hits; grep the materialising token first).
- **INPUT:** the ORM-C exact grep above. Also forms/front-end `maxResultCount=-1|2147483647` (gated, `ORM-C@forms`), autocomplete without a `maxResultCount`, dropdowns loading whole tables, reports with no date bound.
- **PREDICATE:** `GetAllListAsync()`/`GetAllList()` with **no** entity-scoping filter — ESPECIALLY one that **ignores an id parameter it was given** (a correctness bug as well as scale, e.g. `GetObjectives(Guid id)` returning every row). A finite-but-too-small client cap (`maxResultCount: 800`) feeding a client-side total under-counts past the cap → also ORM-H. Bounded small fixed-lookup loads are **fine**.
- **VERDICT/ANCHOR:** `ORM-C@<path>#<Type>.<Member>` per hit + fixed `ORM-C@db` `NOT-ASSESSED(starter-data)` (row-count proof) + `ORM-C@forms` `NOT-ASSESSED(form-markup-not-in-repo)`.
- **EVIDENCE:** CODE-ONLY; call the endpoint on a production-representative copy and count rows → REPRODUCED; App Insights row-growth → CONFIRMED-IN-LOGS.
- **REMEDIATION `PLAN-ORM-C`:** paging everywhere, sensible lookup caps, type-ahead search instead of loading everything; scope the query by the id it is given.
- **REGRESSION TEST:** `Query_BoundedAndScoped_Test` — a seeded-large call returns a capped page; a method taking an id returns only that id's rows.
- **SEVERITY:** dos × (any_authenticated hot path → **Medium** | admin_only batch/import path → **Low**), +business.
- **pd-Hcm reference set:** `performancereviewworkflowmanager.cs#PerformanceReviewWorkflowManager.*` (`GetAllListAsync()` in the per-review creation sweep → any_authenticated → **Medium**, also ORM-D-a); `persalhelper.cs#PersalHelper.*` (`GetAllList(f => f.CreationTime < today)` on the resubmit/import path → admin_only → **Low**).

## ORM-D: Loading related records the slow way (N+1, fetch-all-then-filter). **impact_class per sub, data_sensitivity=business, RC-in-memory-filtering.**
Each sub-predicate is its own finding; the Architect groups them at plan time (operating-standard §6), never collapsed at authoring.
- **INPUT/PREDICATES (one finding per hit):**
  - **ORM-D-a `ORM-D@<path>#<Type>.<Member>` (fetch-all-then-filter):** a `GetAllListAsync()`/`GetAllList()` materialise followed by an in-memory `.Where`/`.Any`/`.FirstOrDefault` on a navigation. **impact_class=dos.** Work grows with the whole table.
  - **ORM-D-b `ORM-D@<path>#<MappingProfile>` (DB call inside a mapper):** a repo/service resolved inside AutoMapper `ForMember`/`ResolveUsing` — a hidden N+1 plus a service locator. **impact_class=dos** (higher-impact than a lazy walk).
  - **ORM-D-c `ORM-D@<path>#<MappingProfile>` (per-row lazy dot-walk):** `MapFrom(b => b.Nav.Prop)` / `b.Nav.Other.Prop` applied per row with no `ProjectTo`/fetch plan. **impact_class=maintainability. Tagged `non_deterministic:true`** (quarantined — fetch-plan coverage needs a semantic analyzer).
  - Per-row fetches in form scripts (`Promise.all(items.map(i => http.get(…?id=i.id)))`) → gated with `ORM-A@forms`/markup.
- **VERDICT/ANCHOR:** as above, per hit + fixed `ORM-D@telemetry` `NOT-ASSESSED(no-app-insights)` (per-request SQL-count proof).
- **EVIDENCE:** CODE-ONLY; App Insights dependency count per request (`${CLAUDE_PLUGIN_ROOT}/shared/appinsights-queries.kql` §3 — dozens/hundreds of SQL calls) → CONFIRMED-IN-LOGS; SQL-profiler on a copy → REPRODUCED.
- **REMEDIATION `PLAN-ORM-D`:** filter in the query (`Where` before `ToList`), eager-load/project what's needed (`ProjectTo`/explicit `select`), batch by id list (`id in [...]`); remove service resolution from mappers. *Seen in dispatcher: the crew form fetched each responder separately, and again on save.*
- **REGRESSION TEST:** `DataAccess_NoNPlusOneUnderLoad_Test` — a list call under a seeded set asserts a bounded dependency count (not O(rows×navigations)).
- **SEVERITY:** D-a/D-b dos × any_authenticated, +business → **Medium**; D-c maintainability → **Low** (quarantined).
- **pd-Hcm reference set:** D-a = ORM-C-1 (`performancereviewworkflowmanager.cs#PerformanceReviewWorkflowManager.*`); D-c = `sagovperformancereviewpdfmappingprofile.cs#SaGovPerformanceReviewPdfMappingProfile` and `sagovperformanceagreementpdfmappingprofile.cs#SaGovPerformanceAgreementPdfMappingProfile` (bounded by one doc → Low, quarantined).

## ORM-E: Generic endpoints exposing whole tables. **impact_class=data_exposure_pii, data_sensitivity=popia_special, RC-generic-crud-exposure. → HANDOVER: Security (SEC-C).**
Shesha dynamic CRUD (`/api/dynamic/.../Crud/GetAll`) and `Entities/GetAll` exist for every entity with only "authenticated" access by default. A **custom app service inheriting a CRUD base** re-exposes the same whole-table CRUD on its entity even when the class looks purpose-built — the business rules of the hand-written endpoints do not apply there.
- **INPUT:** the ORM-E custom-base grep above; list the entity each match exposes. Dynamic-CRUD/`Entities/GetAll` is framework-default (always present) and is a **handover**, not an ORM defect.
- **PREDICATE:** a custom service `: *CrudAppService<T>` / `: *CrudServiceBase<T>` / `AsyncCrudAppService` / `DynamicCrudAppService` exposes an entity holding personal/employment/sensitive data → one finding per `T`. No match → `ORM-E@custom-crud-base=none` (empty verdict, Info).
- **VERDICT/ANCHOR:** `ORM-E@<path>#<Type>` per custom base + fixed `ORM-E@dynamic-crud` (framework surface handover to SEC-C, Info) + fixed `ORM-E@authz-probe` `NOT-ASSESSED(no-low-priv-user)` + fixed `ORM-E@db` `NOT-ASSESSED(starter-data)`.
- **EVIDENCE (pinned):** the **custom-base** record `ORM-E@<path>#<Type>` → **VERIFIED-ARTEFACT** (grep artifact of the inheritance). The fixed **`ORM-E@dynamic-crud`** handover record → **CODE-ONLY**, always (it is a forward-looking SEC-C handover: the framework surface's existence is known, but exposure on real data is not observed at static — **never VERIFIED-ARTEFACT** on this record). The restricted-user `Crud/GetAll` count-compare → REPRODUCED (needs `low_priv_account`) → else the authz dimension is `NOT-ASSESSED(no-low-priv-user)`.
- **REMEDIATION `PLAN-ORM-E`:** restrict the dynamic/custom-base endpoints by permission; add global specifications (row-level filters) for scoped entities; see the security division SEC-C (the authorisation angle owns scoring). *Seen in dispatcher: a region-restricted dispatcher listed all 413k incidents and 404k patients.*
- **REGRESSION TEST:** `GenericCrud_RestrictedByPermissionAndScope_Test` — reuses SEC-C's `AuthorizationInventory_NoInheritedOrAnyAuthenticated_Test`.
- **SEVERITY:** data_exposure_pii × any_authenticated, +popia_special → **Critical** (scored under SEC-C once handed over; the ORM-side custom-base record is the detection anchor).
- **pd-Hcm reference:** custom-base angle **correctly silent** — no service inherits a CRUD base → `ORM-E@custom-crud-base=none`; the dynamic-CRUD surface on HCM/Leave/PMDS personal data is the live handover.

## ORM-F: Business logic in the wrong place, and transactions. **impact_class per sub, data_sensitivity=business, RC-transaction-boundary.**
Side effects inside the save path, and validation that runs after irreversible work.
- **INPUT/PREDICATES (one finding per hit):**
  - **ORM-F-a `ORM-F@<path>#<Type>.<Member>` (side effect in save path):** a notification/SMS/webhook/`HttpClient` call inside a Create/Update body (not an after-commit/outbox handler). **impact_class=data_integrity** — a failed side effect makes a saved record look failed → duplicates.
  - **ORM-F-b `ORM-F@<path>#<Type>.<Member>` (sequence on a separate session):** `GetNextSequenceNo`/`new SequenceManager(sessionFactory)` / `ISessionFactory.OpenSession` drawn inside a save path — it commits independently, so a later failed save leaves a **gap**. **impact_class=maintainability** (a sequence gap feeding an external system; confirm gap-tolerance against `$DLL`).
- **VERDICT/ANCHOR:** as above, per hit.
- **EVIDENCE:** CODE-ONLY (F-b: "needs DLL confirm" of the framework session behaviour → VERIFIED-ARTEFACT after decompile); make the side effect fail / the save fail and observe counters → REPRODUCED.
- **REMEDIATION `PLAN-ORM-F`:** run side effects after commit (unit-of-work completed handlers / outbox); take sequence numbers inside the saving unit of work (or confirm the sequence is gap-tolerant); notification failure non-fatal and logged. *Seen in dispatcher: reference numbers drawn in the validator were used up by ~12% of failed creates; a reporter-SMS failure turned a saved incident into an error.*
- **REGRESSION TEST:** `SavePath_SideEffectsAfterCommitAndSequenceInUoW_Test` — a failing side effect still commits the record once; a failing save consumes no sequence number.
- **SEVERITY:** F-a data_integrity × any_authenticated → **High**; F-b maintainability × admin_only → **Low**.
- **pd-Hcm reference:** F-b = `inputfilemanager.cs#InputFileManager.*` (`ISequenceManager` resolved via static `IocManager.Instance.Resolve`, `GetNextSequenceNo("PERSALInputFileGenerationNumber",…)` while building the PERSAL input file) → **Low**, Shesha-team candidate if a framework-session limitation.

## ORM-G: Lookups by name instead of by id. **impact_class=data_integrity, data_sensitivity=business, RC-name-based-lookup.**
Resolving records by display name — especially versioned configuration maintained separately. A rename, spelling difference or merged area silently breaks the link; with no null check the save crashes.
- **INPUT/PREDICATES (one finding per hit):**
  - **ORM-G-a (request-path, crashes on not-found):** `Name ==`/`Name.Contains` resolution in an interactive action with no not-found guard → the save crashes. **reachability any_authenticated.**
  - **ORM-G-b (versioned config/template by Name, no live filter):** `FirstOrDefaultAsync(x => x.Name == "…")` on a `ConfigurationItemBase` type (NotificationType/Channel, `FileTemplateConfiguration`, workflow step) with **no** `VersionStatus==Live`/`IsLast` filter → an arbitrary version is picked. **reachability admin_only** (sender/job/template path).
  - **ORM-G-c (guarded / roles-by-name):** the same lookup but with a clear not-found throw, or a role resolved by name. **reachability local_only.**
- **VERDICT/ANCHOR:** `ORM-G@<path>#<Type>.<Member>` per hit (state which sub).
- **EVIDENCE:** CODE-ONLY; compare QA vs production names for no-match / a create hitting an unmatched one → REPRODUCED; **rename risk from history** = count workflow/form versions containing the name literal (names that changed before will change again).
- **REMEDIATION `PLAN-ORM-G`:** link by id; filter config items by live version / stable id; handle not-found explicitly (save, flag, log); keep reference data in migrations/seeds. *Seen in dispatcher: map areas matched to dispatch areas by name; with no "Out of Province" area in production, out-of-province calls crashed on save and were lost.*
- **REGRESSION TEST:** `Lookup_ByIdAndLiveVersionNotName_Test`.
- **SEVERITY:** G-a data_integrity × any_authenticated → **High**; G-b × admin_only → **Medium**; G-c × local_only → **Low**.
- **pd-Hcm reference set:** G-b = `changeofsupervisornotificationsender.cs#ChangeOfSupervisorNotificationSender.*`, `leaveapplicantnotificationsender.cs#LeaveApplicantNotificationSender.*`, `sagovpmdsnotificationsender.cs#SaGovPmdsNotificationSender.*` (notification config by Name, no version filter → **Medium**); PDF template-by-Name controllers (`workplanpdfcontroller.cs`, `sagovleaveapplicationpdfcontroller.cs`, …) — Qms controllers that throw a clear error on missing template are **G-c → Low**; G-c = `workflowpersonhelper.cs#WorkflowPersonHelper.*`, `sagovleaverequestprocessor.cs#SaGovLeaveRequestProcessor.*` (roles by name).

## ORM-H: A page used as a total. **impact_class=data_integrity, data_sensitivity=business, RC-unbounded-query.**
A script/screen counts one page of results and treats it as the total. Once there are more rows than one page the count is wrong; when it drives a decision (whether a step happens, a sign-off is needed), the wrong branch is taken silently.
- **INPUT:** the ORM-H form-script grep above (gated on `form_markup_in_repo`): `.filter(…).length`, `.items.length`, `.tableData`, `globalState.<x>.items`, `.selectedRow` adjacent to a count/decision variable; check the request's page size and sort order. Also a finite-small client cap (`maxResultCount: 800`) feeding a client-side total (ties ORM-C). **Do NOT anchor on `onAfterDataLoad`** (noise).
- **PREDICATE:** a client-side count of one page (or a capped fetch) drives a branch/decision, with no server-side count. A server-side `CountAsync()` before `Skip/Take` is **fine**.
- **VERDICT/ANCHOR:** `ORM-H@form:<module>/<name>` (or `ORM-H@<path>#<Type>.<Member>` for a backend count) per hit + fixed `ORM-H@forms` `NOT-ASSESSED(form-markup-not-in-repo)` + fixed `ORM-H@db` `NOT-ASSESSED(starter-data)` (seed-past-one-page proof).
- **EVIDENCE:** CODE-ONLY; seed more rows than one page with the decisive row on page 2 and run the journey → REPRODUCED.
- **REMEDIATION `PLAN-ORM-H`:** count on the server (a query/command returning the count) and make the decision there.
- **REGRESSION TEST:** `Count_ComputedServerSideNotFromPage_Test`.
- **SEVERITY:** data_integrity × any_authenticated, +business → **High**.
- **pd-Hcm reference:** correct guard `changeofsupervisorappservice.cs#ChangeOfSupervisorAppService.GetAllPositionsAsync` (server-side `CountAsync()` before Skip/Take) → no finding; form-script counts → `ORM-H@forms` NOT-ASSESSED.

## ORM-I: Lazy loading at serialisation time (returning entities, not DTOs). **impact_class=dos, data_sensitivity=business, RC-over-fetch.**
An action returns a mapped **entity** (or a DTO still holding entity navigations); at JSON serialisation each lazy navigation is touched and NHibernate issues a query per navigation per row — the N+1 that hides in the response pipeline, after the method "finished". Risks a `LazyInitializationException` if the unit of work has closed.
- **INPUT:** `rg -n "Task<[^>]*>\s+\w+Async\s*\("` — read the return type; `rg -n "\[DisableValidation\]"` and raw `GetAll()` returns straight to the client.
- **PREDICATE (deterministic):** a public action returns an **entity**, `List<Entity>` or `IEnumerable<Entity>`. **(quarantined sub):** a `…Dto` that still exposes entity-typed navigation properties — `non_deterministic:true` (needs type resolution; see Quarantine). A flat hand-projected DTO is **fine**.
- **VERDICT/ANCHOR:** `ORM-I@<path>#<Type>.<Member>` per raw-entity-returning action (deterministic) / tagged `non_deterministic:true` for the DTO-shape sub + fixed `ORM-I@telemetry` `NOT-ASSESSED(no-app-insights)`.
- **EVIDENCE:** CODE-ONLY; App Insights dependency count scaling with rows×navigations (`${CLAUDE_PLUGIN_ROOT}/shared/appinsights-queries.kql` §3) → CONFIRMED-IN-LOGS; SQL-profiler on one call → REPRODUCED.
- **REMEDIATION `PLAN-ORM-I`:** return a flat DTO projected in the query (`ProjectTo`/explicit `select`) with only the primitive/id fields the screen needs; never return a tracked entity graph.
- **REGRESSION TEST:** `Action_ReturnsFlatDtoNoLazySerialisation_Test`.
- **SEVERITY:** dos × any_authenticated, +business → **Medium**.
- **pd-Hcm reference:** largely exemplary — public actions return flat hand-projected DTOs (`RatingSheetDto`, `AmendmentDataOutput`, `PersonJobLevelAndPositionDto`); the real serialisation-time exposure is the generic dynamic-CRUD graph → ORM-E/SEC-C.

## ORM-J: Read-only reads on a tracking session; tracked entities in loops. **impact_class=dos, data_sensitivity=business, RC-tracking-session.**
Large read-only queries run on the default dirty-tracking session, and entities loaded one-by-one in a loop on that session. ABP's unit of work auto-flushes dirty-tracked entities at completion: a big read-only result bloats memory, and an accidental property change (or a mutating mapper) causes a **surprise `UPDATE`** on flush.
- **INPUT:** the ORM-J absence grep above (`IStatelessSession`/`SetReadOnly(true)`/`AsNoTracking()`); entity loads (`GetAsync(id)`/`repository.Get(...)`) inside `for`/`foreach` where one batched `id in [...]` query would do.
- **PREDICATE:** **no** read-only session hint anywhere in the backend while reporting/PDF/display reads exist → one solution-level finding. (Matches present ⇒ assess each reporting read; an in-loop per-id load bounded by one record is a **note**, not raised.)
- **VERDICT/ANCHOR:** `ORM-J@sln:readonly-session-discipline` (body carries the count of reporting/display reads on the tracking session).
- **EVIDENCE (pinned):** **CODE-ONLY**, always, on any static/`--quick` run. The finding is a forward-looking DoS/stray-`UPDATE` risk inferred from the absence of read-only discipline; the DoS itself is **not** observed at static, so it is CODE-ONLY — **never VERIFIED-ARTEFACT** (the zero-match grep is the *detection mechanism*, not proof the risk fires). Only memory/row counts on a representative copy, or a logged stray `UPDATE` at flush, lift it to REPRODUCED.
- **REMEDIATION `PLAN-ORM-J`:** read-only queries use a stateless session / `SetReadOnly(true)`; batch per-id loads into one query; keep write-tracking sessions for actual writes.
- **REGRESSION TEST:** `ReadOnlyReads_UseStatelessOrReadOnlySession_Test`.
- **SEVERITY:** dos × any_authenticated, +business → **Medium**.
- **pd-Hcm reference:** `IStatelessSession`/`SetReadOnly`/`AsNoTracking` grep → **no matches** → `ORM-J@sln:readonly-session-discipline` **Medium**; in-loop touches (ORM-D-c, `kraratingmanager.cs`) bounded by one record → noted, not raised.

## ORM-K: Cartesian explosion from fetching multiple sibling collections. **impact_class=dos, data_sensitivity=business, RC-over-fetch.**
Eager-fetching **more than one child collection** of the same root in a single query multiplies rows: N children A × M children B per root. It looks like an N+1 fix but is often slower.
- **INPUT:** the ORM-K grep above.
- **PREDICATE:** a single query (same statement chain) fetches **≥2 collection** navigations on one root (multiple `.Fetch`/`FetchMany`/`ThenFetch` of collections, or several collection joins in one `QueryOver`/Criteria). One collection fetch, or multiple **single-valued reference** fetches, is **fine**.
- **VERDICT/ANCHOR:** `ORM-K@<path>#<Type>.<Member>` per offending query. None → `ORM-K@none` (empty verdict, Info).
- **EVIDENCE:** CODE-ONLY; row count + duration vs a split-query equivalent on a copy → REPRODUCED.
- **REMEDIATION `PLAN-ORM-K`:** fetch one collection per query (split into round-trips), or project to a flat DTO; never multiply two collections in one join.
- **REGRESSION TEST:** `Fetch_SingleCollectionPerQueryNoCartesian_Test`.
- **SEVERITY:** dos × any_authenticated, +business → **Medium**.
- **pd-Hcm reference:** exemplary — every multi-`Fetch` fetches single-valued references only (`workplanpdfcontroller.cs`, `appraisalratingmanager.cs` with a documented fetch plan; collections each take their own query) → `ORM-K@none`.

---

## Handovers
- **Security (SEC-C):** generic dynamic CRUD + `Entities/GetAll` for every entity on personal/employment data (ORM-E / ORM-A / ORM-I whole-graph exposure) — verify permissioned-objects + global specifications. The ORM-E custom-base record is the detection anchor; SEC-C owns scoring.
- **SQL:** leading-wildcard `'%'+@QuickSearch+'%'` in TVF/proc migrations (ORM-B `@sql-handover`).
- **Shesha-team candidate (`${CLAUDE_PLUGIN_ROOT}/shared/templates/shesha-team-report.md`, only after reproduced):** `ISequenceManager` separate-session gap behaviour (ORM-F-b) — a framework-session limitation, never a finding against the system's own developers.

## Not-assessable gaps (fixed NOT-ASSESSED records, operating-standard §1)
- Business form markup in the DB (starter data) ⇒ `ORM-A@forms`, `ORM-B@forms`, `ORM-C@forms`, `ORM-H@forms` `NOT-ASSESSED(form-markup-not-in-repo)`.
- No App Insights ⇒ `ORM-A@telemetry`, `ORM-D@telemetry`, `ORM-I@telemetry` `NOT-ASSESSED(no-app-insights)`.
- Near-empty / non-representative DB ⇒ `ORM-C@db`, `ORM-E@db`, `ORM-H@db` `NOT-ASSESSED(starter-data)`; no low-priv user ⇒ `ORM-E@authz-probe` `NOT-ASSESSED(no-low-priv-user)`. Severities stay forward-looking (CODE-ONLY), scored intrinsically.
