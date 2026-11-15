"""Compare two collect.py captures of the same application: before/after a framework upgrade,
or first start/second start of the same build. Reports security drift a single-snapshot audit
cannot see.

    python drift.py --before <cache-dir-A> --after <cache-dir-B> [--json drift.json]
                    [--admin-role "System Administrator" ...] [--fail-on widened,reset,gone]

Each cache dir is what `collect.py --cache <dir>` (plus `analyze_forms.py --cache <dir>` for
the form check) writes: po-*.json, roles.json, swagger.json, form_analysis.json.

Why this exists. Three real regressions slipped through audits that looked at one snapshot:

  * WIDENED - a framework upgrade changed a built-in endpoint's requirement from one
    permission to "either of two". A front-line role held the second one (renamed from an
    old grant), so it could reset an administrator's password and sign in as them. Before the
    upgrade the same endpoint inherited a permission those roles did not hold.
  * RESET - the upgraded framework marks some services not configurable and re-applies their
    hard-coded requirement at start-up. A custom, tighter record written by an app migration
    was silently replaced on the first start after deploy.
  * GONE - the upgrade removed generic CRUD routes (e.g. a role-appointment entity's
    Create/Delete moved to a dedicated actions service). Forms still called the old routes and
    failed with 404 for everyone, admin included.

Run it twice per upgrade: (1) old build vs new build on the same database copy, and (2) new
build first start vs new build after a restart, to prove custom records survive start-up.
Output is sorted and stable so two runs on the same inputs are byte-identical.
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
from shesha_audit import ACCESS, load_surface, unwrap  # noqa: E402

PO_TYPES = ("shesha-webapi", "shesha-webapi-action", "shesha-entity", "shesha-entity-action",
            "shesha-webcrudapi", "shesha-webcrudapi-action", "shesha-form")

# Access levels ordered from most open to most closed, for "widened"/"narrowed".
OPENNESS = {5: 0, 3: 1, 4: 2, 1: 3}  # AllowAnonymous, AnyAuthenticated, RequiresPermissions, Disable
DEFAULT_ADMIN_HINTS = ("administrator", "admin", "configurator")


def load(cache, name):
    path = os.path.join(cache, name)
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return None
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def records(cache):
    out = {}
    for potype in PO_TYPES:
        for rec in unwrap(load(cache, "po-%s.json" % potype)) or []:
            obj = rec.get("object")
            if not obj:
                continue
            out[obj] = {
                "type": rec.get("type") or potype,
                "access": rec.get("actualAccess"),
                "permissions": sorted(rec.get("actualPermissions") or []),
                "hardcoded": bool(rec.get("hardcoded")),
                "inherited": bool(rec.get("inherited")),
            }
    return out


def role_grants(cache):
    out = {}
    for role in unwrap(load(cache, "roles.json")) or []:
        name = role.get("name")
        if name:
            out[name] = sorted(p for p in (role.get("permissions") or []) if p)
    return out


def surface(cache):
    doc = load(cache, "swagger.json")
    try:
        return load_surface(doc) if doc else {}
    except (ValueError, AttributeError):
        return {}


def form_routes(cache):
    """{lowercased route: sorted forms} for every route a form calls, live or stale."""
    doc = load(cache, "form_analysis.json") or {}
    out = collections.defaultdict(set)
    for key in ("form_config_endpoints", "js_endpoints", "nav_urls", "stale"):
        block = doc.get(key) or {}
        if isinstance(block, dict):
            for route, forms in block.items():
                norm = route.split("?")[0].rstrip("/").lower()
                if norm.startswith("/api/"):
                    out[norm].update(forms if isinstance(forms, list) else [forms])
    return {k: sorted(v) for k, v in out.items()}


def holders(grants, permission):
    return sorted(r for r, perms in grants.items() if permission in perms)


def is_admin(role, admin_roles):
    if admin_roles:
        return role in admin_roles
    low = role.lower()
    return any(h in low for h in DEFAULT_ADMIN_HINTS)


def compare(before, after, admin_roles):
    rb, ra = records(before), records(after)
    gb, ga = role_grants(before), role_grants(after)
    sb, sa = surface(before), surface(after)
    findings = []

    for obj in sorted(set(rb) & set(ra)):
        b, a = rb[obj], ra[obj]
        if (b["access"], b["permissions"]) == (a["access"], a["permissions"]):
            continue
        row = {"object": obj, "type": a["type"],
               "before": {"access": ACCESS.get(b["access"], b["access"]),
                          "permissions": b["permissions"], "hardcoded": b["hardcoded"]},
               "after": {"access": ACCESS.get(a["access"], a["access"]),
                         "permissions": a["permissions"], "hardcoded": a["hardcoded"]}}
        ob, oa = OPENNESS.get(b["access"], 1), OPENNESS.get(a["access"], 1)
        added = sorted(set(a["permissions"]) - set(b["permissions"]))
        non_admin_gain = sorted({r for p in added for r in holders(ga, p)
                                 if not is_admin(r, admin_roles)})
        if oa < ob:
            kind = "WIDENED"
            row["why"] = "access level opened"
        elif a["access"] == 4 and b["access"] == 4 and added and non_admin_gain:
            # Requirements are OR-ed: adding a permission widens who passes.
            kind = "WIDENED"
            row["why"] = ("requirement now also accepts %s, held by non-admin role(s) %s"
                          % (", ".join(added), ", ".join(non_admin_gain)))
        elif a["hardcoded"] and not b["hardcoded"]:
            kind = "RESET"
            row["why"] = ("record is now hard-coded by the framework; a configured value is "
                          "replaced at start-up and cannot be kept by migration")
        elif oa > ob:
            kind = "NARROWED"
            row["why"] = "access level closed - check nobody who needs it lost it"
        else:
            kind = "CHANGED"
            row["why"] = "permission list changed"
        row["kind"] = kind
        if non_admin_gain:
            row["nonAdminRolesGained"] = non_admin_gain
        findings.append(row)

    for obj in sorted(set(rb) - set(ra)):
        findings.append({"kind": "RECORD-GONE", "object": obj, "type": rb[obj]["type"],
                         "why": "record no longer exists - a custom rule on it is lost"})

    # Role grants: renamed or dropped permissions change who passes every rule.
    for role in sorted(set(gb) | set(ga)):
        lost = sorted(set(gb.get(role, [])) - set(ga.get(role, [])))
        gained = sorted(set(ga.get(role, [])) - set(gb.get(role, [])))
        if lost or gained:
            findings.append({"kind": "GRANTS", "object": role,
                             "lost": lost, "gained": gained,
                             "why": "role's permissions changed (often a framework rename, "
                                    "e.g. an old page permission mapped to a new one)"})

    # Routes removed by the upgrade, and the forms that still call them.
    calls = form_routes(after) or form_routes(before)
    if sb and sa:
        for route in sorted(set(sb) - set(sa)):
            row = {"kind": "ROUTE-GONE", "object": route, "methods": sb[route],
                   "why": "route served before, not after"}
            if calls.get(route):
                row["kind"] = "FORM-CALLS-GONE"
                row["forms"] = calls[route]
                row["why"] = "forms still call a route the new version does not serve (404)"
            findings.append(row)
    if sa:
        for route, forms in sorted(calls.items()):
            if route not in sa and route not in sb and "{" not in route:
                findings.append({"kind": "FORM-CALLS-MISSING", "object": route, "forms": forms,
                                 "why": "forms call a route the running version does not serve"})

    order = {"WIDENED": 0, "FORM-CALLS-GONE": 1, "RESET": 2, "RECORD-GONE": 3,
             "FORM-CALLS-MISSING": 4, "GRANTS": 5, "NARROWED": 6, "CHANGED": 7,
             "ROUTE-GONE": 8}
    findings.sort(key=lambda f: (order.get(f["kind"], 9), f["object"]))
    counts = collections.Counter(f["kind"] for f in findings)
    inputs = {"before": {"records": len(rb), "roles": len(gb), "routes": len(sb)},
              "after": {"records": len(ra), "roles": len(ga), "routes": len(sa)}}
    return {"counts": dict(sorted(counts.items())), "inputs": inputs, "findings": findings}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True, help="collect.py cache dir: old build / first start")
    ap.add_argument("--after", required=True, help="collect.py cache dir: new build / restart")
    ap.add_argument("--admin-role", action="append",
                    help="role names that are administrative (repeatable). Default: any role "
                         "whose name contains administrator/admin/configurator")
    ap.add_argument("--json", default=None)
    ap.add_argument("--fail-on", default="WIDENED,RESET,RECORD-GONE,FORM-CALLS-GONE",
                    help="comma-separated kinds that make the exit code 1")
    args = ap.parse_args()

    result = compare(args.before, args.after, set(args.admin_role or []))
    for side in ("before", "after"):
        if not result["inputs"][side]["records"]:
            print("WARNING: no PermissionedObject records in the %s capture - run collect.py "
                  "--cache <dir> against that build first. Nothing can be compared." % side,
                  file=sys.stderr)
    for side in ("before", "after"):
        if not result["inputs"][side]["routes"]:
            print("NOTE: no swagger.json in the %s capture - removed routes cannot be listed."
                  % side, file=sys.stderr)

    print("%-20s %s" % ("KIND", "OBJECT / WHY"))
    print("-" * 100)
    for f in result["findings"]:
        print("%-20s %s" % (f["kind"], f["object"][:78]))
        print("%-20s   %s" % ("", f["why"]))
        if f.get("forms"):
            print("%-20s   forms: %s" % ("", ", ".join(f["forms"][:6])))
    print("\n" + json.dumps(result["counts"], indent=2))

    if args.json:
        with io.open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print("written %s" % args.json)

    fail = {k.strip() for k in args.fail_on.split(",") if k.strip()}
    return 1 if any(f["kind"] in fail for f in result["findings"]) else 0


if __name__ == "__main__":
    sys.exit(main())
