"""cors-origins: CORS must not allow any origin, and never a wildcard origin with credentials.

A wildcard CORS origin (`AllowAnyOrigin()` or `WithOrigins("*")`, or `App:CorsOrigins` set to
`*`) lets any website read authenticated responses from the API in a logged-in user's browser.
Combined with `AllowCredentials()` it is a cross-origin auth bypass: the browser spec forbids
`*`+credentials, so a project that ships both has usually widened a concrete allowlist to `*`
by hand (framework #4618).

This check is the FIX owner for the shared CHECK-IDs A2 (wildcard origin), A3 (wildcard +
credentials) and B3 (appsettings CorsOrigins). The correct allowlist is environment-specific,
so this check REPORTS and routes to a manual fix rather than guessing origins - a wrong CORS
edit either breaks the app or re-opens the hole. See references/checks.md section 6.
"""
from __future__ import annotations

import re

from core import (Check, Edit, Evidence, Finding, Issue, NotFixable, Repo, Status, config_anchor,
                  enclosing_type, member_anchor, register)

ANY_ORIGIN_RE = re.compile(r"\bAllowAnyOrigin\s*\(\s*\)")
WITH_WILDCARD_RE = re.compile(r'\bWithOrigins\s*\(\s*[^)]*"\*"')
CREDENTIALS_RE = re.compile(r"\bAllowCredentials\s*\(\s*\)")
CORS_FILE_RE = re.compile(r"\bUseCors\b|\bAddCors\b|\bWithOrigins\b|\bAllowAnyOrigin\b")
CORS_KEY = "App:CorsOrigins"


@register
class CorsOrigins(Check):
    id = "cors-origins"
    title = "CORS does not allow any origin (and never a wildcard with credentials)"
    severity = "high"
    doc = "references/checks.md section 6"
    # shared determinism contract (check-registry.md A2; per-issue A3 and B3)
    canonical_id = "A2"
    canonical_refs = ["A1", "A3", "B3"]
    impact_class = "info_leak"
    reachability = "anonymous"
    data_sensitivity = "none"
    root_cause = "RC-sec-cors"
    deterministic = True
    plan_id = "PLAN-cors-restrict-origins"
    regression_test = "scripts/test_checks.py::CorsOriginsTests"
    decision_input = "CORS policy in C# (AllowAnyOrigin / WithOrigins(\"*\") / AllowCredentials) and App:CorsOrigins in appsettings"
    decision_predicate = "wildcard origin -> FAIL (A2/B3); wildcard origin AND AllowCredentials in the same file -> FAIL (A3, auth bypass)"
    decision_verdict = "FAIL = any website can read authenticated API responses in a logged-in user's browser"
    anchor_strategy = "code: <path>#<Type>.Cors; appsettings: <path>#key:App:CorsOrigins (never a line number)"

    def scan(self, repo: Repo) -> Finding:
        issues: list[Issue] = []
        # ---- C# policy
        for path in repo.cs_files():
            text = repo.read(path)
            m = ANY_ORIGIN_RE.search(text) or WITH_WILDCARD_RE.search(text)
            if not m:
                continue
            loc = repo.loc(path, text, m.start())
            anchor = member_anchor(repo.rel(path), enclosing_type(text, m.start()), "Cors")
            if CREDENTIALS_RE.search(text):
                issues.append(Issue(Status.FAIL, "CORS allows a wildcard origin together with "
                                    "AllowCredentials() - any site can make authenticated cross-origin "
                                    "calls; set a concrete origin allowlist", loc, fixable=False,
                                    anchor=anchor, evidence=Evidence.CODE_ONLY, canonical_id="A3",
                                    impact_class="auth_bypass"))   # A3 escalates to Critical
            else:
                issues.append(Issue(Status.FAIL, "CORS allows any origin (wildcard); restrict it to the "
                                    "application's own front-end origins", loc, fixable=False,
                                    anchor=anchor, evidence=Evidence.CODE_ONLY))
        # ---- appsettings App:CorsOrigins
        for path in repo.appsettings():
            value = repo.json_get(path, CORS_KEY)
            if isinstance(value, str) and "*" in [o.strip() for o in value.split(",")]:
                issues.append(Issue(Status.FAIL, f"{CORS_KEY} contains a wildcard '*'; list the exact "
                                    "front-end origins instead", repo.rel(path), fixable=False,
                                    anchor=config_anchor(repo.rel(path), CORS_KEY),
                                    evidence=Evidence.CODE_ONLY, canonical_id="B3"))
        return Finding.from_issues(self.id, issues, "CORS does not allow any origin")

    def fix(self, repo: Repo, finding: Finding) -> list[Edit]:
        # The correct origin allowlist is environment-specific; guessing it would break the app or
        # re-open the hole. Report and route to the manual fix (skill principle: recognise or leave
        # to a human). See references/checks.md section 6.
        raise NotFixable("the correct CORS origin allowlist is environment-specific and cannot be "
                         "guessed safely; set it by hand - see references/checks.md section 6")
