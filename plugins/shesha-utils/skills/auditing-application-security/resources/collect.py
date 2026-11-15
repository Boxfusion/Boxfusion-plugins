"""Collect every piece of live data the audit needs, once.

    python collect.py --url http://localhost:21021 [--user admin --password 123qwe]
                      [--repo-root .] [--skip-forms] [--refresh]

Writes into .claude/.audit-cache/<host>/ so that every later phase of the audit reads the
same snapshot instead of refetching. forms.json is routinely tens of megabytes and is the
slowest single call in the whole audit; it is skipped when a current copy exists unless
--refresh is passed.

Nothing here makes a security judgement. It fetches, records what failed, and stops.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shesha_audit import (PERMISSIONED_OBJECT_TYPES, authenticate, cache_dir,
                          detect_ownership, ensure_dir, get_json, read_json, request,
                          unwrap, write_json)

# name -> (path, needs_auth). Collected in this order.
ENDPOINTS = [
    ("entityconfigs", "/api/services/app/EntityConfig/GetMainDataList"
                      "?maxResultCount=10000&sorting=className", True),
    ("permissions", "/api/services/app/Permission/GetAll?maxResultCount=10000", True),
    ("roles", "/api/services/app/ShaRole/GetAll?maxResultCount=1000", True),
    ("modules", "/api/services/app/Module/GetAll?maxResultCount=1000", True),
    ("api-endpoints", "/api/services/app/Api/Endpoints?term=&maxResultCount=10000", True),
    ("security-settings", "/api/services/app/Settings/GetValue?name=Shesha.Security&module=Shesha", True),
    ("password-length", "/api/services/app/Settings/GetValue"
                        "?name=Abp.Zero.UserManagement.PasswordComplexity.RequiredLength&module=Shesha", True),
    # The main menu is how a form becomes reachable without any other form referencing it.
    # Without it, every menu-only landing page looks unreferenced.
    ("mainmenu", "/api/services/app/Settings/GetValue"
                 "?name=Shesha.MainMenuSettings&module=Shesha&appKey=default-app", True),
]

# ShaRole/GetAll returns `permissions: []` for every role on some versions, so the grants have
# to be read per role. The service name has moved between versions; try each in turn and
# record which one answered.
ROLE_EDIT_PATHS = [
    "/api/services/app/ShaRole/GetRoleForEdit?Id=%s",
    "/api/services/app/Role/GetRoleForEdit?Id=%s",
    "/api/services/app/ShaRole/Get?id=%s",
]


def fetch(base, path, token, label, cache, failures):
    url = base.rstrip("/") + path
    t0 = time.time()
    status, doc = get_json(url, token=token)
    took = time.time() - t0
    if status == 200 and doc is not None:
        write_json(os.path.join(cache, label + ".json"), doc)
        n = unwrap(doc)
        size = len(n) if isinstance(n, list) else "-"
        print("  ok   %-22s %5.1fs  items=%s" % (label, took, size))
        return doc
    failures.append({"label": label, "path": path, "status": status})
    print("  FAIL %-22s %5.1fs  HTTP %d%s"
          % (label, took, status,
             "  (403 = the audit account lacks the permission, NOT a missing endpoint)"
             if status == 403 else ""))
    return None


def collect_role_permissions(base, token, cache, failures):
    """roleId -> {name, permissions[]}. Needed for `rolesAssignedTo` on every permission."""
    roles_path = os.path.join(cache, "roles.json")
    if not os.path.isfile(roles_path):
        return
    roles = unwrap(read_json(roles_path)) or []
    if not isinstance(roles, list):
        return
    out, working, tried = {}, None, []
    for role in roles:
        rid = role.get("id")
        if not rid:
            continue
        paths = [working] if working else ROLE_EDIT_PATHS
        perms, hit = None, None
        for tmpl in paths:
            status, doc = get_json(base + (tmpl % rid), token=token, timeout=60)
            if status == 200 and doc:
                res = doc.get("result") or {}
                inner = res.get("role") if isinstance(res.get("role"), dict) else res
                perms = (res.get("grantedPermissionNames")
                         or res.get("grantedPermissions")
                         or inner.get("permissions")
                         or inner.get("grantedPermissionNames") or [])
                hit = tmpl
                break
        if hit:
            working = hit
            if hit not in tried:
                tried.append(hit)
        out[rid] = {
            "id": rid,
            "name": (role.get("name") or "").strip(),
            "moduleId": role.get("module") or role.get("moduleId"),
            "permissions": [p.get("name") if isinstance(p, dict) else p
                            for p in (perms or []) if p],
            "resolved": hit is not None,
        }
    write_json(os.path.join(cache, "role-permissions.json"),
               {"servicePathUsed": tried, "roles": out})
    unresolved = [r["name"] for r in out.values() if not r["resolved"]]
    print("  ok   role-permissions       %d roles, %d with grants read"
          % (len(out), len(out) - len(unresolved)))
    if unresolved:
        failures.append({"label": "role-permissions", "unresolvedRoles": unresolved})
        print("  WARN no GetRoleForEdit path answered for %d role(s): %s"
              % (len(unresolved), ", ".join(unresolved[:6])))
        print("       `rolesAssignedTo` will be incomplete - say so in the report, do not")
        print("       report those permissions as granted to nobody.")


def collect_entity_permissions(base, token, cache, failures, limit=None):
    """Per-entity CRUD permission configuration, from ModelConfigurations/{id}.

    One request per entity, so it is the second-slowest step after forms.json. It is what
    makes `authorizationRules` on an entity real rather than inferred from the global
    default, so skip it only deliberately.
    """
    path = os.path.join(cache, "entityconfigs.json")
    if not os.path.isfile(path):
        return
    entities = unwrap(read_json(path)) or []
    if limit:
        entities = entities[:limit]
    out, misses = {}, 0
    t0 = time.time()
    for i, ent in enumerate(entities):
        eid, full = ent.get("id"), ent.get("fullClassName")
        if not eid or not full:
            continue
        status, doc = get_json(base + "/api/ModelConfigurations/%s" % eid,
                               token=token, timeout=60)
        if status != 200 or not doc:
            misses += 1
            continue
        res = doc.get("result") or doc
        out[full] = {
            "module": res.get("module") or ent.get("module"),
            "generateAppService": res.get("generateAppService"),
            "permission": res.get("permission"),
            "permissionGet": res.get("permissionGet"),
            "permissionCreate": res.get("permissionCreate"),
            "permissionUpdate": res.get("permissionUpdate"),
            "permissionDelete": res.get("permissionDelete"),
        }
        if (i + 1) % 50 == 0:
            print("       ... %d/%d entities (%.0fs)" % (i + 1, len(entities), time.time() - t0))
    write_json(os.path.join(cache, "entity-permissions.json"), out)
    print("  ok   entity-permissions     %d entities, %d unreadable (%.0fs)"
          % (len(out), misses, time.time() - t0))
    if misses:
        failures.append({"label": "entity-permissions", "unreadable": misses})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:21021")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="123qwe")
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--skip-forms", action="store_true")
    ap.add_argument("--skip-entity-permissions", action="store_true",
                    help="skip the per-entity ModelConfigurations pass (one call per entity)")
    ap.add_argument("--max-entity-permissions", type=int, default=None)
    ap.add_argument("--refresh", action="store_true",
                    help="refetch forms.json even if a cached copy exists")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    cache = args.cache or cache_dir(args.repo_root, base)
    ensure_dir(cache)
    failures = []

    print("cache: %s" % cache)

    status, _ = get_json(base + "/api/TokenAuth/GetExternalAuthenticationProviders")
    if status == 0:
        print("Backend is not answering at %s. Start it first - references/dev-servers.md." % base,
              file=sys.stderr)
        return 2

    token, auth_status = authenticate(base, args.user, args.password)
    print("auth: %s (HTTP %d)%s"
          % ("accepted" if token else "REJECTED", auth_status,
             "  <- default credentials work: audit finding E4" if token else
             "  <- good: default credentials rejected. Supply working ones with --user/--password."))
    if not token:
        print("Continuing with anonymous collection only; permissioned collections will fail.")

    print("\nPermissionedObject records:")
    po_counts = {}
    for potype in PERMISSIONED_OBJECT_TYPES:
        label = "po-" + potype.replace(".", "-").lower()
        doc = fetch(base, "/api/services/app/PermissionedObject/GetAllFlat"
                          "?type=%s&showNested=true&withHidden=true" % potype,
                    token, label, cache, failures)
        recs = unwrap(doc) if doc else []
        po_counts[potype] = len(recs) if isinstance(recs, list) else 0

    print("\nConfiguration and settings:")
    for label, path, needs_auth in ENDPOINTS:
        fetch(base, path, token if needs_auth else None, label, cache, failures)

    print("\nRole grants and entity permissions:")
    collect_role_permissions(base, token, cache, failures)
    if args.skip_entity_permissions:
        print("  skip entity-permissions     (--skip-entity-permissions). Entity "
              "authorizationRules will fall back to DefaultEndpointAccess only.")
    else:
        collect_entity_permissions(base, token, cache, failures,
                                   limit=args.max_entity_permissions)

    print("\nOpenAPI surface:")
    swagger_path = os.path.join(cache, "swagger.json")
    # OpenAPI generation on a large Shesha app intermittently exceeds its time or memory
    # budget and returns 500 with an empty body. It usually succeeds on a retry, and the
    # surface is what lets probe.py tell a disabled endpoint from a wrong route - so it is
    # worth a few attempts rather than degrading the rest of the audit.
    doc = None
    for attempt in range(1, 4):
        status, doc = get_json(base + "/swagger/v1/swagger.json", timeout=300)
        if doc:
            break
        print("  ..   swagger.json attempt %d returned %d; retrying" % (attempt, status))
        time.sleep(5 * attempt)
    surface = {"fresh": bool(doc), "status": status, "cachedCopyFrom": None,
               "liveOnlyPaths": None, "liveOnlySample": []}
    if doc:
        write_json(swagger_path, doc)
        print("  ok   swagger.json           paths=%d" % len(doc.get("paths") or {}))
    else:
        failures.append({"label": "swagger", "path": "/swagger/v1/swagger.json",
                         "status": status})
        if os.path.isfile(swagger_path) and os.path.getsize(swagger_path) > 0:
            surface["cachedCopyFrom"] = time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(swagger_path)))
            print("  WARN swagger.json returned %d; FALLING BACK to the cached copy from %s. "
                  "Endpoints added since then are NOT in this audit, and the catalogue will "
                  "record the surface as stale. Fix Swagger generation (look for the exception "
                  "in the backend log) rather than accepting this."
                  % (status, surface["cachedCopyFrom"]))
        else:
            print("  FAIL swagger.json returned %d and no cached copy exists. Without a "
                  "surface, a 404 cannot be told apart from a wrong route." % status)

    # Cross-check against Shesha's own endpoint list. The list has no HTTP verbs, so it cannot
    # replace Swagger, but it does reflect what is actually served: a Swagger captured on the
    # start that bootstrapped new entity configurations silently omits their CRUD routes.
    try:
        with open(swagger_path, encoding="utf-8") as fh:
            surface_paths = {p.lower() for p in (json.load(fh).get("paths") or {})}
        with open(os.path.join(cache, "api-endpoints.json"), encoding="utf-8") as fh:
            listed = json.load(fh)
        listed = listed.get("result", listed) if isinstance(listed, dict) else listed
        live = {(i.get("value") or "").split("?")[0].rstrip("/").lower()
                for i in (listed or []) if isinstance(i, dict)}
        live_only = sorted(p for p in live - surface_paths if p.startswith("/api/"))
        surface["liveOnlyPaths"] = len(live_only)
        surface["liveOnlySample"] = live_only[:20]
        level = "WARN" if len(live_only) > 25 else "ok  "
        print("  %s live endpoint list vs surface: %d live path(s) absent from the surface%s"
              % (level, len(live_only), " - the surface UNDER-REPORTS the API" if
                 level == "WARN" else ""))
    except (OSError, ValueError):
        print("  ..   could not cross-check the surface against the live endpoint list")

    if not args.skip_forms:
        print("\nForm configurations (the slow one):")
        forms_path = os.path.join(cache, "forms.json")
        if os.path.isfile(forms_path) and os.path.getsize(forms_path) > 0 and not args.refresh:
            mb = os.path.getsize(forms_path) / 1e6
            print("  skip forms.json exists (%.1f MB). Pass --refresh to refetch." % mb)
        else:
            t0 = time.time()
            status, raw = request("GET", base + "/api/services/Shesha/FormConfiguration/GetAll"
                                               "?maxResultCount=10000",
                                  token=token, timeout=900)
            if status == 200:
                with open(forms_path, "wb") as fh:
                    fh.write(raw)
                print("  ok   forms.json            %5.1fs  %.1f MB"
                      % (time.time() - t0, len(raw) / 1e6))
            else:
                failures.append({"label": "forms", "status": status})
                print("  FAIL forms.json HTTP %d%s" % (status,
                      "  (403 = needs app:Configurator)" if status == 403 else ""))

    ownership = detect_ownership(args.repo_root)
    write_json(os.path.join(cache, "ownership.json"), ownership.to_dict())
    print("\nOwnership detected from source:")
    print("  appModules:     %s" % ", ".join(sorted(ownership.app_modules)) or "(none)")
    print("  appUrlSegments: %s" % ", ".join(sorted(ownership.app_url_segments)) or "(none)")
    print("  controller prefixes: %d" % len(ownership.app_path_prefixes))

    write_json(os.path.join(cache, "collection-report.json"), {
        "backend": base, "authenticated": token is not None,
        "defaultCredentialsAccepted": token is not None,
        "permissionedObjectCounts": po_counts, "failures": failures,
        "surface": surface,
    })

    print("\n%d collection failure(s)." % len(failures))
    for f in failures:
        print("  %s -> HTTP %s" % (f["label"], f["status"]))
    empty = [k for k, v in po_counts.items() if v == 0]
    if empty:
        print("\nPermissionedObject types with ZERO records: %s" % ", ".join(empty))
        print("  On Shesha 0.43.x an empty Shesha.Entity / Shesha.Entity.Action is normal -")
        print("  EntityPermissionedObjectProvider is not active, so entity access resolves")
        print("  entirely through DefaultEndpointAccess. Report it; do not re-derive it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
