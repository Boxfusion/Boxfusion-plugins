"""Reproducibility proof for the determinism harness (references/determinism-standard.md).

CI proof that normalize_findings.py + diff_runs.py are a referee: the same findings normalize
byte-identically, a reordered input normalizes to the same bytes, non-deterministic records are
dropped from the diff, and diff_runs converges iff the tuple sets match.

Runs two ways, with no third-party dependency:
    python tests/test_determinism.py      # prints OK / raises AssertionError
    pytest tests/test_determinism.py      # discovered as test_* functions
"""

import copy
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RESOURCES = os.path.dirname(HERE)
sys.path.insert(0, RESOURCES)

import normalize_findings as norm  # noqa: E402
import diff_runs  # noqa: E402


# A small findings.json the way findings.py build() emits it: DET registered checks that carry
# checkId/anchor/severityScore, plus ND records (a live probe, a dependency advisory, and a
# legacy live-endpoint row) that the normalizer must drop.
def sample_findings():
    return {
        "runDir": "260901-0930",
        "generated": "2026-09-01T09:30:00",
        "backend": "http://localhost:21021",
        "findingCount": 5,
        "findings": [
            {"id": "A9@backend/src/web/startup.cs#Startup.ConfigureServices",
             "package": "_repository", "kind": "finding",
             "where": "SheshaAuthorizationFilter not registered (A9-auth-filter)",
             "severity": "CRITICAL", "status": "FAIL", "priority": 0,
             "checkId": "A9", "anchor": "backend/src/web/startup.cs#Startup.ConfigureServices",
             "locator": "backend/src/web/Startup.cs:142", "evidenceLevel": "CODE-ONLY",
             "severityScore": "Critical", "planId": "PLAN-a9", "nonDeterministic": False},
            {"id": "B7@backend/src/web/appsettings.json#key:jwt-signing-key",
             "package": "Shesha.Hcm", "kind": "finding",
             "where": "jwt-signing-key in tracked configuration",
             "severity": "HIGH", "status": "FAIL", "priority": 2,
             "checkId": "B7", "anchor": "backend/src/web/appsettings.json#key:jwt-signing-key",
             "locator": "backend/src/web/appsettings.json:12",
             "evidenceLevel": "VERIFIED-ARTEFACT", "severityScore": "Critical",
             "planId": "PLAN-b7", "nonDeterministic": False},
            {"id": "K1@dep:nuget:*", "package": "_repository", "kind": "finding",
             "where": "3 vulnerable NuGet package(s)", "severity": "MEDIUM", "status": "FAIL",
             "priority": 4, "checkId": "K1", "anchor": "dep:nuget:*",
             "evidenceLevel": "VERIFIED-ARTEFACT", "severityScore": None,
             "planId": "PLAN-k1", "nonDeterministic": True},
            {"id": "_probe-findings|finding|GET /api/x -> OPEN as anonymous",
             "package": "_probe-findings", "kind": "finding", "where": "GET /api/x OPEN",
             "severity": "HIGH", "status": "FAIL", "priority": 1,
             "checkId": None, "anchor": None, "nonDeterministic": True},
            {"id": "Shesha.Hcm|endpoint|/api/services/app/Foo/GetAll",
             "package": "Shesha.Hcm", "kind": "endpoint",
             "where": "/api/services/app/Foo/GetAll", "severity": "HIGH", "status": "OPEN",
             "priority": 3, "checkId": None, "anchor": None, "nonDeterministic": True},
        ],
    }


def test_normalize_is_byte_stable():
    doc = sample_findings()
    a = norm.dumps(norm.normalize(doc))
    b = norm.dumps(norm.normalize(copy.deepcopy(doc)))
    assert a == b, "normalize is not byte-stable across two runs"
    assert a.endswith("\n"), "canonical output must end with a trailing newline"


def test_reordered_input_same_output():
    doc = sample_findings()
    shuffled = copy.deepcopy(doc)
    shuffled["findings"] = list(reversed(shuffled["findings"]))
    # Volatile metadata differs between the two runs; it must not affect the canonical bytes.
    shuffled["generated"] = "2026-09-02T17:05:11"
    shuffled["runDir"] = "260902-1705"
    assert norm.dumps(norm.normalize(doc)) == norm.dumps(norm.normalize(shuffled)), \
        "reordering findings or changing run metadata changed the canonical output"


def test_non_deterministic_dropped():
    out = norm.normalize(sample_findings())
    ids = {t["id"] for t in out["findings"]}
    # Only the two DET registered checks survive into the diff surface.
    assert ids == {
        "A9@backend/src/web/startup.cs#Startup.ConfigureServices",
        "B7@backend/src/web/appsettings.json#key:jwt-signing-key",
    }, "normalizer did not drop exactly the non-deterministic records: %s" % sorted(ids)


def test_diff_converges_on_identical_runs():
    out = norm.normalize(sample_findings())
    result = diff_runs.diff(out["findings"], out["findings"])
    assert result["pass"] is True
    assert result["onlyA"] == [] and result["onlyB"] == []
    assert result["fix_order_match"] is True


def test_diff_flags_a_changed_finding():
    a = norm.normalize(sample_findings())["findings"]
    b = [t for t in a if t["checkId"] != "B7"]  # B7 got fixed in run B
    result = diff_runs.diff(a, b)
    assert result["pass"] is False
    assert result["onlyA"] == ["B7@backend/src/web/appsettings.json#key:jwt-signing-key"]
    assert result["onlyB"] == []


def test_normalize_cli_round_trip(tmp_path=None):
    doc = sample_findings()
    d = tmp_path or tempfile.mkdtemp()
    path = os.path.join(str(d), "findings.json")
    with io.open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    # Two CLI-equivalent normalizations of the same file must be byte-identical.
    first = norm.dumps(norm.normalize(json.load(io.open(path, encoding="utf-8"))))
    second = norm.dumps(norm.normalize(json.load(io.open(path, encoding="utf-8"))))
    assert first == second


def _run():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print("  PASS %s" % t.__name__)
    print("\n%d determinism test(s) passed" % len(tests))


if __name__ == "__main__":
    _run()
