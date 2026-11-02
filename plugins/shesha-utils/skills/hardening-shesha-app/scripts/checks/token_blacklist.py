"""token-blacklist: sign-out revokes the token only if the host checks the blacklist.

Since Shesha 0.43.19 (0.45.0 on the main line; 0.44.x lacks it) TokenAuthController.SignOff adds
the token's jti to a blacklist (DbTokenBlacklistService). Nothing consults that list unless the
host's JwtBearer options call context.EnsureTokenIsNotBlacklistedAsync() in OnTokenValidated -
the framework's own AuthConfigurer does, but projects generated from older templates do not.
Without it, a signed-out token keeps working until it expires.
"""
from __future__ import annotations

import re

from core import (Check, Edit, Finding, Issue, NotFixable, Repo, Status, ensure_using, line_indent,
                  matching_brace, newline_of, parse_version, register)

NAMESPACE = "Shesha.Authentication.JwtBearer"
CALL = "context => context.EnsureTokenIsNotBlacklistedAsync()"
ADD_JWT_RE = re.compile(r"\.AddJwtBearer\s*\(\s*(?:[^,()]+,\s*)?(?P<param>\w+)\s*=>")
EVENTS_RE = re.compile(r"new\s+JwtBearerEvents\s*(?:\(\s*\))?\s*(?P<brace>\{)")
ON_VALIDATED_RE = re.compile(r"\bOnTokenValidated\s*=")
TVP_RE = re.compile(r"\b(?P<param>\w+)\.TokenValidationParameters\s*=\s*new\s+TokenValidationParameters\s*(?:\(\s*\))?\s*(?P<brace>\{)")


def framework_supports(version: str | None) -> bool | None:
    v = parse_version(version)
    if v is None or len(v) < 3:
        return None
    return (0, 43, 19) <= v < (0, 44) or v >= (0, 45)


@register
class TokenBlacklist(Check):
    id = "token-blacklist"
    title = "Signed-out tokens are rejected (blacklist wired into JwtBearer)"
    severity = "high"
    doc = "references/checks.md section 2"

    def applies(self, repo: Repo) -> tuple[bool, str]:
        has = repo.package_has_symbol("Shesha.Application", "Shesha.Application.dll", "EnsureTokenIsNotBlacklistedAsync")
        if has is None:
            has = framework_supports(repo.shesha_version())
        if has is False:
            return False, (f"Shesha {repo.shesha_version()} has no token blacklist (needs 0.43.19+ on 0.43, "
                           "or 0.45.0+); sign-out cannot revoke tokens - rely on token-lifetime")
        return True, ""

    def _configurers(self, repo: Repo):
        return [p for p in repo.cs_files() if ADD_JWT_RE.search(repo.read(p))]

    def scan(self, repo: Repo) -> Finding:
        files = self._configurers(repo)
        if not files:
            return self.finding(Status.MANUAL, "no .AddJwtBearer(...) registration found in C# sources")
        issues = []
        for path in files:
            text = repo.read(path)
            if "EnsureTokenIsNotBlacklistedAsync" in text:
                continue
            m = ADD_JWT_RE.search(text)
            loc = repo.loc(path, text, m.start())
            if ON_VALIDATED_RE.search(text):
                issues.append(Issue(Status.FAIL, "OnTokenValidated has a custom handler that does not check "
                                    "the blacklist - add `await context.EnsureTokenIsNotBlacklistedAsync();` to it",
                                    loc, fixable=False))
            else:
                issues.append(Issue(Status.FAIL, "JwtBearer never checks the token blacklist, so sign-out "
                                    "does not revoke tokens", loc, fixable=True))
        notes = [] if repo.shesha_version() else ["Shesha version unknown; support assumed from restored packages"]
        return Finding.from_issues(self.id, issues, "OnTokenValidated calls EnsureTokenIsNotBlacklistedAsync", notes)

    def fix(self, repo: Repo, finding: Finding) -> list[Edit]:
        edits = []
        for path in self._configurers(repo):
            text = repo.read(path)
            if "EnsureTokenIsNotBlacklistedAsync" in text or ON_VALIDATED_RE.search(text):
                continue
            new = self._with_events(text)
            if not EVENTS_RE.search(text):   # case B introduces the JwtBearerEvents type
                new = ensure_using(new, "Microsoft.AspNetCore.Authentication.JwtBearer")
            edits.append(Edit(path, ensure_using(new, NAMESPACE), "wire token blacklist into OnTokenValidated"))
        if not edits:
            raise NotFixable("no JwtBearer registration in a shape this check can rewrite")
        return edits

    @staticmethod
    def _with_events(text: str) -> str:
        nl = newline_of(text)
        events = EVENTS_RE.search(text)
        if events:
            # Case A: an Events initializer exists - add OnTokenValidated as its first member.
            brace = events.start("brace")
            close = matching_brace(text, brace)
            body = text[brace + 1:close] if close else ""
            if body.strip() == "":
                indent = line_indent(text, brace)
                inner = indent + "    "
                return text[:brace + 1] + f"{nl}{inner}OnTokenValidated = {CALL}{nl}{indent}" + text[close:]
            first = re.search(r"\S", body)
            abs_first = brace + 1 + first.start()
            if "\n" in text[brace:abs_first]:
                indent = line_indent(text, abs_first)
                line_start = text.rfind("\n", 0, abs_first) + 1
                return text[:line_start] + f"{indent}OnTokenValidated = {CALL},{nl}" + text[line_start:]
            return text[:abs_first] + f"OnTokenValidated = {CALL}, " + text[abs_first:]

        # Case B: no Events - add `options.Events = ...;` after the TokenValidationParameters statement.
        tvp = TVP_RE.search(text)
        if not tvp:
            raise NotFixable("found neither `new JwtBearerEvents { ... }` nor a TokenValidationParameters "
                             "assignment to anchor the change")
        close = matching_brace(text, tvp.start("brace"))
        semi = text.find(";", close) if close else -1
        if semi < 0:
            raise NotFixable("could not find the end of the TokenValidationParameters statement")
        indent = line_indent(text, tvp.start())
        param = tvp.group("param")
        block = (f"{nl}{nl}{indent}{param}.Events = new JwtBearerEvents{nl}{indent}{{{nl}"
                 f"{indent}    OnTokenValidated = {CALL}{nl}{indent}}};")
        return text[:semi + 1] + block + text[semi + 1:]
