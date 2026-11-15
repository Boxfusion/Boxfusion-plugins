"""hangfire-dashboard: /hangfire is mapped by the framework's UseSheshaHangfireDashboard().

Projects generated from the Shesha starter map the dashboard themselves with
`app.UseHangfireDashboard("/hangfire", new DashboardOptions { Authorization = new[] { new
HangfireAuthorizationFilter() } })`, where the filter is an app-level class that grants access to
whoever the Abp.AuthToken cookie *says* is "admin". The token is only parsed (ReadToken), never
validated, so a hand-made unsigned token gets in. The framework's own filter in
Shesha.Scheduler.Hangfire checks Pages.Hangfire but reads the user the same way.

shesha-io/shesha-framework#5554 adds UseSheshaHangfireDashboard() (Shesha.Scheduler.Extensions),
which validates the token and checks Pages.Hangfire. This check swaps the app's call for it and
deletes the app-level filter - but only once the restored Shesha.Scheduler package contains the
extension. On older versions it reports the problem and asks the user to upgrade and re-run.
"""
from __future__ import annotations

import re
from pathlib import Path

from core import (Check, Edit, Evidence, Finding, Issue, NotFixable, Repo, Status, ensure_using,
                  enclosing_type, matching_brace, member_anchor, register, type_anchor)

EXTENSION = "UseSheshaHangfireDashboard"
EXTENSION_NS = "Shesha.Scheduler.Extensions"
FRAMEWORK_FILTER_NS = "Shesha.Scheduler.Hangfire"
DEFAULT_PATH = "/hangfire"
ISSUE = "shesha-io/shesha-framework#5554"

CALL_RE = re.compile(r"\.UseHangfireDashboard\s*(?P<paren>\()")
# Recognised arguments: optional path literal, then optional `new DashboardOptions { Authorization = new[] { ... } }`
ARGS_RE = re.compile(r"""\A\s*(?:"(?P<path>[^"\\]*)")?\s*,?\s*
    (?:new\s+DashboardOptions\s*(?:\(\s*\))?\s*\{\s*
        (?:Authorization\s*=\s*new\s*(?:[\w.]*IDashboardAuthorizationFilter\s*)?\[\s*\]\s*\{
            (?P<filters>[^{}]*)\}\s*,?\s*)?
    \}\s*)?\Z""", re.X)
FILTER_RE = re.compile(r"\s*new\s+(?P<name>[\w.]+)\s*\(\s*\)\s*,?")
FILTER_CLASS_RE = re.compile(r"\bclass\s+(?P<name>\w+)\b[^{;]*\bIDashboardAuthorizationFilter\b")
TYPE_DECL_RE = re.compile(r"\b(?:class|record|struct|interface|enum)\s+\w+")
NAMESPACE_RE = re.compile(r"(?m)^\s*namespace\s+(?P<ns>[\w.]+)")
# The starter template's filter body: a hard-coded username compared against the unvalidated token.
TEMPLATE_BODY_RE = re.compile(r"GetUsernameFromJwtToken\(\)[^;]*==\s*\"admin\"")


class _Call:
    def __init__(self, path: Path, text: str, m: re.Match, close: int | None):
        self.path, self.text, self.m, self.close = path, text, m, close
        args = ARGS_RE.match(text[m.end("paren"):close]) if close else None
        self.recognised = args is not None
        self.dashboard_path = (args.group("path") if args else None) or DEFAULT_PATH
        raw = (args.group("filters") or "") if args else ""
        self.filters = [f.group("name") for f in FILTER_RE.finditer(raw)]
        if args and FILTER_RE.sub("", raw).strip():
            self.recognised = False           # something other than `new X()` in the filter array

    def replacement(self) -> str:
        arg = "" if self.dashboard_path == DEFAULT_PATH else f'"{self.dashboard_path}"'
        return f".{EXTENSION}({arg})"


@register
class HangfireDashboard(Check):
    id = "hangfire-dashboard"
    title = "Hangfire dashboard uses the framework's validated Pages.Hangfire check"
    severity = "high"
    doc = "references/checks.md section 4"
    # shared determinism contract (check-registry.md A10)
    canonical_id = "A10"
    impact_class = "auth_bypass"
    reachability = "anonymous"
    data_sensitivity = "none"
    root_cause = "RC-sec-starter-surface"
    deterministic = True            # the call's PRESENCE is DET; "is it guarded?" judgement is flagged ND
    plan_id = "PLAN-hangfire-use-framework-dashboard"
    regression_test = "scripts/test_checks.py::HangfireDashboardTests"
    decision_input = "every .UseHangfireDashboard(...) call and the IDashboardAuthorizationFilter classes declared in the repo"
    decision_predicate = "template/framework filter reading an unvalidated token -> FAIL; custom/unknown filter or extra options -> MANUAL; no filter -> WARN"
    decision_verdict = "FAIL = a hand-made unsigned 'admin' token opens the dashboard (trigger/delete jobs, read args)"
    anchor_strategy = "call: <path>#<Type>.UseHangfireDashboard; filter: <path>#<FilterClass> (never a line number)"

    # ---- framework support
    @staticmethod
    def extension_available(repo: Repo) -> bool | None:
        """True/False from the restored Shesha.Scheduler assembly; None if it is not restored.

        There is no version-table fallback yet: no released version ships the extension. Once #5554
        is released, add its first versions here so un-restored repos can still be judged.
        """
        return repo.package_has_symbol("Shesha.Scheduler", "Shesha.Scheduler.dll", EXTENSION)

    def _blocked_reason(self, repo: Repo) -> str | None:
        has = self.extension_available(repo)
        version = repo.shesha_version() or "unknown"
        if has is True:
            return None
        if has is False:
            return (f"NOT APPLIED: Shesha {version} does not include {EXTENSION}() ({ISSUE}). "
                    "Upgrade Shesha to a version that includes it, then run this skill again")
        return (f"NOT APPLIED: could not confirm that Shesha {version} includes {EXTENSION}() because "
                "the Shesha.Scheduler package is not restored. Run `dotnet restore`, then run this skill again")

    # ---- discovery
    def _calls(self, repo: Repo) -> list[_Call]:
        calls = []
        for path, text, m in repo.grep(CALL_RE):
            calls.append(_Call(path, text, m, matching_brace(text, m.start("paren"))))
        return calls

    def _app_filters(self, repo: Repo) -> dict[str, tuple[Path, str]]:
        """Simple name -> (file, text) of every IDashboardAuthorizationFilter declared in the repo."""
        return {m.group("name"): (path, text) for path, text, m in repo.grep(FILTER_CLASS_RE)}

    def _classify(self, name: str, app_filters) -> str:
        simple = name.split(".")[-1]
        if name.startswith(FRAMEWORK_FILTER_NS + "."):
            return "framework"
        if simple in app_filters:
            _, text = app_filters[simple]
            return "template" if TEMPLATE_BODY_RE.search(text) else "custom"
        return "framework" if simple == "HangfireAuthorizationFilter" else "unknown"

    # ---- scan
    def scan(self, repo: Repo) -> Finding:
        calls = self._calls(repo)
        app_filters = self._app_filters(repo)
        blocked = self._blocked_reason(repo)
        issues, notes = [], []
        for call in calls:
            loc = repo.loc(call.path, call.text, call.m.start())
            anchor = member_anchor(repo.rel(call.path), enclosing_type(call.text, call.m.start()),
                                   "UseHangfireDashboard")
            if not call.recognised:
                issues.append(Issue(Status.MANUAL, "UseHangfireDashboard(...) has options or a shape this check "
                                    f"does not rewrite; switch it to {EXTENSION}() by hand", loc,
                                    anchor=anchor, evidence=Evidence.CODE_ONLY, non_deterministic=True))
                continue
            kinds = {n: self._classify(n, app_filters) for n in call.filters}
            if any(k in ("custom", "unknown") for k in kinds.values()):
                names = ", ".join(n for n, k in kinds.items() if k in ("custom", "unknown"))
                issues.append(Issue(Status.MANUAL, f"dashboard uses custom filter(s) {names}; check that "
                                    f"Pages.Hangfire covers their rules, then switch to {EXTENSION}() by hand", loc,
                                    anchor=anchor, evidence=Evidence.CODE_ONLY, non_deterministic=True))
                continue
            if not call.filters:
                status, msg = Status.WARN, ("dashboard has no permission check (Hangfire default: local "
                                            "requests only)")
            elif "template" in kinds.values():
                status, msg = Status.FAIL, ("dashboard uses the app-level filter that trusts an unvalidated "
                                            "token claiming to be \"admin\"")
            else:
                status, msg = Status.FAIL, ("dashboard filter checks Pages.Hangfire for a user read from an "
                                            "unvalidated token")
            if blocked:
                msg += " (not auto-fixed yet: see note)"
            issues.append(Issue(status, msg, loc, fixable=blocked is None, anchor=anchor,
                                evidence=Evidence.CODE_ONLY))

        # A leftover template filter nobody uses any more (e.g. the call was switched by hand).
        for name, (path, text) in app_filters.items():
            if self._classify(name, app_filters) == "template" and self._deletable(repo, name, path, {}):
                issues.append(Issue(Status.WARN, f"unused app-level filter {name} is still in the repository",
                                    repo.loc(path, text, text.find(name)), fixable=True,
                                    anchor=type_anchor(repo.rel(path), name), evidence=Evidence.VERIFIED_ARTEFACT))

        if blocked and calls:
            notes.append(blocked)
        if not calls:
            uses_ext = any(EXTENSION in repo.read(p) for p in repo.cs_files())
            pass_summary = (f"dashboard is mapped with {EXTENSION}()" if uses_ext
                            else "no Hangfire dashboard is mapped")
        else:
            pass_summary = f"dashboard is mapped with {EXTENSION}()"
        finding = Finding.from_issues(self.id, issues, pass_summary, notes)
        if blocked and calls:
            finding.blocked = ("needs a Shesha version with UseSheshaHangfireDashboard(); upgrade, then re-run"
                               if self.extension_available(repo) is False
                               else "Shesha.Scheduler package not restored; run `dotnet restore`, then re-run")
        return finding

    # ---- fix
    def fix(self, repo: Repo, finding: Finding) -> list[Edit]:
        blocked = self._blocked_reason(repo)
        app_filters = self._app_filters(repo)
        new_texts: dict[Path, str] = {}

        if not blocked:
            by_file: dict[Path, list[_Call]] = {}
            for call in self._calls(repo):
                if not call.recognised:
                    continue
                kinds = [self._classify(n, app_filters) for n in call.filters]
                if any(k in ("custom", "unknown") for k in kinds):
                    continue
                by_file.setdefault(call.path, []).append(call)
            for path, calls in by_file.items():
                text = repo.read(path)
                for call in sorted(calls, key=lambda c: c.m.start(), reverse=True):
                    text = text[:call.m.start()] + call.replacement() + text[call.close + 1:]
                new_texts[path] = ensure_using(text, EXTENSION_NS)

        edits: list[Edit] = []
        deleted_ns: set[str] = set()
        for name, (path, text) in app_filters.items():
            # Only the template filter is deleted, and only once nothing (after the rewrite) uses it.
            if self._classify(name, app_filters) == "template" and self._deletable(repo, name, path, new_texts):
                edits.append(Edit(path, None, f"delete app-level Hangfire filter {name}"))
                ns = NAMESPACE_RE.search(text)
                if ns:
                    deleted_ns.add(ns.group("ns"))

        # Drop `using <filter namespace>;` where nothing else declares that namespace any more.
        deleted_paths = {e.path.resolve() for e in edits}
        for ns in deleted_ns:
            still_declared = any(p.resolve() not in deleted_paths and re.search(
                rf"(?m)^\s*namespace\s+{re.escape(ns)}\s*[;{{\r\n]", repo.read(p)) for p in repo.cs_files())
            if still_declared:
                continue
            using_re = re.compile(rf"(?m)^[ \t]*using\s+{re.escape(ns)}\s*;[^\n]*\n")
            for p in repo.cs_files():
                if p.resolve() in deleted_paths:
                    continue
                current = new_texts.get(p, repo.read(p))
                if using_re.search(current):
                    new_texts[p] = using_re.sub("", current)

        edits = [Edit(p, t, f"map the dashboard with {EXTENSION}()" if CALL_RE.search(repo.read(p))
                      else "remove using of the deleted filter's namespace")
                 for p, t in new_texts.items() if t != repo.read(p)] + edits
        if not edits:
            raise NotFixable(blocked or "no dashboard call in a shape this check can rewrite")
        return edits

    def _deletable(self, repo: Repo, name: str, path: Path, new_texts: dict[Path, str]) -> bool:
        """The filter's file holds only this type and nothing else references it (after new_texts)."""
        text = repo.read(path)
        if len(TYPE_DECL_RE.findall(text)) != 1:
            return False
        ref = re.compile(rf"\b{re.escape(name)}\b")
        return not any(ref.search(new_texts.get(p, repo.read(p)))
                       for p in repo.cs_files() if p.resolve() != path.resolve())
