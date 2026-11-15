#!/usr/bin/env python3
"""Canonicalise a hardening findings.json into the shared diff surface (determinism-standard §8).

    python normalize_findings.py hardening-report.json            # prints the canonical bytes
    python normalize_findings.py hardening-report.json -o norm.json

This produces the SAME canonical shape as the auditing hub's normalizer, so a hardening run and
the matching audit rows compare with one differ. The rules are the contract's, not this skill's:

- the diff surface is the `findings` array reduced to the tuple
  `{finding_id, anchor, evidence_level, severity, plan_id}` (everything else is out of the diff);
- `non_deterministic` rows are DROPPED (§7 quarantine) until their deterministic instrument lands;
- volatile fields (runMeta: repo path, commit sha, run time, mode; backend host) never enter the
  surface, so two runs on one commit are byte-identical;
- output is `json.dumps(sort_keys=True, separators=(",",":"))` + a trailing newline, stable-sorted
  by `(severity_band, check_id, anchor)`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SEVERITY_ORDER = {b: i for i, b in enumerate(["Critical", "High", "Medium", "Low", "Info"])}
TUPLE_FIELDS = ("finding_id", "anchor", "evidence_level", "severity", "plan_id")


def _check_id(finding_id: str) -> str:
    return finding_id.split("@", 1)[0]


def canonical_findings(doc: dict) -> list[dict]:
    """The deterministic tuple list: drop quarantined rows, keep only the diffed fields, sort."""
    tuples = []
    for f in doc.get("findings", []):
        if f.get("non_deterministic"):
            continue
        tuples.append({k: f.get(k, "") for k in TUPLE_FIELDS})
    tuples.sort(key=lambda t: (SEVERITY_ORDER.get(t["severity"], 99), _check_id(t["finding_id"]),
                               t["anchor"]))
    return tuples


def canonical_bytes(doc: dict) -> bytes:
    return (json.dumps(canonical_findings(doc), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("findings", help="a findings.json written by `harden.py scan|fix --json`")
    p.add_argument("-o", "--out", help="write the canonical bytes here (default: stdout)")
    args = p.parse_args(argv)
    doc = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    data = canonical_bytes(doc)
    if args.out:
        Path(args.out).write_bytes(data)
    else:
        sys.stdout.buffer.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
