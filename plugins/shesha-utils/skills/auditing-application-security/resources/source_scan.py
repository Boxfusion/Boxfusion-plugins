"""Scan application-owned source for the checks in app-vulnerability-baseline.md.

    python source_scan.py [--repo-root .] [--cache DIR] [--url ...]

Emits findings with `file:line` already attached. Revision 1 of the pd-Hcm audit cited four
Startup.cs line numbers from memory and every one was wrong; this removes that class of
error entirely.

It reports facts, not severities. Deciding that a wildcard CORS policy is CRITICAL in this
application is a judgement the model makes with the baseline in hand - the script only
establishes that the code says what it says, and where.
"""

import argparse
import io
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shesha_audit import cache_dir, ensure_dir, write_json  # noqa: E402

# id -> (regex, what it means, expected)
STARTUP_CHECKS = [
    ("A9-auth-filter", r"Filters\.AddService\(\s*typeof\(SheshaAuthorizationFilter\)",
     "SheshaAuthorizationFilter registered", "present"),
    ("A2-cors-wildcard", r"SetIsOriginAllowed\s*\(", "CORS wildcard predicate", "absent"),
    ("A3-cors-credentials", r"AllowCredentials\s*\(", "CORS AllowCredentials", "absent-with-wildcard"),
    ("A1-cors-origins", r"WithOrigins\s*\(", "CORS explicit origin allowlist", "present"),
    ("A4-graphql-playground", r"UseGraphQLPlayground\s*\(", "GraphQL Playground", "guarded"),
    ("A5-swagger-ui", r"UseSwaggerUI\s*\(", "Swagger UI", "guarded"),
    ("A5-swagger", r"app\.UseSwagger\s*\(", "Swagger JSON middleware", "guarded"),
    ("A6-security-headers", r"UseSecurityHeaders\s*\(", "Security headers middleware", "present"),
    ("A7-csp", r"Content-Security-Policy", "Content-Security-Policy header", "present"),
    ("A8-hsts", r"UseHsts\s*\(", "HSTS", "present"),
    ("A10-hangfire", r"UseHangfireDashboard\s*\(", "Hangfire dashboard", "guarded"),
    ("A11-elmah", r"UseSheshaElmah\s*\(|UseElmah\s*\(", "ElmahCore error log middleware", "guarded"),
    ("A12-env-guard", r"IsDevelopment\s*\(\)|IsProduction\s*\(\)",
     "any environment guard at all", "present"),
]

SETTINGS_CHECKS = [
    ("B1-jwt-key", r"\"SecurityKey\"\s*:\s*\"([^\"]+)\"", "JWT signing key literal"),
    ("B2-passphrase", r"\"EncryptionPassPhrase\"\s*:", "Authentication:EncryptionPassPhrase"),
    ("B3-cors-origins", r"\"CorsOrigins\"\s*:\s*\"([^\"]*)\"", "App:CorsOrigins"),
    ("B4-conn-password", r"[Pp]assword\s*=\s*([^\";]+)", "connection-string password"),
    ("B5-smtp", r"\"(SmtpPassword|ApiKey|ClientSecret|AccountSid|AuthToken)\"\s*:\s*\"([^\"]+)\"",
     "committed credential"),
]

AUTH_ATTRS = re.compile(
    r"\[\s*(SheshaAuthorize|AbpAuthorize|AbpMvcAuthorize|Authorize|AllowAnonymous|"
    r"AbpAllowAnonymous)\b([^\]]*)\]")
ROUTE_ATTR = re.compile(r"\[\s*Route\(\s*\"([^\"]+)\"")
HTTP_ATTR = re.compile(r"\[\s*Http(Get|Post|Put|Delete|Patch|Head)\b[^\]]*\]")
PUBLIC_METHOD = re.compile(r"public\s+(?:async\s+)?[\w<>\[\],\?\s\.]+\s+(\w+)\s*\(")
ENTITY_ATTR = re.compile(r"\[\s*Entity\(([^\]]*)\)\s*\]")
SPEC_RE = re.compile(r"GlobalSpecification|ShaSpecification<|ApplySpecifications|"
                     r"DisableSpecifications")


def walk_cs(src):
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in ("obj", "bin")]
        for fn in filenames:
            if fn.endswith(".cs"):
                yield os.path.join(dirpath, fn)


def lines_of(path):
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read().split("\n")


def rel(repo_root, path):
    return os.path.relpath(path, repo_root).replace("\\", "/")


def scan_startup(repo_root, findings):
    src = os.path.join(repo_root, "backend", "src")
    hosts = [p for p in walk_cs(src) if os.path.basename(p) == "Startup.cs"]
    for path in hosts:
        lines = lines_of(path)
        text = "\n".join(lines)
        present = {}
        for cid, pattern, label, expected in STARTUP_CHECKS:
            hits = [(i + 1, lines[i].strip())
                    for i in range(len(lines)) if re.search(pattern, lines[i])]
            present[cid] = hits
            findings.append({
                "check": cid, "label": label, "expected": expected,
                "file": rel(repo_root, path),
                "found": bool(hits),
                "locations": [{"line": ln, "code": code[:200]} for ln, code in hits],
            })
        # The one combination worth calling out explicitly.
        if present.get("A2-cors-wildcard") and present.get("A3-cors-credentials"):
            findings.append({
                "check": "A2+A3", "label":
                    "CORS wildcard predicate combined with AllowCredentials",
                "expected": "never both", "file": rel(repo_root, path), "found": True,
                "locations": [{"line": present["A2-cors-wildcard"][0][0],
                               "code": "SetIsOriginAllowed(...) + AllowCredentials()"}],
                "note": "Any origin can make credentialed cross-origin calls with a "
                        "logged-in user's session.",
            })


def scan_settings(repo_root, findings):
    src = os.path.join(repo_root, "backend", "src")
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in ("obj", "bin")]
        for fn in filenames:
            if not (fn.startswith("appsettings") and fn.endswith(".json")):
                continue
            path = os.path.join(dirpath, fn)
            lines = lines_of(path)
            tracked = is_tracked(repo_root, path)
            for cid, pattern, label in SETTINGS_CHECKS:
                hits = [(i + 1, lines[i].strip())
                        for i in range(len(lines)) if re.search(pattern, lines[i])]
                findings.append({
                    "check": cid, "label": label, "file": rel(repo_root, path),
                    "gitTracked": tracked, "found": bool(hits),
                    "locations": [{"line": ln, "code": code[:200]} for ln, code in hits],
                })


def is_tracked(repo_root, path):
    try:
        out = subprocess.run(["git", "ls-files", "--error-unmatch", path],
                             cwd=repo_root, capture_output=True, timeout=20)
        return out.returncode == 0
    except Exception:
        return None


def scan_services(repo_root, findings):
    src = os.path.join(repo_root, "backend", "src")
    services = []
    for path in walk_cs(src):
        base = os.path.basename(path)
        if not (base.endswith("AppService.cs") or base.endswith("Controller.cs")):
            continue
        lines = lines_of(path)
        text = "\n".join(lines)
        attrs = [{"attr": m.group(1), "args": m.group(2).strip(),
                  "line": text[:m.start()].count("\n") + 1}
                 for m in AUTH_ATTRS.finditer(text)]
        routes = [{"route": m.group(1), "line": text[:m.start()].count("\n") + 1}
                  for m in ROUTE_ATTR.finditer(text)]
        endpoints = []
        for m in HTTP_ATTR.finditer(text):
            ln = text[:m.start()].count("\n") + 1
            after = text[m.end():m.end() + 400]
            pm = PUBLIC_METHOD.search(after)
            endpoints.append({"verb": m.group(1).upper(), "line": ln,
                              "method": pm.group(1) if pm else None})
        services.append({
            "file": rel(repo_root, path),
            "kind": "controller" if base.endswith("Controller.cs") else "appservice",
            "isControllerBase": bool(re.search(r":\s*ControllerBase\b", text)),
            "isDynamicCrud": "IDynamicCrudAppService" in text,
            "authAttributes": attrs,
            "routes": routes,
            "httpEndpoints": endpoints,
            "hasAnyAuthAttribute": bool(attrs),
        })
    findings.append({"check": "C1-C6", "label": "application services and controllers",
                     "services": services,
                     "withoutAnyAuthAttribute":
                         [s["file"] for s in services if not s["hasAnyAuthAttribute"]]})


def scan_entities(repo_root, findings):
    src = os.path.join(repo_root, "backend", "src")
    entities = []
    for path in walk_cs(src):
        lines = lines_of(path)
        text = "\n".join(lines)
        for m in ENTITY_ATTR.finditer(text):
            entities.append({
                "file": rel(repo_root, path),
                "line": text[:m.start()].count("\n") + 1,
                "args": m.group(1).strip(),
                "disablesAppService": "DisableGenerateApplicationService" in m.group(1),
            })
    findings.append({"check": "D1-D5", "label": "application entities",
                     "count": len(entities), "entities": entities,
                     "withDisabledAppService":
                         [e for e in entities if e["disablesAppService"]]})


def scan_specifications(repo_root, findings):
    src = os.path.join(repo_root, "backend", "src")
    hits = []
    for path in walk_cs(src):
        lines = lines_of(path)
        for i, line in enumerate(lines):
            if SPEC_RE.search(line):
                hits.append({"file": rel(repo_root, path), "line": i + 1,
                             "code": line.strip()[:200]})
    findings.append({"check": "D5-specifications",
                     "label": "global specifications / row-level security",
                     "found": bool(hits), "count": len(hits), "locations": hits})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--url", default="http://localhost:21021")
    args = ap.parse_args()

    root = os.path.abspath(args.repo_root)
    findings = []
    scan_startup(root, findings)
    scan_settings(root, findings)
    scan_services(root, findings)
    scan_entities(root, findings)
    scan_specifications(root, findings)

    cache = args.cache or cache_dir(args.repo_root, args.url)
    ensure_dir(cache)
    write_json(os.path.join(cache, "source_scan.json"), {"findings": findings})

    print("=== Startup.cs and appsettings ===")
    for f in findings:
        if "locations" not in f:
            continue
        mark = "FOUND  " if f["found"] else "absent "
        # Most checks carry the file on the finding; D5 carries it per location.
        loc = ", ".join("%s:%d" % (l.get("file") or f.get("file"), l["line"])
                        for l in f["locations"][:3])
        print("  %s %-24s %-46s %s"
              % (mark, f["check"], f["label"], loc))
        for l in f["locations"][:2]:
            print("           %s" % l["code"][:110])

    svc = next(f for f in findings if f["check"] == "C1-C6")
    ents = next(f for f in findings if f["check"] == "D1-D5")
    print("\n=== services and controllers ===")
    print("  %d app services/controllers; %d carry NO authorization attribute"
          % (len(svc["services"]), len(svc["withoutAnyAuthAttribute"])))
    for s in svc["services"]:
        if s["authAttributes"]:
            for a in s["authAttributes"]:
                print("    %s:%d  [%s%s]" % (s["file"], a["line"], a["attr"],
                                             (" " + a["args"]) if a["args"] else ""))
    plain = [s for s in svc["services"]
             if s["isControllerBase"] and not s["hasAnyAuthAttribute"]]
    if plain:
        print("\n  ControllerBase classes with no authorization attribute "
              "(no per-action PermissionedObject row exists to tighten instead - "
              "these must be fixed in source):")
        for s in plain:
            print("    %-70s %d endpoints" % (s["file"], len(s["httpEndpoints"])))

    print("\n=== entities ===")
    print("  %d [Entity(...)] declarations; %d declare DisableGenerateApplicationService"
          % (ents["count"], len(ents["withDisabledAppService"])))

    spec = next(f for f in findings if f["check"] == "D5-specifications")
    print("\n=== specifications ===")
    print("  %d matches. %s" % (spec["count"],
          "No global specifications: there is no row-level security." if not spec["found"]
          else "Review each for coverage of sensitive entities."))
    print("\nwritten %s" % os.path.join(cache, "source_scan.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
