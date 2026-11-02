"""Drive probe_matrix.json against a running Shesha backend.

    python probe.py --url http://localhost:21021 [--group workflow] [--cache DIR]
                    [--user admin --password 123qwe]
                    [--lowpriv-user <u> --lowpriv-password <p>] [--json out.json]

Supply `--lowpriv-*` and every probe marked `auth: both` or `auth: lowpriv` also runs as
that principal. This is what turns "any authenticated user can reach X" from a claim derived
from DefaultEndpointAccess into something actually observed - see object_auth.py for the
object-level half.

Why this exists: guessing a route produces a 404, and a 404 read as "endpoint absent"
silently hides an open endpoint. Every path in the matrix was read off a live OpenAPI
document, and this script cross-checks each one against the current surface before
assigning a verdict.

Verdicts
    OPEN          200 where denial was expected              -> finding
    REACHED       400/500 - authorization did not block      -> finding
    DENIED        401/403                                    -> pass
    DISABLED      404, path in surface, record Access=1      -> pass (explicitly disabled)
    NOT-FOUND     404, path in surface, record NOT Access=1  -> INCONCLUSIVE, see below
    ABSENT        404 and the path is NOT in the surface     -> pass, but "absent" not "fixed"
    INCONCLUSIVE  405/415 - wrong verb or content type       -> fix the matrix, re-probe
    UNREACHABLE   000 - backend down                         -> never a verdict
    EXPECTED      200 where anonymous access is allowlisted  -> pass
    JUDGEMENT     needs a human/model call; body captured

NOT-FOUND is the trap this script exists to expose. A 404 from a synthetic payload is an
entity-not-found from business logic, NOT an authorization denial - the request already
got past the authorization filter. If the PermissionedObject record for that method says
AllowAnonymous, the endpoint IS anonymously reachable; a caller with a real id reaches it.
Never record a NOT-FOUND as a pass. Confirm by checking that an authenticated admin gets
the same 404 (identical => not an authorization decision at all).
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shesha_audit import (ACCESS, cache_dir, get_json, load_surface, read_json, request,
                          authenticate, write_json)

MULTIPART_BODY = (
    b"--BOUNDARY\r\n"
    b'Content-Disposition: form-data; name="file"; filename="probe.txt"\r\n'
    b"Content-Type: text/plain\r\n\r\n"
    b"probe\r\n"
    b"--BOUNDARY--\r\n"
)


def verdict_for(probe, status, in_surface, record_access=None):
    expect = probe.get("expect", "denied")
    if status == 0:
        return "UNREACHABLE"
    if status == 200:
        if expect == "anonymous-ok":
            return "EXPECTED"
        if expect == "judgement":
            return "JUDGEMENT"
        return "OPEN"
    if status in (401, 403):
        return "DENIED"
    if status == 404:
        if not in_surface:
            return "ABSENT"
        if record_access == 1:
            return "DISABLED"
        # In the surface, not disabled -> the 404 came from business logic, which means
        # authorization already let the request through.
        return "NOT-FOUND"
    if status in (405, 415):
        return "INCONCLUSIVE"
    if status in (400, 500, 501, 502):
        # Authorization did not block; business logic (or model binding) ran.
        return "REACHED" if expect != "anonymous-ok" else "EXPECTED"
    return "OTHER-%d" % status


def normalise(path):
    return path.split("?")[0].rstrip("/").lower()


def run_probe(base, probe, token, surface, records=None, principal="anonymous"):
    url = base.rstrip("/") + probe["path"]
    ct = probe.get("contentType")
    body = probe.get("body")
    if ct == "multipart/form-data":
        status, raw = request("POST", url, token=token, body=MULTIPART_BODY,
                              content_type="multipart/form-data; boundary=BOUNDARY")
    elif body is not None:
        status, raw = request(probe["method"], url, token=token, body=body,
                              content_type=ct or "application/json")
    else:
        status, raw = request(probe["method"], url, token=token)
    in_surface = normalise(probe["path"]) in surface
    rec = lookup_record(probe["path"], records) if records else None
    rec_access = rec.get("actualAccess") if rec else None
    return {
        "id": probe["id"],
        "group": probe["group"],
        "method": probe["method"],
        "path": probe["path"],
        "authenticated": token is not None,
        "principal": principal,
        "status": status,
        "inSurface": in_surface,
        "recordAccess": rec_access,
        "recordHardcoded": rec.get("hardcoded") if rec else None,
        "recordObject": rec.get("object") if rec else None,
        "verdict": verdict_for(probe, status, in_surface, rec_access),
        "severityIfOpen": probe.get("severityIfOpen"),
        "description": probe.get("description", ""),
        "note": probe.get("note", ""),
        "bytes": len(raw),
        "bodyExcerpt": raw[:600].decode("utf-8", "replace") if status == 200 else
                       raw[:300].decode("utf-8", "replace"),
    }


def lookup_record(path, records):
    """Match a route to its Shesha.WebApi.Action record.

    Route method names do NOT always match record method names - Shesha.Workflow routes
    CompleteUserTask as UserTaskComplete, GetMyActiveTodoItems as MyActiveTodoItems, and
    so on. Try the exact name, then the common Get-prefix and word-swap variants.
    """
    from shesha_audit import SVC_RE
    m = SVC_RE.match(normalise(path))
    if not m:
        return None
    svc, meth = m.group(2).lower(), m.group(3).lower()
    candidates = [meth, "get" + meth]
    # UserTaskComplete <-> CompleteUserTask, UserTaskSave <-> SaveUserTask
    for split in ("usertask", "user"):
        if meth.startswith(split) and len(meth) > len(split):
            candidates.append(meth[len(split):] + split)
    for cand in candidates:
        rec = records.get((svc, cand)) or records.get((svc + "appservice", cand))
        if rec:
            return rec
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:21021")
    ap.add_argument("--group", action="append", help="restrict to these matrix groups")
    ap.add_argument("--id", action="append", help="restrict to these probe ids")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="123qwe")
    ap.add_argument("--lowpriv-user", default=None,
                    help="a second account holding NO roles or permissions")
    ap.add_argument("--lowpriv-password", default=None)
    ap.add_argument("--cache", default=None)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--json", default=None, help="write full results here")
    ap.add_argument("--include-disabled", action="store_true",
                    help="also run probes marked `enabled: false`. Those send "
                         "state-changing requests against real data - only against a "
                         "database you can restore")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    matrix = read_json(os.path.join(here, "probe_matrix.json"))
    cache = args.cache or cache_dir(args.repo_root, args.url)

    # Surface: prefer the cached swagger from collect.py, else fetch it.
    surface = {}
    swagger_path = os.path.join(cache, "swagger.json")
    if os.path.isfile(swagger_path) and os.path.getsize(swagger_path) > 0:
        try:
            surface = load_surface(read_json(swagger_path))
        except ValueError:
            # A truncated or 500-body cache file. Ignore it and refetch.
            surface = {}
    if not surface:
        status, doc = get_json(args.url.rstrip("/") + "/swagger/v1/swagger.json")
        if doc:
            surface = load_surface(doc)
            write_json(swagger_path, doc)
        elif status in (500, 0):
            # Documented: OpenAPI generation can exceed time/memory limits on a large
            # Shesha app, and returns 500 with an empty body. Not a security signal.
            print("NOTE: /swagger/v1/swagger.json returned %d. OpenAPI generation "
                  "commonly fails on large Shesha applications; this is not a finding. "
                  "Supply a previously captured swagger.json in the cache dir to "
                  "classify 404s correctly." % status, file=sys.stderr)
    if not surface:
        print("WARNING: no OpenAPI surface available. 404 results cannot be told apart "
              "from a wrong route - every 404 will be reported as ABSENT-UNVERIFIED.",
              file=sys.stderr)

    token, auth_status = authenticate(args.url, args.user, args.password)
    default_creds_work = token is not None
    # HTTP 0 is a dead backend, not a rejection. Reporting it as "rejected - pass" is
    # exactly the kind of untestable-check-becomes-a-PASS this audit must not do.
    if auth_status == 0:
        verdict = "UNTESTED - backend not answering, record as SKIP"
    elif default_creds_work:
        verdict = "ACCEPTED - finding E4"
    else:
        verdict = "rejected - pass"
    print("Default credentials %s/%s: %s (HTTP %d)"
          % (args.user, args.password, verdict, auth_status))

    low_token = None
    if args.lowpriv_user:
        low_token, low_status = authenticate(args.url, args.lowpriv_user,
                                             args.lowpriv_password or "")
        print("Low-privilege principal %s: %s (HTTP %d)"
              % (args.lowpriv_user, "authenticated" if low_token else "FAILED", low_status))
        if not low_token:
            print("  Without it, every 'any authenticated user can ...' finding stays "
                  "DERIVED from DefaultEndpointAccess rather than observed.", file=sys.stderr)
    else:
        print("No --lowpriv-user supplied. Findings about what an ordinary authenticated "
              "user can reach will be marked DERIVED, not observed.")

    probes = matrix["probes"]
    if args.group:
        probes = [p for p in probes if p["group"] in set(args.group)]
    if args.id:
        probes = [p for p in probes if p["id"] in set(args.id)]
    # A probe marked `enabled: false` sends a state-changing request against real data.
    # extend_probe_matrix.py generates those for write endpoints and leaves them disabled,
    # because "probe every unprotected write endpoint" and "corrupt the database" are the
    # same command. Enabling them is a decision a person makes, never a default.
    disabled = [p for p in probes if p.get("enabled") is False]
    if disabled and not args.include_disabled:
        probes = [p for p in probes if p.get("enabled") is not False]
        print("%d probe(s) are disabled because they would change state. Pass "
              "--include-disabled to run them, and only against a database you can restore."
              % len(disabled))

    # PermissionedObject action records let a 404 be told apart from an explicit Disable.
    records = None
    rec_path = os.path.join(cache, "po-shesha-webapi-action.json")
    if os.path.isfile(rec_path) and os.path.getsize(rec_path) > 0:
        try:
            from shesha_audit import index_permissioned_objects, unwrap
            records = index_permissioned_objects(unwrap(read_json(rec_path)))
            print("Loaded %d Shesha.WebApi.Action records for 404 disambiguation."
                  % len(records))
        except Exception:
            records = None
    if records is None:
        print("NOTE: no po-shesha-webapi-action.json in the cache. A 404 on a route that exists "
              "cannot be told apart from an explicit Disable; those show as NOT-FOUND.",
              file=sys.stderr)

    results = []
    for probe in probes:
        auth_mode = probe.get("auth", "anonymous")
        if auth_mode in ("anonymous", "both"):
            results.append(run_probe(args.url, probe, None, surface, records,
                                     principal="anonymous"))
        if auth_mode in ("authenticated", "both", "lowpriv") and token:
            results.append(run_probe(args.url, probe, token, surface, records,
                                     principal="admin"))
        if auth_mode in ("both", "lowpriv", "authenticated") and low_token:
            results.append(run_probe(args.url, probe, low_token, surface, records,
                                     principal="lowpriv"))

    order = {"OPEN": 0, "REACHED": 1, "NOT-FOUND": 2, "INCONCLUSIVE": 3,
             "JUDGEMENT": 4, "UNREACHABLE": 5}
    results.sort(key=lambda r: (order.get(r["verdict"], 9), r["group"], r["id"]))

    print("\n%-13s %-9s %-4s %-5s %s" % ("VERDICT", "AS", "HTTP", "INSWG", "PROBE"))
    print("-" * 104)
    for r in results:
        print("%-13s %-9s %-4d %-5s %s %s"
              % (r["verdict"], r["principal"], r["status"],
                 "yes" if r["inSurface"] else "NO", r["method"], r["path"][:58]))

    counts = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print("\n" + json.dumps(counts, indent=2))

    actionable = [r for r in results
                  if r["verdict"] in ("OPEN", "REACHED", "NOT-FOUND", "INCONCLUSIVE",
                                      "JUDGEMENT")]
    if actionable:
        print("\n=== NEEDS ATTENTION ===")
        for r in actionable:
            print("\n[%s] %s %s  (%s, %s)"
                  % (r["verdict"], r["method"], r["path"],
                     r["severityIfOpen"] or "-", "as " + r["principal"]))
            print("    %s" % r["description"])
            if r["recordObject"]:
                print("    record: %s  actualAccess=%s (%s)  hardcoded=%s"
                      % (r["recordObject"], r["recordAccess"],
                         ACCESS.get(r["recordAccess"], "?"), r["recordHardcoded"]))
            if r["verdict"] == "INCONCLUSIVE":
                print("    -> wrong verb or content type. Correct probe_matrix.json and re-run; "
                      "do NOT record this as a pass.")
            if r["verdict"] == "NOT-FOUND":
                print("    -> 404 from business logic, NOT an authorization denial. The request "
                      "passed the authorization filter.")
                if r["recordAccess"] == 5:
                    print("    -> the record says AllowAnonymous: this endpoint IS anonymously "
                          "reachable. A caller with a valid id gets in. Treat as OPEN.")
            if r["bodyExcerpt"].strip():
                print("    body[%d]: %s" % (r["bytes"],
                                            r["bodyExcerpt"][:300].replace("\n", " ")))
            if r["note"]:
                print("    note: %s" % r["note"])

    out = args.json or os.path.join(cache, "probe-results.json")
    lowpriv_open = [r for r in results
                    if r["principal"] == "lowpriv" and r["verdict"] in ("OPEN", "REACHED")]
    if low_token and lowpriv_open:
        print("\n=== OBSERVED as a zero-permission user (%d) ===" % len(lowpriv_open))
        print("These are no longer derived from DefaultEndpointAccess - an account holding "
              "no roles reached them.")
        for r in lowpriv_open:
            print("  %-4d %s %s" % (r["status"], r["method"], r["path"][:80]))

    write_json(out, {"defaultCredentialsAccepted": default_creds_work,
                     "defaultCredentialsUntested": auth_status == 0,
                     "lowprivPrincipalUsed": low_token is not None,
                     "lowprivUser": args.lowpriv_user,
                     "counts": counts, "results": results})
    print("\nwritten %s" % out)


if __name__ == "__main__":
    main()
