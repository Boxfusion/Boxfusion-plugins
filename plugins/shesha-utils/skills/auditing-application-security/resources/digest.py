"""Reduce the catalogue to the actionable rows, per package, in priority order.

    python digest.py --run-dir security-audits/YYMMDD-HHMM [--package Shesha.Hcm]
                     [--limit 12] [--json]

The catalogue is complete by design and far too large to read: 60-odd JSON files, most rows
saying "KEEP". This prints only what a recommendation would be written about, already sorted,
so the report can be written from one screen per package instead of from every file.

It selects and orders. It does not write prose, assign a final severity, or decide that an
anonymous endpoint is acceptable - those are the review phase's actual work, and the digest
is deliberately terse so it cannot be pasted into a report and passed off as one.
"""

import argparse
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from shesha_audit import latest_run_dir, read_json, write_json  # noqa: E402

# (priority, theme). Lower priority number is more urgent. The order is the order the
# recommendations report must present sections in.
THEME = {
    "SET-EXPLICIT-ACCESS": (1, "Reachable without logging in"),
    "FIX-EMPTY-PERMISSION-SET": (2, "Permission rules that block everyone"),
    "RESTRICT": (3, "Open to every logged-in user"),
    "ADD-GLOBAL-SPECIFICATION": (4, "Users can see other people's records"),
    "DISABLE-ENTITY": (5, "Unused data APIs"),
    "DISABLE-ACTION": (5, "Unused data APIs"),
    "DISABLE-ENDPOINT": (6, "Unused endpoints"),
    "REVIEW-FOR-REMOVAL": (7, "Screens and forms nothing opens"),
    "REMOVE-OR-WIRE-UP": (8, "Permissions that do nothing"),
    "GRANT-TO-A-ROLE": (8, "Permissions that do nothing"),
    "REVIEW": (9, "Needs a decision before anything is changed"),
}
SEVERITY_PRIORITY = {"CRITICAL": 0, "HIGH": 2, "MEDIUM": 5, "WARN": 7, "LOW": 8, "INFO": 9}
SENSITIVITY_BUMP = {"HIGH": -1, "MEDIUM": 0, "LOW": 1}


def rank(action, sensitivity=None, access=None, override_theme=None):
    priority, theme = THEME.get(action, (9, "Other"))
    if override_theme:
        theme = override_theme
    if sensitivity:
        priority += SENSITIVITY_BUMP.get(sensitivity, 0)
    if access == 5:
        priority = min(priority, 1)
    return priority, theme


def load(run_dir, package=None):
    catalog = os.path.join(run_dir, "catalog")
    if not os.path.isdir(catalog):
        return None, None
    index = read_json(os.path.join(catalog, "_index.json")) \
        if os.path.isfile(os.path.join(catalog, "_index.json")) else {"packages": {}}
    docs = collections.defaultdict(dict)
    for path in sorted(glob.glob(os.path.join(catalog, "*.json"))):
        name = os.path.basename(path)
        if name.startswith("_index"):
            continue
        doc = read_json(path)
        pkg, kind = doc.get("package"), doc.get("artifact")
        if not pkg or not kind:
            continue
        if package and pkg != package:
            continue
        docs[pkg][kind] = doc
    return index, docs


def items_for(pkg, docs):
    """Every actionable row for one package, as (priority, theme, kind, label, detail)."""
    out = []

    for row in (docs.get("endpoints") or {}).get("endpoints", []):
        action = row["recommendedAction"]
        if action in ("KEEP", "KEEP-INFRA"):
            continue
        access = row["authorizationRules"]["effectiveAccess"]
        priority, theme = rank(action, row["sensitivity"]["rating"], access,
                               row.get("reviewTheme"))
        out.append({
            "priority": priority, "theme": theme, "kind": "endpoint",
            "action": action, "where": row["path"],
            "detail": "%s | %s | %s%s%s" % (
                ",".join(row["methods"]),
                row["authorizationRules"]["effectiveAccessName"],
                row["recommendationBasis"],
                "" if row["hasPermissionedObjectConfig"] else " | no permission record",
                " | HARDCODED, a config change will not stick"
                if row["authorizationRules"].get("hardcoded") else ""),
            "sensitivity": row["sensitivity"]["rating"],
            "referencedBy": (row["referencedByForms"] + row["referencedByCustomForms"])[:3],
            "backendCallers": row["backendCodeReferences"],
        })

    for row in (docs.get("entities") or {}).get("entities", []):
        action = row["recommendedAction"]
        if action == "KEEP":
            continue
        access = row["authorizationRules"]["effectiveAccess"]
        priority, theme = rank(action, row["sensitivity"]["rating"], access,
                               row.get("reviewTheme"))
        out.append({
            "priority": priority, "theme": theme, "kind": "entity",
            "action": action, "where": row["entity"],
            "detail": "CRUD=%s | %s | %s%s" % (
                row["CRUDEndpoints"] or "-",
                row["authorizationRules"]["effectiveAccessName"],
                row["recommendationBasis"],
                "" if row["hasGlobalSpecifications"] else " | no row-level filter"),
            "sensitivity": row["sensitivity"]["rating"],
            "referencedBy": (row["referencedByForms"] + row["referencedByCustomForms"])[:3],
            "backendCallers": row["backendCodeReferences"],
        })

    for kind in ("configured-forms", "custom-forms"):
        for row in (docs.get(kind) or {}).get("forms", []):
            action = row.get("recommendedAction")
            if action in ("KEEP", None):
                continue
            access = (row.get("accessConfig") or {}).get("access")
            priority, theme = rank(action, row["sensitivity"]["rating"], access,
                                   row.get("reviewTheme"))
            out.append({
                "priority": priority, "theme": theme,
                "kind": "form" if kind == "configured-forms" else "coded screen",
                "action": action,
                "where": row.get("form") or row.get("file"),
                "detail": row.get("recommendationBasis") or "",
                "sensitivity": row["sensitivity"]["rating"],
                "referencedBy": [], "backendCallers": 0,
            })

    rp = docs.get("roles-and-permissions") or {}
    for row in rp.get("permissions", []):
        action = row["recommendedAction"]
        if action == "KEEP":
            continue
        priority, theme = rank(action)
        out.append({
            "priority": priority, "theme": theme, "kind": "permission",
            "action": action, "where": row["permission"],
            "detail": "%s | roles: %s" % (row["recommendationBasis"],
                                          ", ".join(row["rolesAssignedTo"]) or "none"),
            "sensitivity": "LOW", "referencedBy": [], "backendCallers": 0,
        })
    for row in rp.get("roles", []):
        if row["recommendedAction"] == "KEEP":
            continue
        priority, theme = rank(row["recommendedAction"])
        out.append({
            "priority": priority, "theme": theme, "kind": "role",
            "action": row["recommendedAction"], "where": row["role"],
            "detail": row["recommendationBasis"], "sensitivity": "LOW",
            "referencedBy": [], "backendCallers": 0,
        })

    for row in (docs.get("other-findings") or {}).get("findings", []):
        priority = SEVERITY_PRIORITY.get(row["severityHint"], 9)
        out.append({
            "priority": priority,
            "theme": row.get("reviewTheme") or {"web-host-configuration": "How the application is hosted",
                      "settings-and-secrets": "Secrets and settings",
                      "committed-secret": "Secrets and settings",
                      "controller-without-authorization": "Code with no access check",
                      "row-level-security": "Users can see other people's records",
                      "token-policy": "Login sessions and tokens",
                      "rate-limiting": "No limit on repeated attempts",
                      "dependency-advisory": "Out-of-date libraries",
                      "anonymous-access": "Reachable without logging in",
                      "authenticated-access": "Open to every logged-in user",
                      "object-level-authorization":
                          "Users can see other people's records"}.get(
                              row["category"], "Other"),
            "kind": "finding", "action": row["severityHint"],
            "where": row["title"],
            "detail": "%s | %s" % ("; ".join(str(e) for e in row["evidence"][:2])[:220],
                                   row["recommendationHint"]),
            "sensitivity": "HIGH" if row["severityHint"] in ("CRITICAL", "HIGH") else "LOW",
            "referencedBy": [], "backendCallers": 0, "status": row.get("status"),
        })

    out.sort(key=lambda r: (r["priority"], r["kind"], r["where"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default=None)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--package", action="append")
    ap.add_argument("--limit", type=int, default=12,
                    help="rows printed per theme; the counts always reflect the whole set")
    ap.add_argument("--json", action="store_true", help="also write digest.json")
    args = ap.parse_args()

    run_dir = args.run_dir or latest_run_dir(args.repo_root)
    if not run_dir:
        print("No run directory. Run build_catalogs.py first.", file=sys.stderr)
        return 2
    index, docs = load(run_dir, None)
    if docs is None:
        print("No catalog/ in %s. Run build_catalogs.py first." % run_dir, file=sys.stderr)
        return 2

    missing = index.get("inputsMissing") or []
    if missing:
        print("INPUTS MISSING when the catalogue was built: %s" % ", ".join(missing))
        if any("mainmenu" in m for m in missing):
            print("  Without the main menu, a form reachable only from the menu looks "
                  "unreferenced. Do NOT report those as unused until the menu is read.")
        if any("role-permissions" in m for m in missing):
            print("  Without role grants, `rolesAssignedTo` is empty everywhere - that is "
                  "missing data, not evidence that no role holds a permission.")
        print("")

    wanted = set(args.package) if args.package else None
    digest = {}
    order = sorted(docs, key=lambda p: (
        0 if (index["packages"].get(p, {}).get("owner") == "app") else
        1 if p.startswith("_") else 2, p))

    for pkg in order:
        if wanted and pkg not in wanted:
            continue
        items = items_for(pkg, docs[pkg])
        digest[pkg] = items
        owner = index["packages"].get(pkg, {}).get("owner", "?")
        print("\n" + "=" * 100)
        print("PACKAGE %s   (%s)   %d actionable row(s)" % (pkg, owner, len(items)))
        print("=" * 100)
        if not items:
            print("  nothing to recommend")
            continue
        # Group by theme, ordering themes by their most urgent row. One theme must appear
        # once: a report with "How the application is hosted" three times reads as noise.
        grouped = collections.defaultdict(list)
        for item in items:
            grouped[item["theme"]].append(item)
        for theme, rows in sorted(grouped.items(),
                                  key=lambda kv: (min(r["priority"] for r in kv[1]), kv[0])):
            priority = min(r["priority"] for r in rows)
            print("\n  [p%d] %s  (%d)" % (priority, theme, len(rows)))
            for row in rows[:args.limit]:
                print("     %-9s %-13s %s" % (row["action"][:9], row["kind"], row["where"]))
                if row["detail"]:
                    print("               %s" % row["detail"][:150])
                if row["referencedBy"]:
                    print("               used by: %s" % ", ".join(row["referencedBy"]))
            if len(rows) > args.limit:
                print("     ... and %d more in the catalogue (summarise, do not enumerate)"
                      % (len(rows) - args.limit))

    print("\n" + "=" * 100)
    print("TOP FIVE ACROSS ALL PACKAGES (candidate 'act now' list - confirm each)")
    print("=" * 100)
    flat = [(item, pkg) for pkg, items in digest.items() for item in items]
    flat.sort(key=lambda t: (t[0]["priority"],
                             0 if index["packages"].get(t[1], {}).get("owner") == "app" else 1))
    for item, pkg in flat[:5]:
        print("  [p%d] %-26s %-9s %s" % (item["priority"], pkg, item["action"],
                                          item["where"][:70]))

    if args.json:
        path = os.path.join(run_dir, "catalog", "digest.json")
        write_json(path, digest)
        print("\nwritten %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
