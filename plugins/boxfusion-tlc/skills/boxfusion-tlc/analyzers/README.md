# BoxfusionTlc.SecAnalyzers — deterministic SEC-A / SEC-H

A self-contained Roslyn analyzer that makes the two security checks a text grep cannot
run reproducibly — **SEC-A** (browser-trusted entity-id-as-actor) and **SEC-H** (POPIA
value interpolated into a log) — **deterministic**, retiring their honest
`NON-DETERMINISTIC` quarantine in [`../checks/security.md`](../checks/security.md). See
[`PLAN.md`](PLAN.md) for the predicates and anchoring design.

## Layout
- `src/BoxfusionTlc.SecAnalyzers/` — netstandard2.0 `Microsoft.CodeAnalysis.CSharp`
  analyzer library with two `DiagnosticAnalyzer`s (`SEC_A`, `SEC_H`) + anchoring helpers.
- `src/BoxfusionTlc.SecDriver/` — net8.0 console driver. Opens a target solution with
  `MSBuildWorkspace`, runs both analyzers, and emits operating-standard §8 `findings.json`.
- `reference-findings.json` — the committed proof output from `C:\Dev\pd-Hcm` @ `7fc13b84`.

## Predicates (one line each)
- **SEC-A** — a public app-service/controller method has a `Guid …Id` actor-id parameter
  (person/profile/owner/user/employee/appointment/farmer/delegat, minus audit ids) that
  flows into a read/scope decision, and the body has **no** session cross-check
  (`AbpSession`/`GetLoggedInPersonAsync`/`CurrentUser`).
- **SEC-H** — a `Log*`/`Logger.Info` call is passed an interpolated/concatenated string
  containing a POPIA property access (`IdentityNumber|PersalNo|PersalNumber|FullName|
  DateOfBirth|LeaveReason`) whose **declaring type** (resolved by the semantic model) is
  not `System.Type`/`System.Reflection.*` — separating `person.FullName` (PII) from
  `customType.FullName` (reflection), which a grep cannot.

## Build
```bash
cd analyzers
dotnet build BoxfusionTlc.SecAnalyzers.slnx -c Release
```
A local `NuGet.Config` isolates the build from the machine's private Shesha feed; every
package (Microsoft.Build.Locator, Microsoft.CodeAnalysis.*) is on nuget.org.

## Run against a target (pd-Hcm is READ-ONLY — build/analyze only)
```bash
DRV=src/BoxfusionTlc.SecDriver/bin/Release/net8.0/BoxfusionTlc.SecDriver.dll
SHA=$(git -C C:/Dev/pd-Hcm rev-parse HEAD)
dotnet "$DRV" --solution C:/Dev/pd-Hcm/backend/Shesha.Hcm.sln \
              --repo-root C:/Dev/pd-Hcm --out runs/A/findings.json --commit "$SHA"
```
The driver disables `NuGetAudit`/`TreatWarningsAsErrors` so every project yields a
`Compilation` from the already-restored references without touching the private feed.

## Determinism proof (twice-run, byte-identical)
```bash
dotnet "$DRV" --solution C:/Dev/pd-Hcm/backend/Shesha.Hcm.sln --repo-root C:/Dev/pd-Hcm --out runs/A/findings.json --commit "$SHA"
dotnet "$DRV" --solution C:/Dev/pd-Hcm/backend/Shesha.Hcm.sln --repo-root C:/Dev/pd-Hcm --out runs/B/findings.json --commit "$SHA"
diff runs/A/findings.json runs/B/findings.json          # empty → byte-identical
node ../harness/normalize.mjs runs/A/findings.json > runs/A/findings.norm.json
node ../harness/normalize.mjs runs/B/findings.json > runs/B/findings.norm.json
node ../harness/diff-findings.mjs runs/A/findings.norm.json runs/B/findings.norm.json runs/A/manifest.json runs/B/manifest.json
```
Result on `7fc13b84`: **13 findings** (8 SEC-A app-service sites, 5 SEC-H PII-in-log
sites; 7 `System.Type.FullName` decoys excluded), `sha256 43b5c6cf…` identical across
both runs, acceptance `pass:true`, `fix_order_match:true`.

## Honest fallback
If the driver cannot obtain a `Compilation` (no restore/build), it emits
`SEC-A@analyzer` and `SEC-H@analyzer` as `NOT-ASSESSED(no-build)` / `severity:Info` —
never a silent empty pass.
