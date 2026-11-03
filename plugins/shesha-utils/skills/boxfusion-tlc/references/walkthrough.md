# Walkthrough: Agree or Discuss, then "Let's begin!"

The report is a starting point, not a verdict. The person who started the run often knows things inspection can't see: a business rule, a manual workaround, a planned replacement, a reason something was done. The walkthrough captures that knowledge and turns the report into an agreed plan.

There is one person in this conversation: the one who started the skill.

**Trial runs (`--dev-mode-only`):** no walkthrough unless the user asks. Present the board as a proposal ("Proposal only: nothing is created") and stop there.

## For each finding, in rank order

Present it in a few lines:
- what happens, and why it matters;
- the evidence level and the reproducing test;
- the proposed plan of action, which is a framework-native fix plus its regression test.

Offer exactly two options: **Agree** or **Discuss**.

- **Agree:** status becomes `agreed`. Move on.
- **Discuss:** talk it through.
  - Check what the user says against the code, data or tests where you can, and say plainly if the evidence still points the other way.
  - Change the finding, its rank or its plan if the user's information changes them, and record why in the decision log.
  - The discussion ends in one of:
    - `agreed`, possibly with an adjusted plan;
    - `intended` (by design; the finding stays visible with its rationale and any residual risk);
    - `deferred` (with when to revisit);
    - `rejected` (shown to be wrong; kept so later runs don't re-raise it);
    - `duplicate → <id>`.

Update `REPORT.md` as you go. The decision log at the end of the report records the date, finding ID, decision and reason.

## When every finding is settled

1. Summarise the agreed plan in fix order:
   - the fix groups;
   - size;
   - risk;
   - regression tests;
   - dependencies (from the Architect's sequence).
2. Show the proposed board (`work-items-and-prs.md`):
   - the parent work item `{SystemName}-TLC-Fixes`;
   - the short list of consolidated tasks, each with the findings it covers;
   - the PR grouping.
3. Prompt: **"Let's begin!"**

The user's go-ahead covers creating the work item, the tasks and the PRs as shown. Anything beyond what was shown needs a fresh go-ahead: extra tasks, other projects' boards, merging, deploying.

If the user doesn't want to begin, the report is the deliverable. It is complete and shareable.

## Passing it on

At the end of the walkthrough, remind the user:
- **the report:** the summary, BA questions and PM concerns are for the PM and BA. Pass it on to the previous developer(s) of this system, if applicable;
- **`SHESHA-TEAM-REPORT.md`** (if any) goes to the Shesha team, together with the copy-paste SR text for each issue marked *Log an SR*.
