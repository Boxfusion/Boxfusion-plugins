---
name: shesha-orm-review
description: Deterministic data-access and ORM review for a BoxFusion Shesha / ABP system — entity mappings, dynamic CRUD, GraphQL, GetAll, repositories, lazy loading, specifications and filters. Finds where the system over-fetches, searches every field, skips paging, or loads related records the slow way, and emits findings.json per the shared TLC contract so two runs on the same commit produce identical findings. The ORM division of the BoxFusion TLC collection — the conductor dispatches to it, or run it on its own for a data-access review. Use when asked to review, audit or health-check a Shesha app's data fetching, ORM, queries, N+1, paging, specifications, lazy loading or GraphQL data exposure.
---

# Shesha ORM / data-access review (TLC ORM division)

Reviews **how the system fetches data** in a BoxFusion Shesha / ABP system and returns a ranked, plain-English, no-blame set of findings — each proven to the evidence level the environment allows, with a framework-native remediation and a regression test. One division of the BoxFusion **TLC** collection; it shares the collection's determinism contract so its output merges cleanly with the other divisions.

## The shared contract (read these first — not optional)

This skill owns **only** its check catalogue. How it produces findings lives in the plugin's shared `tlc-core` library and is binding:

- **`${CLAUDE_PLUGIN_ROOT}/shared/operating-standard.md`** — the determinism & quality contract (§0–9).
- **`${CLAUDE_PLUGIN_ROOT}/shared/briefs/inspector-briefs-and-partitions.md`** — the canonical division inspector brief, sub-area partitions, orchestration rules. Run exactly to this brief.
- **`${CLAUDE_PLUGIN_ROOT}/shared/safety-and-data-access.md`** — QA-first, isolation, the secret-redaction rule, PII handling.
- **`${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`** — the Shesha / ABP native mechanism for each fix.
- **`${CLAUDE_PLUGIN_ROOT}/shared/templates/finding.md`**, **`report.md`**, **`shesha-team-report.md`**.
- **`${CLAUDE_PLUGIN_ROOT}/shared/appinsights-queries.kql`** — the shared, PII-masked, sampling-weighted telemetry queries, for the telemetry-backed checks.

## This skill's check catalogue

- **`checks/orm-shesha.md`** — the ORM decision procedures (ORM-A … ORM-K). Each names its exact input, predicate, anchor rule, evidence source, `plan_id` and regression test. Run them **verbatim**.

## Sub-area (for a team split)

The ORM division's fixed partition, from the shared briefs:
- **query shape** = ORM-A, ORM-B, ORM-C, ORM-D, ORM-H
- **exposure & authz handover** = ORM-E, ORM-I (ORM-E is a **narrate-only** handover → the security division owns the authz call, as SEC-C)
- **lifecycle & session** = ORM-F, ORM-G, ORM-J, ORM-K

## How to run

1. **Resolve capability first** (operating-standard §1): repo commit + tree-state, whether there is an **isolated local DB copy**, and whether **App Insights** is reachable (the telemetry-backed N+1 / query-count checks are `NOT-ASSESSED(no-telemetry)` without it — never a silent pass). The static query-shape checks run from the repo.
2. **Run every check in `checks/orm-shesha.md`** to the division brief. Raise a finding **iff** the predicate is true **and** an anchor exists (`ORM-X@<path>#<Symbol>`).
3. **Emit `findings.json`** (operating-standard §8), `area: "orm"`, sorted canonically, stamped with the manifest `commit_sha` + hash. The prose report derives from it.

**Standalone:** write `findings.json` + a short summary to an external run folder. **Dispatched by the conductor:** return the findings per the brief; the conductor persists and merges them.

## Ground rules (from the contract)

- **Diagnose only**; **framework first** (bypassing it is a finding); **data safety** (isolated copy, counts not values, secrets as presence + length band only); **no blame**; **proof before ranking** (an unproven high is worded "the query allows…" until reproduced).
- **Handovers are narrated, not emitted** — ORM-E (a data-exposure that is really missing authorisation) is handed to the security division as SEC-C by a one-line narration referencing its id, never duplicated here.

## Files

- `checks/orm-shesha.md` — the ORM check catalogue (this skill's sole area authority).
- The contract, briefs, templates, the App Insights queries and the safety rules live in `${CLAUDE_PLUGIN_ROOT}/shared/` — read, never copied.
