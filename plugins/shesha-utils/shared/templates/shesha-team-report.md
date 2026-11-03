<!--
Report for the Shesha framework team. Include an issue only when ALL of these hold:
1. The behaviour comes from the framework (Shesha/ABP packages or default configuration), not this system's code or configuration.
2. It is reproduced in the smallest possible case (ideally a fresh entity or form with no project customisation), preferably as a test.
3. You checked whether a newer Shesha version already fixes it (release notes, framework repo, or a quick test on a newer version).
No personal data, no secrets, no customer names unless the user agrees.
Inspect framework behaviour in the pinned NuGet packages (decompile with ilspycmd) before claiming a defect.
Recurring framework defect patterns seen so far:
- anonymous or under-protected framework endpoints (e.g. settings reads returning secret values);
- package defaults pointing at shared servers, or shipping shared credentials (describe generically; never include the credential);
- framework base classes that rewrap exceptions without the inner exception;
- generic CRUD on framework security tables open to any authenticated user by default.
Order issues by urgency, and flag the ones likely to affect every system on that version (cross-project disclosure).
-->

> **Urgent issues** (exposure in every system on this version): <issue numbers, or "none">. Ask for a patch and an advisory, and offer the interim workaround.

# Shesha framework issues found during a TLC review

**Shesha version(s) affected:** <backend Shesha.* / @shesha-io/reactjs>. **Checked on newer:** <version: fixed / not fixed / not tested>
**Found in:** <system name, or "a BoxFusion production system" if preferred>. **Date:** <date>

| # | Issue | Impact | Reproduced in a minimal case? | Log an SR? |
|---|---|---|---|---|
| 1 | <title> | <one line> | yes (test name) | yes / no |

---

## Issue 1: <Component>: <one-line description of the incorrect behaviour>

**Versions:**
- Shesha <x> (backend), @shesha-io/reactjs <y>;
- .NET <v>; SQL Server <v>; browser <v> (if front end).

**Summary**
<Two or three sentences: what the framework does, and why it is wrong or harmful.>

**Where in the framework**
<Package, class and method if known (e.g. from decompiling), configuration default, generated endpoint>

**Minimal reproduction**
1. <setup: a fresh entity, form or endpoint>
2. <action>
3. <observe>

Reproducing test: <test name and code, or attached file>

**Expected behaviour**
<what should happen>

**Actual behaviour**
<what happens: status codes, exception and stack frame, generated SQL shape, response size>

**Impact**
<who is affected and how badly, including other projects likely to be affected>

**Workaround used in the meantime**
<what the system did instead, using the framework's own mechanisms>

**Suggested fix**
<if known>

**Ready-to-paste Claude prompt**

```text
You are working in the Shesha framework repository (<repo/branch>), version <x>.
Problem: <one-paragraph description>.
Reproduce it first:
<minimal steps, or the reproducing test to add, with its code>
Expected: <...>. Actual: <...>.
Relevant code: <package/class/method, file paths if known>.
Tasks:
1. Write a failing test that reproduces the issue in the framework's own test suite.
2. Find the root cause and explain it briefly.
3. Propose and implement a fix that keeps backward compatibility, or explain the breaking change and the migration path.
4. Run the framework's tests and report the results.
Do not change unrelated behaviour.
```

**Log an SR?** yes / no. *(An SR is a support request logged with the Shesha team. Say yes when the issue is urgent, affects other systems, or needs a framework patch to fix properly.)*

If yes, the user pastes this into the SR:

```text
Shesha <version>: <one-line description of the defect>.
Impact: <one line>.
Reproduction: see the attached Shesha team report, issue <n>.
Urgent: yes / no.
```

---
<repeat per issue>

---

## Candidates still to reproduce before sending

<Framework-side suspicions from this run not yet reproduced in a minimal case. One line each: what, where in the framework, why it looks like a framework defect, and the minimal reproduction to try. Move an item up into the issues above only once it meets all three conditions at the top of this template.>
