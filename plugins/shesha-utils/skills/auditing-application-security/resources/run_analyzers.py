"""Thin wrapper around the Roslyn SEC-A / SEC-H analyzer driver.

    python run_analyzers.py --repo-root . --out <run-dir>/analyzer-findings.json [--solution path.sln] [--commit <sha>]

determinism-standard.md §1 gates the Roslyn analyzer on the `buildable_backend` capability:
"dotnet build succeeds". This wrapper IS that gate.

  * Buildable  -> build the driver, build-probe the target solution, run the driver. The
                  driver emits a §8 findings.json fragment (VERIFIED-ARTEFACT SEC-A / SEC-H
                  records, or an empty array when the analyzer finds nothing).
  * NOT buildable (no dotnet, driver won't build, no solution, or the target won't build)
                  -> emit the two fixed `SEC-A@analyzer` / `SEC-H@analyzer`
                  `NOT-ASSESSED(no-build)` records.

It never returns a silent empty pass: the no-build path is a first-class verdict
(determinism-standard §1), byte-identical in shape to the driver's own internal fallback.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYZERS_DIR = os.path.join(HERE, "analyzers")
SLNX = os.path.join(ANALYZERS_DIR, "Boxfusion.SecAnalyzers.slnx")
DRIVER_DLL = os.path.join(
    ANALYZERS_DIR, "src", "Boxfusion.SecDriver", "bin", "Release", "net8.0",
    "Boxfusion.SecDriver.dll")

# MSBuild props that keep the design-time build off the private Shesha feed (mirrors the
# driver's own MSBuildWorkspace props), so the build-probe reflects "can the code compile".
BUILD_PROPS = [
    "-p:NuGetAudit=false", "-p:RunNuGetAudit=false",
    "-p:TreatWarningsAsErrors=false", "-p:RestorePackagesWithLockFile=false",
]


def _no_build_record(check_id, commit):
    return {
        "finding_id": check_id + "@analyzer",
        "check_id": check_id,
        "area": "security",
        "anchor": "analyzer",
        "evidence_level": "NOT-ASSESSED(no-build)",
        "execution_class": "roslyn-analyzer-scan",
        "severity": "Info",
        "severity_inputs": None,
        "plan_id": None,
        "root_cause": None,
        "fix_order_rank": None,
        "sources": [],
        "not_assessed_reason": "no-build",
        "non_deterministic": False,
        "commit_sha": commit,
    }


def write_no_build(out_path, commit, reason):
    """Emit the fixed NOT-ASSESSED(no-build) fragment — never a silent pass."""
    records = [_no_build_record("SEC-A", commit), _no_build_record("SEC-H", commit)]
    text = json.dumps(records, indent=2, ensure_ascii=False).replace("\r\n", "\n")
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text + "\n")
    print("NOT-ASSESSED(no-build): %s" % reason, file=sys.stderr)
    print("  wrote SEC-A@analyzer / SEC-H@analyzer to %s" % out_path, file=sys.stderr)


def discover_solution(repo_root):
    """First backend/**/*.sln, else any *.sln under the repo root. Deterministic order."""
    candidates = []
    for base in (os.path.join(repo_root, "backend"), repo_root):
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            p = dirpath.replace("\\", "/")
            if "/bin/" in p or "/obj/" in p or "/node_modules/" in p:
                continue
            for f in files:
                if f.endswith(".sln"):
                    candidates.append(os.path.join(dirpath, f))
        if candidates:
            break
    return sorted(candidates)[0] if candidates else None


def git_commit(repo_root):
    try:
        out = subprocess.run(["git", "-C", repo_root, "rev-parse", "HEAD"],
                             capture_output=True, text=True)
        if out.returncode == 0:
            return out.stdout.strip() or None
    except Exception:
        pass
    return None


def dotnet_build(target, cwd):
    """Return True iff `dotnet build <target>` exits 0."""
    cmd = ["dotnet", "build", target, "-c", "Release"] + BUILD_PROPS
    print("    $ %s" % " ".join(cmd), file=sys.stderr)
    proc = subprocess.run(cmd, cwd=cwd)
    return proc.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--solution", default=None,
                    help="target .sln; auto-discovered under backend/ when omitted")
    ap.add_argument("--out", required=True, help="findings.json fragment to write")
    ap.add_argument("--commit", default=None, help="commit sha (git HEAD when omitted)")
    ap.add_argument("--no-build-probe", action="store_true",
                    help="trust an existing restore/build of the target instead of building it")
    args = ap.parse_args()

    repo_root = os.path.abspath(args.repo_root)
    commit = args.commit or git_commit(repo_root)
    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    # 1. dotnet present?
    if shutil.which("dotnet") is None:
        write_no_build(out_path, commit, "dotnet CLI not found on PATH")
        return 0

    # 2. driver built (build it once if the dll is missing)?
    if not os.path.isfile(DRIVER_DLL):
        print("building the analyzer driver...", file=sys.stderr)
        if not dotnet_build(SLNX, ANALYZERS_DIR):
            write_no_build(out_path, commit, "analyzer driver failed to build")
            return 0

    # 3. target solution?
    solution = os.path.abspath(args.solution) if args.solution else discover_solution(repo_root)
    if not solution or not os.path.isfile(solution):
        write_no_build(out_path, commit, "no target .sln found under %s" % repo_root)
        return 0

    # 4. is the target buildable? (determinism-standard §1 buildable_backend probe)
    if not args.no_build_probe:
        print("build-probing the target solution...", file=sys.stderr)
        if not dotnet_build(solution, repo_root):
            write_no_build(out_path, commit, "target solution failed to build: %s" % solution)
            return 0

    # 5. run the driver -> it writes the §8 fragment itself (and has its own no-build
    #    fallback if MSBuildWorkspace still cannot open a Compilation).
    cmd = ["dotnet", DRIVER_DLL, "--solution", solution, "--repo-root", repo_root,
           "--out", out_path]
    if commit:
        cmd += ["--commit", commit]
    print("    $ %s" % " ".join(cmd), file=sys.stderr)
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        # The driver returns non-zero only on an argument error; its analysis failure path
        # already wrote the NOT-ASSESSED fallback. Guard anyway, never a silent pass.
        if not os.path.isfile(out_path):
            write_no_build(out_path, commit, "driver exited %d without output" % proc.returncode)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
