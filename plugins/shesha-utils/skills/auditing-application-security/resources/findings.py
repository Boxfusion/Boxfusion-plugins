"""Machine-readable findings index, so run-over-run comparison is mechanical.

    python findings.py --run-dir security-audits/260901-0930
    python findings.py --diff security-audits/260830-1557 security-audits/260901-0930

Built from the **catalogue**, not from the report's prose. Reading a previous report's prose
to work out what changed is how an earlier audit ended up quoting the orphaned-permission
count as 32 in one document and 29 in another. The catalogue is the single source, so the diff
is exact and does not depend on how a sentence was phrased.

Each finding gets a stable id. For a registered check (references/check-registry.md) it is
`<CHECK-ID>@<anchor>` (determinism-standard §2) - a symbol/key anchor, never a line number, so
two runs of the same commit produce byte-identical ids. Everything else (the live endpoint /
entity / form / permission surface, which depends on backend state) keeps the legacy
`{package}|{kind}|{where}` id and is tagged non-deterministic, so the normalizer drops it from
the acceptance diff until its deterministic instrument lands.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from digest import items_for, load  # noqa: E402
from shesha_audit import latest_run_dir, read_json, write_json  # noqa: E402
from catalog_schema import finding_id as make_finding_id  # noqa: E402

SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "WARN", "LOW", "INFO"]

# digest priority -> severity. The review phase can override a row's severityHint, and an
# overridden row carries reviewed=true, which is recorded here so a diff can tell a
# re-judged finding from a changed one.
PRIORITY_SEVERITY = [(0, "CRITICAL"), (2, "HIGH"), (4, "MEDIUM"), (6, "WARN"), (8, "LOW")]


def severity_of(item):
    if item["kind"] == "finding" and item["action"] in SEVERITIES:
        return item["action"]
    for threshold, severity in PRIORITY_SEVERITY:
        if item["priority"] <= threshold:
            return severity
    return "INFO"


def build(run_dir):
    index, docs = load(run_dir, None)
    if docs is None:
        return None
    findings, counts = [], {}
    for pkg in sorted(docs):
        for item in items_for(pkg, docs[pkg]):
            severity = severity_of(item)
            status = item.get("status") or "OPEN"
            check_id, anchor = item.get("checkId"), item.get("anchor")
            # A registered check anchors on a symbol/key -> stable <CHECK-ID>@<anchor> id.
            # Only a finding carrying both is a diff candidate; the rest keep the legacy id
            # and are non-deterministic (live state), so the normalizer drops them.
            if item["kind"] == "finding" and check_id and anchor:
                fid = make_finding_id(check_id, anchor)
                non_det = bool(item.get("nonDeterministic"))
            else:
                fid = "%s|%s|%s" % (pkg, item["kind"], item["where"])
                non_det = True
            record = {
                "id": fid,
                "package": pkg,
                "kind": item["kind"],
                "where": item["where"],
                "action": item["action"],
                "theme": item["theme"],
                "severity": severity,
                "status": status,
                "priority": item["priority"],
                # Determinism block (determinism-standard §2-§6). severityScore is the derived
                # band; `locator` holds the line and is a display field, kept out of the diff.
                "checkId": check_id,
                "anchor": anchor,
                "locator": item.get("locator"),
                "evidenceLevel": item.get("evidenceLevel"),
                "severityScore": item.get("severityScore"),
                "impactClass": item.get("impactClass"),
                "reachability": item.get("reachability"),
                "dataSensitivity": item.get("dataSensitivity"),
                "planId": item.get("planId"),
                "rootCause": item.get("rootCause"),
                "subArea": item.get("subArea"),
                "nonDeterministic": non_det,
            }
            findings.append(record)
            if status not in ("SKIP",):
                counts[severity] = counts.get(severity, 0) + 1

    doc = {
        "runDir": os.path.basename(run_dir.rstrip("/\\")),
        "generated": index.get("generated"),
        "backend": index.get("backend"),
        "source": "catalog/",
        "findingCount": len(findings),
        "openBySeverity": {s: counts[s] for s in SEVERITIES if counts.get(s)},
        "packages": {p: len([f for f in findings if f["package"] == p])
                     for p in sorted({f["package"] for f in findings})},
        "inputsMissing": index.get("inputsMissing") or [],
        "confidence": index.get("confidence") or {},
        "review": index.get("review") or {},
        "findings": sorted(findings, key=lambda f: (f["priority"], f["id"])),
    }
    return doc


def diff(old_doc, new_doc):
    old = {f["id"]: f for f in old_doc.get("findings", [])}
    new = {f["id"]: f for f in new_doc.get("findings", [])}
    fixed = [old[i] for i in sorted(old) if i not in new]
    added = [new[i] for i in sorted(new) if i not in old]
    still = [new[i] for i in sorted(new) if i in old]
    changed = [{"id": i, "from": old[i]["severity"], "to": new[i]["severity"]}
               for i in sorted(new)
               if i in old and old[i]["severity"] != new[i]["severity"]]
    return {"fixedSince": fixed, "newlyFound": added, "stillOpen": still,
            "severityChanged": changed,
            "note": "A finding counts as fixed when the catalogue no longer produces an "
                    "actionable row for it. Confirm a sample by hand - a row can also "
                    "disappear because an input was missing on this run."}


def show(label, rows):
    print("%-14s %d" % (label, len(rows)))
    for row in rows[:25]:
        print("   [%-8s] %-24s %s" % (row["severity"], row["package"], row["where"][:64]))
    if len(rows) > 25:
        print("   ... and %d more" % (len(rows) - 25))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default=None)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--diff", nargs=2, metavar=("OLD", "NEW"))
    args = ap.parse_args()

    if args.diff:
        docs = []
        for run in args.diff:
            path = os.path.join(run, "findings.json")
            if os.path.isfile(path):
                docs.append(read_json(path))
                continue
            built = build(run)
            if built is None:
                print("%s has neither findings.json nor catalog/" % run, file=sys.stderr)
                return 2
            write_json(path, built)
            docs.append(built)
        d = diff(docs[0], docs[1])
        show("fixed since", d["fixedSince"])
        show("newly found", d["newlyFound"])
        show("still open", d["stillOpen"])
        if d["severityChanged"]:
            print("severity changed")
            for c in d["severityChanged"]:
                print("   %s  %s -> %s" % (c["id"][:70], c["from"], c["to"]))
        out = os.path.join(args.diff[1], "comparison.json")
        write_json(out, d)
        print("\nwritten %s" % out)
        return 0

    run_dir = args.run_dir or latest_run_dir(args.repo_root)
    if not run_dir:
        print("no run directory found", file=sys.stderr)
        return 2
    doc = build(run_dir)
    if doc is None:
        print("No catalog/ in %s. Run build_catalogs.py first." % run_dir, file=sys.stderr)
        return 2
    write_json(os.path.join(run_dir, "findings.json"), doc)
    print("run %s: %d findings" % (doc["runDir"], doc["findingCount"]))
    for severity, n in doc["openBySeverity"].items():
        print("   %-9s %d" % (severity, n))
    if not (doc["review"] or {}).get("overridesApplied"):
        print("\nNOTE: no review overrides were applied, so every severity here came from a "
              "heuristic. Complete the review pass before treating this as a findings list.")
    print("written %s" % os.path.join(run_dir, "findings.json"))

    prev = latest_run_dir(args.repo_root, before=run_dir)
    if prev:
        print("\nprevious run %s - diff with:" % os.path.basename(prev))
        print("   python findings.py --diff %s %s" % (prev, run_dir))
    else:
        print("\nNo previous run: this is the baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
