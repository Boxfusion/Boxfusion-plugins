# Audit resources

Stdlib-only Python 3.8+. No pip install, no external dependencies.

## Scripts

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
| `extend_probe_matrix.py` | Generates probes for **this** application from its catalogue, plus the framework-entity CRUD sweep (every package-owned entity, signed out and low-privilege). Write endpoints are generated disabled |
| `drift.py` | Compares two `collect.py` captures (old vs new build, or first start vs restart): widened or reset permission records, lost records, role-grant changes, removed routes that forms still call. Exit 1 on the dangerous kinds |
| `object_auth.py` | Object-level authorization (IDOR/BOLA), file ownership, workflow tasks. **Needs the second account** |
| `posture_scan.py` | Token and session policy, rate limiting, dependency advisories, secrets in tracked config |
| `build_catalogs.py` | Everything above → the per-package JSON catalogue |
| `catalog_schema.py` | **The catalogue's format, declared once**: fields, order, types, defaults, sort keys. The builder normalises to it, the workbook takes its columns from it, `verify_run.py` enforces it. Imported, not run |
| `digest.py` | The catalogue → the actionable rows only, per package, in priority order |
| `verify_run.py` | Checks the written reports against the catalogue, and that probes ran signed out, as the low-privilege user and with the framework-entity sweep. **Run it before showing anyone the run** |
| `findings.py` | `findings.json` built from the catalogue, and the diff between two runs |
| `export_workbook.py` | **Final step.** The catalogue → `security-catalog-<run>.xlsx`, one worksheet per object type, key columns first |
| `report.py` | Mechanical tables, if a supporting appendix is wanted |
| `probe_matrix.json` | Every probe's **exact** path, verb and content type, read off a live OpenAPI document |

## Pipeline

Order matters. Each step reads what the previous ones wrote.

**Use `run_audit.py` unless you are diagnosing a single step.** It encodes the graph below,
derives every path, skips what is already fresh and stops at the review gate:

```bash
R=<skill-dir>/resources
python $R/run_audit.py --repo-root . --lowpriv-user <u> --lowpriv-password <p>
# ... review, record decisions in <run>/catalog/review-overrides.json ...
python $R/run_audit.py --repo-root . --phase 2 --run-dir security-audits/YYMMDD-HHMM
```

The graph it runs, if you need to drive it by hand:

```bash
RUN=$(python -c "import sys;sys.path.insert(0,'$R');from shesha_audit import new_run_dir;print(new_run_dir('.'))")
C=.claude/.audit-cache/localhost_21021          # <host> varies

python $R/collect.py       --repo-root .                     # live data -> shared cache
python $R/source_scan.py   --repo-root .                     # A/B/C/D source checks, file:line
python $R/analyze_forms.py --repo-root .                     # form markup -> references, per form
python $R/scan_frontend.py --repo-root .                     # coded screens -> references + coded-endpoints.txt
python $R/scan_package_sources.py --repo-root . --package-source shesha-framework=<path> \
                                  --package-source shesha-enterprise=<path>  # framework/Enterprise callers
python $R/crossref.py      --repo-root . --coded-endpoints $C/coded-endpoints.txt
python $R/probe.py         --repo-root . --lowpriv-user <u> --lowpriv-password <p>
python $R/object_auth.py   --repo-root . --lowpriv-user <u> --lowpriv-password <p>
python $R/posture_scan.py  --repo-root .
python $R/build_catalogs.py --repo-root . --run-dir $RUN     # -> $RUN/catalog/*.json
python $R/extend_probe_matrix.py --run-dir $RUN              # app-specific probes
python $R/probe.py          --repo-root . --lowpriv-user <u> --lowpriv-password <p>
python $R/build_catalogs.py --repo-root . --run-dir $RUN     # so the new verdicts land
python $R/digest.py         --run-dir $RUN                   # actionable rows, priority order
# ... review, record decisions in $RUN/catalog/review-overrides.json ...
python $R/build_catalogs.py --repo-root . --run-dir $RUN     # re-run to apply the overrides
# ... write {package}-recommendations.md and the index ...
python $R/verify_run.py     --run-dir $RUN --repo-root .     # reports vs catalogue - gate
python $R/findings.py       --run-dir $RUN                   # index built FROM the catalogue
python $R/export_workbook.py --run-dir $RUN                  # -> $RUN/security-catalog-<run>.xlsx
```

Three ordering rules that are easy to get wrong and quietly produce false results:

- **`crossref.py` after both `analyze_forms.py` and `scan_frontend.py`.** Without
  `coded-endpoints.txt`, everything the coded front-end calls looks unreferenced.
- **The catalogue's format lives in `catalog_schema.py`.** `build_catalogs.py` normalises every
  row to it, `export_workbook.py` takes its columns from it and `verify_run.py` fails a run
  that deviates. Change the format there first, never only in the builder.
- **`build_catalogs.py` twice.** The first run writes an empty `review-overrides.json`; the
  second applies what the review put in it. Skipping the second means the report and the
  catalogue disagree.
- **`extend_probe_matrix.py` after the first `build_catalogs.py`, then probe again.** It reads
  the catalogue, so it cannot run before one exists - and its expectations come from the
  reviewed disposition, so running it after the review is better still.
- **`verify_run.py` last, after the reports are written.** It is the gate: it compares what the
  reports claim against what the catalogue holds. Running the audit without it is how three
  per-package counts, three package names and twelve characters of a signing key reached a
  finished report on the first run of this skill.
- **`export_workbook.py` after `verify_run.py`.** The workbook is the standard hand-off to
  reviewers, so it is only produced from a catalogue that has passed the gate. It never
  overwrites a reviewer's edits: a differing existing workbook is kept as `.bak-<stamp>.xlsx`.

Diff two runs:

```bash
python $R/findings.py --diff security-audits/260830-1557 security-audits/260901-0930
```

## Output locations

| Directory | Contents | Committed? |
|---|---|---|
| `security-audits/YYMMDD-HHMM/` | `recommendations-index.md`, `{package}-recommendations.md`, `security-catalog-YYMMDD-HHMM.xlsx`, `catalog/*.json` | **yes** — the history is the point |
| `.claude/.audit-cache/<host>/` | raw captures: form dump, PermissionedObject records, swagger, scans, probe results | **no** — gitignored, holds credentials and captured tokens |

`shesha_audit.new_run_dir(repo_root)` and `latest_run_dir(repo_root, before=...)` are the
helpers. Runs are never overwritten, which is what lets one run be compared with the previous.

## Cache

`.claude/.audit-cache/<host>/` — gitignored, and it must stay that way. It holds a full form
dump (tens of MB) and, wherever an endpoint like `/elmah` is exposed, captured request headers
containing **live bearer tokens**.

`forms.json` is the slowest call in the audit and is reused unless `--refresh` is passed.
`collect.py`'s per-entity `ModelConfigurations` pass is the second slowest; `--skip-entity-permissions`
opts out, at the cost of entity `authorizationRules` falling back to the global default only.

`posture_scan.py` is the third: its dependency scan takes minutes. Use `--only T,R,G` to re-run
the fast checks - results **merge** into `posture.json` and a per-group provenance block records
when each group last ran, so re-running one check no longer deletes the others.

## The second account

`object_auth.py` requires a zero-permission principal and `probe.py` uses one when given. This
is the single biggest determinant of how much the audit actually proves.

Without it, every "any logged-in user can reach X" statement is **derived** from
`DefaultEndpointAccess` plus the enforcement model. The inference is sound, but it is not
evidence, and it can be wrong both ways — a global specification or a custom
`ICustomPermissionChecker` may restrict something the configuration suggests is open.

More importantly, object-level authorization is **undetectable** with one account: as an
administrator every id is legitimately yours, so a 200 tells you nothing about whether
row-level access control exists.

Creating the account is a state change and a persistent credential. Ask first, never do it on
production, and record the username in the report so it can be removed.

## The three rules the probe scripts encode

Each corresponds to a way an earlier run recorded an open endpoint as closed.

1. **Never type a URL from memory.** A guessed route 404s, and a 404 reads as "absent →
   PASS". Probing `/api/services/Workflow/Process/...` missed twelve endpoints because the
   real segment is `SheshaWorkflow`; eight of them were anonymous. Paths, verbs and content
   types live in `probe_matrix.json`, read off a live OpenAPI document.
2. **405 and 415 are not denials.** Wrong verb, wrong content type. `ExecuteHql` and
   `ImportPackage` want `multipart/form-data`; `RemoveConfigurationsOfMissingClasses` is a
   DELETE; `FormConfiguration/UpdateMarkup` is a PUT. `probe.py` scores these `INCONCLUSIVE`
   and refuses to call them passes.
3. **A 404 from business logic is not an authorization denial.** If the route exists and the
   `PermissionedObject` record is not `Access=1`, the request passed authorization and then
   failed an entity lookup. When that record says AllowAnonymous, the endpoint *is*
   anonymously reachable — `probe.py` scores it `NOT-FOUND` and says so.

## What these scripts deliberately do not do

They produce data and selections. They do not assign final severities, decide whether an
anonymous endpoint is acceptable, judge ownership edge cases, or write prose — those are the
audit's actual work, and scripting them would make the output worse rather than faster.

`build_catalogs.py` emits `sensitivity` and `recommendedAction` as heuristics carrying
`reviewRequired: true`, and `digest.py` prints them terse enough that pasting them into a
report is obviously not a report. The review phase's decisions go into
`review-overrides.json`, which the next `build_catalogs.py` run folds in — so the catalogue,
not a second computation, stays the single source of every number.

## Out of scope, on purpose

Injection testing (JsonLogic `filter` parameters, GraphQL, HQL), front-end XSS through stored
form markup, and infrastructure review are real gaps that need different tooling and a
different method.

The report must **say so**. A reader cannot otherwise tell "checked and clean" from "never
looked at", and an audit silent about its own boundaries reads as more complete than it is.

## Maintaining probe_matrix.json

`extend_probe_matrix.py` generates the application-specific half from the catalogue and marks
each one with `generatedFrom`, so `--prune` drops and regenerates them without touching the
hand-maintained probes. Regenerate after a catalogue rebuild; it is idempotent otherwise.

Add a probe by hand when a run finds a route neither the matrix nor the catalogue has - take
the verb and content type from the live OpenAPI document rather than inferring them. Record
`severityIfOpen` and, where the result needs a human call, set `expect: "judgement"` and say
what to look for in `note`. Set `enabled: false` on anything that changes state.

`assemblyChecks` records what a type's compiled attributes actually show at a pinned version.
The entries there were verified by reading `Shesha.Application.dll` at 0.43.37 and contradict
`package-fix-matrix.md`'s general expectations — a probe outranks the matrix, and the assembly
explains why.
