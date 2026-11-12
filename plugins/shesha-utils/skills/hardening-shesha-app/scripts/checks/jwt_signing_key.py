"""jwt-signing-key: the JWT signing key must not be a literal committed to the repository.

`Authentication:JwtBearer:SecurityKey` is the HMAC secret every issued token is signed with.
A literal value in a tracked `appsettings*.json` lets anyone who can read the repository mint
valid tokens for any user in any environment that shares the key (framework #4250). Worse, a
value left at the template default is identical across every Shesha/ABP system built from that
template, so one leak forges tokens everywhere (registry SEC-P). The key is also too weak if it
is shorter than 32 bytes / low-entropy (registry I2).

This check is the FIX owner for the shared CHECK-IDs B1 (committed literal) and references I2
(short key) and SEC-P (starter-key fingerprint). Secret material is NEVER echoed: the report
cites presence, length and a sha256:<12> fingerprint only, and the fix diff is redacted.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core import (Check, Edit, Evidence, Finding, Issue, NotFixable, Repo, Status, config_anchor,
                  register, secret_fingerprint)

KEY = "Authentication:JwtBearer:SecurityKey"
# Captures the literal value so it can be fingerprinted and redacted - never reported verbatim.
VALUE_RE = re.compile(r'("SecurityKey"\s*:\s*)"(?P<val>[^"]*)"')
MIN_BYTES = 32          # HS256 needs >= 256 bits of key material to be sound
FINGERPRINTS = Path(__file__).resolve().parent / "known_jwt_key_fingerprints.json"


def _known_fingerprints() -> dict[str, str]:
    try:
        data = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {e["sha256_12"]: e.get("source", "known starter key") for e in data.get("fingerprints", [])}


def _is_reference(value: str) -> bool:
    """A placeholder or environment/secret reference, not a committed secret."""
    v = value.strip()
    return v == "" or v.startswith("$(") or v.startswith("${") or v.startswith("#{") or v == KEY


# A fix that moves a secret out of the repository must carry these four items in the same
# change (references/checks.md, "Moving a secret out of the repository"). Without them the next
# deployment or pipeline run breaks, and the old value stays live.
MOVED_SECRET_HANDOVER = [
    "Pipeline / host variable: Authentication__JwtBearer__SecurityKey (double underscore = "
    "section separator). Create it as a secret variable in every environment BEFORE merging.",
    "Local developers: dotnet user-secrets set \"Authentication:JwtBearer:SecurityKey\" "
    "\"<fresh 48-byte random value>\" in the Web.Host project (or the same environment "
    "variable). Put these steps in the PR description and the repo's setup notes.",
    "Rotation: the committed value is in git history - flag it for rotation per environment "
    "(presence and fingerprint only in any report). Rotation signs every user out; schedule it.",
    "Warning: until the variable exists, the API starts with an empty key and cannot issue or "
    "validate tokens (sign-in fails). Say so in the PR so reviewers create the variable first.",
]


@register
class JwtSigningKey(Check):
    id = "jwt-signing-key"
    title = "JWT signing key is supplied per environment, not committed"
    severity = "high"
    doc = "references/checks.md section 5"
    # shared determinism contract (check-registry.md B1; references I2 short-key and SEC-P fingerprint)
    canonical_id = "B1"
    canonical_refs = ["I2", "SEC-P"]
    impact_class = "auth_bypass"
    reachability = "anonymous"
    data_sensitivity = "none"
    root_cause = "RC-sec-committed-secret"
    deterministic = True
    plan_id = "PLAN-jwt-key-rotate-to-secret"
    regression_test = "scripts/test_checks.py::JwtSigningKeyTests"
    decision_input = "the literal value of Authentication:JwtBearer:SecurityKey in each tracked appsettings*.json"
    decision_predicate = "non-reference literal -> FAIL; fingerprint in the known-starter list -> FAIL (forgeable); < 32 bytes -> also weak"
    decision_verdict = "FAIL = anyone who can read the repo can mint tokens for any user"
    anchor_strategy = "<path>#key:Authentication:JwtBearer:SecurityKey (never a line number; the value is never shown)"

    def _hits(self, repo: Repo):
        """Yield (path, match, value) for every appsettings file that sets a literal SecurityKey."""
        for path in repo.appsettings():
            text = repo.read(path)
            for m in VALUE_RE.finditer(text):
                yield path, m, m.group("val")

    def scan(self, repo: Repo) -> Finding:
        known = _known_fingerprints()
        issues: list[Issue] = []
        for path, _m, value in self._hits(repo):
            if _is_reference(value):
                continue
            fp = secret_fingerprint(value)
            anchor = config_anchor(repo.rel(path), KEY)
            starter = known.get(fp["sha256_12"])
            if starter:
                issues.append(Issue(
                    Status.FAIL, f"SecurityKey is committed AND identical to a known starter key "
                    f"({starter}) - forgeable across every system built from that template "
                    f"[{fp['sha256_12']}, {fp['length']} bytes]", repo.rel(path), fixable=True,
                    anchor=anchor, evidence=Evidence.VERIFIED_ARTEFACT, canonical_id="SEC-P"))
                continue
            weak = "" if fp["length"] >= MIN_BYTES else f" and is only {fp['length']} bytes (< {MIN_BYTES}; weak, ref I2)"
            issues.append(Issue(
                Status.FAIL, f"SecurityKey is a literal committed to the repository{weak} "
                f"[{fp['sha256_12']}, {fp['length']} bytes] - supply it per environment instead",
                repo.rel(path), fixable=True, anchor=anchor, evidence=Evidence.CODE_ONLY))
        notes = MOVED_SECRET_HANDOVER if issues else None
        return Finding.from_issues(self.id, issues,
                                   f"no committed literal {KEY}; the key is supplied per environment",
                                   notes=notes)

    def fix(self, repo: Repo, finding: Finding) -> list[Edit]:
        """Blank the committed value in tracked appsettings, keeping the key present (so the config
        shape stays documented). The operator then supplies it with user-secrets locally and an
        environment variable / key vault in deployed environments, and ROTATES it (every issued
        token is invalidated - schedule it). The shown diff is redacted; the real value is removed."""
        edits: list[Edit] = []
        by_path: dict[Path, list[tuple]] = {}
        for path, m, value in self._hits(repo):
            if not _is_reference(value):
                by_path.setdefault(path, []).append((m, value))
        for path, hits in by_path.items():
            text = repo.read(path)
            secrets = []
            for m, value in sorted(hits, key=lambda h: h[0].start(), reverse=True):
                text = text[:m.start()] + f'{m.group(1)}""' + text[m.end():]
                secrets.append(value)
            edits.append(Edit(path, text, f"blank the committed JWT SecurityKey in {repo.rel(path)} "
                              "(supply per environment and rotate)", redactions=tuple(secrets)))
        if not edits:
            raise NotFixable("no committed literal SecurityKey to blank; supply and rotate it per environment")
        return edits
