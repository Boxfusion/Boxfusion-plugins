"""Reduce a findings.json to its canonical, byte-stable form - the acceptance diff surface.

    python normalize_findings.py security-audits/YYMMDD-HHMM/findings.json > a.norm.json

The determinism standard (references/determinism-standard.md §8) says two runs of the same
commit, over the same capabilities, must produce byte-identical findings. This script is half
of the referee: it strips everything that legitimately varies between runs and leaves only the
canonical tuples, so `diff_runs.py` can byte-compare two runs.

It:
  - keeps only the diff tuple per finding - `{id, checkId, anchor, evidenceLevel, severity,
    planId}` (determinism-standard §0) - dropping prose, run metadata and the `locator`
    display field (the line number lives there and is deliberately out of the diff);
  - drops every record tagged `nonDeterministic: true` (the quarantine, §7);
  - stable-sorts by `(severity band, checkId, anchor)`;
  - emits `json.dumps(sort_keys=True, separators=(",",":"))` plus a trailing newline.

Pure and total: a path in, canonical JSON on stdout, nothing written. Import `normalize()` to
use it in-process (verify_run.py does, for its reproducibility gate).
"""

import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from catalog_schema import severity_rank  # noqa: E402

# Stripped because they legitimately differ run-to-run (determinism-standard §8).
VOLATILE_TOP = ("generated", "ranAt", "runDir", "backend", "source", "openBySeverity",
                "packages", "findingCount", "confidence", "review", "inputsMissing")


def _band(rec):
    """The severity band a record sorts and diffs on: the derived score, else the legacy
    severity, so a pre-determinism finding still lands somewhere stable."""
    return rec.get("severityScore") or rec.get("severity")


def _tuple(rec):
    """The canonical diff tuple for one finding (determinism-standard §0)."""
    return {
        "id": rec.get("id"),
        "checkId": rec.get("checkId"),
        "anchor": rec.get("anchor"),
        "evidenceLevel": rec.get("evidenceLevel"),
        "severity": _band(rec),
        "planId": rec.get("planId"),
    }


def normalize(doc):
    """Canonical form of a findings doc: ND dropped, tuple-only, stably sorted.

    Returns a dict: `{commit, findings:[...]}`. `commit` is carried through when the input
    names one (for diff_runs' same_commit check) and is otherwise null; per-finding commit
    shas inside evidence never reach the tuple, so they cannot perturb the diff.
    """
    findings = doc.get("findings") if isinstance(doc, dict) else doc
    kept = [_tuple(r) for r in (findings or []) if not r.get("nonDeterministic")]
    kept.sort(key=lambda t: (severity_rank(t["severity"]),
                             t["checkId"] or "", t["anchor"] or "", t["id"] or ""))
    commit = doc.get("commit") if isinstance(doc, dict) else None
    return {"commit": commit, "findings": kept}


def dumps(canonical):
    """The exact bytes two runs must match."""
    return json.dumps(canonical, sort_keys=True, separators=(",", ":")) + "\n"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        sys.stderr.write("usage: normalize_findings.py <findings.json>\n")
        return 2
    path = argv[0]
    if not os.path.isfile(path):
        sys.stderr.write("no such file: %s\n" % path)
        return 2
    doc = json.load(io.open(path, encoding="utf-8"))
    sys.stdout.write(dumps(normalize(doc)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
