"""Build the per-package catalogue JSON that the whole audit is written from.

    python build_catalogs.py --repo-root . [--run-dir security-audits/YYMMDD-HHMM]
                             [--packages Shesha.Hcm --packages Shesha.Leave]
                             [--scope app] [--url http://localhost:21021]

Reads the audit cache (collect.py, analyze_forms.py, scan_frontend.py, crossref.py,
source_scan.py, probe.py, posture_scan.py, object_auth.py) and writes, per package:

    catalog/{package}-roles-and-permissions.json
    catalog/{package}-configured-forms.json
    catalog/{package}-custom-forms.json
    catalog/{package}-endpoints.json
    catalog/{package}-entities.json
    catalog/{package}-other-findings.json
    catalog/_index.json

A "package" is the unit that owns configuration items and code: a Shesha module for
back-end artefacts (`Shesha.Hcm`, `Shesha.Leave`, `Shesha` for the framework itself), and a
front-end code package for coded screens (`adminportal`, `adminportal/packages/hcm`).
Grouping this way is what makes a recommendation actionable - every row in one file is fixed
by the same team, in the same repository or by the same upgrade.

What this script does NOT do: assign final severities, decide that an anonymous endpoint is
acceptable, or write prose. It emits `sensitivity` and `recommendedAction` as *heuristics*
carrying `reviewRequired`, and the review phase confirms or overrides each one. A heuristic
presented as a conclusion is worse than no heuristic at all.
"""

import argparse
import collections
import datetime
import glob
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from catalog_schema import normalise_rows  # noqa: E402
from shesha_audit import (ACCESS, DYN_RE, Ownership, SVC_RE, cache_dir,  # noqa: E402
                          ensure_dir, latest_run_dir, load_surface,
                          lookup_action_record, new_run_dir, read_json, unwrap,
                          write_json)

# --------------------------------------------------------------------------------------
# Judgement inputs the script only *suggests* against
# --------------------------------------------------------------------------------------

# Personal, financial or health data in an HR / case-management application. Substring match
# on entity and service names, lowercased.
SENSITIVE_HIGH = [
    "person", "employee", "user", "account", "salary", "payroll", "remuneration", "bank",
    "medical", "health", "disciplinary", "grievance", "identity", "passport", "address",
    "contact", "nextofkin", "dependant", "beneficiary", "document", "attachment",
    "storedfile", "note", "password", "otp", "token", "permission", "role",
]
SENSITIVE_MEDIUM = [
    "leave", "performance", "agreement", "assessment", "appraisal", "review", "balance",
    "cycle", "profile", "supervisor", "delegation", "position", "job", "organisation",
    "organization", "unit", "qualification", "training", "case", "request", "application",
    "workflow", "task", "notification",
]
# State-changing or administrative operations, by action name.
WRITE_ACTIONS = ("create", "update", "delete", "remove", "save", "submit", "approve",
                 "reject", "cancel", "import", "enqueue", "start", "run", "trigger",
                 "execute", "send", "reset", "set", "assign", "complete", "sync")

# Framework infrastructure the Shesha React runtime calls without any application code
# naming it. Never recommend disabling these - see references/disabling-unused-endpoints.md.
KEEP_INFRA = [
    "/api/tokenauth/", "/api/services/app/session/", "/api/antiforgery/",
    "/api/services/shesha/formconfiguration/", "/api/services/app/metadata/",
    "/api/services/app/referencelist/", "/api/services/app/settings/",
    "/api/services/app/permissionedobject/", "/api/services/app/permission/",
    "/api/services/app/sharole/", "/api/storedfile/", "/api/services/app/notes/",
    "/api/services/shesha/entities/", "/api/services/app/configurationitem/",
    "/api/services/app/module/", "/api/services/app/user/",
]

DEFINITIONS = {
    "isUnreferenced": "Nothing in the scanned front-end reaches this: no form configuration, "
                      "no coded screen, no main-menu entry, and - when package sources were "
                      "scanned - no framework or Enterprise page, component or packaged form. "
                      "It says nothing about back-end callers (jobs, workflow tasks, "
                      "integrations) - check backendCodeReferences, "
                      "packageBackendCodeReferences and the safety gates before acting.",
    "referencedByPackageSource": "Where the framework's or Enterprise's own source calls "
                                 "this endpoint (kind: file:line), from "
                                 "scan_package_sources.py. Up to five shown.",
    "packageSourcesNotScanned": "Imported packages whose source was not scanned and that "
                                "could call this package-owned object. Non-empty means an "
                                "unreferenced verdict is unproven: the recommendation is "
                                "capped at REVIEW, never DISABLE/RESTRICT on usage grounds.",
    "packageBackendCodeReferences": "Framework/Enterprise back-end files that use this "
                                    "service class in-process. Not an HTTP caller, so it "
                                    "does not make the endpoint referenced - it rules out "
                                    "a disable.",
    "referenceIndeterminate": "An opaque reference (a URL built at runtime) in a form or "
                              "coded file could reach this. Treat as possibly-used, never "
                              "as unreferenced.",
    "hasPermissionedObjectConfig": "A PermissionedObject row exists for this object. Without "
                                   "one, access resolves entirely through DefaultEndpointAccess.",
    "authorizationRules": "The effective access level actually enforced at runtime, resolved "
                          "through the precedence model in references/enforcement-rules.md - "
                          "not the code attribute.",
    "authorizationMethod": "configuration = a database record decides; code = a code "
                           "attribute the bootstrapper re-seeds every restart; both = a "
                           "record exists and code re-seeds it; none = nothing decides, so "
                           "DefaultEndpointAccess applies.",
    "hasGlobalSpecifications": "A [GlobalSpecification] filters every query for this entity. "
                               "This is the only row-level control in Shesha - a permission "
                               "gates the endpoint, a specification gates the row.",
    "sensitivity": "HEURISTIC from the artefact name. reviewRequired is always true: confirm "
                   "against what the data actually is before quoting it in a report.",
    "recommendedAction": "HEURISTIC. KEEP, KEEP-INFRA, RESTRICT, SET-EXPLICIT-ACCESS, "
                         "ADD-GLOBAL-SPECIFICATION, DISABLE-ACTION, DISABLE-ENTITY, "
                         "DISABLE-ENDPOINT or REVIEW. Prefer RESTRICT over DISABLE wherever "
                         "a caller is plausible.",
}


def sensitivity_of(*names):
    blob = " ".join(n.lower() for n in names if n)
    hits_high = [h for h in SENSITIVE_HIGH if h in blob]
    hits_med = [h for h in SENSITIVE_MEDIUM if h in blob]
    if hits_high:
        rating, basis = "HIGH", "name matches %s" % ", ".join(hits_high[:4])
    elif hits_med:
        rating, basis = "MEDIUM", "name matches %s" % ", ".join(hits_med[:4])
    else:
        rating, basis = "LOW", "no personal-data keyword in the name"
    return {"rating": rating, "basis": basis, "reviewRequired": True}


def is_keep_infra(path):
    p = path.lower()
    return any(p.startswith(k) for k in KEEP_INFRA)


def is_write(action):
    a = (action or "").lower()
    return any(a.startswith(w) for w in WRITE_ACTIONS)


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------


def maybe(cache, name):
    path = os.path.join(cache, name)
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        try:
            return read_json(path)
        except ValueError:
            return None
    return None


def load_all(cache, repo_root):
    d = {"missing": []}

    def need(name, key, transform=None):
        doc = maybe(cache, name)
        if doc is None:
            d["missing"].append(name)
            d[key] = None
        else:
            d[key] = transform(doc) if transform else doc

    own_raw = maybe(cache, "ownership.json") or {"appModules": [], "appUrlSegments": []}
    d["ownership"] = Ownership(own_raw.get("appModules") or [],
                               own_raw.get("appUrlSegments") or [],
                               own_raw.get("appPathPrefixes") or ())
    d["appModules"] = set(own_raw.get("appModules") or [])

    need("swagger.json", "surface", lambda doc: load_surface(doc))
    need("form_analysis.json", "forms")
    need("frontend_scan.json", "frontend")
    need("crossref.json", "crossref")
    need("source_scan.json", "source")
    need("posture.json", "posture")
    need("probe-results.json", "probes")
    need("object-auth.json", "objectauth")
    need("mainmenu.json", "mainmenu")
    need("entity-permissions.json", "entityPermissions")
    need("role-permissions.json", "rolePermissions")
    # Optional: without it the catalogue is still valid, only less complete - recorded in
    # the confidence block rather than as a missing input.
    # A stale or incomplete surface caps everything: endpoints missing from it are simply not
    # in the catalogue. Named as missing inputs so the index has to disclose it.
    surf = (maybe(cache, "collection-report.json") or {}).get("surface") or {}
    d["surfaceHealth"] = surf
    if surf.get("cachedCopyFrom"):
        d["missing"].append("swagger.json (stale: cached copy from %s)" % surf["cachedCopyFrom"])
    if (surf.get("liveOnlyPaths") or 0) > 25:
        d["missing"].append("swagger.json (incomplete: %d live paths absent)" % surf["liveOnlyPaths"])
    d["packageSources"] = maybe(cache, "package_source_refs.json")
    cov = (d["packageSources"] or {}).get("coverage")
    if d["packageSources"] is None or cov is None:
        # never ran (or ran before coverage was recorded): nothing is known to be covered
        d["missing"].append("package_source_refs.json")
        d["pkgNotScanned"] = ["imported package source (not scanned)"]
        d["pkgUnitsScanned"] = []
    else:
        d["pkgNotScanned"] = list(cov.get("frontendPackagesNotScanned") or [])
        d["pkgUnitsScanned"] = list(cov.get("dotnetUnitsScanned") or [])
        # Named individually so the index has to say which package's callers were not seen.
        d["missing"] += ["%s source" % n for n in d["pkgNotScanned"]]

    d["entityconfigs"] = unwrap(maybe(cache, "entityconfigs.json")) or []
    d["permissions"] = unwrap(maybe(cache, "permissions.json")) or []
    d["roles"] = unwrap(maybe(cache, "roles.json")) or []
    d["modules"] = unwrap(maybe(cache, "modules.json")) or []
    d["security"] = (maybe(cache, "security-settings.json") or {}).get("result") or {}

    d["po"] = {}
    for potype in ("shesha-webapi", "shesha-webapi-action", "shesha-entity",
                   "shesha-entity-action", "shesha-webcrudapi",
                   "shesha-webcrudapi-action", "shesha-form"):
        d["po"][potype] = unwrap(maybe(cache, "po-%s.json" % potype)) or []
    return d


# --------------------------------------------------------------------------------------
# Source-code cross-referencing
# --------------------------------------------------------------------------------------

def cs_files(repo_root):
    src = os.path.join(repo_root, "backend", "src")
    if not os.path.isdir(src):
        return
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [x for x in dirnames if x not in ("obj", "bin")]
        for fn in filenames:
            if fn.endswith(".cs"):
                yield os.path.join(dirpath, fn)


MODULE_INFO_RE = re.compile(
    r"SheshaModuleInfo\(\s*(?:\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_.]*))")
NAME_CONST_RE = re.compile(
    r"(?:const|static(?:\s+readonly)?)\s+string\s+Name\s*=\s*\"([^\"]+)\"")
URL_SEGMENT_RE = re.compile(r"moduleName\s*:\s*\"([^\"]+)\"")


def module_from_text(text):
    m = MODULE_INFO_RE.search(text)
    if not m:
        return None
    if m.group(1):
        return m.group(1)
    c = NAME_CONST_RE.search(text)
    return c.group(1) if c else None


def project_module_map(repo_root):
    """project directory (repo-relative) -> the Shesha module the project declares.

    Findings about a file need a package, and the project containing the file is the only
    honest answer - a Startup.cs belongs to the host project, not to a business module.
    Projects are found by their .csproj, because repositories nest them differently:
    `backend/src/<Project>` in some, `backend/src/Module/<Project>` in others.
    """
    src = os.path.join(repo_root, "backend", "src")
    out = {}
    if not os.path.isdir(src):
        return out
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [x for x in dirnames if x not in ("obj", "bin")]
        if not any(f.endswith(".csproj") for f in filenames):
            continue
        rel = os.path.relpath(dirpath, repo_root).replace("\\", "/")
        module = None
        for path in cs_files(dirpath):
            try:
                text = io.open(path, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            module = module_from_text(text)
            if module:
                break
        out[rel] = module or os.path.basename(rel)
    return out


def refine_project_modules(proj_modules, known_modules):
    """A project that declares no module of its own belongs to its sibling's module.

    `SaGov.Leave.Application` holds the services; `SaGov.Leave.Domain` declares the module.
    Without this, findings in the Application project land in a package called
    `SaGov.Leave.Application` that nobody recognises.
    """
    out = {}
    for rel, module in proj_modules.items():
        name = os.path.basename(rel)
        if module != name or module in known_modules:
            out[rel] = module
            continue
        stem = name
        while "." in stem:
            stem = stem.rsplit(".", 1)[0]
            if stem in known_modules:
                module = stem
                break
        out[rel] = module
    return out


ROUTE_ATTR_RE = re.compile(r"\[\s*Route\(\s*\"([^\"]+)\"")


def controller_route_module_map(repo_root, proj_modules):
    """`[Route("api/services/persal/input-file")]` -> the module of the declaring project.

    Hand-routed controllers do not follow `/api/services/{module}/{Service}/{Action}`, so
    neither the URL segment nor the service name attributes them. Their route attribute
    does, and these are app-owned endpoints - exactly the ones an audit must not lose.
    """
    out = {}
    for path in cs_files(repo_root):
        if not os.path.basename(path).endswith("Controller.cs"):
            continue
        try:
            text = io.open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        rel = os.path.relpath(path, repo_root).replace("\\", "/")
        module = None
        for prefix, mod in proj_modules.items():
            if rel.startswith(prefix + "/"):
                module = mod
                break
        for m in ROUTE_ATTR_RE.finditer(text):
            route = m.group(1)
            if "[controller]" in route:
                route = route.replace(
                    "[controller]", os.path.basename(path)[: -len("Controller.cs")])
            out["/" + route.strip("/").lower()] = {"module": module, "file": rel}
    return out


def url_segment_module_map(repo_root, proj_modules):
    """ABP URL segment (`moduleName:` in PostInitialize) -> Shesha module name.

    `/api/services/{segment}/...` is the only clue an endpoint's route gives about its
    owner, and the segment is never the module name - a repository routinely registers
    module `Shesha.Hcm` under segment `HcmCommon`.
    """
    out = {}
    for path in cs_files(repo_root):
        try:
            text = io.open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        segments = URL_SEGMENT_RE.findall(text)
        if not segments:
            continue
        module = module_from_text(text)
        if not module:
            rel = os.path.relpath(path, repo_root).replace("\\", "/")
            for prefix, mod in proj_modules.items():
                if rel.startswith(prefix + "/"):
                    module = mod
                    break
        for seg in segments:
            out.setdefault(seg.lower(), module)
    return out


def scan_source_references(repo_root, permission_names, entity_names, service_names=()):
    """One pass over backend/src counting permission and entity references per file class.

    Splitting appservice / specification / other matters: a permission referenced only from a
    specification guards rows, not endpoints, and the remediation differs.
    """
    result = {
        "permission": collections.defaultdict(lambda: collections.Counter()),
        "entity": collections.Counter(),
        "entityFiles": collections.defaultdict(list),
        "specEntities": collections.defaultdict(list),
        "globalSpecEntities": set(),
        "service": collections.Counter(),
        "serviceFiles": collections.defaultdict(list),
        "filesScanned": 0,
    }
    if not permission_names and not entity_names and not service_names:
        return result
    svc_re = (re.compile(r"\b(%s)\b" % "|".join(re.escape(s) for s in sorted(service_names)))
              if service_names else None)
    perm_re = (re.compile("|".join(re.escape(p) for p in
                                   sorted(permission_names, key=len, reverse=True)))
               if permission_names else None)
    short_to_full = collections.defaultdict(list)
    for full in entity_names:
        short_to_full[full.rsplit(".", 1)[-1]].append(full)
    ent_re = (re.compile(r"\b(%s)\b" % "|".join(re.escape(s) for s in sorted(short_to_full)))
              if short_to_full else None)
    spec_re = re.compile(r"ShaSpecification\s*<\s*([A-Za-z0-9_\.]+)")
    global_spec_re = re.compile(r"\[\s*GlobalSpecification")

    for path in cs_files(repo_root):
        rel = os.path.relpath(path, repo_root).replace("\\", "/")
        base = os.path.basename(path)
        try:
            text = io.open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        result["filesScanned"] += 1
        if base.endswith("AppService.cs") or base.endswith("Controller.cs"):
            bucket = "appservice"
        elif "Specification" in base or spec_re.search(text):
            bucket = "specification"
        else:
            bucket = "other"

        if perm_re:
            for m in perm_re.finditer(text):
                result["permission"][m.group(0)][bucket] += 1

        if ent_re:
            for short in {m.group(1) for m in ent_re.finditer(text)}:
                for full in short_to_full[short]:
                    result["entity"][full] += 1
                    if len(result["entityFiles"][full]) < 8:
                        result["entityFiles"][full].append(rel)

        if svc_re:
            # A service named in a file other than its own declaration has a back-end
            # caller - a job, a workflow task, a validator. That is a safety gate against
            # recommending a disable purely because the front-end never calls it.
            declared_here = re.search(r"class\s+(%s)\b" % "|".join(
                re.escape(s) for s in service_names), text) if service_names else None
            for name in {m.group(1) for m in svc_re.finditer(text)}:
                if declared_here and declared_here.group(1) == name:
                    continue
                result["service"][name] += 1
                if len(result["serviceFiles"][name]) < 8:
                    result["serviceFiles"][name].append(rel)

        has_global = bool(global_spec_re.search(text))
        for m in spec_re.finditer(text):
            target = m.group(1)
            full = target if "." in target else (short_to_full.get(target) or [target])[0]
            result["specEntities"][full].append({"file": rel, "global": has_global})
            if has_global:
                result["globalSpecEntities"].add(full)
    return result


# --------------------------------------------------------------------------------------
# Package attribution
# --------------------------------------------------------------------------------------

def module_name_map(d):
    """moduleId -> module name, from every source that carries both."""
    out = {}
    for mod in d["modules"]:
        if isinstance(mod, dict) and mod.get("id") and mod.get("name"):
            out[mod["id"]] = mod["name"]
    for group in d["po"].values():
        for rec in group:
            if rec.get("moduleId") and rec.get("module"):
                out.setdefault(rec["moduleId"], rec["module"])
    for perm in d["permissions"]:
        mod = perm.get("module")
        if isinstance(mod, dict) and mod.get("id"):
            out.setdefault(mod["id"], mod.get("_displayName") or mod.get("name"))
    return out


def permission_module(perm, id_to_name):
    mod = perm.get("module")
    if isinstance(mod, dict):
        return (mod.get("_displayName") or mod.get("name")
                or id_to_name.get(mod.get("id")) or "_unattributed")
    if isinstance(mod, str):
        return id_to_name.get(mod, mod)
    return id_to_name.get(perm.get("moduleId"), "_unattributed")


def service_short_module_map(d):
    """short class name (lowercased) -> module, from PermissionedObject service records.

    This is what attributes `/api/modelconfigurations/...` to `Shesha` and
    `/api/clickatell/settings` to `Shesha.Clickatell` without any source access.
    """
    out = {}
    for key in ("shesha-webapi", "shesha-webapi-action"):
        for rec in d["po"][key]:
            obj, module = (rec.get("object") or "").split("@")[0], rec.get("module")
            if obj and module:
                out.setdefault(obj.rsplit(".", 1)[-1].lower(), module)
    return out


def entity_class_module_map(d):
    """entity class name (lowercased) -> module. Attributes the dynamic CRUD services that
    have no PermissionedObject row of their own, such as `/api/services/app/module/getall`."""
    out = {}
    for cfg in d["entityconfigs"]:
        name = (cfg.get("className") or "").lower()
        if name and cfg.get("module"):
            out.setdefault(name, cfg["module"])
    return out


def namespace_module_map(d):
    """Longest-prefix namespace -> module, learned from PermissionedObject records.

    PermissionedObject rows carry both the full type name and the owning module, which makes
    them the only reliable way to attribute an endpoint whose route segment says nothing
    about its module.
    """
    out = {}
    for key in ("shesha-webapi", "shesha-webapi-action"):
        for rec in d["po"][key]:
            obj, module = rec.get("object") or "", rec.get("module")
            if not module:
                continue
            cls = obj.split("@")[0]
            if "." in cls:
                out.setdefault(cls, module)
                out.setdefault(cls.rsplit(".", 1)[0], module)
    return out


def module_of_namespace(full, ns_map):
    best, best_len = None, 0
    for prefix, module in ns_map.items():
        if full == prefix or full.startswith(prefix + "."):
            if len(prefix) > best_len:
                best, best_len = module, len(prefix)
    return best


# --------------------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------------------

def index_actions(records):
    """(service_short, method) -> record, and full-object -> record."""
    by_pair, by_object = {}, {}
    for rec in records:
        obj = rec.get("object") or ""
        by_object[obj.lower()] = rec
        if "@" in obj:
            cls, meth = obj.rsplit("@", 1)
            by_pair[(cls.split(".")[-1].lower(), meth.lower())] = rec
    return by_pair, by_object


def source_service_index(source):
    """service file/class -> its code authorization attributes, from source_scan.json."""
    out = {}
    if not source:
        return out
    for finding in source.get("findings", []):
        if finding.get("check") != "C1-C6":
            continue
        for svc in finding.get("services", []):
            key = os.path.basename(svc["file"])[:-3].lower()
            out[key] = svc
    return out


def resolve_endpoint_auth(path, action, by_pair, by_object, default_access, src_svc):
    """The effective access for one endpoint, per references/enforcement-rules.md."""
    m = SVC_RE.match(path)
    rec = None
    if m:
        # Route names and record names diverge - see lookup_action_record. Matching only the
        # exact name reports the eight AllowAnonymous workflow methods as AnyAuthenticated.
        rec = lookup_action_record(m.group(2), m.group(3), by_pair)
    code_attrs = []
    svc_info = None
    if m:
        for cand in (m.group(2).lower(), m.group(2).lower() + "appservice",
                     m.group(2).lower() + "controller"):
            if cand in src_svc:
                svc_info = src_svc[cand]
                break
    if svc_info:
        code_attrs = [{"attribute": a["attr"], "args": a["args"],
                       "at": "%s:%d" % (svc_info["file"], a["line"])}
                      for a in svc_info.get("authAttributes", [])]

    if rec is None:
        rules = {"effectiveAccess": default_access,
                 "effectiveAccessName": ACCESS.get(default_access, "unknown"),
                 "permissions": [], "recordAccess": None, "hardcoded": None,
                 "resolvedVia": "DefaultEndpointAccess (no PermissionedObject row)",
                 "codeAttributes": code_attrs}
        method = "code" if code_attrs else "none"
        return rules, method, False, None

    actual = rec.get("actualAccess")
    if actual == 2:
        # An Inherited record decides nothing: the global default does. Reporting this as
        # "configuration" would suggest someone chose it, and nobody did.
        rules = {"effectiveAccess": default_access,
                 "effectiveAccessName": ACCESS.get(default_access, "unknown"),
                 "permissions": [], "recordAccess": actual,
                 "hardcoded": bool(rec.get("hardcoded")),
                 "resolvedVia": "record is Inherited -> DefaultEndpointAccess",
                 "codeAttributes": code_attrs}
        return rules, ("code" if code_attrs else "none"), True, rec
    else:
        rules = {"effectiveAccess": actual,
                 "effectiveAccessName": ACCESS.get(actual, "unknown"),
                 "permissions": list(rec.get("actualPermissions") or []),
                 "recordAccess": rec.get("access"),
                 "hardcoded": bool(rec.get("hardcoded")),
                 "resolvedVia": "PermissionedObject (%s)" % rec.get("type"),
                 "codeAttributes": code_attrs}
    if rec.get("hardcoded"):
        method = "both" if code_attrs else "code"
    else:
        method = "both" if code_attrs else "configuration"
    return rules, method, True, rec


def _segments_in_order(module, unit):
    """True if the module's dotted segments appear, in order, within the unit's."""
    it = iter(unit.split("."))
    return all(seg in it for seg in module.split("."))


def module_covered(module, units, known):
    """True if a scanned .NET unit belongs to this module: the known module whose segments
    appear in order in the unit's name, longest wins.

    Shesha.Application -> Shesha; Shesha.Enterprise.Application -> Shesha.Enterprise;
    Shesha.Sms.Clickatell -> Shesha.Clickatell.
    """
    for unit in units:
        best = max((k for k in known if unit.split(".")[0] == k.split(".")[0]
                    and _segments_in_order(k, unit)),
                   key=lambda k: len(k.split(".")), default=None)
        if best == module:
            return True
    return False


def not_scanned_for(module, owner, d, known):
    """Imported packages whose unscanned source could be calling a package-owned object:
    every imported front-end package that was not scanned, plus the owning module itself
    when none of its projects were. Empty for app-owned rows - the app is always scanned."""
    if owner != "package" or not module or module.startswith("_"):
        return []
    out = list(d["pkgNotScanned"])
    if not module_covered(module, d["pkgUnitsScanned"], known):
        out.append(module)
        d["pkgModulesNotScanned"].add(module)
    return out


def recommend_endpoint(ep):
    """Heuristic disposition. The review phase confirms or overrides every one."""
    access = ep["authorizationRules"]["effectiveAccess"]
    sens = ep["sensitivity"]["rating"]
    write = ep["isWriteOperation"]
    if is_keep_infra(ep["path"]):
        return "KEEP-INFRA", "framework infrastructure the SPA calls indirectly"
    if access == 5:
        return ("SET-EXPLICIT-ACCESS",
                "resolves to AllowAnonymous%s" % (" and is a write operation" if write else ""))
    if access == 1:
        return "KEEP", "already disabled"
    if access == 4 and not ep["authorizationRules"]["permissions"]:
        return ("FIX-EMPTY-PERMISSION-SET",
                "RequiresPermissions with no permission named - denies everyone, admins too")
    if ep["referenceIndeterminate"]:
        return "REVIEW", "an opaque reference could reach it; usage cannot be established"
    if ep["isUnreferenced"] and ep["packageSourcesNotScanned"]:
        return ("REVIEW", "nothing scanned calls it, but the source of %s was not scanned - "
                "its own screens may call this" % ", ".join(ep["packageSourcesNotScanned"]))
    backend_refs = ep["backendCodeReferences"] + ep["packageBackendCodeReferences"]
    if ep["isUnreferenced"] and backend_refs == 0:
        return ("DISABLE-ENDPOINT" if write else "RESTRICT",
                "nothing in the scanned front-end or back-end source calls it")
    if ep["isUnreferenced"]:
        return ("RESTRICT",
                "no front-end caller, but %s back-end source uses the service" % (
                    "this repository's" if ep["backendCodeReferences"] else
                    "framework/Enterprise"))
    if access == 3 and (sens == "HIGH" or write):
        return ("RESTRICT",
                "any authenticated user can call it and it %s"
                % ("changes state" if write else "returns sensitive data"))
    return "KEEP", "referenced, and access is at least authenticated"


def entity_of_service(short_service, full_by_short):
    """The entity a service is named after, so row-level filtering can be reported for it.

    `LeaveRequestAppService` -> `Shesha.Leave.Domain.LeaveRequest`. Returns None when no
    entity matches, and None must be reported as "not determined", never as "no filter".
    """
    stem = short_service
    for suffix in ("AppService", "CrudAppService", "Controller", "Service"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return full_by_short.get(stem.lower())


def attribute_endpoint(path, rec, service, maps):
    """Which package owns this endpoint. First hit wins, strongest evidence first.

    Returns (module, how). `how` is recorded so a wrong attribution can be traced rather
    than argued about - an endpoint filed under the wrong package is a recommendation sent
    to the wrong team.
    """
    if rec and rec.get("module"):
        return rec["module"], "PermissionedObject record"
    if rec:
        module = module_of_namespace((rec.get("object") or "").split("@")[0], maps["ns"])
        if module:
            return module, "namespace prefix of the PermissionedObject record"
    svc = (service or "").lower()
    for cand in (svc, svc + "appservice", svc + "controller"):
        if cand in maps["shortService"]:
            return maps["shortService"][cand], "service class name seen in another record"
    if svc in maps["entityClass"]:
        return maps["entityClass"][svc], "dynamic CRUD service for an entity of that name"
    for cand in (svc, svc + "appservice", svc + "controller"):
        if cand in maps["source"]:
            rel = maps["source"][cand]["file"]
            for prefix, module in maps["proj"].items():
                if rel.startswith(prefix + "/"):
                    return module, "declared in %s" % prefix
    # A hand-routed controller, matched on the longest declared route prefix.
    best = None
    for prefix, info in maps["routePrefix"].items():
        if path.startswith(prefix + "/") or path == prefix:
            if info["module"] and (best is None or len(prefix) > len(best[0])):
                best = (prefix, info)
    if best:
        return best[1]["module"], "route prefix declared in %s" % best[1]["file"]

    # The OpenAPI tag is the declaring controller or service name. It is the only clue for a
    # root-level route such as `/ReplaceValueInFormConfigsThroughoutModule`, and those are
    # the endpoints most likely to be missed entirely.
    for tag in maps["pathTags"].get(path, ()):
        for cand in (tag.lower(), tag.lower() + "appservice", tag.lower() + "controller"):
            if cand in maps["shortService"]:
                return maps["shortService"][cand], "OpenAPI tag '%s'" % tag

    m = SVC_RE.match(path)
    if m and m.group(1).lower() in maps["segment"]:
        module = maps["segment"][m.group(1).lower()]
        if module:
            return module, "URL segment registered by that module"
    # Last resort: the type's namespace root is itself a known module name. Weak, so it is
    # labelled as such - `Shesha.Services.NHibernateAppService` -> `Shesha`.
    if rec:
        cls = (rec.get("object") or "").split("@")[0]
        best = None
        for known in maps["known"]:
            if cls == known or cls.startswith(known + "."):
                if best is None or len(known) > len(best):
                    best = known
        if best:
            return best, "namespace root matches a known module name (weak)"
    return None, "unattributed"


def build_endpoints(d, refs, src_refs, maps, display_paths):
    default_access = d["security"].get("defaultEndpointAccess")
    by_pair, by_object = index_actions(d["po"]["shesha-webapi-action"])
    src_svc = source_service_index(d["source"])
    surface = d["surface"] or {}
    referenced = (d["crossref"] or {}).get("referenced") or {}
    indeterminate = set((d["crossref"] or {}).get("indeterminate") or [])
    pkg_evidence = (d["crossref"] or {}).get("packageEvidence") or {}
    pkg_services = (d["packageSources"] or {}).get("serviceMentions") or {}
    probe_by_path = {}
    for r in ((d["probes"] or {}).get("results") or []):
        probe_by_path.setdefault(r["path"].split("?")[0].lower(), []).append(
            {"principal": r["principal"], "status": r["status"], "verdict": r["verdict"]})

    out = collections.defaultdict(list)
    for path in sorted(surface):
        if DYN_RE.match(path):
            continue  # dynamic entity CRUD is catalogued in {package}-entities.json
        m = SVC_RE.match(path)
        segs = [s for s in path.strip("/").split("/") if s]
        # /api/services/{mod}/{Service}/{Action} for app services; hand-routed controllers
        # are /api/{Controller}/{Action} and anything shorter is a bare route.
        service = m.group(2) if m else (segs[1] if len(segs) > 2 else
                                        segs[-1] if segs else path)
        action = m.group(3) if m else (segs[-1] if len(segs) > 1 else "")
        rules, method, has_po, rec = resolve_endpoint_auth(
            path, action, by_pair, by_object, default_access, src_svc)

        module, how = attribute_endpoint(path, rec, service, maps)
        owner = d["ownership"].of_path(path)
        if module is None:
            module = "_unattributed" if owner == "package" else "_app-unattributed"
        if module in d["appModules"]:
            owner = "app"

        shown = display_paths.get(path, path)
        shown_segs = [s for s in shown.strip("/").split("/") if s]
        service_class = (rec.get("object") or "").split("@")[0] if rec else service
        short_service = service_class.rsplit(".", 1)[-1]
        spec_entity = entity_of_service(short_service, maps["entityFullByShort"])
        spec_state = (spec_entity in src_refs["globalSpecEntities"]) if spec_entity else None
        forms = sorted(refs["endpointToForms"].get(path, ()))
        coded = sorted(refs["endpointToFiles"].get(path, ()))
        ep = {
            "path": shown,
            "matchKey": path,
            "attributedBy": how,
            "methods": surface[path],
            "service": service_class,
            "action": (rec.get("object") or "").rsplit("@", 1)[-1] if rec and "@" in (
                rec.get("object") or "") else (shown_segs[-1] if shown_segs else action),
            "owner": owner,
            "module": module,
            "isWriteOperation": is_write(action) or any(
                v in ("POST", "PUT", "DELETE", "PATCH") for v in surface[path]),
            # Belt and braces: crossref's `referenced` set is the authority, but a direct
            # form or coded-file hit counts too, in case the two were generated from
            # different snapshots.
            "isUnreferenced": path not in referenced and not forms and not coded,
            "referencedBy": sorted(referenced.get(path, ())),
            "referencedByForms": forms,
            "referencedByCustomForms": coded,
            "referencedByPackageSource": pkg_evidence.get(path, []),
            "referenceIndeterminate": path in indeterminate,
            "hasPermissionedObjectConfig": has_po,
            "authorizationRules": rules,
            "authorizationMethod": method,
            "grantedToRoles": sorted({r for p in rules["permissions"]
                                      for r in refs["permToRoles"].get(p, ())}),
            # Resolved from the entity the service is named after, where one exists. null
            # means "no entity could be matched", which is not the same as "no filter" -
            # reporting False there would claim a check that was never made.
            "hasGlobalSpecifications": spec_state,
            "specificationEntity": spec_entity,
            "backendCodeReferences": src_refs["service"].get(short_service, 0),
            "backendCodeFiles": src_refs["serviceFiles"].get(short_service, []),
            "packageBackendCodeReferences":
                (pkg_services.get(short_service) or {}).get("count", 0),
            "packageBackendCodeFiles": (pkg_services.get(short_service) or {}).get("files", []),
            "probeResults": probe_by_path.get(path, []),
            "sensitivity": sensitivity_of(service, action),
        }
        # A live anonymous probe outranks every record lookup. If an unauthenticated request
        # reached business logic, the endpoint IS anonymously reachable whatever the record
        # says - and "NOT-FOUND from a synthetic id" is reached, not denied.
        anon = [p for p in ep["probeResults"]
                if p["principal"] == "anonymous"
                and p["verdict"] in ("OPEN", "REACHED", "NOT-FOUND")]
        if anon and ep["authorizationRules"]["effectiveAccess"] != 5:
            ep["authorizationRules"]["effectiveAccessBeforeProbe"] = \
                ep["authorizationRules"]["effectiveAccessName"]
            ep["authorizationRules"]["effectiveAccess"] = 5
            ep["authorizationRules"]["effectiveAccessName"] = "AllowAnonymous"
            ep["authorizationRules"]["resolvedVia"] = (
                "OBSERVED: anonymous probe returned %s (%s). This outranks the "
                "PermissionedObject lookup." % (anon[0]["status"], anon[0]["verdict"]))
            ep["observedAnonymous"] = True

        ep["packageSourcesNotScanned"] = not_scanned_for(module, ep["owner"], d, maps["known"])
        ep["recommendedAction"], ep["recommendationBasis"] = recommend_endpoint(ep)
        out[module].append(ep)
    return out


# --------------------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------------------

CRUD_LETTER = {"get": "R", "getall": "R", "query": "R", "queryall": "R",
               "create": "C", "creategql": "C", "update": "U", "updategql": "U",
               "delete": "D"}


def attribute_entity(cfg, full, maps):
    """Which package owns an entity. `EntityConfig.module` is authoritative when set.

    It is null for the ~38 ABP framework entities (`Abp.Authorization.Users.UserRole` and
    friends), and those are the identity tables that matter most - leaving them in
    `_unattributed` buries the privilege-escalation surface.
    """
    if cfg.get("module"):
        return cfg["module"], "EntityConfig.module"
    best = None
    for known in maps["known"]:
        if full.startswith(known + "."):
            if best is None or len(known) > len(best):
                best = known
    if best:
        return best, "namespace root matches a known module name"
    ns = (cfg.get("namespace") or full).split(".")[0]
    if ns in ("Abp", "Microsoft", "System"):
        # ABP's own entities reach this application only because the Shesha packages bundle
        # ABP, and they are fixed the same way any Shesha package endpoint is: a
        # PermissionedObject row. Filing them under Shesha is where the remediation lands.
        return "Shesha", "ABP framework entity, reaches this app via the Shesha packages"
    return "_unattributed", "EntityConfig.module is null and the namespace matched nothing"


def recommend_entity(ent):
    access = ent["authorizationRules"]["effectiveAccess"]
    sens = ent["sensitivity"]["rating"]
    if access == 5:
        return ("SET-EXPLICIT-ACCESS",
                "entity CRUD resolves to AllowAnonymous - anyone can read and write it")
    if not ent["CRUDEndpoints"]:
        return "KEEP", "no live dynamic CRUD route"
    if ent["referenceIndeterminate"]:
        return "REVIEW", "an opaque reference could reach it; usage cannot be established"
    if (ent["isUnreferenced"] or ent["unreferencedWriteActions"]) and \
            ent.get("packageSourcesNotScanned"):
        return ("REVIEW", "no scanned caller, but the source of %s was not scanned - its "
                "own screens may use this entity's API"
                % ", ".join(ent["packageSourcesNotScanned"]))
    if ent["isUnreferenced"] and ent["backendCodeReferences"] == 0:
        return ("DISABLE-ENTITY",
                "no form, coded screen or back-end source reference to this entity")
    if ent["isUnreferenced"]:
        return ("DISABLE-ENTITY",
                "no front-end reference; back-end code uses the entity but not its API "
                "(confirm no integration calls it)")
    if ent["unreferencedWriteActions"] and not ent["isUnreferenced"]:
        return ("DISABLE-ACTION",
                "read is used but %s unreferenced"
                % ", ".join(ent["unreferencedWriteActions"]))
    if sens in ("HIGH", "MEDIUM") and not ent["hasGlobalSpecifications"] and access == 3:
        return ("ADD-GLOBAL-SPECIFICATION",
                "any authenticated user can list every row and there is no row-level filter")
    if access == 3 and sens == "HIGH":
        return "RESTRICT", "any authenticated user can reach personal data"
    return "KEEP", "referenced, and access is at least authenticated"


def build_entities(d, refs, src_refs, display_paths, maps):
    default_access = d["security"].get("defaultEndpointAccess")
    ent_actions = (d["crossref"] or {}).get("entActions") or {}
    referenced = (d["crossref"] or {}).get("referenced") or {}
    indeterminate = set((d["crossref"] or {}).get("indeterminate") or [])
    ent_po = {(r.get("object") or "").lower(): r for r in d["po"]["shesha-entity"]}
    ent_act_po = collections.defaultdict(dict)
    for rec in d["po"]["shesha-entity-action"]:
        obj = (rec.get("object") or "")
        if "@" in obj:
            cls, act = obj.rsplit("@", 1)
            ent_act_po[cls.lower()][act.lower()] = rec
    ent_perms = d["entityPermissions"] or {}
    declared_disable = set()
    for finding in ((d["source"] or {}).get("findings") or []):
        if finding.get("check") == "D1-D5":
            for e in finding.get("withDisabledAppService", []):
                declared_disable.add(e["file"])

    # short entity name -> live dynamic CRUD base(s)
    base_by_short = collections.defaultdict(list)
    for base in ent_actions:
        base_by_short[base.rsplit("/", 2)[-2].lower()].append(base)

    out = collections.defaultdict(list)
    for cfg in d["entityconfigs"]:
        full = cfg.get("fullClassName")
        if not full:
            continue
        module, attributed_by = attribute_entity(cfg, full, maps)
        short = (cfg.get("className") or full.rsplit(".", 1)[-1]).lower()
        bases = base_by_short.get(short, [])
        actions, letters, unref_actions, unref_writes = {}, [], [], []
        for base in bases:
            for act in ent_actions.get(base, []):
                url = base + "/" + act
                used = url in referenced
                actions[act] = {"url": display_paths.get(url, url),
                                "referenced": used,
                                "referencedBy": sorted(referenced.get(url, ()))}
                letter = CRUD_LETTER.get(act.lower())
                if letter and letter not in letters:
                    letters.append(letter)
                if not used:
                    unref_actions.append(act)
                    if CRUD_LETTER.get(act.lower()) in ("C", "U", "D"):
                        unref_writes.append(act)

        rec = ent_po.get(full.lower())
        act_recs = ent_act_po.get(full.lower(), {})
        cfg_perms = ent_perms.get(full) or {}
        declared_perms = {k: v for k, v in cfg_perms.items()
                          if k.startswith("permission") and v}
        if rec and rec.get("actualAccess") not in (None, 2):
            rules = {"effectiveAccess": rec.get("actualAccess"),
                     "effectiveAccessName": ACCESS.get(rec.get("actualAccess"), "unknown"),
                     "permissions": list(rec.get("actualPermissions") or []),
                     "resolvedVia": "PermissionedObject (Shesha.Entity)",
                     "hardcoded": bool(rec.get("hardcoded"))}
            method = "configuration"
        elif act_recs:
            first = list(act_recs.values())[0]
            rules = {"effectiveAccess": first.get("actualAccess"),
                     "effectiveAccessName": ACCESS.get(first.get("actualAccess"), "unknown"),
                     "permissions": list(first.get("actualPermissions") or []),
                     "resolvedVia": "PermissionedObject (Shesha.Entity.Action)",
                     "hardcoded": bool(first.get("hardcoded")),
                     "perAction": {a: {"access": r.get("actualAccess"),
                                       "accessName": ACCESS.get(r.get("actualAccess"), "?"),
                                       "permissions": list(r.get("actualPermissions") or [])}
                                   for a, r in act_recs.items()}}
            method = "configuration"
        else:
            rules = {"effectiveAccess": default_access,
                     "effectiveAccessName": ACCESS.get(default_access, "unknown"),
                     "permissions": [],
                     "resolvedVia": "no Shesha.Entity or Shesha.Entity.Action row -> "
                                    "EntityCrudAuthorizationHelper falls back to "
                                    "DefaultEndpointAccess",
                     "hardcoded": False}
            method = "configuration" if declared_perms else "none"
        if declared_perms:
            rules["entityConfigPermissions"] = declared_perms

        specs = src_refs["specEntities"].get(full, [])
        form_refs = sorted(refs["entityToForms"].get(full, ()))
        coded_refs = sorted(refs["entityToFiles"].get(full, ()))
        any_indeterminate = any((base + "/" + act) in indeterminate
                                for base in bases for act in ent_actions.get(base, []))

        ent = {
            "entity": full,
            "className": cfg.get("className"),
            "module": module,
            "attributedBy": attributed_by,
            "owner": "app" if module in d["appModules"] else "package",
            "tableName": cfg.get("tableName"),
            "generateAppService": cfg.get("generateAppService"),
            "declaredDisableGenerateApplicationService": any(
                full.rsplit(".", 1)[-1] in f for f in declared_disable),
            "CRUDEndpoints": "".join(sorted(set(letters), key="CRUD".index)),
            "crudActions": actions,
            "unreferencedActions": sorted(unref_actions),
            "unreferencedWriteActions": sorted(unref_writes),
            "isUnreferenced": bool(bases) and not any(a["referenced"]
                                                      for a in actions.values())
                              and not form_refs and not coded_refs,
            "referencedByForms": form_refs,
            "referencedByCustomForms": coded_refs,
            "referenceIndeterminate": any_indeterminate,
            "backendCodeReferences": src_refs["entity"].get(full, 0),
            "backendCodeFiles": src_refs["entityFiles"].get(full, []),
            "hasPermissionedObjectConfig": bool(rec or act_recs),
            "authorizationRules": rules,
            "authorizationMethod": method,
            "grantedToRoles": sorted({r for p in rules["permissions"]
                                      for r in refs["permToRoles"].get(p, ())}),
            "hasGlobalSpecifications": full in src_refs["globalSpecEntities"],
            "specifications": specs,
            "sensitivity": sensitivity_of(full, cfg.get("className") or ""),
        }
        ent["packageSourcesNotScanned"] = not_scanned_for(module, ent["owner"], d,
                                                          maps["known"])
        ent["recommendedAction"], ent["recommendationBasis"] = recommend_entity(ent)
        out[module].append(ent)
    return out


# --------------------------------------------------------------------------------------
# Forms
# --------------------------------------------------------------------------------------

def menu_form_refs(mainmenu):
    """Form names and URLs the main menu points at.

    A landing page is usually referenced by nothing except the menu, so without this every
    top-level page in the application looks unreferenced.
    """
    names, urls, raw = set(), set(), json.dumps(mainmenu or {})
    for m in re.finditer(r'"formId"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"', raw):
        names.add(m.group(1))
    for m in re.finditer(r'"name"\s*:\s*"([^"]+)"\s*,\s*"module"\s*:\s*"([^"]+)"', raw):
        names.add(m.group(1))
    for m in re.finditer(r'"url"\s*:\s*"([^"]+)"', raw):
        urls.add(m.group(1))
        parts = [p for p in m.group(1).split("?")[0].strip("/").split("/") if p]
        if parts:
            names.add(parts[-1])
    return names, urls


def build_configured_forms(d, refs, menu_names):
    per_form = (d["forms"] or {}).get("perForm") or {}
    form_po = {(r.get("object") or "").lower(): r for r in d["po"]["shesha-form"]}
    coded_form_refs = refs["formToFiles"]
    pkg_form_refs = {}
    for k, evs in ((d["packageSources"] or {}).get("forms") or {}).items():
        pkg_form_refs.setdefault(k.lower(), []).extend(
            "%s-%s: %s" % (e["source"], e["kind"], e["file"]) for e in evs)
    out = collections.defaultdict(list)
    for key, rec in sorted(per_form.items()):
        module = rec.get("module") or "_unattributed"
        name = rec.get("name") or ""
        po = form_po.get(("%s.%s" % (module, name)).lower())
        endpoints = [{"url": u, "resolved": True} for u in sorted(rec["endpoints"])]
        for o in rec["opaque"]:
            endpoints.append({"resolved": False, "opaque": True,
                              "reason": o["reason"], "markupKey": o["markupKey"],
                              "snippet": o["snippet"], "guessedUrl": o["guessedUrl"]})
        in_menu = name in menu_names
        by_form = rec.get("referencedByForms") or []
        by_code = sorted(set(coded_form_refs.get(key, ()))
                         | set(coded_form_refs.get("?/" + name, ())))
        by_pkg = (pkg_form_refs.get(key.lower(), [])
                  + pkg_form_refs.get(("?/" + name).lower(), []))[:5]
        form = {
            "form": key,
            "module": module,
            "name": name,
            "label": rec.get("label"),
            "modelType": rec.get("modelType"),
            "owner": "app" if module in d["appModules"] else "package",
            "isUnreferenced": not (in_menu or by_form or by_code or by_pkg),
            "isReferencedByMainMenu": in_menu,
            "isReferencedByOtherForm": bool(by_form),
            "isReferencedByCustomForm": bool(by_code),
            "referencedByForms": by_form,
            "referencedByCustomForms": by_code,
            "referencedByPackageSource": by_pkg,
            "endPointsReferenced": endpoints,
            "formsReferenced": sorted(rec["forms"]),
            "entitiesReferenced": sorted(rec["entities"]),
            "referenceListsReferenced": sorted(rec["reflists"]),
            "ownerBindings": sorted(rec["owners"]),
            "permissionsReferenced": sorted(rec["permissions"]),
            "staleEndpoints": sorted(rec["staleEndpoints"]),
            "externalUrls": sorted(rec["externalUrls"]),
            "accessConfig": ({"access": po.get("actualAccess"),
                              "accessName": ACCESS.get(po.get("actualAccess"), "unknown"),
                              "permissions": list(po.get("actualPermissions") or []),
                              "hardcoded": bool(po.get("hardcoded"))}
                             if po else None),
            "hasPermissionedObjectConfig": po is not None,
            "sensitivity": sensitivity_of(name, rec.get("modelType") or ""),
        }
        form["packageSourcesNotScanned"] = not_scanned_for(
            module, form["owner"], d, d["knownModules"])
        if po and po.get("actualAccess") == 5:
            form["recommendedAction"] = "SET-EXPLICIT-ACCESS"
            form["recommendationBasis"] = ("the form is configured AllowAnonymous - anyone "
                                           "can open it without logging in")
        elif form["isUnreferenced"] and form["packageSourcesNotScanned"]:
            form["recommendedAction"] = "REVIEW"
            form["recommendationBasis"] = (
                "nothing scanned opens it, but the source of %s was not scanned - that "
                "package's own screens may open it by name"
                % ", ".join(form["packageSourcesNotScanned"]))
        elif form["isUnreferenced"] and not rec["opaque"]:
            form["recommendedAction"] = "REVIEW-FOR-REMOVAL"
            form["recommendationBasis"] = ("no menu entry, no other form and no coded screen "
                                           "opens it; it may still be opened by URL")
        elif form["isUnreferenced"]:
            form["recommendedAction"] = "REVIEW"
            form["recommendationBasis"] = "unreferenced, but it contains opaque script"
        else:
            form["recommendedAction"] = "KEEP"
            form["recommendationBasis"] = "reachable from the menu, another form or code"
        out[module].append(form)
    return out


def build_custom_forms(d, refs, menu_names, menu_urls):
    files = (d["frontend"] or {}).get("files") or {}
    out = collections.defaultdict(list)
    for key, rec in sorted(files.items()):
        pkg = rec["package"]
        route = rec.get("route")
        in_menu = bool(route) and (route in menu_urls
                                  or route.strip("/").split("/")[-1] in menu_names)
        by_files = rec.get("referencedByFiles") or []
        endpoints = [{"url": u, "resolved": True}
                     for u in sorted(rec["endpointsReferenced"])]
        for o in rec["opaque"]:
            endpoints.append({"resolved": False, "opaque": True, "reason": o["reason"],
                              "snippet": o["snippet"], "guessedUrl": o["guessedUrl"]})
        item = {
            "file": rec["file"],
            "frontend": rec["frontend"],
            "package": pkg,
            "kind": rec["kind"],
            "route": route,
            "owner": "app",
            "isUnreferenced": not (route or by_files or in_menu),
            "isReferencedByMainMenu": in_menu,
            "isReferencedByOtherForm": bool(by_files),
            "referencedByCustomForms": by_files,
            "endPointsReferenced": endpoints,
            "formsReferenced": sorted(rec["formsReferenced"]),
            "entitiesReferenced": sorted(rec["entitiesReferenced"]),
            "permissionsReferenced": sorted(rec["permissionsReferenced"]),
            "routesDeclared": rec.get("routesDeclared") or [],
            "usesDataHooks": rec.get("usesDataHooks"),
            "sensitivity": sensitivity_of(rec["file"]),
        }
        if item["isUnreferenced"] and rec["kind"] in (
                "component", "screen", "designer-component", "api-module"):
            item["recommendedAction"] = "REVIEW-FOR-REMOVAL"
            item["recommendationBasis"] = ("nothing imports it and it serves no route - dead "
                                           "code, unless it is exported for another package")
        elif route and not rec["endpointsReferenced"] and not rec["formsReferenced"]:
            item["recommendedAction"] = "KEEP"
            item["recommendationBasis"] = "a route with no direct API call of its own"
        else:
            item["recommendedAction"] = "KEEP"
            item["recommendationBasis"] = "routed or imported"
        out[pkg].append(item)
    return out


# --------------------------------------------------------------------------------------
# Roles and permissions
# --------------------------------------------------------------------------------------

def build_roles_permissions(d, refs, src_refs, id_to_name):
    role_grants = ((d["rolePermissions"] or {}).get("roles") or {})
    perm_to_roles = refs["permToRoles"]
    form_refs = (d["forms"] or {}).get("permission_refs") or {}
    code_refs = src_refs["permission"]
    coded_perm_refs = refs["permToFiles"]

    po_web = collections.Counter()
    po_entity = collections.Counter()
    po_form = collections.Counter()
    for key in ("shesha-webapi", "shesha-webapi-action"):
        for rec in d["po"][key]:
            for p in (rec.get("actualPermissions") or []):
                po_web[p] += 1
    for key in ("shesha-entity", "shesha-entity-action", "shesha-webcrudapi",
                "shesha-webcrudapi-action"):
        for rec in d["po"][key]:
            for p in (rec.get("actualPermissions") or []):
                po_entity[p] += 1
    for rec in d["po"]["shesha-form"]:
        for p in (rec.get("actualPermissions") or []):
            po_form[p] += 1
    for cfg in (d["entityPermissions"] or {}).values():
        for field in ("permission", "permissionGet", "permissionCreate", "permissionUpdate",
                      "permissionDelete"):
            val = cfg.get(field)
            names = val if isinstance(val, list) else ([val] if isinstance(val, str) else
                                                       (val or {}).get("permissions")
                                                       if isinstance(val, dict) else None)
            for p in (names or []):
                if isinstance(p, str):
                    po_entity[p] += 1

    per_package = collections.defaultdict(lambda: {"roles": [], "permissions": []})

    for perm in d["permissions"]:
        name = perm.get("name")
        if not name:
            continue
        module = permission_module(perm, id_to_name)
        counts = {
            "numReferencesByFormConfig": len(form_refs.get(name, [])) + po_form.get(name, 0),
            "numReferencesByWebApiConfig": po_web.get(name, 0),
            "numReferencesByEntityConfig": po_entity.get(name, 0),
            "numReferencesByAppServiceCode": code_refs.get(name, {}).get("appservice", 0),
            "numReferencesBySpecificationCode": code_refs.get(name, {}).get("specification", 0),
            "numReferencesByOtherBackendCode": code_refs.get(name, {}).get("other", 0),
            "numReferencesByCustomForm": len(coded_perm_refs.get(name, ())),
        }
        roles = sorted(perm_to_roles.get(name, ()))
        total = sum(counts.values())
        per_package[module]["permissions"].append({
            "permission": name,
            "displayName": perm.get("displayName"),
            "module": module,
            "owner": "app" if module in d["appModules"] else "package",
            "isDbPermission": perm.get("isDbPermission"),
            "parentName": perm.get("parentName"),
            "isUnreferenced": total == 0,
            "guardsNothing": counts["numReferencesByWebApiConfig"] == 0
                             and counts["numReferencesByEntityConfig"] == 0
                             and counts["numReferencesByFormConfig"] == 0,
            "rolesAssignedTo": roles,
            "totalReferences": total,
            "recommendedAction": (
                "REMOVE-OR-WIRE-UP" if total == 0 and not roles else
                "GRANT-TO-A-ROLE" if total and not roles else
                "REVIEW" if total == 0 else "KEEP"),
            "recommendationBasis": (
                "nothing references it and no role holds it - it is dead configuration"
                if total == 0 and not roles else
                "roles hold it but nothing is guarded by it, so holding it grants nothing"
                if total == 0 else
                "it guards something but no role holds it, so the guarded object is "
                "unreachable by anyone except through another permission"
                if not roles else "in use"),
        })
        per_package[module]["permissions"][-1].update(counts)

    for role in d["roles"]:
        rid = role.get("id")
        grant = role_grants.get(rid) or {}
        module = id_to_name.get(role.get("module") or role.get("moduleId"), "_unattributed")
        perms = grant.get("permissions") or role.get("permissions") or []
        per_package[module]["roles"].append({
            "role": (role.get("name") or "").strip(),
            "id": rid,
            "module": module,
            "description": role.get("description"),
            "permissions": sorted(perms),
            "permissionCount": len(perms),
            "grantsResolved": bool(grant.get("resolved", False)),
            "holdsNoPermissions": not perms,
            "recommendedAction": "REVIEW" if not perms else "KEEP",
            "recommendationBasis": (
                "the role grants no permissions, so assigning it changes nothing - either "
                "it is unused or its permissions were never configured"
                if not perms else "in use"),
        })
    return per_package


# --------------------------------------------------------------------------------------
# Other findings
# --------------------------------------------------------------------------------------

STARTUP_SEVERITY = {
    "A9-auth-filter": ("CRITICAL", "absent"),
    "A11-elmah": ("CRITICAL", "present-unguarded"),
    "A2-cors-wildcard": ("HIGH", "present"),
    "A3-cors-credentials": ("HIGH", "present"),
    "A2+A3": ("CRITICAL", "present"),
    "A4-graphql-playground": ("HIGH", "present-unguarded"),
    "A5-swagger-ui": ("MEDIUM", "present-unguarded"),
    "A5-swagger": ("MEDIUM", "present-unguarded"),
    "A6-security-headers": ("MEDIUM", "absent"),
    "A7-csp": ("MEDIUM", "absent"),
    "A8-hsts": ("MEDIUM", "absent"),
    "A10-hangfire": ("HIGH", "present-unguarded"),
    "A12-env-guard": ("HIGH", "absent"),
    "A1-cors-origins": ("HIGH", "absent"),
    "B1-jwt-key": ("CRITICAL", "present"),
    "B2-passphrase": ("HIGH", "absent"),
    "B4-conn-password": ("HIGH", "present"),
    "B5-smtp": ("HIGH", "present"),
}


def package_for_file(rel, proj_modules, frontends):
    r = (rel or "").replace("\\", "/")
    for prefix, module in proj_modules.items():
        if r.startswith(prefix + "/"):
            return module
    for front in frontends:
        if r.startswith(front + "/"):
            return front
    return "_repository"


def build_other_findings(d, proj_modules, frontends):
    out = collections.defaultdict(list)
    fid = collections.Counter()

    def add(package, category, title, severity_hint, evidence, recommendation,
            status="FAIL"):
        fid[package] += 1
        out[package].append({
            "id": "%s-%d" % (category[:3].upper(), fid[package]),
            "category": category,
            "title": title,
            "severityHint": severity_hint,
            "status": status,
            "evidence": evidence,
            "recommendationHint": recommendation,
            "reviewRequired": True,
        })

    for finding in ((d["source"] or {}).get("findings") or []):
        check = finding.get("check")
        if check in STARTUP_SEVERITY and "found" in finding:
            severity, bad_when = STARTUP_SEVERITY[check]
            found = finding["found"]
            is_bad = (found and bad_when.startswith("present")) or \
                     (not found and bad_when == "absent")
            if not is_bad:
                continue
            pkg = package_for_file(finding.get("file"), proj_modules, frontends)
            locs = ["%s:%s" % (finding.get("file"), l["line"])
                    for l in finding.get("locations", [])[:4]] or [finding.get("file")]
            add(pkg, "web-host-configuration" if check.startswith("A")
                else "settings-and-secrets",
                "%s (%s)" % (finding.get("label"), check), severity, locs,
                "See references/app-vulnerability-baseline.md section %s and "
                "references/remediation-guide.md." % check[0])
        if check == "C1-C6":
            for svc in finding.get("services", []):
                if svc["hasAnyAuthAttribute"] or not svc["isControllerBase"]:
                    continue
                pkg = package_for_file(svc["file"], proj_modules, frontends)
                add(pkg, "controller-without-authorization",
                    "%s is a hand-routed controller with no authorization attribute"
                    % os.path.basename(svc["file"]), "HIGH",
                    ["%s (%d endpoints)" % (svc["file"], len(svc["httpEndpoints"]))],
                    "A hand-routed controller has no per-action PermissionedObject row to "
                    "tighten, so this must be fixed in source: add [SheshaAuthorize].")
        if check == "D5-specifications" and not finding.get("found"):
            add("_repository", "row-level-security",
                "No global specifications anywhere in the application", "HIGH",
                ["backend/src (no ShaSpecification<T> or [GlobalSpecification])"],
                "Every authenticated user sees every row of every entity. See "
                "references/remediation-guide.md, 'Restricting rows'.")

    for finding in ((d["posture"] or {}).get("findings") or []):
        check = finding.get("check", "")
        verdict = finding.get("verdict") or ""
        # A posture scan run against a backend that was not up records T0 and then assesses
        # nothing. Without this row the token findings simply vanish from the catalogue,
        # which reads as "checked and clean" - the one failure mode this audit must not have.
        if check.startswith("T0"):
            add("_repository", "token-policy",
                "Token and session policy was NOT assessed", "INFO",
                ["could not authenticate: HTTP %s. %s"
                 % (finding.get("status"), finding.get("note") or "")],
                "Re-run posture_scan.py with the backend up. Token lifetime, signing-key "
                "strength and whether SignOff invalidates are all unknown until then.",
                status="SKIP")
        if check.startswith("T2") and verdict in ("TOO-SHORT", "LOW-ENTROPY"):
            add("_repository", "token-policy", "JWT signing key is weak (%s)" % verdict,
                "CRITICAL", [finding.get("note")],
                "Replace the key with 32+ random bytes supplied per environment, then "
                "rotate. See references/remediation-guide.md, 'Rotating the signing key'.")
        if check.startswith("T3") and verdict == "TOKEN-STILL-VALID-AFTER-SIGNOFF":
            add("_repository", "token-policy",
                "A token stays valid after SignOff", "MEDIUM",
                ["probe %s: before=%s after=%s" % (finding.get("probe"),
                                                   finding.get("beforeStatus"),
                                                   finding.get("afterStatus"))],
                "Shorten the token lifetime; a stateless JWT cannot be revoked.")
        if check.startswith("T1") and (finding.get("lifetimeHours") or 0) > 24:
            add("_repository", "token-policy",
                "Token lifetime is %s hours" % finding.get("lifetimeHours"), "MEDIUM",
                ["alg=%s" % finding.get("alg")],
                "Reduce to hours. A leaked token is usable for its whole lifetime.")
        if check.startswith("R1") and verdict == "NONE-CONFIGURED":
            add("_repository", "rate-limiting",
                "No rate limiting and no account lockout is configured", "HIGH",
                [json.dumps(finding.get("hits") or {})[:300]],
                "Add ASP.NET rate limiting and enable account lockout. See "
                "references/remediation-guide.md, 'Rate limiting and lockout'.")
        if check.startswith("G1") and finding.get("count"):
            for hit in finding.get("hits", [])[:20]:
                pkg = package_for_file(hit.get("file"), proj_modules, frontends)
                add(pkg, "committed-secret",
                    "%s in tracked configuration" % hit.get("pattern"), "HIGH",
                    # Location, length and a fingerprint - never the value. This report is
                    # the artefact most likely to be shared beyond the repository.
                    ["%s:%s (%d chars, %s)"
                     % (hit.get("file"), hit.get("line"), hit.get("length"),
                        hit.get("fingerprint") or "no fingerprint recorded")],
                    "Move it to per-environment configuration and ROTATE it - removing the "
                    "line leaves it in git history.")
        if check.startswith("D1") and finding.get("count"):
            add("_repository", "dependency-advisory",
                "%d vulnerable NuGet package(s)" % finding.get("count"), "MEDIUM",
                ["%s %s (%s)" % (p["package"], p["resolved"], p["severity"])
                 for p in finding.get("packages", [])[:12]],
                "Upgrade the direct runtime dependencies first; separate build-only "
                "advisories from runtime ones before rating this.")
        if check.startswith("D2"):
            summary = finding.get("summary") or {}
            bad = sum(v for k, v in summary.items()
                      if k in ("critical", "high") and isinstance(v, int))
            if verdict == "TOOL-UNAVAILABLE":
                add(finding.get("frontend") or "_repository", "dependency-advisory",
                    "npm audit did not run", "INFO", [finding.get("note")],
                    "Run it manually; a tool-not-found is not a clean result.",
                    status="SKIP")
            elif bad:
                add(finding.get("frontend") or "_repository", "dependency-advisory",
                    "%d critical/high npm advisories" % bad, "MEDIUM",
                    [json.dumps(summary)],
                    "Separate runtime from build-only packages before rating.")
        if check.startswith("D") and finding.get("skipped"):
            add("_repository", "dependency-advisory",
                "Dependency scan skipped (%s)" % check, "INFO",
                ["--skip-deps was passed"], "Re-run without --skip-deps.", status="SKIP")

    probes = d["probes"] or {}
    # Default credentials are a finding in their own right, and one that lives only in the
    # probe output. Without this row it reaches the report only if someone remembers it.
    if probes.get("defaultCredentialsUntested"):
        add("_repository", "default-credentials",
            "Whether the default administrator password still works was NOT tested",
            "INFO", ["the backend did not answer the authentication probe"],
            "Re-run with the backend up. An untested check is not a pass.", status="SKIP")
    elif probes.get("defaultCredentialsAccepted"):
        add("_repository", "default-credentials",
            "The default administrator password still works", "HIGH",
            ["POST /api/TokenAuth/Authenticate as admin/123qwe returned 200 with a token"],
            "Change the deployed admin password. Combined with no account lockout, this is "
            "the shortest path into the application.")

    for r in (probes.get("results") or []):
        if r["verdict"] not in ("OPEN", "REACHED", "NOT-FOUND", "INCONCLUSIVE", "JUDGEMENT"):
            continue
        pkg = "_probe-findings"
        add(pkg, "anonymous-access" if r["principal"] == "anonymous"
            else "authenticated-access",
            "%s %s -> %s as %s" % (r["method"], r["path"], r["verdict"], r["principal"]),
            r.get("severityIfOpen") or "MEDIUM",
            ["HTTP %d, record access %s, hardcoded=%s"
             % (r["status"], ACCESS.get(r.get("recordAccess"), "-"),
                r.get("recordHardcoded")),
             (r.get("bodyExcerpt") or "")[:200]],
            "NOT-FOUND and INCONCLUSIVE are NOT passes - re-probe with the right verb and "
            "content type, and check the PermissionedObject record."
            if r["verdict"] in ("NOT-FOUND", "INCONCLUSIVE") else
            "Set an explicit access level on the PermissionedObject record, or disable it.",
            status="FAIL" if r["verdict"] in ("OPEN", "REACHED") else "REVIEW")

    for f in ((d["objectauth"] or {}).get("findings") or []):
        if f.get("verdict") not in ("EXPOSED", "UNSCOPED"):
            continue
        add("_object-authorization", "object-level-authorization",
            "%s: %s" % (f.get("check"),
                        f.get("entity") or f.get("ownerType") or f.get("taskId")),
            "CRITICAL" if f.get("sensitiveFieldsReturned") else "HIGH",
            [json.dumps({k: v for k, v in f.items() if k != "check"})[:300]],
            "Add a [GlobalSpecification] scoping this entity's queries to the caller. An "
            "entity action permission gates the endpoint, not the row.")
    return out


# --------------------------------------------------------------------------------------
# Reference cross-indexes
# --------------------------------------------------------------------------------------

def build_reference_indexes(d):
    forms = d["forms"] or {}
    per_form = forms.get("perForm") or {}
    front = (d["frontend"] or {}).get("files") or {}

    idx = {
        "endpointToForms": collections.defaultdict(set),
        "entityToForms": collections.defaultdict(set),
        "formToFiles": collections.defaultdict(set),
        "endpointToFiles": collections.defaultdict(set),
        "entityToFiles": collections.defaultdict(set),
        "permToFiles": collections.defaultdict(set),
        "permToRoles": collections.defaultdict(set),
    }
    for key, rec in per_form.items():
        for url in rec["endpoints"]:
            idx["endpointToForms"][url.split("?")[0].rstrip("/").lower()].add(key)
        for ent in rec["entities"]:
            idx["entityToForms"][ent].add(key)
    for key, rec in front.items():
        for url in rec["endpointsReferenced"]:
            idx["endpointToFiles"][url.split("?")[0].rstrip("/").lower()].add(rec["file"])
        for ent in rec["entitiesReferenced"]:
            idx["entityToFiles"][ent].add(rec["file"])
        for perm in rec["permissionsReferenced"]:
            idx["permToFiles"][perm].add(rec["file"])
        for form in rec["formsReferenced"]:
            idx["formToFiles"][form].add(rec["file"])
    for role in ((d["rolePermissions"] or {}).get("roles") or {}).values():
        for perm in role.get("permissions") or []:
            idx["permToRoles"][perm].add(role.get("name") or role.get("id"))
    for role in d["roles"]:
        for perm in (role.get("permissions") or []):
            name = perm.get("name") if isinstance(perm, dict) else perm
            if name:
                idx["permToRoles"][name].add((role.get("name") or "").strip())
    return idx


# --------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------

OVERRIDE_TEMPLATE = {
    "_readme": [
        "Reviewer overrides, applied on the next build_catalogs.py run. This is how the",
        "review phase's judgement becomes part of the catalogue instead of diverging from",
        "it: correct a row here, re-run, and every count in the report agrees.",
        "Keys: endpoints by path (case-insensitive), entities by full class name, forms by",
        "'module/name', customForms by file, permissions by name, findings by",
        "'{package}:{id}'. Values may set sensitivity (HIGH|MEDIUM|LOW), recommendedAction,",
        "severityHint, status, theme (the report section title), package (to re-attribute a",
        "row) and note (required).",
    ],
    "endpoints": {}, "entities": {}, "forms": {}, "customForms": {},
    "permissions": {}, "findings": {},
}


def apply_override(row, override, label_field):
    """Apply one reviewer override to one row, recording that a human decided it."""
    note = override.get("note")
    if "sensitivity" in override:
        row["sensitivity"] = {"rating": override["sensitivity"],
                              "basis": note or "set by reviewer",
                              "reviewRequired": False}
    if "recommendedAction" in override:
        row["recommendedAction"] = override["recommendedAction"]
        row["recommendationBasis"] = note or row.get("recommendationBasis")
    if "severityHint" in override:
        row["severityHint"] = override["severityHint"]
    if "status" in override:
        row["status"] = override["status"]
    if "theme" in override:
        # The digest normally derives the report section from recommendedAction. A reviewer
        # who raises the priority of a row (identity-table CRUD, say) must be able to name
        # the section too, or the row lands under a heading that misdescribes it.
        row["reviewTheme"] = override["theme"]
    row["reviewed"] = True
    if note:
        row["reviewNote"] = note
    if isinstance(row.get("sensitivity"), dict):
        row["sensitivity"]["reviewRequired"] = False
    if "reviewRequired" in row:
        row["reviewRequired"] = False
    return row


def apply_overrides(overrides, endpoints, entities, conf_forms, custom_forms, rolesperms,
                    other):
    """Move and amend rows per the reviewer's overrides. Returns a count and a warning list."""
    applied, unmatched = 0, []

    def relocate(buckets, row, new_package, key_field):
        for pkg, rows in buckets.items():
            if row in rows and pkg != new_package:
                rows.remove(row)
                buckets.setdefault(new_package, []).append(row)
                row[key_field] = new_package
                return True
        return False

    ep_index = {}
    for pkg, rows in endpoints.items():
        for row in rows:
            ep_index[row["matchKey"]] = row
            ep_index[row["path"].lower()] = row
    for key, override in (overrides.get("endpoints") or {}).items():
        row = ep_index.get(key.lower()) or ep_index.get(key.split("?")[0].rstrip("/").lower())
        if not row:
            unmatched.append("endpoint %s" % key)
            continue
        apply_override(row, override, "path")
        if override.get("package"):
            relocate(endpoints, row, override["package"], "module")
        applied += 1

    ent_index = {row["entity"].lower(): row
                 for rows in entities.values() for row in rows}
    for key, override in (overrides.get("entities") or {}).items():
        row = ent_index.get(key.lower())
        if not row:
            unmatched.append("entity %s" % key)
            continue
        apply_override(row, override, "entity")
        if override.get("package"):
            relocate(entities, row, override["package"], "module")
        applied += 1

    form_index = {row["form"].lower(): row
                  for rows in conf_forms.values() for row in rows}
    for key, override in (overrides.get("forms") or {}).items():
        row = form_index.get(key.lower())
        if not row:
            unmatched.append("form %s" % key)
            continue
        apply_override(row, override, "form")
        applied += 1

    cf_index = {row["file"].lower(): row
                for rows in custom_forms.values() for row in rows}
    for key, override in (overrides.get("customForms") or {}).items():
        row = cf_index.get(key.lower())
        if not row:
            unmatched.append("custom form %s" % key)
            continue
        apply_override(row, override, "file")
        applied += 1

    perm_index = {row["permission"].lower(): row
                  for bucket in rolesperms.values() for row in bucket["permissions"]}
    for key, override in (overrides.get("permissions") or {}).items():
        row = perm_index.get(key.lower())
        if not row:
            unmatched.append("permission %s" % key)
            continue
        apply_override(row, override, "permission")
        applied += 1

    find_index = {("%s:%s" % (pkg, row["id"])).lower(): row
                  for pkg, rows in other.items() for row in rows}
    for key, override in (overrides.get("findings") or {}).items():
        row = find_index.get(key.lower())
        if not row:
            unmatched.append("finding %s" % key)
            continue
        apply_override(row, override, "id")
        applied += 1

    return applied, unmatched


def safe_name(package):
    return re.sub(r"[^A-Za-z0-9_.\-]+", "-", package).strip("-") or "_unattributed"


ARTIFACT_KINDS = ("roles-and-permissions", "configured-forms", "custom-forms", "endpoints",
                  "entities", "other-findings")


def sweep_stale(out_dir, written):
    """Delete catalogue files this run did not write.

    A file is written only when its package has rows, so a package that loses its last row -
    a reviewer re-attributing the two endpoints that were in `_unattributed`, say - stops
    producing a file. Without this sweep the previous build's file survives and keeps
    asserting content that no longer exists, which is how a stale row gets quoted in a report.
    Reviewer input (review-overrides.json) and the index are never touched.
    """
    removed = []
    for path in sorted(glob.glob(os.path.join(out_dir, "*.json"))):
        name = os.path.basename(path)
        if name in ("_index.json", "review-overrides.json", "digest.json"):
            continue
        if not any(name.endswith("-%s.json" % kind) for kind in ARTIFACT_KINDS):
            continue
        if name not in written:
            os.remove(path)
            removed.append(name)
    return removed


def emit(out_dir, package, kind, payload, meta):
    doc = dict(meta)
    doc["package"] = package
    doc["artifact"] = kind
    doc.update(payload)
    path = os.path.join(out_dir, "%s-%s.json" % (safe_name(package), kind))
    write_json(path, doc)
    return os.path.basename(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--url", default="http://localhost:21021")
    ap.add_argument("--run-dir", default=None,
                    help="an existing security-audits/YYMMDD-HHMM directory")
    ap.add_argument("--packages", action="append",
                    help="restrict output to these packages; repeatable")
    ap.add_argument("--scope", choices=("all", "app"), default="all",
                    help="app = emit only packages this repository owns")
    ap.add_argument("--overrides", default=None,
                    help="reviewer overrides (default: <run-dir>/catalog/review-overrides.json)")
    args = ap.parse_args()

    repo_root = os.path.abspath(args.repo_root)
    cache = args.cache or cache_dir(args.repo_root, args.url)
    d = load_all(cache, repo_root)
    if d["surface"] is None and not d["entityconfigs"]:
        print("Nothing to build from: no swagger.json and no entityconfigs.json in %s.\n"
              "Run collect.py first." % cache, file=sys.stderr)
        return 2

    run_dir = args.run_dir or new_run_dir(args.repo_root)
    out_dir = os.path.join(run_dir, "catalog")
    ensure_dir(out_dir)

    id_to_name = module_name_map(d)
    known_modules = set(id_to_name.values()) | d["appModules"]
    known_modules |= {m.get("name") for m in d["modules"] if isinstance(m, dict)}
    known_modules |= {c.get("module") for c in d["entityconfigs"] if c.get("module")}
    known_modules.discard(None)
    proj_modules = refine_project_modules(project_module_map(repo_root), known_modules)
    # Swagger paths are matched lowercased everywhere (crossref, probes) but reported with
    # their real casing, because a reader has to be able to paste the path into a request.
    raw_swagger = maybe(cache, "swagger.json") or {}
    display_paths = {p.lower(): p for p in (raw_swagger.get("paths") or {})}
    path_tags = {}
    for path, ops in (raw_swagger.get("paths") or {}).items():
        tags = []
        for op in ops.values():
            for tag in (op.get("tags") or []) if isinstance(op, dict) else []:
                if tag not in tags:
                    tags.append(tag)
        if tags:
            path_tags[path.lower()] = tags
    maps = {
        "ns": namespace_module_map(d),
        "shortService": service_short_module_map(d),
        "entityClass": entity_class_module_map(d),
        "proj": proj_modules,
        "segment": url_segment_module_map(repo_root, proj_modules),
        "routePrefix": controller_route_module_map(repo_root, proj_modules),
        "pathTags": path_tags,
        "source": source_service_index(d["source"]),
        "known": sorted(known_modules),
        "entityFullByShort": {c["fullClassName"].rsplit(".", 1)[-1].lower():
                             c["fullClassName"]
                             for c in d["entityconfigs"] if c.get("fullClassName")},
    }
    frontends = (d["frontend"] or {}).get("frontendsScanned") or []
    refs = build_reference_indexes(d)

    perm_names = {p.get("name") for p in d["permissions"] if p.get("name")}
    entity_names = {e.get("fullClassName") for e in d["entityconfigs"]
                    if e.get("fullClassName")}
    service_names = set()
    for key in ("shesha-webapi", "shesha-webapi-action"):
        for rec in d["po"][key]:
            cls = (rec.get("object") or "").split("@")[0]
            if cls and "." in cls:
                service_names.add(cls.rsplit(".", 1)[-1])
    print("scanning backend source for permission, entity and service references ...")
    src_refs = scan_source_references(repo_root, perm_names, entity_names, service_names)
    print("  %d .cs files scanned" % src_refs["filesScanned"])

    menu_names, menu_urls = menu_form_refs(
        (d["mainmenu"] or {}).get("result") if isinstance(d["mainmenu"], dict)
        else d["mainmenu"])

    d["pkgModulesNotScanned"] = set()
    d["knownModules"] = maps["known"]
    endpoints = build_endpoints(d, refs, src_refs, maps, display_paths)
    entities = build_entities(d, refs, src_refs, display_paths, maps)
    conf_forms = build_configured_forms(d, refs, menu_names)
    d["missing"] += ["%s source" % m for m in sorted(d["pkgModulesNotScanned"])
                     if "%s source" % m not in d["missing"]]
    custom_forms = build_custom_forms(d, refs, menu_names, menu_urls)
    rolesperms = build_roles_permissions(d, refs, src_refs, id_to_name)
    other = build_other_findings(d, proj_modules, frontends)

    override_path = args.overrides or os.path.join(out_dir, "review-overrides.json")
    overrides, override_note = {}, None
    if os.path.isfile(override_path):
        try:
            overrides = read_json(override_path)
        except ValueError:
            override_note = "%s is not valid JSON - no overrides applied" % override_path
    else:
        write_json(override_path, OVERRIDE_TEMPLATE)
        override_note = ("wrote an empty override template to %s - record review decisions "
                         "there and re-run" % override_path)
    applied, unmatched = apply_overrides(overrides, endpoints, entities, conf_forms,
                                        custom_forms, rolesperms, other)

    packages = sorted(set(endpoints) | set(entities) | set(conf_forms)
                      | set(custom_forms) | set(rolesperms) | set(other))
    if args.scope == "app":
        packages = [p for p in packages
                    if p in d["appModules"] or p in frontends or p.startswith("_")
                    or any(p.startswith(f + "/") for f in frontends)]
    if args.packages:
        wanted = set(args.packages)
        packages = [p for p in packages if p in wanted]

    meta = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "backend": args.url,
        "defaultEndpointAccess": d["security"].get("defaultEndpointAccess"),
        "defaultEndpointAccessName": ACCESS.get(
            d["security"].get("defaultEndpointAccess"), "unknown"),
        "definitions": DEFINITIONS,
        "inputsMissing": d["missing"],
    }

    index = {"generated": meta["generated"], "runDir": os.path.basename(run_dir),
             "backend": args.url, "packages": {}, "inputsMissing": d["missing"],
             "totals": {}, "confidence": {},
             "review": {"overrideFile": os.path.basename(override_path),
                        "overridesApplied": applied,
                        "overridesUnmatched": unmatched}}

    all_written = set()
    for pkg in packages:
        written = []
        rp = rolesperms.get(pkg)
        if rp and (rp["roles"] or rp["permissions"]):
            written.append(emit(out_dir, pkg, "roles-and-permissions", {
                "roleCount": len(rp["roles"]),
                "permissionCount": len(rp["permissions"]),
                "unreferencedPermissions": sum(1 for p in rp["permissions"]
                                               if p["isUnreferenced"]),
                "roles": normalise_rows("roles", rp["roles"]),
                "permissions": normalise_rows("permissions", rp["permissions"]),
            }, meta))
        if conf_forms.get(pkg):
            rows = normalise_rows("forms", conf_forms[pkg])
            written.append(emit(out_dir, pkg, "configured-forms", {
                "formCount": len(rows),
                "unreferenced": sum(1 for r in rows if r["isUnreferenced"]),
                "anonymous": sum(1 for r in rows
                                 if (r["accessConfig"] or {}).get("access") == 5),
                "forms": rows,
            }, meta))
        if custom_forms.get(pkg):
            rows = normalise_rows("customForms", custom_forms[pkg])
            written.append(emit(out_dir, pkg, "custom-forms", {
                "fileCount": len(rows),
                "routes": sum(1 for r in rows if r["route"]),
                "unreferenced": sum(1 for r in rows if r["isUnreferenced"]),
                "forms": rows,
            }, meta))
        if endpoints.get(pkg):
            rows = normalise_rows("endpoints", endpoints[pkg])
            written.append(emit(out_dir, pkg, "endpoints", {
                "endpointCount": len(rows),
                "anonymous": sum(1 for r in rows
                                 if r["authorizationRules"]["effectiveAccess"] == 5),
                "anyAuthenticated": sum(1 for r in rows
                                        if r["authorizationRules"]["effectiveAccess"] == 3),
                "permissioned": sum(1 for r in rows
                                    if r["authorizationRules"]["effectiveAccess"] == 4),
                "unreferenced": sum(1 for r in rows if r["isUnreferenced"]),
                "note": "Dynamic entity CRUD endpoints are deliberately excluded - they are "
                        "catalogued per entity in {package}-entities.json.",
                "endpoints": rows,
            }, meta))
        if entities.get(pkg):
            rows = normalise_rows("entities", entities[pkg])
            written.append(emit(out_dir, pkg, "entities", {
                "entityCount": len(rows),
                "withCrudEndpoints": sum(1 for r in rows if r["CRUDEndpoints"]),
                "anonymous": sum(1 for r in rows
                                 if r["authorizationRules"]["effectiveAccess"] == 5),
                "unreferenced": sum(1 for r in rows if r["isUnreferenced"]),
                "withoutGlobalSpecification": sum(
                    1 for r in rows if r["CRUDEndpoints"] and not r["hasGlobalSpecifications"]),
                "entities": rows,
            }, meta))
        if other.get(pkg):
            rows = normalise_rows("findings", other[pkg])
            written.append(emit(out_dir, pkg, "other-findings", {
                "findingCount": len(rows),
                "bySeverityHint": dict(collections.Counter(r["severityHint"] for r in rows)),
                "findings": rows,
            }, meta))
        all_written.update(written)
        if written:
            is_front = pkg in frontends or any(pkg.startswith(f + "/") for f in frontends)
            index["packages"][pkg] = {
                "owner": ("internal" if pkg.startswith("_")
                          else "app" if pkg in d["appModules"] or is_front
                          else "package"),
                "files": written,
            }

    xr = (d["crossref"] or {}).get("summary") or {}
    fa = d["forms"] or {}
    index["totals"] = {
        "packages": len(index["packages"]),
        "endpoints": sum(len(v) for v in endpoints.values()),
        "entities": sum(len(v) for v in entities.values()),
        "configuredForms": sum(len(v) for v in conf_forms.values()),
        "customFormFiles": sum(len(v) for v in custom_forms.values()),
        "permissions": sum(len(v["permissions"]) for v in rolesperms.values()),
        "roles": sum(len(v["roles"]) for v in rolesperms.values()),
        "otherFindings": sum(len(v) for v in other.values()),
    }
    index["confidence"] = {
        "frontendsDetected": [f["dir"] for f in
                              ((d["frontend"] or {}).get("frontendsDetected") or [])],
        "frontendsScanned": frontends,
        "opaqueFormReferences": fa.get("opaqueCount"),
        "formsWithOpaqueReferences": len(fa.get("opaqueForms") or []),
        "opaqueCodedReferences": (d["frontend"] or {}).get("opaqueCount"),
        "unresolvableReferences": xr.get("unresolvableRefs"),
        "roleGrantsResolved": bool((d["rolePermissions"] or {}).get("servicePathUsed")),
        "entityPermissionsCollected": d["entityPermissions"] is not None,
        "swaggerAvailable": d["surface"] is not None,
        "surfaceFresh": bool(d["surfaceHealth"].get("fresh")),
        "surfaceCachedCopyFrom": d["surfaceHealth"].get("cachedCopyFrom"),
        "liveEndpointsAbsentFromSurface": d["surfaceHealth"].get("liveOnlyPaths"),
        "packageSourcesScanned": [
            {"name": s["name"], "branch": (s.get("git") or {}).get("branch"),
             "commit": (s.get("git") or {}).get("commit"),
             "units": len(s.get("unitsIncluded") or [])}
            for s in ((d["packageSources"] or {}).get("sources") or [])],
        "endpointsReferencedOnlyByPackageSource": xr.get("referencedOnlyByPackageSource"),
        "packageSourcesNotScanned": sorted(set(d["pkgNotScanned"]) | d["pkgModulesNotScanned"]),
        "unreferencedCappedAtReviewForUnscannedSource": sum(
            1 for rows in (list(endpoints.values()) + list(entities.values())
                           + list(conf_forms.values())) for r in rows
            if r.get("packageSourcesNotScanned") and r["recommendedAction"] == "REVIEW"
            and (r["recommendationBasis"] or "").startswith(("nothing scanned", "no scanned"))),
        "caveat": "isUnreferenced covers the scanned front-end and the scanned "
                  "framework/Enterprise source only.%s Every disable recommendation must "
                  "clear the safety gates in references/disabling-unused-endpoints.md first."
                  % ("" if not (d["pkgNotScanned"] or d["pkgModulesNotScanned"]) else
                     " Source was NOT scanned for: %s - package-owned rows those packages "
                     "could reach are capped at REVIEW, because their own screens may call "
                     "what looks unreferenced." % ", ".join(
                         sorted(set(d["pkgNotScanned"]) | d["pkgModulesNotScanned"]))),
    }
    stale = sweep_stale(out_dir, all_written)
    index["review"]["staleFilesRemoved"] = stale
    write_json(os.path.join(out_dir, "_index.json"), index)

    print("\nrun directory %s" % run_dir)
    print("catalog       %s" % out_dir)
    for key, val in index["totals"].items():
        print("  %-18s %s" % (key, val))
    print("\npackages (%d):" % len(index["packages"]))
    for pkg, info in sorted(index["packages"].items()):
        print("  %-34s %-8s %d files" % (pkg, info["owner"], len(info["files"])))
    if override_note:
        print("\nreview overrides: %s" % override_note)
    else:
        print("\nreview overrides: %d applied from %s"
              % (applied, os.path.basename(override_path)))
    for item in unmatched:
        print("  WARNING override matched nothing: %s" % item)

    if d["missing"]:
        print("\nMISSING INPUTS - these caps what the catalogue can say:")
        for name in d["missing"]:
            print("  %s" % name)
    if index["confidence"]["opaqueFormReferences"]:
        print("\nCONFIDENCE: %d opaque references in %d forms could reach any endpoint. "
              "Treat every isUnreferenced=true as a review item, not an apply item."
              % (index["confidence"]["opaqueFormReferences"],
                 index["confidence"]["formsWithOpaqueReferences"]))
    previous = latest_run_dir(args.repo_root, before=run_dir)
    print("\nprevious run: %s" % (previous or "none - this is the baseline"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
