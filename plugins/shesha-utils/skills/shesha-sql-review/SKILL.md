---
name: shesha-sql-review
description: Deterministic SQL and database review for a BoxFusion Shesha / ABP application — schema, indexes, stored procedures, functions, views, raw SQL in code, and migrations. Finds what will degrade or break as data grows, what is wrong or dangerous, and what grows unbounded, and emits findings.json per the shared TLC contract so two runs on the same commit produce identical findings. The SQL division of the BoxFusion TLC collection — the conductor dispatches to it, or run it on its own for a database-layer review. Use when asked to review, audit or health-check a Shesha app's SQL, database, schema, indexes, stored procedures, functions, views or migrations, or when triaging queries that are slow or that grow without bound.
---

# Shesha SQL review (TLC SQL division)

Reviews the **database layer** of a BoxFusion Shesha / ABP system and returns a ranked, plain-English, no-blame set of findings — each one proven to the evidence level the environment allows, with a framework-native remediation and a regression test. It is one division of the BoxFusion **TLC** collection; it shares the collection's determinism contract so its output merges cleanly with the other divisions.

## The shared contract (read these first — they are not optional)

This skill owns **only** its check catalogue. Everything about *how* it produces findings — the rules, the output shape, the safety rules — lives in the plugin's shared `tlc-core` library and is binding:

- **`${CLAUDE_PLUGIN_ROOT}/shared/operating-standard.md`** — the determinism & quality contract (§0–9): the capability manifest, checks-as-decision-procedures, stable `CHECK-ID@anchor` ids, the closed evidence enum, scored severity, templated remediation, and `findings.json` as the normalized diff surface.
- **`${CLAUDE_PLUGIN_ROOT}/shared/briefs/inspector-briefs-and-partitions.md`** — the canonical **division inspector brief** (fill only the placeholders), the fixed sub-area partitions, and the orchestration rules. Run exactly to this brief; invent nothing outside it.
- **`${CLAUDE_PLUGIN_ROOT}/shared/safety-and-data-access.md`** — QA-first, production escalation, isolation + canary, the **secret-redaction rule** (presence + length band only, never a value), and PII handling.
- **`${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`** — the Shesha / ABP native mechanism for each kind of fix.
- **`${CLAUDE_PLUGIN_ROOT}/shared/templates/finding.md`**, **`report.md`**, **`shesha-team-report.md`** — the finding, report and framework-defect shapes.

## This skill's check catalogue

- **`checks/sql.md`** — the SQL decision procedures (SQL-A … SQL-H): craftsmanship (static), physical & growth (data-level), integrity & release path. Each check names its exact input, predicate, anchor rule, evidence source, `plan_id` and regression test. Run its procedures **verbatim** — zero improvisation.
- **`sql/diagnostic-queries.sql`** — the SQL Server diagnostic queries. Run with `sqlcmd -i` against an **isolated local copy**, never a live QA/Test/production database (see the safety rules).

## Sub-area (for a team split)

The SQL division's fixed partition, from the shared briefs:
- **craftsmanship (static)** = SQL-C (16 vectors; `groupby-hiding-dup` is NON-DETERMINISTIC — excluded from the diff)
- **physical & growth (data-level → `NOT-ASSESSED` when static)** = SQL-A, SQL-B, SQL-D, SQL-E
- **integrity & release path** = SQL-F, SQL-G, SQL-H

Only the check-id set differs between team members; every other brief field is shared, so a team split and a single-operator run merge byte-identically.

## How to run

1. **Resolve capability first.** Build the manifest fields this division needs (operating-standard §1): is there an **isolated local DB copy** (and did the canary pass), is it **SQL Server** (the checks and tooling assume it — a PostgreSQL-only system means the data-level checks are `NOT-ASSESSED(no-sqlserver-copy)`), and is `sqlcmd` present. A check whose capability is absent returns **`NOT-ASSESSED(reason)`** — a first-class verdict, never a silent pass.
2. **Run every check in `checks/sql.md`** against its input, to the division brief. The static craftsmanship checks run from the repo; the physical/growth checks need the isolated copy.
3. **Emit `findings.json`** (operating-standard §8), each record `{finding_id: SQL-X@anchor, check_id, area: "sql", anchor, evidence_level, execution_class, severity, severity_inputs, plan_id, root_cause, fix_order_rank, sources[], not_assessed_reason}`, sorted canonically, stamped with the manifest `commit_sha` + hash. The prose report is derived from it.

**Standalone:** write `findings.json` + a short markdown summary to an external run folder (never inside the app repo on a read-only run). **Dispatched by the conductor:** return the findings per the brief; the conductor persists and merges them with the other divisions.

## Ground rules (from the contract)

- **Diagnose only** — never modify the application, its schema or its data during review.
- **Framework first** — every proposed fix uses the Shesha / ABP native mechanism (`${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`); bypassing the framework is itself a finding.
- **Data safety** — work on an isolated local copy; personal data never leaves the machine; report counts, never values; secrets as presence + length band only.
- **No blame** — describe what the system does, never who did it. Route genuine framework defects to the Shesha-team report.
- **Proof before ranking** — every finding carries an honest evidence level; an unproven high-severity finding is worded "the schema allows…" until reproduced.

## Files

- `checks/sql.md` — the SQL check catalogue (this skill's sole area authority).
- `sql/diagnostic-queries.sql` — SQL Server diagnostic queries (`sqlcmd -i`).
- The contract, briefs, templates and safety rules live in `${CLAUDE_PLUGIN_ROOT}/shared/` — read, never copied.
