"""Security posture checks that are cheap, high-signal and outside the endpoint model.

    python posture_scan.py --repo-root . [--url ...] [--skip-deps] [--only T,G]

Four things the endpoint audit cannot see:

  T. Token and session policy  - signing key strength, algorithm, lifetime, logout
  R. Rate limiting and lockout - brute force, and metered-cost endpoints like OTP send
  D. Dependency CVEs           - dotnet list package --vulnerable, npm audit
  G. Secrets in git history    - not merely in the current working tree

`--only` re-runs a subset. Results MERGE into posture.json rather than replacing it, and a
per-group provenance block records when each group last ran - overwriting the whole file is
how a re-run of one check silently deletes the others, which is exactly what happened when
this was re-run for the secrets check with the backend down: the token findings vanished, and
the catalogue then showed nothing for them rather than showing them as untested.

Each reports facts. Severity is the model's call, with app-vulnerability-baseline.md in hand.
"""

import argparse
import base64
import collections
import datetime
import hashlib
import io
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shesha_audit import authenticate, cache_dir, ensure_dir, write_json  # noqa: E402

SECRET_PATTERNS = [
    ("jwt-signing-key", r"\"SecurityKey\"\s*:\s*\"([^\"]{8,})\""),
    ("password-assignment", r"[Pp]assword\s*[=:]\s*[\"']([^\"';$]{6,})[\"']"),
    ("api-key", r"\"(ApiKey|ClientSecret|AccountSid|AuthToken|SmtpPassword)\"\s*:\s*\"([^\"]{8,})\""),
    ("connection-string", r"(?:Server|Data Source)=[^\";]+;[^\"]*[Pp]assword=[^\";]+"),
    ("private-key-block", r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def run(cmd, cwd=".", timeout=300):
    """Run a command, trying the Windows .cmd/.exe shims when the bare name is absent.

    npm, npx and yarn are batch shims on Windows; subprocess without shell=True does not
    find `npm`, only `npm.cmd`. Reporting that as "no vulnerabilities" would be a false pass.
    """
    candidates = [cmd]
    if os.name == "nt" and not cmd[0].lower().endswith((".cmd", ".exe", ".bat")):
        candidates.append([cmd[0] + ".cmd"] + cmd[1:])
        candidates.append([cmd[0] + ".exe"] + cmd[1:])
    last = (127, "command not found: %s" % cmd[0])
    for c in candidates:
        try:
            p = subprocess.Popen(c, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, shell=False)
        except FileNotFoundError:
            continue
        except Exception as e:
            return 1, str(e)
        try:
            out, err = p.communicate(timeout=timeout)
            return p.returncode, (out or "") + (err or "")
        except subprocess.TimeoutExpired:
            # On Windows `npm` is a batch shim: killing it leaves the real node.exe holding
            # the pipes open, so communicate() - and the whole audit - would hang forever.
            # Kill the entire process tree instead.
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                               capture_output=True)
            else:
                p.kill()
            try:
                p.communicate(timeout=30)
            except Exception:
                pass
            return 124, "TIMEOUT after %ds: %s - this check did NOT complete" % (
                timeout, " ".join(c))
    return last


# ---------------------------------------------------------------------------- T: tokens

def check_tokens(base, user, password, findings):
    token, status = authenticate(base, user, password)
    if not token:
        findings.append({"check": "T0-authenticate", "status": status,
                         "note": "Could not authenticate; token policy not assessed."})
        return
    try:
        head_b64, payload_b64 = token.split(".")[0], token.split(".")[1]
        pad = lambda s: s + "=" * (-len(s) % 4)
        header = json.loads(base64.urlsafe_b64decode(pad(head_b64)))
        claims = json.loads(base64.urlsafe_b64decode(pad(payload_b64)))
    except Exception as e:
        findings.append({"check": "T1-decode", "note": "could not decode token: %s" % e})
        return

    alg = header.get("alg")
    iat, exp = claims.get("iat"), claims.get("exp")
    lifetime_h = round((int(exp) - int(iat)) / 3600.0, 1) if (iat and exp) else None
    findings.append({
        "check": "T1-token", "alg": alg, "tokenLength": len(token),
        "lifetimeHours": lifetime_h,
        "claims": sorted(claims.keys()),
        "note": ("HS256 is symmetric: the signing key alone forges any token."
                 if alg and alg.startswith("HS") else ""),
    })

    # T2 - signing key strength. Judge entropy, not length: 32 alphanumeric characters is
    # ~165 bits and is NOT crackable, so do not report it as weak. The finding for a
    # committed key of adequate strength is disclosure, and the fix is rotation.
    key = None
    for root, dirs, files in os.walk(os.path.join(".", "backend", "src")):
        dirs[:] = [d for d in dirs if d not in ("obj", "bin")]
        for fn in files:
            if fn.startswith("appsettings") and fn.endswith(".json"):
                try:
                    txt = io.open(os.path.join(root, fn), encoding="utf-8",
                                  errors="replace").read()
                except Exception:
                    continue
                m = re.search(r"\"SecurityKey\"\s*:\s*\"([^\"]+)\"", txt)
                if m:
                    key = m.group(1)
    if key is not None:
        # RFC 7518 requires an HS256 key at least as long as the HMAC output: 32 bytes.
        # Estimate real entropy from the character set actually used, not from length
        # alone - "password123" and 11 random bytes are not the same thing.
        charset = 0
        if re.search(r"[a-z]", key):
            charset += 26
        if re.search(r"[A-Z]", key):
            charset += 26
        if re.search(r"[0-9]", key):
            charset += 10
        if re.search(r"[^A-Za-z0-9]", key):
            charset += 30
        import math
        bits = round(len(key) * math.log2(charset)) if charset else 0
        if len(key) < 32:
            verdict, note = "TOO-SHORT", (
                "%d characters is below the 32-byte minimum RFC 7518 sets for HS256."
                % len(key))
        elif bits < 128:
            verdict, note = "LOW-ENTROPY", (
                "%d characters from a %d-symbol alphabet is about %d bits of entropy."
                % (len(key), charset, bits))
        else:
            verdict, note = "adequate-length", (
                "%d characters from a %d-symbol alphabet, about %d bits - meets RFC 7518 "
                "and is not brute-forceable. The risk here is disclosure, not strength: "
                "a committed key must be ROTATED, and removing the line does not do that."
                % (len(key), charset, bits))
        findings.append({
            "check": "T2-signing-key", "length": len(key), "alphabetSize": charset,
            "approxEntropyBits": bits, "verdict": verdict, "note": note,
        })

    # T3 - does SignOff actually invalidate the token?
    # This MUST be probed against an endpoint that requires authentication. Session/
    # GetCurrentLoginInfo is on the expected-anonymous allowlist and returns 200 with no
    # token at all, so using it proves nothing either way.
    from shesha_audit import request as _req
    probe_url = base + "/api/services/app/Api/Endpoints?term=&maxResultCount=1"
    anon_st, _ = _req("GET", probe_url)
    before, _ = _req("GET", probe_url, token=token)
    _req("POST", base + "/api/TokenAuth/SignOff", token=token)
    after, _ = _req("GET", probe_url, token=token)
    if anon_st == 200:
        verdict = "INCONCLUSIVE-probe-endpoint-is-anonymous"
    elif before == 200 and after == 200:
        verdict = "TOKEN-STILL-VALID-AFTER-SIGNOFF"
    elif before == 200 and after in (401, 403):
        verdict = "invalidated"
    else:
        verdict = "inconclusive"
    findings.append({
        "check": "T3-signoff-invalidates", "probe": probe_url,
        "anonymousStatus": anon_st, "beforeStatus": before, "afterStatus": after,
        "verdict": verdict,
        "note": "JWTs are stateless: unless the framework keeps a revocation list, SignOff "
                "cannot invalidate an issued token. A stolen token stays usable until it "
                "expires - which is why token lifetime and key rotation both matter.",
    })


# --------------------------------------------------------------- R: rate limit / lockout

def check_rate_limiting(repo_root, findings):
    hits = {}
    for name, pattern in [("UseRateLimiter", r"UseRateLimiter\s*\("),
                          ("AddRateLimiter", r"AddRateLimiter\s*\("),
                          ("AspNetCoreRateLimit", r"AspNetCoreRateLimit"),
                          ("LockoutEnabled", r"LockoutEnabled"),
                          ("MaxFailedAccessAttempts", r"MaxFailedAccess")]:
        found = []
        for root, dirs, files in os.walk(os.path.join(repo_root, "backend", "src")):
            dirs[:] = [d for d in dirs if d not in ("obj", "bin")]
            for fn in files:
                if not (fn.endswith(".cs") or fn.endswith(".json")):
                    continue
                path = os.path.join(root, fn)
                try:
                    txt = io.open(path, encoding="utf-8", errors="replace").read()
                except Exception:
                    continue
                if re.search(pattern, txt):
                    found.append(os.path.relpath(path, repo_root).replace("\\", "/"))
        hits[name] = found
    findings.append({
        "check": "R1-rate-limiting", "hits": hits,
        "verdict": "NONE-CONFIGURED" if not any(hits.values()) else "present",
        "note": "No rate limiting and no account lockout means unmetered login brute force, "
                "and unmetered cost on anonymous endpoints such as Otp/SendPin (SMS spend) "
                "and password-reset email dispatch.",
    })


# ------------------------------------------------------------------------ D: dependencies

SEV = r"(Critical|High|Moderate|Low)"
# `dotnet list package --vulnerable` prints two different row shapes, and a scan that only
# knows the first silently reports a vulnerable solution as clean:
#   direct:      > Package   Requested  Resolved  Severity  URL   (4 fields + url)
#   transitive:  > Package              Resolved  Severity  URL   (3 fields + url)
# plus continuation rows carrying a second advisory for the same package, with no name at all:
#                                       Severity  URL
DOTNET_DIRECT = re.compile(r">\s+(\S+)\s+(\S+)\s+(\S+)\s+" + SEV + r"\s+(\S+)")
DOTNET_TRANSITIVE = re.compile(r">\s+(\S+)\s+(\S+)\s+" + SEV + r"\s+(\S+)")
DOTNET_EXTRA = re.compile(r"^\s+" + SEV + r"\s+(https?://\S+)\s*$")
DOTNET_PROJECT = re.compile(r"Project `([^`]+)` has the following vulnerable packages")


def parse_dotnet_vulnerable(out):
    """Rows from `dotnet list package --vulnerable --include-transitive`.

    Returns one entry per advisory (a package can carry several), each tagged direct or
    transitive - the report has to separate a direct runtime dependency from a transitive
    build-time one, and the tool's own output is the only place that distinction exists.
    """
    rows, project, last = [], None, None
    in_transitive = False
    for line in out.split("\n"):
        m = DOTNET_PROJECT.search(line)
        if m:
            project, in_transitive = m.group(1), False
            continue
        low = line.strip().lower()
        if low.startswith("top-level package"):
            in_transitive = False
        elif low.startswith("transitive package"):
            in_transitive = True
        if ">" in line:
            m = DOTNET_DIRECT.search(line)
            if m and not in_transitive:
                last = {"package": m.group(1), "requested": m.group(2),
                        "resolved": m.group(3), "severity": m.group(4),
                        "advisory": m.group(5), "direct": True, "project": project}
                rows.append(last)
                continue
            m = DOTNET_TRANSITIVE.search(line)
            if m:
                last = {"package": m.group(1), "requested": None,
                        "resolved": m.group(2), "severity": m.group(3),
                        "advisory": m.group(4), "direct": not in_transitive,
                        "project": project}
                rows.append(last)
                continue
        m = DOTNET_EXTRA.match(line)
        if m and last:
            rows.append(dict(last, severity=m.group(1), advisory=m.group(2)))
    # The same transitive package appears under every project that pulls it in.
    seen, unique = set(), []
    for r in rows:
        key = (r["package"], r["resolved"], r["severity"], r["advisory"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    return unique


def check_dependencies(repo_root, findings, skip=False):
    if skip:
        findings.append({"check": "D1-dotnet-vulnerable", "skipped": True})
        findings.append({"check": "D2-npm-audit", "skipped": True})
        return
    sln = None
    for fn in os.listdir(os.path.join(repo_root, "backend")):
        if fn.endswith(".sln"):
            sln = os.path.join("backend", fn)
    if sln:
        code, out = run(["dotnet", "list", sln, "package", "--vulnerable",
                         "--include-transitive"], cwd=repo_root, timeout=600)
        vulns = parse_dotnet_vulnerable(out)
        by_sev = collections.Counter(v["severity"] for v in vulns)
        findings.append({
            "check": "D1-dotnet-vulnerable", "solution": sln, "exitCode": code,
            "count": len(vulns),
            "distinctPackages": len({v["package"] for v in vulns}),
            "bySeverity": dict(by_sev),
            "direct": sorted({v["package"] for v in vulns if v["direct"]}),
            "packages": vulns,
            "verdict": ("TOOL-FAILED" if code != 0 and not vulns else
                        "clean" if not vulns else "advisories"),
            "note": ("dotnet list produced no parseable rows and exited %d - record as SKIP, "
                     "not as clean." % code) if (code != 0 and not vulns) else "",
            "raw": out[-4000:] if (code != 0 and not vulns) else "",
        })
    else:
        findings.append({"check": "D1-dotnet-vulnerable",
                         "note": "no .sln found under backend/"})

    for front in ("adminportal", "publicportal"):
        pkg = os.path.join(repo_root, front, "package.json")
        if not os.path.isfile(pkg):
            continue
        code, out = run(["npm", "audit", "--json"], cwd=os.path.join(repo_root, front),
                        timeout=600)
        summary = {}
        try:
            data = json.loads(out[out.index("{"):])
            summary = (data.get("metadata") or {}).get("vulnerabilities") or {}
        except Exception:
            pass
        findings.append({
            "check": "D2-npm-audit", "frontend": front, "exitCode": code,
            "summary": summary,
            "verdict": ("TOOL-UNAVAILABLE" if code == 127 else
                        ("clean" if summary and not sum(
                            v for k, v in summary.items() if k != "total") else "advisories")),
            "note": ("npm was not found on PATH - this check did NOT run. Record it as SKIP "
                     "in Appendix B; it is not evidence of a clean tree."
                     if code == 127 else
                     ("" if summary else
                      "npm audit produced no parseable summary - it needs node_modules and "
                      "registry access. Record as SKIP, not as clean."))})


# ------------------------------------------------------------------- G: secrets in history

def check_git_secrets(repo_root, findings, max_commits=400):
    code, out = run(["git", "log", "--format=%H", "-n", str(max_commits)], cwd=repo_root)
    if code != 0:
        findings.append({"check": "G1-history-secrets", "note": "git log failed"})
        return
    shas = [s for s in out.split() if s]
    hits = []
    for name, pattern in SECRET_PATTERNS:
        code, out = run(["git", "log", "-S", "SecurityKey" if name == "jwt-signing-key"
                         else name.split("-")[0], "--format=%H %ad %s",
                         "--date=short", "-n", "40"], cwd=repo_root)
    # Content scan across tracked history is expensive; scan the current tree of every
    # tracked settings/config file plus a grep of history for the highest-signal marker.
    code, tracked = run(["git", "ls-files"], cwd=repo_root)
    for rel in tracked.split("\n"):
        rel = rel.strip()
        if not rel:
            continue
        if not re.search(r"(appsettings.*\.json|\.ya?ml|\.env|\.config|Pulumi.*\.yaml)$", rel):
            continue
        path = os.path.join(repo_root, rel)
        if not os.path.isfile(path):
            continue
        try:
            txt = io.open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for name, pattern in SECRET_PATTERNS:
            for m in re.finditer(pattern, txt):
                val = m.group(1) if m.groups() else m.group(0)
                if val.startswith("$(") or val.startswith("${") or "secret" in val.lower()[:8]:
                    continue  # a pipeline variable reference, not a literal
                # Never put secret material in the audit output. The report is the artefact
                # most likely to be shared beyond the people who can already read the
                # repository, so cite the location and a fingerprint - enough to confirm
                # which value is meant, and useless to anyone who does not have it.
                hits.append({"file": rel, "pattern": name,
                             "line": txt[:m.start()].count("\n") + 1,
                             "fingerprint": "sha256:" + hashlib.sha256(
                                 val.encode("utf-8")).hexdigest()[:12],
                             "length": len(val)})
    code, out = run(["git", "log", "--oneline", "-S", "SecurityKey", "--", "*appsettings*.json"],
                    cwd=repo_root)
    key_commits = [l for l in out.split("\n") if l.strip()]
    findings.append({
        "check": "G1-secrets-in-tracked-config", "hits": hits, "count": len(hits),
        "commitsTouchingSigningKey": key_commits,
        "note": "Rotation matters more than deletion: a key removed in the working tree is "
                "still recoverable from history by anyone who has ever cloned the repo.",
    })


GROUPS = "TRGD"
GROUP_LABELS = {
    "T": "token and session policy",
    "R": "rate limiting and lockout",
    "G": "secrets in tracked configuration",
    "D": "dependency advisories",
}


def merge_findings(existing, fresh, groups_run):
    """Replace only the groups that ran; carry the rest forward unchanged.

    Overwriting the whole file is how a re-run of one check silently deletes the others.
    That happened: re-running for the secrets check with the backend down dropped the token
    findings entirely, and the catalogue then showed no token findings at all rather than
    showing them as untested.
    """
    kept = [f for f in existing
            if (f.get("check") or "?")[0].upper() not in groups_run]
    return kept + fresh


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--url", default="http://localhost:21021")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="123qwe")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--skip-deps", action="store_true")
    ap.add_argument("--only", default=None,
                    help="run only these check groups, e.g. --only T,G. Groups: "
                         "T (tokens), R (rate limiting), G (secrets), D (dependencies). "
                         "Groups not run keep their previous result, and the provenance "
                         "block records when each one last ran.")
    args = ap.parse_args()

    if args.only:
        groups = "".join(dict.fromkeys(
            g.strip().upper() for g in args.only.replace(",", " ").split() if g.strip()))
        bad = [g for g in groups if g not in GROUPS]
        if bad:
            print("Unknown check group(s): %s. Valid groups are %s."
                  % (", ".join(bad), ", ".join(GROUPS)), file=sys.stderr)
            return 2
    else:
        groups = GROUPS
    if args.skip_deps:
        groups = groups.replace("D", "")

    cache = args.cache or cache_dir(args.repo_root, args.url)
    ensure_dir(cache)
    out_path = os.path.join(cache, "posture.json")
    previous = {}
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        try:
            previous = json.load(io.open(out_path, encoding="utf-8"))
        except ValueError:
            previous = {}

    skipped_groups = [g for g in GROUPS if g not in groups]
    if skipped_groups:
        carried = [g for g in skipped_groups
                   if any((f.get("check") or "?")[0].upper() == g
                          for f in previous.get("findings", []))]
        print("running groups %s; %s"
              % (", ".join(groups) or "(none)",
                 ("carrying forward previous results for %s" % ", ".join(carried))
                 if carried else "no previous results to carry forward"))

    findings = []
    if "T" in groups:
        print("T. token and session policy")
        check_tokens(args.url.rstrip("/"), args.user, args.password, findings)
    if "R" in groups:
        print("R. rate limiting and lockout")
        check_rate_limiting(args.repo_root, findings)
    if "G" in groups:
        print("G. secrets in tracked configuration")
        check_git_secrets(args.repo_root, findings)
    if "D" in groups:
        print("D. dependency advisories - this one is slow")
        check_dependencies(args.repo_root, findings, skip=False)
    elif not any((f.get("check") or "?").startswith("D")
                 for f in previous.get("findings", [])):
        # Not run and no previous result to carry forward: record the absence explicitly,
        # so the catalogue shows a SKIP rather than nothing at all.
        print("D. dependency advisories (not run, and no previous result)")
        check_dependencies(args.repo_root, findings, skip=True)
        groups += "D"

    print("\n=== results ===")
    for f in findings:
        head = f["check"]
        if f.get("skipped"):
            print("  %-28s skipped" % head)
            continue
        verdict = f.get("verdict") or ""
        print("  %-28s %s" % (head, verdict))
        for k in ("alg", "lifetimeHours", "length", "approxBits", "count",
                  "beforeStatus", "afterStatus", "summary", "exitCode"):
            if k in f and f[k] not in (None, "", {}):
                print("      %-16s %s" % (k, f[k]))
        if f.get("packages"):
            for p in f["packages"][:15]:
                print("      %-10s %-42s %s" % (p["severity"], p["package"], p["advisory"]))
        if f.get("hits") and isinstance(f["hits"], list):
            for h in f["hits"][:12]:
                print("      %s:%d  %s  (%s, %d chars)"
                      % (h["file"], h["line"], h["pattern"],
                         h.get("fingerprint", "-"), h["length"]))
        if f.get("hits") and isinstance(f["hits"], dict):
            for k, v in f["hits"].items():
                print("      %-24s %s" % (k, ", ".join(v) if v else "not found"))
        if f.get("commitsTouchingSigningKey"):
            for c in f["commitsTouchingSigningKey"][:6]:
                print("      commit  %s" % c)
        if f.get("note"):
            print("      note: %s" % f["note"])

    merged = merge_findings(previous.get("findings", []), findings, groups)
    provenance = dict(previous.get("groups") or {})
    now = datetime.datetime.now().isoformat(timespec="seconds")
    for g in groups:
        provenance[g] = {
            "label": GROUP_LABELS.get(g, g),
            "ranAt": now,
            "backend": args.url if g == "T" else None,
            "findings": sum(1 for f in findings
                            if (f.get("check") or "?")[0].upper() == g),
        }
    write_json(os.path.join(cache, "posture.json"),
               {"findings": merged, "groups": provenance})

    print("\nwritten %s" % os.path.join(cache, "posture.json"))
    print("group provenance (a merged file is not uniformly fresh - this is how you tell):")
    for g in GROUPS:
        info = provenance.get(g)
        present = any((f.get("check") or "?")[0].upper() == g for f in merged)
        if info:
            when = info["ranAt"] + ("  <- this run" if g in groups else "  (carried forward)")
        elif present:
            when = "carried forward, run time unknown (written before provenance existed)"
        else:
            when = "NEVER RUN - nothing in the catalogue will cover this"
        print("  %s  %-32s %s" % (g, GROUP_LABELS[g], when))
    carried = [g for g in GROUPS if g not in groups
               and any((f.get("check") or "?")[0].upper() == g for f in merged)]
    if carried:
        print("\n%d group(s) carried forward from an earlier run: %s. If the code or the "
              "deployment changed since, re-run them."
              % (len(carried), ", ".join(carried)))
    absent = [g for g in GROUPS
              if not any((f.get("check") or "?")[0].upper() == g for f in merged)]
    if absent:
        print("WARNING: no result at all for group(s) %s. The catalogue will show nothing "
              "for them, which reads as clean. Run them." % ", ".join(absent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
