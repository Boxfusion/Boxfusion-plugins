# TLC Operating Standard (v1) — determinism & quality contract

This is the contract **every** TLC agent obeys: the orchestrator, every inspector, the fact-checker, the tester, the fixers. It exists so two operators on the **same repo commit + same declared environment** produce the **same structured findings and the same remediation plan**. Prose may differ; the structured finding and the plan may not.

Loaded by: the Start step (always), every inspector brief (`references/team.md`), and Phase 5. Section numbers are referenced from the check files and the briefs.

## 0. Reproducibility target (the acceptance test)
Two independent runs on the same commit + same manifest MUST produce an **empty diff** on, per finding: `{finding_id, anchor, evidence_level, severity, plan_id}` and on the ordered `fix_order_rank` list. Narrative prose is explicitly **out of the diff surface**. The diff surface is `findings.json` (§8), not the markdown. Convergence on an area = empty diff + no expert finds an un-pinned judgement call.

## 1. Capability Manifest (pin the environment — the #1 variance source)
Every run resolves one machine-readable `manifest.json` **by commands, never by belief**. A capability is `present` iff its resolver command exits 0 and matches. Fields (each carries `{value, source, resolver}`):
- `repo`: `commit_sha` (`git rev-parse HEAD`), `tree_state` ∈ {clean, dirty, zero-commit, not-a-git-repo} (`git status --porcelain`), `dirty_paths_count`.
- `stack`: `shesha` (`Directory.Build.props` `$(SheshaVersion)`), `abp`, `dotnet`, `node`, `dbms[]` (what actually runs; dual-DBMS lists the live one).
- `pinned_dll`: `$DLL` = resolved path of `Shesha.Application/$SHA` from `Web.Host/obj/project.assets.json` (every decompile step targets this exact path, never a guessed cache path).
- `capabilities`: `db_copy{present,identity,canary}`, `backend_running{present,url}`, `low_priv_account{present,reason}`, `app_insights{present}`, `private_nuget_feed{present}`, `private_npm_feed{present}`, `tools{gitleaks,ilspycmd,dotnet,sqlcmd,playwright,sec_analyzer}` (each `{present,version}` via `--version`; `sec_analyzer` = the built `analyzers/BoxfusionTlc.SecAnalyzers` driver that makes SEC-A/SEC-H deterministic — present iff it builds and the target yields a `Compilation`).
- `severity_target` (MANDATORY, declared, e.g. `"production"`): the deployment context severity is scored against — never the copy's data volume.

**Capability rule.** A check whose required capability is absent returns `NOT-ASSESSED(reason)` — a first-class verdict, never a silent pass, never "fine", never a guess, never a weaker-instrument substitution that keeps the strong evidence level (gitleaks absent ⇒ SEC-E recall is `NOT-ASSESSED(no-secret-scanner)`, a seam-grep is a `CODE-ONLY` spot-check; no low-priv account ⇒ the authenticated dimension is `NOT-ASSESSED(no-low-priv-user)`, anonymous/static evidence stands alone).

**Capability-tiered comparison (replaces the false "ASSESSED must be identical" invariant).** Two runs are comparable only at the **intersection** of their manifests. The diff is computed over checks whose required capabilities are present in **both**; within that set `{finding_id, anchor, severity, plan_id}` match exactly and `evidence_level` matches (equal executed capabilities by construction). Checks assessed on only one side go to a `manifest_delta` report, never counted as a diff failure. The harness refuses to pass/fail until it prints the delta, so operators **equalize first** (install gitleaks, restore the same DB, provision a low-priv user).

## 2. Checks are decision procedures, not judgement calls
Every check reads **INPUT** (exact grep/decompile/query/probe) → **PREDICATE** (a deterministic boolean) → **VERDICT** → **EVIDENCE ANCHOR**. A finding is raised **iff** the predicate is true **and** an anchor exists. No anchor ⇒ no finding; no anchor-less "smell". Residual judgement is reduced to an allow-list, a numeric threshold, or a named exception. A check whose finding set can still be swung by sampling is a **determinism defect** — re-engineer it or mark it `NON-DETERMINISTIC` in its check file.

## 3. Stable IDs
`finding_id = <CHECK-ID>@<anchor>`. **CHECK-ID is the lettered check only — no `-1/-2/-3` ordinal suffix, ever** (multiplicity is carried by the anchor; N anchors ⇒ N findings that collapse by identical string). **Anchor is a symbol/role, never a raw line number** (lines drift on reformat). Anchor forms:
| Target | Form | Example |
|---|---|---|
| C# member | `<path>#<Type>.<Member>` | `src/.../persalappservice.cs#PersalAppService.CompletePersalStepStepAsync` |
| C# type | `<path>#<Type>` | `.../hcmpermissionchecker.cs#HcmPermissionChecker` |
| Config value | `<path>#key:<json.path>` | `src/web.host/appsettings.json#key:Authentication.JwtBearer.SecurityKey` |
| HTTP endpoint | `http:<VERB> <route-template>` | `http:GET /api/services/app/Settings/GetValue` |
| Dynamic CRUD | `http:<VERB> /api/dynamic/<Module>/<Entity>/Crud/<op>` | `http:PUT /api/dynamic/SaGov.Leave/SaGovLeaveRequest/Crud/Update` |
| Framework defect | `pkg:<package>@<version>#<Type>.<Member>` | `pkg:Shesha.Application@0.43.38#SettingsAppService.GetValueAsync` |
| Form/workflow | `form:<module>/<name>` (no version) | `form:SaGov.Leave/sagov-approve-leave-application` |
| Dependency | `dep:<ecosystem>:<name>` | `dep:npm:next` |

Path normalization (ordered, total): repo-root-relative → `/` separators → **lowercase the path part** (keep everything after `#` verbatim — C# identifiers and JSON keys are case-sensitive; the `#key:<json.path>` segment is written **exactly as it appears in the file**, e.g. `#key:Authentication.JwtBearer.SecurityKey`, and is never case-folded) → collapse `./` → trim + NFC. Route templates use the attribute template with `{param}` placeholders, path lowercased. Line numbers may appear in a prose `Where:` field but are forbidden in `finding_id`/`anchor`; the normalizer strips `:\d+(-\d+)?`. Identical `finding_id`s collapse to one record with `sources:[...]` — mechanical, not judgement.

**Anchor pins (remove the R2 divergences; non-negotiable):**
- **Narrowest named symbol always.** Anchor at the method, not the type, when the finding is about a method (`#Type.Member`, never `#Type` alone, unless the finding is genuinely type-wide). Enumerate every qualifying member — one finding per member.
- **Solution-level anchors use the fixed token `sln`**, never a module/assembly name: `SEC-C@sln:authorize-ratio=<A>/<N>`, `SEC-C@sln:DefaultEndpointAccess=<value>`. No operator-chosen prefix (`shesha.hcm:` vs `solution:` is a defect).
- **A capability-gated dimension is its own fixed-anchor record**, not a free-text one: `SEC-C@sln:DefaultEndpointAccess`, `SEC-D@probe`, `SEC-E@scanner:gitleaks`, `SEC-H@telemetry`, `SEC-K@forms` — each with `evidence_level=NOT-ASSESSED(reason)` when the capability is absent. Fixed strings so two runs' NOT-ASSESSED sets match exactly.
- **Overloaded members carry a discriminator:** `#Type.Member(argTypeList)` (e.g. `#HcmPermissionChecker.IsGrantedAsync(long,string)`) when a type has >1 member of that name; otherwise `#Type.Member` is fine. A pinned anchor for an overloaded method names the exact overload(s) in scope. The normalizer does not merge two different-signature members.
- **Inherited / not-overridden members anchor at the declaring type:** if the defect is in an abstract/base method that derived classes don't override, anchor at `#BaseType.Member` (one finding per declaring base), and separately, if reachability is per-derived-endpoint, emit `http:` endpoint anchors. State which view a check uses.
- **A check marked `NON-DETERMINISTIC` in its check file emits findings tagged `non_deterministic:true`; the normalizer drops them from the tuple compare** (they are reported to the user but excluded from the acceptance diff until the check is rebuilt).

**Fixed `root_cause` vocabulary (closes the `fix_order_rank` divergence).** `root_cause` is an enumerated id — never free text (`committed-secrets-and-data-in-repo` vs `RC-committed-secrets` is a defect). The registry is the **union of every area's declared set** (each `checks/<area>.md` lists its own ids with their check mapping; a reviewer takes the id from the owning check file, never invents one). `fix_order_rank` is a pure function of {severity, root_cause, anchor} and matches across runs. The registered sets:
- **security** (`checks/security.md`): `RC-no-authz-model` (SEC-C, CODE-G-1, SEC-A, SEC-B, SEC-P, SEC-Q, SEC-S) · `RC-browser-trusted-flow` (SEC-K, CODE-F-1) · `RC-committed-secrets` (SEC-E) · `RC-framework-anonymous-settings` (SEC-I) · `RC-starter-hardening` (SEC-O, SEC-D) · `RC-input-integrity` (SEC-L, SEC-M, SEC-N, SEC-G) · `RC-pii-handling` (SEC-H) · `RC-realtime-messaging` (SEC-F, SEC-J, SEC-R).
- **code** (`checks/code.md`): `RC-error-opacity` · `RC-service-locator-di` · `RC-sync-over-async` · `RC-concurrency` · `RC-side-effect-ordering` · `RC-missing-abstraction` · `RC-frontend-render` · `RC-starter-residue` · `RC-framework-bypass` · `RC-weak-test` · `RC-predicate-correctness`. (CODE-F-1/CODE-G-1 handovers carry the **security** RC.)
- **orm** (`checks/orm-shesha.md`): `RC-over-fetch` · `RC-unbounded-query` · `RC-in-memory-filtering` · `RC-non-sargable-search` · `RC-generic-crud-exposure` · `RC-transaction-boundary` · `RC-name-based-lookup` · `RC-tracking-session`. (The SEC-C handover record uses `RC-no-authz-model`.)
- **sql** (`checks/sql.md`): `RC-sql-missing-index` · `RC-sql-query-craftsmanship` · `RC-sql-physical-design` · `RC-sql-unbounded-growth` · `RC-sql-schema-integrity` · `RC-sql-dead-objects` · `RC-sql-config-outside-release-path`.
- **ops** (`checks/operations.md`, `checks/safety-nets.md`): the `RC-ops-*` set declared there.
- **forms** (`checks/forms.md`): `RC-forms-client-trusted-logic` · `RC-forms-config-drift` · `RC-forms-state-leak` · `RC-forms-wasted-requests` · `RC-forms-script-quality` · `RC-forms-secret-rendering`.

Adding an area never edits the normalizer (it does not hard-code RCs); it only appends a set here and in that area's check file. **Additional anchor forms** used by non-security areas (register with §3's table): `db:<schema>.<object>` (a stable DB-object anchor — a view/proc/function/table; lowercased), `dmv:<name>` (a fixed data-level NOT-ASSESSED anchor). **NOT-ASSESSED `(reason)` tokens** are a documented closed set so two runs match: `no-backend`, `no-low-priv-user`, `no-secret-scanner`, `no-telemetry`, `no-decompiler`, `no-db-copy`, `no-restored-copy`, `no-production-sized-data`, `no-prod-dmv`, `prod-engine-unknown`, `postgresql-backend`, `form-markup-not-in-repo`, `starter-data`, `single-tenant`, `external-callers-unconfirmed`, `handover-source-not-run`, `no-build` (the SEC-A/SEC-H Roslyn analyzer could not obtain a `Compilation`). **Capability-manifest fields** the non-security gates rely on (register with §1): `form_markup_in_repo{present,reason}` and `db_copy{present, identity, representativeness: production-representative|starter}` — both resolved by command, not belief.

## 4. Evidence level (closed enum, total function)
Enum (uppercase, nothing else accepted): `REPRODUCED` · `CONFIRMED-IN-LOGS` · `VERIFIED-ARTEFACT` · `CODE-ONLY` · `DATA-ANOMALY` · `NOT-ASSESSED(reason)`. The level is a lookup on a machine-recorded `execution_class`, taking the **MAX achieved** for the anchor (`REPRODUCED > CONFIRMED-IN-LOGS > VERIFIED-ARTEFACT > CODE-ONLY`):
- live test/HTTP probe with recorded request+response or a failing assertion → `REPRODUCED` (an **anonymous** probe is still `REPRODUCED` — the anon nuance belongs to severity's reachability axis, not the level token; there is no `VERIFIED-LIVE`/`REPRODUCED-anon`).
- production telemetry shows it → `CONFIRMED-IN-LOGS`.
- a tool/scan/decompile/config artifact with an anchor → `VERIFIED-ARTEFACT` (a decompiled attribute is this, unless a live probe also confirmed it → then `REPRODUCED`).
- static source read only → `CODE-ONLY`. Anomalous data, cause unknown → `DATA-ANOMALY`. Required capability absent → `NOT-ASSESSED(reason)` (reason mandatory; lowercase "not assessed" prose is rejected).

## 5. Severity (scored, intrinsic — evidence is NOT an input)
Severity is the intrinsic badness of the behaviour **if real**, scored against the manifest's `severity_target`. Evidence level is a separate tuple axis; an unproven critical is still critical, worded "the configuration allows…" (ground rule 4). Severity is never raised for sequencing.

`severity = base(impact_class, reachability)` then `± data_sensitivity band` (floor Low, ceiling Critical).

**impact_class** {secret_exposure, auth_bypass, data_exposure_pii, data_integrity, dos, info_leak, maintainability} — a fixed property declared per check.
**reachability** {anonymous > any_authenticated > low_priv > admin_only > local_only} — resolved from the probe/manifest.
Base grid:
| impact_class \ reachability | anonymous | any_authenticated | low_priv | admin_only | local_only |
|---|---|---|---|---|---|
| secret_exposure / auth_bypass | Critical | Critical | High | Medium | Low |
| data_exposure_pii / data_integrity | Critical | High | High | Medium | Low |
| dos | High | Medium | Medium | Low | Low |
| info_leak | High | Medium | Low | Low | Low |
| maintainability | Low | Low | Low | Low | Low |
**data_sensitivity modifier** (declared from the entity catalogue, not guessed): `popia_special` (health, ID number, biometrics, security clearance) **+1 band**; `pii_basic`/`business` +0; `none` −1 band.
Every finding prints its three inputs → band. The table is total over the finite axes. **Records with no scored severity — `NOT-ASSESSED(reason)` and empty-verdict `=none` records — carry the fixed token `severity: "Info"`** (never `None`/blank/omitted), so two runs' non-scored records match. The bands, highest→lowest, are `Critical, High, Medium, Low, Info`.

## 6. Remediation is templated
Each check owns, in its check file, a canonical framework-native remediation with a stable `plan_id` and a **named regression test**. The plan-of-action is that template instantiated with the anchor — not free prose. Root-cause grouping and `fix_order_rank` are the Architect's **fixed rule**: group by `root_cause`; order groups by max severity in group then root_cause id; within a group by severity then anchor. `fix_order_rank` is a pure function of the finding set, explained in prose afterwards — never hand-sequenced.

## 7. Agent briefing standard
Every subagent receives, verbatim and non-optional: its exact closed set of CHECK-IDs; the `manifest.json`; the `{repo-commit}` + `{tree-state}`; the output contract (§3 stable-id, §2 anchor-required, §4 level function, §5 severity inputs, §6 plan_id + named test, §8 canonical order, separator-wrapped); the presence-only data-safety sentence inlined verbatim; "partial inputs ⇒ NOT-ASSESSED, never guess"; "never invent ids/levels/severities/remediations outside the templates". Subagents never Write report files — the orchestrator persists (externally, on a propose-only run). The canonical brief template lives in `references/team.md`.

## 8. Output normalization (`findings.json` is the diff surface)
Phase 5 emits `findings.json` alongside the prose report, and **the markdown is derived from it** (one source of truth — this is what makes a finding having two different evidence levels in two files impossible). Record: `finding_id, check_id, area, anchor, evidence_level, execution_class, severity, severity_inputs{impact_class,reachability,data_sensitivity}, plan_id, root_cause, fix_order_rank, sources[], not_assessed_reason`. Canonical sort (total): severity band (Critical→Low) → area → check_id → anchor. Each record carries the manifest's `commit_sha` + a manifest hash; two runs are comparable only when both match. The harness is in `harness/` (`normalize.mjs`, `diff-findings.mjs`, `run-acceptance.ps1`).

## 9. Residual non-determinism (sampling firewall)
The irreducible source is LLM sampling. No field in the canonical tuple may be free-generated — each is the output of a named total function (§3 ID, §4 level tree, §5 table, §6 plan + fix-order). Sampling may then vary prose but not the finding set / level / severity / plan. Any check that cannot populate the tuple by such a function is a determinism defect: re-engineer it, or mark it `NON-DETERMINISTIC` in its check file and exclude it from the diff surface until fixed.
