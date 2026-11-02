# Phase 2 — Reporting and recommendations

Steps 11–13 of `SKILL.md`. `$R` is `<skill-dir>/resources` and `$RUN` the run directory from Step 1.

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
