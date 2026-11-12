# TLC canonical inspector briefs, sub-area partitions & orchestration rules

*Single source of truth (tlc-core). Referenced by the conductor and every division skill via `${CLAUDE_PLUGIN_ROOT}/shared/briefs/inspector-briefs-and-partitions.md`. The conductor fills only the placeholders; everything else is fixed and non-optional.*

## Security division — deterministic briefing & orchestration (`--security-only`)

This section makes the security division reproducible per `${CLAUDE_PLUGIN_ROOT}/shared/operating-standard.md`: two operators on the same commit + manifest produce the same `findings.json`. It supersedes, for security, the numeric-range and "mark evidence level honestly" guidance above.

### The canonical security inspector brief (fill only the placeholders)
The orchestrator fills `{check-ids}`, `{repo-commit}`, `{tree-state}`, `{manifest}`; everything else is fixed and non-optional.

```
=====BEGIN SECURITY INSPECTOR BRIEF=====
ROLE: Security reviewer, BoxFusion TLC --security-only. You inspect; you never start the app,
never write a file, never change the working tree (git status identical before/after; delete
anything you create; scratch only in the scratchpad).

YOUR CHECKS (exact closed set — run every one, invent no others; run SEC-I FIRST):
  {check-ids}

REPO: commit {repo-commit} (tree: {tree-state}). Tie every finding to this commit; read the
working tree, not only tracked files.

CAPABILITY MANIFEST (authoritative — do NOT re-detect, do NOT install anything):
  {manifest}
  RULE: a check whose required capability is ABSENT returns NOT-ASSESSED(<reason>) — a first-class
  verdict, never a silent pass, never "fine", never a guess, never a weaker instrument kept at a
  strong level. gitleaks absent => SEC-E recall NOT-ASSESSED(no-secret-scanner), seam-grep = CODE-ONLY.
  No low-priv account => authenticated dimension of SEC-A/B/C/K/L/M/N NOT-ASSESSED(no-low-priv-user);
  anonymous/static stands alone. (See checks/security.md capability-gating table.)
  SEC-ESC needs per-role synthetic logins on a restorable copy => else NOT-ASSESSED(no-per-role-logins).
  SEC-DRIFT/SEC-RESET need two live captures (old/new build, first start/restart) => else
  NOT-ASSESSED(no-before-capture). A module only on a branch not under review =>
  NOT-ASSESSED(branch-not-audited), listed by name, never dropped.

OUTPUT CONTRACT (every finding; operating-standard §§2-6,8):
  1. finding_id = <CHECK-ID>@<anchor>  — NO -1/-2/-3 ordinal. N anchors => N findings. Anchor by
     symbol/role never a raw line number; path lowercased, #Symbol.Member verbatim (§3 forms table).
  2. ANCHOR-REQUIRED: raise a finding IFF the predicate is true AND an anchor exists. No anchor,
     no finding; no anchor-less "smell".
  3. evidence_level from the closed enum via execution_class, MAX achieved for the anchor
     (REPRODUCED>CONFIRMED-IN-LOGS>VERIFIED-ARTEFACT>CODE-ONLY; NOT-ASSESSED(reason) if cap absent).
     An anonymous live probe IS REPRODUCED. Do not upgrade on confidence.
  4. severity SCORED from operating-standard §5 (intrinsic; evidence is NOT an input). Print the
     three inputs: impact_class={} reachability={} data_sensitivity={} => BAND. Score against the
     manifest severity_target, never the copy's data volume. Never raise severity for sequencing.
  5. remediation = the check's templated plan_id (checks/security.md), instantiated with your anchor
     — not free prose. Name the regression test exactly as the check names it.
  6. CANONICAL ORDER: emit sorted by severity band DESC, then check_id ASC, then anchor ASC.
  7. PARTIAL INPUTS => NOT-ASSESSED(reason). Never guess, never infer a value you did not read.
  8. NEVER invent ids, levels, severities or remediations outside these templates.

DATA-SAFETY (verbatim, non-optional): "Never reproduce a secret value anywhere in your hand-back —
not keys, tokens, connection strings, passwords or API keys. Report presence + length band only
(e.g. 'SecurityKey present, ~32 chars'). The same for personal data: counts and categories, never
the values." Compare committed vs deployed secrets by SHA-256 hash only (match/no-match).

SCOPE (--security-only): in scope = the checks listed. Out of scope = performance, ORM scale, SQL
craft, ops/telemetry, forms UX, non-security code quality — name each "not in scope for
--security-only", do not raise it.

RETURN: file content ONLY, no preamble, starting =====BEGIN findings/security.md===== ending =====END=====.
Use ${CLAUDE_PLUGIN_ROOT}/shared/templates/finding.md per finding. List "checked and fine" and the NOT-ASSESSED set explicitly.
Keep BA questions and PM concerns separate from findings.
=====END SECURITY INSPECTOR BRIEF=====
```

### Orchestration rules (fixed, not judgement)
- **Fixed sub-area partition** (a team split and a single-operator run merge byte-identically):
  - access-control = SEC-A, SEC-B, SEC-C, SEC-K, SEC-P (JWT-trust), SEC-Q (GraphQL data-plane), SEC-S (tenant isolation), SEC-FW (framework entities via generic CRUD), SEC-ESC (admin takeover), SEC-DRIFT / SEC-RESET (upgrade drift, start-up reset), SEC-GONE (forms calling removed endpoints) (+ consumed handovers CODE-G-1, CODE-F-1/2, CODE-G-3)
  - secrets & config = SEC-E, SEC-I, SEC-O, SEC-D
  - input & data = SEC-G, SEC-L, SEC-M, SEC-N, SEC-H
  - real-time & messaging = SEC-F, SEC-J, SEC-R (background-job trust)
  Only `{check-ids}` differs between team members. SEC-K stays whole in access-control and consumes its fixed handover list; if a handover-source sub-area didn't run, SEC-K records `NOT-ASSESSED(handover-source-not-run)` for that trace — never guesses it.
- **Overlap resolution (fixed priority, first match wins):** property-authorisation → SEC-L; business-flow/workflow → SEC-K; endpoint authz → SEC-C/B/A; secret → SEC-E/I. The losing check emits a one-line handover referencing the winner's `finding_id`, never a duplicate.
- **Duplicate collapse:** identical `finding_id` ⇒ keep one, union evidence, take the MAX evidence level; take the higher severity only if computed from identical §5 inputs, else flag a determinism defect (don't average). Collapse by id equality only (the id carries the anchor) — no fuzzy/title matching.
- **Persist + normalize:** the orchestrator emits `findings.json` (operating-standard §8 schema) alongside the prose, sorted canonically, each record tagged with `commit_sha` + manifest hash; on a propose-only run, to the external run folder, never under the app root. The markdown is derived from `findings.json` (one source of truth).
- **Acceptance test:** `${CLAUDE_PLUGIN_ROOT}/shared/harness/run-acceptance.ps1` launches two independent operators (`--security-only --static`, same manifest) and diffs; see `harness/`.

## All divisions — deterministic briefing & team-split (generalises the security model)

Every division is now acceptance-proven deterministic the same way security is: two independent operators on the same commit + manifest produce byte-identical `findings.json` (frozen references in `harness/<area>-PASS-*.json`). A team can split **any** division across members, or one person can run the whole division, and the merged result is identical. This section is the generic counterpart to the security briefing above — use it for `--area code|orm|sql|operations|forms` (and for splitting those areas across a team).

### The canonical division inspector brief (fill only the placeholders)
Identical in spirit to the security brief; the orchestrator fills `{area}`, `{check-file}`, `{check-ids}`, `{repo-commit}`, `{tree-state}`, `{manifest}`. The output contract, anchor rules, evidence enum, scored severity, canonical order, and data-safety clauses are **verbatim the same** as the security brief above — a division operator differs only in (a) which `checks/<area>.md` is its sole authority, (b) its check-id set, and (c) its area tag on each record. Non-negotiable additions that the overnight hardening proved necessary:

```
=====BEGIN DIVISION INSPECTOR BRIEF ({area})=====
ROLE: {area} reviewer, BoxFusion TLC. Inspect only; never start the app, never write outside the
scratchpad, git status identical before/after.
AUTHORITY: checks/{check-file} is your ONLY spec. Run its decision procedures VERBATIM — zero
judgement, zero improvisation. Where it gives an exact grep, run that exact grep; do not widen,
narrow, or add a clause qualifier it does not state.
YOUR CHECKS (exact closed set): {check-ids}
REPO: commit {repo-commit} (tree {tree-state}). CAPABILITY MANIFEST (authoritative, no re-detect): {manifest}
  Absent capability => NOT-ASSESSED(<reason>) at the check's fixed anchor — first-class verdict, never a silent pass.
OUTPUT CONTRACT: finding_id=<CHECK-ID>@<anchor> (no ordinal; N anchors => N findings; anchor a
  symbol/role never a line number; the anchor NEVER re-prepends the check id; a `=none` empty verdict
  anchor is literally "none"). evidence from the closed enum (absence/zero-match grep => CODE-ONLY;
  a measured PRESENCE count => VERIFIED-ARTEFACT). severity SCORED intrinsically (§5), evidence is not
  an input. A `sln:<token>=<n>` tally is a context metric => severity Info, plan_id null. Info / empty
  / NOT-ASSESSED records carry plan_id null. A sub the check marks NON-DETERMINISTIC => emit tagged
  non_deterministic:true (the normalizer drops it). Handovers to another area are NARRATED ONLY — never
  emit another area's record in this division's findings.json. Canonical order: severity DESC, check_id
  ASC, anchor ASC.
RETURN: findings.json (bare array) to {out-path}; file content only, no preamble.
=====END DIVISION INSPECTOR BRIEF ({area})=====
```

### Fixed sub-area partitions (a team split and a single-operator run merge byte-identically)
Only `{check-ids}` differs between team members; every other brief field is shared. Handover records are narrated by the detecting area and scored by the receiving area — if a handover source didn't run, the receiver records `NOT-ASSESSED(handover-source-not-run)`, never a guess.

- **CODE** (`checks/code.md`):
  - error & flow = CODE-A, CODE-B, CODE-C
  - structure & patterns = CODE-D, CODE-E, CODE-H
  - front-end & dead code = CODE-F, CODE-G (CODE-F-1/CODE-G-1 narrate-only → security owns them)
  - tests & predicates = CODE-I, CODE-J (CODE-J + CODE-A null-deref + CODE-D semantic-dup + CODE-G import-graph are NON-DETERMINISTIC, dropped from the diff)
- **ORM** (`checks/orm-shesha.md`):
  - query shape = ORM-A, ORM-B, ORM-C, ORM-D, ORM-H
  - exposure & authz handover = ORM-E, ORM-I (ORM-E → SEC-C)
  - lifecycle & session = ORM-F, ORM-G, ORM-J, ORM-K
- **SQL** (`checks/sql.md`):
  - craftsmanship (static) = SQL-C (16 vectors; `groupby-hiding-dup` NON-DETERMINISTIC)
  - physical & growth (DATA-LEVEL → NOT-ASSESSED static) = SQL-A, SQL-B, SQL-D, SQL-E
  - integrity & release path = SQL-F, SQL-G, SQL-H
- **OPERATIONS** (`checks/operations.md`):
  - telemetry-gated (→ NOT-ASSESSED(no-telemetry) static) = OPS-A, OPS-B, OPS-D, OPS-E
  - static config & scheduling = OPS-C, OPS-F, OPS-G, OPS-H
- **FORMS** (`checks/forms.md`):
  - repo-static = FORM-F (F2 cross-module + per-field parity NON-DETERMINISTIC), FORM-D server-validator inventory
  - DB-gated (→ NOT-ASSESSED(no-db-copy) static) = FORM-A, FORM-B, FORM-C, FORM-E, FORM-G

### Orchestration rules (same as security)
Overlap resolution, duplicate-collapse-by-id, persist-`findings.json`-then-derive-markdown, and the two-operator acceptance diff are identical to the security section above. Each division's frozen PASS reference (`harness/<area>-PASS-{A,B}.json`) is the regression baseline: a check-file edit that changes a division's output must be re-accepted (two fresh operators, empty diff) before it ships.
