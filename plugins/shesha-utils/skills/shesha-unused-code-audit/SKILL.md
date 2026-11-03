---
name: shesha-unused-code-audit
description: Audits a BoxFusion Shesha / ABP application for unused and dead code — API endpoints, entities and their dynamic CRUD APIs, application services and methods, classes, DTOs, form configurations, reference lists, settings, permissions, front-end components and routes, database objects, background jobs and message consumers. Combines three independent signals — static code references, form configurations, and App Insights telemetry (what is actually called at runtime) — to decide whether something is genuinely unused, then PROPOSES its removal with evidence and a confidence level. It never deletes anything. Use when the user asks to find dead code, unused endpoints, orphaned entities, uncalled APIs, unreferenced forms or reference lists, removable surface, or to clean up / trim a Shesha application, or asks which endpoints are never called.
---

# Shesha unused-code audit (propose-only)

Finds code that nothing uses and **proposes** removing it — it never removes anything itself. Part of the BoxFusion **TLC** collection; it shares the collection's determinism contract, so its proposals come out the same on two runs and merge with the other divisions.

The whole skill rests on one asymmetric rule: **a wrongly-kept dead endpoint is cheap; a wrongly-removed live one breaks the app at runtime, often in a screen nobody opened during testing.** So it recommends removal only where the evidence is **positive and complete across every available signal**; everything else is **REVIEW**, and REVIEW is a perfectly good outcome.

## The three signals (the core idea)

"Unused" is not one question — it is three, and a confident proposal needs all the signals that apply to agree:

1. **Static references** — is the symbol referenced anywhere in the back-end or front-end source, including DI registration, reflection, specifications, validators, workflow service tasks and scheduled jobs? (A grep/analyzer pass. Catches "nothing in the code names it.")
2. **Form configurations** — is it reached by any Shesha **form**? Forms call endpoints nine different ways (dialogs, subforms, reference lists, data sources, embedded scripts, actions…), none of which look like a code reference. (Reuse the form-reference knowledge in `${CLAUDE_PLUGIN_ROOT}/skills/auditing-application-security/references/form-reference-mechanisms.md`.)
3. **App Insights telemetry** — was it **actually called** in the retention window? This is the signal the other two cannot give: an endpoint can be statically referenced by a caller that is *itself* dead, and only telemetry proves it never runs. (Uses `${CLAUDE_PLUGIN_ROOT}/shared/appinsights-queries.kql`.)

**How they combine into a verdict:**
- **PROPOSE-REMOVE** (high confidence): no static reference **and** no form reference **and** zero telemetry calls over a sufficient window **and** no safety gate (below) applies.
- **PROPOSE-REMOVE (caveated)**: no static/form reference, but **App Insights is unavailable** → the runtime signal is `NOT-ASSESSED(no-telemetry)`; propose with the explicit caveat "not confirmed uncalled at runtime — verify before removing."
- **REVIEW**: statically referenced but **zero telemetry** over a long window — the reference may be dead code too; surface it (often a chain of dead code to trace), never auto-propose deletion.
- **REVIEW**: any safety gate applies, or signals disagree, or an input was incomplete.

## The shared contract (read first — binding)

- **`${CLAUDE_PLUGIN_ROOT}/shared/operating-standard.md`** — the determinism & quality contract (§0–9): the capability manifest, `CHECK-ID@anchor` ids, the **closed evidence enum** (here `CONFIRMED-IN-LOGS` = telemetry-proven uncalled; `CODE-ONLY` = static-only; `NOT-ASSESSED(reason)` when a signal is unavailable), scored severity, and `findings.json` as the diff surface.
- **`${CLAUDE_PLUGIN_ROOT}/shared/briefs/inspector-briefs-and-partitions.md`** — the canonical division inspector brief; run to it.
- **`${CLAUDE_PLUGIN_ROOT}/shared/safety-and-data-access.md`** — QA-first, isolation, secret-redaction (presence + length only), PII handling.
- **`${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`** — the Shesha / ABP native mechanism (how a form/entity/endpoint is *properly* disabled or removed, so the proposal is framework-native).
- **`${CLAUDE_PLUGIN_ROOT}/shared/appinsights-queries.kql`** — PII-masked, sampling-weighted telemetry queries (always weight by `itemCount`; App Insights samples).
- **`${CLAUDE_PLUGIN_ROOT}/shared/templates/finding.md`**, **`report.md`**.

## What it catalogues (the methodology lives in `references/methodology.md`)

`references/methodology.md` is the authority — per-category detection, the exact three-signal procedure, the safety gates, capability gating and the proposal format. The categories:

- **UNUSED-EP** API endpoints never called · **UNUSED-ENT** entities + their dynamic CRUD APIs · **UNUSED-SVC** application services / methods with no caller · **UNUSED-TYPE** classes, DTOs and models with no reference · **UNUSED-FORM** form configurations no menu/navigation/form references · **UNUSED-REF** reference lists bound by nothing · **UNUSED-SET** settings defined but never read · **UNUSED-PERM** orphaned permissions (**reuses `auditing-application-security` SEC-U** — don't re-derive; consume it) · **UNUSED-FE** front-end components / pages / routes not imported or routed · **UNUSED-DB** database tables / views / procedures / functions never referenced (hands to the SQL division) · **UNUSED-JOB** background jobs and message consumers registered but never triggered (telemetry-gated).

## How to run

1. **Resolve capability first** (operating-standard §1): repo commit + tree-state, whether the back end builds, whether an **App Insights** connection is reachable (absent → every telemetry signal is `NOT-ASSESSED(no-telemetry)` and verdicts drop to the caveated form — never silently treat "no telemetry" as "uncalled"), whether there is more than one front end, and whether package sources are available (a package-owned form may call it). Build the back-end + front-end **catalogues against one consistent backend state** (comparing catalogues from different runs produces false "unused" results).
2. **Run each category per `references/methodology.md`**, applying the three-signal procedure and the safety gates **before** any PROPOSE-REMOVE.
3. **Emit `findings.json`** (operating-standard §8), `area: "unused"`, one record per candidate: `{finding_id: UNUSED-X@anchor, check_id, anchor, evidence_level, signals:{static, forms, telemetry}, disposition: PROPOSE-REMOVE|REVIEW, confidence, removal_plan, safety_gate, not_assessed_reason}`, sorted canonically, stamped with the manifest `commit_sha` + hash.
4. **Write the proposal report** (derived from `findings.json`) — ranked by confidence × size-of-win, each item with its three-signal evidence, the framework-native removal steps, a rollback note, and the risks. **Propose only; apply nothing.**

**Standalone:** write `findings.json` + the proposal report to an external run folder (never inside the app repo on this read-only audit). **Dispatched by the conductor:** return the proposals per the brief; the conductor merges and the user walks each one.

## Ground rules

- **Propose, never act.** This skill does not delete, disable or edit application code. Removal happens only after a human agrees to each proposal (in the conductor's walkthrough, or by the user directly).
- **Asymmetric evidence.** PROPOSE-REMOVE needs positive, complete, multi-signal evidence; anything short is REVIEW. "Nothing we could see calls it" is **not** "nothing calls it."
- **Diagnose only / data safety / no blame / framework-first**, per the shared contract.
- **Secrets & PII** as presence + length band / counts only, never values.

## Safety gates (do NOT propose removal when any applies — record REVIEW + reason)

Extends `${CLAUDE_PLUGIN_ROOT}/skills/auditing-application-security/references/disabling-unused-endpoints.md`; aligned with it, widened to all code:
1. A **backend caller** exists (service tasks, scheduled jobs, notification senders, validators, specifications, message consumers reference symbols with no front-end involvement).
2. It is reached by a **package-owned form or page** whose source was not scanned ("not scanned" ≠ "no caller").
3. It plausibly serves an **external integration** (import/export, webhook receiver, third-party-named) — only the user knows; ask.
4. **Dynamic / reflective** use (reflection, DI by convention, dynamically-built form references, `indeterminate` catalogue entries).
5. The app has **more than one front end** and only one was scanned — downgrade every unreferenced result to REVIEW.
6. A catalogue input was **incomplete or stale** (Swagger unavailable, telemetry retention shorter than the feature's usage cycle, catalogues from different backend states).

## Files

- `references/methodology.md` — per-category detection, the three-signal procedure, safety gates, capability gating, proposal format (this skill's authority).
- The contract, briefs, templates, safety rules and App Insights queries live in `${CLAUDE_PLUGIN_ROOT}/shared/` — read, never copied.
