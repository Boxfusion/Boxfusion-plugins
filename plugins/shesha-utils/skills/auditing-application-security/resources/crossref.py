"""Intersect the backend surface with what the frontend actually references.

    python crossref.py [--cache DIR] [--repo-root .] [--url http://localhost:21021]
                       [--coded-endpoints file.txt] [--package-refs file.json]

Reads swagger.json, form_analysis.json and ownership.json from the audit cache, plus
package_source_refs.json (scan_package_sources.py) when present; writes crossref.json
beside them.

Package-source references - endpoints called from the framework's or Enterprise's own React
pages, components and packaged form configurations - are marked with the kind
`<source>-frontend` / `<source>-backend` / `<source>-packaged-form`, so the catalogue shows
who the caller is, not merely that one exists.

Expansion rules, per references/form-reference-mechanisms.md section 4A:
  entity binding  -> that entity's dynamic CRUD routes + Metadata/Get
  owner binding   -> the StoredFile family and the Notes service
  reference list  -> ReferenceList/GetByName
  form reference  -> FormConfiguration GetByName + CheckPermissions

Endpoint references are unioned globally, so a transitive form->form->endpoint path is
already covered without walking the graph: if any live form references an endpoint, it is
referenced. The graph would only matter for per-form attribution, which this catalog does
not claim.
"""

import argparse
import collections
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from shesha_audit import (Ownership, cache_dir, dynamic_entities, load_surface,  # noqa: E402
                          read_json, write_json)

STOREDFILE = ["/api/StoredFile/FilesList", "/api/StoredFile/Upload",
              "/api/StoredFile/UploadNewVersion", "/api/StoredFile/Download",
              "/api/StoredFile/Delete", "/api/StoredFile/EntityProperty",
              "/api/services/app/Notes/GetList", "/api/services/app/Notes/Create",
              "/api/services/app/Notes/Update", "/api/services/app/Notes/Delete"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=None)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--url", default="http://localhost:21021")
    ap.add_argument("--coded-endpoints", default=None,
                    help="file with one /api/ path per line, from the frontend source scan")
    ap.add_argument("--package-refs", default=None,
                    help="package_source_refs.json from scan_package_sources.py "
                         "(default: the one in the cache, if present)")
    args = ap.parse_args()

    cache = args.cache or cache_dir(args.repo_root, args.url)
    analysis = read_json(os.path.join(cache, "form_analysis.json"))
    own_raw = read_json(os.path.join(cache, "ownership.json"))
    own = Ownership(own_raw["appModules"], own_raw["appUrlSegments"],
                    own_raw.get("appPathPrefixes") or ())

    swagger_path = os.path.join(cache, "swagger.json")
    if not os.path.isfile(swagger_path) or os.path.getsize(swagger_path) == 0:
        print("No usable swagger.json in %s. Without a surface there is nothing to "
              "intersect against, and every endpoint would look unreferenced." % cache,
              file=sys.stderr)
        return 2
    surface = load_surface(read_json(swagger_path))
    ent_actions = dynamic_entities(surface)

    ent_routes = collections.defaultdict(set)
    for base in ent_actions:
        ent_routes[base.rsplit("/", 2)[-2].lower()].add(base)

    referenced = collections.defaultdict(set)

    def mark(path, kind):
        p = path.split("?")[0].rstrip("/").lower()
        if p.startswith("/api/"):
            referenced[p].add(kind)

    for url in analysis["form_config_endpoints"]:
        mark(url, "form-config-property")
    for url in analysis["js_endpoints"]:
        mark(url, "embedded-javascript")
    for url in analysis["nav_urls"]:
        mark(url, "action-configuration")

    if args.coded_endpoints and os.path.isfile(args.coded_endpoints):
        for line in open(args.coded_endpoints):
            if line.strip():
                mark(line.strip(), "coded-frontend")

    # Endpoints the framework's and Enterprise's own code calls.
    pkg_path = args.package_refs or os.path.join(cache, "package_source_refs.json")
    pkg = read_json(pkg_path) if os.path.isfile(pkg_path) else None
    package_evidence = collections.defaultdict(list)
    pkg_patterns_unresolved = []
    if pkg:
        def mark_pkg(path, ev):
            key = path.split("?")[0].rstrip("/").lower()
            mark(key, "%s-%s" % (ev["source"], ev["kind"]))
            line = "%s-%s: %s" % (ev["source"], ev["kind"], ev["file"])
            if len(package_evidence[key]) < 5 and line not in package_evidence[key]:
                package_evidence[key].append(line)
        for url, evs in pkg["references"].items():
            for ev in evs:
                mark_pkg(url, ev)
        # `${id}` in a URL template becomes {} on both sides, so
        # /api/storedfile/storedfile/${fileId}/versions meets {fileid} in the surface.
        placeholder = re.compile(r"\{[^}/]*\}")
        by_shape = collections.defaultdict(list)
        for p in surface:
            by_shape[placeholder.sub("{}", p)].append(p)
        for pat, evs in pkg["patterns"].items():
            hits = by_shape.get(pat)
            if not hits:
                pkg_patterns_unresolved.append(pat)
            for hit in hits or ():
                for ev in evs:
                    mark_pkg(hit, ev)

    entity_hits = {}
    for ent in analysis["entity_bindings"]:
        bases = sorted(ent_routes.get(ent.split(".")[-1].lower(), set()))
        entity_hits[ent] = bases
        for base in bases:
            for action in ent_actions[base]:
                mark(base + "/" + action, "entity-binding")
        mark("/api/services/app/Metadata/Get", "entity-binding")

    owner_hits = {}
    for ent in analysis["owner_bindings"]:
        bases = sorted(ent_routes.get(ent.split(".")[-1].lower(), set()))
        owner_hits[ent] = bases
        for base in bases:
            mark(base + "/get", "owner-binding")
    if analysis["owner_bindings"]:
        for url in STOREDFILE:
            mark(url, "owner-binding")
    if analysis["reflists"]:
        mark("/api/services/app/ReferenceList/GetByName", "reference-list")
    if analysis["form_refs"]:
        mark("/api/services/Shesha/FormConfiguration/GetByName", "form-reference")
        mark("/api/services/Shesha/FormConfiguration/CheckPermissions", "form-reference")

    unref = [(p, surface[p], own.of_path(p))
             for p in sorted(surface) if p not in referenced]
    app_unref = [u for u in unref if u[2] == "app"]

    # Entities whose every action is unreferenced.
    rollup, fully_unused = [], []
    for base, actions in sorted(ent_actions.items()):
        used = [a for a in actions if (base + "/" + a) in referenced]
        row = (base, len(actions), len(used), own.of_path(base + "/get"))
        rollup.append(row)
        if not used:
            fully_unused.append(row)

    # Anything an opaque reference might reach is indeterminate, not unreferenced.
    opaque_forms = set(analysis.get("opaqueForms") or [])
    tainted = set()
    for ent, forms in analysis["entity_bindings"].items():
        if any(f in opaque_forms for f in forms):
            for base in ent_routes.get(ent.split(".")[-1].lower(), set()):
                for action in ent_actions[base]:
                    tainted.add(base + "/" + action)
    indeterminate = sorted({u[0] for u in unref} & tainted)

    summary = {
        "surfacePaths": len(surface),
        "surfaceOps": sum(len(v) for v in surface.values()),
        "surfaceApp": sum(1 for p in surface if own.of_path(p) == "app"),
        "surfacePackage": sum(1 for p in surface if own.of_path(p) == "package"),
        "dynamicEntities": len(ent_actions),
        "referenced": len(referenced),
        "referencedInSurface": sum(1 for p in referenced if p in surface),
        "referencedNotInSurface": sum(1 for p in referenced if p not in surface),
        "unreferenced": len(unref),
        "unreferencedApp": len(app_unref),
        "unreferencedPackage": len(unref) - len(app_unref),
        "indeterminate": len(indeterminate),
        "unresolvableRefs": len(analysis["unresolvable"]),
        "opaqueRefs": analysis.get("opaqueCount", 0),
        "opaqueForms": len(opaque_forms),
        "entitiesBound": len(analysis["entity_bindings"]),
        "entitiesWithDynamicCrud": sum(1 for v in entity_hits.values() if v),
        "fullyUnusedEntities": len(fully_unused),
        "packageSourcesScanned": [s["name"] for s in (pkg or {}).get("sources", [])],
        "referencedByPackageSource": len(package_evidence),
        "referencedOnlyByPackageSource": sum(
            1 for k in package_evidence
            if k in referenced and all(kind.startswith(tuple(
                s["name"] + "-" for s in pkg["sources"])) for kind in referenced[k])),
        "packagePatternsUnresolved": len(pkg_patterns_unresolved),
    }
    for key in sorted(summary):
        print("  %-26s %s" % (key, summary[key]))

    print("\napp-owned unreferenced (%d):" % len(app_unref))
    for path, methods, _ in app_unref:
        print("   %-22s %s" % (",".join(methods), path))

    write_json(os.path.join(cache, "crossref.json"), {
        "summary": summary,
        "referenced": {k: sorted(v) for k, v in referenced.items()},
        "unreferenced": [[p, m, o] for p, m, o in unref],
        "indeterminate": indeterminate,
        "entityHits": entity_hits,
        "ownerHits": owner_hits,
        "entityRollup": rollup,
        "fullyUnusedEntities": fully_unused,
        "entActions": ent_actions,
        "surface": surface,
        "packageEvidence": {k: v for k, v in sorted(package_evidence.items())},
        "packagePatternsUnresolved": pkg_patterns_unresolved,
    })
    print("\nwritten %s" % os.path.join(cache, "crossref.json"))

    if not pkg:
        print("\nNOTE: no package_source_refs.json - endpoints called only by framework or "
              "Enterprise pages will read as unreferenced. Run scan_package_sources.py.")
    if summary["opaqueRefs"]:
        print("\nCONFIDENCE: reduced. %d opaque references in %d forms could reach any "
              "endpoint. The unreferenced list is a review starting point, not an apply list."
              % (summary["opaqueRefs"], summary["opaqueForms"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
