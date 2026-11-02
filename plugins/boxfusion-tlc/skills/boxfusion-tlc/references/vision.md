# boxfusion-tlc: product vision and requirements

These requirements come from the product owner's own statements (Igor Kors, lead) in the build conversation, 2026-10. Each line is a testable requirement. The source is paraphrased.

## Purpose
- **V1.** Turn "the system keeps having problems" into a proven, ranked, plain-English list of findings, each with a plan of action. Once the user agrees, fix the problems the framework's way.
- **V2.** Work as a learning experience. Many systems were built by developers early in their careers, so each finding explains why the pattern is harmful and what good looks like, using the system's own code.
- **V3.** Built for BoxFusion Shesha / ABP systems. Inspect the Shesha version, and flag framework defects to the Shesha team.

## Audience and interaction
- **V4.** The skill talks only to the person who started it. Everyone else receives documents through them.
- **V5.** The report has sections for the BA (questions) and the PM (concerns), wherever they apply.
- **V6.** For each finding, offer **Agree** or **Discuss**. The user may know something the skill doesn't, so Discuss checks their information against the code and data.
- **V7.** When every finding is settled, prompt with **"Let's begin!"**. Nothing gets fixed before that.
- **V8.** No blame. Cite a date and a PR or commit link where history helps; never name or identify people. Don't try to identify the graduate developers. The summary ends with a note asking the initiator to pass it on to the previous developer(s).
- **V9.** Quiet during a run. The user sees one-line progress updates, then the report. Raw specialist output and tool noise stay out of the chat. The only interruption is an urgent alert for a critical exposure that is live now.
- **V10.** No unnecessary prompts. Anything that is a company standard, or has an obvious default, happens automatically.

## Test coverage (company standard)
- **V11.** Test coverage comes first, always, and automatically: integration tests plus the e2e harness. It uses the existing BoxFusion skills (shesha-auto-testing, shesha-utils / create-integration-tests). The user isn't asked.
- **V12.** Phase 0 runs **in parallel** with the inspection sweep. The staff is doubled to fit modern laptops, and the run aims to take far less than 5 hours. Only the proof phase waits for the harness.
- **V13.** Every finding is proven, preferably by a test that fails today and becomes its regression test: "Always investigate, and reproduce to build up proof." Anomalies are chased until they are explained, so poor data isn't mistaken for a defect.
- **V14.** Java/Allure must not block anyone from getting tests running; it is optional.

## Team
- **V15.** A team of specialists working in parallel, with topic ownership:
  - DevOps engineer, Developer, SQL developer, ORM/Shesha specialist, Security reviewer and Forms analyst;
  - a Senior Engineer who consolidates;
  - an Architect for root causes and fix order;
  - a Tester;
  - a fact-checker.
- **V16.** The inspection covers:
  - **Code:** bad patterns.
  - **SQL:** indexes, procedures, raw SQL.
  - **ORM:** whole-graph fetches, wildcard searches, unlimited queries, navigation-property fetches.
  - **Security:** access control, secrets.
  - **SignalR setup.**
  - **Failing jobs:** SMS etc.
  - **Form design:** intent and anti-patterns.
  - **Operations and telemetry.**
- **V17.** Use discretion over dogma. For example, ELMAH stays disabled when it kills performance.

## Data safety
- **V18.** Start with a local copy of the QA database. Production data comes only by escalation to the IT Manager, and only when QA evidence of a serious issue justifies it. The IT Manager may hand the work to more senior staff. Graduates must not carry production databases on their laptops.
- **V19.** Isolate integrations automatically: email, SMS, brokers, webhooks and jobs, with a local broker stand-in. Verify the configuration with a canary check. Never touch the developer's real database or real accounts; use synthetic ZZ-PROBE users. Passwords live only in a gitignored `.env`. Personal data never leaves the machine.
- **V20.** Use App Insights where it's available, with aggregated, PII-masked queries.

## Fixing
- **V21.** Framework first. Fixes use Shesha / ABP native mechanisms:
  - `.shaconfig` packages for forms, settings, permissions and entity configuration;
  - specifications;
  - Fluent validators;
  - after-commit events.

  No custom JS, raw SQL or hand-made database edits, except in a recorded emergency that carries a follow-up item. Bypassing the framework is itself a finding.
- **V22.** One work item named `{SystemName}-TLC-Fixes`, with 5–12 consolidated tasks and PRs linked to them. Don't go overboard on tasks.
- **V23.** Each fix ships with its tests, and e2e runs before the PR is pushed.

## Framework escalation
- **V24.** A separate Shesha team report, covering framework defects only. Each defect has findings, reproduction steps and a ready-to-paste Claude prompt. Where needed, the user is flagged to log an SR, with copy-paste wording.

## Self-improvement and distribution
- **V25.** The skill can upgrade itself from what it learns: it raises a PR to `Boxfusion/Boxfusion-plugins`. **igorkors-boxfusion is always the reviewer, and the skill never merges itself.**
- **V26.** It is published in the BoxFusion Claude plugin marketplace, and stays marked as a draft until it is released.
- **V27.** Treat the skill as a product: consistent, coherent docs, and easy for the next user (a graduate) to pick up and run.

## Modes
- **V28.** Quick / deep / area modes. A trial-subject mode runs diagnosis only, with no fixes.
