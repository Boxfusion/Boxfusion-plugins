"""Extract every endpoint reference from a Shesha form-configuration dump.

    python analyze_forms.py [--cache DIR] [--repo-root .] [--url http://localhost:21021]

Reads forms.json from the audit cache (produced by collect.py) and writes
form_analysis.json beside it.

Two views of the same data are emitted, because both are needed:
  * the global inverted index (endpoint -> forms), which answers "is this endpoint used"
  * `perForm`, keyed by "{module}/{name}", which is what `{package}-configured-forms.json`
    is built from and what makes a per-package recommendation possible at all.

Implements all nine mechanisms in references/form-reference-mechanisms.md. The two that
matter most for correctness, because getting them wrong silently produces false
"unreferenced" results:

  * Source-type discriminators. A component holds both an entityType and a URL, and a mode
    flag decides which is live. The inactive one is stale configuration, not a reference.
  * Unresolvable references. A script that builds its URL at runtime taints everything.
    They are counted separately, and split into "the snippet also contains a literal /api/
    path" (so the endpoint was probably captured anyway) and "fully opaque".
"""

import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from shesha_audit import cache_dir, read_json, write_json  # noqa: E402

URL_KEYS = {
    "url", "endpoint", "customReorderEndpoint", "dataSourceUrl", "getUrl", "postUrl",
    "putUrl", "deleteUrl", "customCreateUrl", "customUpdateUrl", "customDeleteUrl",
    "getEntityUrl", "quickviewGetEntityUrl", "autocompleteUrl", "getListUrl", "submitUrl",
    "fetchUrl", "getFormUrl", "customUrl", "customApiUrl",
}
NAV_KEYS = {"targetUrl", "navigateToUrl", "onSuccessRedirectUrl"}
PERMISSION_KEYS = {"permissions", "requiredPermissions", "permissionName", "permission"}
JS_KEYS = {
    "expression", "executeExpression", "onExecute", "customJsCode", "actionScript",
    "jsCode", "code", "onChangeCustom", "onBlurCustom", "onFocusCustom",
    "customVisibility", "customEnabled", "onBeforeDataLoad", "onAfterDataLoad",
    "onPrepareSubmitData", "onBeforeSubmit", "onSubmitSuccess", "onSubmitFailed",
    "onValuesUpdate", "onRowSave", "onRowSaveSuccess", "customFilter", "filter",
    "permanentFilter", "content", "defaultValue",
}
API_RE = re.compile(r"/api/[A-Za-z0-9_\-/\.\{\}]+")
VERBS = "get|post|put|patch|delete|head|options"
UNRESOLVABLE = [
    (re.compile(r"http\.(?:" + VERBS + r")\s*\(\s*[`'\"][^`'\"]*\$\{"), "template-literal-url"),
    (re.compile(r"http\.(?:" + VERBS + r")\s*\(\s*[A-Za-z_$][A-Za-z0-9_$\.]*\s*[,\)]"), "endpoint-from-data"),
    (re.compile(r"http\[[^\]]+\]\s*\("), "dynamic-verb"),
    (re.compile(r"/api/[^\s\"'`]*['\"]\s*\+"), "concatenated-url"),
]


def window(text, at, before=70, after=170):
    """A readable excerpt around `at`, whitespace collapsed."""
    start, end = max(0, at - before), min(len(text), at + after)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def new_state():
    return {
        "form_config_endpoints": collections.defaultdict(set),
        "js_endpoints": collections.defaultdict(set),
        "nav_urls": collections.defaultdict(set),
        "entity_bindings": collections.defaultdict(set),
        "owner_bindings": collections.defaultdict(set),
        "reflists": collections.defaultdict(set),
        "form_refs": collections.defaultdict(set),
        "stale": collections.defaultdict(set),
        "external": collections.defaultdict(set),
        "permission_refs": collections.defaultdict(set),
        "unresolvable": [],
        "dyn_subforms": [],
        "datasource_modes": collections.Counter(),
    }


def add_url(res, bucket, raw, fk):
    u = (raw or "").strip()
    if not u:
        return
    if u.startswith("http://") or u.startswith("https://"):
        if "/api/" in u:
            res[bucket]["/api/" + u.split("/api/", 1)[1]].add(fk)
        else:
            res["external"][u].add(fk)
        return
    if u.startswith("/api/") or u.startswith("api/"):
        res[bucket][u if u.startswith("/") else "/" + u].add(fk)
    elif "${" in u or "`" in u or "+" in u:
        res["unresolvable"].append((fk, "url-property", "concatenated-url", u[:200]))


def live_branches(node):
    """Return (entity_is_live, url_is_live) after applying the discriminator."""
    ent_live = url_live = True
    st, dst, dm = node.get("sourceType"), node.get("dataSourceType"), node.get("dataMode")
    if st is not None:
        s = str(st).lower()
        ent_live, url_live = s == "entity", s == "url"
    if dst is not None:
        s = str(dst).lower()
        if s in ("entitieslist", "entity"):
            ent_live, url_live = True, False
        elif s == "url":
            ent_live, url_live = False, True
        elif s in ("referencelist", "values"):
            ent_live, url_live = False, False
    if dm is not None:
        s = str(dm).lower()
        ent_live, url_live = s == "entitytype", s == "url"
    return ent_live, url_live


def scan(node, fk, res):
    if isinstance(node, list):
        for item in node:
            scan(item, fk, res)
        return
    if not isinstance(node, dict):
        return

    for key in ("sourceType", "dataSourceType", "dataMode"):
        if node.get(key):
            res["datasource_modes"][(key, str(node[key]))] += 1

    ent_live, url_live = live_branches(node)

    ent = node.get("entityType") or node.get("modelType")
    if ent and isinstance(ent, str):
        (res["entity_bindings"] if ent_live else res["stale"])[ent].add(fk)

    owner = node.get("ownerType")
    if owner and isinstance(owner, str):
        res["owner_bindings"][owner].add(fk)

    for key, val in node.items():
        if key in URL_KEYS and isinstance(val, str):
            add_url(res, "form_config_endpoints" if url_live else "stale", val, fk)
        elif key in NAV_KEYS and isinstance(val, str) and "/api/" in val:
            res["nav_urls"][val].add(fk)
        elif isinstance(val, str) and len(val) > 3 and (
                key in JS_KEYS or key.endswith("Expression") or key.endswith("Custom")):
            for hit in API_RE.findall(val):
                res["js_endpoints"][hit].add(fk)
            for rx, reason in UNRESOLVABLE:
                m = rx.search(val)
                if m:
                    # Window the snippet around the match, not the first 160 characters of
                    # the script. A reviewer needs the line that builds the URL; the top of
                    # a 200-line handler tells them nothing.
                    res["unresolvable"].append((fk, key, reason, window(val, m.start())))

    # Permission gating declared on the form or on a component. A permission referenced only
    # here is still referenced - miss it and the permission looks orphaned.
    for key in PERMISSION_KEYS:
        val = node.get(key)
        if isinstance(val, str) and val.strip():
            res["permission_refs"][val.strip()].add(fk)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str) and item.strip():
                    res["permission_refs"][item.strip()].add(fk)
                elif isinstance(item, dict) and isinstance(item.get("name"), str):
                    res["permission_refs"][item["name"].strip()].add(fk)

    rl = node.get("referenceListId")
    if isinstance(rl, dict) and rl.get("name"):
        res["reflists"][(rl.get("module"), rl.get("name"))].add(fk)
    elif isinstance(node.get("referenceListName"), str):
        res["reflists"][(None, node["referenceListName"])].add(fk)

    for key in ("formId", "formIdentifier"):
        val = node.get(key)
        if isinstance(val, dict) and val.get("name"):
            res["form_refs"][fk].add((val.get("module"), val.get("name")))
        elif isinstance(val, str) and val:
            res["form_refs"][fk].add((None, val))

    mode = node.get("formSelectionMode")
    if mode == "expression":
        res["unresolvable"].append(
            (fk, "formSelectionMode", "expression-selected-form", str(node.get("id"))[:60]))
    elif mode == "dynamic":
        res["dyn_subforms"].append((fk, node.get("entityType"), node.get("formType")))

    for val in node.values():
        if isinstance(val, (dict, list)):
            scan(val, fk, res)


def guess_url(snippet):
    """Best guess at the URL an opaque snippet builds, for the catalogue's benefit.

    A reviewer needs something to grep for. Prefer a literal /api/ fragment; otherwise take
    the first template-literal or concatenation base that looks like a path.
    """
    m = API_RE.search(snippet or "")
    if m:
        return m.group(0)
    m = re.search(r"[`'\"](/[A-Za-z0-9_\-/\.]*\$\{[^}]*\}[A-Za-z0-9_\-/\.]*)", snippet or "")
    if m:
        return m.group(1)
    m = re.search(r"[`'\"](/[A-Za-z0-9_\-/\.]{3,})", snippet or "")
    return m.group(1) if m else None


def build_per_form(live, res):
    """Invert the global indexes into one record per form.

    `{package}-configured-forms.json` needs per-form attribution, and inverting here keeps
    the two views arithmetically identical - two separate computations of "which endpoints
    does this form call" is exactly how an earlier revision reported two different totals.
    """
    per = {}
    for form in live:
        fk = (form.get("module") or "?") + "/" + (form.get("name") or "?")
        per[fk] = {
            "module": form.get("module"),
            "name": form.get("name"),
            "label": form.get("label"),
            "modelType": form.get("modelType"),
            "endpoints": [], "staleEndpoints": [], "entities": [], "owners": [],
            "reflists": [], "forms": [], "externalUrls": [], "permissions": [],
            "opaque": [],
        }

    def spread(index, field, transform=None):
        for target, forms in index.items():
            value = transform(target) if transform else target
            for fk in forms:
                if fk in per and value not in per[fk][field]:
                    per[fk][field].append(value)

    spread(res["form_config_endpoints"], "endpoints")
    spread(res["js_endpoints"], "endpoints")
    spread(res["nav_urls"], "endpoints")
    spread(res["stale"], "staleEndpoints")
    spread(res["entity_bindings"], "entities")
    spread(res["owner_bindings"], "owners")
    spread(res["external"], "externalUrls")
    spread(res["permission_refs"], "permissions")
    for (module, name), forms in res["reflists"].items():
        label = "%s/%s" % (module or "?", name)
        for fk in forms:
            if fk in per and label not in per[fk]["reflists"]:
                per[fk]["reflists"].append(label)

    for fk, targets in res["form_refs"].items():
        if fk not in per:
            continue
        for module, name in targets:
            label = "%s/%s" % (module or "?", name)
            if label not in per[fk]["forms"]:
                per[fk]["forms"].append(label)

    for fk, key, reason, snippet in res["unresolvable"]:
        if fk not in per:
            continue
        per[fk]["opaque"].append({
            "markupKey": key, "reason": reason,
            "snippet": snippet[:160],
            "guessedUrl": guess_url(snippet),
        })

    # Which forms are referenced BY another form - the inverse edge, needed for
    # isReferencedByOtherForm without re-walking the graph.
    referenced_by = collections.defaultdict(set)
    for fk, targets in res["form_refs"].items():
        for module, name in targets:
            referenced_by["%s/%s" % (module or "?", name)].add(fk)
    for fk, rec in per.items():
        rec["referencedByForms"] = sorted(referenced_by.get(fk, ()))
        # A GUID form reference resolves to no module/name pair, so also match on bare name.
        if not rec["referencedByForms"]:
            rec["referencedByForms"] = sorted(referenced_by.get("?/" + (rec["name"] or ""), ()))
    return per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=None)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--url", default="http://localhost:21021")
    args = ap.parse_args()

    cache = args.cache or cache_dir(args.repo_root, args.url)
    forms_path = os.path.join(cache, "forms.json")
    if not os.path.isfile(forms_path):
        print("No forms.json in %s. Run collect.py first." % cache, file=sys.stderr)
        return 2

    own = read_json(os.path.join(cache, "ownership.json"))
    app_modules = set(own.get("appModules") or [])

    items = read_json(forms_path)["result"]["items"]
    live = [f for f in items if f.get("isLastVersion")]
    by_module = collections.Counter(f.get("module") for f in live)
    app_forms = sum(v for k, v in by_module.items() if k in app_modules)
    print("form rows %d -> live versions %d (%d app-owned, %d package)"
          % (len(items), len(live), app_forms, len(live) - app_forms))

    res = new_state()
    for form in live:
        fk = (form.get("module") or "?") + "/" + (form.get("name") or "?")
        if form.get("modelType"):
            res["entity_bindings"][form["modelType"]].add(fk)
        markup = form.get("markup")
        if not markup:
            continue
        try:
            scan(json.loads(markup) if isinstance(markup, str) else markup, fk, res)
        except ValueError:
            continue

    opaque = [u for u in res["unresolvable"] if "/api/" not in u[3]]
    print("\nreferences found")
    for key in ("form_config_endpoints", "js_endpoints", "entity_bindings",
                "owner_bindings", "reflists", "form_refs", "stale", "external"):
        print("  %-24s %d" % (key, len(res[key])))
    print("  %-24s %d (%d fully opaque, in %d forms)"
          % ("unresolvable", len(res["unresolvable"]), len(opaque),
             len(set(u[0] for u in opaque))))
    if opaque:
        print("\n  %d opaque references cap the confidence of any 'unreferenced' conclusion."
              % len(opaque))
        print("  Report that number; do not present the unreferenced list as safe to apply.")

    per_form = build_per_form(live, res)

    out = {
        "form_config_endpoints": {k: sorted(v) for k, v in res["form_config_endpoints"].items()},
        "js_endpoints": {k: sorted(v) for k, v in res["js_endpoints"].items()},
        "nav_urls": {k: sorted(v) for k, v in res["nav_urls"].items()},
        "entity_bindings": {k: sorted(v) for k, v in res["entity_bindings"].items()},
        "owner_bindings": {k: sorted(v) for k, v in res["owner_bindings"].items()},
        "reflists": {str(k): sorted(v) for k, v in res["reflists"].items()},
        "form_refs": {k: [list(x) for x in sorted(v, key=lambda t: (str(t[0]), str(t[1])))]
                      for k, v in res["form_refs"].items()},
        "stale": {k: sorted(v) for k, v in res["stale"].items()},
        "external": {k: sorted(v) for k, v in res["external"].items()},
        "permission_refs": {k: sorted(v) for k, v in res["permission_refs"].items()},
        "perForm": per_form,
        "unresolvable": res["unresolvable"],
        "opaqueCount": len(opaque),
        "opaqueForms": sorted(set(u[0] for u in opaque)),
        "dyn_subforms": res["dyn_subforms"],
        "datasource_modes": {str(k): v for k, v in res["datasource_modes"].items()},
        "liveForms": [{"module": f.get("module"), "name": f.get("name"),
                       "label": f.get("label"), "modelType": f.get("modelType")}
                      for f in live],
        "formsByModule": dict(by_module),
    }
    write_json(os.path.join(cache, "form_analysis.json"), out)
    print("\nwritten %s" % os.path.join(cache, "form_analysis.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
