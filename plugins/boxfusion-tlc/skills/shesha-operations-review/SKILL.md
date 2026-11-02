---
name: shesha-operations-review
description: Deterministic operations and reliability review for a BoxFusion Shesha / ABP system — CI and pipelines, configuration and secrets in config files, dependencies, telemetry, background jobs, messaging and notification delivery, plus the test and debug safety nets. Finds what fails in production and how often, what is slow, which integrations fall back to package defaults, and whether telemetry is adequate, and emits findings.json per the shared TLC contract so two runs on the same commit produce identical findings. The operations division of the BoxFusion TLC collection — the conductor dispatches to it, or run it on its own for an ops and reliability review. Use when asked to review, audit or health-check a Shesha app's operations, pipelines, configuration, dependencies, telemetry, background jobs, messaging or notifications.
---

# Shesha operations review (TLC operations division)

Reviews the **operational health** of a BoxFusion Shesha / ABP system — pipelines, configuration, dependencies, telemetry, jobs, messaging, and the test/debug safety nets — and returns a ranked, plain-English, no-blame set of findings, each proven to the evidence level the environment allows, with a framework-native remediation and a regression test. One division of the BoxFusion **TLC** collection; it shares the collection's determinism contract so its output merges cleanly with the other divisions.

## The shared contract (read these first — not optional)

This skill owns **only** its check catalogues. How it produces findings lives in the plugin's shared `tlc-core` library and is binding:

- **`${CLAUDE_PLUGIN_ROOT}/shared/operating-standard.md`** — the determinism & quality contract (§0–9).
- **`${CLAUDE_PLUGIN_ROOT}/shared/briefs/inspector-briefs-and-partitions.md`** — the canonical division inspector brief, sub-area partitions, orchestration rules. Run exactly to this brief.
- **`${CLAUDE_PLUGIN_ROOT}/shared/safety-and-data-access.md`** — QA-first, isolation, the secret-redaction rule (presence + length band only — critical here, config files hold secrets), PII handling.
- **`${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`** — the Shesha / ABP native mechanism for each fix.
- **`${CLAUDE_PLUGIN_ROOT}/shared/templates/finding.md`**, **`report.md`**, **`shesha-team-report.md`**.
- **`${CLAUDE_PLUGIN_ROOT}/shared/appinsights-queries.kql`** — the telemetry queries (always weight counts by `itemCount`; App Insights samples).

## This skill's check catalogues

- **`checks/operations.md`** — the operations decision procedures (OPS-A … OPS-H): pipelines, config, dependencies, telemetry, jobs, messaging, notification delivery.
- **`checks/safety-nets.md`** — the test/debug safety-net checks: which existing tests can't start and why, modules that can't be tested against a database (e.g. one that starts its own message bus at start-up), test/debug endpoints left in place. Run both **verbatim**.

## Sub-area (for a team split)

The operations division's fixed partition, from the shared briefs:
- **telemetry-gated** (→ `NOT-ASSESSED(no-telemetry)` when static) = OPS-A, OPS-B, OPS-D, OPS-E
- **static config & scheduling** = OPS-C, OPS-F, OPS-G, OPS-H

## How to run

1. **Resolve capability first** (operating-standard §1): repo commit + tree-state, whether **App Insights** is reachable (the telemetry checks are `NOT-ASSESSED(no-telemetry)` without it — never a silent pass), and whether pipelines/DevOps are reachable. Static config, dependency and scheduling checks run from the repo.
2. **Run every check in `checks/operations.md` and `checks/safety-nets.md`** to the division brief. Raise a finding **iff** the predicate is true **and** an anchor exists (`OPS-X@<anchor>`).
3. **Emit `findings.json`** (operating-standard §8), `area: "ops"`, sorted canonically, stamped with the manifest `commit_sha` + hash. The prose report derives from it.

**Standalone:** write `findings.json` + a short summary to an external run folder. **Dispatched by the conductor:** return the findings per the brief; the conductor persists and merges them.

## Ground rules (from the contract)

- **Diagnose only**; **framework first** (bypassing it is a finding); **data safety** (isolated copy, counts not values, **secrets as presence + length band only** — never copy a connection string or key into a finding); **no blame**; **proof before ranking** (an unproven high is worded "the configuration allows…" until reproduced).
- **Discretion over dogma** — a best practice that hurts this system (e.g. full request logging that kills API performance or fills the disk) is not a finding; weigh cost against benefit and say so.
- **Handovers are narrated, not emitted** — an ops observation that is really an authorisation, data-access or code issue is handed to the owning division by a one-line narration referencing its id, never duplicated here.

## Files

- `checks/operations.md`, `checks/safety-nets.md` — the operations check catalogues (this skill's sole area authority).
- The contract, briefs, templates, the App Insights queries and the safety rules live in `${CLAUDE_PLUGIN_ROOT}/shared/` — read, never copied.
