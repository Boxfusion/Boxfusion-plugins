# Work items and PRs (Phase 7)

The goal is a board people can follow, not a flood of tickets.

## Board structure

- **One parent work item:** `{SystemName}-TLC-Fixes`, e.g. `pd-sagov-TLC-Fixes`.
  - Use the project's usual type for a body of work: a Feature, or a User Story if the project doesn't use Features. Check the project's existing work items.
  - Its description holds the report summary, a link to or attachment of `REPORT.md`, and the fix sequence.
- **Tasks underneath, consolidated.** One task per **fix group**, not per finding. Group findings that:
  - share a root cause (e.g. "server-side authorisation model: SEC-2, SEC-3, SEC-4, ORM-4");
  - are fixed by the same change, or touch the same files;
  - ship in the same PR.

  A typical TLC has **5–12 tasks**. If the list grows past about 12, merge further. Low-severity clean-ups go into a single "Small clean-ups" task. The 5–12 count includes the test-coverage task. Shortcut follow-ups are child items, not tasks.
- **Each task's description:**
  - the finding IDs it covers;
  - the plan of action;
  - the framework mechanisms to use;
  - the regression tests;
  - dependencies on other tasks.
- **Required fields.** Projects often require fields such as Client, Implementation Phase or Deployment. Read the project's work item type definitions, reuse the values its existing items use, and ask the user once if a value can't be determined.
- **Follow-up items** under the parent for each emergency shortcut (from the shortcuts register), e.g. "remove the interim filter when the framework fix ships".
- **Approval.** The board shown at the end of the walkthrough is approved by "Let's begin!". Create exactly that. Anything more needs a fresh go-ahead.
- **Trial runs (`--dev-mode-only`):** the board is a **proposal only**, in the report's board section, labelled "Proposal only: nothing is created". Create no work items, fix branches or PRs.
- Use one parent name throughout the report and board (the project's usual short system name).

## PRs

- One PR per task, or per a few tightly coupled tasks, from a branch named for the fix group (e.g. `tlc/authorisation-model`).
- Link each PR to its task and the parent work item. Link only the items the PR actually completes, so unrelated items aren't auto-closed.
- **PR description:**
  - what users or the business will notice;
  - the finding IDs fixed;
  - the framework mechanisms used (`${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`);
  - tests: the reproducing test now passing, plus the e2e results (run before push);
  - rollout notes: config packages, migrations, deploy order, anything to check in production first, and **the rollback step: a read-only export of the rows each package will overwrite, taken before import** (packages can't be rolled back on their own);
  - **for a secret moved out of the repository:** the pipeline variable and local environment variable names, developer set-up steps, the committed value flagged for rotation (presence only), and what fails until the variable exists (e.g. a restore with `NU1301`); reviewers create the variables before merging;
  - **for a framework upgrade:** the security-drift result (`upgrade-shesha-stack` step 8) and proof that custom permission records survived a restart;
  - any emergency shortcut, with its follow-up item;
  - open BA decisions.
- **At most one open package per form across all PRs** (`${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md` caveats). If two tasks touch one form, sequence them, or put the form change in one PR.
- Don't merge, enable auto-merge or deploy unless the user asks.
- **Add a "Post-merge re-test and re-audit" task** (SKILL.md Phase 7b) that depends on the fix PRs. It closes only when the merged build has been re-tested and re-audited, before human testing starts.
- The test-coverage branch from Phase 0 (`tlc/test-coverage`) gets its own PR and its own task, "Test coverage to standard". Ideally it merges first, so later PRs can rely on it. In a trial run it stays local, with no PR.
