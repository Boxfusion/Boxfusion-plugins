"""Generate probes for this application from its own catalogue.

    python extend_probe_matrix.py --run-dir security-audits/YYMMDD-HHMM [--dry-run]
                                 [--prune] [--include-writes] [--max 250]

`probe_matrix.json` ships the framework surface - the endpoints every Shesha application has.
The application's own surface is different on every deployment, and the skill has always said
to extend the matrix from the catalogue. Nobody did: the first full run of this skill left the
matrix untouched, so the three `ConfigurationItemUtilities` routes that turned out to be the
most interesting app-specific finding were never probed. They were found by reading an
unattributed bucket by hand.

This closes that loop. From the catalogue it generates:

  * an anonymous probe for every endpoint whose effective access resolves to AllowAnonymous
  * a low-privilege probe for every sensitive endpoint open to any authenticated user
  * an anonymous and a low-privilege GetAll for every sensitive entity with a live read route

Safety. A generated probe is READ-ONLY unless you ask otherwise: an endpoint whose action
changes state gets a probe with `enabled: false` and a note, because "probe every unprotected
write endpoint" and "corrupt the database" are the same request. `probe.py` skips disabled
probes unless `--include-disabled` is passed.

Generated probes carry `generatedFrom`, so `--prune` can drop and regenerate them without
touching the hand-maintained ones.
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
from digest import load  # noqa: E402
from shesha_audit import read_json, write_json  # noqa: E402

MARKER = "extend_probe_matrix"

# Action-name prefixes that only read. Anything else is treated as state-changing, whatever
# its HTTP verb says - a POST called `Search` is a read, and a GET called `SendEmail` is not.
READ_PREFIXES = ("get", "query", "list", "search", "find", "check", "validate", "count",
                 "exists", "download", "preview", "resolve", "fetch", "read", "is", "has",
                 "available", "my", "details", "conventions", "settings", "endpoints",
                 "specifications", "metadata", "gateways", "timeline", "progress")
WRITE_PREFIXES = ("create", "update", "delete", "remove", "save", "submit", "approve",
                  "reject", "cancel", "import", "export", "enqueue", "start", "run",
                  "trigger", "execute", "send", "reset", "set", "assign", "complete",
                  "replace", "sync", "close", "reopen", "amend", "finalize", "finalise",
                  "generate", "link", "accept", "invite", "reassign", "resubmit", "resume",
                  "suspend", "process", "upload", "clear", "merge", "reorder")


def is_read_only(action, methods):
    a = (action or "").lower()
    if a.startswith(WRITE_PREFIXES):
        return False
    if a.startswith(READ_PREFIXES):
        return True
    # Unknown verb: trust the HTTP method, and treat anything but GET/HEAD as a write.
    return all(m in ("GET", "HEAD", "OPTIONS") for m in methods)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:70]


def probe_key(method, path, auth=None):
    """Identity of a probe. The principal is part of it: an anonymous and a low-privilege read
    of the same route answer different questions, and keying on method+path alone silently
    discarded every low-privilege entity read as a duplicate of its anonymous twin."""
    return (method.upper(), path.split("?")[0].rstrip("/").lower(), (auth or "anonymous").lower())


def expectation(row):
    """What a probe against this row should expect, taken from the reviewed disposition.

    An endpoint the review kept - login, password reset, OTP, public form loading - is
    SUPPOSED to answer anonymously. Generating `expect: denied` for those manufactures a
    false finding on every run, which is the fastest way to get a probe matrix ignored.
    """
    action = row.get("recommendedAction")
    if action in ("KEEP", "KEEP-INFRA"):
        return "anonymous-ok", "expected-anonymous per the reviewed disposition (%s)" % action
    if action == "REVIEW":
        return "judgement", "the review left this undecided - a human reads the result"
    return "denied", None


def pick_method(methods, read_only):
    """The verb to probe with. Prefer GET for a read; otherwise the first state-changer."""
    order = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"]
    available = [m for m in order if m in methods]
    if not available:
        return None
    if read_only:
        for m in ("GET", "HEAD", "POST"):
            if m in available:
                return m
    return available[0]


def generate(docs, args):
    """(probes, stats). Every probe carries why it was generated."""
    out, stats = [], collections.Counter()

    for pkg, kinds in sorted(docs.items()):
        for row in (kinds.get("endpoints") or {}).get("endpoints", []):
            path = row["path"]
            if "{" in path:
                stats["skipped-templated"] += 1
                continue
            access = row["authorizationRules"]["effectiveAccess"]
            sens = row["sensitivity"]["rating"]
            action = row.get("action") or ""
            methods = row.get("methods") or []
            read_only = is_read_only(action, methods)
            method = pick_method(methods, read_only)
            if not method:
                continue

            if access == 5:
                # Anonymous. Worth probing whatever it does, because the question is whether
                # an unauthenticated caller reaches it at all.
                expect, why = expectation(row)
                probe = {
                    "id": "gen-anon-%s" % slug(path),
                    "group": "generated-anonymous",
                    "method": method,
                    "path": path,
                    "auth": "anonymous",
                    "expect": expect,
                    "severityIfOpen": "CRITICAL" if sens == "HIGH" else "HIGH",
                    "description": "%s resolves to AllowAnonymous (%s, %s data)"
                                   % (path, pkg, sens.lower()),
                    "enabled": read_only or args.include_writes,
                    "body": {} if method in ("POST", "PUT", "PATCH") else None,
                    "generatedFrom": {"marker": MARKER, "package": pkg, "reason":
                                      "effectiveAccess=AllowAnonymous",
                                      "readOnly": read_only},
                }
                if why:
                    probe["note"] = why
                out.append(probe)
                stats["anonymous"] += 1
                stats["anonymous-" + expect] += 1
                if not (read_only or args.include_writes):
                    stats["anonymous-disabled-write"] += 1

            elif access == 3 and sens == "HIGH" and (read_only or args.include_writes):
                # A low-privilege probe exists to turn one derived claim - "any logged-in
                # user can reach this" - into an observation. A handful per package does
                # that; 250 disabled write probes only bloat the matrix, and a matrix nobody
                # reads is worse than a smaller one that gets maintained.
                if not args.lowpriv_probes:
                    continue
                if stats["lowpriv-" + pkg] >= args.per_package:
                    stats["skipped-lowpriv-over-cap"] += 1
                    continue
                stats["lowpriv-" + pkg] += 1
                out.append({
                    "id": "gen-lowpriv-%s" % slug(path),
                    "group": "generated-lowpriv",
                    "method": method,
                    "path": path,
                    "auth": "lowpriv",
                    "expect": "denied",
                    "severityIfOpen": "HIGH" if sens == "HIGH" else "MEDIUM",
                    "description": "%s is open to any authenticated user (%s, %s data%s)"
                                   % (path, pkg, sens.lower(),
                                      "" if read_only else ", changes state"),
                    "enabled": read_only or args.include_writes,
                    "body": {} if method in ("POST", "PUT", "PATCH") else None,
                    "generatedFrom": {"marker": MARKER, "package": pkg, "reason":
                                      "effectiveAccess=AnyAuthenticated",
                                      "readOnly": read_only},
                })
                stats["lowpriv"] += 1
                if not (read_only or args.include_writes):
                    stats["lowpriv-disabled-write"] += 1

        for row in (kinds.get("entities") or {}).get("entities", []):
            if "R" not in (row.get("CRUDEndpoints") or ""):
                continue
            if row["sensitivity"]["rating"] != "HIGH":
                stats["skipped-entity-not-sensitive"] += 1
                continue
            actions = row.get("crudActions") or {}
            url = None
            for name in ("GetAll", "getall", "Get", "get"):
                if name in actions:
                    url = actions[name]["url"]
                    break
            if not url or "{" in url:
                continue
            access = row["authorizationRules"]["effectiveAccess"]
            entity = row["entity"]
            for auth, sev in (("anonymous", "CRITICAL"), ("lowpriv", "HIGH")):
                if auth == "lowpriv" and not args.lowpriv_probes:
                    continue
                out.append({
                    "id": "gen-entity-%s-%s" % (auth, slug(entity)),
                    "group": "generated-entity-read",
                    "method": "GET",
                    "path": url + ("?maxResultCount=1" if "?" not in url else ""),
                    "auth": auth,
                    "expect": "denied",
                    "severityIfOpen": sev,
                    "description": "%s holds sensitive data and exposes a read route "
                                   "(effective access %s)"
                                   % (entity, row["authorizationRules"]["effectiveAccessName"]),
                    "note": "If this returns 200, quote the field names in the finding - "
                            "\"returns 200 with identityNumber and dateOfBirth\" gets fixed, "
                            "\"IDOR present\" does not.",
                    "enabled": True,
                    "generatedFrom": {"marker": MARKER, "package": pkg, "reason":
                                      "sensitive entity with a live read route",
                                      "entity": entity, "readOnly": True},
                })
                stats["entity-read"] += 1
    return out, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--matrix", default=os.path.join(HERE, "probe_matrix.json"))
    ap.add_argument("--prune", action="store_true",
                    help="drop previously generated probes first, then regenerate")
    ap.add_argument("--include-writes", action="store_true",
                    help="mark generated write probes enabled. They send state-changing "
                         "requests against real data - only on a database you can restore")
    ap.add_argument("--no-lowpriv-probes", dest="lowpriv_probes", action="store_false",
                    help="skip the low-privilege probes (they need a second account to run)")
    ap.add_argument("--per-package", type=int, default=6,
                    help="cap low-privilege probes per package. A few per package convert "
                         "the derived claim into an observed one; hundreds do not add "
                         "anything a reviewer will read")
    ap.add_argument("--max", type=int, default=300,
                    help="stop after this many new probes; the framework matrix is 73, and a "
                         "matrix of thousands stops being reviewable")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    _, docs = load(args.run_dir, None)
    if not docs:
        print("No catalogue in %s. Run build_catalogs.py first." % args.run_dir,
              file=sys.stderr)
        return 2

    matrix = read_json(args.matrix)
    existing = matrix.get("probes") or []
    pruned = 0
    if args.prune:
        before = len(existing)
        existing = [p for p in existing
                    if (p.get("generatedFrom") or {}).get("marker") != MARKER]
        pruned = before - len(existing)

    have = {probe_key(p["method"], p["path"], p.get("auth")) for p in existing}
    candidates, stats = generate(docs, args)

    added, duplicate = [], 0
    for probe in candidates:
        key = probe_key(probe["method"], probe["path"], probe.get("auth"))
        if key in have:
            duplicate += 1
            continue
        have.add(key)
        if probe.get("body") is None:
            probe.pop("body", None)
        added.append(probe)
        if len(added) >= args.max:
            break

    print("catalogue          %s" % args.run_dir)
    print("matrix             %s (%d existing probe(s))"
          % (os.path.basename(args.matrix), len(existing)))
    if args.prune:
        print("pruned             %d previously generated probe(s)" % pruned)
    print("candidates         %d" % len(candidates))
    print("already covered    %d" % duplicate)
    print("new                %d%s"
          % (len(added), "  (capped by --max)" if len(added) >= args.max else ""))
    for key in sorted(k for k in stats if not k.startswith("lowpriv-")):
        print("   %-32s %d" % (key, stats[key]))
    capped = sum(v for k, v in stats.items() if k.startswith("lowpriv-"))
    if capped:
        print("   %-32s %d (cap %d per package)" % ("lowpriv-selected", capped,
                                                    args.per_package))

    by_group = collections.Counter(p["group"] for p in added)
    disabled = [p for p in added if p.get("enabled") is False]
    print("\nby group")
    for group, n in sorted(by_group.items()):
        print("   %-28s %d" % (group, n))
    if disabled:
        print("\n%d generated probe(s) target state-changing endpoints and are DISABLED. "
              "They are recorded so the surface is documented, but probe.py will not send "
              "them unless you pass --include-disabled." % len(disabled))
        for p in disabled[:8]:
            print("   %-6s %s" % (p["method"], p["path"][:74]))
        if len(disabled) > 8:
            print("   ... and %d more" % (len(disabled) - 8))

    lowpriv = [p for p in added if p.get("auth") == "lowpriv"]
    if lowpriv:
        print("\n%d generated probe(s) need a second, zero-permission account. Without "
              "--lowpriv-user they simply do not run, and the report must say the "
              "corresponding findings stayed derived." % len(lowpriv))

    if not added:
        print("\nNothing to add - the matrix already covers this application's surface.")
        return 0
    if args.dry_run:
        print("\n--dry-run: matrix not written. Sample of what would be added:")
        for p in added[:10]:
            print("   %-6s %-64s %s" % (p["method"], p["path"][:64], p["group"]))
        return 0

    matrix["probes"] = existing + added
    matrix.setdefault("generated", {})[MARKER] = {
        "at": datetime.datetime.now().isoformat(timespec="seconds"),
        "fromRun": os.path.basename(args.run_dir.rstrip("/\\")),
        "added": len(added),
        "disabled": len(disabled),
        "note": "Regenerate with --prune after the next catalogue build. Hand-maintained "
                "probes have no generatedFrom marker and are never pruned.",
    }
    write_json(args.matrix, matrix)
    print("\nwritten %s - now %d probe(s)" % (args.matrix, len(matrix["probes"])))
    print("Re-run probe.py to exercise them, then build_catalogs.py so the new verdicts "
          "reach the catalogue.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
