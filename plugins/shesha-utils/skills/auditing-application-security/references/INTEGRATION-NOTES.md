# Integration notes — TLC security reverse-flow

**Status of this branch:** Phases 0–3 of the reverse-flow are implemented and committed across the three skills. Two things need a **Python environment** to finish-wire and verify (they were deliberately *not* blind-shipped, since this machine has no Python interpreter — only the Windows Store stub):

## 1. Final analyzer wiring (2 small steps — apply + test with Python)

The SEC-A/SEC-H Roslyn analyzer (`resources/analyzers/`) is built, proven byte-identical standalone (`dotnet build` succeeded), and `resources/run_analyzers.py` is ready. It is **not yet called by the pipeline**. To wire it:

**(a)** In `resources/run_audit.py` → `build_steps()`, add this phase-1 step (after the `object-auth` step):
```python
Step("analyzers", "run_analyzers.py", [os.path.join("@run", "analyzer-findings.json")],
     always=True, optional=True,
     extra=lambda a, ctx: ["--out", os.path.join(ctx["run_dir"], "analyzer-findings.json")]),
```
**(b)** In `resources/findings.py`, union `<run-dir>/analyzer-findings.json` into the run's `findings.json` by `finding_id` (the analyzer already emits the shared schema). If a `finding_id` collides, keep the analyzer's (VERIFIED-ARTEFACT) record.

Both are one-localised-change each; apply and run the existing tests before relying on them.

## 2. Reproducibility proofs to run in CI (written, not yet executed here)

Each skill ships its proof; run once Python is available:
- `auditing`: `python plugins/shesha-utils/skills/auditing-application-security/resources/tests/test_determinism.py`
- `hardening`: `python plugins/shesha-utils/skills/hardening-shesha-app/scripts/test_checks.py`
- the two-run byte-identity check in each `verify_run.py` / `test_checks.py` (normalize two runs on one commit → empty diff).

The analyzer's own two-run byte-identity **was** demonstrated (dotnet is available).

## What is done and verifiable now
- Shared **determinism standard** + **check registry** (the contract) — `references/`.
- `auditing`: `CHECK-ID@anchor` ids (incl. the `G1→B7`, `D1/D2→K1/K2` renames), scored severity, evidence enum, normalize/diff harness, reproducibility gate — in `catalog_schema.py` / `findings.py` / `verify_run.py` + new scripts.
- `hardening`: same contract applied to its four checks (I3/I4/J2/A10, shared canonical ids), secret-safety helper, two new checks (`jwt-signing-key`, `cors-origins`), no-blame routing.
- `access-control`: Detect→Remediate hand-off, `checks.md` with 6 remediation templates, and the **authorisation-inventory test** (`authorisation-inventory-test.md`, 11 deterministic invariants, baseline snapshot, capability gate).
- `analyzer`: SEC-A/SEC-H ported, built, proven byte-identical; `NOT-ASSESSED(no-build)` fallback.

## Registry calibrations settled on merge
- SEC-H reachability `n/a` → `admin_only` (scores High, as the analyzer emits).
- D5 derives **High** (no row-level security anywhere) — supersedes the earlier Medium note.
- Orphaned/unused permission got a canonical id **SEC-U** (the inventory test's provisional `sln:orphaned-permission` anchor now has one).
- `RC-sec-pii-logging` and the rest registered as the closed `RC-sec-*` set.

## Still open (follow-ups, not blockers)
- `J1`/`J2` split into two rows (posture_scan currently emits one combined rate-limit+lockout row).
- SEC-K / SEC-L predicates are seeded from secure-design practice — confirm against real workflow/DTO shapes when a project is in scope.
- `known_jwt_key_fingerprints.json` has the ABP module-zero default; add confirmed Boxfusion/Shesha-starter fingerprints.
