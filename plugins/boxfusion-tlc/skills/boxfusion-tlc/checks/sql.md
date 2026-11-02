# SQL checks

Read-only schema facts and counts only — never row contents, never a value (presence + count + `db:<schema>.<object>`/`#symbol` only; see `references/safety-and-data-access.md`). Synthetic data for any `--deep` reproduction.

**This file obeys `references/operating-standard.md`.** Every check is a decision procedure: **INPUT → PREDICATE (boolean) → VERDICT → ANCHOR**, then **REMEDIATION (plan_id + template) → REGRESSION TEST → SEVERITY INPUTS**. A finding is raised **iff** the predicate is true and an anchor exists. IDs are `SQL-X@<anchor>` (operating-standard §3) — **never** `SQL-X-1/-2`; multiplicity is carried by the anchor (the historic `SQL-C1..C10` labels are now **anchors/vectors**, not check-ids). Severity is scored intrinsically from the operating-standard §5 table (evidence level is a separate axis, not a severity input).

**Run the DBMS-confirm gate first on every system** (below). A PostgreSQL backend changes the whole instrument set.

## Honest split by data source (the core of this file)
Every SQL concern is one of two kinds, and the split is **fixed per check, not per operator**:
- **STATIC-detectable (no database needed, belongs in every run):** raw SQL in app code and migrations (`CreateSQLQuery`/`FromSqlRaw`/`ExecuteSqlRaw`, string-built SQL), the **text of every proc/view/function a migration creates** (read the `CREATE …` body right out of the migration), `Execute.Sql(...)` framework-table writes, hand-run `.sql` scripts in the repo, and FluentMigrator FK/index declarations. These are read-only grep/read → evidence **VERIFIED-ARTEFACT** (the artifact is the committed SQL text) or **CODE-ONLY**, with a `db:`/`#symbol` anchor.
- **DATA-LEVEL (requires a restored database copy):** missing-index measurement, FK-index *reality* (§2), grow-forever *sizes*, DMVs/Query-Store, heaps/GUID-cluster fragmentation, disabled/untrusted constraints (§1), orphans, dead-object dependency sweep (§6), and the **runtime cost** that *proves* any SQL-C anti-pattern. **No restored copy ⇒ each of these is a FIXED `NOT-ASSESSED(no-restored-copy)` anchor — a first-class verdict, never "fine", never silently skipped.** Reproduced only under `--deep` with a copy (upgrades that same anchor from `NOT-ASSESSED` to `REPRODUCED`/`VERIFIED-ARTEFACT`). Never report the SQL area clean on the strength of having run nothing.

`sql/diagnostic-queries.sql` is the DATA-LEVEL instrument. Run it against the **local copy** with `sqlcmd -i <file>` (passing it with `-Q` breaks on the leading comment). On a restored copy, index-usage statistics and missing-index suggestions are **empty** — they only accumulate on the live server; use `SET STATISTICS IO, TIME ON` on production-sized data, or approved production DMV/Query-Store access.

## DBMS-confirm gate (run first — dual-DBMS starters)
A Shesha starter is frequently **dual-DBMS**: a PostgreSQL backup (`*-PostgreSql.backup`) ships beside the `.bacpac`. These checks and `diagnostic-queries.sql` assume **SQL Server** (`sqlcmd`, `sys.*` DMVs, T-SQL).
- **INPUT:** resolve `$DBMS` from the running configuration — `Abp:DbmsType`/`ConnectionStrings` + `DbmsType` in `Web.Host/appsettings*.json`; note which dump files ship at repo root.
- **PREDICATE:** `$DBMS == PostgreSQL` (the *running* copy, not merely a `.backup` that ships).
- **VERDICT/ANCHOR:** if PostgreSQL → every `sys.*`/T-SQL DATA-LEVEL check emits its fixed DATA anchor as `NOT-ASSESSED(postgresql-backend)`; say "SQL-Server tooling N/A" and either port (`psql`, `pg_stat_*`, `information_schema`) under `--deep` or defer. The STATIC checks (SQL-C text scan, SQL-H, raw-SQL grep) **still run** — but T-SQL-only proc syntax may not exist on a PG backend, so read before asserting. A `.backup` shipping alongside a live SQL-Server copy is **not** a PostgreSQL backend — go by `$DBMS`.
- Record `$DBMS` in the finding header verbatim (e.g. `DBMS: SQL Server — DbmsType:"SQLServer"`).

## Framework vs system separation (apply before every verdict)
Objects prefixed `Frwk_`, `Core_`, `entpr_`, `Abp`, `HangFire.`, `workflow.`, `elmah.`, `frwk.` or `sp_admin_` belong to Shesha / ABP / Hangfire / DBA tooling — **not** the system. A hit there is a **Shesha-team-report candidate** (`templates/shesha-team-report.md`), only after it is reviewed and reproduced, and **never a finding against the system's own developers**. System-authored = the module-prefixed tables (`Hcm_`, `Leave_`, `SaGov_`, `Pmds_`, `Qms_`, …) and the `dbo.sp_*/fn_*/vw_*` domain objects.

**Version note — framework table/schema names move between releases (`references/framework-standards.md`, "Framework table and schema names move between versions"):** through 0.44.x they are Pascal/underscore in `dbo` (`Frwk_ConfigurationItems`, `Core_ShaRoles`, `Core_ShaRolePermissions`, `Frwk_PermissionedObjects`, `Frwk_EntityProperties`); **on 0.45.x they moved to a `frwk` schema with snake_case names** (`frwk.configuration_items`, `frwk.roles`, `frwk.role_permissions`, `frwk.entity_properties`, …). Resolve the real names for the version in hand from the decompiled `[Table(..., Schema=…)]` attributes **before** querying or grepping — a scan keyed on the old names finds nothing on 0.45 and wrongly reads as clean.

## Pins (from the manifest, operating-standard §1)
`$SHA` = `$(SheshaVersion)` from `backend/Directory.Build.props`; `$DBMS` = resolved above; `db_copy{present,identity}` = the restored copy (e.g. `pdHcm_DEV_TLC`) — its presence gates every DATA-LEVEL check; `severity_target` = the declared deployment context (score against production, never the copy's near-empty row counts).

## Capability-gating table (operating-standard §1 — absent capability ⇒ first-class fixed NOT-ASSESSED anchor, never a silent pass)
| Capability absent | Dimensions that become `NOT-ASSESSED(reason)` |
|---|---|
| `db_copy` (no restored copy) | SQL-A `@dmv:missing-index`; SQL-B `@dmv:fk-index`; SQL-D `@dmv:heaps-guid-cluster`; SQL-E `@dmv:table-sizes`; SQL-F `@dmv:constraints-orphans`; SQL-G `@dmv:dead-sweep`; and every SQL-C `@<vector>@<obj>#cost` runtime-cost record → `NOT-ASSESSED(no-restored-copy)`. The STATIC predicates still run. |
| production DMV / Query-Store access | SQL-A `@dmv:missing-index` (even with a copy — stats are empty) + SQL-E growth-rate → `NOT-ASSESSED(no-prod-dmv)` |
| production engine version | SQL-C `@engine-version-dep` deploy gate → `NOT-ASSESSED(prod-engine-unknown)` (a question for IT: `SELECT @@VERSION, SERVERPROPERTY('Edition')`) |
| SQL-Server DBMS (dual-DBMS runs PostgreSQL) | all `sys.*`/T-SQL DATA-LEVEL checks → `NOT-ASSESSED(postgresql-backend)` (DBMS gate above) |

**All DATA-LEVEL fixed anchors are MANDATORY — every operator emits every one, always**, even when empty, so two runs' NOT-ASSESSED sets match exactly (operating-standard §8). A near-empty starter copy that *is* restored but has no production-sized data still yields `NOT-ASSESSED(no-production-sized-data)` on the volume-dependent dimensions (missing-index, grow-forever sizes, heap forwarded-records, orphan/sentinel counts) — present-but-too-small is still not-assessed, never "fine".

## Enumerated `root_cause` vocabulary (SQL set — closes `fix_order_rank`; never free text)
`RC-sql-missing-index` (SQL-A, SQL-B) · `RC-sql-query-craftsmanship` (SQL-C, all vectors) · `RC-sql-physical-design` (SQL-D) · `RC-sql-unbounded-growth` (SQL-E) · `RC-sql-schema-integrity` (SQL-F) · `RC-sql-dead-objects` (SQL-G) · `RC-sql-config-outside-release-path` (SQL-H). `fix_order_rank` is then a pure function of {severity, root_cause, anchor}. **(Shared-file addition — these ids must be added to operating-standard §3's vocabulary; see notes.)**

## Anchor forms used here (extend operating-standard §3)
| Target | Form | Example |
|---|---|---|
| Database object (proc/view/function/table) | `db:<schema>.<object>` | `db:dbo.vw_sagov_employeelistdashboard` |
| Raw SQL in app code | `<path>#<Type>.<Member>` | `src/.../persalimportappservice.cs#PersalImportAppService.SyncAsync` |
| Migration class | `<path>#<MigrationClass>` | `.../migrations/m20260825094500.cs#M20260825094500` |
| Solution-level ratio/count | `sln:<token>` | `sql-c@sln:nolock-migrations=11` |
| Fixed data-level / empty-verdict | `dmv:<name>` / `@<vector>=none` | `sql-a@dmv:missing-index`, `sql-c@sentinel-return=none` |

**A `sln:<token>=<n>` (or `=<n>/<N>`) tally/ratio record is a context METRIC, not a scored finding — severity is ALWAYS `Info`, `plan_id=null`, and `evidence_level=VERIFIED-ARTEFACT` (a measured count is an artifact; never CODE-ONLY).** The scored finding, if the metric implies one, is carried by the per-object/per-migration record, never by the tally. **Every tally's `<n>` comes from a single pinned command so both operators get the identical number** — the commands are pinned at each tally's definition (`sln:nolock-migrations`, `sln:execute-sql-migrations`, `sln:db-name-guards`).
**Anchor the DB object, not the migration that created it** — a view re-created by a later migration (e.g. `vw_SaGov_EmployeeListDashboard` re-created by `M20261027133643`) keeps the stable `db:dbo.vw_sagov_employeelistdashboard` anchor; anchoring at the migration drifts between runs. Path part lowercased per §3; the schema/object after `db:` is lowercased (SQL identifiers are case-insensitive) — keep C# identifiers after `#` verbatim.

## Fixed severity-inputs (impact_class + data_sensitivity are FIXED properties of the check/vector; reachability resolves from the grid — author these exactly)
| Check / SQL-C vector | impact_class | data_sensitivity | reachability → band |
|---|---|---|---|
| SQL-A missing index | dos | none | any_authenticated → Low |
| SQL-B FK without index | dos | none | any_authenticated → Low |
| SQL-C `leading-wildcard` | dos | none | any_authenticated → Low |
| SQL-C `function-on-column` | dos | none | any_authenticated → Low |
| SQL-C `scalar-udf-per-row` | dos | none | any_authenticated → Low |
| SQL-C `cursor-while` | dos | none | any_authenticated → Low |
| SQL-C `catch-all-where` | dos | none | any_authenticated → Low |
| SQL-C `select-star` | maintainability | none | any → Low |
| SQL-C `engine-version-dep` | maintainability | none | local_only → Low |
| SQL-C `implicit-conversion` | data_integrity | business | any_authenticated → High |
| SQL-C `nolock` | data_integrity | business | any_authenticated → High |
| SQL-C `missing-softdelete-filter` | data_integrity | business | any_authenticated → High |
| SQL-C `groupby-hiding-dup` | data_integrity | business | any_authenticated → High |
| SQL-C `sentinel-return` | data_integrity | business | any_authenticated → High |
| SQL-C `reflist-by-name` | data_integrity | business | any_authenticated → High |
| SQL-C `dynamic-sql-concat` | data_integrity | business | any_authenticated → High (if the target string is request-sourced, it is SEC-G injection — SEC-G wins, do not double-list) |
| SQL-C `missing-nocount-try` | data_integrity | business | admin_only → Medium |
| SQL-C `unfiltered-mass-write` | data_integrity | business | admin_only → Medium |
| SQL-D heaps / GUID cluster | dos | none | any_authenticated → Low |
| SQL-E grow-forever | dos | none | any_authenticated → Low |
| SQL-F schema integrity | data_integrity | business | local_only → Low |
| SQL-G dead object | maintainability | none | local_only → Low |
| SQL-H config outside release path | maintainability | none | local_only → Low |
Empty-verdict (`@<vector>=none`) and `NOT-ASSESSED(reason)` records: fixed `severity: "Info"`, evidence `CODE-ONLY`/`NOT-ASSESSED` (operating-standard §5). Info/NOT-ASSESSED records never enter `fix_order_rank`.

## Exact commands (replace described predicates; one command → one result)
- **Raw SQL in app code (SQL-C `dynamic-sql-concat` seam + positive):** `rg -n "CreateSQLQuery|FromSqlRaw|ExecuteSqlRaw|ExecuteSqlInterpolated" backend/src --type cs`; for each site, PREDICATE-hit = the SQL string is built with `+` concat or `$"…{…}…"` interpolation of a non-parameter value; PREDICATE-clean = value passed via `.SetParameter(...)`/interpolated-`FromSql` parameter. All-clean → `SQL-C@dynamic-sql-concat=none` (a positive, VERIFIED-ARTEFACT).
- **Proc/view/function text (SQL-C static set):** `rg -niU "CREATE +(OR ALTER +)?(PROC|PROCEDURE|VIEW|FUNCTION)" backend/src` → read each `CREATE …` body from the migration and apply the per-vector predicate. When `db_copy` present, corroborate with `diagnostic-queries.sql` §4 (anti-pattern column scan over `sys.sql_modules`) + §4 scalar-UDF list — same VERIFIED-ARTEFACT set; §4's `catch_all_where` column is noisy, review each hit.
- **Execute.Sql framework-table writes (SQL-H):** `rg -n "Execute\.Sql\(" backend/src --type cs` then, over those, `rg -n "Frwk_|Core_Sha|Core_[A-Z]|AbpPermission|Frwk_PermissionedObjects|frwk\.(roles|role_permissions|configuration_items|permissioned)" ` — **grep `Core_Sha*` and the `frwk.*` snake_case equivalents, not `Frwk_` alone**, or every permission-grant migration is missed (the richest instance of the pattern). Separate `Core_ShaRoles … WITH (NOLOCK)` *reads* (SQL-C `nolock`) from genuine config *writes*.
- **Hand-run `.sql` scripts (SQL-H):** `rg --files backend -g '*.sql'` → any loose `.sql` not shipped as an embedded migration resource is a drift candidate.
- **Migration shape (SQL-H context):** count `OneWayMigration` vs reversible; `rg -n "DB_NAME\(\)" backend/src` for the database-name guard (0 guards = reported, mitigated by `VersionInfo` tracking).

---

## SQL-A: Missing indexes for real query patterns. **DATA-LEVEL. impact_class=dos, data_sensitivity=none, root_cause=RC-sql-missing-index.**
Without a suitable index SQL Server reads the whole table — fine at 1k rows, painful at 1M.
- **INPUT (DATA-LEVEL):** map frequent queries (App Insights dependencies, stored procedures, ORM filters) to the columns in their `WHERE`/`JOIN`/`ORDER BY`; `diagnostic-queries.sql` §7 for tables >100k rows; with approved production DMV access, `sys.dm_db_missing_index_*` (§9) as **hints, not orders**.
- **PREDICATE:** a table >100k rows is filtered/joined/ordered on a column that leads no index. **Requires `db_copy` with production-sized data.**
- **VERDICT/ANCHOR:** per table/column `SQL-A@db:<schema>.<table>#<column>`; **always also emit the fixed `SQL-A@dmv:missing-index` record** = `NOT-ASSESSED(no-restored-copy)` under `--static`, `NOT-ASSESSED(no-prod-dmv)`/`NOT-ASSESSED(no-production-sized-data)` on a near-empty copy, `REPRODUCED` under `--deep` with measured reads.
- **EVIDENCE:** `--deep` logical-reads-before/after inside a rolled-back transaction → REPRODUCED; otherwise `NOT-ASSESSED(…)`.
- **REMEDIATION `PLAN-SQL-A`:** a migration adding the index (ONLINE where the edition allows, else off-peak) with INCLUDE columns for covering where justified.
- **REGRESSION TEST:** `Index_LogicalReadsWithinBudget_Test` — the mapped query's logical reads stay under budget on seeded production-sized data.
- **SEVERITY:** dos × any_authenticated, none → **Low** (Info while `NOT-ASSESSED`).

## SQL-B: Foreign keys without an index. **DATA-LEVEL authoritative (§2) + STATIC spot-check. impact_class=dos, data_sensitivity=none, root_cause=RC-sql-missing-index.**
Joins/deletes on the child side scan the table; deleting a parent scans every child.
- **INPUT:** authoritative = `diagnostic-queries.sql` §2 (FK columns that lead no index, with row counts) — **DATA-LEVEL**. STATIC spot-check = FluentMigrator FK declarations (`.ForeignKey(`/`WithForeignKey`) in a migration with no matching `.Index(`/`CreateIndex` on that column — a CODE-ONLY hint only.
- **PREDICATE:** a **system** (non-framework, non-audit) FK column leads no index. **Exclude the 4 framework audit/tenant columns** (`CreatorUserId`/`LastModifierUserId`/`DeleterUserId`/`TenantId`) and framework tables — those are a Shesha-team candidate, not a system finding.
- **VERDICT/ANCHOR:** per system FK `SQL-B@db:<schema>.<table>#<fkcolumn>`; **always emit the fixed `SQL-B@dmv:fk-index` record** `NOT-ASSESSED(no-restored-copy)` under `--static`, `VERIFIED-ARTEFACT`/`REPRODUCED` with the copy. **Under `--static` this fixed `@dmv:fk-index` record is the ONLY SQL-B output — do NOT also emit `SQL-B@none`** (the FK check is DATA-LEVEL; with no copy it is not-assessed, not "clean", so there is no empty-verdict record). (pd-Hcm: §2 ~600 rows, all audit-column or framework — `frwk_application_startup_assemblies.module_id`, `entpr_AccountInvitations` — **no system business FK affected**.)
- **EVIDENCE:** §2 on the copy → VERIFIED-ARTEFACT; `--deep` join/delete read-cost → REPRODUCED; no copy → `NOT-ASSESSED(no-restored-copy)`.
- **REMEDIATION `PLAN-SQL-B`:** index the FK columns actually joined or filtered on — not blindly every one.
- **REGRESSION TEST:** `ForeignKeys_JoinedColumnsIndexed_Test`.
- **SEVERITY:** dos × any_authenticated, none → **Low** (Info while `NOT-ASSESSED`).

## SQL-C: Poorly written stored procedures, functions and raw SQL. **Presence STATIC (VERIFIED-ARTEFACT); runtime cost DATA-LEVEL. Each vector is its own finding; emit a verdict line per vector even when empty (`SQL-C@<vector>=none`). root_cause=RC-sql-query-craftsmanship.**
Fixed vector set (16): `leading-wildcard · function-on-column · implicit-conversion · scalar-udf-per-row · cursor-while · select-star · nolock · dynamic-sql-concat · catch-all-where · missing-softdelete-filter · unfiltered-mass-write · groupby-hiding-dup · missing-nocount-try · engine-version-dep · sentinel-return · reflist-by-name`.

| Vector | PREDICATE (read the proc/view/function/raw-SQL text) | Why it hurts |
|---|---|---|
| `leading-wildcard` | `LIKE '%…'` / `LIKE '%…%'` on a column | no index usable; every row read |
| `function-on-column` | `CONVERT/ISNULL/LOWER(Col) = …` in `WHERE`/`JOIN` | non-sargable; index ignored |
| `implicit-conversion` | `nvarchar`↔`varchar` / `datetime`↔`datetime2` param vs column type mismatch | index ignored **and** wrong results at boundaries |
| `scalar-udf-per-row` | a scalar UDF (`type='FN'`) called in `SELECT`/`WHERE` over many rows | runs once per row; serial on older engines |
| `cursor-while` | `CURSOR` or `WHILE` row-by-row | orders slower than set-based; longer locks |
| `select-star` | `SELECT *` in a proc/view | unneeded columns; breaks on column change |
| `nolock` | `WITH (NOLOCK)` / `READ UNCOMMITTED` in a correctness-sensitive read | dirty reads — wrong counts/duplicates/missing rows |
| `dynamic-sql-concat` | dynamic SQL built by string concat / interpolation (not `sp_executesql` parameters) — **scanned in BOTH app-code raw-SQL AND proc/function bodies** (see pinned predicate below) | plan-cache bloat; injection if request-sourced (→ SEC-G) |
| `catch-all-where` | `(@p IS NULL OR Col=@p)` across many params, no `OPTION(RECOMPILE)` | one bad plan for every combination |
| `missing-softdelete-filter` | a query over a soft-delete table with no `IsDeleted = 0` | deleted data shows up |
| `unfiltered-mass-write` | `UPDATE`/`DELETE` with no selective `WHERE` (rewrites every row) | mass change + lock storm |
| `groupby-hiding-dup` | `GROUP BY`/`DISTINCT` used to hide join duplication | wrong results, slow |
| `missing-nocount-try` | a **write-side** proc (≥1 `INSERT`/`UPDATE`/`DELETE`/`MERGE`) with **no `BEGIN TRY`** wrapping (see pinned predicate — `SET NOCOUNT` absence alone does NOT trigger it) | partial updates on failure |
| `engine-version-dep` | `STRING_AGG`/`TRIM`/`OPENJSON` etc. without checking the production **engine** version (needs 2017+; compat level does not gate it) | deploy failure on an older engine |
| `sentinel-return` | a lookup function returning a sentinel (`-1`,`'INVALID'`) callers then store | bad values saved silently instead of an error |
| `reflist-by-name` | a `Frwk_GetRefListItem`-style lookup by list **name** that ignores the module | finds nothing / the wrong list → returns the sentinel |

- **INPUT:** the two exact scans above (raw-SQL grep + `CREATE PROC/VIEW/FUNCTION` text read; `diagnostic-queries.sql` §4 column scan + scalar-UDF list when `db_copy` present). Apply framework-vs-system separation to every hit.
- **Pinned object enumeration (both operators enumerate the IDENTICAL set):** the static object set = every `CREATE (OR ALTER) PROC|PROCEDURE|VIEW|FUNCTION [schema.]<name>` found by `rg -niU "CREATE +(OR ALTER +)?(PROC|PROCEDURE|VIEW|FUNCTION)\s+(\[?(\w+)\]?\.)?\[?(\w+)\]?" backend/src` (migration `Execute.Sql` bodies and `.sql` files) — **capture the schema** (the group before the `.`); when the CREATE names no schema the schema is `dbo`. The anchor is `db:<schema-lowercased>.<name-lowercased>` for the LATEST create (an object re-created by a later migration keeps the one `db:` anchor — never one per migration). **"LATEST create" is pinned by migration timestamp: sort every migration that creates the object by its `M<UTC>` class/file name descending (lexicographic = chronological) and read ONLY the highest one's body for the vector scan** — scanning an older version (or concatenating versions) is the cause of two operators attributing `function-on-column`/`select-star`/etc. to different objects. Each vector regex in the table below is applied to **every** enumerated object's latest body and a finding emitted for **every** (vector, object) match — no operator scans a subset. **A CREATE that appears only inside another object's dynamic-SQL string (`EXEC(@sql)` / an `@sql = @sql + '…CREATE…'` build) is NOT separately enumerated** — that text belongs to the enclosing proc's body, and any vector hit in it attributes to the enclosing proc, not the nested object. A **system** object is one whose **`<schema>.<name>` matches NONE** of the framework patterns (see the exact rule below) — crucially an object in the **`workflow` schema** (e.g. `workflow.vw_my_items`) is a **framework** object and is excluded, so the schema must never be dropped/assumed `dbo`. Apply each vector predicate to each system object's latest body.
- **Pinned EXACT predicates for the two vectors that otherwise diverge:**
  - **`missing-nocount-try`** raises **iff** the object is a proc whose latest body contains **≥1 data-modifying statement** (`rg -ni "\b(INSERT|UPDATE|DELETE|MERGE)\b"` matches in the body) **AND** the body contains **no `BEGIN TRY`** (`rg -ni "BEGIN\s+TRY"` = 0). `SET NOCOUNT` presence/absence is **irrelevant** to the trigger (despite the vector name). A read-only proc (no DML), or a write proc that has `BEGIN TRY`, does **not** raise. One finding per qualifying proc `SQL-C@missing-nocount-try@db:dbo.<proc>`. (This removes the A=4/B=28 split: B was flagging every proc missing `SET NOCOUNT`; the real risk is a write proc with no TRY.)
  - **`dynamic-sql-concat`** is scanned in **two places**, both required: (1) **app code** — the raw-SQL grep sites where the SQL string is built with `+`/`$"…{…}"` of a non-parameter value; (2) **proc/function bodies**. **EXACT proc trigger (removes the GET-vs-CREATE split):** a proc body raises iff it contains **`EXEC\s*\(\s*@\w+`** — i.e. it executes a variable (`EXEC(@sql)`) that is built by concatenation. A proc using **`sp_executesql`** raises **only** if the statement variable is assigned with `+` concatenation **AND** the `sp_executesql` call has **no parameter-definition argument** (`rg` for `sp_executesql\s+@\w+\s*,\s*N?'` ⇒ **clean**, it is parameterised). A fully parameterised `sp_executesql @stmt, N'@p int', @p=…` is **clean** regardless of how `@stmt` was built from literals. (So `sp_sagov_createperformancemanagementdashboard` with `EXEC(@sql)` raises; `sp_sagov_getperformancemanagementdashboard` with parameterised `sp_executesql @stmt,@paramDefs` is clean.) Emit one finding per qualifying site (`@db:<schema>.<obj>` for a proc, `@<path>#<Type>.<Member>` for app code). Emit `SQL-C@dynamic-sql-concat=none` **only when BOTH app code and every proc body are clean**.
- **EXACT per-vector grep (run each over every enumerated system object's latest body — one finding per object that matches, anchor `SQL-C@<vector>@db:dbo.<object>`, unless the vector's own anchor rule below says otherwise). Both operators run the identical command set, so the match set is identical:**
  | Vector | EXACT match (case-insensitive, over the object body) | Anchor |
  |---|---|---|
  | `leading-wildcard` | `LIKE\s*'%` | the object containing it |
  | `function-on-column` | the PURE regex `\b(CONVERT|CAST|ISNULL|LOWER|UPPER|LTRIM|RTRIM|SUBSTRING|LEFT|RIGHT|YEAR|MONTH|DATEPART)\s*\(\s*\w+\.?\w*\s*\)?\s*(=\|>\|<\|LIKE\|IN)\b` matching **anywhere** in the object body — **do NOT add a "must be in a WHERE/JOIN/ON clause" qualifier** (deciding the clause needs SQL parsing and split the operators; the trailing comparison operator already implies a predicate context). One finding per object whose latest body matches. | the object containing it |
  | `scalar-udf-per-row` | — (special, see below) | **the scalar UDF `db:dbo.<fn>`, NOT the caller** |
  | `cursor-while` | `\bDECLARE\s+\w+\s+CURSOR\b` or `\bWHILE\s+@` | the object |
  | `select-star` | `SELECT\s+\*` | the object |
  | `nolock` | `WITH\s*\(\s*NOLOCK\s*\)` or `READ\s+UNCOMMITTED` | the object. **Always emit the migration tally** `SQL-C@nolock@sln:nolock-migrations=<n>` (Info, both operators every run) where `<n>` = `rg -li "WITH\s*\(\s*NOLOCK" backend/src --type cs -g "**/[Mm]igrations/**" | wc -l` (**case-insensitive dir glob `[Mm]igrations` — the repo dir is `Migrations`, so a lowercase-only `migrations` glob wrongly returns 0**; identical command ⇒ identical count); migration `NOLOCK` reads collapse into this tally, never per-file findings |
  | `catch-all-where` | `\(\s*@\w+\s+IS\s+NULL\s+OR\b` | the object |
  | `missing-softdelete-filter` | — (DATA-LEVEL, needs schema; static → `SQL-C@missing-softdelete-filter=none` unless a soft-delete column is visibly filtered-absent in a scanned body) | the object |
  | `groupby-hiding-dup` | **NON-DETERMINISTIC — quarantined.** `GROUP BY`/`DISTINCT` + `JOIN` is a very noisy signal (dozens of legitimate aggregations match); proving the `GROUP BY` actually *hides* join fan-out needs row-level corroboration (DATA-LEVEL) or clone analysis a grep cannot do. Emit candidates tagged `non_deterministic:true` (dropped from the diff); the deterministic replacement is a row-count-vs-distinct-count check under `--deep`. On `--static` with no copy, emit the single `SQL-C@groupby-hiding-dup=none` fixed record (Info). | — (ND) |
  | `missing-nocount-try` | (pinned above: ≥1 DML AND no `BEGIN TRY`) | the proc |
  | `dynamic-sql-concat` | (pinned above: app code + proc bodies) | per site |
  | `engine-version-dep` | `\b(STRING_AGG|TRIM|OPENJSON|STRING_SPLIT|CONCAT_WS)\s*\(` | the object |
  | `implicit-conversion` | — (DATA-LEVEL type comparison; static → `=none` unless a literal `nvarchar`/`varchar` vs typed-column compare is visible) | the object |
  | `sentinel-return` | a `FUNCTION` body with `RETURN\s+(-1|'INVALID'|'?UNKNOWN'?)` | the function |
  | `reflist-by-name` | `ci\.Name\s*=\s*@\w+` without a module/namespace `AND` guard | the function |
  **`scalar-udf-per-row` (special, anchor the UDF):** enumerate scalar UDFs = `CREATE (OR ALTER) FUNCTION <name> … RETURNS <scalar-type>` (RETURNS a scalar, not `TABLE`). For each scalar UDF, grep its bare name across **all** proc/view bodies; if it appears in ≥1 `SELECT`/`WHERE`/`JOIN` of another object → emit **one** finding `SQL-C@scalar-udf-per-row@db:dbo.<fn>` (anchor the UDF, never the calling view — that was the A-anchors-view / B-anchors-fn split). A scalar UDF never called is not a finding.
- **PREDICATE:** a **system** object matches a vector. Framework-object hits (`workflow.vw_*`, `entpr_Sequences_GetNextSequenceNo`, `Frwk_GetRefListItem`, `vw_Frwk_PermissionedObjectsFull`) are Shesha-team candidates, not system findings — list separately. **System-vs-framework is decided by an EXACT rule over `<schema>.<name>` (case-insensitive):** an object is a framework object iff its **schema** is `workflow` (any object in the `workflow` schema) OR its **name** matches `^(Frwk_|vw_Frwk_|entpr_Sequences_|Core_|Abp)` — everything else is a system object. No per-operator judgment; the schema is never dropped (so `workflow.vw_my_items` is framework, excluded).
- **VERDICT/ANCHOR:** `SQL-C@<vector>@db:<schema>.<object>` per system object (raw-SQL-in-code sites anchor `SQL-C@dynamic-sql-concat@<path>#<Type>.<Member>`). For solution-wide counts a `SQL-C@<vector>@sln:<token>=<n>` tally may accompany (e.g. migrations reading `Core_ShaRoles WITH (NOLOCK)`). **The runtime-cost dimension is a separate fixed anchor `SQL-C@<vector>@db:<object>#cost` = `NOT-ASSESSED(no-restored-copy)`/`NOT-ASSESSED(no-production-sized-data)` static, `REPRODUCED` under `--deep`.** Every vector with no hit → `SQL-C@<vector>=none`.
- **EVIDENCE:** the anti-pattern text is **VERIFIED-ARTEFACT** (committed SQL); the runtime cost is `--deep` STATISTICS IO/TIME → REPRODUCED, else `NOT-ASSESSED`. For `sentinel-return`, the stored-sentinel prevalence count is DATA-LEVEL → `NOT-ASSESSED` static.
- **Reference set (pd-Hcm, system-authored — preserve):** `reflist-by-name`+`sentinel-return` → `dbo.fn_SaGov_GetRefListItemValue`, `dbo.fn_entre_GetRefListItemValue` (match `ci.Name=@ns+'.'+@name OR ci.Name=@name` ⇒ any module's Live list; return `-1`). `scalar-udf-per-row` → 21 scalar UDFs incl. `fn_GetActiveAppointment`, `fn_GetPositionWithActiveAppointment`, `fn_SAGov_GetActivePositionName`, `fn_pmds_GetActiveRole`, `fn_HasSuperVisor`, `fn_CalculateReservedBalances`, joined into `vw_SaGov_*`/`sp_SaGov_*`. `nolock` → `vw_sagov_PerformanceAgreementDashboardItems`, `vw_SaGov_PerformanceReviewDashboardItems` + 11 migrations reading `Core_ShaRoles WITH (NOLOCK)`. `cursor-while` → `sp_SaGov_GetPerformanceManagementDashboard` (also `select-star`, `leading-wildcard`, `catch-all-where`), `sp_Pmds_CreateRatingsForPerformanceReview`, `sp_Pmds_CreateKRARatingsForPerformanceAgreement`, `sp_Pmds_CreateKRAsFromPreviousVersion`, `sp_Pmds_CreateKRAsFromStandardKRAs`, `sp_Pmds_CreateScoringsForPerformanceAgreement`. `function-on-column`+`leading-wildcard` → `vw_SaGov_EmployeeListDashboard` (`LOWER(pr.Name) LIKE '%mid%year%'`/`'%annual%'`; migration comments document a dropped 3rd review + `ROW_NUMBER()`+`HASHBYTES('MD5',…)` dedup fan-out), `sp_Pmds_GetKeyActivityTargetsPivot`, `Sp_GetHierarchyDepth`. `dynamic-sql-concat` review → `sp_SaGov_GetMyPmdsItems`, `sp_SaGov_GetScoreSheet`, `sp_Pmds_GetKeyActivityTargetsPivot` (confirm each parameterises). `missing-nocount-try`/writes-without-TRY → `sp_Pmds_PostponeInputTransactions`, `sp_Pmds_UpdateInputTransactionStatuses(FromReport)`, `sp_Pmds_LinkReport2InputTransactions`, `sp_SaGov_ImportLeaveBalanceItem`. `engine-version-dep` (STRING_AGG) → `vw_SaGov_BulkAssessmentApprovalDashboardItems`, `SaGov_FlattenedSaGovLeaveApplications`, `sp_Pmds_GetKeyActivityTargetsPivot`, `vw_sagov_PerformanceAgreementDashboardItems`. `select-star` → `sp_SaGov_GetPerformanceManagementDashboard`, `Leave_FlattenedLeaveApplications`. `dynamic-sql-concat=none` positive → 56 raw-SQL sites across 20 app files all use `.SetParameter(...)`; concat scan found only log-message interpolation. *Also seen in dispatcher:* a proc rewrote the owner of every historical scheduled incident in an area with no status filter (`unfiltered-mass-write`); a function compared a priority field to the wrong type (`implicit-conversion`).
- **REMEDIATION `PLAN-SQL-C`** (per vector): rewrite hot scalar UDFs as inline TVF/set-based; replace cursor/`WHILE` with set-based SQL; key classification on a stable type field (not a name `LIKE`), make the view N-review-capable; remove `NOLOCK` from correctness-sensitive dashboards (use READ COMMITTED SNAPSHOT at DB level for contention); parameterise + whitelist identifiers in dynamic SQL; `OPTION(RECOMPILE)` or parameterised dynamic SQL for catch-all; add `IsDeleted=0`; selective `WHERE` on mass writes; wrap multi-writes in transaction + `SET NOCOUNT ON` + `TRY/CATCH`; enumerate needed columns (no `SELECT *`); **raise/NULL on miss** (no sentinel) and scope reflist lookups by module; confirm the production engine version before shipping `STRING_AGG`/`TRIM`.
- **REGRESSION TEST:** `SqlCraftsmanship_StaticScanClean_Test` — the vector scan over `sys.sql_modules`/migrations asserts the banned-pattern set is empty on the reviewed allow-list; correctness vectors add `Reflist_ModuleScopedRaisesOnMiss_Test` and `Dashboard_CountsCorrectUnderConcurrency_Test`.
- **SEVERITY:** per the fixed per-vector table above (dos/maintainability → Low; data_integrity correctness → High; admin-only write-side → Medium). Runtime-cost records: Info while `NOT-ASSESSED`.

## SQL-D: Clustered key choice and heaps. **DATA-LEVEL. impact_class=dos, data_sensitivity=none, root_cause=RC-sql-physical-design.**
Random GUID clustered keys fragment and bloat every non-clustered index; heaps leave forwarded records.
- **INPUT (DATA-LEVEL):** `diagnostic-queries.sql` §3 (heaps; clustered-on-`uniqueidentifier` tables >100k rows).
- **PREDICATE:** a **system** hot/large table is a heap or GUID-clustered >100k rows. Framework/logging heaps (`elmah.errors`, `elmah.error_refs`) are excluded (Shesha-team candidate).
- **VERDICT/ANCHOR:** per table `SQL-D@db:<schema>.<table>`; fixed `SQL-D@dmv:heaps-guid-cluster` = `NOT-ASSESSED(no-restored-copy)` static, VERIFIED-ARTEFACT with the copy. (pd-Hcm: §3 heaps = `elmah.errors`/`elmah.error_refs` only — **no system business heap, no >100k GUID-clustered table**.)
- **EVIDENCE:** §3 on the copy → VERIFIED-ARTEFACT; fragmentation/forwarded-record cost `--deep` → REPRODUCED; no copy → `NOT-ASSESSED`.
- **REMEDIATION `PLAN-SQL-D`:** usually leave existing GUID keys (costly to change); flag only hot, large tables; prefer sequential GUIDs for new tables; add a clustered index to a hot heap.
- **REGRESSION TEST:** `Schema_NoLargeHeapsOrGuidClusteredHotTables_Test`.
- **SEVERITY:** dos × any_authenticated, none → **Low** (Info while `NOT-ASSESSED`).

## SQL-E: Tables that grow forever. **Sizes DATA-LEVEL; retention-job absence STATIC. impact_class=dos, data_sensitivity=none, root_cause=RC-sql-unbounded-growth.**
Audit/history/heartbeat/notification/job tables grow without limit — backups, restores and queries slow, storage cost rises.
- **INPUT:** `diagnostic-queries.sql` §5 (largest tables) — **DATA-LEVEL**; STATIC = grep the repo for a retention/clean-up job over the known unbounded tables.
- **PREDICATE:** a **system** unbounded table has no retention job. Framework config/log tables (`Frwk_FormConfigurations`, `elmah.errors`, `workflow.workflow_execution_log_items`, `Core_Notifications/Messages`, `AbpEntityChanges(Sets)`, `Core_EntityHistoryEvents`, `Frwk_UserLoginAttempts`) are retention questions for the **Shesha team / BA-PM**, not system findings.
- **VERDICT/ANCHOR:** per system table `SQL-E@db:<schema>.<table>`; **always emit the single fixed-anchor record `SQL-E@retention-job` (bare anchor, never a `=present`/`=none` suffix — the suffix was the A/B split), CODE-ONLY, severity Info, plan_id null, every run** — the body states "clean-up job found" / "none found" per `rg -il "retention|cleanup|purge|DeleteOlderThan|RecurringJob[^;]*[Dd]elete" backend/src` (non-empty/empty), but the **anchor and tuple do not change** either way; fixed `SQL-E@dmv:table-sizes` = `NOT-ASSESSED(no-restored-copy)`/`NOT-ASSESSED(no-production-sized-data)` static, VERIFIED-ARTEFACT with a production-sized copy. (pd-Hcm: all largest tables framework-owned; no retention job found; sizes not assessed on starter data.)
- **EVIDENCE:** §5 sizes → VERIFIED-ARTEFACT (needs copy); growth-rate → `NOT-ASSESSED(no-prod-dmv)`; retention-grep → CODE-ONLY.
- **REMEDIATION `PLAN-SQL-E`:** an agreed retention period per table (BA/PM question) + a batched clean-up job with a supporting index on the date column.
- **REGRESSION TEST:** `Retention_LargeTablesHaveCleanupJob_Test`.
- **SEVERITY:** dos × any_authenticated, none → **Low** (Info while `NOT-ASSESSED`); `SQL-E@retention-job` maintainability → Low.

## SQL-F: Data integrity in the schema. **DATA-LEVEL. impact_class=data_integrity, data_sensitivity=business, root_cause=RC-sql-schema-integrity.**
- **INPUT (DATA-LEVEL):** `diagnostic-queries.sql` §1 (disabled/untrusted FKs & CHECKs, disabled triggers) + orphan checks on the important relationships.
- **PREDICATE:** a **system** constraint is disabled/untrusted or a trigger disabled, or a real orphan exists. On an imported production copy, separate **export artefacts** from real bad data (`references/safety-and-data-access.md`).
- **VERDICT/ANCHOR:** per object `SQL-F@db:<schema>.<object>`; fixed `SQL-F@dmv:constraints-orphans` = `NOT-ASSESSED(no-restored-copy)` static, VERIFIED-ARTEFACT with the copy. (pd-Hcm: §1 zero rows — clean on the copy; orphan checks not meaningful on starter data, re-run on prod copy if approved.)
- **EVIDENCE:** §1/orphan query on the copy → VERIFIED-ARTEFACT; `--deep` on a prod copy confirming a real orphan → REPRODUCED; no copy → `NOT-ASSESSED`.
- **REMEDIATION `PLAN-SQL-F`:** re-enable + `WITH CHECK` every constraint; fix the orphaned rows; re-enable triggers.
- **REGRESSION TEST:** `SchemaIntegrity_AllConstraintsTrustedNoOrphans_Test`.
- **SEVERITY:** data_integrity × local_only, business → **Low** (Info while `NOT-ASSESSED`).

## SQL-G: Dead objects. **Naming-duplicate STATIC; dependency sweep DATA-LEVEL. impact_class=maintainability, data_sensitivity=none, root_cause=RC-sql-dead-objects.**
- **INPUT:** STATIC = grep for `…Old`/`…Backup`/`…_v2` object names and for callers of each object name in code. DATA-LEVEL = `diagnostic-queries.sql` §6 (`sys.sql_expression_dependencies`) for in-DB dependants.
- **PREDICATE:** a **system** proc/view/function has no code caller **and** no DB dependant **and** (BA-confirmed) no external caller (reports/integrations outside the repo). ORM-mapped views (appearing in §6) are excluded before calling them dead.
- **VERDICT/ANCHOR:** naming duplicates → `SQL-G@db:<schema>.<object>` (CODE-ONLY, STATIC); the definitive sweep → fixed `SQL-G@dmv:dead-sweep` = `NOT-ASSESSED(no-restored-copy)` static, and `NOT-ASSESSED(external-callers-unconfirmed)` even with a copy until the BA rules out external callers. (pd-Hcm: ~90 modules with no in-DB dependants are expected — called via raw SQL / ORM views; top candidates spot-checked as code-referenced; no `…Old/…Backup/…_v2` duplicates seen.)
- **EVIDENCE:** naming-grep → CODE-ONLY; §6 on the copy → VERIFIED-ARTEFACT; the "truly dead" conclusion → `NOT-ASSESSED` until external callers excluded.
- **REMEDIATION `PLAN-SQL-G`:** drop in a migration **after** confirming no callers, including reports and integrations outside the repo (a BA question).
- **REGRESSION TEST:** `DeadObjects_NoUnreferencedModules_Test`.
- **SEVERITY:** maintainability → **Low** (Info while `NOT-ASSESSED`).

## SQL-H: Configuration and repairs outside the framework's release path. **STATIC. impact_class=maintainability, data_sensitivity=none, root_cause=RC-sql-config-outside-release-path.**
- **INPUT (STATIC):** (i) `rg -n "Execute\.Sql\(" backend/src --type cs` then filter to framework-config tables — **grep `Core_Sha*` (roles/permissions) and `Core_*`/`Frwk_*` config tables and their 0.45 `frwk.*` snake_case equivalents, not `Frwk_` alone** (a `Frwk_`-only grep misses every permission-grant migration). (ii) Loose `.sql` scripts (`rg --files backend -g '*.sql'`) applied by hand → environment drift. (iii) Each migration's `DB_NAME()` guard and idempotency (`WHERE NOT EXISTS`); `OneWayMigration` vs reversible count. (iv) Hand-run-script-vs-`VersionInfo` drift (which object a repo `.sql` creates, whether any migration applies it) — the *object-exists-and-matches* part is DATA-LEVEL → a `SQL-H@drift` `NOT-ASSESSED(no-restored-copy)` sub-record.
- **PREDICATE (EXACT — both operators emit the identical per-migration set):** the config-write migration set = every file matched by `rg -lU "Execute\.Sql" backend/src --type cs` whose body also matches `rg -li "(INSERT|UPDATE|DELETE)[^;]*(Frwk_ConfigurationItems|Core_ShaRoles|Core_ShaRolePermissions|Frwk_PermissionedObjects|frwk\.(configuration_items|roles|role_permissions|permissioned))"` — i.e. an `Execute.Sql` that **writes** a framework config/permission/role table (a read-side `SELECT`/`JOIN`/`VIEW` over those tables is NOT a hit). Emit **one finding per matching migration** `SQL-H@<path>#<MigrationClass>` (both operators emit every match — do not drop any; pd-Hcm's `M20260825094500` INSERT into `Frwk_ConfigurationItems` is always emitted). Also raise per loose hand-run `.sql` repair, and note any repair script with no DB-name/idempotency guard.
- **VERDICT/ANCHOR:** per migration `SQL-H@<path>#<MigrationClass>`; per loose script `SQL-H@<path>`; two solution tallies with **pinned count commands (both operators identical)** — `SQL-H@sln:execute-sql-migrations=<n>` where `<n>` = `rg -c "Execute\.Sql\(" backend/src --type cs | awk -F: '{s+=$2} END{print s+0}'` (total `Execute.Sql(` CALLS, not migration-class count), and `SQL-H@sln:db-name-guards=<g>/<n>` where `<g>` = `rg -c "DB_NAME\(\)" backend/src --type cs | awk -F: '{s+=$2} END{print s+0}'` and `<n>` is the **same** `execute-sql-migrations` total above (guards over Execute.Sql calls); the drift sub-record `SQL-H@drift` = `NOT-ASSESSED(no-restored-copy)`. (pd-Hcm: 104 `Execute.Sql` migrations; config seeding into `Frwk_ConfigurationItems` by `Shesha.Qms.Domain/.../M20260825094500.cs` guarded `WHERE NOT EXISTS`; **no direct permission/role-table writes**; all 182 classes `OneWayMigration`; 0/104 `DB_NAME()` guards but risk mitigated by `VersionInfo` tracking + no loose `.sql` files.)
- **EVIDENCE:** the `Execute.Sql`/no-guard facts → VERIFIED-ARTEFACT (committed migration text); the drift (object-matches-copy) dimension → `NOT-ASSESSED(no-restored-copy)`/CODE-ONLY.
- **REMEDIATION `PLAN-SQL-H`:** move pure config/permission seeding into `.shaconfig` / `api-permissions-manifest` packages; repairs as idempotent `OneWayMigration`s; interim guard headers (database-name check + idempotency) on any hand-run script as an emergency shortcut. Framework-config writes reviewed-and-reproduced route to `templates/shesha-team-report.md`, never a finding against the system's developers.
- **REGRESSION TEST:** `ReleasePath_NoFrameworkConfigWritesInMigrations_Test`.
- **SEVERITY:** maintainability × local_only, none → **Low**.

---
### `--deep` closers (run when `db_copy` + production-sized data are in the manifest — both static operators are otherwise blind here)
Upgrade each fixed DATA anchor from `NOT-ASSESSED` to `REPRODUCED`/`VERIFIED-ARTEFACT`: SQL-A missing-index measurement (STATISTICS IO/TIME before/after, rolled back) + prod DMV/Query-Store read; SQL-B §2 FK-scan + join/delete cost; SQL-C per-vector runtime cost + stored-sentinel counts; SQL-D §3 heaps/GUID-cluster + forwarded-record cost; SQL-E §5 sizes + growth rate; SQL-F §1 + orphan proof; SQL-G §6 dependency sweep (+ BA external-caller ruling). On PostgreSQL port to `pg_stat_*`/`information_schema` or defer.

### Framework-defect candidates (→ `templates/shesha-team-report.md`, only after reproduced)
Audit-column FKs without indexes (SQL-B framework set); framework heaps/grow-forever tables (`elmah.errors`, `AbpEntityChanges`, `Core_EntityHistoryEvents`, `workflow.workflow_execution_log_items`, `Core_Notifications/Messages`, `Frwk_UserLoginAttempts`); `entpr_Sequences_GetNextSequenceNo` allocator (no TRY/CATCH or NOCOUNT — lost-reference-number area, ties ORM-F-1); `Frwk_GetRefListItem` name-only reflist lookup. A hit on a framework table/behaviour is never a finding against the system's own developers.
