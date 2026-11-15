"""Shared helpers for the Shesha endpoint-security skills.

Import from the other resource scripts:

    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from shesha_audit import *

Everything here is deliberately dependency-free (stdlib only) so it runs on any machine
that has Python 3.8+, with no pip install step.
"""

import collections
import io
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

# Windows consoles default to cp1252. Form markup and C# source routinely contain
# characters it cannot encode (zero-width spaces are common in Shesha templates), and the
# resulting UnicodeEncodeError kills a script mid-report. Importing this module fixes it
# for every caller.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# --------------------------------------------------------------------------------------
# Access levels — RefListPermissionedAccess
# --------------------------------------------------------------------------------------

ACCESS = {
    1: "Disabled",
    2: "Inherited",
    3: "AnyAuthenticated",
    4: "RequiresPermissions",
    5: "AllowAnonymous",
}

PERMISSIONED_OBJECT_TYPES = [
    "Shesha.WebApi",
    "Shesha.WebApi.Action",
    "Shesha.Entity",
    "Shesha.Entity.Action",
    "Shesha.WebCrudApi",
    "Shesha.WebCrudApi.Action",
    "Shesha.Form",
]

# --------------------------------------------------------------------------------------
# JSON / encoding
#
# Windows defaults to cp1252, and Shesha form markup routinely contains characters that
# blow up under it. Always go through these two helpers, never bare open().
# --------------------------------------------------------------------------------------


def read_json(path):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, obj):
    ensure_dir(os.path.dirname(path))
    with io.open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


def write_text(path, text):
    ensure_dir(os.path.dirname(path))
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def ensure_dir(path):
    if path and not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def unwrap(payload):
    """ABP wraps responses as {result: ...}; `result` is sometimes a bare list and
    sometimes {items: [...], totalCount: n}. Normalise to a list where it is a
    collection, otherwise return the object."""
    if isinstance(payload, dict) and "result" in payload:
        payload = payload["result"]
    if isinstance(payload, dict) and "items" in payload:
        return payload["items"]
    return payload


# --------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------

_NOVERIFY = ssl.create_default_context()
_NOVERIFY.check_hostname = False
_NOVERIFY.verify_mode = ssl.CERT_NONE


def request(method, url, token=None, body=None, timeout=120, content_type="application/json"):
    """Returns (status, body_bytes). Status 0 means the connection failed outright —
    that is a dead backend, never a security verdict."""
    data = None
    headers = {}
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        headers["Content-Type"] = content_type
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_NOVERIFY) as resp:
            return resp.getcode(), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception:
        return 0, b""


def get_json(url, token=None, timeout=180):
    status, raw = request("GET", url, token=token, timeout=timeout)
    if status != 200:
        return status, None
    try:
        return status, json.loads(raw.decode("utf-8"))
    except Exception:
        return status, None


def authenticate(base_url, user, password):
    status, raw = request(
        "POST",
        base_url.rstrip("/") + "/api/TokenAuth/Authenticate",
        body={"userNameOrEmailAddress": user, "password": password},
        timeout=60,
    )
    if status != 200:
        return None, status
    try:
        return json.loads(raw.decode("utf-8"))["result"]["accessToken"], status
    except Exception:
        return None, status


# --------------------------------------------------------------------------------------
# Ownership
#
# appModules are SheshaModuleInfo names; appUrlSegments are moduleName: values. They are
# different strings — a repo routinely has module `Shesha.Hcm` and URL segment `HcmCommon`.
# --------------------------------------------------------------------------------------

DYN_RE = re.compile(r"^/api/dynamic/([^/]+)/([^/]+)/crud/(\w+)$")
SVC_RE = re.compile(r"^/api/services/([^/]+)/([^/]+)/(\w+)$")


class Ownership(object):
    def __init__(self, app_modules, app_url_segments, app_path_prefixes=()):
        self.app_modules = set(app_modules)
        self.app_url_segments = set(s.lower() for s in app_url_segments)
        self.app_path_prefixes = tuple(p.lower() for p in app_path_prefixes)

    def of_path(self, path):
        p = path.lower()
        for pre in self.app_path_prefixes:
            if p.startswith(pre):
                return "app"
        m = DYN_RE.match(p) or SVC_RE.match(p)
        if m:
            return "app" if m.group(1).lower() in self.app_url_segments else "package"
        return "package"

    def of_module(self, module):
        return "app" if module in self.app_modules else "package"

    def to_dict(self):
        return {
            "appModules": sorted(self.app_modules),
            "appUrlSegments": sorted(self.app_url_segments),
            "appPathPrefixes": list(self.app_path_prefixes),
        }


def detect_ownership(repo_root):
    """Derive appModules / appUrlSegments / hand-routed controller prefixes from source.

    Resolves `SheshaModuleInfo(Name)` where Name is a constant by looking for a matching
    `const string Name = "..."` in the same file.
    """
    app_modules, url_segments, prefixes = set(), set(), set()
    src = os.path.join(repo_root, "backend", "src")
    if not os.path.isdir(src):
        return Ownership(app_modules, url_segments, ())

    mod_re = re.compile(r"SheshaModuleInfo\(\s*(?:\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_.]*))")
    # The name constant is declared as `const string Name`, `static string Name` or
    # `static readonly string Name` depending on the template vintage - match all of them.
    const_re = re.compile(
        r"(?:const|static(?:\s+readonly)?)\s+string\s+Name\s*=\s*\"([^\"]+)\"")
    seg_re = re.compile(r"moduleName\s*:\s*\"([^\"]+)\"")
    route_re = re.compile(r"\[Route\(\s*\"([^\"]+)\"")

    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in ("obj", "bin")]
        for fn in filenames:
            if not fn.endswith(".cs"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with io.open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except Exception:
                continue

            for m in mod_re.finditer(text):
                literal, ident = m.group(1), m.group(2)
                if literal:
                    app_modules.add(literal)
                elif ident:
                    c = const_re.search(text)
                    if c:
                        app_modules.add(c.group(1))
            for m in seg_re.finditer(text):
                url_segments.add(m.group(1))
            if fn.endswith("Controller.cs"):
                for m in route_re.finditer(text):
                    route = m.group(1)
                    if "[controller]" in route:
                        ctrl = fn[: -len("Controller.cs")]
                        route = route.replace("[controller]", ctrl)
                    prefixes.add("/" + route.strip("/").lower())

    return Ownership(app_modules, url_segments, sorted(prefixes))


# --------------------------------------------------------------------------------------
# Surface
# --------------------------------------------------------------------------------------


def load_surface(swagger):
    """{lowercased path: sorted[methods]} from an OpenAPI document."""
    verbs = ("get", "post", "put", "delete", "patch", "head", "options")
    surface = {}
    for path, ops in (swagger.get("paths") or {}).items():
        methods = [m.upper() for m in ops if m.lower() in verbs]
        surface.setdefault(path.lower(), set()).update(methods)
    return dict((k, sorted(v)) for k, v in surface.items())


def dynamic_entities(surface):
    """{'/api/dynamic/{mod}/{Entity}/crud': [actions]}"""
    out = collections.defaultdict(set)
    for path in surface:
        m = DYN_RE.match(path)
        if m:
            out["/api/dynamic/%s/%s/crud" % (m.group(1), m.group(2))].add(m.group(3))
    return dict((k, sorted(v)) for k, v in out.items())


def index_permissioned_objects(records):
    """Index Shesha.WebApi.Action records by (service_short_name, method) lowercased."""
    idx = {}
    for rec in records:
        obj = rec.get("object") or ""
        if "@" in obj:
            cls, meth = obj.rsplit("@", 1)
            idx[(cls.split(".")[-1].lower(), meth.lower())] = rec
    return idx


def record_name_candidates(method):
    """Record method names that could correspond to a route segment.

    Route names and PermissionedObject record names do NOT always match. Shesha.Workflow
    routes `CompleteUserTask` as `UserTaskComplete`, `SaveUserTask` as `UserTaskSave`,
    `GetMyActiveTodoItems` as `MyActiveTodoItems`, `GetDetails` as `Details` and
    `GetUserTaskDetails` as `UserTaskDetails`. Matching only the exact name reports eight
    AllowAnonymous endpoints as AnyAuthenticated, which is the difference between "any
    logged-in user" and "the whole internet".
    """
    meth = (method or "").lower()
    out = [meth, "get" + meth]
    for split in ("usertask", "user"):
        if meth.startswith(split) and len(meth) > len(split):
            tail = meth[len(split):]
            out.append(tail + split)          # UserTaskComplete -> CompleteUserTask
            out.append("get" + tail + split)  # UserTaskDetails  -> GetUserTaskDetails
            out.append("get" + split + tail)  # UserTaskDetails  -> GetUserTaskDetails
    if meth.startswith("my"):
        out.append("getmy" + meth[2:])        # MyActiveTodoItems -> GetMyActiveTodoItems
    seen, uniq = set(), []
    for cand in out:
        if cand not in seen:
            seen.add(cand)
            uniq.append(cand)
    return uniq


def lookup_action_record(service, method, action_index):
    """Find the Shesha.WebApi.Action record for a route, allowing for renamed routes."""
    svc = (service or "").lower()
    for cand in record_name_candidates(method):
        for key in (svc, svc + "appservice", svc + "controller"):
            rec = action_index.get((key, cand))
            if rec:
                return rec
    return None


def resolve_access(path, action_index, default_endpoint_access):
    """Walk the precedence model for one endpoint.

    Returns (record_or_None, effective_access, permissions, hardcoded, enforcement_note).
    Mirrors references/enforcement-rules.md — do not shortcut it elsewhere.
    """
    m = SVC_RE.match(path)
    if m:
        svc, meth = m.group(2).lower(), m.group(3).lower()
        rec = action_index.get((svc, meth)) or action_index.get((svc + "appservice", meth))
        if rec:
            actual = rec.get("actualAccess")
            if actual == 2:
                return (rec, default_endpoint_access, [], rec.get("hardcoded"),
                        "Inherited -> DefaultEndpointAccess")
            return (rec, actual, rec.get("actualPermissions") or [], rec.get("hardcoded"),
                    "PermissionedObject (Shesha.WebApi.Action)")
    if DYN_RE.match(path):
        return (None, default_endpoint_access, [], False,
                "EntityCrudAuthorizationHelper -> DefaultEndpointAccess "
                "(no Shesha.Entity.Action record)")
    return (None, default_endpoint_access, [], False, "DefaultEndpointAccess (no record)")


def permission_to_roles(roles):
    p2r = collections.defaultdict(list)
    for role in roles:
        for perm in (role.get("permissions") or []):
            p2r[perm].append((role.get("name") or "").strip())
    return dict(p2r)


# --------------------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------------------


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join("" if c is None else str(c) for c in row) + " |")
    return "\n".join(out)


def cache_dir(repo_root, base_url):
    host = urllib.parse.urlparse(base_url).netloc.replace(":", "_") or "default"
    return os.path.join(repo_root, ".claude", ".audit-cache", host)


# --------------------------------------------------------------------------------------
# Report output location
#
# Every report from one run goes in security-audits/YYMMDD-HHMM/ so that runs are
# comparable over time and nothing is silently overwritten. The cache under
# .claude/.audit-cache/ is separate and gitignored - it holds raw captures, some of which
# contain credentials. Reports are committable; the cache is not.
# --------------------------------------------------------------------------------------

AUDIT_ROOT = "security-audits"


def new_run_dir(repo_root, when=None):
    """security-audits/YYMMDD-HHMM for this run, created."""
    import datetime
    stamp = (when or datetime.datetime.now()).strftime("%y%m%d-%H%M")
    path = os.path.join(repo_root, AUDIT_ROOT, stamp)
    ensure_dir(path)
    return path


def latest_run_dir(repo_root, before=None):
    """The most recent existing run directory, or None.

    Pass `before` (a directory name) to get the run preceding it - that is what the
    report's comparison section needs, so a re-run compares against the previous audit
    rather than against itself.
    """
    root = os.path.join(repo_root, AUDIT_ROOT)
    if not os.path.isdir(root):
        return None
    runs = sorted(d for d in os.listdir(root)
                  if os.path.isdir(os.path.join(root, d))
                  and re.match(r"^\d{6}-\d{4}$", d))
    if before:
        runs = [d for d in runs if d < os.path.basename(before.rstrip("/\\"))]
    return os.path.join(root, runs[-1]) if runs else None
