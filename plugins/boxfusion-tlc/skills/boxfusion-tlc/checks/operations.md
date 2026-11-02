# Operations checks (DevOps engineer)

Source: App Insights (`${CLAUDE_PLUGIN_ROOT}/shared/appinsights-queries.kql`) plus the local database copy — **when the manifest declares them present**. App Insights samples, so when telemetry is read, **always weight by `itemCount`** and sanity-check the first query against database counts. Synthetic users and records only; read-only tooling only; secrets presence-only (never a value).

**This file obeys `${CLAUDE_PLUGIN_ROOT}/shared/operating-standard.md`.** Every check is a decision procedure: **INPUT → PREDICATE (boolean) → VERDICT → ANCHOR**, then **REMEDIATION (plan_id + template) → REGRESSION TEST → SEVERITY INPUTS**. A finding is raised **iff** the predicate is true and an anchor exists. IDs are `OPS-X@<anchor>` (operating-standard §3) — **never** `OPS-X-1/-2`; multiplicity is carried by the anchor. Severity is scored intrinsically from the operating-standard §5 table (evidence level is a separate axis, not a severity input).

**Telemetry is the #1 variance source for this area.** Operations was historically a judgement-call area ("about 12% of creates failed") because its primary instrument (App Insights) is a manifest capability that is usually **absent** on an isolated review. Under `--static` (no `app_insights`), **OPS-A, OPS-B, OPS-D, OPS-E are a single fixed `NOT-ASSESSED(no-telemetry)` record each**, and the telemetry dimensions of OPS-C/OPS-F are fixed `NOT-ASSESSED(no-telemetry)` records too — never a silent pass, never a guessed percentage. Only the **static seams** (cron enumeration + collisions, scale-to-zero host, config drift, messaging/bus defaults, observability wiring) carry scored findings.

**Pins (from the manifest, operating-standard §1):** `$SHA` = `$(SheshaVersion)` from `backend/Directory.Build.props`; `$DLL` = the `Shesha.Application/$SHA` path resolved from `Web.Host/obj/project.assets.json` (every decompile targets this exact path); `$BASE` = the backend URL when `backend_running`; `$KQL` = `${CLAUDE_PLUGIN_ROOT}/shared/appinsights-queries.kql` (its §1..§N are the numbered queries).

## Capability-gating table (operating-standard §1 — absent capability ⇒ first-class NOT-ASSESSED, never a silent pass)
| Capability absent | Dimensions that become `NOT-ASSESSED(reason)` |
|---|---|
| `app_insights` | OPS-A/B/D/E entirely → one fixed `OPS-x@telemetry` `NOT-ASSESSED(no-telemetry)` each; OPS-C runtime/failure/duration dims → `OPS-C@telemetry` `NOT-ASSESSED(no-telemetry)`; OPS-F telemetry dim → `OPS-F@telemetry` `NOT-ASSESSED(no-telemetry)` |
| `db_copy` | OPS-C Hangfire job-state table counts, OPS-D notification-table status-by-month → `OPS-x@db` `NOT-ASSESSED(no-db-copy)`; OPS-G reference-data/migration-history drift → `OPS-G@db` `NOT-ASSESSED(no-db-copy)` |
| `backend_running` | OPS-C live Hangfire dashboard/state probe, OPS-E live SignalR negotiate probe → `NOT-ASSESSED(no-backend)`; the static cron/host/code predicates still run at CODE-ONLY/VERIFIED-ARTEFACT |
| two environments (QA + prod copy) | OPS-G QA-vs-prod reference/settings/form-version diff → `OPS-G@drift:qa-vs-prod` `NOT-ASSESSED(no-second-environment)` |

## Determinism pins (apply exactly; these remove observed cross-operator divergences)
- **The telemetry NOT-ASSESSED records are MANDATORY fixed anchors — every operator emits every one under `--static`, always:** `OPS-A@telemetry`, `OPS-B@telemetry`, `OPS-D@telemetry`, `OPS-E@telemetry`, `OPS-C@telemetry`, `OPS-F@telemetry`, each `evidence_level=NOT-ASSESSED(no-telemetry)`, `severity=Info`. Fixed strings so two runs' NOT-ASSESSED sets match exactly, and (operating-standard §6) Info/NOT-ASSESSED records never enter the fix-order list.
- **OPS-C cron enumeration is run BOTH ways Shesha/ABP registers recurring jobs — this is the historical false-negative.** A `[ScheduledJob]`-only grep returns nothing on a backend that registers via `RecurringJob.AddOrUpdate` and wrongly reads "no jobs". Run **both** exact greps (below) and union the result. The collision finding is **one record per distinct cron expression that ≥2 jobs share**, anchored `OPS-C@sched:collision=<cron-literal>` (the cron string verbatim), the member job types enumerated in the body — not one finding per job, not one narrative blob.
- **OPS-C scale-to-zero host is its own fixed finding** (`OPS-C@host:scale-to-zero`) when the hosting template sets a zero minimum replica count AND Hangfire runs in-process AND ≥1 `StartUpMode.Automatic` job exists — three booleans, no judgement. The missing jobs-off start-up switch is a separate fixed finding `OPS-C@host:no-job-toggle`.
- **OPS-G scope: committed config only under `--static`.** The QA-vs-prod reference-data/form-version diff and the migration-history-vs-incident correlation need `db_copy`/a second environment → fixed `NOT-ASSESSED` records. The static finding is the risky **committed default** in tracked `appsettings*.json`: an environment-specific connection string or a fail-closed value shipped without a per-environment override AND no fail-fast guard. One finding per offending `#key:<json.path>`. **Secret-valued defaults (signing keys, passwords, API keys) are SEC-E's, not OPS-G's** — overlap priority: SEC-E owns committed secrets; OPS-G raises only the non-secret config-drift keys (e.g. a QA-shaped `ConnectionStrings:Default`) and cross-references SEC-E for the secret ones.
- **OPS-H bus detection is a wiring grep, not a package-reference grep — this is the historical false trail.** A transitive `RabbitMQ.Client` referenced only for an exception type (e.g. in `ElmahFilter.cs`) is **not** a bus. Bus present IFF the wiring grep (below) matches an actual registration/consumer. No bus → `OPS-H@bus=none` (deterministic empty verdict, severity Info) AND the broker sub-checks are skipped; the check reframes onto shipped integration **defaults** (`WithDefaultValue(...)` to a real endpoint/credential).
- **root_cause is an enumerated id** from the `RC-ops-*` vocabulary (this file's table; must be merged into operating-standard §3). `fix_order_rank` is computed from {severity, root_cause, anchor}, so it matches across runs.

## Fixed severity-inputs per check (operating-standard §5 — impact_class + data_sensitivity are FIXED properties of the check; reachability resolves from the manifest). Author these exactly so two operators compute the same band.
| Check | impact_class | data_sensitivity | typical reachability → band |
|---|---|---|---|
| OPS-C `sched:collision` | dos | none | local_only → Low |
| OPS-C `host:scale-to-zero` | dos | none | local_only → Low |
| OPS-C `host:no-job-toggle` | maintainability | none | local_only → Low |
| OPS-G committed config default | maintainability | none | local_only → Low |
| OPS-H shipped integration default (non-secret endpoint) | info_leak | none | local_only → Low |
| OPS-H broker shared-default host (bus present) | data_integrity | business | any_authenticated → High |
| OPS-F observability gap (no failure logging) | maintainability | none | local_only → Low |
| OPS-A/B/D/E (telemetry) | info_leak | none | **NOT-ASSESSED(no-telemetry) → Info** |

`root_cause` map: OPS-C → `RC-ops-job-scheduling`; OPS-G → `RC-ops-config-drift`; OPS-H → `RC-ops-shipped-defaults`; OPS-F → `RC-ops-observability`. (OPS-A/B/D/E carry no root_cause — NOT-ASSESSED records are excluded from fix-order.)

**When `app_insights` IS present** the telemetry path below runs and upgrades the relevant anchor to `CONFIRMED-IN-LOGS` (telemetry shows it) or, where a failing path is reproduced live, `REPRODUCED`. The KQL queries stay the instrument; the predicates below become scored. Author the telemetry-present findings to the same anchor/severity contract.

---

## OPS-A: Failed requests by endpoint. **impact_class=info_leak, data_sensitivity=none, RC — none (telemetry-gated).**
Endpoints returning 4xx/5xx at meaningful rates, especially create/save operations — every failed save is a user's lost work or a duplicate-creating retry.
- **INPUT:** requires `app_insights`. `$KQL` §1 (failure rate per operation per month, weighted by `itemCount`); cross-check saved counts against DB rows and failed counts against gaps in reference-number sequences; then reproduce the failure path against the isolated copy.
- **PREDICATE:** an operation's monthly failure rate exceeds its business-volume-adjusted baseline (create/save with >1% 5xx or a 4xx rate not explained by validation) → one finding per operation.
- **VERDICT/ANCHOR:** telemetry present → `OPS-A@http:<VERB> <route-template>` (rate + volume + matched DB gap). **Telemetry absent → the fixed record `OPS-A@telemetry` `NOT-ASSESSED(no-telemetry)`.**
- **EVIDENCE:** telemetry shows it → CONFIRMED-IN-LOGS; failure path reproduced live → REPRODUCED; no telemetry → NOT-ASSESSED(no-telemetry).
- **REMEDIATION `PLAN-OPS-A`:** fix the failing path (feeds the code/ORM/SQL checks with real numbers); add the smallest targeted logging (OPS-F) so the rate is visible; alert on create/save 5xx spikes.
- **REGRESSION TEST:** `FailedRequests_CreateSaveErrorRateUnderThreshold_Test` (telemetry-backed assertion in the monitoring suite).
- **SEVERITY:** NOT-ASSESSED(no-telemetry) → **Info**. With telemetry: info_leak × any_authenticated → Medium (data_integrity when a failed save silently loses committed work → High).

## OPS-B: Slow endpoints and where the time goes. **impact_class=info_leak, data_sensitivity=none, RC — none (telemetry-gated).**
- **INPUT:** requires `app_insights`. `$KQL` §2 (P50/P95 duration + volume per operation); `$KQL` §3 (SQL calls + total SQL time per request for the slow ones).
- **PREDICATE:** an operation's P95 exceeds a stated budget AND the SQL-time breakdown localises the cost → one finding per operation (feeds `checks/orm-shesha.md` / `checks/sql.md` with real numbers).
- **VERDICT/ANCHOR:** `OPS-B@http:<VERB> <route-template>` (P50/P95 + SQL calls). **Telemetry absent → `OPS-B@telemetry` `NOT-ASSESSED(no-telemetry)`.**
- **EVIDENCE:** CONFIRMED-IN-LOGS from telemetry; no telemetry → NOT-ASSESSED(no-telemetry).
- **REMEDIATION `PLAN-OPS-B`:** hand the P95 + SQL-call numbers to the ORM/SQL findings; add an index / fix the N+1 / cache the hot read as those checks direct.
- **REGRESSION TEST:** `SlowEndpoints_P95WithinBudget_Test` (telemetry-backed).
- **SEVERITY:** NOT-ASSESSED(no-telemetry) → **Info**. With telemetry: info_leak × any_authenticated → Medium.

## OPS-C: Background jobs. **impact_class=dos (scheduling) / maintainability (toggle), data_sensitivity=none, RC-ops-job-scheduling.**
Hangfire/other jobs that collide, fail, retry forever or pile up; recurring jobs doing heavy work too often; and a host that cannot actually run them. **The static cron + host seams are scored; the runtime state is telemetry/DB-gated.**
- **INPUT (static — always runs):**
  - **Cron enumeration BOTH ways (union the two):**
    (a) `rg -n "\[ScheduledJob\(" backend/src --type cs` and read each `cronString`/cron argument + the job's `StartUpMode`.
    (b) `rg -n "RecurringJob\.AddOrUpdate|IRecurringJobManager|Cron\.(Hourly|Daily|Minutely|Monthly|Weekly)|AddOrUpdate\(" backend/src --type cs` (direct Hangfire registration in `Startup`/modules).
  - **Scale-to-zero host:** read the hosting template (`Pulumi.yaml`/`*.bicep`/`values*.yaml`/container-app manifest) for the minimum replica/instance count; confirm Hangfire runs in-process (`AddHangfire`/`UseHangfireServer` in the web host, not a separate worker); count `StartUpMode.Automatic` jobs.
  - **Start-up switch:** grep for an `IsJobExecutionEnabled`/`BackgroundJobs:Enabled`-type toggle that separates background processing from web serving.
- **INPUT (telemetry/DB — gated):** `HangFire.Job` state counts and failed-jobs-by-type (`db_copy`); `$KQL` failed-job + job-duration queries (`app_insights`); live Hangfire dashboard (`backend_running`).
- **PREDICATES (one finding per hit):**
  - **collision:** a distinct cron expression is shared by ≥2 jobs on a single in-process Hangfire server → `OPS-C@sched:collision=<cron-literal>`.
  - **scale-to-zero:** min-replicas/instances = 0 AND Hangfire in-process AND ≥1 `Automatic` job → `OPS-C@host:scale-to-zero` (a sleeping host does not fire scheduled jobs).
  - **no-job-toggle:** no start-up switch to run the host with background processing off → `OPS-C@host:no-job-toggle` (nobody can safely start it against a copy).
  - runtime (gated): a job failing/retrying forever or piling up → `OPS-C@job:<JobType>` when telemetry/DB present; else `OPS-C@telemetry` `NOT-ASSESSED(no-telemetry)` / `OPS-C@db` `NOT-ASSESSED(no-db-copy)`.
- **VERDICT/ANCHOR:** as above; collision body enumerates every member `#<JobType>` sharing the cron.
- **EVIDENCE:** cron/host facts from source + hosting template → **VERIFIED-ARTEFACT**; runtime state from telemetry → CONFIRMED-IN-LOGS; no telemetry/DB → NOT-ASSESSED.
- **REMEDIATION `PLAN-OPS-C`:** stagger the colliding cohort across distinct minutes; run background processing on a non-scale-to-zero worker (or pin the job host to ≥1 replica); add a background-processing-off start-up switch; surface Hangfire failures to an owner/alert (PM concern: does anyone watch the dashboard?).
- **REGRESSION TEST:** `BackgroundJobs_NoCronCollisionsAndJobsFireWhenHostIdle_Test` — asserts no two `Automatic` jobs share a cron AND a scale-to-zero host still fires the schedule (or a dedicated job host is configured).
- **SEVERITY:** `sched:collision` dos × local_only, −1 none → floor **Low**; `host:scale-to-zero` dos × local_only → **Low**; `host:no-job-toggle` maintainability → **Low**. (A collision that misses a legally-mandated run window may be argued up by the BA; author Low, note the escalation.)

## OPS-D: SMS, email, push and integrations. **impact_class=info_leak, data_sensitivity=none, RC — none (telemetry-gated).**
Outbound messages that fail (gateway errors, missing templates, bad numbers) and integrations failing silently — a failed SMS can turn a successful save into an error.
- **INPUT:** requires `app_insights`/`db_copy`. Notification message tables by status per month (`db_copy`); `$KQL` dependency calls to gateway hosts by result code (`app_insights`); templates referenced in code (`rg` the template-name constants) that don't exist in the database. Prove by reproducing against the isolated copy with the gateway pointed at a dead host (does the user action fail? is it retried? is anyone told?).
- **PREDICATE:** an outbound channel/integration shows a non-trivial failure rate OR a referenced template is absent in the DB → one finding per channel/template.
- **VERDICT/ANCHOR:** `OPS-D@dep:<gateway-host>` or `OPS-D@template:<name>`. **Telemetry/DB absent → `OPS-D@telemetry` `NOT-ASSESSED(no-telemetry)`.**
- **EVIDENCE:** CONFIRMED-IN-LOGS from telemetry; reproduced dead-host behaviour → REPRODUCED; absent → NOT-ASSESSED(no-telemetry).
- **REMEDIATION `PLAN-OPS-D`:** decouple the user action from the send (queue + retry); surface send failures; seed/validate referenced templates at start-up.
- **REGRESSION TEST:** `OutboundMessaging_SaveSucceedsWhenGatewayDown_Test`.
- **SEVERITY:** NOT-ASSESSED(no-telemetry) → **Info**. With telemetry: data_integrity (failed send fails the save) × any_authenticated → High.

## OPS-E: SignalR in production. **impact_class=info_leak, data_sensitivity=none, RC — none (telemetry-gated).**
- **INPUT:** requires `app_insights`/`backend_running`. Connection counts + failures, negotiate 401s, messages-per-event-type, broadcast-to-everyone volume, reconnect storms, server memory/CPU around peaks. Authentication + scoping are `checks/security.md` SEC-F, not here.
- **PREDICATE:** negotiate-failure rate, reconnect-storm, or broadcast fan-out exceeds a stated baseline → one finding.
- **VERDICT/ANCHOR:** `OPS-E@hub:<hub-path>`. **Telemetry absent → `OPS-E@telemetry` `NOT-ASSESSED(no-telemetry)`.** (Note the static presence of `AddSignalR()` / `MapHub<...>` here for the OPS-E body and hand authentication to SEC-F.)
- **EVIDENCE:** CONFIRMED-IN-LOGS from telemetry; absent → NOT-ASSESSED(no-telemetry).
- **REMEDIATION `PLAN-OPS-E`:** scope broadcasts to the user's groups; back off reconnects; watch negotiate 401 rate.
- **REGRESSION TEST:** `SignalR_NegotiateAndBroadcastWithinBaseline_Test`.
- **SEVERITY:** NOT-ASSESSED(no-telemetry) → **Info**. With telemetry: info_leak × any_authenticated → Medium.

## OPS-F: Observability — can the team find out what and why when production breaks? **impact_class=maintainability, data_sensitivity=none, RC-ops-observability.**
Be pragmatic — recommend the **smallest targeted logging**, never "turn on everything" (full request/audit logging can cripple API performance and fill disk). The static wiring is scored; the "does telemetry actually capture it" dimension is telemetry-gated.
- **INPUT (static):** grep the exception-handling pipeline / global filters (`rg -n "ExceptionFilter|IExceptionFilter|UseExceptionHandler|ILogger|AddApplicationInsightsTelemetry|AbpHandledExceptionData|OnException" backend/src --type cs`) to answer: are handled exceptions logged at all (frameworks often turn them into 400/500 with no log)? do validation failures record the failing field names? is there an audit trail for sensitive actions (admin changes, data access)? is sampling configured so aggressively it hides rare failures?
- **PREDICATE:** a critical-endpoint failure path produces **no** log/telemetry record (handled exception swallowed, or rejected create with no failing-field warning, or admin action with no audit row) → one finding per gap.
- **VERDICT/ANCHOR:** `OPS-F@<path>#<Type>.<Member>` (the swallowing handler/filter) or `OPS-F@observability:<gap>` for a pipeline-wide gap (e.g. `OPS-F@observability:handled-exceptions-unlogged`). **The "telemetry confirms the gap in production" dimension → `OPS-F@telemetry` `NOT-ASSESSED(no-telemetry)`.**
- **EVIDENCE:** static wiring read → CODE-ONLY (VERIFIED-ARTEFACT if decompiled); production confirmation → NOT-ASSESSED(no-telemetry) absent App Insights.
- **REMEDIATION `PLAN-OPS-F`:** smallest targeted logging only — a warning with the failing property names on rejected creates; exceptions on critical endpoints with personal data masked (ties SEC-H); an audit row for admin actions only. Estimate the added volume.
- **REGRESSION TEST:** `Observability_CriticalEndpointFailuresAreLogged_Test` — a forced failure on a critical endpoint asserts a log/audit record with masked PII and the failing fields.
- **SEVERITY:** maintainability × local_only → floor **Low**.

## OPS-G: Configuration drift and deployment. **impact_class=maintainability, data_sensitivity=none, RC-ops-config-drift.**
- **INPUT (static — always runs):** enumerate committed `appsettings*.json` (`rg --files -g 'appsettings*.json' backend/src`) and read each for an environment-specific value shipped as the committed default without a per-environment override pattern: a real/QA-shaped `ConnectionStrings:*`, a fail-closed URL, a `TargetFramework`/SQL-edition assumption. Read the migration directory for the FluentMigrator set (`M<UTC>.cs`) and deployment order (back end before front end).
- **INPUT (gated):** QA-vs-prod reference-data/settings/form-version diff and missing named records need a second environment; migration-history-vs-incident dates and the SQL Server version/edition needed by recent migrations need `db_copy` → fixed `NOT-ASSESSED` records.
- **PREDICATE:** a tracked `appsettings*.json` key holds an environment-specific/fail-closed value AND there is no per-environment override committed AND no fail-fast guard rejecting the default outside Development → one finding per `#key:<json.path>`. **Secret-valued keys (signing keys, passwords, API keys) are excluded here and raised under SEC-E** (overlap priority: SEC-E owns committed secrets).
- **VERDICT/ANCHOR:** `OPS-G@<path>#key:<Section>:<Key>` — the JSON key path uses the **ABP/.NET config `:` separator** (e.g. `#key:ConnectionStrings:Default`, `#key:App:ServerRootAddress`), **never a `.` dot** (that was the A=`.`/B=`:` split). Plus the fixed `OPS-G@db` / `OPS-G@drift:qa-vs-prod` NOT-ASSESSED records when those capabilities are absent.
- **EVIDENCE:** committed-config read → VERIFIED-ARTEFACT; cross-environment/DB dimensions → NOT-ASSESSED(no-db-copy / no-second-environment).
- **REMEDIATION `PLAN-OPS-G`:** empty/placeholder every shipped environment-specific value; set it per environment via the pipeline/secret store; fail fast on start-up if a required value is unset outside Development; keep reference data in migrations or seeds (not hand-SQL); a release checklist + a migration rehearsal on a production-sized copy (with approval).
- **REGRESSION TEST:** `Config_FailsFastWhenEnvValueUnsetOutsideDevelopment_Test`.
- **SEVERITY:** maintainability × local_only → floor **Low**.

## OPS-H: Messaging and integration defaults. **impact_class=info_leak (shipped default) / data_integrity (shared broker), data_sensitivity=none/business, RC-ops-shipped-defaults.**
**First: is there a bus at all?** — a wiring grep, not a package-reference grep.
- **INPUT:** `rg -n "AddMassTransit|IBusControl|UsingRabbitMq|UseRabbitMq|AddConsumer|IConsumer<|AddRabbitMq|CreateConnection\(" backend/src --type cs`. A transitive `RabbitMQ.Client` referenced only for an exception type (e.g. `ElmahFilter.cs`) is **not** a bus. If no wiring match → `OPS-H@bus=none` (empty verdict, severity Info) and skip the broker sub-checks. Then, bus or not, scan shipped **defaults**: every `*Module.cs` `WithDefaultValue(...)`/`RegisterSettingAccessor` on an integration setting, and every `appsettings*.json` integration block, for a default that is a **real endpoint / API key / connection/crypto string** rather than empty-set-per-environment. Compare sibling integrations in the same codebase (one often ships empty while one ships a live default).
- **PREDICATES (one finding per hit):**
  - shipped integration default points at a real/production endpoint (non-secret) → `OPS-H@<path>#<Module>.<member>` or `OPS-H@<path>#key:<json.path>`. (A `WithDefaultValue` that is only a migration column default — a bool/decimal — does **not** qualify.)
  - shipped default is a credential/signing/crypto string → raised under **SEC-E** (cross-ref; do not double-list).
  - **bus present** broker sub-checks: a package-default host (shared server, sometimes a default username) → `OPS-H@<path>#key:<broker.host>` (prove the default from the DLL string table via `ilspycmd`, classify credential-like strings by length only); queue names not unique per environment → `OPS-H@queue:<name>`; a config key nothing reads → `OPS-H@key:<name>:unread`; a consumer trusting shared-broker content or acking on failure → cross-ref SEC-J.
- **VERDICT/ANCHOR:** as above; `OPS-H@bus=none` when there is no bus. **`OPS-H@bus=none` is an absence/empty-verdict record → EVIDENCE pinned CODE-ONLY, severity Info, plan_id null** (never VERIFIED-ARTEFACT — a zero-match wiring grep is a forward-looking absence, consistent with every other `=none` record).
- **EVIDENCE:** source/config read → VERIFIED-ARTEFACT; DLL-string default → VERIFIED-ARTEFACT; a settings insert with a NULL old-value (an `InsertedSetting` audit row) proving the DB relied on the default → DATA-ANOMALY/VERIFIED-ARTEFACT.
- **REMEDIATION `PLAN-OPS-H`:** per-environment settings (default empty); environment-unique queue names; a start-up guard refusing known defaults outside Development; route shared-server defaults to the Shesha team report.
- **REGRESSION TEST:** `Messaging_NoSharedDefaultsEnvUniqueQueues_Test`.
- **SEVERITY:** non-secret shipped endpoint default info_leak × local_only → **Low**; `bus=none` → **Info**; shared-broker default host (bus present) data_integrity × any_authenticated, +business → **High**.
