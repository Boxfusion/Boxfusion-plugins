"""token-lifetime: the JWT access token lifetime set on TokenAuthConfiguration.Expiration.

A JWT stays valid until it expires, whatever sign-out does, so the lifetime is how long a
stolen token keeps working. Shesha starter templates hard-code TimeSpan.FromDays(n) in the
{Project}WebCoreModule; this check flags long lifetimes and rewrites the assignment to a
configurable value with a short default.
"""
from __future__ import annotations

import re

from core import Check, Edit, Finding, Issue, NotFixable, Repo, Status, register

CONFIG_KEY = "Authentication:JwtBearer:TokenLifetimeMinutes"
ASSIGN_RE = re.compile(r"(?P<lhs>\b\w+\.Expiration\s*=\s*)(?P<rhs>[^;]+);")
LITERAL_RE = re.compile(r"^\s*TimeSpan\.From(?P<unit>Days|Hours|Minutes|Seconds)\(\s*(?P<n>\d+(?:\.\d+)?)\s*\)\s*$")
NEW_TS_RE = re.compile(r"^\s*new\s+TimeSpan\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)\s*$")   # h, m, s
CONFIG_REF_RE = re.compile(r'\[\s*"(?P<key>Authentication:JwtBearer:[^"]+)"\s*\]')
FALLBACK_RE = re.compile(r":\s*(?P<n>\d+)\s*\)?\s*$")
CONFIG_VAR_RE = re.compile(r'(?P<var>\b_?\w+)\s*\[\s*"Authentication:JwtBearer:')
UNIT_MINUTES = {"Days": 1440, "Hours": 60, "Minutes": 1, "Seconds": 1 / 60}


def _config_minutes(value) -> float | None:
    """Interpret an appsettings value as minutes: a number, or a TimeSpan string like 02:00:00 / 1.00:00:00."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        if value.strip().isdigit():
            return float(value)
        m = re.match(r"^\s*(?:(\d+)\.)?(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$", value)
        if m:
            d, h, mi, s = (int(g or 0) for g in m.groups())
            return d * 1440 + h * 60 + mi + s / 60
    return None


def _hard_coded_minutes(rhs: str) -> float | None:
    if (m := LITERAL_RE.match(rhs)):
        return float(m.group("n")) * UNIT_MINUTES[m.group("unit")]
    if (m := NEW_TS_RE.match(rhs)):
        h, mi, s = (int(g) for g in m.groups())
        return h * 60 + mi + s / 60
    return None


def _fmt(minutes: float) -> str:
    if minutes >= 1440 and minutes % 1440 == 0:
        return f"{int(minutes // 1440)} day(s)"
    if minutes >= 60:
        return f"{minutes / 60:g} hour(s)"
    return f"{minutes:g} minute(s)"


@register
class TokenLifetime(Check):
    id = "token-lifetime"
    title = "JWT access token lifetime is short"
    severity = "high"
    doc = "references/checks.md section 1"
    options = {"minutes": 120, "warn_hours": 8, "fail_hours": 24}

    def _assignments(self, repo: Repo):
        files = [p for p in repo.cs_files() if "TokenAuthConfiguration" in repo.read(p)]
        return list(repo.grep(ASSIGN_RE, files))

    def _judge(self, minutes: float, where: str, what: str, fixable: bool) -> Issue | None:
        if minutes > self.opts["fail_hours"] * 60:
            status = Status.FAIL
        elif minutes > self.opts["warn_hours"] * 60:
            status = Status.WARN
        else:
            return None
        return Issue(status, f"token lifetime is {_fmt(minutes)} ({what}); target {_fmt(self.opts['minutes'])}",
                     where, fixable)

    def scan(self, repo: Repo) -> Finding:
        hits = self._assignments(repo)
        if not hits:
            return self.finding(Status.MANUAL, "no TokenAuthConfiguration.Expiration assignment found; "
                                "the framework default applies - confirm what it is for this version")
        issues, ok = [], []
        for path, text, m in hits:
            loc = repo.loc(path, text, m.start())
            rhs = m.group("rhs")
            minutes = _hard_coded_minutes(rhs)
            if minutes is not None:
                issue = self._judge(minutes, loc, "hard-coded", fixable=True)
                issues.append(issue) if issue else ok.append(f"{_fmt(minutes)} at {loc}")
                continue
            ref = CONFIG_REF_RE.search(rhs)
            if not ref:
                issues.append(Issue(Status.MANUAL, f"unrecognised expression `{rhs.strip()}`", loc))
                continue
            # configuration-driven: judge every appsettings value and the code fallback
            key = ref.group("key")
            found = False
            for settings in repo.appsettings():
                minutes = _config_minutes(repo.json_get(settings, key))
                if minutes is None:
                    continue
                found = True
                issue = self._judge(minutes, repo.rel(settings), f"{key} in appsettings", fixable=True)
                issues.append(issue) if issue else ok.append(f"{_fmt(minutes)} in {repo.rel(settings)}")
            if (fb := FALLBACK_RE.search(rhs)):
                found = True
                minutes = float(fb.group("n"))
                issue = self._judge(minutes, loc, "code fallback when the setting is absent", fixable=False)
                issues.append(issue) if issue else ok.append(f"{_fmt(minutes)} fallback at {loc}")
            if not found:
                issues.append(Issue(Status.MANUAL, f"lifetime is read from {key} but no value was found in "
                                    "appsettings and no code fallback was recognised", loc))
        notes = []
        refresh = self._frontend_refreshes(repo)
        if refresh is False:
            notes.append("front end does not appear to call /api/TokenAuth/RefreshToken - a short lifetime "
                         "will log active users out when it expires")
        elif refresh:
            notes.append("front end calls /api/TokenAuth/RefreshToken, so a short lifetime ends idle "
                         "sessions without interrupting active ones")
        return Finding.from_issues(self.id, issues, "token lifetime is " + ", ".join(ok), notes)

    @staticmethod
    def _frontend_refreshes(repo: Repo) -> bool | None:
        bundles = list(repo.root.glob("*/node_modules/@shesha-io/reactjs/dist/index.js"))
        if not bundles:
            return None
        return any(b"/api/TokenAuth/RefreshToken" in b.read_bytes() for b in bundles)

    def fix(self, repo: Repo, finding: Finding) -> list[Edit]:
        minutes = int(self.opts["minutes"])
        edits: list[Edit] = []
        targets = {i.location for i in finding.issues if i.fixable and i.location}

        # 1. hard-coded assignments -> configurable value with a short default
        for path in {p for p, _, _ in self._assignments(repo)}:
            text = repo.read(path)
            changed = text
            for m in reversed(list(ASSIGN_RE.finditer(text))):
                if repo.loc(path, text, m.start()) not in targets or _hard_coded_minutes(m.group("rhs")) is None:
                    continue
                var = CONFIG_VAR_RE.search(text)
                new_rhs = (f'TimeSpan.FromMinutes(int.TryParse({var.group("var")}["{CONFIG_KEY}"], '
                           f"out var tokenLifetimeMinutes) ? tokenLifetimeMinutes : {minutes})"
                           if var else f"TimeSpan.FromMinutes({minutes})")
                changed = changed[:m.start("rhs")] + new_rhs + changed[m.end("rhs"):]
            if changed != text:
                edits.append(Edit(path, changed, f"token lifetime -> {_fmt(minutes)}"
                                  + (f", overridable with {CONFIG_KEY}" if CONFIG_VAR_RE.search(text) else "")))

        # 2. configuration-driven lifetimes -> rewrite the over-long appsettings values
        keys = {r.group("key") for _, _, m in self._assignments(repo) if (r := CONFIG_REF_RE.search(m.group("rhs")))}
        for rel in sorted(t for t in targets if t.endswith(".json")):
            path = repo.root / rel
            text = repo.read(path)
            for key in keys:
                leaf = re.escape(key.split(":")[-1])
                hits = list(re.finditer(rf'("{leaf}"\s*:\s*)("[^"]*"|[\d.]+)', text))
                if len(hits) != 1:
                    raise NotFixable(f'{rel}: expected exactly one "{key.split(":")[-1]}" entry, found {len(hits)}')
                h = hits[0]
                quoted = h.group(2).startswith('"')
                if "minute" in key.lower():
                    value = f'"{minutes}"' if quoted else str(minutes)
                elif minutes < 1440:
                    value = f'"{minutes // 60:02d}:{minutes % 60:02d}:00"'
                else:
                    raise NotFixable("a TimeSpan-formatted setting needs minutes < 1440")
                text = text[:h.start(2)] + value + text[h.end(2):]
            edits.append(Edit(path, text, f"{rel}: token lifetime -> {_fmt(minutes)}"))

        if not edits:
            raise NotFixable("no assignment or setting in a shape this check can rewrite")
        return edits
