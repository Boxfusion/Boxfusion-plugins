# Determinism standard (the shared security-skills contract)

**Status: incoming — the TLC security-hardening reverse-flow.** This is the contract that makes the three Shesha security skills reproducible: two independent runs on the same commit, with the same capabilities, produce **byte-identical** findings and the same fix order. `auditing-application-security` is the **hub** — it owns this standard, the check registry, the `findings.json` schema and the normalizer/differ. `hardening-shesha-app` and `shesha-access-control` **emit into** this schema; they never fork it.

It is adapted from the TLC skill's `operating-standard.md`, which proved this method across six inspection divisions (two operators, empty diff).

---

## 0. The acceptance test (what "done" means)

The **diff surface** is the `findings.json` array of canonical tuples. Two runs pass iff, over the **capability intersection** of their manifests, the tuple sets are equal and the scored fix-order list matches:

```
tuple = { finding_id, anchor, evidence_level, severity, plan_id }
```

Everything else (prose, workbook, run metadata) is **out of the diff**. A field that cannot be produced by a named total function (§2–§6) is a determinism defect — re-engineer the check or mark it NON-DETERMINISTIC (§7). The harness (`normalize_findings.py` + `diff_runs.py`, §8) is the referee; `verify_run.py` gains a reproducibility gate.

---

## 1. Capability manifest (`capabilities.json`, emitted by `run_audit.py`)

Detected up front, never re-guessed mid-run. Each capability is `present` iff its probe exits 0:

| Capability | Probe |
|---|---|
| `live_backend` + url | dev server reachable |
| `low_priv_account` | a non-admin test login is supplied |
| `buildable_backend` | `dotnet build` succeeds (gates the Roslyn analyzer) |
| `gitleaks` / `dotnet` / `npm` | tool `--version` |
| `package_sources` | framework/Enterprise package sources restored & scannable |

**Rule:** a check whose required capability is **absent** emits `NOT-ASSESSED(<reason>)` — a first-class verdict, **never** a silent pass, never "fine", never a weaker instrument reported at a strong level. The diff compares only checks whose capabilities are present in **both** manifests; one-sided checks are reported in a `manifest_delta`, never as a diff failure. (Supersedes the current ad-hoc `SKIP` / `inputsMissing`.)

---

## 2. Finding id & anchor (replaces `{package}|{kind}|{where}`)

```
finding_id = <CHECK-ID>@<anchor>
```

- **CHECK-ID** = the registered check only (A1–A12, B1–B6, C1–C6, D1–D5, E1–E8, H1–H5, I1–I5, J1–J3, T/R/G, and the new SEC-L..S) — **no `-1/-2/-3` ordinal**; multiplicity is carried by the anchor (N anchors ⇒ N findings that collapse by identical string).
- **anchor** = a symbol/role, **never a raw line number** (lines drift on `dotnet format`). Forms: C# member `<path>#<Type>.<Member>` (overloads carry `(argTypeList)`); type `<path>#<Type>`; config `<path>#key:<Section>:<Key>`; HTTP `http:<VERB> <route-template>`; dynamic CRUD `http:<VERB> /api/dynamic/<Module>/<Entity>/Crud/<op>`; solution-wide `sln:<token>`; empty verdict `<CHECK-ID>@none`.
- **Path normalization:** repo-root-relative → `/` separators → lowercase the path part, keep `#Symbol.Member` verbatim → strip any `:\d+` defensively. `line` survives only as a non-diffed display field.

Implement in `catalog_schema.py` (the single format source) and `findings.py`; `verify_run.py` asserts no line-number anchors.

---

## 3. Evidence level (closed enum, separate axis from severity)

`REPRODUCED > CONFIRMED-IN-LOGS > VERIFIED-ARTEFACT > CODE-ONLY > DATA-ANOMALY > NOT-ASSESSED(reason)` — take the **MAX achieved** for the anchor. Map the existing vocabulary:

| Current signal | Evidence level |
|---|---|
| Probe verdict OPEN / REACHED (anonymous or low-priv) | **REPRODUCED** |
| Restored-DLL symbol / `ilspycmd` fact / scanner hit / grep artifact | **VERIFIED-ARTEFACT** |
| Static source match, `DERIVED` claim | **CODE-ONLY** |
| Odd data, no proven cause | **DATA-ANOMALY** |
| Capability absent (§1) | **NOT-ASSESSED(reason)** |

Evidence is **never** a severity input. Do not upgrade on confidence; an anonymous probe **is** REPRODUCED.

---

## 4. Severity (scored intrinsically, not a heuristic hint)

`severity = base(impact_class, reachability) ± data_sensitivity band` — a pure function of three declared inputs per check:
- **impact_class** ∈ {auth_bypass, data_exposure_pii, data_integrity, dos, info_leak, maintainability}
- **reachability** ∈ {anonymous, any_authenticated, low_priv, admin_only, local_only} (resolved from the gate)
- **data_sensitivity** ∈ {popia_special, pii_basic, business, none}

The review pass (`review-overrides.json`) becomes a **recorded input override** (it changes an input, reproducibly), not a free edit of the output. Retire the priority→severity map as the source of truth; keep it only as a derived display.

---

## 5. Remediation & fix order

Each finding carries a templated `plan_id` (not free prose) and names its **regression test** exactly. `fix_order_rank` is a pure function of `{severity, root_cause, anchor}` — never hand-sequenced, so it matches across runs. Remediation *content* lives in the owning skill: settings fixes → `hardening-shesha-app`; access-control design + the authorisation-inventory test → `shesha-access-control`. This skill references the `plan_id`; the receiving skill owns it. **One canonical finding_id per issue, shared** (fixes the `jwt-signing-key` / lockout double-detection between this skill and hardening).

---

## 6. root_cause vocabulary

An enumerated `RC-sec-*` id per check (registered in the check registry), never free text — so `fix_order_rank` is stable.

---

## 7. NON-DETERMINISTIC quarantine (the honesty rule)

A check a text scan cannot make reproducible is marked `non_deterministic: true` and **dropped from the diff** by the normalizer, until its deterministic instrument lands. The instruments that retire quarantine here:
- **Roslyn analyzer** (`resources/analyzers/`, gated on `buildable_backend` → else `NOT-ASSESSED(no-build)`): SEC_A (client/route id trusted as identity, no session cross-check — BOLA) and SEC_H (POPIA personal data interpolated into a log call, excluding `System.Type`). These replace grep guesses.
- Live probes depend on backend state, so the byte-identity guarantee covers the **static** checks; live-probe results are normalised or kept out of the guaranteed set, and that scope is stated.

---

## 8. Acceptance harness

- `normalize_findings.py` — strip volatile fields (`generated`, `ranAt`, `runDir`, backend host, commit SHAs); canonical `json.dumps(sort_keys=True, separators=(",",":"))` + trailing newline; stable sort by `(severity_band, check_id, anchor)`.
- `diff_runs.py` — byte-compare two normalised runs; print `onlyA`, `onlyB`, `fix_order_match`, `same_commit`, `manifest_delta`. Exit 0 = converged.
- `verify_run.py` — add a reproducibility check (run twice on one commit → empty diff) and keep the existing secret-leak gate.

---

## 9. Team-split (`--area` on `run_audit.py`)

Each check is tagged with one fixed sub-area so one person sweeps every project or a team divides a system and the merged result is byte-identical:
`access-control` · `secrets-and-config` · `input-and-data` · `real-time-and-messaging`. A `merge_runs.py` unions area runs into the identical whole a single run produces.

---

## 10. Secret-safety & no-blame (mostly present — tighten)

- Report secrets as **presence + length / `sha256:<12>`** only, never the value (already in `posture_scan` G1 / `verify_run`); add committed-vs-deployed SHA-256 comparison and a known-starter-key fingerprint list (hashes, never keys).
- **No-blame:** findings name no one; framework flaws route to the Shesha-team report. Add the wording rule to `recommendations-format.md`; `verify_run.py` already fails on leaked secrets — extend it to fail on personal names in reports.

---

*Next: the per-check **registry** (`references/check-registry.md`) instantiates §2–§6 for every CHECK-ID; then the code changes land in `catalog_schema.py` / `findings.py` / `verify_run.py` + the new harness scripts; then a two-run byte-identity proof.*
