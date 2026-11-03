# Unused-code audit — methodology

The detection authority for `shesha-unused-code-audit`. Governed by the determinism contract (`${CLAUDE_PLUGIN_ROOT}/shared/operating-standard.md`): stable `UNUSED-X@anchor` ids, the closed evidence enum, scored severity, `findings.json` as the diff surface. **Propose-only** throughout — nothing here deletes or edits code.

---

## 1. The asymmetric standard

Disabling or deleting dead code is the cheapest maintainability and attack-surface win a Shesha app has. The risk runs the other way: a wrongly-removed endpoint returns 404 and breaks a screen nobody opened in testing. Shesha's indirection makes this easy to get wrong — a symbol can be reached by a dialog, a subform, a reference list, an embedded script, a specification, a validator, a workflow service task, a scheduled job or a message consumer without its name appearing where you looked.

So: **recommend removal only where the evidence is positive and complete across every signal that applies. Everything else is `REVIEW`.** "Nothing we could see calls it" is never "nothing calls it."

## 2. The three signals and the verdict

For each candidate symbol, gather the signals that apply to its kind, then combine:

| Signal | Source | Evidence when "unused" | Applies to |
|---|---|---|---|
| **static** | back-end + front-end source grep / Roslyn | no reference found → `CODE-ONLY` | every kind |
| **forms** | form catalogues + `form-reference-mechanisms.md` (in `auditing-application-security`) | reached by no form | endpoints, entities, ref-lists, forms |
| **telemetry** | App Insights (`${CLAUDE_PLUGIN_ROOT}/shared/appinsights-queries.kql`) | zero calls over the window → `CONFIRMED-IN-LOGS`; App Insights absent → `NOT-ASSESSED(no-telemetry)` | endpoints, services, jobs, consumers |

**Verdict (disposition):**
- **PROPOSE-REMOVE** *(high confidence)* — every applicable signal says unused (static: none, forms: none, telemetry: zero over a sufficient window) **and** no safety gate (§4).
- **PROPOSE-REMOVE (caveated)** *(medium)* — static + forms say unused but telemetry is `NOT-ASSESSED(no-telemetry)`; propose with the explicit line "not confirmed uncalled at runtime — verify before removing."
- **REVIEW** *(no proposal)* — statically referenced but telemetry shows zero calls (the caller may itself be dead; trace the chain), OR signals disagree, OR a safety gate applies, OR an input was incomplete/stale.

**Telemetry windows matter.** A feature used quarterly looks dead in a 30-day window. Record the retention window and the feature's plausible cadence; if the window is shorter than the cadence, telemetry is `NOT-ASSESSED(window-too-short)`, not "uncalled."

## 3. Per-category detection

Each row: INPUT → PREDICATE → ANCHOR. Raise a candidate **iff** the predicate holds and an anchor exists.

- **UNUSED-EP — API endpoints never called.** INPUT: the endpoint catalogue (route + owning service). static = grep the route/service/action in back-end + front-end source; forms = is the route in any form catalogue (`configured-forms`/`custom-forms`); telemetry = `requests` where `name`/`url` matches, summed by `itemCount`. ANCHOR `UNUSED-EP@<httpMethod> <route>`.
- **UNUSED-ENT — entities + their dynamic CRUD APIs.** INPUT: entity catalogue. static = type name referenced in source (specs/validators/managers/mappers count); forms = entity bound by any form/data source; telemetry = any CRUD route for it called. The biggest single win is usually entities that got dynamic CRUD endpoints nobody asked for. ANCHOR `UNUSED-ENT@<FullTypeName>`.
- **UNUSED-SVC — application services / methods with no caller.** static = method referenced (front-end call, backend caller, DI); telemetry = the method's endpoint called. ANCHOR `UNUSED-SVC@<path>#<Type>.<Member>`.
- **UNUSED-TYPE — classes / DTOs / models with no reference.** static only (telemetry N/A). PREDICATE: the type is referenced nowhere (construction, inheritance, generic arg, mapping, serialization). Exclude types used only by reflection/DI by convention (safety gate 4). ANCHOR `UNUSED-TYPE@<FullTypeName>`.
- **UNUSED-FORM — orphaned form configurations.** INPUT: the live form list. PREDICATE: a form referenced by no menu/navigation item, no other form (dialog/subform), and no coded screen. ANCHOR `UNUSED-FORM@<module>/<formName>`.
- **UNUSED-REF — reference lists bound by nothing.** PREDICATE: a reference list referenced by no entity property, form component or code. ANCHOR `UNUSED-REF@<module>/<refListName>`.
- **UNUSED-SET — settings defined but never read.** PREDICATE: a setting registered but read by no code path or form. ANCHOR `UNUSED-SET@<settingName>`.
- **UNUSED-PERM — orphaned permissions.** **Consume `auditing-application-security` SEC-U** (granted to no role, or required by no endpoint); do not re-derive. Narrate it here as the maintainability view. ANCHOR `UNUSED-PERM@<permissionName>` (mirror SEC-U's anchor).
- **UNUSED-FE — front-end components / pages / routes not imported or routed.** static = import graph + router config; PREDICATE: a component/page/route not imported, not routed, not referenced by a form's custom-component registry. (The import-graph part is NON-DETERMINISTIC — tag `non_deterministic:true`; the normalizer drops it, but still report it for human review.) ANCHOR `UNUSED-FE@<path>#<Component>`.
- **UNUSED-DB — database objects never referenced.** PREDICATE: a table/view/procedure/function referenced by no NHibernate mapping, no `CreateSQLQuery`, no migration, no other DB object. Hands to / aligns with the SQL division. Data-level confirmation (row counts, last-write) needs the isolated copy → otherwise `NOT-ASSESSED(no-db-copy)`. ANCHOR `UNUSED-DB@<schema>.<object>`.
- **UNUSED-JOB — background jobs / message consumers never triggered.** static = registered (Hangfire schedule, `IConsume<>`/AutoSubscriber); telemetry = the job/consumer has fired in the window (custom events / dependencies). A registered consumer for a message type nothing publishes, or a scheduled job that never ran, is a candidate. ANCHOR `UNUSED-JOB@<path>#<Type>`.

## 4. Safety gates — never PROPOSE-REMOVE when any applies (record REVIEW + reason)

Extends `${CLAUDE_PLUGIN_ROOT}/skills/auditing-application-security/references/disabling-unused-endpoints.md`; aligned, widened to all code.

1. **A backend caller exists.** Search source for the type/service/member name before proposing: `grep -rn "Name" backend/src --include=*.cs | grep -v "/obj/"`. Workflow service tasks, scheduled jobs, notification senders, validators, specifications and message consumers all reference symbols with no front-end involvement.
2. **Reached by a package-owned form/page** whose source was not scanned. The row's `packageSourcesNotScanned` marks it → stays REVIEW. "Not scanned" ≠ "no caller."
3. **Plausible external integration** — import/export, webhook receiver, anything named for a third-party system. Only the user knows; ask, don't propose.
4. **Dynamic / reflective use** — reflection, DI-by-convention, dynamically-built form references, catalogue `indeterminate`/`unresolvable` entries, serialization-only types.
5. **More than one front end** (admin + public, or a mobile app) and only one scanned → downgrade every unreferenced result to REVIEW.
6. **Incomplete / stale input** — Swagger unavailable, catalogues from different backend states, telemetry window shorter than the feature cadence, front-end not built.
7. **Infrastructure keep-list** — framework endpoints the SPA calls indirectly (auth, config, permissions, reference-data, file store). Reuse the keep-list in `${CLAUDE_PLUGIN_ROOT}/skills/auditing-application-security/references/disabling-unused-endpoints.md`.

## 5. Capability gating (operating-standard §1)

| Capability absent | Effect |
|---|---|
| App Insights | all telemetry signals `NOT-ASSESSED(no-telemetry)`; verdicts cap at PROPOSE-REMOVE (caveated); never treat "no telemetry" as "uncalled" |
| buildable back end | static analysis degrades to grep-only; note reduced confidence |
| built front end / its source | `forms`/`UNUSED-FE` partial → affected rows REVIEW |
| isolated DB copy | `UNUSED-DB` data-level checks `NOT-ASSESSED(no-db-copy)` (schema-reference check still runs) |
| package sources | package-owned-form gate 2 applies broadly → more REVIEW |

A capability-missing check returns `NOT-ASSESSED(reason)` — a first-class verdict, never a silent pass and never an unsupported removal.

## 6. Output — the proposal (propose only)

`findings.json` (operating-standard §8), then a derived proposal report ranked by **confidence × size-of-win**. Per item:
- the symbol + anchor, its **kind** (UNUSED-X), and its **disposition** (PROPOSE-REMOVE / PROPOSE-REMOVE-caveated / REVIEW);
- the **three-signal evidence** — static (refs found / none), forms (reached / not), telemetry (calls in window / zero / not-assessed), each with its evidence level;
- the **confidence** and any **safety gate** that held it at REVIEW;
- the **framework-native removal plan** (`${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`) — how to properly disable/remove this kind (an entity's dynamic CRUD, a `.shaconfig` form, a coded endpoint, a DB object) — plus a **rollback note** and the **verification** to run after removal;
- a one-line **why it's safe to propose** (or why it's REVIEW).

The report proposes; a human agrees to each item before anything is removed (the conductor's walkthrough, or the user directly). This skill applies nothing.
