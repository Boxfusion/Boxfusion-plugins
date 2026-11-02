# Self-improvement: the skill learns from every run (Phase 8)

Each TLC run can meet problem types the skill doesn't know yet. The skill turns those into upgrades of itself, so the next person gets a better copy. **It never publishes them unreviewed.**

## Reviewer (always)

- **Skill upgrade reviewer and approver:** **Igor Kors** (GitHub `igorkors-boxfusion`), lead for this skill.
- Every upgrade PR requests his review. **Only his approval counts**, and nothing merges without it.
- Merge, version bump and release happen automatically once he approves, **when** merge-on-approval is configured (branch policy or auto-merge). Until then he merges by hand. The skill never merges or publishes on its own.
- To change the reviewer, the lead edits this file in a reviewed PR.

## What counts as a learning

Collect candidates during the run, in `diagnosis/LEARNINGS.md`:
- **A problem type not in the check catalogue** (`checks/*.md`): a new anti-pattern, failure mode or framework pitfall, found and proven in this run.
- **A better way to detect or prove something:** a SQL or KQL query, a test pattern, an inspection step.
- **A framework caveat:** a Shesha/ABP behaviour or bug, a version-specific limitation, a native mechanism that works better.
- **A correction from the user in a Discuss** that applies beyond this system, e.g. "this pattern is intended in Shesha systems because…".
- **A fault in the skill itself:** unclear guidance, a wrong query, a missing step (the kind of thing in `TRIAL-NOTES.md`).

**Not learnings:**
- facts about one system (its data, its business rules, its secrets);
- anything unproven (only REPRODUCED, CONFIRMED-IN-LOGS or VERIFIED-ARTEFACT findings, or explicit user corrections);
- opinions without evidence.

**Trial runs (`--dev-mode-only`)** exist to improve the skill. Collect learnings as usual, including process lessons (what the user found noisy, slow or confusing). When a system is re-run as a trial after the skill changed, run it from scratch and compare the new report with the previous run's: findings found, missed, corrected, and report size.

## Writing the upgrade

1. **Generalise.** Describe the pattern, not the system. Strip:
   - system, client and customer names;
   - table, entity, endpoint, form and person names;
   - ids, URLs and file paths from the diagnosed repo;
   - all data values.

   A short invented example is fine ("an app service that takes a personId from the request"). The system's real code is not.
2. **Place it** where the skill already keeps that kind of knowledge:
   - `checks/<area>.md` (in the same what / why / detect / prove / plan shape);
   - `sql/diagnostic-queries.sql` or `references/appinsights-queries.kql`;
   - `references/framework-standards.md` (caveats, with the Shesha version);
   - `references/*.md` for process faults.
3. **Don't duplicate.** If the catalogue already covers it, improve that entry instead.
4. **Validate:**
   - the skill still loads (frontmatter intact, no broken file references);
   - new SQL and KQL is syntactically valid (run new SQL against a local database, read-only);
   - **a secret and PII scan** over the diff: emails, phone and ID number patterns, connection strings, keys and tokens, long random strings, and names from the diagnosed system's recon. **Any hit blocks the PR** until it's removed.

## Raising the PR

- **Repository:** `Boxfusion/Boxfusion-plugins` (public), the plugin that carries this skill. Until the skill is published there, propose the change against the local draft and list it in `TRIAL-NOTES.md` for the lead instead.
- **Branch:** `tlc-learning/<yyyy-mm-dd>-<short-topic>`. One PR per run, grouping that run's learnings.
- **Version:** bump the plugin version (patch for wording and queries; minor for new checks or phases) and add a changelog entry.
- **PR description:**
  - each learning in one line;
  - where it went;
  - the evidence level it came from;
  - the anonymised reason ("found in a TLC run on 2026-10-29: <pattern>");
  - the scan result;
  - the request for review from **igorkors-boxfusion**.
- **Ask the user first.** At the end of the run, show the learnings and the draft PR, then ask: *"Raise the skill-upgrade PR for review by Igor Kors?"* Raise it on yes. The user may drop individual learnings.
- **Never auto-merge without approval, and never approve your own PR.** After the reviewer approves, the repository's merge-on-approval setup publishes it. Users get it on their next plugin update.

## Why there's a human gate

- The plugin repo is public, so a leaked name, secret or personal detail can't be taken back.
- A wrong lesson would spread to every future run on every system.
- The skill reads code and data from systems it doesn't control, and planted text could try to "teach" it something harmful.

One review covers all three.
