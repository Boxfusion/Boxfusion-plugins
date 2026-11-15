#!/usr/bin/env python3
"""Byte-compare two hardening findings.json runs (determinism-standard §8).

    python diff_runs.py runA.json runB.json

Prints `onlyA`, `onlyB`, `fix_order_match`, `same_commit` and `manifest_delta`, the same report
the auditing hub's differ prints. Exit 0 = the two runs converged (empty onlyA/onlyB and matching
fix order over the capability intersection); exit 1 = they diverged.

`fix_order_rank` is a pure function of `{severity, root_cause, anchor}` (§5), so the ordered list of
deterministic finding_ids must match across runs. One-sided checks (a capability present in only one
manifest) are reported in `manifest_delta`, never counted as a diff failure (§1).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from normalize_findings import SEVERITY_ORDER, canonical_findings, _check_id


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _present_capabilities(doc: dict) -> set[str]:
    return {name for name, cap in (doc.get("capabilities") or {}).items() if cap.get("present")}


def _fix_order(doc: dict) -> list[str]:
    """Deterministic rows ordered by (severity_band, root_cause, anchor) -> finding_ids (§5)."""
    rows = [f for f in doc.get("findings", []) if not f.get("non_deterministic")]
    rows.sort(key=lambda f: (SEVERITY_ORDER.get(f.get("severity"), 99), f.get("root_cause", ""),
                             f.get("anchor", "")))
    return [f["finding_id"] for f in rows]


def diff(doc_a: dict, doc_b: dict) -> dict:
    ids_a = {t["finding_id"] for t in canonical_findings(doc_a)}
    ids_b = {t["finding_id"] for t in canonical_findings(doc_b)}
    caps_a, caps_b = _present_capabilities(doc_a), _present_capabilities(doc_b)
    commit_a = (doc_a.get("runMeta") or {}).get("commit")
    commit_b = (doc_b.get("runMeta") or {}).get("commit")
    return {
        "onlyA": sorted(ids_a - ids_b),
        "onlyB": sorted(ids_b - ids_a),
        "fix_order_match": _fix_order(doc_a) == _fix_order(doc_b),
        "same_commit": commit_a == commit_b and commit_a is not None,
        "manifest_delta": {"onlyA": sorted(caps_a - caps_b), "onlyB": sorted(caps_b - caps_a)},
    }


def converged(report: dict) -> bool:
    return not report["onlyA"] and not report["onlyB"] and report["fix_order_match"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("runA")
    p.add_argument("runB")
    args = p.parse_args(argv)
    report = diff(_load(args.runA), _load(args.runB))
    print(json.dumps(report, indent=2))
    ok = converged(report)
    print("\nconverged" if ok else "\nDIVERGED", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
