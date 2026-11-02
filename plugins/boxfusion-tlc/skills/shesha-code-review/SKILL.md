---
name: shesha-code-review
description: Deterministic application-code review for a BoxFusion Shesha / ABP system, back end and front end — error handling, control flow, transactions, side effects, structure, dead code and test predicates. Flags where the code violates basic engineering practice in ways that cause real problems and which harmful patterns repeat, and emits findings.json per the shared TLC contract so two runs on the same commit produce identical findings. The code division of the BoxFusion TLC collection — the conductor dispatches to it, or run it on its own for a code-quality review. Use when asked to review, audit or health-check a Shesha app's application code, error handling, transactions, side effects, structure or code quality.
---

# Shesha code review (TLC code division)

Reviews the **application code** (back end and front end) of a BoxFusion Shesha / ABP system and returns a ranked, plain-English, no-blame set of findings — each proven to the evidence level the environment allows, with a framework-native remediation and a regression test. One division of the BoxFusion **TLC** collection; it shares the collection's determinism contract so its output merges cleanly with the other divisions.

## The shared contract (read these first — not optional)

This skill owns **only** its check catalogue. How it produces findings lives in the plugin's shared `tlc-core` library and is binding:

- **`${CLAUDE_PLUGIN_ROOT}/shared/operating-standard.md`** — the determinism & quality contract (§0–9): capability manifest, checks-as-decision-procedures, `CHECK-ID@anchor` ids, the closed evidence enum, scored severity, templated remediation, `findings.json` as the diff surface.
- **`${CLAUDE_PLUGIN_ROOT}/shared/briefs/inspector-briefs-and-partitions.md`** — the canonical division inspector brief (fill only the placeholders), the fixed sub-area partitions, the orchestration rules. Run exactly to this brief.
- **`${CLAUDE_PLUGIN_ROOT}/shared/safety-and-data-access.md`** — QA-first, isolation, the secret-redaction rule (presence + length band only), PII handling.
- **`${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`** — the Shesha / ABP native mechanism for each fix.
- **`${CLAUDE_PLUGIN_ROOT}/shared/templates/finding.md`**, **`report.md`**, **`shesha-team-report.md`**.

## This skill's check catalogue

- **`checks/code.md`** — the code decision procedures (CODE-A … CODE-J). Each names its exact input (grep/pattern), predicate, anchor rule, evidence source, `plan_id` and regression test. Run them **verbatim** — zero improvisation.

## Sub-area (for a team split)

The code division's fixed partition, from the shared briefs:
- **error & flow** = CODE-A, CODE-B, CODE-C
- **structure & patterns** = CODE-D, CODE-E, CODE-H
- **front-end & dead code** = CODE-F, CODE-G (CODE-F-1 / CODE-G-1 are **narrate-only** handovers → the security division owns them)
- **tests & predicates** = CODE-I, CODE-J

**NON-DETERMINISTIC (emit tagged `non_deterministic:true`; the normalizer drops them from the diff):** CODE-J, CODE-A null-deref, CODE-D semantic-dup, CODE-G import-graph.

## How to run

1. **Resolve capability first** (operating-standard §1): repo commit + tree-state, and whether the backend builds (some predicates need it; where it can't build, those checks are `NOT-ASSESSED(no-build)` — never a silent pass). Most code checks are static (repo read).
2. **Run every check in `checks/code.md`** to the division brief. Raise a finding **iff** the predicate is true **and** an anchor exists (`CODE-X@<path>#<Symbol>`); no anchor, no finding.
3. **Emit `findings.json`** (operating-standard §8) — `{finding_id, check_id, area: "code", anchor, evidence_level, execution_class, severity, severity_inputs, plan_id, root_cause, fix_order_rank, sources[], not_assessed_reason}`, sorted canonically, stamped with the manifest `commit_sha` + hash. The prose report derives from it.

**Standalone:** write `findings.json` + a short summary to an external run folder (never inside the app repo on a read-only run). **Dispatched by the conductor:** return the findings per the brief; the conductor persists and merges them.

## Ground rules (from the contract)

- **Diagnose only** — never modify the application during review.
- **Framework first** — proposed fixes use the Shesha / ABP native mechanism; bypassing the framework is itself a finding.
- **Data safety** — isolated local copy; counts not values; secrets as presence + length band only.
- **No blame** — describe what the code does, never who did it. Route genuine framework defects to the Shesha-team report.
- **Proof before ranking** — honest evidence level per finding; an unproven high is worded "the code allows…" until reproduced.
- **Handovers are narrated, not emitted** — a code-smell that is really an authorisation hole (CODE-F-1 / CODE-G-1) is handed to the security division by a one-line narration referencing its id, never duplicated here.

## Files

- `checks/code.md` — the code check catalogue (this skill's sole area authority).
- The contract, briefs, templates and safety rules live in `${CLAUDE_PLUGIN_ROOT}/shared/` — read, never copied.
