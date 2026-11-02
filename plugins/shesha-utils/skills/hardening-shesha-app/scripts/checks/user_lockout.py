"""user-lockout: failed-login lockout is not disabled or weakened.

Shesha's framework module enables lockout by default (5 failed attempts, 300 seconds) through
ISecuritySettings. A source search for "LockoutEnabled" finds nothing in a healthy repo, which
is why this check looks for code that switches it OFF or weakens it rather than for its
presence. The effective value lives in the database, so with --base-url the check also reads
it from AuthorizationSettings/GetSettings (read-only).
"""
from __future__ import annotations

import re
import urllib.error

from core import Check, Edit, Finding, Issue, NotFixable, Repo, Status, register

DISABLE_DEFAULT_RE = re.compile(r"UserLockOutEnabled\s*\.\s*WithDefaultValue\(\s*false\s*\)")
DISABLE_SET_RE = re.compile(r"UserLockOutEnabled\s*\.\s*SetValue(?:Async)?\(\s*false\s*\)")
DISABLE_RAW_RE = re.compile(r'UserLockOut\.IsEnabled["\s,)]*[^;\n]*\bfalse\b', re.IGNORECASE)
MAX_RE = re.compile(r"MaxFailedAccessAttemptsBeforeLockout\s*\.\s*(?:WithDefaultValue|SetValue(?:Async)?)\(\s*(\d+)\s*\)")
SECONDS_RE = re.compile(r"DefaultAccountLockoutSeconds\s*\.\s*(?:WithDefaultValue|SetValue(?:Async)?)\(\s*(\d+)\s*\)")
NO_LOCKOUT_LOGIN_RE = re.compile(r"shouldLockout\s*:\s*false")
SETTINGS_URL = "/api/services/app/AuthorizationSettings/GetSettings"


@register
class UserLockout(Check):
    id = "user-lockout"
    title = "Failed-login account lockout is enabled"
    severity = "high"
    doc = "references/checks.md section 3"
    options = {"max_attempts": 10, "min_seconds": 60}

    def scan(self, repo: Repo) -> Finding:
        issues: list[Issue] = []
        for path, text, m in repo.grep(DISABLE_DEFAULT_RE):
            issues.append(Issue(Status.FAIL, "lockout disabled by default in code", repo.loc(path, text, m.start()), True))
        for rx in (DISABLE_SET_RE, DISABLE_RAW_RE):
            for path, text, m in repo.grep(rx):
                issues.append(Issue(Status.FAIL, "code or migration sets lockout off", repo.loc(path, text, m.start())))
        for path, text, m in repo.grep(MAX_RE):
            if int(m.group(1)) > self.opts["max_attempts"]:
                issues.append(Issue(Status.WARN, f"lockout only after {m.group(1)} failed attempts "
                                    f"(<= {self.opts['max_attempts']} expected)", repo.loc(path, text, m.start())))
        for path, text, m in repo.grep(SECONDS_RE):
            if int(m.group(1)) < self.opts["min_seconds"]:
                issues.append(Issue(Status.WARN, f"lockout lasts only {m.group(1)} s "
                                    f"(>= {self.opts['min_seconds']} expected)", repo.loc(path, text, m.start())))
        for path, text, m in repo.grep(NO_LOCKOUT_LOGIN_RE):
            issues.append(Issue(Status.MANUAL, "LoginAsync(..., shouldLockout: false) - fine when re-checking the "
                                "current user's password, a bypass if this is a login path",
                                repo.loc(path, text, m.start())))

        notes = []
        if repo.live:
            issues += self._live(repo, notes)
        else:
            notes.append("no code override means the framework default (enabled, 5 attempts, 300 s) applies "
                         "unless changed in the database - pass --base-url to read the effective value")
        return Finding.from_issues(self.id, issues, "lockout is not disabled or weakened in code", notes)

    def _live(self, repo: Repo, notes: list[str]) -> list[Issue]:
        where = repo.live.base_url + SETTINGS_URL
        try:
            s = repo.live.get(SETTINGS_URL) or {}
        except (urllib.error.URLError, KeyError, ValueError) as exc:
            return [Issue(Status.SKIP, f"could not read live settings: {exc}", where)]
        enabled = s.get("isLockoutEnabled")
        attempts = s.get("maxFailedAccessAttemptsBeforeLockout")
        seconds = s.get("defaultAccountLockoutSeconds")
        notes.append(f"live: enabled={enabled}, attempts={attempts}, seconds={seconds}")
        out = []
        if enabled is False:
            out.append(Issue(Status.FAIL, "lockout is switched off in the live settings", where))
        if isinstance(attempts, int) and attempts > self.opts["max_attempts"]:
            out.append(Issue(Status.WARN, f"live: lockout only after {attempts} attempts", where))
        if isinstance(seconds, int) and seconds < self.opts["min_seconds"]:
            out.append(Issue(Status.WARN, f"live: lockout lasts only {seconds} s", where))
        return out

    def fix(self, repo: Repo, finding: Finding) -> list[Edit]:
        edits = []
        for path in {p for p, _, _ in repo.grep(DISABLE_DEFAULT_RE)}:
            text = repo.read(path)
            new = DISABLE_DEFAULT_RE.sub("UserLockOutEnabled.WithDefaultValue(true)", text)
            edits.append(Edit(path, new, "enable lockout by default"))
        if not edits:
            raise NotFixable("only the code default can be fixed automatically; live settings and "
                             "migrations are changed by hand - see " + self.doc)
        return edits
