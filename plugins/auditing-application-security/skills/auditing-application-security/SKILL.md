---
name: auditing-application-security
description: Catalogues and security-reviews a whole Shesha application — roles and permissions, configured forms, coded screens, custom endpoints, entities and their CRUD APIs — then writes plain-English, prioritised remediation recommendations per package. Self-contained: starts the dev servers, collects live configuration, scans form markup and front-end source, probes endpoints anonymously and as a low-privilege user, checks Startup.cs, appsettings, tokens, rate limiting and dependencies, and resolves each object's effective access from live PermissionedObject data. Emits per-package JSON catalogues plus {package}-recommendations.md. Use when the user asks to security-audit, review, pen-test or harden a Shesha application, to catalogue its endpoints, entities, forms, roles or permissions, to find unsecured, anonymously-accessible, unused or orphaned API surface, or to check which permissions and forms are actually referenced.
---

# Auditing Application Security

Build a complete map of a Shesha application's security-relevant artefacts and the
relationships between them, review it, and write recommendations a developer can act on.

This skill is standalone. It starts its own servers, collects its own data and runs its own
scans — nothing else needs to be invoked first.

Two phases, in order, and the second is written entirely from the first:

1. **Catalogue and review** — one JSON artefact per package per artefact type, then a review
   pass that confirms or overrides every heuristic in them.
2. **Reporting** — `{package}-recommendations.md`, succinct, prioritised, jargon-free.

Arguments (from `$ARGUMENTS`, all optional):
- `--url <base_url>` — backend base URL (default from `appsettings.json`, else `http://localhost:21021`)
- `--user` / `--password` — audit credentials (default `admin` / `123qwe`)
- `--lowpriv-user` / `--lowpriv-password` — a second, zero-permission account. Without it,
  every "any logged-in user can …" finding is **derived**, never observed, and object-level
  authorization cannot be tested at all
- `--scope app` — catalogue only packages this repository owns
- `--packages <name>` — restrict to named packages (repeatable)
- `--refresh` — refetch the live data even if a current cache exists
- `--skip-live` — source and package analysis only; every live check becomes SKIP
- `--skip-probes` — build the catalogue but do not send probe requests
- `--skip-deps` — skip the dependency advisory scan, the slowest step
- `--no-servers` — fail rather than starting the backend
- `--package-source <name>=<path>` — a framework or Enterprise **source** checkout whose own
  React pages, components and packaged forms count as callers (repeatable, remembered in the
  cache). Without it, every endpoint only the framework or Enterprise UI calls reads as
  unreferenced. Point it at the repository that holds the *source*, e.g.
  `shesha-framework=C:/src/shesha-framework` and `shesha-enterprise=C:/src/pd-enterpriseproject`
  — not at an application that merely consumes the packages. **Optional**: the audit runs
  without it (see Step 5b, "When the source is not available")
- `--no-package-source` — audit deliberately without package source and forget remembered trees

## Where output goes

**Every artefact from one run goes in `security-audits/YYMMDD-HHMM/`**, created once at Step 1:

```
security-audits/260901-0930/
  recommendations-index.md              <- the lead reads this
  Shesha.Hcm-recommendations.md         <- one per package with findings
  SaGov.Leave-recommendations.md
  ...
  security-catalog-260901-0930.xlsx     <- reviewers work from this (final step)
  catalog/
    _index.json                         <- manifest, totals, confidence, missing inputs
    review-overrides.json               <- the review phase's decisions
    Shesha.Hcm-roles-and-permissions.json
    Shesha.Hcm-configured-forms.json
    Shesha.Hcm-endpoints.json
    Shesha.Hcm-entities.json
    Shesha.Hcm-other-findings.json
    adminportal-custom-forms.json
    ...
```

Fix the directory once and pass it to every script as `--run-dir`:

```bash
RUN=$(python -c "import sys;sys.path.insert(0,'.claude/skills/auditing-application-security/resources');from shesha_audit import new_run_dir;print(new_run_dir('.'))")
```

Runs are never overwritten — that is what makes the comparison step possible. Raw captures
stay separate in `.claude/.audit-cache/<host>/`, which is **gitignored because it holds
credentials and captured tokens**; `security-audits/` is meant to be committed.

## Files

Reference files, each read when its step is reached — not up front:

| File | Read at |
|------|---------|
| `references/dev-servers.md` | Step 1, if the backend is not already up |
| `references/ownership-detection.md` | Step 2 — app-owned versus package-imported |
| `references/form-reference-mechanisms.md` | Step 4 — the nine ways a form reaches an endpoint |
| `references/enforcement-rules.md` | Step 8 — how authorization is actually enforced at runtime |
| `references/catalog-schemas.md` | Step 9 — what every field in the catalogue means |
| `references/app-vulnerability-baseline.md` | Step 8 — what this repository owns and can fix |
| `references/package-fix-matrix.md` | Step 8 — confirming a framework fix without framework source |
| `references/disabling-unused-endpoints.md` | Step 10 — the safety gates before recommending a disable |
| `references/recommendations-format.md` | Step 11 — how to write the report |
| `references/remediation-guide.md` | Step 11 — the annexures every recommendation cites |

Executable resources. **Prefer these over ad-hoc curl and one-off scripts** — they exist
because hand-rolling each step produced wrong verdicts (see "Why the scripts exist"):

| Script | Does |
|--------|------|
| `run_audit.py` | **Runs the pipeline in order.** Derives every path, checks freshness, stops at the review gate. Prefer it over invoking the steps by hand |
| `shesha_audit.py` | Shared helpers: HTTP, ownership, the precedence model, run directories, UTF-8. Imported, not run |
| `collect.py` | One pass fetching every piece of live data into the shared cache |
| `source_scan.py` | The A/B/C/D source checks, emitting `file:line` |
| `analyze_forms.py` | Form markup → endpoint, entity, form, permission and opaque references, globally and per form |
| `scan_frontend.py` | Coded screens, routes, components → endpoints, forms, entities, the import graph, and `coded-endpoints.txt` |
| `scan_package_sources.py` | Framework/Enterprise source → endpoints their own pages, components, packaged forms and back-end code call. Scans only the units this app resolves |
| `crossref.py` | Backend surface ∩ everything referenced |
| `probe.py` | Drives `probe_matrix.json` and assigns verdicts honestly |
| `extend_probe_matrix.py` | Generates probes for **this** application from its catalogue. Write endpoints are generated disabled |
| `object_auth.py` | Object-level authorization (IDOR/BOLA), file ownership, workflow tasks. **Needs the second account** |
| `posture_scan.py` | Token and session policy, rate limiting, dependency advisories, secrets in tracked config |
| `build_catalogs.py` | Everything above → the per-package JSON catalogue |
| `catalog_schema.py` | **The catalogue's format, declared once**: fields, order, types, defaults, sort keys. The builder normalises to it, the workbook takes its columns from it, `verify_run.py` enforces it. Imported, not run |
| `digest.py` | The catalogue → the actionable rows only, per package, in priority order |
| `verify_run.py` | Checks the written reports against the catalogue. **Run it before showing anyone the run** |
| `findings.py` | `findings.json` built from the catalogue, and the diff between two runs |
| `export_workbook.py` | **Final step.** The catalogue → `security-catalog-<run>.xlsx`, one worksheet per object type, key columns first |
| `report.py` | Mechanical tables, if a supporting appendix is wanted |
| `probe_matrix.json` | Every probe's **exact** path, verb and content type, read off a live OpenAPI document |

## Why the scripts exist

Three failure modes produced wrong findings when this audit was run by hand, and each one made
an open endpoint look closed:

1. **A guessed route returns 404, and a 404 reads as "endpoint absent → PASS."** A run that
   probed `/api/services/Workflow/Process/...` missed twelve endpoints; the real segment is
   `SheshaWorkflow` and eight of those endpoints were anonymous. Never type a URL from
   memory — take it from the matrix or from the live OpenAPI document.
2. **405 and 415 are not denials.** Wrong verb or wrong content type. `ExecuteHql` and
   `ImportPackage` take `multipart/form-data`; sending JSON yields 415, which says nothing
   about authorization. `RemoveConfigurationsOfMissingClasses` is a DELETE.
3. **A 404 from business logic is not an authorization denial.** If the route exists and the
   `PermissionedObject` record is not `Access=1`, a 404 on a synthetic payload means the
   request *passed* authorization and then failed an entity lookup. When that record says
   AllowAnonymous, the endpoint is anonymously reachable.

The scripts encode all three. If you probe by hand anyway, apply the same rules.

## What makes an application audit different

1. **The framework is a black box.** There is no framework source to grep. Fixes are confirmed
   by live probe first, compiled-assembly inspection second, pinned version last.
2. **The application owns its `Startup.cs` and `appsettings.json`.** Findings that are
   framework concerns upstream — CORS, Swagger and GraphQL gating, security headers, signing
   keys, the Elmah error log — are application findings here, and application templates have
   shipped permissive defaults for all of them.
3. **Every artefact needs an owning package.** App-owned packages are fixed in this
   repository; imported packages are fixed by configuration or an upgrade. Both are this
   application's exposure.

## Run it with the orchestrator

The steps below are the reasoning; `run_audit.py` is how you execute them. It encodes the
dependency graph, derives every path, skips steps whose inputs have not changed, and stops at
the review gate:

```bash
R=.claude/skills/auditing-application-security/resources

# Phase 1 - collect, scan, probe, catalogue
python $R/run_audit.py --repo-root . --lowpriv-user <u> --lowpriv-password <p> \
  --package-source shesha-framework=<framework checkout> \
  --package-source shesha-enterprise=<enterprise checkout>

# ... review (Step 10), recording decisions in catalog/review-overrides.json ...

# Phase 2 - apply the overrides, rebuild, index, verify, export the workbook
python $R/run_audit.py --repo-root . --phase 2 --run-dir security-audits/YYMMDD-HHMM
```

Run the steps by hand only when you are diagnosing one of them. Two orderings are easy to get
wrong by hand and both produce a *wrong audit rather than an error*: `crossref.py` before
`scan_frontend.py` reports everything the coded front-end calls as unused, and skipping the
second `build_catalogs.py` leaves the report disagreeing with the catalogue.

Read the steps anyway — the orchestrator runs the scripts, but the judgement in Steps 2, 7, 8,
10 and 11 is yours.

## Workflow

Copy this checklist and track progress:

```
Phase 1 — catalogue and review
- [ ] Step 1: Run directory, layout, versions, servers
- [ ] Step 2: Ownership and the package set
- [ ] Step 3: Collect live data
- [ ] Step 4: Scan form configurations
- [ ] Step 5: Scan the coded front-end
- [ ] Step 5b: Scan the framework and Enterprise source
- [ ] Step 6: Cross-reference the surface
- [ ] Step 7: Probe — anonymous, low-privilege, object-level, posture
- [ ] Step 8: Application source checks
- [ ] Step 9: Build the per-package catalogue
- [ ] Step 10: Review pass — confirm or override every heuristic

Phase 2 — reporting
- [ ] Step 11: Write {package}-recommendations.md and the index
- [ ] Step 12: findings.json, comparison with the previous run, summary
- [ ] Step 13: Export the reviewer workbook (security-catalog-<run>.xlsx)
```

---

# Phase 1 — Catalogue and review

## Step 1: Run directory, layout, versions, servers

Create the run directory (above) and report it.

Detect the layout rather than assuming it:

```bash
find . -name "*.Web.Host.csproj" -not -path "*/obj/*" -not -path "*/bin/*"
find . -maxdepth 2 -name "next.config.js" -not -path "*/node_modules/*"
cat backend/Directory.Build.props
```

Record the pinned `SheshaVersion`, `EnterpriseVersion` and `SaGovVersion`, and the frontend
`@shesha-io/*` versions from each portal `package.json`. Every package finding is relative to
them, and a frontend and backend on mismatched minor versions is itself worth reporting.

**If more than one front-end exists and only one will be scanned, say so now** — it caps the
confidence of every unreferenced result in the whole audit.

**Backend up?** Probe `GET {BASE_URL}/api/TokenAuth/GetExternalAuthenticationProviders`. If it
does not answer, follow `references/dev-servers.md`. On a cold database the backend takes
10–20 minutes to bind while migrations and bootstrappers run — that is normal; say so before
waiting rather than appearing to hang. With `--no-servers`, report what is missing and stop.

If the backend cannot be started at all, continue with `--skip-live`: the form, front-end and
source scans still work from the repository, and every live check is recorded SKIP. **Never
convert an untestable check into a PASS.**

## Step 2: Ownership and the package set

Read `references/ownership-detection.md` and build `appModules`, `appUrlSegments` and
`appNamespaces`. `collect.py` writes the detected sets to `ownership.json`; confirm them and
report what was found.

`appModules` (Shesha module names, e.g. `Shesha.Hcm`) and `appUrlSegments` (route segments,
e.g. `HcmCommon`) are **different strings**. Conflating them misclassifies both endpoints and
forms.

The package set that the catalogue is grouped by is: every app-owned module, every imported
module observed live, and every front-end code package. `build_catalogs.py` derives it; your
job is to sanity-check the result and reconcile anything that lands in `_unattributed`.

## Step 3: Collect live data

```bash
R=.claude/skills/auditing-application-security/resources
python $R/collect.py --repo-root . --url $BASE_URL --user $USER --password $PASS
```

One pass, into `.claude/.audit-cache/<host>/`: PermissionedObject records of all seven types,
entity configurations, permissions, roles **and their grants**, modules, the endpoint list,
security settings, the main menu, per-entity CRUD permissions, the OpenAPI document, and the
form dump. `forms.json` is tens of megabytes and is the slowest call; it is reused unless
`--refresh` is passed.

Three results are findings in their own right — record them now:

- **Whether the default credentials were accepted.** Authentication *failing* here is a pass.
  If it fails, ask the user for working credentials: the permissioned collection endpoints
  need an account holding `app:Configurator` and `pages:maintenance`.
- **Which PermissionedObject types came back empty.** On Shesha 0.43.x `Shesha.Entity` and
  `Shesha.Entity.Action` are normally empty because `EntityPermissionedObjectProvider` is
  inactive — which means entity access resolves *entirely* through `DefaultEndpointAccess`.
  Report it; do not re-investigate it on every run.
- **Anything that returned 403.** That is the audit account lacking a permission, not a
  missing endpoint.

**A `/swagger/v1/swagger.json` that returns 500 is not a finding.** OpenAPI generation
routinely exceeds time or memory limits on a large Shesha application. `collect.py` retries and
keeps any cached copy — without a surface, a disabled endpoint cannot be told from a wrong
route.

### Step 3b: The second principal

**This is the difference between an audit that proves configuration and one that proves
behaviour.** With one administrator account, every "any logged-in user can reach X" is
inferred from `DefaultEndpointAccess`. The inference is sound but it is not evidence, and it
can be wrong in both directions. Object-level authorization is undetectable with one account:
as an administrator, every id is legitimately yours.

Ask the user for one of:

1. **An existing low-privilege account** — best. A real user holding no administrative roles.
2. **Permission to create a throwaway account.** This is a state change and a persistent
   credential, so **ask first** and never on production. Record the username in the report so
   it can be removed.
3. **Neither** — proceed, and mark every affected finding **DERIVED**, with the report stating
   that object-level authorization was not testable.

## Step 4: Scan form configurations

Read `references/form-reference-mechanisms.md` first — it is the checklist of every way a form
reaches an endpoint without naming it, and the accuracy of the whole "unused" conclusion
depends on covering all nine.

```bash
python $R/analyze_forms.py --repo-root . --url $BASE_URL
```

Produces both views of the same data: the global index (endpoint → forms) and `perForm`, which
is what the configured-forms catalogue is built from. It also captures, per form, the
**opaque** references — a URL built at runtime — with the snippet windowed around the code
that builds it and a guessed URL where one can be extracted.

Take the opaque count seriously. It is the honest measure of how far any "unreferenced"
conclusion can be trusted.

## Step 5: Scan the coded front-end

```bash
python $R/scan_frontend.py --repo-root .
```

One record per coded source file: its route, kind, endpoints, forms, entities, permissions,
opaque URL builds, and who imports it. Also writes `coded-endpoints.txt`, which Step 6 needs.

A coded screen nothing routes to and nothing imports is the same dead surface as an
unreferenced form configuration — check it is not exported for another package before calling
it dead.

## Step 5b: Scan the framework and Enterprise source

```bash
python $R/scan_package_sources.py --repo-root . \
  --package-source shesha-framework=<framework checkout> \
  --package-source shesha-enterprise=<enterprise checkout>
```

The application's scans see only the application. The framework and Enterprise ship their own
admin pages, components and form packages, and those call endpoints too — the permissioned
objects page, the workflow inbox, the file list. Skip this step and each of those endpoints
reads as unreferenced, which is exactly the input that produces a RESTRICT or DISABLE.

What it counts, and what it does not:

- **Only units this application ships.** A directory with a `*.csproj` counts only if the
  Web.Host's `obj/project.assets.json` resolves that project name; one with a `package.json`
  only if that package is installed under a front-end's `node_modules`. Demo apps, starter
  templates, test projects and modules the application does not use are excluded and listed.
  It therefore needs a restored backend and an installed front-end.
- **Packaged forms: the latest version only.** `ConfigMigrations/*.shaconfig` keeps every
  historical package; the database ends up with the newest copy of each item, so older copies
  are dropped as superseded rather than counted as evidence.
- **Back-end:** HTTP calls to `/api/...` count as references (there are normally none — the
  back-end calls its own services in-process). An in-process mention of a service class does
  **not** mark the endpoint referenced; it is `packageBackendCodeReferences`, a gate against
  disabling, just like `backendCodeReferences` for this repository's own C#.
- **Forms too:** `formId: { module, name }` in package code and packaged configuration items,
  and literal `new FormIdentifier("module", "name")` in C#, count as the package opening that
  form. A packaged form's own identifier inside its markup is not a reference to itself.
- **Versions:** the checkout's branch and commit are recorded. Say in the report when they
  differ from the version the application pins.

### When the source is not available

Often it is not: the framework and Enterprise are consumed as packages, and their source may
not be at hand. **Proceed anyway** — the step still runs, and records coverage instead:

- `package_source_refs.json` → `coverage` lists the imported `@shesha-io/*` front-end packages
  (linked workspace packages excluded — they are the app's own code) and which were scanned.
- `build_catalogs.py` sets `packageSourcesNotScanned` on every **package-owned** endpoint,
  entity and configured form: the imported front-end packages not scanned, plus the owning
  module when none of its projects were scanned. Where that list is non-empty, an
  unreferenced row is recommended **REVIEW**, never DISABLE, RESTRICT or REVIEW-FOR-REMOVAL
  on usage grounds. Access-level recommendations (AllowAnonymous, open to any logged-in user
  and sensitive) are unaffected — they do not depend on who calls the endpoint.
- Every unscanned package is added to `inputsMissing` as `<package> source`, so
  `verify_run.py` fails until the index names it.
- `run_audit.py` warns at the start and the end of phase 1.

**Tell the user what this means**, in the index's coverage section and when summarising:
without a package's source, every endpoint and form only that package's own screens use
**looks unreferenced**. Acting on those as if they were unused would break the package's
screens. In the first run that scanned framework and Enterprise source for this skill, 96
endpoints flipped from unreferenced to referenced and 27 disable recommendations were
withdrawn. Say which packages were not scanned, how many rows were capped at REVIEW
(`_index.json` → `confidence.unreferencedCappedAtReviewForUnscannedSource`), and that
supplying the source with `--package-source` lifts the cap.

## Step 6: Cross-reference the surface

```bash
python $R/crossref.py --repo-root . \
  --coded-endpoints .claude/.audit-cache/<host>/coded-endpoints.txt
```

Order matters: Steps 4, 5 and 5b must all have run, or the referenced set is incomplete and
endpoints the front-end genuinely calls will read as unused. `crossref.py` picks up
`package_source_refs.json` from the cache and marks those references as
`<source>-frontend`, `<source>-backend` or `<source>-packaged-form`.

`crossref.py` expands entity bindings into CRUD routes, owner bindings into the StoredFile and
Notes families, reference lists into `ReferenceList/GetByName`, and form references into form
fetches; then it intersects with the OpenAPI surface and prints a confidence line.

## Step 7: Probe

```bash
python $R/probe.py --repo-root . --lowpriv-user <u> --lowpriv-password <p>
python $R/object_auth.py --repo-root . --lowpriv-user <u> --lowpriv-password <p>
python $R/posture_scan.py --repo-root .
```

Skip under `--skip-probes` or `--skip-live`, and record that in the report.

`probe.py` drives `probe_matrix.json` — framework hardening, the workflow surface, the
identity-table privilege paths, app-owned developer surfaces, and the expected-anonymous
allowlist. Read the verdicts literally:

| Verdict | Meaning |
|---------|---------|
| `OPEN` | 200 where denial was expected. A finding |
| `REACHED` | 400/500 — authorization did not block; business logic ran. A finding |
| `NOT-FOUND` | 404, route exists, record is not `Access=1`. **Not a pass.** Business logic ran and failed a lookup. If the record says AllowAnonymous, treat as OPEN |
| `INCONCLUSIVE` | 405/415. Wrong verb or content type — fix the matrix and re-probe. Never a pass |
| `DISABLED` | 404, route exists, record `Access=1`. A genuine pass |
| `ABSENT` | 404, route not in the surface. Pass, but record "absent", never "fixed" |
| `UNREACHABLE` | 000. The backend is down. Never a verdict |
| `EXPECTED` | 200 where anonymous access is allowlisted. Pass |

`probe_matrix.json` ships the **framework** surface. This application's own surface is
different on every deployment, so extend the matrix from the catalogue and probe again:

```bash
python $R/extend_probe_matrix.py --run-dir $RUN --dry-run    # see what it would add
python $R/extend_probe_matrix.py --run-dir $RUN              # add it
python $R/probe.py --repo-root . --lowpriv-user <u> --lowpriv-password <p>
python $R/build_catalogs.py --repo-root . --run-dir $RUN     # so the verdicts land
```

It generates an anonymous probe for every endpoint resolving to AllowAnonymous, a
low-privilege probe for the sensitive endpoints open to any authenticated user (capped per
package — a handful converts the derived claim into an observed one, hundreds just bloat the
matrix), and a read of every sensitive entity with a live read route. Expectations come from
the **reviewed** disposition, so a `KEEP`/`KEEP-INFRA` endpoint is generated as
`anonymous-ok` rather than manufacturing a false finding on the login and password-reset
family every run.

**Write endpoints are generated `enabled: false`.** "Probe every unprotected write endpoint"
and "corrupt the database" are the same request, so those are documented but not sent;
`probe.py --include-disabled` fires them, and only against a database you can restore.

This step was skipped on the first run of this skill, and it cost real coverage: the three
`ConfigurationItemUtilities` routes — any logged-in user rewriting every form in a module —
were never probed and were found by reading an unattributed bucket by hand.

For anything returning 200, capture the body and quote the field names. "Returns 200 with
employee identity numbers and salary bands" gets fixed; "returns 200" does not.

`object_auth.py` answers the question endpoint probes structurally cannot: may this user see
**this row**. Its remediation is a global specification, **not** an entity action permission —
a permission gates the endpoint, a specification gates the row. Saying "configure entity
permissions" in response to an IDOR finding is wrong advice, and it is the mistake an
endpoint-focused audit is most likely to make.

`posture_scan.py` covers token and session policy, rate limiting and lockout, dependency
advisories and secrets in tracked configuration. Judge a signing key by **entropy, not
length**: 32 alphanumeric characters is ~165 bits and is not brute-forceable, so do not report
it as weak — a committed key of adequate strength is a *disclosure* finding whose fix is
rotation. Read rate-limiting **configuration**; never run a brute-force burst to prove its
absence.

## Step 8: Application source checks

```bash
python $R/source_scan.py --repo-root .
```

Then read `references/app-vulnerability-baseline.md` and interpret what it found. It covers
sections A to D — web host configuration, settings files, services and controllers, entities
and specifications — and emits `file:line` for every hit. **Cite its line numbers rather than
your own**: an earlier hand-written audit of this repository cited four `Startup.cs` line
numbers from memory and all four were wrong.

The scanner reports facts, not severities. Rating them is yours.

Two checks deserve to be looked at before anything else:

- **A9, the authorization filter.** If `SheshaAuthorizationFilter` is not registered, no
  Shesha endpoint authorization runs at all, every other finding is downstream of it, and it
  is the report's headline.
- **A11, the Elmah error log.** `app.UseSheshaElmah()` is ASP.NET middleware, mounted outside
  MVC, so the authorization filter never sees it — a correctly configured authorization chain
  provides no protection whatsoever. Stored records include the full request header block,
  which means live `Bearer` tokens. Probe `/elmah`, `/elmah/api/errors?i=0&s=5` and
  `/elmah/api/error`; if any answers, decode a captured token's `exp` claim to establish
  whether it is still valid. Rate it CRITICAL when it is.

Read `references/enforcement-rules.md` before classifying any access level. Do not infer an
access level from a code attribute — the database record is what is enforced.

For package-owned behaviour, read `references/package-fix-matrix.md` and use
`mcp__handmirror__get_type_info` on the types in `probe_matrix.json` under `assemblyChecks` to
tell "secured because the package ships the attribute" apart from "secured because someone
configured the database record". Only the first survives a database reset. **A probe outranks
the matrix, and the assembly explains why.**

## Step 9: Build the per-package catalogue

```bash
python $R/build_catalogs.py --repo-root . --run-dir $RUN
```

Read `references/catalog-schemas.md` before interpreting any of it. Six artefacts per package:

| Artefact | Answers |
|----------|---------|
| `{package}-roles-and-permissions.json` | Which permissions exist, which roles hold them, and — counted by source — whether anything references them at all |
| `{package}-configured-forms.json` | Every live form configuration: is it reachable, from where, and what does it call |
| `{package}-custom-forms.json` | The same questions for coded screens and components |
| `{package}-endpoints.json` | Every custom endpoint (dynamic entity CRUD excluded): effective access, who enforces it, who calls it, how sensitive, what to do |
| `{package}-entities.json` | Every entity: which CRUD letters are live, how they are authorized, whether rows are filtered, who binds to it |
| `{package}-other-findings.json` | Everything not about endpoint or entity surface: host configuration, secrets, tokens, rate limiting, dependencies, probe verdicts, object-level exposures |

Then read `_index.json`. Its `inputsMissing` and `confidence` blocks are the audit's honesty
record and both must reach the report.

## Step 10: Review pass

The catalogue's `sensitivity` and `recommendedAction` fields are **heuristics from names and
access levels**. This step is where they become judgements. Do not skip it, and do not write
the report straight from the heuristics.

```bash
python $R/digest.py --run-dir $RUN --limit 12
```

This prints only the actionable rows, per package, grouped by theme in priority order — one
screen per package instead of sixty JSON files. Work through it and, for every row that would
reach the report:

1. **Confirm the sensitivity.** The rating came from the artefact's *name*. Open the entity or
   endpoint and confirm what it actually holds before writing anything about salary, medical
   or identity data.
2. **Confirm the disposition.** Apply the safety gates in
   `references/disabling-unused-endpoints.md` to every `DISABLE-*`. Anything touched by an
   opaque reference, a back-end caller, a package-owned form, an unscanned front-end or a
   plausible external integration becomes `REVIEW` — and `REVIEW` is a perfectly good
   outcome. **Prefer `RESTRICT` to `DISABLE` wherever a caller is plausible**: restricting
   fails visibly as a 403 and is reversible, disabling returns 404 and looks like a bug.
3. **Check the allowlist** in `app-vulnerability-baseline.md` section G before reporting any
   anonymous endpoint. Login, password reset, CSRF token and public form loading belong there.
4. **Reconcile `_unattributed` and `_app-unattributed`.** An unclassified app endpoint is
   exactly what an audit must not lose. Re-attribute what you can; report the rest by count.
5. **Fold the internal packages in.** `_probe-findings` and `_object-authorization` rows
   belong to the package that owns the endpoint or entity.

Record every decision in `catalog/review-overrides.json` — the file `build_catalogs.py` writes
a template for — then **re-run `build_catalogs.py`**. Overrides can set `sensitivity`,
`recommendedAction`, `severityHint`, `status` and `package`, and each needs a `note`:

```json
{
  "endpoints": {
    "/api/services/Hcm/HcmHealthCheck/Check": {
      "recommendedAction": "KEEP", "sensitivity": "LOW",
      "note": "Load balancer health probe; returns no data. Accepted."
    }
  },
  "entities": {
    "Shesha.Leave.Domain.LeaveRequest": {
      "sensitivity": "HIGH",
      "note": "Confirmed: holds medical certificate attachments."
    }
  }
}
```

This is what keeps the report and the catalogue arithmetically identical. Every number in the
report comes from the rebuilt catalogue or from `digest.py` — never from a second, independent
count.

---

# Phase 2 — Reporting and recommendations

## Step 11: Write the recommendations

Read `references/recommendations-format.md` and follow it. It carries the section order, the
jargon translation table, a worked example and the finishing checklist.

The rules that matter most, because they are the ones that make a report get acted on:

- **One file per package**, `{package}-recommendations.md`, plus one
  `recommendations-index.md` at the root of the run directory.
- **Only negative findings you recommend actioning.** No "checked and clean", no
  low-priority padding, no section saying "no issues found" — omit the section instead.
- **Succinct.** One or two lines per finding. Where forty rows share a shape, report the
  pattern, the count and the worst five, and point at the catalogue file for the rest.
- **Priority order within every section**, and app-owned before package-owned on ties.
- **Every finding: where, what someone could do with it, and the fix.**
- **No security jargon.** Write it so a junior developer understands both the risk and the
  change. `recommendations-format.md` has the translations.
- **Where remediation needs code, cite the annexure** in `references/remediation-guide.md`
  rather than inlining a tutorial. If a fix is not covered there, add it to the guide so the
  next run inherits it.
- **The index ends with the top five to action immediately** — across all packages, only if
  genuinely urgent. Four real items beat five padded ones.
- **State what was not covered.** Skipped probes, missing inputs, unscanned front-ends, no
  second account, and the areas out of scope: injection testing (JsonLogic filter parameters,
  GraphQL, HQL), stored-markup XSS, infrastructure and deployment. An audit silent about its
  own boundaries reads as more complete than it is.

Mark clearly which claims are **observed** (a probe, or the low-privilege account actually
reaching something) and which are **derived** from configuration. Both are legitimate;
presenting the second as the first is not.

## Step 12: Verify, index, compare, summarise

**Verify first, and do not skip it.** The reports assert numbers, paths and severities that
must all trace back to the catalogue, and checking that by eye does not work — the first run
of this skill drifted three per-package counts after the review overrides were applied, put
three wrong package names in a dependency finding, and reproduced twelve characters of a
signing key in a report.

```bash
python $R/verify_run.py --run-dir $RUN --repo-root .
```

It checks: that every catalogue file matches `catalog_schema.py` (fields, order, types,
sorting); the per-package and totals tables against the catalogue; that every package with
actionable rows has a report or is named in the index; that every quoted path exists; that no
secret material reached the output; that every missing input is disclosed; that no review
override matched nothing; that all four posture groups have a result; and that `findings.json`
is not stale. A FAIL means fix and re-run — including re-running `build_catalogs.py`, because a
stale catalogue file is one of the things it catches.

The one WARN it is normal to carry is `reviewed-citations`: rows cited in prose whose severity
is still the machine heuristic. Drive it down for anything you rate CRITICAL or HIGH.

```bash
python $R/findings.py --run-dir $RUN
python $R/findings.py --diff <previous-run> $RUN     # when a previous run exists
```

`findings.json` is built from the catalogue, not from the report's prose, so run it after the
review-pass rebuild in Step 10 — the two then cannot disagree. If it warns that no overrides
were applied, the review pass has not been completed.

Put the comparison in `recommendations-index.md`: fixed since, still open, newly found, and
the direction of travel. Say "baseline audit" when there is no earlier run.

If a finding is a correction of an earlier run rather than something new, mark it inline and
say what the earlier run got wrong. An audit that quietly revises itself is
indistinguishable from one that was right first time, and the reader needs to know which
checks are fragile.

## Step 13: Export the reviewer workbook

The standard output of the skill, and always the last thing produced. `run_audit.py --phase 2`
runs it after `verify_run.py` passes; by hand:

```bash
python $R/export_workbook.py --run-dir $RUN     # -> $RUN/security-catalog-<run>.xlsx
```

One worksheet per object type — Findings, Entities, Roles, Permissions, Custom Forms,
Configured Forms, Endpoints. Module is always the first column and the source catalogue file
the last. The columns a reviewer needs to decide the next action come first (what the object
is, `recommendedAction`, effective access, whether anything uses it, `recommendationBasis`);
every other field declared in `catalog_schema.py` follows. Columns are fixed by the schema,
not by the data, so every run's workbook has the same columns in the same places, including
columns no row populates. Change the order in `LEAD` in the
script, not by hand in the output.

It reads only the catalogue, so it agrees with the reports by construction. Reviewers annotate
the workbook directly; if it already exists and differs from what would be written, the old
copy is kept as `.bak-<stamp>.xlsx` rather than overwritten.

Finish by printing, to the user: the package count, the per-package urgent counts, the top
five, the confidence caveats, the path to the run directory, and the path to the workbook.

Then stop the servers if this session started them — `references/dev-servers.md`, Stopping.

## The honesty rules, in one place

1. A check that could not run is **SKIP**, never PASS, and it appears in the report by name.
2. A missing input caps what can be claimed, and the report says so.
3. `isUnreferenced` means "the scanned front-end does not reach it" — never "safe to delete".
4. An opaque reference outranks an unreferenced verdict — and so does an imported package
   whose source was not scanned: its own screens may be the caller.
5. `hardcoded: true` changes the remediation, not the severity: configuration will be
   re-seeded away, so say what the real options are.
6. Derived is labelled derived.
7. Severity is rated by impact on **this application's data**, not by the abstract class of
   the issue. Anonymous read access to a leave-balance entity in an HR system is CRITICAL
   even where "anonymous read" is benign elsewhere.
