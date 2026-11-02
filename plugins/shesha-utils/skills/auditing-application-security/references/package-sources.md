# Step 5b — Framework and Enterprise source

Read at Step 5b of `SKILL.md`, after running `scan_package_sources.py`.


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
