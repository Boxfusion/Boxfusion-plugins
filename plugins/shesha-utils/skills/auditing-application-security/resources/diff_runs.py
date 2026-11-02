"""Byte-compare two normalized findings runs - the acceptance referee.

    python normalize_findings.py runA/findings.json > a.norm.json
    python normalize_findings.py runB/findings.json > b.norm.json
    python diff_runs.py a.norm.json b.norm.json

The other half of the determinism harness (references/determinism-standard.md §8). It reads two
files already run through `normalize_findings.py` and prints, as JSON:

    {pass, onlyA, onlyB, fix_order_match, same_commit}

- `onlyA` / `onlyB` - finding ids present in one run but not the other (by `id`, which is
  `<CHECK-ID>@<anchor>`). Empty on both sides means the tuple sets converged.
- `fix_order_match` - the two runs present their findings in the same scored order. Since both
  files are canonically sorted, equal sets already imply equal order; this reports it
  explicitly so a future hand-sequenced order would be caught.
- `same_commit` - true when both normalized files name the same commit, false when they name
  different ones, null when neither carries a commit (findings.json does not emit one yet).

Exit code 0 iff the runs converged (determinism-standard §0): equal tuple sets AND matching fix
order. A non-empty diff exits 1 - that is the failure a CI reproducibility gate trips on.
"""

import io
import json
import os
import sys


def _load(path):
    doc = json.load(io.open(path, encoding="utf-8"))
    if isinstance(doc, dict):
        return doc.get("findings") or [], doc.get("commit")
    return doc, None


def diff(a_records, b_records, commit_a=None, commit_b=None):
    a_by_id = {r.get("id"): r for r in a_records}
    b_by_id = {r.get("id"): r for r in b_records}
    only_a = sorted(i for i in a_by_id if i not in b_by_id)
    only_b = sorted(i for i in b_by_id if i not in a_by_id)
    order_a = [r.get("id") for r in a_records]
    order_b = [r.get("id") for r in b_records]
    fix_order_match = order_a == order_b
    if commit_a is None and commit_b is None:
        same_commit = None
    else:
        same_commit = commit_a == commit_b
    converged = not only_a and not only_b and fix_order_match
    return {
        "pass": converged,
        "onlyA": only_a,
        "onlyB": only_b,
        "fix_order_match": fix_order_match,
        "same_commit": same_commit,
    }


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        sys.stderr.write("usage: diff_runs.py <a.norm.json> <b.norm.json>\n")
        return 2
    for p in argv:
        if not os.path.isfile(p):
            sys.stderr.write("no such file: %s\n" % p)
            return 2
    a_records, commit_a = _load(argv[0])
    b_records, commit_b = _load(argv[1])
    result = diff(a_records, b_records, commit_a, commit_b)
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
