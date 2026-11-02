"""Object-level authorization testing — IDOR / BOLA, file ownership, workflow tasks.

    python object_auth.py --url http://localhost:21021 \
        --lowpriv-user <u> --lowpriv-password <p> [--repo-root .]

Endpoint authorization answers "may this user call this URL". Object-level authorization
answers "may this user see *this row*". They are different questions and a Shesha
application answers the second one only through global specifications — of which many
applications have none.

This is OWASP API Security #1 (Broken Object Level Authorization) and the audit's endpoint
probes cannot detect it, because as an administrator every id is legitimately yours.

Method, and why it needs two accounts:
  1. As the ADMIN principal, collect real ids for each sensitive entity.
  2. As a ZERO-PERMISSION principal, request those same ids.
  3. A 200 means the second user read a record that is not theirs.

Strictly read-only. It issues GETs against ids that already exist and never writes, so it
cannot corrupt data — but it does read other people's records, which is the point, and
should only be run against a non-production database.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shesha_audit import (authenticate, cache_dir, get_json, read_json, request,  # noqa: E402
                          unwrap, write_json)

# Entities worth testing in an HR / case-management Shesha application. Matched against the
# live EntityConfig list by substring, so a repo with different names still gets coverage.
SENSITIVE_HINTS = [
    "person", "employee", "user", "leave", "performance", "review", "agreement",
    "payroll", "salary", "bank", "medical", "disciplinary", "grievance", "appraisal",
    "cycle", "balance", "profile", "supervisor", "contact", "address", "document",
]


def collect_ids(base, token, entities, per_entity=3):
    """As admin: real ids per entity, via the generic gateway."""
    out = {}
    for full in entities:
        status, doc = get_json(
            "%s/api/services/app/Entities/GetAll?entityType=%s&maxResultCount=%d"
            % (base, full, per_entity), token=token, timeout=60)
        if status != 200 or not doc:
            continue
        items = ((doc.get("result") or {}).get("items")) or []
        ids = [i.get("id") for i in items if isinstance(i, dict) and i.get("id")]
        if ids:
            out[full] = {"ids": ids,
                         "fields": sorted(items[0].keys()) if items else [],
                         "totalCount": (doc.get("result") or {}).get("totalCount")}
    return out


SENSITIVE_FIELDS = {
    "identitynumber", "idnumber", "passportnumber", "dateofbirth", "taxnumber",
    "bankaccountnumber", "accountnumber", "salary", "remuneration", "mobilenumber1",
    "mobilenumber2", "emailaddress1", "emailaddress2", "homenumber", "address",
    "medicalcertificate", "photo", "gender",
}


def sensitive_in(fields):
    return sorted(f for f in fields if f.lower() in SENSITIVE_FIELDS)


def probe_idor(base, low_token, harvested):
    findings = []
    for full, info in sorted(harvested.items()):
        for oid in info["ids"][:2]:
            status, doc = get_json(
                "%s/api/services/app/Entities/Get?entityType=%s&id=%s" % (base, full, oid),
                token=low_token, timeout=60)
            exposed = []
            if status == 200 and doc:
                res = doc.get("result") or {}
                exposed = sensitive_in(res.keys() if isinstance(res, dict) else [])
            findings.append({
                "check": "IDOR",
                "entity": full,
                "id": oid,
                "status": status,
                "verdict": "EXPOSED" if status == 200 else "denied",
                "sensitiveFieldsReturned": exposed,
            })
            break  # one id per entity is enough to establish the finding
    return findings


def probe_list_scope(base, low_token, admin_counts):
    """Does GetAll return the whole table to a zero-permission user, or only their rows?"""
    findings = []
    for full, info in sorted(admin_counts.items()):
        status, doc = get_json(
            "%s/api/services/app/Entities/GetAll?entityType=%s&maxResultCount=1"
            % (base, full), token=low_token, timeout=60)
        low_total = None
        if status == 200 and doc:
            low_total = (doc.get("result") or {}).get("totalCount")
        findings.append({
            "check": "list-scope",
            "entity": full,
            "status": status,
            "adminTotal": info.get("totalCount"),
            "lowprivTotal": low_total,
            "verdict": ("UNSCOPED" if status == 200 and low_total == info.get("totalCount")
                        and low_total not in (None, 0)
                        else "scoped-or-denied"),
        })
    return findings


def probe_file_ownership(base, low_token, harvested):
    """ownerType/ownerId are client-supplied. Can a user list another entity's files?"""
    findings = []
    for full, info in sorted(harvested.items()):
        for oid in info["ids"][:1]:
            status, doc = get_json(
                "%s/api/StoredFile/FilesList?ownerType=%s&ownerId=%s" % (base, full, oid),
                token=low_token, timeout=60)
            count = None
            if status == 200 and doc:
                res = doc.get("result")
                count = len(res) if isinstance(res, list) else None
            findings.append({
                "check": "file-ownership",
                "ownerType": full,
                "ownerId": oid,
                "status": status,
                "filesReturned": count,
                "verdict": "EXPOSED" if status == 200 else "denied",
            })
    return findings


def probe_workflow_tasks(base, admin_token, low_token):
    """Can a user act on a task that is not assigned to them?"""
    findings = []
    status, doc = get_json("%s/api/services/SheshaWorkflow/Process/UserTasks" % base,
                           token=admin_token, timeout=60)
    task_ids = []
    if status == 200 and doc:
        res = doc.get("result")
        items = res.get("items") if isinstance(res, dict) else res
        for it in (items or [])[:2]:
            if isinstance(it, dict) and it.get("id"):
                task_ids.append(it["id"])
    for tid in task_ids:
        st, _ = get_json("%s/api/services/SheshaWorkflow/Process/UserTaskDetails?id=%s"
                         % (base, tid), token=low_token, timeout=60)
        findings.append({"check": "workflow-task-assignment", "taskId": tid,
                         "status": st,
                         "verdict": "EXPOSED" if st == 200 else "denied"})
    if not task_ids:
        findings.append({"check": "workflow-task-assignment", "verdict": "no-tasks-available",
                         "note": "No workflow user tasks existed to test against. Re-run on a "
                                 "database with live workflow instances before concluding "
                                 "task assignment is enforced."})
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:21021")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="123qwe")
    ap.add_argument("--lowpriv-user", required=True)
    ap.add_argument("--lowpriv-password", required=True)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--max-entities", type=int, default=25)
    args = ap.parse_args()

    base = args.url.rstrip("/")
    cache = args.cache or cache_dir(args.repo_root, args.url)

    admin, st = authenticate(base, args.user, args.password)
    if not admin:
        print("Could not authenticate as %s (HTTP %d)." % (args.user, st), file=sys.stderr)
        return 2
    low, st = authenticate(base, args.lowpriv_user, args.lowpriv_password)
    if not low:
        print("Could not authenticate the low-privilege principal %s (HTTP %d). "
              "Object-level authorization CANNOT be tested with one account."
              % (args.lowpriv_user, st), file=sys.stderr)
        return 2
    print("admin: ok    low-privilege principal %s: ok" % args.lowpriv_user)

    ecfg = unwrap(read_json(os.path.join(cache, "entityconfigs.json")))
    names = [e.get("fullClassName") for e in ecfg if e.get("fullClassName")]
    sensitive = [n for n in names
                 if any(h in n.lower() for h in SENSITIVE_HINTS)][:args.max_entities]
    print("testing %d sensitive entities (of %d configured)" % (len(sensitive), len(names)))

    print("\n1/4 harvesting real ids as admin ...")
    harvested = collect_ids(base, admin, sensitive)
    print("    got ids for %d entities" % len(harvested))

    print("2/4 IDOR: fetching those ids as the zero-permission user ...")
    idor = probe_idor(base, low, harvested)
    print("3/4 list scope: comparing GetAll totals ...")
    scope = probe_list_scope(base, low, harvested)
    print("4/4 file ownership and workflow task assignment ...")
    files = probe_file_ownership(base, low, harvested)
    tasks = probe_workflow_tasks(base, admin, low)

    all_f = idor + scope + files + tasks
    exposed = [f for f in all_f if f.get("verdict") in ("EXPOSED", "UNSCOPED")]

    print("\n%-14s %-52s %s" % ("VERDICT", "ENTITY / TARGET", "DETAIL"))
    print("-" * 104)
    for f in all_f:
        target = f.get("entity") or f.get("ownerType") or f.get("taskId") or "-"
        detail = ""
        if f["check"] == "IDOR" and f.get("sensitiveFieldsReturned"):
            detail = "fields: " + ", ".join(f["sensitiveFieldsReturned"][:6])
        elif f["check"] == "list-scope":
            detail = "admin=%s lowpriv=%s" % (f.get("adminTotal"), f.get("lowprivTotal"))
        elif f["check"] == "file-ownership":
            detail = "files=%s" % f.get("filesReturned")
        elif f.get("note"):
            detail = f["note"][:60]
        print("%-14s %-52s %s" % (f["verdict"], str(target)[:52], detail))

    print("\n%d object-level exposure(s)." % len(exposed))
    if exposed:
        print("\nThese are OBSERVED, not derived: an account holding no roles read records "
              "belonging to other people. Quote the entity and the field names in the "
              "finding - 'returns 200 with identityNumber and dateOfBirth' gets fixed, "
              "'IDOR present' does not.")
        print("\nRemediation is a global specification per entity "
              "([GlobalSpecification] ShaSpecification<T>) scoping queries to the caller. "
              "Entity action permissions alone do NOT fix this - they gate the endpoint, "
              "not the row.")

    write_json(os.path.join(cache, "object-auth.json"),
               {"lowprivUser": args.lowpriv_user,
                "entitiesTested": sensitive,
                "harvested": {k: {"count": len(v["ids"]),
                                  "totalCount": v.get("totalCount"),
                                  "sensitiveFields": sensitive_in(v["fields"])}
                              for k, v in harvested.items()},
                "findings": all_f,
                "exposedCount": len(exposed)})
    print("\nwritten %s" % os.path.join(cache, "object-auth.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
