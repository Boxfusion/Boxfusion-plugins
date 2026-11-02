# Forms checks (Shesha)

Forms are **configuration stored in each environment's database**, versioned per environment; the repo holds a packaged copy that is usually stale. Two things therefore have **different, honestly-separated data sources**, and this file never blurs them:

- **Static-on-repo (always reproducible):** how `.shaconfig` packages are built, embedded and imported — **FORM-F**. Answered by exact commands over the working tree; evidence `VERIFIED-ARTEFACT`/`CODE-ONLY`, anchors `FORM-F@<path>`.
- **Needs the live form DB (reproducible only with a restored copy):** intent, form scripts, form-only validation, secret rendering and browser-side workflow routing — **FORM-A/B/C/D/E/G**. Without `db_copy`, each is a **first-class `NOT-ASSESSED(no-db-copy)`** at a fixed anchor — never a silent pass, never "clean". With `db_copy` present, the same checks run `REPRODUCED` (against a synthetic/restored copy) over exported Live markup.

Test as a **logged-in user with the least privilege that is realistic** and as an anonymous caller. Synthetic users and records only. Presence-only for secrets and personal data (never a value; presence + length band + `#symbol`/`form:` anchor only).

**This file obeys `references/operating-standard.md`.** Every check is a decision procedure: **INPUT → PREDICATE (boolean) → VERDICT → ANCHOR**, then **REMEDIATION (plan_id + template) → REGRESSION TEST → SEVERITY INPUTS**. A finding is raised **iff** the predicate is true and an anchor exists. IDs are `FORM-X@<anchor>` (operating-standard §3) — **never** `FORM-X-1/-2`; multiplicity is carried by the anchor (N forms ⇒ N `FORM-X@form:<module>/<name>` findings that collapse by identical string). Severity is scored intrinsically from operating-standard §5 (evidence level is a separate axis, not a severity input).

**The browser-side workflow-routing *security* finding is owned by SEC-K, not duplicated here.** FORM-G detects and anchors the form-config facts and **hands the server-enforcement finding over to SEC-K** in one line (see Handoffs). FORM-D likewise hands its server-validation gap to SEC-K.

## Data-source / capability-gating table (operating-standard §1 — absent capability ⇒ first-class NOT-ASSESSED, never a silent pass)
| Capability absent | Dimensions that become `NOT-ASSESSED(reason)` |
|---|---|
| `db_copy` | the live-markup dimension of FORM-A/B/C/D/E/G → `NOT-ASSESSED(no-db-copy)` at the fixed per-check `@forms` anchor; the repo-static part of FORM-D (server-validator inventory) and **all of FORM-F** still run at CODE-ONLY/VERIFIED-ARTEFACT |
| `backend_running` (or no browser) | the UI-reproduction dimension of FORM-A/B/G live-proof → `NOT-ASSESSED(no-backend)`; the exported-markup predicate still runs when `db_copy` present |
| `app_insights` | FORM-B request-count-per-page dimension → `NOT-ASSESSED(no-telemetry)` |

**Note the honest asymmetry:** a restored DB upgrades FORM-A/B/C/D/E/G from `NOT-ASSESSED` to `REPRODUCED`, but it does **not** make the *judgement* sub-parts deterministic — those stay quarantined (`non_deterministic:true`, below) even with a DB. FORM-F never needs the DB at all except for its package-vs-live drift sub-predicate.

## Determinism pins (apply exactly; these remove cross-operator divergence)

- **Fixed capability-gated NOT-ASSESSED anchors are MANDATORY — every operator emits every one, always, so the two runs' NOT-ASSESSED sets match exactly:** `FORM-A@forms`, `FORM-B@forms`, `FORM-C@forms`, `FORM-D@forms`, `FORM-E@forms`, `FORM-G@forms` (each `NOT-ASSESSED(no-db-copy)` when `db_copy` absent); plus `FORM-B@telemetry` `NOT-ASSESSED(no-telemetry)` for the per-page request-count dimension. Info/NOT-ASSESSED records never enter the fix-order list, so their presence can't change it (operating-standard §6).
- **`root_cause` is an enumerated `RC-forms-*` id** (never free text). Mapping: `RC-forms-client-trusted-logic` (FORM-G, FORM-D) · `RC-forms-config-drift` (FORM-F) · `RC-forms-state-leak` (FORM-A) · `RC-forms-wasted-requests` (FORM-B) · `RC-forms-script-quality` (FORM-C) · `RC-forms-secret-rendering` (FORM-E). `fix_order_rank` is computed from {severity, root_cause, anchor}, so it matches across runs.
- **Form anchors keep module case, path anchors lowercase (operating-standard §3):** `FORM-G@form:SaGov.Leave/sagov-approve-leave-application` (module verbatim, no version); **FORM-F file anchors are the FULL repo-root-relative path, lowercased, starting `backend/src/…`** (the SAME convention every other area uses — never a module-relative path that drops the `backend/src/module/` prefix), e.g. `FORM-F@backend/src/module/sagov.leave.application/configmigrations/package20251023_1206.shaconfig`. The upload aggregate stays `FORM-F@app_data-uploads=<n>`.
- **Quarantine (operating-standard §9) — these sub-predicates are `NON-DETERMINISTIC`; emit findings tagged `non_deterministic:true`, the normalizer drops them from the acceptance diff:**
  - FORM-A: intent-vs-behaviour *mismatch* and silent-fall-through detection (semantic). The `globalState` **usage count/enumeration** is deterministic and NOT quarantined.
  - FORM-B: real-N+1-vs-benign-parallel-fetch *classification* (judgement). The raw grep match list is deterministic; the verdict is not.
  - FORM-C: "action chain not awaited" semantic detection. `console.log`/`.then(`/shadowed-globals **counts** are deterministic and NOT quarantined.
  - FORM-D: per-field form-to-server parity *mapping* (judgement). The form `required` count and the server-validator inventory counts are deterministic.
  - FORM-E: "loaded-then-hidden over-exposure" (judgement). The secret-field-in-clear structural predicate is deterministic.
  - FORM-F: near-duplicate-markup *similarity* judgement, **and the F2 framework/cross-module "is this bundle a defect" judgement** (foreign-item *enumeration* is deterministic, but distinguishing a defect from normal Shesha dependency bundling is not — F2 is quarantined `non_deterministic:true`). Embedding/import (F1), name-family regex, and duplicate-package detection (F3) are deterministic.
  - FORM-G: branch-to-BPMN-gateway semantic *mapping* and approve/reject-asymmetry reasoning. The `Process/UserTaskComplete` form list and hard-coded-`decisionUid` enumeration are deterministic.
- **Empty-verdict + NOT-ASSESSED records: fixed severity token `Info`.** `FORM-x@none` and `FORM-x@forms` NOT-ASSESSED records are `severity=Info`.

## Fixed severity-inputs per check (impact_class + data_sensitivity are FIXED properties of the check; reachability resolves from the gate — author these exactly so two operators compute the same band)
| Check | impact_class | data_sensitivity | typical reachability → band |
|---|---|---|---|
| FORM-A (globalState leak / intent-mismatch) | data_integrity | business | any_authenticated → High |
| FORM-B (wasted requests) | dos | none | any_authenticated → Low |
| FORM-C (script quality) | maintainability | none | n/a → Low |
| FORM-D (form-only validation) | data_integrity | business | any_authenticated → High |
| FORM-E (secret rendered in clear) | info_leak | business | any_authenticated → Medium |
| FORM-F (not-embedded / drift / framework-overwrite) | data_integrity | none | local_only → Low |
| FORM-G (workflow routing in browser) | data_integrity | business | any_authenticated → High (the server-enforcement **security** severity is owned by SEC-K → Critical) |
Empty-verdict / NOT-ASSESSED records: severity `Info`.

## Package & markup mechanics (preserve these — a grep that ignores them reads falsely "clean")
- **`.shaconfig` packages are ZIP archives, not text.** A whole-repo grep for form patterns **stalls or returns nothing** because it scans the binary zips. Extract first, then grep the extracted JSON. Some zips use backslash paths: `unzip` warns but extracts.
- **Form scripts live under the PascalCase `Markup` field as stringified JSON.** In a `.shaconfig` item, components and their scripts are in a `"Markup"` property (capital M) whose value is a **stringified** `{"components":[…]}` — you must `JSON.parse` it before scanning. A grep keyed on lowercase `markup` (or on the raw item) returns **zero** hits and makes FORM-A/B/C/E/G all read as falsely "clean".
- **In a live-DB markup export the `Markup` column is already raw JSON** (not re-stringified like the package item) — scan directly. Filter to Live versions (`VersionStatusLkp=3 AND IsLast=1`) before `LIKE`/grep.
- **Tool tips:** export live markup with SqlClient from PowerShell, one file per form (`sqlcmd` in a `while read` loop eats the loop's input, and `-h -1` can't combine with `-y 0`); Bash heredocs strip `\\` from inline JS regexes — write scripts to files; `.shaconfig` `VersionNo` is the *authoring* environment's number — the importing DB assigns its own, so compare **content, not version numbers**.

## Preconditions (run once; reproducibility rests on them)
1. **Extract packages (always, static):** `find . -name '*.shaconfig'` → `unzip -o "$f" -d "$SCRATCH/pkg/<name>"` for each. List filenames first (a ` (1).shaconfig` is a browser-download duplicate smell) but read contents only after extraction.
2. **Export live markup (only if `db_copy`):** one file per Live form from `Frwk_FormConfigurations JOIN Frwk_ConfigurationItems` (0.43–0.44) / `frwk.configuration_items` (0.45+), `VersionStatusLkp=3 AND IsLast=1`. Absent `db_copy` ⇒ every DB-gated check emits its fixed `@forms` `NOT-ASSESSED(no-db-copy)` record.

---

## FORM-F: Config packaging & reproducibility (STATIC-ON-REPO — exact commands, always runnable). **impact_class=data_integrity, data_sensitivity=none, root_cause=RC-forms-config-drift.**

The only fully static check. Sub-predicates each own an anchor; the package-vs-live drift sub-predicate alone is DB-gated.

- **INPUT (exact commands over the extracted tree):**
  - `PKGS=$(find . -name '*.shaconfig')` — every package.
  - Embedded? `rg -n "<EmbeddedResource[^>]*\.shaconfig" **/*.csproj` → set of embedded package paths.
  - Imported? `rg -n "ImportConfigurationAsync|ConfigMigration|ImportConfiguration\(" backend/src --type cs` → set of modules that import at start-up.
  - Framework / cross-module items inside an app package: unzip each package and list item paths; a path under `Shesha/`, `Shesha.Workflow/`, `Shesha.Enterprise/`, `Shesha.Leave/` (or any `ModuleName` ≠ the hosting module) bundled into an **application** package.
  - Scratch/duplicate package files on disk: `basename` matching `/ (1)\.shaconfig$|-copy|-old|-new|duplicate/`.
  - `App_Data/Upload/` packages: `find . -path '*App_Data/Upload/*.shaconfig'` + confirm the folder is gitignored (`git check-ignore <path>`).
- **PREDICATES (each a boolean; one finding per hit):**
  - **F1 not-embedded:** a `.shaconfig` on disk is **not** in the `<EmbeddedResource>` set (won't import on deploy → silent drift). `FORM-F@<path>` (reason=not-embedded).
  - **F2 framework / cross-module bundled — NON-DETERMINISTIC (quarantined).** Enumerating foreign items (`ModuleName` ≠ hosting module) is deterministic, but **deciding which foreign bundle is a defect vs normal Shesha dependency bundling is a judgement a grep cannot make reproducibly** — Shesha legitimately bundles a dependency's reference-lists / notification-types into an app package, so the raw enumeration over-reports (≈140 items across ~43 packages on pd-Hcm, nearly all benign). Emit each foreign item as a candidate `FORM-F@<package-path>#foreign:<Module>/<name>` **tagged `non_deterministic:true`** (dropped from the acceptance diff). Do **not** hand-scope F2 to a chosen package — that is not reproducible. The deterministic replacement is a module-dependency-manifest check (is `<Module>` a declared dependency of the hosting module?) under a future analyzer.
  - **F3 scratch/duplicate package on disk:** a package basename matches the duplicate regex. `FORM-F@<path>` (reason=duplicate-package).
  - **F4 uncommitted upload artefacts (note) — SINGLE aggregate record:** committed `.shaconfig` files that live only under a gitignored `App_Data/Upload/` folder are all one issue (stray local uploads tracked despite the ignore). Emit **one** aggregate record `FORM-F@app_data-uploads=<n>` (severity `Info`, reason=local-only-upload, plan_id null) where `<n>` = `rg --files -g "**/App_Data/Upload/*.shaconfig" backend/src | wc -l`; the body lists the filenames. **Do NOT emit one record per GUID-named file** — that split one operator into 12 per-file records while the other aggregated. If `<n>`=0 the record is not emitted.
  - **F5 package-vs-live content drift (DB-gated):** normalise each system form's newest package markup and its Live markup; `hash(pkg) != hash(live)` → `FORM-F@form:<module>/<name>` (reason=drift / same-version-different-content); scratch/near-duplicate **forms live in DB** (status 3) matching `test|mask|quick|-old|-new|-copy|duplicate|-crud` → `FORM-F@form:<module>/<name>` (reason=scratch-in-db). **Absent `db_copy` ⇒ `FORM-F@forms` `NOT-ASSESSED(no-db-copy)`** for the drift dimension; F1–F4 still run.
  - If **all** packages are embedded AND imported AND no duplicates → `FORM-F@none` (the embedding guard is *correctly silent*, not skipped). **F2 foreign items do not gate `@none`** (they are quarantined ND, not scored).
- **VERDICT/ANCHOR:** as above. Near-duplicate-markup *similarity* beyond exact-hash is `non_deterministic:true`.
- **EVIDENCE:** F1–F4 `VERIFIED-ARTEFACT` (grep/zip artefact); F5 `VERIFIED-ARTEFACT` with `db_copy`, else `NOT-ASSESSED(no-db-copy)`.
- **REMEDIATION `PLAN-FORM-F`:** ship form changes only as new packages built from the environment's current version; embed/rebuild F1 (or delete if superseded, ≤1 open package per form); rebuild F2 so each item ships from its owning module and exclude framework items; retire F3/F5 scratch forms after confirming the canonical is Live; each package PR carries a pre-import rollback export.
- **REGRESSION TEST:** `ConfigPackages_EmbeddedAndReproducible_Test` — asserts every on-disk `.shaconfig` is an `<EmbeddedResource>` imported at start-up, carries no foreign-module items, and Live markup hash-matches the newest package.
- **SEVERITY:** data_integrity × local_only, none → **Low** (F4 note → Info).
- *pd-Hcm reference set:* all six app modules call `ImportConfigurationAsync()` (area largely healthy) — exceptions F1 (`SaGov.Leave.Application/ConfigMigrations/package20251023_1206.shaconfig`, `package20260622_1508.shaconfig`; `SaGov.Pmds.Application/ConfigMigrations/package20251102_2248.shaconfig`, `package20251121_1457.shaconfig`), F2 (`SaGov.Leave.Application/ConfigMigrations/package20260730_1117.shaconfig` bundles `Shesha/…/Shesha.MainMenuSettings.json`, `Shesha.Workflow/notification-type/user-task-breach-of-sla.json`, `Shesha.Leave/*`), F4 (12 GUID-named `.shaconfig` in `Web.Host/App_Data/Upload/`, gitignored), F5 (`calendar-test`, `sagov-leave-test`, `test`, `sagov-persal-transactions-copy`, `test-datatable`, `change-supervisor2/3-wf-approve`, `sagovemployee-create2`, customised framework forms in DB).

---

## FORM-G: Workflow decisions made in the browser (DB-GATED). **impact_class=data_integrity, data_sensitivity=business, root_cause=RC-forms-client-trusted-logic. The server-enforcement security finding HANDS OVER to SEC-K.**

- **INPUT (exported Live markup, `db_copy` required):**
  - Enumerate workflow-completing forms: `grep -rl "Process/UserTaskComplete" <markup-dir>`.
  - Hard-coded routes: per form, `grep -no "decisionUid" ` and extract the assigned value; flag client-chosen routes — the ternary `count>0?"A":"B"`, **and** `if (<x> === …) { decisionUid = … } else …`, `switch (data?.<field>) { case …: … }`, **and** stale `decisionUid` literals left in comments. A ternary-only regex misses the if/switch forms.
- **PREDICATE:** a form POSTs a **hard-coded `decisionUid`** to `Process/UserTaskComplete` from form JS (route not chosen by the server) → one finding per form; **sub-flag** forms that pick among **multiple** hard-coded ids, or **compute** the route from client form state.
- **VERDICT/ANCHOR:** `FORM-G@form:<module>/<name>` per workflow-completing form (record: id-count, client-computed yes/no). Branch-to-BPMN-gateway mapping and approve/reject-asymmetry are `non_deterministic:true`.
- **EVIDENCE:** exported-markup facts `VERIFIED-ARTEFACT` (`REPRODUCED` with a UI e2e that drives the risky branch); absent `db_copy` → `FORM-G@forms` `NOT-ASSESSED(no-db-copy)`.
- **REMEDIATION `PLAN-FORM-G`:** one server-side workflow-step command per action that decides the route from server data, completes the task by a **stable decision key** in one unit of work, and records the real actor; forms use the native task-complete action, not hand-rolled `http.post`; validate Live ids against the BPMN gateways and decommission stale ids.
- **REGRESSION TEST:** `BusinessFlow_StatusAndRouteServerEnforced_Test` (shared with SEC-K) — low-priv completes a task not assigned / with a forged route → 403/rejected.
- **SEVERITY:** data_integrity × any_authenticated, business → **High** (the *security* severity — server trusts whatever `decisionUid` arrives — is scored by SEC-K → Critical).
- **→ SEC-K handover (one line, not duplicated):** *`UserTaskComplete` trusts a client-supplied `decisionUid` and a client-chosen route; server must re-derive the route and verify caller==assignee. Owned by SEC-K.*
- *pd-Hcm reference set:* 75 Live forms complete BPMN tasks by hard-coded `decisionUid`; 34 pick among multiple ids client-side; 2 compute the route from form state (`SaGov.Leave/sagov-acknowledge-without-pay` v23 — `submitToPersal==2 && transactionsConfiguredManually` **falls through to `else { hideLoading(); return; }`**, task silently not completed; `SaGov.Pmds/sagov-performanceagreement-wf-reviewperformanceagreement` v17). Approve/reject asymmetry: `sagov-approve-leave-application` drops `userComments` on one branch.

---

## FORM-D: Validation lives only in the form (SPLIT: server inventory STATIC, form side DB-GATED). **impact_class=data_integrity, data_sensitivity=business, root_cause=RC-forms-client-trusted-logic. Server-enforcement gap HANDS OVER to SEC-K.**

- **INPUT:**
  - **Static (repo):** server-validator inventory `rg -n ": *AbstractValidator<" backend/src --type cs | grep -vi "/obj/\|/bin/"` → `A` validator classes, grouped by module → `FORM-D@sln:server-validators=<A>/<modules>`.
  - **DB-gated:** form-side rule counts over exported markup — `grep -rl '"required": *true' <markup-dir>` (forms with required fields) and `grep -rl "validator" <markup-dir>` (forms carrying custom validator code).
- **PREDICATE:** a module whose forms declare required/validator rules has **no** (or materially fewer) server `AbstractValidator` classes covering those entities → the rule is enforced only in the browser; mobile/USSD/integration/raw API bypass it.
- **VERDICT/ANCHOR:** `FORM-D@sln:server-validators=<A>/<modules>` (static, always) — this is an **inventory tally: severity `Info`, `plan_id=null`, evidence VERIFIED-ARTEFACT** (a `sln:…=count` metric, exactly like the SQL/ORM tallies; it is NOT the scored finding). The **scored** FORM-D "validation lives only in the form" finding (data_integrity × business → High, the §severity-table row) is the **DB-gated `FORM-D@forms`** dimension, which is `NOT-ASSESSED(no-db-copy)` under `--static` — so on a static run FORM-D contributes **no High record**, only the Info inventory + the NOT-ASSESSED form record. Per-field form-to-server parity mapping is `non_deterministic:true`.
- **EVIDENCE:** server inventory `VERIFIED-ARTEFACT` (static); form-rule counts `VERIFIED-ARTEFACT` with `db_copy`, else `NOT-ASSESSED(no-db-copy)`.
- **REMEDIATION `PLAN-FORM-D`:** move business rules into server fluent validators (`shesha-fluent-validators`); keep form validation for UX only.
- **REGRESSION TEST:** `Validation_ServerEnforcesFormRules_Test` — a raw API call bypassing the form with invalid data → rejected server-side.
- **SEVERITY:** data_integrity × any_authenticated, business → **High**.
- **→ SEC-K handover (one line):** *Server-enforced validation exists in only one module; SEC-K must re-check each business rule independent of the form.*
- *pd-Hcm reference set:* 219 Live forms declare `"required": true`, 14 carry custom validator code; server `AbstractValidator` exists in only Shesha.Qms (7 validators). `FORM-D@sln:server-validators=7/Shesha.Qms`.

---

## FORM-E: Secret-like fields rendered in clear (DB-GATED). **impact_class=info_leak, data_sensitivity=business, root_cause=RC-forms-secret-rendering.**

- **INPUT (exported markup, `db_copy` required):** parse each form's components; select components whose `propertyName`/`name` matches `/password|secret|apikey|token/i`.
- **PREDICATE:** such a text component has `textType != "password"` (visible in clear). **Exclude** config-flag props (`requirePasswordChange`, `passwordLength`, etc.) that are not value fields.
- **VERDICT/ANCHOR:** `FORM-E@form:<module>/<name>#<propertyName>` per clear-text secret field. "Loaded-then-hidden over-exposure" is `non_deterministic:true`.
- **EVIDENCE:** `VERIFIED-ARTEFACT` with `db_copy`; absent → `FORM-E@forms` `NOT-ASSESSED(no-db-copy)`.
- **REMEDIATION `PLAN-FORM-E`:** set `textType:"password"` (`shesha-form-edit`); confirm the value is stored encrypted server-side, not merely masked.
- **REGRESSION TEST:** `FormFields_SecretsMaskedAndEncrypted_Test`.
- **SEVERITY:** info_leak × any_authenticated, business → **Medium**.
- *pd-Hcm reference set:* `Boxfusion.Persal/persal-connection-settings` v1 (`persalFtpPassword`), `Boxfusion.Persal/ssh-connection-settings` v1 (`password`), `Boxfusion.SAGov/sagovemployee-create` v4 & `sagovemployee-create2` v2 (`password`, `confirmPassword`), `Boxfusion.SAGov/sagovemployee-details` v3 (`password`, `confirmPassword`).

---

## FORM-C: Script quality (DB-GATED, mostly mechanical). **impact_class=maintainability, data_sensitivity=none, root_cause=RC-forms-script-quality.**

- **INPUT (exported markup; or `clean-form-config` in report-only mode):**
  - `grep -rno "console\.log" <markup-dir>` → per-form + total counts.
  - `.then(` chaining instead of async/await: `grep -rno "\.then(" <markup-dir>`.
  - Shadowed Shesha globals: `grep -rno "const *\(message\|http\|data\|form\|globalState\)\b" <markup-dir>`.
  - `clean-form-config`: dead properties, missing try/catch around API calls, label-vs-propertyName references, JS syntax errors, layout overflow.
- **PREDICATE:** count > 0 for any mechanical defect class → one finding per class (the counts are the finding). "Action chain not awaited" (Execute-Script IIFE not returning its promise before a following Refresh/success) is detected but `non_deterministic:true` (semantic).
- **VERDICT/ANCHOR:** `FORM-C@class:console-log`, `FORM-C@class:then-chain`, `FORM-C@class:shadowed-globals`, `FORM-C@class:<clean-form-config-rule>` — each carrying its form+call count; `=none` when the class is clean.
- **EVIDENCE:** `VERIFIED-ARTEFACT` with `db_copy` (counts exact); `clean-form-config` output `VERIFIED-ARTEFACT`; absent `db_copy` → `FORM-C@forms` `NOT-ASSESSED(no-db-copy)`.
- **REMEDIATION `PLAN-FORM-C`:** `clean-form-config` report-only, then a pilot-first fleet fix (`fleet-transformer`): strip `console.log`, convert `.then()`→async/await+try/catch, await action promises, rename shadowed globals.
- **REGRESSION TEST:** `FormConfig_CleanScriptsNoConsoleOrThenChains_Test` (CI runs `clean-form-config` and fails on any defect class above a baseline).
- **SEVERITY:** maintainability → **Low**.
- *pd-Hcm reference set:* `console.log` in 163 forms / 792 calls (worst `leaveapplication-wf-capture` 88); `.then()` chaining in 133 forms; shadowed globals **0 — clean**.

---

## FORM-A: Intent vs behaviour (DB-GATED, largely judgement). **impact_class=data_integrity, data_sensitivity=business, root_cause=RC-forms-state-leak.**

- **INPUT (exported markup):** `grep -rl "globalState" <markup-dir>` → forms using `globalState` to pass data between forms, and the keys read/written (`grep -rno "globalState\.\w\+\|globalState\['\?\w\+" <markup-dir>`).
- **PREDICATE (deterministic part only):** a form writes a `globalState` key that another form reads → cross-record/cross-journey leak risk. Raise `FORM-A@form:<module>/<name>#globalState:<key>` per write site. **Quarantined (`non_deterministic:true`):** intent-vs-behaviour *mismatches* (autofill producing `{itemValue: undefined}`, save chains missing `shesha.form.Validate`, composed strings a server parser rejects, silent fall-throughs) — these need semantic reading/UI drive, not a grep.
- **VERDICT/ANCHOR:** `FORM-A@form:<module>/<name>#globalState:<key>` (deterministic); mismatch findings tagged `non_deterministic:true`.
- **EVIDENCE:** `globalState` enumeration `VERIFIED-ARTEFACT` with `db_copy` (`REPRODUCED` only with a UI e2e proving the leak); absent `db_copy` → `FORM-A@forms` `NOT-ASSESSED(no-db-copy)`.
- **REMEDIATION `PLAN-FORM-A`:** pass values via form data / subform context, not `globalState`; clear on unload; add the missing `shesha.form.Validate` step where custom validators exist.
- **REGRESSION TEST:** `FormState_NoCrossRecordGlobalStateLeak_Test` — e2e opens record A then record B; B must not inherit A's `globalState`.
- **SEVERITY:** data_integrity × any_authenticated, business → **High** (quarantined mismatch findings excluded from the diff surface).
- *pd-Hcm reference set:* `globalState` keys `takenDaysText` (12), `takenHoursText` (6), `confirmAssessmentReadOnly` (2), `comment` (1, read back as `userComments`), `Total` (1); 88 Live forms reference `globalState`. The `sagov-acknowledge-without-pay` silent fall-through (FORM-G) is also an intent-vs-behaviour defect.

---

## FORM-B: Wasted requests in form scripts (DB-GATED + telemetry). **impact_class=dos, data_sensitivity=none, root_cause=RC-forms-wasted-requests.**

- **INPUT (exported markup; App Insights for per-page counts):** `grep -rn "Promise.all(.*\.map(\|\.map(.*http\.\(get\|post\)" <markup-dir>` (candidate N+1 per-item fetches in `onAfterDataLoad`/`onChange`); lookups on every keystroke vs on select; unfiltered table loads; refetching a whole record to read one field.
- **PREDICATE (deterministic part):** a script maps over items issuing one `http.get`/`http.post` **per item** → candidate N+1; raise `FORM-B@form:<module>/<name>#<handler>`. **Quarantined (`non_deterministic:true`):** the real-N+1-vs-benign-fixed-parallel *classification* (a small fixed `Promise.all` of 2–3 known calls is correct, not an N+1) — needs reading. Keystroke-lookup / unfiltered-table-load severity and per-page request counts need runtime/App Insights → `FORM-B@telemetry` `NOT-ASSESSED(no-telemetry)`.
- **VERDICT/ANCHOR:** `FORM-B@form:<module>/<name>#<handler>` for the deterministic candidate list; `FORM-B@none` when no map-over-http candidates; `FORM-B@telemetry` fixed NOT-ASSESSED record.
- **EVIDENCE:** candidate list `VERIFIED-ARTEFACT` with `db_copy`; `REPRODUCED` only via a browser network trace; absent `db_copy` → `FORM-B@forms` `NOT-ASSESSED(no-db-copy)`.
- **REMEDIATION `PLAN-FORM-B`:** batch per-item fetches into one filtered call; lookup on select, not keystroke; filter tables server-side; read fields from the already-loaded record.
- **REGRESSION TEST:** `FormScripts_NoNPlusOneFetches_Test` — a network assertion caps requests per page load.
- **SEVERITY:** dos × any_authenticated, none → **Low**.
- *pd-Hcm reference set:* no per-item N+1 (no `Promise.all(items.map(get by id))`); 10 `Promise.all`/`allSettled` are small fixed parallel fetches (correct → `FORM-B@none`). Keystroke/unfiltered-table not detectable on a near-empty starter DB; App Insights N/A → `FORM-B@telemetry` `NOT-ASSESSED(no-telemetry)`.

---

## Checked-and-fine / correctly-silent guards (report, don't drop)
- FORM-F embedding guard **correctly silent** on a reproducible setup (all modules `ImportConfigurationAsync()`, embed from `ConfigMigrations/`) → emit `FORM-F@none` for the embedding dimension, not nothing.
- FORM-C shadowed-globals clean → `FORM-C@class:shadowed-globals=none`.
- FORM-B N+1 absent → `FORM-B@none`.

## Handoffs to Security (SEC-K) — one line each, finding owned there
1. `UserTaskComplete` trusts client-supplied `decisionUid` + client-chosen route (FORM-G) → server must re-derive the route and verify caller==assignee.
2. Server-enforced validation exists in only one module (FORM-D) → server must re-check each business rule independent of the form.
