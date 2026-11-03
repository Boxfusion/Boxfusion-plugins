<!-- One finding. Plain English first, technical evidence last. No names. History = date + PR/commit link only.
Full form: critical and high findings. Compact form (at the end): medium findings. Low findings: one table row.
An unproven critical finding's title says "The configuration allows…" or "The code allows…" until it is reproduced. -->

### <ID> <Short title saying what happens, not what the code is>

**Area:** code | sql | orm | security | ops | forms (as in `references/team.md`, "ID ranges"; safety nets are `ops`)
**Severity:** critical | high | medium | low. **Harm:** life-safety / lost work / data exposure / integrity / reliability / performance / maintainability
**Evidence:** REPRODUCED | CONFIRMED-IN-LOGS | VERIFIED-ARTEFACT | CODE-ONLY | DATA-ANOMALY
**Merged from:** <source ids, if merged>
**Task:** T<n>. **Root cause:** RC<n> (if any)
**Status:** open
**Reproducing test:** <test name and project or spec path, failing today>, fails because: <one-line assertion message showing the finding's behaviour, not a login or setup error> | none (why: no harness reaches it / quick mode)
**Covered by existing tests?** yes (<test>) / no
**Scale:** <how often or how much, e.g. "about 1,100 failed creates a month", "every incident list load">

**What happens**
<Two or three sentences a PM can follow. What a user or the business experiences.>

**Why this is a problem** *(for developers new to this)*
<The underlying principle in plain English. Why the pattern is harmful in general, then why it matters here. Use an analogy if it helps.>

**Where**
<file:line, endpoint, procedure, form name and version. Since: <date>, <PR/commit link> if known.>

**What good looks like**
<The pattern that avoids it, in plain English, using the framework's native mechanism (see ${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md), with a short before/after sketch where it helps.>

**Plan of action**
- Fix: <what to change, via which framework mechanism (.shaconfig package, specification, validator, app service command, …)>
- Size: S | M | L. Risk: <what could break>
- Depends on / related: <IDs>
- Regression test: <integration test or e2e spec to add or keep, named; reuse the reproducing test if there is one> | none (<why>)
- Verify by: <the reproduction to rerun, the metric to watch>

**Questions for the BA** *(if any)*
- <intended business behaviour, rules, who should see what>

**Concerns for the PM** *(if any)*
- <risk, sequencing, release, effort, skills>

**Evidence**
<How it was proven: queries, counts, status codes, reproduction steps with synthetic data. No personal data. Note any part of the finding a test disproved, and any fact-check correction.>

---

<!-- Compact form, for medium findings: 10-12 lines. No "Why" paragraph: point to the root cause or the learning digest. -->

### <ID> <Short title saying what happens>

**Severity:** medium · **Harm:** <harm> · **Evidence:** <level> · **Task:** T<n> · **Root cause:** RC<n> / digest: <pattern>
- <what happens, one line>
- <scale or consequence, one line>
- <optional third point>

**Where:** <one-line pointer: file:line or form and version>
**Fix:** <framework mechanism, one or two lines>. **Size:** S/M/L. **Risk:** <one line>
**Regression test:** <name> | none (<why>)
**Evidence:** `diagnosis/findings/<area>.md` (<ID>)
