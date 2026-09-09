"""Resolve a compatible Shesha stack from a single target Shesha version.

Given a target Shesha version, works out which version of every other Shesha /
Boxfusion module the project uses, by reading each candidate build's .nuspec off
the private Azure Artifacts feed and checking which Shesha version it was
actually built against.

Discovers everything from the project itself -- no hardcoded package lists:
  * MSBuild version properties from Directory.Build.props
  * which packages each property versions, from the .csproj files IN THE .sln
  * matching @shesha-io/* npm packages from the frontend package.json files

Usage:
    python resolve_versions.py --repo <repo-root> --target 0.43.37
    python resolve_versions.py --repo . --target 0.43.37 --json plan.json

Requires SHESHA_FEED_PAT (Azure DevOps PAT, Packaging:Read).
"""
import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ORG = "boxfusion"
NUGET_FEED = "nuget.shesha.dev"
NPM_FEED = "npm.shesha.dev"
FEEDS_API = f"https://feeds.dev.azure.com/{ORG}/_apis/packaging/feeds/{NUGET_FEED}"
FLAT2 = f"https://pkgs.dev.azure.com/{ORG}/_packaging/{NUGET_FEED}/nuget/v3/flat2"
NPM_REGISTRY = f"https://pkgs.dev.azure.com/{ORG}/_packaging/{NPM_FEED}/npm/registry"

# Packages whose version defines "the Shesha version" itself. FluentMigrator
# tracks this line too and is the ONLY core dependency some modules declare
# (e.g. Shesha.Enterprise.DocumentProcessing), so omitting it loses the signal.
SHESHA_CORE_IDS = {"shesha.framework", "shesha.core", "shesha.application",
                   "shesha.nhibernate", "shesha.fluentmigrator"}
# Suffixes stripped from a NuGet id to get the module slug used by npm.
NUGET_SUFFIXES = (".domain.service", ".application", ".domain", ".core", ".framework")
# The npm package fed by the Shesha core version has a name that does not
# derive from any NuGet id: Shesha.Framework et al. -> @shesha-io/reactjs.
CORE_NPM_SLUGS = ("reactjs",)


def auth_header():
    pat = os.environ.get("SHESHA_FEED_PAT", "")
    if not pat or pat.startswith("REPLACE_ME"):
        sys.exit("ERROR: SHESHA_FEED_PAT is unset or still the placeholder.\n"
                 "Add a PAT with Packaging:Read scope to the env block of "
                 "~/.claude/settings.json, then start a new session.\n"
                 "Do NOT fall back to nuget.org: the public feed carries some of "
                 "these package names under a different version series and will "
                 "return confidently wrong versions.")
    return "Basic " + base64.b64encode(f":{pat}".encode()).decode()


AUTH = None


def fetch(url, as_json=True):
    req = urllib.request.Request(url, headers={"Authorization": AUTH})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    return json.loads(raw) if as_json else raw.decode("utf-8", "replace")


def vkey(v):
    """Numeric-aware sort key. Releases sort above prereleases of equal number."""
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?(?:-(.*))?$", v or "")
    if not m:
        return (-1, 0, 0, 0, 0, v or "")
    maj, mi, pa, rev, pre = m.groups()
    return (int(maj), int(mi), int(pa), int(rev or 0), 0 if pre else 1, pre or "")


def is_release(v):
    """Reject prereleases and CI build-number versions (0.0.0-buildNNN, 0.0.64973-build)."""
    return "-" not in v and not v.startswith("0.0.")


# --------------------------------------------------------------------------- #
# Project discovery
# --------------------------------------------------------------------------- #

def find_backend(repo):
    for cand in ("backend", "."):
        d = os.path.join(repo, cand) if cand != "." else repo
        if os.path.isfile(os.path.join(d, "Directory.Build.props")):
            return d
    sys.exit(f"ERROR: no Directory.Build.props found under {repo}")


def read_props(backend):
    """Return {propertyName: value} for every property in Directory.Build.props.

    Deliberately matches ANY property name, not just names ending in 'Version':
    real projects contain typos such as <ContentManagementVerison>, and the
    authoritative list of version properties comes from what the .csproj files
    actually reference via $(...), not from the naming convention.
    """
    text = open(os.path.join(backend, "Directory.Build.props"), encoding="utf-8-sig").read()
    return {m.group(1): m.group(2).strip()
            for m in re.finditer(r"<([A-Za-z_][\w.-]*)>([^<>]+)</\1>", text)}


def sln_projects(backend):
    """Absolute paths of every .csproj referenced by the solution.

    Projects NOT in the .sln are deliberately ignored -- a repo can contain
    stray/backup .csproj files that reference obsolete versions.
    """
    slns = [f for f in os.listdir(backend) if f.endswith(".sln")]
    if not slns:
        sys.exit(f"ERROR: no .sln in {backend}")
    out, sln = [], os.path.join(backend, slns[0])
    for m in re.finditer(r'"([^"]+\.csproj)"', open(sln, encoding="utf-8-sig").read()):
        p = os.path.normpath(os.path.join(backend, m.group(1).replace("\\", os.sep)))
        if os.path.isfile(p):
            out.append(p)
    return sln, out


def scan_packages(csprojs):
    """Return (property -> {package ids}, [hardcoded Shesha/Boxfusion refs])."""
    by_prop, hardcoded = {}, []
    for p in csprojs:
        text = open(p, encoding="utf-8-sig").read()
        for pid, ver in re.findall(
                r'<PackageReference\s+(?:Include|Update)="([^"]+)"\s+Version="([^"]+)"', text):
            if not re.match(r"^(shesha|boxfusion)\.", pid, re.I):
                continue
            m = re.match(r"^\$\((\w+)\)$", ver)
            if m:
                by_prop.setdefault(m.group(1), set()).add(pid)
            else:
                hardcoded.append((os.path.basename(p), pid, ver))
    return by_prop, hardcoded


SKIP_DIRS = {"node_modules", ".next", "dist", "build", "obj", "bin", ".git", ".vs"}


def find_frontend_manifests(repo):
    """Every package.json in the repo that references an @shesha-io package.

    Walks the filesystem directly rather than using a gitignore-aware glob:
    frontend folders are often gitignored, which makes such a glob silently
    return nothing. Does not assume a folder name -- a project may have
    adminportal, publicportal, or several of each, with nested workspaces.
    """
    found = []
    for base, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if "package.json" not in files:
            continue
        p = os.path.join(base, "package.json")
        try:
            if "@shesha-io/" in open(p, encoding="utf-8").read():
                found.append(p)
        except (OSError, UnicodeDecodeError):
            continue
    return found


def scan_npm(manifests):
    """Return [(manifest, section, npm package, current version)] for @shesha-io/* deps.

    Covers dependencies, devDependencies, peerDependencies AND the overrides
    block -- nested pins inside overrides are invisible to anything that only
    walks the dependency sections, and leaving one behind silently pins a
    transitive copy of the old version.

    Excludes any package that is itself one of this repo's workspace packages:
    a workspace package's own version is release metadata owned by the build
    pipeline, and a sibling workspace dependency is local, not from the feed.
    """
    local = set()
    for mf in manifests:
        try:
            local.add(json.load(open(mf, encoding="utf-8")).get("name", ""))
        except (OSError, ValueError):
            continue
    local.discard("")

    rows = []
    for mf in manifests:
        d = json.load(open(mf, encoding="utf-8"))
        def add(section, k, v):
            if k.startswith("@shesha-io/") and k not in local:
                rows.append((mf, section, k, v))
        for sect in ("dependencies", "devDependencies", "peerDependencies"):
            for k, v in (d.get(sect) or {}).items():
                add(sect, k, v)
        for outer, inner in (d.get("overrides") or {}).items():
            if isinstance(inner, dict):
                for k, v in inner.items():
                    add(f"overrides[{outer}]", k, v)
            else:
                add("overrides", outer, inner)
    return rows


# --------------------------------------------------------------------------- #
# Feed queries
# --------------------------------------------------------------------------- #

def nuget_versions(pkg):
    url = (f"{FEEDS_API}/packages?packageNameQuery={urllib.parse.quote(pkg)}"
           f"&includeAllVersions=true&api-version=7.1-preview.1")
    for p in fetch(url).get("value", []):
        if p["normalizedName"].lower() == pkg.lower():
            return sorted([v["normalizedVersion"] for v in p["versions"] if v.get("isListed")],
                          key=vkey, reverse=True)
    return []


def shesha_floor(pkg, ver):
    """The Shesha version this build was compiled against, per its .nuspec.

    NuGet dependency versions are floors (>=), not pins -- so this is 'built
    against', not 'requires exactly'.
    """
    try:
        xml = fetch(f"{FLAT2}/{pkg.lower()}/{ver.lower()}/{pkg.lower()}.nuspec", as_json=False)
    except urllib.error.HTTPError as e:
        return None
    deps = dict(re.findall(r'<dependency id="([^"]+)" version="\[?([^",\]]+)', xml))
    core = [v for k, v in deps.items() if k.lower() in SHESHA_CORE_IDS]
    return sorted(core, key=vkey)[-1] if core else None


def npm_meta(pkg):
    try:
        return fetch(f"{NPM_REGISTRY}/{urllib.parse.quote(pkg, safe='')}")
    except urllib.error.HTTPError:
        return None


def npm_has(pkg, ver, meta=None):
    d = meta if meta is not None else npm_meta(pkg)
    if d is None:
        return None
    return ver in d.get("versions", {})


def npm_resolve(pkg, target, depth=8):
    """Resolve a frontend-only @shesha-io package with no backend counterpart.

    Same idea as the .nuspec check, on the npm side: find the newest release
    whose own @shesha-io/reactjs dependency matches the target Shesha version.
    """
    d = npm_meta(pkg)
    if d is None:
        return None, "npm lookup failed"
    vers = sorted([v for v in d.get("versions", {}) if is_release(v)], key=vkey, reverse=True)
    fallback = None
    for v in vers[:depth]:
        m = d["versions"][v]
        dep = None
        for sect in ("dependencies", "peerDependencies", "devDependencies"):
            got = (m.get(sect) or {}).get("@shesha-io/reactjs")
            if got:
                dep = got.lstrip("^~>=< ")
                break
        if not dep:
            continue
        if vkey(dep) > vkey(target):
            continue
        if dep == target:
            return v, "exact"
        if fallback is None:
            fallback = v
    if fallback:
        return fallback, "compat"
    return None, "no release pairs with the target"


def slug(pid):
    s = pid.lower()
    for pre in ("shesha.", "boxfusion."):
        if s.startswith(pre):
            s = s[len(pre):]
            break
    for suf in NUGET_SUFFIXES:
        if s.endswith(suf):
            s = s[:-len(suf)]
            break
    return s.replace(".", "")


def resolve_property(pkgs, target, depth):
    """Pick one version for a property group, given a target Shesha version.

    All packages sharing a property must move together, so the chosen version
    must be published by every one of them. Among those, prefer the newest
    where some package was built against the target exactly, and reject any
    where a package requires something newer than the target.

    A package that declares no Shesha core dependency at all has no opinion
    about compatibility -- it must publish the chosen version, but it must not
    veto a version the rest of the group agrees on.
    """
    published, floors, notes = {}, {}, []
    for pkg in sorted(pkgs):
        vers = [v for v in nuget_versions(pkg) if is_release(v)]
        if not vers:
            notes.append(f"{pkg}: no release versions on feed")
            return None, "unresolved", notes
        published[pkg] = set(vers)
        for v in vers[:depth]:
            floors[(pkg, v)] = shesha_floor(pkg, v)

    common = sorted(set.intersection(*published.values()), key=vkey, reverse=True)
    if not common:
        notes.append("no single version is published by every package in this group")
        return None, "unresolved", notes

    fallback = None
    for v in common[:depth]:
        opinions = [floors[(p, v)] for p in pkgs if floors.get((p, v))]
        if not opinions:
            continue
        if any(vkey(f) > vkey(target) for f in opinions):
            continue                       # needs a newer Shesha than the target
        if target in opinions:
            return v, "exact", notes
        if fallback is None:
            fallback = v
    if fallback:
        notes.append("no build declares the target Shesha version exactly; using "
                     "the newest build with a lower floor -- confirm at build time")
        return fallback, "compat", notes
    notes.append("every recent build requires a newer Shesha than the target")
    return None, "unresolved", notes


def main():
    global AUTH
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--target", required=True, help="target Shesha version, e.g. 0.43.37")
    ap.add_argument("--depth", type=int, default=8, help="candidate builds to inspect per package")
    ap.add_argument("--json", help="write the plan to this file")
    a = ap.parse_args()
    AUTH = auth_header()

    repo = os.path.abspath(a.repo)
    backend = find_backend(repo)
    props = read_props(backend)
    sln, csprojs = sln_projects(backend)
    by_prop, hardcoded = scan_packages(csprojs)

    print(f"repo     : {repo}")
    print(f"solution : {os.path.basename(sln)} ({len(csprojs)} projects)")
    print(f"target   : Shesha {a.target}\n")

    plan, slug_to_version = {}, {}
    for prop in sorted(by_prop):
        pkgs = by_prop[prop]
        is_core = bool({p.lower() for p in pkgs} & SHESHA_CORE_IDS)
        if is_core:
            chosen, kind, notes = a.target, "target", []
        else:
            chosen, kind, notes = resolve_property(pkgs, a.target, a.depth)
        plan[prop] = {"current": props.get(prop), "resolved": chosen, "basis": kind,
                      "packages": sorted(pkgs), "notes": notes}
        for p in pkgs:
            if chosen:
                slug_to_version[slug(p)] = chosen
        if is_core and chosen:
            for s in CORE_NPM_SLUGS:
                slug_to_version[s] = chosen
        cur = props.get(prop, "?")
        arrow = "unchanged" if chosen == cur else f"{cur} -> {chosen}"
        print(f"  {prop:28s} {arrow:24s} [{kind}]  ({len(pkgs)} packages)")
        for n in notes:
            print(f"      ! {n}")

    if hardcoded:
        print("\nHardcoded versions found in .sln projects (NOT managed by a property):")
        for f, pid, v in hardcoded:
            print(f"  {f}: {pid} = {v}")

    fe, npm_cache = [], {}
    for mf, sect, pkg, cur in scan_npm(find_frontend_manifests(repo)):
        want = slug_to_version.get(pkg.split("/", 1)[1].replace("-", ""))
        basis = "mirrors backend"
        if not want:
            # Not every backend module has a frontend package, and not every
            # frontend package has a backend module. Resolve these on their own.
            if pkg not in npm_cache:
                npm_cache[pkg] = npm_resolve(pkg, a.target)
            want, basis = npm_cache[pkg]
            basis = f"npm-only/{basis}"
        fe.append({"manifest": mf, "section": sect, "package": pkg, "current": cur,
                   "resolved": want, "write": f"^{want}" if want else None,
                   "basis": basis,
                   "exists": npm_has(pkg, want) if want else None})
    if fe:
        print("\nFrontend @shesha-io/* packages (written as caret ranges):")
        for r in fe:
            rel = os.path.relpath(r["manifest"], repo).replace(os.sep, "/")
            if r["resolved"] is None:
                print(f"  {rel} [{r['section']}] {r['package']}: "
                      f"UNRESOLVED ({r['basis']}) -- set manually")
            else:
                ok = {True: "", False: "  NOT ON NPM FEED", None: "  npm lookup failed"}[r["exists"]]
                same = " (no change)" if r["current"] == r["write"] else ""
                print(f"  {rel} [{r['section']}] {r['package']}: "
                      f"{r['current']} -> {r['write']}{same}  [{r['basis']}]{ok}")

    out = {"repo": repo, "solution": sln, "target": a.target, "backend": plan,
           "frontend": fe, "hardcoded": hardcoded}
    if a.json:
        json.dump(out, open(a.json, "w"), indent=2)
        print(f"\nplan written to {a.json}")

    unresolved = [p for p, v in plan.items() if not v["resolved"]]
    if unresolved or any(r.get("exists") is False for r in fe):
        print("\nINCOMPLETE: unresolved properties or missing npm versions "
              "(see above). Do not apply until resolved.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
