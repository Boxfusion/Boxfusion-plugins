"""Catalogue the coded (custom) front-end: screens, pages, components and what they call.

    python scan_frontend.py [--repo-root .] [--cache DIR] [--url http://localhost:21021]
                            [--frontend-dir adminportal]

Writes two things into the audit cache:

  frontend_scan.json   one record per coded source file, plus the import graph
  coded-endpoints.txt  one /api/ path per line - the input crossref.py expects

A "custom form" in Shesha is a screen built in code (a Next.js route, a registered screen, a
custom designer component) as opposed to a form configuration stored in the database. Both
reach endpoints, and both can be orphaned, so both need cataloguing - a coded screen nobody
routes to is the same dead surface as an unreferenced form configuration.

Facts only. Whether an orphan should be deleted is a judgement made in the review phase.
"""

import argparse
import collections
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from shesha_audit import cache_dir, ensure_dir, write_json  # noqa: E402

CODE_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs")
SKIP_DIRS = {"node_modules", ".next", "dist", "build", "out", "coverage", ".turbo",
             "__snapshots__"}

API_RE = re.compile(r"['\"`](/api/[A-Za-z0-9_\-/\.\{\}\$]*)")
HOOK_RE = re.compile(r"\b(useGet|useMutate|useGetForEndpoint|useMutateForEndpoint|usePost|"
                     r"usePut|useDelete)\s*[<(]")
HTTP_RE = re.compile(r"\b(?:http|axios|httpClient)\s*\.\s*(get|post|put|patch|delete|head|"
                     r"options)\s*\(")
# A URL assembled at runtime cannot be attributed to an endpoint. Same rule as the form
# scan: it taints, it never counts as evidence that something is unused.
OPAQUE_RE = [
    (re.compile(r"['\"`]/api/[^'\"`]*\$\{"), "template-literal-url"),
    (re.compile(r"['\"`]/api/[^'\"`]*['\"`]\s*\+"), "concatenated-url"),
    (re.compile(r"\bhttp\s*\[\s*[^\]]+\]\s*\("), "dynamic-verb"),
    # `url: string` in an interface is a type, not a runtime URL. Excluding the type names
    # stops this firing on every component prop that happens to be called `url`.
    (re.compile(r"\b(?:url|endpoint)\s*[:=]\s*"
                r"(?!string|number|boolean|any|unknown|null|undefined)"
                r"[A-Za-z_$][A-Za-z0-9_$\.]*\s*[,;\)]"),
     "endpoint-from-variable"),
]
ENTITY_RE = re.compile(r"\b(?:entityType|modelType)\s*[:=]\s*\{?\s*['\"]([A-Za-z0-9_\.]+)['\"]")
FORMID_RE = re.compile(r"formId\s*[:=]\s*\{?\{?\s*([^}]{0,200})\}?\}?", re.S)
FORM_NAME_RE = re.compile(r"name\s*:\s*['\"]([A-Za-z0-9_\-\.]+)['\"]")
FORM_MODULE_RE = re.compile(r"module\s*:\s*['\"]([A-Za-z0-9_\-\.]+)['\"]")
# Any string that *could* be a permission name. Filtered against the live permission list
# below, because the shape alone matches plenty of unrelated kebab-case strings.
PERMISSION_RE = re.compile(r"['\"]((?:pages|app|Pages)[:.][A-Za-z0-9_\-\.]+|"
                           r"[A-Za-z][A-Za-z0-9]+-[A-Za-z][A-Za-z0-9\-]+)['\"]")
IMPORT_RE = re.compile(r"""(?:import|export)\s[^;'"]*from\s*['"]([^'"]+)['"]|"""
                       r"""require\(\s*['"]([^'"]+)['"]\s*\)""")
ROUTE_CONST_RE = re.compile(r"['\"](/[A-Za-z0-9_\-/\[\]\.]{1,120})['\"]")


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


def find_frontends(repo_root):
    """Directories holding a Shesha front-end. More than one is normal and matters:
    scanning only one caps the confidence of every 'unreferenced' conclusion."""
    out = []
    for name in sorted(os.listdir(repo_root)):
        path = os.path.join(repo_root, name)
        if not os.path.isdir(path) or name in SKIP_DIRS or name.startswith("."):
            continue
        if not os.path.isfile(os.path.join(path, "next.config.js")) and \
           not os.path.isfile(os.path.join(path, "next.config.mjs")):
            continue
        pkg = os.path.join(path, "package.json")
        dep = ""
        if os.path.isfile(pkg):
            try:
                dep = json.dumps(json.load(io.open(pkg, encoding="utf-8")))
            except Exception:
                dep = ""
        out.append({"dir": name, "isShesha": "@shesha-io/reactjs" in dep})
    return out


def walk_code(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(CODE_EXT) and not fn.endswith(".d.ts"):
                yield os.path.join(dirpath, fn)


def route_of(rel):
    """The Next.js App Router route a file serves, or None.

    src/app/login/page.tsx        -> /login
    src/app/dynamic/[...path]/page.tsx -> /dynamic/[...path]
    """
    parts = rel.replace("\\", "/").split("/")
    if "app" not in parts:
        return None
    base = os.path.basename(rel)
    if base.split(".")[0] not in ("page", "route"):
        return None
    idx = parts.index("app")
    segs = [p for p in parts[idx + 1:-1] if not (p.startswith("(") and p.endswith(")"))]
    return "/" + "/".join(segs) if segs else "/"


def kind_of(rel, route):
    r = rel.replace("\\", "/")
    if route:
        return "route-page"
    if "/screens/" in r or "/generic-pages/" in r:
        return "screen"
    if "/designer-components/" in r:
        return "designer-component"
    if "/api/" in r or "/apis/" in r:
        return "api-module"
    if "/providers/" in r:
        return "provider"
    if "/components/" in r:
        return "component"
    if "/routes/" in r or "/routing/" in r:
        return "route-table"
    if "/app-constants/" in r or "/constants/" in r:
        return "constants"
    return "other"


def package_of(front_dir, rel):
    """Coded screens belong to the front-end code package that ships them, not to a backend
    Shesha module - a workspace package under packages/<x> is its own deployable unit."""
    r = rel.replace("\\", "/")
    m = re.match(r"packages/([^/]+)/", r)
    return "%s/packages/%s" % (front_dir, m.group(1)) if m else front_dir


def window(text, at, before=60, after=160):
    start, end = max(0, at - before), min(len(text), at + after)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def known_permissions(cache):
    """Live permission names, used to filter the candidate strings the regex finds."""
    path = os.path.join(cache, "permissions.json")
    if not os.path.isfile(path):
        return None
    try:
        doc = json.load(io.open(path, encoding="utf-8"))
    except Exception:
        return None
    items = doc.get("result") if isinstance(doc, dict) else doc
    if isinstance(items, dict):
        items = items.get("items") or []
    return {p.get("name") for p in (items or []) if isinstance(p, dict) and p.get("name")}


def scan_file(path, rel, front_dir):
    try:
        text = io.open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return None
    text = inline_api_constants(text)
    route = route_of(rel)
    endpoints = sorted({m.group(1) for m in API_RE.finditer(text)
                        if "${" not in m.group(1)})
    opaque = []
    for rx, reason in OPAQUE_RE:
        for m in rx.finditer(text):
            opaque.append({"reason": reason, "snippet": window(text, m.start()),
                           "guessedUrl": guess_url(window(text, m.start()))})
            break

    forms = set()
    for m in FORMID_RE.finditer(text):
        blob = m.group(1)
        name = FORM_NAME_RE.search(blob)
        module = FORM_MODULE_RE.search(blob)
        if name:
            forms.add("%s/%s" % (module.group(1) if module else "?", name.group(1)))
    entities = sorted({m.group(1) for m in ENTITY_RE.finditer(text)
                       if "." in m.group(1)})
    perms = sorted({m.group(1) for m in PERMISSION_RE.finditer(text)})
    imports = sorted({(m.group(1) or m.group(2)) for m in IMPORT_RE.finditer(text)})
    verbs = sorted({m.group(1).upper() for m in HTTP_RE.finditer(text)})
    routes_declared = []
    if kind_of(rel, route) == "route-table":
        routes_declared = sorted({m.group(1) for m in ROUTE_CONST_RE.finditer(text)})

    return {
        "file": rel,
        "package": package_of(front_dir, rel),
        "kind": kind_of(rel, route),
        "route": route,
        "endpointsReferenced": endpoints,
        "httpVerbs": verbs,
        "usesDataHooks": bool(HOOK_RE.search(text)),
        "formsReferenced": sorted(forms),
        "entitiesReferenced": entities,
        "permissionsReferenced": perms,
        "routesDeclared": routes_declared,
        "opaque": opaque,
        "imports": imports,
        "lines": text.count("\n") + 1,
    }


def guess_url(snippet):
    m = re.search(r"/api/[A-Za-z0-9_\-/\.\{\}\$]+", snippet or "")
    return m.group(0) if m else None


def resolve_import(spec, from_rel, known):
    """Resolve a relative or `@/`-aliased import to a scanned file, or None."""
    if spec.startswith("@/"):
        base = "src/" + spec[2:]
    elif spec.startswith("."):
        base = os.path.normpath(os.path.join(os.path.dirname(from_rel), spec))
    else:
        return None
    base = base.replace("\\", "/")
    for cand in (base, base + ".ts", base + ".tsx", base + ".js", base + ".jsx",
                 base + "/index.ts", base + "/index.tsx", base + "/index.js"):
        if cand in known:
            return cand
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--url", default="http://localhost:21021")
    ap.add_argument("--frontend-dir", action="append",
                    help="override auto-detection; repeatable")
    args = ap.parse_args()

    root = os.path.abspath(args.repo_root)
    detected = find_frontends(root)
    fronts = args.frontend_dir or [f["dir"] for f in detected if f["isShesha"]]
    if not fronts:
        print("No Shesha front-end found under %s. Pass --frontend-dir." % root,
              file=sys.stderr)
        return 2
    cache = args.cache or cache_dir(args.repo_root, args.url)
    perms_known = known_permissions(cache)
    if perms_known is None:
        print("NOTE: no permissions.json in the cache, so permissionsReferenced is "
              "unfiltered and will contain look-alike strings. Run collect.py first.")
    print("front-ends detected: %s" % ", ".join(
        "%s%s" % (f["dir"], "" if f["isShesha"] else " (not Shesha)") for f in detected))
    if len(fronts) < len([f for f in detected if f["isShesha"]]):
        print("WARNING: scanning %d of %d Shesha front-ends. Every 'unreferenced' result "
              "below is capped at REVIEW confidence." % (len(fronts), len(detected)))

    files, by_front = {}, collections.Counter()
    for front in fronts:
        base = os.path.join(root, front)
        for path in walk_code(base):
            rel = os.path.relpath(path, base).replace("\\", "/")
            rec = scan_file(path, rel, front)
            if rec is None:
                continue
            rec["frontend"] = front
            if perms_known is not None:
                rec["permissionsReferenced"] = [p for p in rec["permissionsReferenced"]
                                                if p in perms_known]
            files[front + "::" + rel] = rec
            by_front[front] += 1

    # Import graph, so an orphaned component can be told from a used one.
    per_front_known = collections.defaultdict(set)
    for key, rec in files.items():
        per_front_known[rec["frontend"]].add(rec["file"])
    referenced_by = collections.defaultdict(set)
    for key, rec in files.items():
        known = per_front_known[rec["frontend"]]
        for spec in rec["imports"]:
            target = resolve_import(spec, rec["file"], known)
            if target:
                referenced_by[rec["frontend"] + "::" + target].add(rec["file"])
    for key, rec in files.items():
        rec["referencedByFiles"] = sorted(referenced_by.get(key, ()))
        rec.pop("imports", None)

    coded = sorted({e for rec in files.values() for e in rec["endpointsReferenced"]})
    out_path = os.path.join(cache, "frontend_scan.json")
    ensure_dir(os.path.dirname(out_path))
    write_json(out_path, {
        "frontendsDetected": detected,
        "frontendsScanned": fronts,
        "permissionFilterApplied": perms_known is not None,
        "files": files,
        "codedEndpoints": coded,
        "opaqueCount": sum(len(r["opaque"]) for r in files.values()),
    })

    coded_txt = os.path.join(os.path.dirname(out_path), "coded-endpoints.txt")
    io.open(coded_txt, "w", encoding="utf-8").write("\n".join(coded) + "\n")

    print("\nfiles scanned        %d (%s)"
          % (len(files), ", ".join("%s=%d" % (k, v) for k, v in by_front.items())))
    kinds = collections.Counter(r["kind"] for r in files.values())
    for kind, n in kinds.most_common():
        print("  %-20s %d" % (kind, n))
    print("coded endpoints      %d" % len(coded))
    print("opaque URL builds    %d" % sum(len(r["opaque"]) for r in files.values()))
    orphans = [r["file"] for r in files.values()
               if not r["referencedByFiles"] and not r["route"]
               and r["kind"] in ("component", "screen", "designer-component", "api-module")]
    print("no importer, no route %d" % len(orphans))
    for o in orphans[:15]:
        print("  %s" % o)
    print("\nwritten %s" % out_path)
    print("written %s" % coded_txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
