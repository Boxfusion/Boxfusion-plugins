"""Run the audit pipeline in the right order, with derived paths and freshness checks.

    # phase 1 - collect, scan, probe, catalogue, then stop at the review gate
    python run_audit.py --repo-root . [--url ...] [--lowpriv-user u --lowpriv-password p]

    # phase 2 - after review decisions are in catalog/review-overrides.json
    python run_audit.py --repo-root . --phase 2 --run-dir security-audits/YYMMDD-HHMM

Nine scripts have to run in a specific order, several of them reading files the previous one
wrote, and one path (`coded-endpoints.txt`) has to be handed from one to the next. Doing that
by hand worked, but only just: the first run of this skill nearly ran crossref.py before
scan_frontend.py, which would have reported everything the coded front-end calls as unused.

This encodes the graph. It does not make any security judgement, and it deliberately stops
before the report is written - that half is prose and belongs to the person or model doing the
review, not to a script.
"""

import argparse
import glob
import io
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from shesha_audit import cache_dir, get_json, latest_run_dir, new_run_dir  # noqa: E402

PY = sys.executable or "python"

# Source trees whose modification time makes a scan stale.
SOURCE_GLOBS = {
    "backend": ["backend/src/**/*.cs"],
    "frontend": ["*/src/**/*.ts", "*/src/**/*.tsx", "*/packages/**/src/**/*.ts",
                 "*/packages/**/src/**/*.tsx"],
}


class Step(object):
    def __init__(self, name, script, produces, requires=(), sources=(), needs_backend=False,
                 needs_lowpriv=False, phase=1, extra=None, always=False, optional=False):
        self.name = name
        self.script = script
        self.produces = list(produces)
        self.requires = list(requires)
        self.sources = list(sources)
        self.needs_backend = needs_backend
        self.needs_lowpriv = needs_lowpriv
        self.phase = phase
        self.extra = extra or (lambda a, ctx: [])
        self.always = always
        self.optional = optional


def newest(paths):
    stamps = [os.path.getmtime(p) for p in paths if os.path.isfile(p)]
    return max(stamps) if stamps else 0


def oldest(paths):
    stamps = [os.path.getmtime(p) for p in paths if os.path.isfile(p)]
    return min(stamps) if stamps else 0


def source_mtime(repo_root, keys):
    newest_stamp = 0
    for key in keys:
        for pattern in SOURCE_GLOBS.get(key, []):
            for path in glob.iglob(os.path.join(repo_root, pattern), recursive=True):
                p = path.replace("\\", "/")
                if "/obj/" in p or "/bin/" in p or "/node_modules/" in p:
                    continue
                try:
                    newest_stamp = max(newest_stamp, os.path.getmtime(path))
                except OSError:
                    continue
    return newest_stamp


def decide(step, ctx, force, max_age_minutes):
    """(run?, reason). Reasons are printed, because a silently skipped step is a wrong audit."""
    produced = [os.path.join(ctx["cache"], p) if not os.path.isabs(p) else p
                for p in step.produces]
    required = [os.path.join(ctx["cache"], r) if not os.path.isabs(r) else r
                for r in step.requires]

    if force:
        return True, "forced"
    if step.always:
        return True, "always runs"
    missing_out = [os.path.basename(p) for p in produced if not os.path.isfile(p)]
    if missing_out:
        return True, "output missing: %s" % ", ".join(missing_out)
    missing_in = [os.path.basename(r) for r in required if not os.path.isfile(r)]
    if missing_in:
        return False, "BLOCKED - input missing: %s" % ", ".join(missing_in)
    out_stamp = oldest(produced)
    if required and newest(required) > out_stamp:
        return True, "an input is newer than the output"
    if step.sources:
        src = source_mtime(ctx["repo_root"], step.sources)
        if src > out_stamp:
            return True, "source changed since the last scan"
    if max_age_minutes is not None:
        age = (time.time() - out_stamp) / 60.0
        if age > max_age_minutes:
            return True, "output is %.0f minutes old (limit %d)" % (age, max_age_minutes)
    return False, "up to date"


def read_json_quiet(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def build_steps():
    def collect_extra(a, ctx):
        args = ["--url", a.url, "--user", a.user, "--password", a.password]
        if a.refresh:
            args.append("--refresh")
        if a.skip_entity_permissions:
            args.append("--skip-entity-permissions")
        return args

    def crossref_extra(a, ctx):
        return ["--url", a.url,
                "--coded-endpoints", os.path.join(ctx["cache"], "coded-endpoints.txt")]

    def package_sources_extra(a, ctx):
        args = ["--url", a.url]
        for spec in (a.package_source or []):
            args += ["--package-source", spec]
        if a.no_package_source:
            args.append("--no-package-source")
        return args

    def lowpriv_extra(a, ctx):
        args = ["--url", a.url, "--user", a.user, "--password", a.password]
        if a.lowpriv_user:
            args += ["--lowpriv-user", a.lowpriv_user,
                     "--lowpriv-password", a.lowpriv_password or ""]
        return args

    def posture_extra(a, ctx):
        args = ["--url", a.url, "--user", a.user, "--password", a.password]
        if a.skip_deps:
            args.append("--skip-deps")
        if a.posture_only:
            args += ["--only", a.posture_only]
        return args

    def catalog_extra(a, ctx):
        args = ["--url", a.url, "--run-dir", ctx["run_dir"], "--scope", a.scope]
        for pkg in (a.packages or []):
            args += ["--packages", pkg]
        return args

    return [
        Step("collect", "collect.py", ["collection-report.json"],
             needs_backend=True, extra=collect_extra),
        Step("source-scan", "source_scan.py", ["source_scan.json"],
             sources=["backend"], extra=lambda a, ctx: ["--url", a.url]),
        Step("form-scan", "analyze_forms.py", ["form_analysis.json"],
             requires=["forms.json", "ownership.json"],
             extra=lambda a, ctx: ["--url", a.url]),
        Step("frontend-scan", "scan_frontend.py",
             ["frontend_scan.json", "coded-endpoints.txt"],
             sources=["frontend"], extra=lambda a, ctx: ["--url", a.url]),
        # Endpoints the framework's and Enterprise's own pages call. Runs with or without
        # source: without it, it records which imported packages went unscanned, and the
        # catalogue caps their unreferenced rows at REVIEW and lists them as missing inputs.
        # always=True: its coverage record must describe *this* run's choice of sources, so a
        # stale file can never claim a package was scanned when it was not.
        Step("package-sources", "scan_package_sources.py", ["package_source_refs.json"],
             always=True, optional=True, extra=package_sources_extra),
        Step("crossref", "crossref.py", ["crossref.json"],
             requires=["swagger.json", "form_analysis.json", "coded-endpoints.txt",
                       "package_source_refs.json"],
             extra=crossref_extra),
        Step("probe", "probe.py", ["probe-results.json"],
             requires=["swagger.json"], needs_backend=True, extra=lowpriv_extra),
        Step("object-auth", "object_auth.py", ["object-auth.json"],
             requires=["entityconfigs.json"], needs_backend=True, needs_lowpriv=True,
             optional=True, extra=lowpriv_extra),
        Step("posture", "posture_scan.py", ["posture.json"],
             needs_backend=True, extra=posture_extra),
        Step("catalogue", "build_catalogs.py",
             [os.path.join("@run", "catalog", "_index.json")],
             requires=["crossref.json", "source_scan.json"],
             always=True, extra=catalog_extra),
        # Extend the matrix from this catalogue - the app's own surface plus the
        # framework-entity CRUD sweep - then probe again and rebuild so the verdicts land.
        # Skipping this left built-in identity and bank-account entities unprobed on a first
        # audit; an anonymous user-account list was only found by the re-audit.
        Step("extend-matrix", "extend_probe_matrix.py", [],
             always=True, extra=lambda a, ctx: ["--run-dir", ctx["run_dir"], "--prune"]),
        Step("probe-extended", "probe.py", ["probe-results.json"],
             requires=["swagger.json"], needs_backend=True, always=True,
             extra=lowpriv_extra),
        Step("catalogue-extended", "build_catalogs.py",
             [os.path.join("@run", "catalog", "_index.json")],
             always=True, extra=catalog_extra),
        # phase 2
        Step("catalogue-with-overrides", "build_catalogs.py",
             [os.path.join("@run", "catalog", "_index.json")],
             always=True, phase=2, extra=catalog_extra),
        Step("findings", "findings.py", [os.path.join("@run", "findings.json")],
             always=True, phase=2,
             extra=lambda a, ctx: ["--run-dir", ctx["run_dir"]]),
        Step("verify", "verify_run.py", [], always=True, phase=2,
             extra=lambda a, ctx: ["--run-dir", ctx["run_dir"], "--url", a.url]),
        # Last, and only once verify passes: the workbook is what reviewers are handed.
        Step("workbook", "export_workbook.py", [], always=True, phase=2,
             extra=lambda a, ctx: ["--run-dir", ctx["run_dir"]]),
    ]


def resolve(paths, ctx):
    out = []
    for p in paths:
        if p.startswith("@run"):
            out.append(os.path.join(ctx["run_dir"], *p.split(os.sep)[1:]))
        else:
            out.append(os.path.join(ctx["cache"], p))
    return out


def run_step(step, args, ctx, dry_run):
    cmd = [PY, os.path.join(HERE, step.script), "--repo-root", args.repo_root]
    cmd += step.extra(args, ctx)
    printable = " ".join(os.path.basename(c) if c.endswith(".py") else c for c in cmd[1:])
    print("    $ %s" % printable)
    if dry_run:
        return 0, 0.0
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=args.repo_root)
    return proc.returncode, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--url", default="http://localhost:21021")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="123qwe")
    ap.add_argument("--lowpriv-user", default=None)
    ap.add_argument("--lowpriv-password", default=None)
    ap.add_argument("--run-dir", default=None,
                    help="reuse an existing run directory (required for --phase 2)")
    ap.add_argument("--phase", type=int, choices=(1, 2), default=1)
    ap.add_argument("--scope", choices=("all", "app"), default="all")
    ap.add_argument("--packages", action="append")
    ap.add_argument("--refresh", action="store_true", help="refetch the live data")
    ap.add_argument("--force", action="store_true", help="re-run every step")
    ap.add_argument("--skip-deps", action="store_true")
    ap.add_argument("--skip-entity-permissions", action="store_true")
    ap.add_argument("--posture-only", default=None,
                    help="pass through to posture_scan.py --only, e.g. T,R,G")
    ap.add_argument("--only", action="append",
                    help="run only these steps by name; repeatable")
    ap.add_argument("--skip", action="append", help="skip these steps by name; repeatable")
    ap.add_argument("--max-age", type=int, default=None,
                    help="re-run any step whose output is older than this many minutes")
    ap.add_argument("--allow-offline", action="store_true",
                    help="continue with the backend down, skipping every live step. Each one "
                         "is recorded as skipped, never as passed")
    ap.add_argument("--package-source", action="append", metavar="NAME=PATH",
                    help="framework/Enterprise source tree whose own pages and code count as "
                         "callers, e.g. shesha-framework=C:/src/shesha-framework; repeatable. "
                         "Remembered in the cache for later runs")
    ap.add_argument("--no-package-source", action="store_true",
                    help="audit without framework/Enterprise source (forgets remembered trees). "
                         "Package-owned unreferenced rows are then capped at REVIEW")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo_root = os.path.abspath(args.repo_root)
    cache = cache_dir(args.repo_root, args.url)

    if args.phase == 2:
        run_dir = args.run_dir or latest_run_dir(args.repo_root)
        if not run_dir:
            print("No run directory for phase 2. Pass --run-dir.", file=sys.stderr)
            return 2
        overrides = os.path.join(run_dir, "catalog", "review-overrides.json")
        if not os.path.isfile(overrides):
            print("No %s - phase 1 has not completed." % overrides, file=sys.stderr)
            return 2
    else:
        run_dir = args.run_dir or new_run_dir(args.repo_root)

    ctx = {"repo_root": repo_root, "cache": cache, "run_dir": run_dir}
    print("repo      %s" % repo_root)
    print("backend   %s" % args.url)
    print("cache     %s" % cache)
    print("run dir   %s" % run_dir)
    print("phase     %d" % args.phase)

    backend_up = False
    status, _ = get_json(args.url.rstrip("/") +
                         "/api/TokenAuth/GetExternalAuthenticationProviders", timeout=10)
    backend_up = status != 0
    print("backend   %s" % ("responding" if backend_up else "NOT RESPONDING"))
    if not backend_up and args.phase == 1 and not args.allow_offline:
        print("\nThe backend is not answering. Start it (references/dev-servers.md) and "
              "re-run, or pass --allow-offline to run the source and form scans only.\n"
              "Note that --allow-offline means every live check is SKIPPED - and a skipped "
              "check is never a pass.", file=sys.stderr)
        return 2
    if not args.lowpriv_user:
        print("lowpriv   none supplied - object-level authorization CANNOT be tested, and "
              "every \"any logged-in user\" finding stays derived rather than observed")
    remembered = os.path.join(cache, "package_sources_config.json")
    if args.phase == 1 and (args.no_package_source or
                            (not args.package_source and not os.path.isfile(remembered))):
        print("pkg src   none - framework/Enterprise source will NOT be scanned. Endpoints only "
              "their own screens call will look unreferenced; the catalogue caps those at "
              "REVIEW and the report must say so. Supply --package-source NAME=PATH if the "
              "source is available.")

    steps = [s for s in build_steps() if s.phase == args.phase]
    if args.only:
        wanted = {n.strip() for n in args.only}
        steps = [s for s in steps if s.name in wanted]
    if args.skip:
        unwanted = {n.strip() for n in args.skip}
        steps = [s for s in steps if s.name not in unwanted]

    print("\n%d step(s) in phase %d\n" % (len(steps), args.phase))
    timings, skipped, failed = [], [], []

    for step in steps:
        produced = resolve(step.produces, ctx)
        required = resolve(step.requires, ctx)
        local = Step(step.name, step.script, produced, required, step.sources,
                     step.needs_backend, step.needs_lowpriv, step.phase, step.extra,
                     step.always, step.optional)
        # decide() joins relative names onto the cache; these are already absolute.
        run, reason = decide(local, dict(ctx, cache=""), args.force, args.max_age)

        print("  %-24s %s" % (step.name, reason))
        # Order matters here. A step that is already up to date does not need the backend,
        # so warning about the backend for it would be noise - and noise in a skip list is
        # how a real skip gets overlooked.
        if not run:
            if reason.startswith("BLOCKED"):
                print("      cannot run, and later steps depend on it")
                failed.append(step.name)
                if not step.optional:
                    break
            else:
                skipped.append((step.name, reason))
            continue
        if step.needs_backend and not backend_up:
            print("      SKIPPED - backend down, and this step needed to run. Record it as "
                  "SKIP in the report; it is not a pass.")
            skipped.append((step.name, "NOT RUN - backend down"))
            continue
        if step.needs_lowpriv and not args.lowpriv_user:
            print("      SKIPPED - needs a second, zero-permission account. Object-level "
                  "authorization is untested, and the report must say so.")
            skipped.append((step.name, "NOT RUN - no low-privilege account"))
            continue

        code, took = run_step(step, args, ctx, args.dry_run)
        timings.append((step.name, took))
        if code != 0:
            print("      FAILED with exit code %d" % code)
            failed.append(step.name)
            if step.optional:
                continue
            print("\nStopping: %s failed and later steps read what it writes."
                  % step.name, file=sys.stderr)
            break

    print("\n" + "=" * 72)
    if timings:
        print("timings (seconds)")
        for name, took in timings:
            print("  %-24s %6.1f" % (name, took))
        print("  %-24s %6.1f" % ("total", sum(t for _, t in timings)))
    if skipped:
        print("\nskipped")
        for name, why in skipped:
            print("  %-24s %s" % (name, why))
    if failed:
        print("\nFAILED: %s" % ", ".join(failed))

    coverage = (read_json_quiet(os.path.join(cache, "package_source_refs.json")) or {}).get(
        "coverage")
    if coverage is None:
        print("\nPACKAGE SOURCE: not scanned (package_source_refs.json missing). Every "
              "package-owned unreferenced row is capped at REVIEW.")
    elif coverage.get("frontendPackagesNotScanned"):
        print("\nPACKAGE SOURCE: not scanned for %s. Endpoints those packages' own screens "
              "call will read as unreferenced; their package-owned rows are capped at REVIEW, "
              "and the report must name them under what was not covered."
              % ", ".join(coverage["frontendPackagesNotScanned"]))

    if args.phase == 1 and not failed:
        print("\nPhase 1 complete. Next, the review pass - it is not optional, because the "
              "catalogue's severities and dispositions are heuristics until a human confirms "
              "them:\n"
              "  1. python %s/digest.py --run-dir %s\n"
              "  2. record decisions in %s/catalog/review-overrides.json\n"
              "  3. python %s/run_audit.py --repo-root %s --phase 2 --run-dir %s\n"
              "     (re-applies the overrides, rebuilds, indexes and verifies)\n"
              "  4. write {package}-recommendations.md per "
              "references/recommendations-format.md, then re-run phase 2 to verify them"
              % (os.path.relpath(HERE, repo_root), run_dir, run_dir,
                 os.path.relpath(HERE, repo_root), args.repo_root, run_dir))
    if args.phase == 2 and not failed and not args.dry_run:
        print("\nPhase 2 complete. Reviewer workbook: %s"
              % os.path.join(run_dir, "security-catalog-%s.xlsx"
                             % os.path.basename(os.path.normpath(run_dir))))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
