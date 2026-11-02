#!/usr/bin/env python3
"""Scan a Shesha application repository for security misconfigurations and (optionally) fix them.

  harden.py list
  harden.py scan [--repo DIR] [--only a,b] [--json FILE] [--base-url URL --username U]
  harden.py fix  [--repo DIR] [--only a,b] [--apply [--commit [--trailer T ...]]] [--set check.option=value ...]

Checks run one at a time, in order; each sees the changes made by the ones before it.
`fix` is a dry run unless --apply is given: it prints the diff it would write.
With --apply --commit, every check that changes code gets its own git commit holding only
that change (the user's other uncommitted work is left alone). Every run ends with a final
report: one row per check - gap found, current state, action taken.
Live checks need --base-url and --username, with the password in SHESHA_ADMIN_PASSWORD
(or --password). The live backend is only ever read, never written.
Exit code: 0 = nothing failed, 1 = at least one check failed, 2 = usage error.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import (Check, Edit, Finding, LiveBackend, NotFixable, Repo, Status, capability_manifest,  # noqa: E402
                  diff, load_checks)
from gitops import Git, GitError  # noqa: E402

ICON = {Status.PASS: "PASS", Status.WARN: "WARN", Status.FAIL: "FAIL", Status.MANUAL: "MANUAL",
        Status.SKIP: "SKIP", Status.NOT_APPLICABLE: "N/A"}


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["list", "scan", "fix"])
    p.add_argument("--repo", default=".", help="repository root (default: current directory)")
    p.add_argument("--only", help="comma-separated check ids (default: all)")
    p.add_argument("--json", help="also write the findings as JSON to this file")
    p.add_argument("--apply", action="store_true", help="fix: write the changes (default: dry run)")
    p.add_argument("--commit", action="store_true",
                   help="fix --apply: commit each check's change separately (needs a clean index, not on the default branch)")
    p.add_argument("--allow-default-branch", action="store_true", help="--commit: allow committing on main/master")
    p.add_argument("--trailer", action="append", default=[],
                   help="--commit: line appended to every commit message, e.g. a Co-Authored-By trailer")
    p.add_argument("--set", action="append", default=[], metavar="CHECK.OPTION=VALUE",
                   help="override a check option, e.g. token-lifetime.minutes=60")
    p.add_argument("--base-url", help="running backend for live checks, e.g. http://localhost:21021")
    p.add_argument("--username", help="admin user for live checks")
    p.add_argument("--password", help="DEPRECATED - use SHESHA_ADMIN_PASSWORD; a password on the "
                   "command line leaks into shell history and the process table")
    return p.parse_args(argv)


def build_checks(registry, only: str | None, sets: list[str]) -> list[Check]:
    overrides: dict[str, dict] = {}
    for item in sets:
        key, _, value = item.partition("=")
        check_id, _, opt = key.partition(".")
        if not opt or check_id not in registry:
            sys.exit(f"--set {item!r}: expected <check-id>.<option>=<value> with a known check id")
        default = registry[check_id].options.get(opt)
        if default is None:
            sys.exit(f"--set {item!r}: {check_id} has no option {opt!r} "
                     f"(options: {', '.join(registry[check_id].options) or 'none'})")
        typed = value.lower() in ("1", "true", "yes") if isinstance(default, bool) else type(default)(value)
        overrides.setdefault(check_id, {})[opt] = typed
    ids = [s.strip() for s in only.split(",")] if only else list(registry)
    unknown = [i for i in ids if i not in registry]
    if unknown:
        sys.exit(f"Unknown check id(s): {', '.join(unknown)}. Run `harden.py list`.")
    return [registry[i](overrides.get(i)) for i in ids]


def scan_one(repo: Repo, check: Check) -> Finding:
    ok, why = check.applies(repo)
    if not ok:
        return Finding(check.id, Status.NOT_APPLICABLE, why)
    try:
        return check.scan(repo)
    except Exception as exc:  # a broken check must not hide the others
        return Finding(check.id, Status.SKIP, f"check crashed: {exc!r}")


def run_scan(repo: Repo, checks: list[Check]) -> list[tuple[Check, Finding]]:
    return [(check, scan_one(repo, check)) for check in checks]


class Row:
    """One line of the final report."""

    def __init__(self, check: Check, before: Finding, after: Finding, action: str):
        self.check, self.before, self.after, self.action = check, before, after, action

    @property
    def gap(self) -> str:
        s = self.before.status
        if s in (Status.FAIL, Status.WARN, Status.MANUAL):
            return f"yes ({ICON[s]})"
        return {Status.PASS: "no", Status.NOT_APPLICABLE: "n/a", Status.SKIP: "not assessed"}[s]

    @property
    def state(self) -> str:
        s = self.after.status
        if s == Status.PASS:
            return "resolved" if self.before.status != Status.PASS else "OK"
        return f"{ICON[s]}: {short(self.after.summary)}"

    def to_dict(self) -> dict:
        return {"check": self.check.id, "gap": self.gap, "state": self.state, "action": self.action,
                "before": self.before.status.value, "after": self.after.status.value}


def short(text: str, limit: int = 90) -> str:
    text = text.split(" (not auto-fixed yet")[0]
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


def idle_action(check: Check, f: Finding, scan_only: bool) -> str:
    """Action text for a check whose fix did not run."""
    if f.status == Status.PASS:
        return "none needed"
    if f.status == Status.NOT_APPLICABLE:
        return "none (not applicable)"
    if f.status == Status.SKIP:
        return "none (could not assess)"
    if f.blocked:
        return f"not applied: {f.blocked}"
    if scan_only and f.fixable:
        return "none (scan only; auto-fixable)"
    return f"manual fix needed ({check.doc})"


def print_final_report(rows: list[Row], mode: str) -> None:
    print(f"\n==== Final report ({mode}) ====\n")
    print("| Check | Gap found | Current state | Action taken |")
    print("|---|---|---|---|")
    for r in rows:
        print(f"| `{r.check.id}` | {r.gap} | {r.state} | {r.action} |")
    print()


def commit_message(check: Check, edits: list[Edit], trailers: list[str]) -> str:
    body = "\n".join(f"- {e.description} ({e.path.name})" for e in edits)
    msg = (f"Harden {check.id}: {check.title}\n\n{body}\n\n"
           f"Applied by the hardening-shesha-app skill; see {check.doc}.\n")
    return msg + ("\n" + "\n".join(trailers) + "\n" if trailers else "")


def fix_one(repo: Repo, check: Check, finding: Finding, args, git: "Git | None") -> str:
    """Fix one check (dry run, apply, or apply + commit). Returns the report's action text."""
    try:
        edits = check.fix(repo, finding)
    except NotFixable as exc:
        print(f"[{check.id}] not auto-fixable: {exc}\n")
        return f"manual fix needed ({check.doc})"
    originals = {e.path.resolve(): repo.read(e.path) for e in edits}
    dirty = {}
    if git:
        for e in edits:
            code = git.status(e.path)
            if code:
                dirty[e.path.resolve()] = code
    for edit in edits:
        print(f"[{check.id}] {edit.description}")
        print(diff(repo, edit) or "  (no textual change)\n")
        repo.stage(edit)            # later checks see this change
        if args.apply:
            repo.write(edit)
    what = "; ".join(dict.fromkeys(e.description for e in edits))
    if not args.apply:
        return f"would fix (dry run): {what}"
    if not git:
        return f"fixed, not committed: {what}"
    sha, problems = git.commit_check(edits, originals, dirty, commit_message(check, edits, args.trailer))
    if sha:
        print(f"[{check.id}] committed {sha}\n")
        return f"fixed, committed {sha}: {what}"
    print(f"[{check.id}] NOT COMMITTED: {'; '.join(problems)}\n")
    return f"fixed in working tree, NOT committed ({'; '.join(problems)}): {what}"


def print_report(repo: Repo, results):
    print(f"Repository: {repo.root}")
    print(f"Shesha version: {repo.shesha_version() or 'unknown'}")
    print(f"Live backend: {repo.live.base_url if repo.live else 'not provided (live parts skipped)'}\n")
    for check, f in results:
        fix = "  [auto-fixable]" if f.fixable else ""
        print(f"[{ICON[f.status]:>6}] {check.id} ({check.severity}) - {f.summary}{fix}")
        for i in f.issues:
            where = f"  @ {i.location}" if i.location else ""
            print(f"         - {ICON[i.status]}: {i.message}{where}")
        for n in f.notes:
            print(f"         note: {n}")
        if f.status not in (Status.PASS, Status.NOT_APPLICABLE):
            print(f"         see: {check.doc}")
    counts = {}
    for _, f in results:
        counts[f.status] = counts.get(f.status, 0) + 1
    print("\nSummary: " + ", ".join(f"{ICON[s]} {n}" for s, n in sorted(counts.items(), key=lambda x: -x[0].rank)))


def main(argv=None) -> int:
    # Diffs echo source text (e.g. zero-width spaces); a cp1252 console must not crash mid-apply.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = parse_args(argv)
    registry = load_checks()

    if args.command == "list":
        for cid, cls in registry.items():
            opts = ", ".join(f"{k}={v}" for k, v in cls.options.items())
            print(f"{cid:<18} {cls.severity:<7} {cls.title}" + (f"  [options: {opts}]" if opts else ""))
        return 0

    live = None
    if args.base_url:
        if args.password:
            print("WARNING: --password is deprecated; put the password in SHESHA_ADMIN_PASSWORD instead "
                  "(it is reported only by presence and length, never echoed).", file=sys.stderr)
        password = os.environ.get("SHESHA_ADMIN_PASSWORD") or args.password
        if not (args.username and password):
            sys.exit("--base-url needs --username and a password in SHESHA_ADMIN_PASSWORD")
        live = LiveBackend(args.base_url, args.username, password)

    repo = Repo(Path(args.repo), live)
    checks = build_checks(registry, args.only, args.set)

    git = None
    if args.commit:
        if not (args.command == "fix" and args.apply):
            sys.exit("--commit needs `fix --apply`")
        try:
            git = Git(repo.root)
            git.preflight(args.allow_default_branch)
        except GitError as exc:
            sys.exit(f"--commit: {exc}")

    rows: list[Row] = []
    if args.command == "scan":
        mode = "scan only"
        for check, f in run_scan(repo, checks):
            rows.append(Row(check, f, f, idle_action(check, f, scan_only=True)))
    else:
        mode = "APPLY + COMMIT" if git else "APPLY" if args.apply else "DRY RUN (add --apply to write)"
        print(f"Mode: {mode}\n")
        for check in checks:                       # one at a time: scan, fix, (commit), re-scan
            before = scan_one(repo, check)
            if before.blocked:
                print(f"[{check.id}] WARNING - not applied: {before.blocked}\n")
            if before.fixable:
                action = fix_one(repo, check, before, args, git)
                after = scan_one(repo, check)
            else:
                action, after = idle_action(check, before, scan_only=False), before
            rows.append(Row(check, before, after, action))
        print("---- state after fixes" + ("" if args.apply else " (simulated)") + " ----\n")

    results = [(r.check, r.after) for r in rows]
    print_report(repo, results)
    print_final_report(rows, mode)
    if args.json:
        Path(args.json).write_text(json.dumps(
            build_findings_document(repo, mode, rows, results), indent=2), encoding="utf-8")
    return 1 if any(f.status == Status.FAIL for _, f in results) else 0


def _commit_sha(root: Path) -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except OSError:
        return None


def build_findings_document(repo: Repo, mode: str, rows, results) -> dict:
    """The findings.json. The shared-schema `findings` array is the diff surface (one row per
    anchor, determinism-standard §2-§6). Everything volatile - repo path, commit sha, run time,
    mode - lives in `runMeta`, which the normalizer strips so two runs converge byte-for-byte.
    `report` and `checks` are kept for backward compatibility."""
    findings = []
    for check, f in results:
        findings += f.shared_findings(check)
    return {
        "schema": "hardening-shesha-app/findings@1",
        "runMeta": {                                  # NOT in the diff (stripped by normalize_findings.py)
            "repo": str(repo.root),
            "sheshaVersion": repo.shesha_version(),
            "mode": mode,
            "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "commit": _commit_sha(repo.root),
        },
        "capabilities": capability_manifest(repo),    # §1 manifest; absent -> NOT-ASSESSED(reason)
        "report": [r.to_dict() for r in rows],        # back-compat: the final-report table rows
        "checks": [f.to_dict() for _, f in results],  # back-compat: the old detailed per-check findings
        "findings": findings,                         # the shared diff surface
    }


if __name__ == "__main__":
    sys.exit(main())
