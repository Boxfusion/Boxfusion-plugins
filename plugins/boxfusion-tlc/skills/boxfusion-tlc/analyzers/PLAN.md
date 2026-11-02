# PLAN — Roslyn analyzer to make SEC-A and SEC-H deterministic

**Goal.** Retire the honest `NON-DETERMINISTIC` quarantine on SEC-A and SEC-H in
`checks/security.md` (R4 pin line 33, R8 pin line 79) by replacing the text-grep
predicates — which two operators genuinely cannot run reproducibly — with a
self-contained Roslyn analyzer whose predicate is evaluated over the parsed syntax
tree + the **semantic model**. The analyzer is a tool/scan that emits an anchor per
finding, so its output is `VERIFIED-ARTEFACT` (operating-standard §4) and is
byte-identical across two runs on the same commit (§0 acceptance target).

Everything stays on branch `weekend-hardening`. The target system
`C:\Dev\pd-Hcm` @ `7fc13b84` is **read-only** (we only `dotnet build`/analyze it).

---

## Why a grep cannot do this (the determinism defect being retired)

- **SEC-A** needs *dataflow*: does a client-supplied `Guid …Id` reach a read/scope
  decision **without** a server-side re-derivation from the session/principal? A
  single-line grep cannot match `Task<…>` / nested generics / PascalCase-vs-camelCase
  param names, so operators fall back to reading signatures by eye and pick different
  methods (R4 pin, line 33).
- **SEC-H** needs the *receiver's type*: `person.FullName` (PII, a finding) vs
  `customSubmitType.FullName` (`System.Type.FullName`, reflection, benign). The
  `\bType\.FullName` text exclusion misses longer camelCase identifiers and the
  `rg | rg -v` pipe executes inconsistently — operators returned 0, 10, and 14 sites
  for the "same" command (R8 pin, line 79). On pd-Hcm the raw grep returns **14**
  `.FullName`-token log-ish sites; **7** of them are `System.Type.FullName` reflection
  decoys inside `throw new ArgumentException(...)`. Only the semantic model separates
  them reproducibly.

---

## Deliverable layout

```
analyzers/
  PLAN.md                                  (this file)
  BoxfusionTlc.SecAnalyzers.sln
  src/BoxfusionTlc.SecAnalyzers/           netstandard2.0 analyzer library
    BoxfusionTlc.SecAnalyzers.csproj
    AnchorHelper.cs                        repo-relative + §3 path/overload anchoring
    Predicates.cs                          frozen token sets (closed, pinned)
    SecABrowserTrustedAnalyzer.cs          DiagnosticAnalyzer id "SEC-A"
    SecHPiiInLogsAnalyzer.cs               DiagnosticAnalyzer id "SEC-H"
  src/BoxfusionTlc.SecDriver/              net8.0 console driver
    BoxfusionTlc.SecDriver.csproj
    Program.cs                             MSBuildWorkspace → run analyzers → findings.json
    FindingRecord.cs                       §8 record + canonical sort + §6 fix_order_rank
```

The driver runs the two `DiagnosticAnalyzer`s via
`compilation.WithAnalyzers(...).GetAnalyzerDiagnosticsAsync()` and maps each
`Diagnostic` to an operating-standard §8 `findings.json` record. The analyzer stores
the computed anchor fragment (`#Type.Member`, with an overload discriminator when the
type has >1 member of that name) and the absolute file path in the diagnostic's
`Properties`; the driver turns the path into the §3 repo-relative, lower-cased anchor.

---

## SEC-A predicate (one line)

> A public method of an app-service / controller type has a `Guid`/`Guid?` parameter
> whose name carries an actor-id token *(person, profile, owner, user, employee,
> appointment, farmer, delegat)* and ends in `Id` (minus the audit set
> creator/lastModifier/deleter), that parameter **flows into a read/scope decision**
> (it is an argument to a repository/LINQ query call, or an operand of an `==`/`!=`
> filter against an entity `…Id` — excluding `Guid.Empty`/`null`/`default` validity
> guards), **and** the method body contains **no** server-side cross-check symbol
> (`AbpSession`, `GetLoggedInPersonAsync`, `GetLoggedInUserAsync`,
> `GetCurrentPersonAsync`, `GetCurrentUserAsync`, `CurrentUser`).

- **Reachable surface** = instance method on a type that (a) derives from
  `Abp.Application.Services.ApplicationService` / `IApplicationService`, or from
  `Microsoft.AspNetCore.Mvc.ControllerBase`, resolved by walking the base chain; or
  (b) whose name ends with `AppService` (name fallback when the base type is an
  unresolved framework symbol). Public, non-static, non-ctor.
- **Anchor** `SEC-A@<path>#<Type>.<Member>` (method symbol, never a line). One finding
  per method even with several qualifying params.
- **Known pd-Hcm sites** (R2/R4 pins require *both*):
  `SaGovLeaveRequestAppService.CreateDelegationAppointmentAsync` (`leaveProfileId`,
  `delegatedToId`) and `SaGovCycleAppService.GetEmployeePerformanceItemsAsync`
  (`employeeId`).
- **Severity inputs (fixed, from checks/security.md SEC-A + the CODE-F-1 handover):**
  impact_class=`auth_bypass`, reachability=`any_authenticated`,
  data_sensitivity=`business` → **Critical**. plan_id=`PLAN-SEC-A`,
  root_cause=`RC-no-authz-model`.

## SEC-H predicate (one line)

> A logging call (`_logger`/`Logger`/`Log`/`logger` receiver, or a receiver whose type
> is an `ILogger`, or a bare `Log…`-named wrapper) is passed an interpolated string /
> string-concat argument that contains a member access `X.P` where `P` is a frozen
> POPIA token *(IdentityNumber, PersalNo, PersalNumber, FullName, DateOfBirth,
> LeaveReason)* **and** the semantic type of the receiver `X` is a resolvable,
> non-reflection type (i.e. **not** `System.Type`/`System.Reflection.*` — this is the
> `FullName` vs `Type.FullName` disambiguation the semantic model resolves and a grep
> cannot).

- **Anchor** `SEC-H@<path>#<Type>.<Member>` (the enclosing method of the log call).
  Multiple PII log sites in one method collapse to one finding (§3 identical ids).
- **Known pd-Hcm sites** (entity receivers, inside real `Log*`/`Logger.Info` calls):
  `LeaveTakenPerPersonImport` (`currentPerson.FullName`), `PersalLeavesSyncJob`
  (`transaction.PersalNumber`), `PersalHelper` (`transaction.PersalNumber`),
  `LeaveInterfaceDatafileImport` (`row.PersalNo`), `SaGovCycleReviewProcessAppService`
  (`currentPerson?.FullName`). The 7 `…Type.FullName` reflection sites are excluded.
- **Severity inputs (fixed, from checks/security.md R6 table line 59):**
  impact_class=`data_exposure_pii`, reachability=`low_priv`, data_sensitivity=`pii_basic`
  → **High**. plan_id=`PLAN-SEC-H`, root_cause=`RC-pii-handling`.

## Output contract (operating-standard §8) and determinism

- Record fields: `finding_id, check_id, area="security", anchor, evidence_level,
  execution_class, severity, severity_inputs{impact_class,reachability,data_sensitivity},
  plan_id, root_cause, fix_order_rank, sources[], not_assessed_reason=null,
  non_deterministic=false, commit_sha`.
- `evidence_level="VERIFIED-ARTEFACT"`, `execution_class="roslyn-analyzer-scan"`.
- **Canonical sort** (§8): severity band → area → check_id → anchor.
- **fix_order_rank** (§6, computed, never hand-set): group by root_cause; order groups
  by max severity then root_cause id; within a group by severity then anchor; 1-based.
- Serialized with `System.Text.Json` (`WriteIndented`), stable field order, paths
  repo-relative — so two runs on `7fc13b84` are **byte-identical**. Proof: run twice,
  `fc`/`diff` the two `findings.json`.
- Passes `harness/normalize.mjs` (closed evidence enum, anchor has no `:line`) and is
  a clean diff under `harness/diff-findings.mjs`.

## Honest fallback (kept, per the task)

If the driver cannot obtain a `Compilation` (no restore/build — e.g. a
`backend_building` capability is absent), it emits the fixed NOT-ASSESSED records
`SEC-A@analyzer` and `SEC-H@analyzer` with `evidence_level=NOT-ASSESSED(no-build)`,
`severity="Info"`, `non_deterministic=false` — never a silent empty pass. `no-build`
is registered in the operating-standard §3 closed reason set.

## checks/security.md changes (after the analyzer is proven deterministic)

1. SEC-A block: replace the R4 "NON-DETERMINISTIC until rebuilt" pin with
   "deterministic via the Roslyn analyzer (`analyzers/BoxfusionTlc.SecAnalyzers`)",
   point the Detect/INPUT step at the analyzer, keep the fixed severity inputs.
2. SEC-H block: replace the R8 "NON-DETERMINISTIC (quarantined)" pin likewise; keep
   `SEC-H@telemetry` NOT-ASSESSED and the frozen POPIA token list.
3. `harness/manifest.json` capability note: the analyzer is now a present instrument
   (`sec_analyzer`) — record it so the capability-gating table knows SEC-A/SEC-H are
   assessed when a build is available, NOT-ASSESSED(no-build) otherwise.
