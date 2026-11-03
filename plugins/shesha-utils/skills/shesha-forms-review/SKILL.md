---
name: shesha-forms-review
description: Deterministic Shesha form review for a BoxFusion Shesha / ABP system — the live form configurations in the environment's database, their scripts and their data sources. Finds where a form does something other than intended and where form scripts cause wrong data, failed saves or wasted requests, and emits findings.json per the shared TLC contract so two runs on the same commit produce identical findings. The forms division of the BoxFusion TLC collection — the conductor dispatches to it, or run it on its own for a forms review. Use when asked to review, audit or health-check a Shesha app's forms, form configurations, form scripts or form data sources.
---

# Shesha forms review (TLC forms division)

Reviews the **Shesha form configurations** of a BoxFusion Shesha / ABP system — the **live versions in the environment's database, not the repo copy** — with their scripts and data sources, and returns a ranked, plain-English, no-blame set of findings, each proven to the evidence level the environment allows, with a framework-native remediation and a regression test. One division of the BoxFusion **TLC** collection; it shares the collection's determinism contract so its output merges cleanly with the other divisions.

## The shared contract (read these first — not optional)

This skill owns **only** its check catalogue. How it produces findings lives in the plugin's shared `tlc-core` library and is binding:

- **`${CLAUDE_PLUGIN_ROOT}/shared/operating-standard.md`** — the determinism & quality contract (§0–9).
- **`${CLAUDE_PLUGIN_ROOT}/shared/briefs/inspector-briefs-and-partitions.md`** — the canonical division inspector brief, sub-area partitions, orchestration rules. Run exactly to this brief.
- **`${CLAUDE_PLUGIN_ROOT}/shared/safety-and-data-access.md`** — QA-first, isolation, the secret-redaction rule, PII handling.
- **`${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`** — the Shesha / ABP native mechanism for each fix.
- **`${CLAUDE_PLUGIN_ROOT}/shared/templates/finding.md`**, **`report.md`**, **`shesha-team-report.md`**.

## This skill's check catalogue

- **`checks/forms.md`** — the forms decision procedures (FORM-A … FORM-G): what each form is meant to do versus what it actually does, and where form scripts cause wrong data, failed saves or wasted requests. Run them **verbatim**.

## Sub-area (for a team split)

The forms division's fixed partition, from the shared briefs:
- **repo-static** = FORM-F (its F2 cross-module and per-field parity sub-checks are **NON-DETERMINISTIC** — emit tagged `non_deterministic:true`; the normalizer drops them), FORM-D server-validator inventory
- **DB-gated** (→ `NOT-ASSESSED(no-db-copy)` when static) = FORM-A, FORM-B, FORM-C, FORM-E, FORM-G

## How to run

1. **Resolve capability first** (operating-standard §1): repo commit + tree-state, and whether there is an **isolated local copy of the environment database** holding the **live form versions** (without it the DB-gated checks are `NOT-ASSESSED(no-db-copy)` — never a silent pass; the repo copy of a form is not the live version). The FORM-F / FORM-D repo-static checks run from the repo.
2. **Run every check in `checks/forms.md`** to the division brief, against the **live form configurations**. Raise a finding **iff** the predicate is true **and** an anchor exists (`FORM-X@<form>`).
3. **Emit `findings.json`** (operating-standard §8), `area: "forms"`, sorted canonically, stamped with the manifest `commit_sha` + hash. The prose report derives from it.

**Standalone:** write `findings.json` + a short summary to an external run folder. **Dispatched by the conductor:** return the findings per the brief; the conductor persists and merges them.

## Ground rules (from the contract)

- **Diagnose only**; **framework first** (a form rule that bypasses the framework — raw SQL, hand-made config — is a finding); **data safety** (isolated copy, counts not values, secrets as presence + length band only); **no blame**; **proof before ranking** (an unproven high is worded "the form allows…" until reproduced).
- **Handovers are narrated, not emitted** — a form behaviour that is really an authorisation or data issue is handed to the owning division by a one-line narration referencing its id, never duplicated here.

## Files

- `checks/forms.md` — the forms check catalogue (this skill's sole area authority).
- The contract, briefs, templates and safety rules live in `${CLAUDE_PLUGIN_ROOT}/shared/` — read, never copied.
