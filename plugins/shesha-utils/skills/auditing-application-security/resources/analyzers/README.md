# Boxfusion.SecAnalyzers — deterministic SEC-A / SEC-H (Roslyn)

A self-contained Roslyn analyzer that makes the two security checks a text grep cannot run
reproducibly — **SEC-A** (a client/route-supplied entity id trusted as the identity/scope,
no `AbpSession`/`GetLoggedInPerson` cross-check — BOLA / param-trust) and **SEC-H** (a POPIA
personal-data property interpolated into a `Log*` call, excluding `System.Type` reflection) —
**deterministic**. It is the instrument that retires the `non_deterministic:true` quarantine
on SEC-A / SEC-H described in `references/determinism-standard.md` §7, gated on the
`buildable_backend` capability (§1) — otherwise `NOT-ASSESSED(no-build)`.

Ported from the proven TLC skill analyzer (`boxfusion-tlc/analyzers`); the analyzer **logic
is identical** (predicates, anchoring, semantic-model exclusions). Only the namespace /
assembly names changed: `BoxfusionTlc.SecAnalyzers` → **`Boxfusion.SecAnalyzers`**,
`BoxfusionTlc.SecDriver` → **`Boxfusion.SecDriver`**. The Roslyn `DiagnosticId`s stay
`SEC_A` / `SEC_H` (the driver maps `_`→`-` to the registry check id).

## Why an analyzer, not a grep

- **SEC-A needs dataflow.** The question is whether a client-supplied `Guid …Id` reaches a
  read or scope decision **without** being re-derived from the session. A one-line grep cannot
  match `Task<…>` and nested generics or PascalCase-vs-camelCase parameter names, so operators
  fell back to reading signatures by eye and picked different methods.
- **SEC-H needs the receiver's type.** `person.FullName` is personal data; `someType.FullName`
  (`System.Type.FullName`, reflection) is not. A text exclusion missed longer identifiers, and
  the `rg | rg -v` pipe ran inconsistently: operators got 0, 10 and 14 sites for the "same"
  command, and half of one system's raw hits were reflection decoys inside exception messages.
  Only the semantic model separates them reproducibly.

## Layout
- `src/Boxfusion.SecAnalyzers/` — netstandard2.0 `Microsoft.CodeAnalysis.CSharp` analyzer
  library with two `DiagnosticAnalyzer`s (`SEC_A`, `SEC_H`) + `AnchorHelper` / `Predicates`.
- `src/Boxfusion.SecDriver/` — net8.0 console driver. Opens a target solution with
  `MSBuildWorkspace`, runs both analyzers, and emits a determinism-standard §8
  `findings.json` fragment (canonically sorted, byte-identical across two runs).
- `../run_analyzers.py` — the thin Python wrapper audit code calls (see **Hook** below).

## Predicates (one line each)
- **SEC-A** — a public app-service/controller method has a `Guid …Id` actor-id parameter
  (person/profile/owner/user/employee/appointment/farmer/delegat, minus audit ids) that
  flows into a read/scope decision, and the body has **no** session cross-check
  (`AbpSession`/`GetLoggedInPersonAsync`/`CurrentUser`).
- **SEC-H** — a `Log*`/`Logger.Info` call is passed an interpolated/concatenated string
  containing a POPIA property access (`IdentityNumber|PersalNo|PersalNumber|FullName|
  DateOfBirth|LeaveReason`) whose **declaring type** (resolved by the semantic model) is not
  `System.Type`/`System.Reflection.*` — separating `person.FullName` (PII) from
  `customType.FullName` (reflection), which a grep cannot.

## Build
```bash
cd resources/analyzers
dotnet build Boxfusion.SecAnalyzers.slnx -c Release
```
A local `NuGet.Config` isolates the build from the machine's private Shesha feed; every
package (Microsoft.Build.Locator, Microsoft.CodeAnalysis.*) is on nuget.org. `bin/` and
`obj/` are git-ignored (`.gitignore`) — build output is never committed.

## Run (standalone)
```bash
DRV=src/Boxfusion.SecDriver/bin/Release/net8.0/Boxfusion.SecDriver.dll
SHA=$(git -C <repo> rev-parse HEAD)
dotnet "$DRV" --solution <repo>/backend/<App>.sln --repo-root <repo> \
              --out <run-dir>/analyzer-findings.json --commit "$SHA"
```
The driver disables `NuGetAudit`/`TreatWarningsAsErrors` so every project yields a
`Compilation` from the already-restored references without touching the private feed. If it
cannot obtain any `Compilation` it writes its own `NOT-ASSESSED(no-build)` fallback — never
a silent empty pass.

## Determinism
Anchors are symbols (`<path>#<Type>.<Member>`), never line numbers; output is canonically
sorted (severity band → area → check_id → anchor) and serialized with a stable field order
and `\n` newlines, so two runs on the same commit are **byte-identical**
(determinism-standard §8). `fix_order_rank` is a pure function of `{severity, root_cause,
anchor}`.

## The emitted finding (shared §8 schema)

| field | SEC-A | SEC-H |
|---|---|---|
| `finding_id` | `SEC-A@<path>#<Type>.<Member>` | `SEC-H@<path>#<Type>.<Member>` |
| `evidence_level` | `VERIFIED-ARTEFACT` | `VERIFIED-ARTEFACT` |
| `execution_class` | `roslyn-analyzer-scan` | `roslyn-analyzer-scan` |
| `severity` (derived) | **Critical** | **High** |
| `severity_inputs` | `auth_bypass` / `any_authenticated` / `pii_basic` | `data_exposure_pii` / `admin_only` / `pii_basic` |
| `plan_id` | `PLAN-SEC-A` | `PLAN-SEC-H` |
| `root_cause` | `RC-sec-bola` | `RC-sec-pii-logging` |
| `non_deterministic` | `false` | `false` |

`severity` is **derived** from the three inputs by the §4 scoring table in
`FindingRecord.cs` (`CheckProfiles.Score`), not asserted — base(impact_class, reachability)
then +1 band for `pii_basic`/`popia_special`. SEC-A: base High +1 = Critical. SEC-H: base
Medium (admin_only) +1 = High.

### Registry reconciliation (for the parent to confirm at merge)
The driver keys off `references/check-registry.md`. Two registry cells are under-specified,
resolved here and flagged:
1. **SEC-H reachability** — the registry lists `n/a` (a log sink is not an endpoint gate).
   Resolved to `admin_only` (the leaked PII is exposed to whoever reads the logs), which
   scores the TLC-proven **High**. Change this cell if the registry prefers a different reach.
2. **root_cause vocabulary** — determinism-standard §6 requires an enumerated `RC-sec-*` id
   registered in the check registry. SEC-A → `RC-sec-bola` (§7 names SEC_A a BOLA check;
   `RC-sec-bola` is already registered in the H section). SEC-H → `RC-sec-pii-logging`
   (registered in the check registry §6). The TLC source used the older ids
   `RC-no-authz-model` / `RC-pii-handling`; `shared/operating-standard.md` now uses the
   `RC-sec-*` names too.

These are value-only choices; they do not affect two-run byte-identity.

## Hook — how `run_audit.py` should call this (parent applies at merge)
`run_analyzers.py` is deliberately **not** wired into `run_audit.py` yet (a sibling worker is
editing that file). Add it as one static-phase step. Minimal one-line hook in
`run_audit.py`'s `build_steps()` list (phase 1, alongside `posture`/`source-scan`):

```python
Step("analyzers", "run_analyzers.py", [os.path.join("@run", "analyzer-findings.json")],
     always=True, optional=True,
     extra=lambda a, ctx: ["--out", os.path.join(ctx["run_dir"], "analyzer-findings.json")]),
```

`run_analyzers.py` already takes `--repo-root` (added by `run_step`). It auto-discovers the
backend `.sln` and the git commit; pass `--solution`/`--commit` via `extra` to override.
`optional=True` keeps a no-build run from stopping the pipeline — the step still writes the
`NOT-ASSESSED(no-build)` fragment, so it is recorded, never silently skipped.

The emitted `<run-dir>/analyzer-findings.json` is a §8 fragment to be unioned into the run's
`findings.json` (determinism-standard §9 `merge_runs.py` semantics): the two SEC-A/SEC-H rows
join the catalogue-derived findings keyed by their shared `finding_id`.

## No-build fallback (the honesty rule)
`run_analyzers.py` is the `buildable_backend` gate (determinism-standard §1). When `dotnet`
is absent, the driver won't build, no target `.sln` is found, or the target fails to build,
it writes the two fixed records:
```
SEC-A@analyzer  evidence_level=NOT-ASSESSED(no-build)  severity=Info  not_assessed_reason=no-build
SEC-H@analyzer  evidence_level=NOT-ASSESSED(no-build)  severity=Info  not_assessed_reason=no-build
```
`non_deterministic=false` throughout. A capability-absent check is a first-class
`NOT-ASSESSED` verdict, **never** a silent pass.
