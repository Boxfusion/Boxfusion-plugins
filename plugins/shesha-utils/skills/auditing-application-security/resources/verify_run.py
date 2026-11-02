"""Verify a finished audit run against its own catalogue before anyone reads or commits it.

    python verify_run.py --run-dir security-audits/YYMMDD-HHMM [--repo-root .] [--strict]

The skill promises that every number in a report comes from the catalogue, that no secret
material reaches the output, and that a check which could not run is visible. Those promises
were kept in the last run only because they were checked by hand, and two of them slipped
anyway: per-package counts drifted after review overrides were applied, and the audit output
reproduced the first twelve characters of the JWT signing key. This makes the checks permanent.

Exit code 0 when nothing failed, 1 otherwise. `--strict` also fails on warnings.

What it does NOT do: judge severity, read prose for sense, or decide whether a finding is
right. It checks the mechanical claims - the ones a human reviewer is worst at.
"""

import argparse
import collections
import glob
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from catalog_schema import check_document  # noqa: E402
from digest import items_for, load  # noqa: E402
from posture_scan import SECRET_PATTERNS  # noqa: E402

# Well-known template defaults. The finding IS that they are public, so a report must be able
# to name them. Anything else that looks like a credential must not appear in the output.
KNOWN_DEFAULTS = {"123qwe", "admin", "password", "Password123", "changeme", "P@ssw0rd",
                  "sa", "root", "guest"}

# Paths a report legitimately cites that are middleware rather than catalogued endpoints.
NON_ENDPOINT_PATHS = ("/elmah", "/hangfire", "/swagger", "/ui/playground", "/graphql",
                      "/dynamic/", "/no-auth/", "/login", "/settings/", "/shesha/", "/api/")

TOTALS_LABELS = [
    (re.compile(r"^packages$", re.I), ["packages"]),
    (re.compile(r"custom endpoints", re.I), ["endpoints"]),
    (re.compile(r"^entities", re.I), ["entities"]),
    (re.compile(r"form configurations", re.I), ["configuredForms"]),
    (re.compile(r"coded front-?end", re.I), ["customFormFiles"]),
    (re.compile(r"permissions\s*/\s*roles", re.I), ["permissions", "roles"]),
    (re.compile(r"other findings", re.I), ["otherFindings"]),
]


class Result(object):
    def __init__(self):
        self.rows = []

    def add(self, status, check, message, detail=None):
        self.rows.append({"status": status, "check": check, "message": message,
                          "detail": detail or []})

    def ok(self, check, message, detail=None):
        self.add("PASS", check, message, detail)

    def warn(self, check, message, detail=None):
        self.add("WARN", check, message, detail)

    def fail(self, check, message, detail=None):
        self.add("FAIL", check, message, detail)

    def counts(self):
        return collections.Counter(r["status"] for r in self.rows)


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------

def read(path):
    return io.open(path, encoding="utf-8", errors="replace").read()


def report_files(run_dir):
    return sorted(glob.glob(os.path.join(run_dir, "*.md")))


def package_of_report(path):
    name = os.path.basename(path)
    return name[: -len("-recommendations.md")] if name.endswith("-recommendations.md") else None


def md_table_rows(text, header_contains):
    """Rows of the first markdown table whose header line contains all the given strings."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        head = line.lower()
        if all(h.lower() in head for h in header_contains):
            rows = []
            for row in lines[i + 2:]:
                if not row.strip().startswith("|"):
                    break
                cells = [c.strip() for c in row.strip().strip("|").split("|")]
                rows.append(cells)
            return rows
    return None


def strip_md(cell):
    return re.sub(r"[`*]", "", cell).strip()


# --------------------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------------------

def check_structure(run_dir, res):
    required = ["catalog/_index.json", "recommendations-index.md"]
    missing = [r for r in required if not os.path.isfile(os.path.join(run_dir, r))]
    if missing:
        res.fail("structure", "missing required file(s)", missing)
        return False
    if not os.path.isfile(os.path.join(run_dir, "findings.json")):
        res.warn("structure", "no findings.json - run findings.py so the next audit can diff")
    res.ok("structure", "run directory has the expected shape")
    return True


def check_catalog_schema(run_dir, res):
    """Every catalogue file matches catalog_schema.py: same fields, same order, same types,
    rows sorted. This is what keeps the JSON, and the workbook built from it, the same shape
    from run to run."""
    problems, files = [], 0
    for path in sorted(glob.glob(os.path.join(run_dir, "catalog", "*.json"))):
        name = os.path.basename(path)
        if name in ("_index.json", "review-overrides.json", "digest.json"):
            continue
        files += 1
        try:
            doc = json.load(io.open(path, encoding="utf-8"))
        except ValueError:
            problems.append("%s: not valid JSON" % name)
            continue
        problems.extend(check_document(name, doc))
    if problems:
        res.fail("catalog-schema",
                 "%d schema deviation(s) - re-run build_catalogs.py, or declare the change in "
                 "catalog_schema.py" % len(problems), problems[:10])
    else:
        res.ok("catalog-schema", "%d catalogue file(s) match catalog_schema.py" % files)


def check_package_table(run_dir, index, docs, res):
    text = read(os.path.join(run_dir, "recommendations-index.md"))
    rows = md_table_rows(text, ["package", "urgent"])
    if not rows:
        res.warn("index-package-table", "no per-package table found in the index")
        return
    checked, bad = 0, []
    for cells in rows:
        if len(cells) < 5:
            continue
        pkg = package_of_report(strip_md(cells[-1]))
        if pkg is None or pkg not in docs:
            bad.append("%s -> no such package in the catalogue" % strip_md(cells[-1]))
            continue
        try:
            claimed_urgent, claimed_total = int(strip_md(cells[2])), int(strip_md(cells[3]))
        except ValueError:
            continue
        items = items_for(pkg, docs[pkg])
        urgent = sum(1 for i in items if i["priority"] <= 2)
        checked += 1
        if urgent != claimed_urgent or len(items) != claimed_total:
            bad.append("%s: report says %d urgent / %d total, catalogue says %d / %d"
                       % (pkg, claimed_urgent, claimed_total, urgent, len(items)))
    if bad:
        res.fail("index-package-table",
                 "%d of %d package rows disagree with the catalogue" % (len(bad), checked),
                 bad)
    else:
        res.ok("index-package-table", "all %d package rows match the catalogue" % checked)


def check_totals_table(run_dir, index, res):
    text = read(os.path.join(run_dir, "recommendations-index.md"))
    rows = md_table_rows(text, ["count"])
    if not rows:
        res.warn("index-totals-table", "no totals table found in the index")
        return
    totals = index.get("totals") or {}
    bad, checked, unmapped = [], 0, []
    for cells in rows:
        if len(cells) < 2:
            continue
        label, value = strip_md(cells[0]), strip_md(cells[1])
        keys = None
        for pattern, k in TOTALS_LABELS:
            if pattern.search(label):
                keys = k
                break
        if not keys:
            if label:
                unmapped.append(label)
            continue
        claimed = [int(n) for n in re.findall(r"\d+", value)]
        expected = [totals.get(k) for k in keys]
        # A cell may carry an extra parenthetical figure (e.g. "369 (78 with CRUD)"); the
        # leading numbers are the ones this table is asserting.
        if claimed[:len(expected)] != expected:
            bad.append("%s: report says %s, catalogue totals say %s"
                       % (label, claimed[:len(expected)], expected))
        checked += 1
    if bad:
        res.fail("index-totals-table", "%d total(s) disagree with the catalogue" % len(bad),
                 bad)
    else:
        res.ok("index-totals-table", "%d total(s) match the catalogue" % checked,
               (["not checked (no mapping): " + ", ".join(unmapped[:6])] if unmapped else []))


def check_package_coverage(run_dir, index, docs, res, threshold=5):
    have = {package_of_report(p) for p in report_files(run_dir)}
    have.discard(None)
    index_text = read(os.path.join(run_dir, "recommendations-index.md"))
    missing, orphan = [], []
    for pkg in sorted(docs):
        n = len(items_for(pkg, docs[pkg]))
        if pkg in have or n == 0:
            continue
        if n >= threshold and pkg not in index_text:
            missing.append("%s (%d actionable rows, no file and not named in the index)"
                           % (pkg, n))
    for pkg in sorted(have):
        if pkg not in docs:
            orphan.append("%s-recommendations.md has no catalogue package" % pkg)
    if missing or orphan:
        res.fail("package-coverage", "%d gap(s) between reports and catalogue"
                 % (len(missing) + len(orphan)), missing + orphan)
    else:
        res.ok("package-coverage",
               "%d report file(s); every package with >=%d rows is covered or named"
               % (len(have), threshold))


def catalogue_paths(docs):
    """Every path the catalogue knows about, from endpoints, probes and finding evidence."""
    paths, evidence = set(), []
    for pkg, kinds in docs.items():
        for row in (kinds.get("endpoints") or {}).get("endpoints", []):
            paths.add(row["path"].lower())
            paths.add(row["matchKey"])
            for p in row.get("probeResults") or []:
                pass
        for row in (kinds.get("entities") or {}).get("entities", []):
            for act in (row.get("crudActions") or {}).values():
                paths.add(act["url"].lower())
        for row in (kinds.get("other-findings") or {}).get("findings", []):
            evidence.extend(str(e) for e in row.get("evidence", []))
    return paths, " ".join(evidence).lower()


def check_quoted_paths(run_dir, docs, cache_probe_paths, res):
    paths, evidence = catalogue_paths(docs)
    token_re = re.compile(r"`([^`]+)`")
    unknown = []
    checked = 0
    for path in report_files(run_dir):
        text = read(path)
        for m in token_re.finditer(text):
            tok = m.group(1).strip()
            if not (tok.startswith("/") or tok.startswith("…/") or tok.startswith("...")):
                continue
            core = tok.lstrip("…. ").split("?")[0].rstrip(".,;:)").lower()
            if not core:
                continue
            checked += 1
            if tok.startswith("…") or tok.startswith("...") or core.endswith("*"):
                needle = core.rstrip("*")
                if any(needle in p for p in paths) or needle in evidence:
                    continue
            elif (core in paths or core in evidence
                  or any(p.startswith(core) for p in paths)
                  # Prose abbreviates a family: "Entities/GetAll, `/Get`, `/GetTree`". A
                  # token that is the tail of a catalogued path is shorthand, not an
                  # invention - and an invented tail still matches nothing.
                  or any(p.endswith(core) for p in paths)
                  or core in cache_probe_paths
                  or core.startswith(NON_ENDPOINT_PATHS)):
                continue
            unknown.append("%s: `%s`" % (os.path.basename(path), tok))
    if unknown:
        res.fail("quoted-paths",
                 "%d quoted path(s) do not appear anywhere in the catalogue" % len(unknown),
                 unknown[:15])
    else:
        res.ok("quoted-paths", "all %d quoted path(s) trace to the catalogue" % checked)


def repo_secret_values(repo_root):
    """Candidate secret values from the repository's own tracked configuration."""
    values = set()
    for pattern in ("backend/src/**/appsettings*.json", "*.yaml", "*.yml", "**/.env"):
        for path in glob.glob(os.path.join(repo_root, pattern), recursive=True):
            if "/obj/" in path.replace("\\", "/") or "/bin/" in path.replace("\\", "/"):
                continue
            try:
                text = read(path)
            except Exception:
                continue
            for _, rx in SECRET_PATTERNS:
                for m in re.finditer(rx, text):
                    val = m.group(1) if m.groups() else m.group(0)
                    val = val.strip()
                    if (len(val) >= 12 and val not in KNOWN_DEFAULTS
                            and not val.startswith(("$(", "${", "#{"))):
                        values.add(val)
    return values


def check_secrets(run_dir, repo_root, res):
    blob = ""
    for path in glob.glob(os.path.join(run_dir, "**", "*"), recursive=True):
        if os.path.isfile(path):
            try:
                blob += read(path)
            except Exception:
                continue
    leaked = []
    for val in repo_secret_values(repo_root):
        # Any 8-character window is enough to be a disclosure, and is what caught the
        # 12-character "preview" the last run put in a report.
        windows = {val[i:i + 8] for i in range(max(1, len(val) - 7))}
        hit = sorted(w for w in windows if w in blob)
        if hit:
            leaked.append("a %d-char secret from tracked config appears in the run output "
                          "(matched %d window(s), e.g. %d chars starting '%s…')"
                          % (len(val), len(hit), len(hit[0]), hit[0][:2]))
    jwts = re.findall(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.", blob)
    if jwts:
        leaked.append("%d JWT-shaped string(s) in the run output" % len(jwts))
    if leaked:
        res.fail("secrets", "secret material reached the audit output", leaked)
    else:
        res.ok("secrets", "no secret material in the run output "
                          "(known template defaults such as 123qwe are exempt by design)")


def check_disclosure(run_dir, index, res):
    text = read(os.path.join(run_dir, "recommendations-index.md"))
    missing = [m for m in (index.get("inputsMissing") or [])
               if m.split(".")[0] not in text]
    if missing:
        res.fail("missing-inputs-disclosed",
                 "the index does not mention %d missing input(s)" % len(missing), missing)
    elif index.get("inputsMissing"):
        res.ok("missing-inputs-disclosed",
               "all %d missing input(s) are named in the index"
               % len(index["inputsMissing"]))
    else:
        res.ok("missing-inputs-disclosed", "no missing inputs to disclose")

    conf = index.get("confidence") or {}
    detected = set(conf.get("frontendsDetected") or [])
    scanned = set(conf.get("frontendsScanned") or [])
    if detected - scanned and "front-end" not in text.lower():
        res.fail("missing-inputs-disclosed",
                 "%d front-end(s) were not scanned and the index does not say so"
                 % len(detected - scanned))


def check_overrides(index, res):
    review = index.get("review") or {}
    unmatched = review.get("overridesUnmatched") or []
    if unmatched:
        res.fail("overrides", "%d review override(s) matched nothing - a decision was lost"
                 % len(unmatched), unmatched)
    elif review.get("overridesApplied"):
        res.ok("overrides", "%d review override(s) applied, none unmatched"
               % review["overridesApplied"])
    else:
        res.warn("overrides",
                 "no review overrides were applied - every severity and disposition in the "
                 "reports is still a machine heuristic")


def check_reviewed_citations(run_dir, docs, res):
    """Rows a report leans on that the review pass never confirmed."""
    reviewed, unreviewed = {}, {}
    for pkg, kinds in docs.items():
        for row in (kinds.get("endpoints") or {}).get("endpoints", []):
            (reviewed if row.get("reviewed") else unreviewed)[row["path"].lower()] = pkg
        for row in (kinds.get("entities") or {}).get("entities", []):
            (reviewed if row.get("reviewed") else unreviewed)[row["entity"].lower()] = pkg
    cited_unreviewed = set()
    for path in report_files(run_dir):
        text = read(path).lower()
        for key in unreviewed:
            if len(key) > 12 and key in text:
                cited_unreviewed.add(key)
    if cited_unreviewed:
        res.warn("reviewed-citations",
                 "%d row(s) cited in reports carry an unreviewed heuristic severity or "
                 "disposition" % len(cited_unreviewed),
                 sorted(cited_unreviewed)[:10])
    else:
        res.ok("reviewed-citations", "every row cited in a report was reviewed")


def check_posture_groups(cache_dir_path, res):
    path = os.path.join(cache_dir_path, "posture.json")
    if not os.path.isfile(path):
        res.warn("posture-groups", "no posture.json - token, rate-limiting, secret and "
                                   "dependency checks did not run at all")
        return
    try:
        doc = json.load(io.open(path, encoding="utf-8"))
    except ValueError:
        res.fail("posture-groups", "posture.json is not valid JSON")
        return
    present = {(f.get("check") or "?")[0].upper() for f in doc.get("findings", [])}
    absent = [g for g in "TRGD" if g not in present]
    if absent:
        res.fail("posture-groups",
                 "no result for posture group(s) %s - the catalogue shows nothing for them, "
                 "which reads as clean" % ", ".join(absent))
    else:
        groups = doc.get("groups") or {}
        stamps = sorted({v.get("ranAt") for v in groups.values() if v.get("ranAt")})
        res.ok("posture-groups", "all four posture groups have a result",
               ["group run times: %s" % ", ".join(stamps)] if len(stamps) > 1 else [])


def check_findings_index(run_dir, res):
    path = os.path.join(run_dir, "findings.json")
    if not os.path.isfile(path):
        return
    try:
        doc = json.load(io.open(path, encoding="utf-8"))
    except ValueError:
        res.fail("findings-index", "findings.json is not valid JSON")
        return
    import findings as findings_mod
    fresh = findings_mod.build(run_dir)
    if fresh is None:
        res.warn("findings-index", "could not rebuild findings.json for comparison")
        return
    if fresh["findingCount"] != doc.get("findingCount"):
        res.fail("findings-index",
                 "findings.json is stale: it holds %s rows, the catalogue now yields %d"
                 % (doc.get("findingCount"), fresh["findingCount"]),
                 ["re-run findings.py after the last build_catalogs.py"])
    else:
        res.ok("findings-index", "findings.json matches the catalogue (%d rows)"
               % fresh["findingCount"])


def check_reproducibility(run_dir, res):
    """The determinism gate (references/determinism-standard.md §0, §8): two builds of the same
    catalogue must normalize to byte-identical canonical findings. Catches a check that leaked a
    line number, a timestamp or dict-ordering into its diff tuple - the class of defect that
    makes a 'same commit, same findings' promise quietly false."""
    import findings as findings_mod
    import normalize_findings as norm
    a = findings_mod.build(run_dir)
    b = findings_mod.build(run_dir)
    if a is None or b is None:
        res.warn("reproducibility", "no catalogue to build findings from - gate not run")
        return
    bytes_a = norm.dumps(norm.normalize(a))
    bytes_b = norm.dumps(norm.normalize(b))
    if bytes_a != bytes_b:
        # Narrow it to the first differing tuple so the cause is obvious.
        ta = {t["id"]: t for t in norm.normalize(a)["findings"]}
        tb = {t["id"]: t for t in norm.normalize(b)["findings"]}
        detail = sorted(set(ta) ^ set(tb))[:10] or ["tuple contents differ for a shared id"]
        res.fail("reproducibility",
                 "two builds of this run normalize differently - the findings are not "
                 "reproducible", detail)
        return
    deterministic = [t for t in norm.normalize(a)["findings"]]
    res.ok("reproducibility",
           "two builds normalize byte-identically (%d deterministic finding(s) in the "
           "acceptance diff)" % len(deterministic))


# --------------------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--url", default="http://localhost:21021")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero on warnings as well as failures")
    ap.add_argument("--threshold", type=int, default=5,
                    help="actionable rows above which a package needs its own report file")
    args = ap.parse_args()

    run_dir = args.run_dir.rstrip("/\\")
    res = Result()
    if not check_structure(run_dir, res):
        report(res)
        return 1

    index = json.load(io.open(os.path.join(run_dir, "catalog", "_index.json"),
                              encoding="utf-8"))
    _, docs = load(run_dir, None)

    from shesha_audit import cache_dir
    cache_path = args.cache or cache_dir(args.repo_root, args.url)
    probe_paths = set()
    probe_file = os.path.join(cache_path, "probe-results.json")
    if os.path.isfile(probe_file):
        try:
            for r in json.load(io.open(probe_file, encoding="utf-8")).get("results", []):
                probe_paths.add(r["path"].split("?")[0].rstrip("/").lower())
        except ValueError:
            pass

    check_catalog_schema(run_dir, res)
    check_package_table(run_dir, index, docs, res)
    check_totals_table(run_dir, index, res)
    check_package_coverage(run_dir, index, docs, res, args.threshold)
    check_quoted_paths(run_dir, docs, probe_paths, res)
    check_secrets(run_dir, args.repo_root, res)
    check_disclosure(run_dir, index, res)
    check_overrides(index, res)
    check_reviewed_citations(run_dir, docs, res)
    check_posture_groups(cache_path, res)
    check_findings_index(run_dir, res)
    check_reproducibility(run_dir, res)

    counts = report(res)
    if counts["FAIL"]:
        return 1
    if args.strict and counts["WARN"]:
        return 1
    return 0


def report(res):
    counts = res.counts()
    print("verifying %d check(s)\n" % len(res.rows))
    for row in res.rows:
        print("  %-5s %-26s %s" % (row["status"], row["check"], row["message"]))
        for line in row["detail"]:
            print("          - %s" % line)
    print("\n%d pass, %d warn, %d fail"
          % (counts.get("PASS", 0), counts.get("WARN", 0), counts.get("FAIL", 0)))
    if counts.get("FAIL"):
        print("\nThe run is not ready to be read or committed. Fix the failures and re-run "
              "build_catalogs.py, then verify again.")
    return {"FAIL": counts.get("FAIL", 0), "WARN": counts.get("WARN", 0)}


if __name__ == "__main__":
    sys.exit(main())
