# Adding a check

A check is one Python file in `scripts/checks/`. The runner imports every module there that
doesn't start with `_`, so nothing needs registering by hand. There are four steps, and the
tests enforce steps 2 and 3.

## 1. Write `scripts/checks/<snake_name>.py`

```python
"""<check-id>: <one line: what must be true>.

<Why it matters, which Shesha versions it applies to, and any framework issue/PR links.>
"""
from __future__ import annotations

import re

from core import Check, Edit, Finding, Issue, NotFixable, Repo, Status, register

BAD_RE = re.compile(r"<pattern that identifies the misconfiguration>")


@register
class MyCheck(Check):
    id = "<check-id>"                      # kebab-case, stable forever (used on the CLI and in reports)
    title = "<what must be true>"
    severity = "high"                      # high | medium | low
    doc = "references/checks.md section <N>"
    options = {"threshold": 10}            # typed defaults; CLI: --set <check-id>.threshold=5

    def applies(self, repo: Repo) -> tuple[bool, str]:
        # Optional. Return (False, reason) for n/a, e.g. the framework version lacks the feature.
        # Prefer repo.package_has_symbol(pkg, dll, symbol) over version arithmetic.
        return True, ""

    def scan(self, repo: Repo) -> Finding:
        issues = []
        for path, text, m in repo.grep(BAD_RE):            # all .cs files, bin/obj excluded
            issues.append(Issue(Status.FAIL, "<plain-English problem>",
                                repo.loc(path, text, m.start()), fixable=True))
        return Finding.from_issues(self.id, issues, "<summary when nothing is wrong>")

    def fix(self, repo: Repo, finding: Finding) -> list[Edit]:
        # Omit fix() entirely for report-only checks.
        edits = []
        for path in {p for p, _, _ in repo.grep(BAD_RE)}:
            text = repo.read(path)                          # includes earlier checks' staged edits
            edits.append(Edit(path, BAD_RE.sub("<replacement>", text), "<what changed>"))
        if not edits:
            raise NotFixable("<why, and where the manual steps are>")
        return edits
```

### Rules

- **Never write files or call a live backend with side effects.** Return `Edit`s. The runner
  shows the diff and writes only with `--apply`. `repo.live` is for reads only.
- **Fix only shapes you recognise.** Anything else should be `Status.MANUAL`, or `NotFixable`
  with a pointer to the manual steps. A wrong automatic edit is worse than none.
- **Be idempotent.** Once fixed, `scan` must return PASS and `fix` must propose nothing.
- **Preserve formatting.** Work on the text from `repo.read` (line endings kept), use
  `newline_of`, `line_indent`, `matching_brace` and `ensure_using` from `core`, and change as
  few characters as possible.
- **Choose status carefully.** Use FAIL for a confirmed problem, WARN for weak-but-working,
  MANUAL when a human must judge, SKIP when an input was missing (e.g. no `--base-url`), and n/a
  via `applies()`. Only FAIL makes the exit code 1.
- **Look for the bad thing, not the absence of the good thing,** when the framework provides a
  safe default. `user-lockout` is the example: Shesha enables lockout by default, so its absence
  in source is not a finding.
- **Gate a fix on the framework version** when it needs an API that older Shesha lacks. Report the
  problem as usual, but mark the issues `fixable=False` and set `finding.blocked` to a short reason
  that ends with what to do (e.g. `"needs Shesha X; upgrade, then re-run"`). The runner prints it as
  a warning and puts it in the final report's *Action taken* column. `hangfire-dashboard` is the example.
- **Deleting a file** is `Edit(path, None, "<why>")`. It shows as a diff to `/dev/null`, and an
  emptied folder is removed on `--apply`. Delete only files the check can prove are unused.
- **Keep `Edit.description` short and specific.** It becomes a bullet in the check's commit message
  and the *Action taken* text in the final report.
- **Live checks** read through `repo.live.get(path)` and must degrade to a note or SKIP when
  `repo.live` is None.

## 2. Document it in `references/checks.md`

Append `## Section <N>. \`<check-id>\`: <title>` with **Why**, **Detection**, **Automatic fix**,
**Manual fix** and **Verify**. Use the next free number, never renumber, and set `doc` to match.

## 3. Add it to the catalog table in `SKILL.md`

## 4. Add fixture tests to `scripts/test_checks.py`

Subclass `RepoCase`, `put()` the smallest files that reproduce the problem, and use
`run_check()` to assert FAIL, then the expected edit, then PASS. Cover each code shape the fixer
handles and one shape it must refuse. Run:

```bash
python <skill-dir>/scripts/test_checks.py
```

## The shared determinism contract

Every check emits into the shared schema (hub: `auditing-application-security`,
`references/determinism-standard.md` + `references/check-registry.md`). When you add a check, also
set its contract metadata so its findings are reproducible and not double-identified against the
audit skill:

- `canonical_id` = the **shared** registry CHECK-ID this fix owns (reuse the audit's id where the
  issue overlaps; add `canonical_refs` for secondary ids). `canonical_id` defaults to `id` only for
  app-only checks with no registry row.
- the three scoring inputs `impact_class` / `reachability` / `data_sensitivity` (severity is
  **derived** via `scored_severity()`, never asserted; the flat `severity` is a display alias). An
  issue may override these per-anchor (e.g. a credentials-escalation that scores higher).
- `root_cause` (an `RC-sec-*` id), `plan_id`, `regression_test`, and the decision-procedure fields
  `decision_input` / `decision_predicate` / `decision_verdict` / `anchor_strategy`.
- set `deterministic = False`, or mark individual `Issue(non_deterministic=True)`, for
  MANUAL/undecidable cases - the normalizer drops them from the acceptance diff.

On each `Issue`, set a **symbol/role `anchor`** (use `member_anchor` / `type_anchor` /
`config_anchor` / `sln_anchor` from `core`, **never** a line number - `location` stays as the
non-diffed display locator) and an `evidence` level (`CODE_ONLY` static, `VERIFIED_ARTEFACT`
restored-DLL/scanner/grep, `REPRODUCED` live, `NOT_ASSESSED` when a capability is absent). Report
secrets by `secret_fingerprint()` (presence + length + `sha256:<12>`) only, and pass the literal in
`Edit(redactions=...)` so the shown diff is masked. Prove reproducibility with `diff_runs.py`
(two scans on one commit → exit 0).

## Candidate checks

These are findings from Shesha security audits that are fixable at application level:

| Candidate id | What | Notes |
|---|---|---|
| `admin-default-password` | `admin` / `123qwe` still authenticates | live-only; POST to Authenticate, report-only; framework issue #4614 |
| `security-headers` | no `UseSecurityHeaders()` / HSTS in Startup | framework #4660 (registry A6/A7/A8) |
| `elmah-exposed` | `/elmah` reachable without a permission check | registry A11 |
| `swagger-in-production` | Swagger UI enabled outside Development | `SecuritySettings.SwaggerUiEnabled` defaults to true (registry A5/E2) |
| `rate-limiting` | no `AddRateLimiter` on login / OTP / password-reset for versions before 0.46 | framework #4771 (fixed on main only), #4773 (registry J1/J3) |
| `generate-app-service` | entities that must never have CRUD APIs lack `GenerateApplicationServiceState.DisableGenerateApplicationService` | registry D3 |
| `per-user-lockout` | existing users with `IsLockoutEnabled = false` | live; follow-on to `user-lockout` |

Implemented since: `jwt-signing-key` (section 5, registry B1/I2/SEC-P) and `cors-origins`
(section 6, registry A2/A3/B3).
