"""Find endpoint references inside the source of the packages this application imports.

    python scan_package_sources.py [--repo-root .] [--cache DIR] [--url http://localhost:21021]
                                   --package-source shesha-framework=C:/src/shesha-framework
                                   --package-source shesha-enterprise=C:/src/enterprise

Why: the application's own scan only sees the application's front-end and form
configurations. The framework and Enterprise ship their own React pages, components and
back-end code, and those call endpoints too - the permissioned-objects admin page, the
workflow inbox, the file-upload component. Without this step every such endpoint looks
unreferenced, and "unreferenced" is what turns into a RESTRICT or DISABLE recommendation.

Only what actually ships into this application is scanned. Each source tree is divided into
units - a directory with a package.json (a JS package) or a *.csproj (a .NET project) - and a
unit is included only if this application resolves it:

  .NET  the project name appears in the Web.Host's obj/project.assets.json (transitive
        closure included), e.g. Shesha.Application, Shesha.Workflow
  JS    the package.json name is installed under an app front-end's node_modules,
        e.g. @shesha-io/reactjs, @shesha-io/workflow

Demo apps, test projects, starter templates and modules the application does not use are
therefore excluded, and listed as such in the output.

Source is often not available - the framework and Enterprise are consumed as packages. The
step still runs without it: it records which imported packages were NOT scanned, prints what
that means, and build_catalogs.py then refuses to recommend disabling any package-owned
endpoint or entity that such a package could be calling (REVIEW instead), and lists every
unscanned package as a missing input the report must disclose. Pass --no-package-source to
run deliberately without source and forget any remembered trees.

Writes package_source_refs.json into the audit cache. crossref.py folds it into the
referenced set as `<source>-frontend`, `<source>-backend` and `<source>-packaged-form`.
A back-end mention of a service *class* (in-process use, no HTTP call) is recorded
separately: it never marks an endpoint referenced, it only softens a disable to a restrict -
the same rule build_catalogs.py applies to this repository's own C#.
"""

import argparse
import collections
import glob
import io
import json
import os
import re
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from shesha_audit import cache_dir, ensure_dir, write_json  # noqa: E402

FRONT_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs")
BACK_EXT = (".cs", ".json", ".js")
SKIP_DIRS = {"node_modules", ".next", "dist", "build", "out", "coverage", ".turbo", "bin",
             "obj", ".git", ".vs", "TestResults", "__tests__", "__mocks__", "__snapshots__",
             "test", "tests", "stories", "e2e", "cypress"}
TEST_PROJECT_RE = re.compile(r"(^|\.)(Tests?|Testing|UnitTests|IntegrationTests)$", re.I)
TEST_FILE_RE = re.compile(r"\.(test|spec|stories)\.[jt]sx?$")

# A quote, or the closing brace of an interpolated base URL (`${backendUrl}/api/...`,
# C# $"{baseUrl}/api/..."), immediately before /api/.
URL_RE = re.compile(r"(?:['\"`]|\})(/api/[A-Za-z0-9_\-/\.\{\}\$]*)")
INTERP_RE = re.compile(r"\$\{[^}]*\}|\{[^}/]*\}")
# Lines that declare an endpoint rather than call one, and comments.
DECLARATION_RE = re.compile(r"\[\s*(?:Route|Http(?:Get|Post|Put|Delete|Patch|Head|Options))\s*\(|"
                            r"\bRoute\s*=|\.Map(?:Get|Post|Put|Delete|Patch)\s*\(")
COMMENT_RE = re.compile(r"^\s*(?://|\*|/\*)")
SERVICE_RE = re.compile(r"\bI?([A-Z][A-Za-z0-9_]*AppService)\b")
SERVICE_DECL_RE = re.compile(r"\b(?:class|interface)\s+I?([A-Z][A-Za-z0-9_]*AppService)\b")
# Form references: a package's own UI opens its forms by name, so without these a
# package-owned form looks unopened. `formId: { module, name }` in code and in packaged
# configuration items (JSON, possibly escaped inside markup), and literal C# identifiers.
FORMID_OBJ_RE = re.compile(r"""formId\\?['"]?\s*[:=]\s*\{([^{}]{0,300})\}""")
FORM_NAME_RE = re.compile(r"""\bname\\?['"]?\s*:\s*\\?['"]([A-Za-z0-9_\-\. ]+?)\\?['"]""")
FORM_MODULE_RE = re.compile(r"""\bmodule\\?['"]?\s*:\s*\\?['"]([A-Za-z0-9_\-\.]+?)\\?['"]""")
CS_FORMID_RE = re.compile(r'new\s+FormIdentifier\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)')
EVIDENCE_CAP = 10


def git_info(path):
    """Branch and commit of the repository holding `path`, for the report's version note."""
    def run(*a):
        try:
            return subprocess.run(("git", "-C", path) + a, capture_output=True, text=True,
                                  timeout=20).stdout.strip() or None
        except Exception:
            return None
    root = run("rev-parse", "--show-toplevel")
    return {"root": root, "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
            "commit": run("log", "-1", "--format=%h %ad %s", "--date=short"),
            "tag": run("describe", "--tags", "--abbrev=0")}


def resolved_nuget(repo_root):
    """Every package name the application's Web.Host resolves, transitive ones included."""
    names = set()
    for assets in glob.glob(os.path.join(repo_root, "backend", "src", "*", "obj",
                                         "project.assets.json")):
        try:
            doc = json.load(io.open(assets, encoding="utf-8"))
        except Exception:
            continue
        names.update(k.split("/")[0].lower() for k in (doc.get("libraries") or {}))
    return names


def resolved_npm(repo_root):
    """{package name: installed version} for scoped packages under any front-end's node_modules."""
    out = {}
    for pkg in glob.glob(os.path.join(repo_root, "*", "node_modules", "@*", "*", "package.json")):
        try:
            doc = json.load(io.open(pkg, encoding="utf-8"))
        except Exception:
            continue
        if doc.get("name"):
            out[doc["name"]] = doc.get("version")
    return out


def imported_shesha_frontends(repo_root):
    """{name: version} of @shesha-io packages installed from a registry.

    A workspace package (npm links it: node_modules/@shesha-io/hcm -> packages/hcm) is this
    repository's own code and is already covered by scan_frontend.py, so it is excluded.
    What remains ships UI whose calls this audit can only see if its source is scanned.
    """
    out = {}
    for pkg_dir in glob.glob(os.path.join(repo_root, "*", "node_modules", "@shesha-io", "*")):
        real = os.path.realpath(pkg_dir)
        if "node_modules" not in real.replace("\\", "/").split("/"):
            continue                    # linked workspace package: the app's own source
        try:
            doc = json.load(io.open(os.path.join(pkg_dir, "package.json"), encoding="utf-8"))
        except Exception:
            continue
        if doc.get("name"):
            out[doc["name"]] = doc.get("version")
    return out


IMPLICATIONS = """
  Without the source of an imported package, the audit cannot see the calls that package's
  own screens, components and back-end code make. Every endpoint only that package calls
  will look UNREFERENCED - and unreferenced is what drives a DISABLE or RESTRICT
  recommendation. Acting on those would break the package's screens (in one audit of this
  kind, 27 disable recommendations were withdrawn once framework and Enterprise source
  were scanned).

  What the audit does about it:
    - unreferenced endpoints and entities owned by a package are recommended REVIEW, not
      DISABLE/RESTRICT, with the unscanned packages named in packageSourcesNotScanned
    - each unscanned package is recorded as a missing input, which the index must disclose
  To lift the cap, re-run with --package-source NAME=PATH pointing at each package's source.
"""


def find_units(root):
    """{unit dir: (kind, name)} for every package.json / *.csproj directory under root."""
    units = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        csproj = [f for f in filenames if f.endswith(".csproj")]
        if csproj:
            units[dirpath] = ("dotnet", csproj[0][:-len(".csproj")])
        elif "package.json" in filenames:
            try:
                name = json.load(io.open(os.path.join(dirpath, "package.json"),
                                         encoding="utf-8")).get("name")
            except Exception:
                name = None
            units[dirpath] = ("npm", name or os.path.basename(dirpath))
    return units


def unit_of(path, units):
    d = os.path.dirname(path)
    while True:
        if d in units:
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


# A URL is often built from a module-level constant: const BASE = '/api/services/X/Y' and then
# `${BASE}/action` or BASE + '/action'. Inline those constants first, so the endpoint is seen as
# a literal reference instead of an opaque runtime-built URL (which made called endpoints look
# unused).
API_CONST_RE = re.compile(r"""\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::\s*string\s*)?=\s*"""
                          r"""['"`](/api/[^'"`$]*)['"`]""")


def inline_api_constants(text):
    consts = dict(API_CONST_RE.findall(text))
    for name, value in consts.items():
        value = value.rstrip("/")
        text = re.sub(r"\$\{\s*%s\s*\}" % re.escape(name), lambda m: value, text)
        text = re.sub(r"\b%s\s*\+\s*(['\"`])" % re.escape(name),
                      lambda m: m.group(1) + value, text)
    return text


def extract(text):
    """(literal paths, template patterns), each as [(normalised path, line)]."""
    literals, patterns = [], []
    text = inline_api_constants(text)
    for m in URL_RE.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.start())
        line = text[line_start:line_end if line_end >= 0 else len(text)]
        if COMMENT_RE.match(line) or DECLARATION_RE.search(line):
            continue
        raw = m.group(1).rstrip("/.")
        if raw.count("/") < 2 or raw.lower() in ("/api/services", "/api/dynamic"):
            continue                    # "/api/" or a bare prefix is not an endpoint
        lineno = text.count("\n", 0, m.start()) + 1
        if "$" in raw or "{" in raw:
            pat = INTERP_RE.sub("{}", raw).lower()
            if pat.count("/") >= 2 and "$" not in pat:
                patterns.append((pat, lineno))
        else:
            literals.append((raw.lower(), lineno))
    return literals, patterns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--url", default="http://localhost:21021")
    ap.add_argument("--package-source", action="append", default=[], metavar="NAME=PATH",
                    help="a package source tree; repeatable. Remembered in the cache, so a "
                         "later run without the flag rescans the same trees")
    ap.add_argument("--no-package-source", action="store_true",
                    help="run without any package source and forget remembered trees")
    args = ap.parse_args()

    repo_root = os.path.abspath(args.repo_root)
    cache = args.cache or cache_dir(args.repo_root, args.url)
    config_path = os.path.join(cache, "package_sources_config.json")
    specs = []
    for item in args.package_source:
        name, _, path = item.partition("=")
        if not name or not path:
            print("--package-source %r: expected NAME=PATH" % item, file=sys.stderr)
            return 2
        specs.append({"name": name.strip(), "path": os.path.abspath(path.strip())})
    ensure_dir(cache)
    if args.no_package_source:
        specs = []
        if os.path.isfile(config_path):
            os.remove(config_path)
            print("forgot remembered package sources")
    elif specs:
        write_json(config_path, {"sources": specs})
    elif os.path.isfile(config_path):
        specs = json.load(io.open(config_path, encoding="utf-8")).get("sources") or []
        print("using remembered package sources from %s" % config_path)
    unavailable = [s for s in specs if not os.path.isdir(s["path"])]
    for s in unavailable:
        print("WARNING: package source %s not found at %s - continuing without it"
              % (s["name"], s["path"]))
    specs = [s for s in specs if os.path.isdir(s["path"])]

    nuget = resolved_nuget(repo_root)
    npm = resolved_npm(repo_root)
    if not nuget:
        print("WARNING: no project.assets.json under backend/src/*/obj - restore the backend "
              "first. No .NET project can be matched, so back-end code is not scanned.")
    if not npm:
        print("WARNING: no scoped packages under */node_modules - run npm install in the "
              "front-end first. No JS package can be matched, so front-end code is not scanned.")

    refs = collections.defaultdict(list)          # path -> evidence
    ref_counts = collections.Counter()
    pats = collections.defaultdict(list)
    service_mentions = collections.defaultdict(lambda: {"count": 0, "files": []})
    sources_out = []

    latest_item, superseded = {}, collections.Counter()
    form_refs = collections.defaultdict(list)     # "module/name" (or "?/name") -> evidence

    def record(source, kind, fn, where, text):
        literals, patterns = extract(text)
        for url, line in literals:
            ref_counts[url] += 1
            if len(refs[url]) < EVIDENCE_CAP:
                refs[url].append({"source": source, "kind": kind,
                                  "file": "%s:%d" % (where, line)})
        for pat, line in patterns:
            if len(pats[pat]) < EVIDENCE_CAP:
                pats[pat].append({"source": source, "kind": kind,
                                  "file": "%s:%d" % (where, line)})
        found = []
        for m in FORMID_OBJ_RE.finditer(text):
            name = FORM_NAME_RE.search(m.group(1))
            module = FORM_MODULE_RE.search(m.group(1))
            if name:
                found.append((module.group(1) if module else "?", name.group(1), m.start()))
        for m in CS_FORMID_RE.finditer(text):
            found.append((m.group(1), m.group(2), m.start()))
        # A packaged form (<Module>/form/<name>.json inside a .shaconfig) carries its own
        # identifier in its markup; that is not a reference to itself.
        inner = where.split("!", 1)[1].split("/") if "!" in where else []
        self_key = None
        if len(inner) >= 3 and inner[-2] == "form" and inner[-1].endswith(".json"):
            self_key = ("%s/%s" % (inner[0], inner[-1][:-len(".json")])).lower()
        for module, name, at in found:
            key = "%s/%s" % (module, name)
            if self_key and key.lower() == self_key:
                continue
            if len(form_refs[key]) < EVIDENCE_CAP:
                form_refs[key].append({"source": source, "kind": kind, "file": "%s:%d" % (
                    where, text.count("\n", 0, at) + 1)})
        if kind == "backend" and fn.endswith(".cs"):
            declared = set(SERVICE_DECL_RE.findall(text))
            for svc in set(SERVICE_RE.findall(text)) - declared:
                entry = service_mentions[svc]
                entry["count"] += 1
                if len(entry["files"]) < 8:
                    entry["files"].append(where)

    for spec in specs:
        root, name = spec["path"], spec["name"]
        info = git_info(root)
        display_base = os.path.dirname(info["root"]) if info.get("root") else os.path.dirname(root)
        units = find_units(root)
        included, excluded = {}, {}
        for udir, (kind, uname) in units.items():
            rel = os.path.relpath(udir, display_base).replace("\\", "/")
            shipped = (uname.lower() in nuget) if kind == "dotnet" else (uname in npm)
            if kind == "dotnet" and TEST_PROJECT_RE.search(uname):
                shipped = False
            (included if shipped else excluded)[udir] = {
                "unit": uname, "kind": kind, "dir": rel,
                "installedVersion": npm.get(uname) if kind == "npm" else None}
        counts = collections.Counter()

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                           and not TEST_PROJECT_RE.search(d)]
            for fn in filenames:
                path = os.path.join(dirpath, fn)
                udir = unit_of(path, units)
                if udir not in included:
                    continue
                ukind = included[udir]["kind"]
                rel = os.path.relpath(path, display_base).replace("\\", "/")
                if fn.endswith(".shaconfig"):
                    kind = "packaged-form"
                elif ukind == "npm" and fn.endswith(FRONT_EXT) and not fn.endswith(".d.ts") \
                        and not TEST_FILE_RE.search(fn):
                    kind = "frontend"
                elif ukind == "dotnet" and fn.endswith(BACK_EXT):
                    kind = "backend"
                else:
                    continue
                blobs = []
                if kind == "packaged-form":
                    # ConfigMigrations holds every historical package. The database ends up
                    # with the latest version of each item, so only that one is evidence;
                    # names sort by date (packageYYYYMMDD_hhmm.shaconfig).
                    try:
                        with zipfile.ZipFile(path) as z:
                            for member in z.namelist():
                                if member.endswith("/"):
                                    continue
                                key = (udir, member)
                                prior = latest_item.get(key)
                                if prior is None or fn > prior[0]:
                                    if prior is not None:
                                        superseded[name] += 1
                                    latest_item[key] = (fn, "%s!%s" % (rel, member),
                                                        z.read(member).decode("utf-8", "replace"))
                                else:
                                    superseded[name] += 1
                    except Exception:
                        continue
                    counts[kind] += 1
                    continue
                else:
                    try:
                        blobs.append((rel, io.open(path, encoding="utf-8",
                                                   errors="replace").read()))
                    except Exception:
                        continue
                counts[kind] += 1
                for where, text in blobs:
                    record(name, kind, fn, where, text)

        for (_, _), (_, where, text) in sorted(latest_item.items()):
            record(name, "packaged-form", "", where, text)
        latest_item.clear()

        sources_out.append({
            "name": name, "path": root, "git": info, "filesScanned": dict(counts),
            "packagedItemsSuperseded": superseded[name],
            "unitsIncluded": sorted(v["dir"] + " (" + v["unit"] + ")" for v in included.values()),
            "unitsExcluded": sorted(v["dir"] + " (" + v["unit"] + ")" for v in excluded.values()),
        })
        print("%s  %s  %s" % (name, info.get("branch") or "?", info.get("commit") or ""))
        print("  units shipped into this app: %d   excluded: %d" % (len(included), len(excluded)))
        for v in sorted(included.values(), key=lambda v: v["dir"]):
            print("    + %-60s %s" % (v["dir"], v["unit"]))
        print("  files scanned: %s" % ", ".join("%s=%d" % kv for kv in sorted(counts.items())))

    frontends = imported_shesha_frontends(repo_root)
    scanned_npm = {u.rsplit("(", 1)[-1].rstrip(")") for s in sources_out
                   for u in s["unitsIncluded"]}
    scanned_dotnet = sorted(n for n in scanned_npm if not n.startswith("@"))
    coverage = {
        "frontendPackagesImported": frontends,
        "frontendPackagesScanned": sorted(n for n in frontends if n in scanned_npm),
        "frontendPackagesNotScanned": sorted(n for n in frontends if n not in scanned_npm),
        "dotnetUnitsScanned": scanned_dotnet,
        "sourcesUnavailable": [s["name"] for s in unavailable],
    }
    if not sources_out:
        print("\nPACKAGE SOURCE NOT SCANNED - no framework or Enterprise source was available.")
    elif coverage["frontendPackagesNotScanned"]:
        print("\nPACKAGE SOURCE PARTLY SCANNED")
    if coverage["frontendPackagesNotScanned"] or not sources_out:
        print("  imported front-end packages not scanned: %s"
              % (", ".join("%s %s" % (n, frontends[n])
                           for n in coverage["frontendPackagesNotScanned"]) or "none detected"))
        print(IMPLICATIONS)

    out = {
        "coverage": coverage,
        "sources": sources_out,
        "references": {k: v for k, v in sorted(refs.items())},
        "referenceCounts": dict(sorted(ref_counts.items())),
        "patterns": {k: v for k, v in sorted(pats.items())},
        "forms": {k: v for k, v in sorted(form_refs.items())},
        "serviceMentions": dict(sorted(service_mentions.items())),
        "summary": {
            "literalPaths": len(refs),
            "templatePatterns": len(pats),
            "servicesMentioned": len(service_mentions),
        },
    }
    out_path = os.path.join(cache, "package_source_refs.json")
    write_json(out_path, out)
    print("\nliteral endpoint paths  %d" % len(refs))
    print("template URL patterns   %d (resolved against the surface in crossref.py)" % len(pats))
    print("services mentioned      %d (in-process back-end use)" % len(service_mentions))
    print("forms referenced        %d" % len(form_refs))
    print("written %s" % out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
