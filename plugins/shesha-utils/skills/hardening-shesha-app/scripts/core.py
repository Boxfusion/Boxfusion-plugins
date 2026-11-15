"""Shared plumbing for hardening checks: repository access, check registry, results, edits.

A check never writes to disk itself. It returns Edit objects; the runner shows them as a
diff and writes them only when --apply is given. That keeps every check dry-run by default.
"""
from __future__ import annotations

import difflib
import hashlib
import importlib
import json
import os
import pkgutil
import re
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable

SKIP_DIRS = {"bin", "obj", "node_modules", ".git", ".vs", ".idea", "packages", "TestResults"}


# --------------------------------------------------------------------------- results

class Status(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    MANUAL = "manual"            # a problem, or possibly one, that needs a human to fix or confirm
    SKIP = "skip"                # could not be assessed (missing input, e.g. no live backend)
    NOT_APPLICABLE = "n/a"       # the check does not apply to this repo or framework version

    @property
    def rank(self) -> int:
        return {"n/a": 0, "skip": 1, "pass": 2, "warn": 3, "manual": 4, "fail": 5}[self.value]


# ----------------------------------------------- shared determinism contract (see the
# auditing-application-security references/determinism-standard.md and check-registry.md).
# These three skills emit into one findings schema so two runs on the same commit converge
# byte-for-byte. hardening is the FIX owner for the checks below; it keys off the SHARED
# CHECK-IDs (I3/I4/J2/A10/B1/A1..) so the same issue is not double-identified between skills.

class Evidence(str, Enum):
    """How strongly an anchor's verdict is proven (determinism-standard §3). A separate axis
    from Status and from severity: take the MAX achieved for an anchor; never upgrade on
    confidence (an anonymous probe already *is* REPRODUCED)."""
    REPRODUCED = "REPRODUCED"                   # live probe reached/opened it
    CONFIRMED_IN_LOGS = "CONFIRMED-IN-LOGS"
    VERIFIED_ARTEFACT = "VERIFIED-ARTEFACT"     # restored-DLL symbol / scanner hit / grep artefact
    CODE_ONLY = "CODE-ONLY"                     # static source match
    DATA_ANOMALY = "DATA-ANOMALY"
    NOT_ASSESSED = "NOT-ASSESSED"               # a required capability was absent (carries a reason)

    @property
    def rank(self) -> int:
        order = ["NOT-ASSESSED", "DATA-ANOMALY", "CODE-ONLY", "VERIFIED-ARTEFACT",
                 "CONFIRMED-IN-LOGS", "REPRODUCED"]
        return order.index(self.value)


# Severity scoring key (determinism-standard §4 / check-registry.md). Severity is DERIVED from
# three declared inputs, never asserted; the flat Check.severity stays only as a display alias.
SEVERITY_BANDS = ["Info", "Low", "Medium", "High", "Critical"]
IMPACT_CLASSES = {"auth_bypass", "data_exposure_pii", "data_integrity", "dos", "info_leak",
                  "maintainability"}
REACHABILITY = ["anonymous", "any_authenticated", "low_priv", "admin_only", "local_only"]
DATA_SENSITIVITY = {"popia_special": 1, "pii_basic": 0, "business": 0, "none": 0}

# base(impact_class, reachability) -> band, in REACHABILITY column order.
_BASE_SEVERITY = {
    "auth_bypass":       ["Critical", "High", "High", "Medium", "Low"],
    "data_exposure_pii": ["Critical", "High", "High", "Medium", "Low"],
    "data_integrity":    ["High", "High", "Medium", "Medium", "Low"],
    "dos":               ["High", "Medium", "Medium", "Low", "Low"],
    "info_leak":         ["High", "Medium", "Low", "Low", "Low"],
    "maintainability":   ["Low", "Low", "Low", "Low", "Low"],
}


def score_severity(impact_class: str, reachability: str, data_sensitivity: str = "none") -> str:
    """Pure function of the three registry inputs; capped at Critical. Evidence is not an input."""
    base = _BASE_SEVERITY[impact_class][REACHABILITY.index(reachability)]
    shifted = min(SEVERITY_BANDS.index(base) + DATA_SENSITIVITY[data_sensitivity],
                  len(SEVERITY_BANDS) - 1)
    return SEVERITY_BANDS[shifted]


# ---- anchors (determinism-standard §2): a symbol/role, NEVER a raw line number (lines drift on
# `dotnet format`). file:line survives only as a non-diffed `locator`.

def norm_path(rel: str) -> str:
    """repo-root-relative -> '/' separators -> lowercase the path -> strip any defensive ':\\d+'."""
    return re.sub(r":\d+$", "", rel.replace("\\", "/")).lower()


def member_anchor(rel: str, type_name: str, member: str) -> str:
    """C# member anchor `<path>#<Type>.<Member>` - the path lowercased, #Symbol.Member verbatim."""
    return f"{norm_path(rel)}#{type_name}.{member}"


def type_anchor(rel: str, type_name: str) -> str:
    return f"{norm_path(rel)}#{type_name}"


def config_anchor(rel: str, key: str) -> str:
    """appsettings key anchor `<path>#key:<Section>:<Key>`."""
    return f"{norm_path(rel)}#key:{key}"


def sln_anchor(token: str) -> str:
    return f"sln:{token}"


def enclosing_type(text: str, index: int) -> str:
    """Best-effort name of the type/record/class declared above `index`; 'Unknown' if none."""
    decls = list(re.finditer(r"\b(?:class|record|struct|interface)\s+(?P<name>\w+)", text[:index]))
    return decls[-1].group("name") if decls else "Unknown"


# ---- secret safety (determinism-standard §10): presence + length + sha256:<12> only, never the
# value. Used by the key check and to redact diffs so a rotated secret is never echoed.

def secret_fingerprint(value: str | None) -> dict:
    if not value:
        return {"present": False, "length": 0, "sha256_12": None}
    return {"present": True, "length": len(value),
            "sha256_12": "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]}


def redact_secrets(text: str, secrets: Iterable[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, f"«redacted {secret_fingerprint(s)['sha256_12']}»")
    return text


@dataclass
class Issue:
    status: Status
    message: str
    location: str | None = None      # "relative/path.cs:123" - a non-diffed display LOCATOR only
    fixable: bool = False
    anchor: str | None = None        # symbol/role anchor (determinism-standard §2); None -> "@none"
    evidence: Evidence = Evidence.CODE_ONLY
    evidence_reason: str | None = None   # required when evidence is NOT-ASSESSED
    non_deterministic: bool = False  # a MANUAL/undecidable case the normalizer drops from the diff
    canonical_id: str | None = None  # override the check's shared id for this one issue (e.g. A3 vs A2)
    # optional per-issue scoring overrides (§4); None falls back to the check's declared inputs
    impact_class: str | None = None
    reachability: str | None = None
    data_sensitivity: str | None = None

    def finding_id(self, check_canonical_id: str) -> str:
        return f"{self.canonical_id or check_canonical_id}@{self.anchor or 'none'}"

    def scored_severity(self, check: "Check") -> str:
        return score_severity(self.impact_class or check.impact_class,
                              self.reachability or check.reachability,
                              self.data_sensitivity or check.data_sensitivity)


@dataclass
class Finding:
    check_id: str
    status: Status
    summary: str
    issues: list[Issue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    blocked: str | None = None      # a fix exists but is gated (e.g. needs a framework upgrade): short reason

    @property
    def fixable(self) -> bool:
        return any(i.fixable for i in self.issues)

    @classmethod
    def from_issues(cls, check_id: str, issues: list[Issue], pass_summary: str,
                    notes: list[str] | None = None) -> "Finding":
        if not issues:
            return cls(check_id, Status.PASS, pass_summary, [], notes or [])
        worst = max(issues, key=lambda i: i.status.rank)
        summary = worst.message if len(issues) == 1 else f"{len(issues)} issues; worst: {worst.message}"
        return cls(check_id, worst.status, summary, issues, notes or [])

    def to_dict(self) -> dict:
        # Backward-compatible shape (kept so nothing downstream breaks) PLUS the shared-schema
        # fields per issue: a stable finding_id, the symbol anchor, the evidence level and the
        # non-deterministic flag. file:line stays as a non-diffed `location`/`locator`.
        return {
            "check": self.check_id, "status": self.status.value, "summary": self.summary,
            "fixable": self.fixable,
            "issues": [{"status": i.status.value, "message": i.message, "location": i.location,
                        "locator": i.location, "fixable": i.fixable, "anchor": i.anchor,
                        "evidence": i.evidence.value, "evidence_reason": i.evidence_reason,
                        "non_deterministic": i.non_deterministic}
                       for i in self.issues],
            "notes": self.notes,
            "blocked": self.blocked,
        }

    def shared_findings(self, check: "Check") -> list[dict]:
        """Emit the determinism-standard findings rows (one per anchor; an empty verdict is
        `<CHECK-ID>@none`). Volatile data (paths, SHAs, time) is NOT here - it lives in run-meta."""
        cid = check.canonical_id or check.id
        severity = check.scored_severity()
        common = {
            "check_id": cid,                      # the SHARED registry id (e.g. I3, A10)
            "hardening_check": check.id,          # this skill's local fix-owner id (kebab)
            "severity": severity,                 # DERIVED (§4); flat value kept as an alias
            "severity_flat": check.severity,
            "impact_class": check.impact_class,
            "reachability": check.reachability,
            "data_sensitivity": check.data_sensitivity,
            "root_cause": check.root_cause,
            "plan_id": check.plan_id,
            "regression_test": check.regression_test,
            "canonical_refs": check.canonical_refs,
        }
        if not self.issues:
            level = (Evidence.NOT_ASSESSED if self.status in (Status.SKIP, Status.NOT_APPLICABLE)
                     else Evidence.CODE_ONLY)
            return [{**common, "finding_id": f"{cid}@none", "anchor": "none",
                     "evidence_level": level.value,
                     "evidence_reason": self.blocked or self.summary if level is Evidence.NOT_ASSESSED else None,
                     "non_deterministic": not check.deterministic,
                     "status": self.status.value, "locator": None, "message": self.summary}]
        rows = []
        for i in self.issues:
            rows.append({**common, "check_id": i.canonical_id or cid, "finding_id": i.finding_id(cid),
                         "severity": i.scored_severity(check),           # per-issue (A3 Critical vs A2 High)
                         "impact_class": i.impact_class or check.impact_class,
                         "reachability": i.reachability or check.reachability,
                         "data_sensitivity": i.data_sensitivity or check.data_sensitivity,
                         "anchor": i.anchor or "none", "evidence_level": i.evidence.value,
                         "evidence_reason": i.evidence_reason,
                         "non_deterministic": i.non_deterministic or not check.deterministic,
                         "status": i.status.value, "locator": i.location, "message": i.message})
        return rows


@dataclass
class Edit:
    path: Path              # absolute
    new_text: str | None    # None deletes the file
    description: str
    redactions: tuple[str, ...] = ()   # secret literals to mask in the shown diff (never the file)

    @property
    def deletes(self) -> bool:
        return self.new_text is None


class NotFixable(Exception):
    """Raised by Check.fix when the code shape is not one the check can safely rewrite."""


# --------------------------------------------------------------------------- checks

class Check:
    id: str = ""                 # kebab-case, stable; used on the command line
    title: str = ""
    severity: str = "medium"     # DERIVED display alias of scored_severity(); high | medium | low
    doc: str = ""                # e.g. "references/checks.md section 1"
    options: dict = {}           # defaults, overridable with --set <id>.<key>=<value>

    # ---- shared determinism contract (check-registry.md). The canonical_id is the SHARED
    # CHECK-ID this fix owns, so the same issue carries one id across the three skills.
    canonical_id: str = ""               # e.g. "I3"; defaults to `id` if blank
    canonical_refs: list[str] = []       # other registry ids this maps to (e.g. ["I2", "SEC-T"])
    impact_class: str = "maintainability"    # §4 input
    reachability: str = "any_authenticated"  # §4 input
    data_sensitivity: str = "none"           # §4 input
    root_cause: str = ""                 # RC-sec-* (§6), never free text
    deterministic: bool = True           # DET enters the byte-identity diff; ND is quarantined (§7)
    plan_id: str = ""                    # templated remediation id (§5), not free prose
    regression_test: str = ""            # the exact test that proves the fix (§5)

    # ---- decision procedure (one declared, reproducible rule per check)
    decision_input: str = ""             # what the check reads
    decision_predicate: str = ""         # the boolean rule applied to that input
    decision_verdict: str = ""           # what each outcome means
    anchor_strategy: str = ""            # how the anchor string is built (symbol/role, not line)

    def __init__(self, overrides: dict | None = None):
        self.opts = {**self.options, **(overrides or {})}

    @classmethod
    def scored_severity(cls) -> str:
        return score_severity(cls.impact_class, cls.reachability, cls.data_sensitivity)

    def applies(self, repo: "Repo") -> tuple[bool, str]:
        return True, ""

    def scan(self, repo: "Repo") -> Finding:
        raise NotImplementedError

    def fix(self, repo: "Repo", finding: Finding) -> list[Edit]:
        raise NotFixable("This check has no automatic fix; follow the manual steps in " + self.doc)

    # helpers for subclasses
    def finding(self, status: Status, summary: str, **kw) -> Finding:
        return Finding(self.id, status, summary, **kw)


_REGISTRY: dict[str, type[Check]] = {}


def register(cls: type[Check]) -> type[Check]:
    if not cls.id or cls.id in _REGISTRY:
        raise ValueError(f"Check id missing or duplicated: {cls.id!r}")
    _REGISTRY[cls.id] = cls
    return cls


def load_checks() -> dict[str, type[Check]]:
    """Import every module in the checks package; each registers itself with @register."""
    import checks  # noqa: PLC0415 - package lives next to this file
    for mod in pkgutil.iter_modules(checks.__path__):
        if not mod.name.startswith("_"):
            importlib.import_module(f"checks.{mod.name}")
    return dict(sorted(_REGISTRY.items()))


# --------------------------------------------------------------------------- repository

def parse_version(text: str | None) -> tuple[int, ...] | None:
    if not text:
        return None
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", text)
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


@dataclass
class _FileState:
    text: str
    bom: bool
    deleted: bool = False


class Repo:
    """Read-only view of a Shesha application repository, plus an in-memory overlay of edits."""

    def __init__(self, root: Path, live: "LiveBackend | None" = None):
        self.root = root.resolve()
        self.live = live
        self._files: dict[Path, _FileState] = {}
        self._cs: list[Path] | None = None

    # ---- files
    def rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def loc(self, path: Path, text: str, index: int) -> str:
        return f"{self.rel(path)}:{text.count(chr(10), 0, index) + 1}"

    def walk(self, suffixes: Iterable[str]) -> list[Path]:
        suffixes = tuple(s.lower() for s in suffixes)
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            out += [Path(dirpath) / f for f in filenames if f.lower().endswith(suffixes)]
        return sorted(out)

    def cs_files(self) -> list[Path]:
        if self._cs is None:
            self._cs = self.walk([".cs"])
        return [p for p in self._cs if not self.is_deleted(p)]

    def is_deleted(self, path: Path) -> bool:
        state = self._files.get(path.resolve())
        return state is not None and state.deleted

    def read(self, path: Path) -> str:
        path = path.resolve()
        if path not in self._files:
            raw = path.read_bytes()
            bom = raw.startswith(b"\xef\xbb\xbf")
            # newline="" semantics: keep \r\n so edits preserve the file's line endings
            self._files[path] = _FileState(raw.decode("utf-8-sig", errors="replace"), bom)
        return self._files[path].text

    def stage(self, edit: Edit) -> None:
        self.read(edit.path)
        state = self._files[edit.path.resolve()]
        if edit.deletes:
            state.deleted = True
        else:
            state.text = edit.new_text

    def write(self, edit: Edit) -> None:
        if edit.deletes:
            edit.path.unlink()
            try:                              # drop the folder too if the file was its last one
                edit.path.parent.rmdir()
            except OSError:
                pass
            return
        state = self._files[edit.path.resolve()]
        data = edit.new_text.encode("utf-8")
        edit.path.write_bytes((b"\xef\xbb\xbf" if state.bom else b"") + data)

    def grep(self, pattern: re.Pattern, files: Iterable[Path] | None = None):
        """Yield (path, text, match) for every match across files (default: all .cs)."""
        for path in files if files is not None else self.cs_files():
            text = self.read(path)
            for m in pattern.finditer(text):
                yield path, text, m

    # ---- Shesha specifics
    def shesha_version(self) -> str | None:
        """SheshaVersion from Directory.Build.props, else the Shesha.Framework/Application PackageReference."""
        for props in self.walk(["directory.build.props"]):
            m = re.search(r"<SheshaVersion>\s*([^<\s]+)\s*</SheshaVersion>", self.read(props))
            if m:
                return m.group(1)
        pkg = re.compile(r'<PackageReference\s+Include="Shesha\.(?:Framework|Application|Core)"\s+Version="([^"]+)"')
        for proj in self.walk([".csproj"]):
            m = pkg.search(self.read(proj))
            if m and not m.group(1).startswith("$("):
                return m.group(1)
        return None

    @staticmethod
    def nuget_root() -> Path:
        return Path(os.environ.get("NUGET_PACKAGES") or Path.home() / ".nuget" / "packages")

    def package_dll(self, package: str, dll: str, version: str | None = None) -> Path | None:
        version = version or self.shesha_version()
        if not version:
            return None
        base = self.nuget_root() / package.lower() / version.lower() / "lib"
        if not base.is_dir():
            return None
        hits = sorted(base.glob(f"*/{dll}"), reverse=True)   # prefer the newest TFM
        return hits[0] if hits else None

    def package_has_symbol(self, package: str, dll: str, symbol: str) -> bool | None:
        """True/False if the restored package's assembly does/doesn't contain `symbol`; None if not restored.

        Method and type names live UTF-8 encoded in the metadata #Strings heap, so a byte search
        is reliable for "does this API exist in this version" questions.
        """
        path = self.package_dll(package, dll)
        return None if path is None else symbol.encode() in path.read_bytes()

    def appsettings(self) -> list[Path]:
        return [p for p in self.walk([".json"]) if p.name.lower().startswith("appsettings")]

    def json_get(self, path: Path, dotted: str):
        """Read Section:Key from a (possibly commented) appsettings file; None if absent/unparseable."""
        text = re.sub(r"(?m)^\s*//.*$", "", self.read(path))
        try:
            node = json.loads(text)
        except json.JSONDecodeError:
            return None
        for part in dotted.split(":"):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node


# --------------------------------------------------------------------------- live backend

class LiveBackend:
    """Authenticated read access to a running Shesha backend. Checks must never write through it."""

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self._creds = (username, password)
        self._token: str | None = None

    def _request(self, method: str, path: str, body: dict | None = None, token: str | None = None):
        req = urllib.request.Request(self.base_url + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"null")

    def token(self) -> str:
        if self._token is None:
            user, pwd = self._creds
            data = self._request("POST", "/api/TokenAuth/Authenticate",
                                 {"userNameOrEmailAddress": user, "password": pwd})
            self._token = data["result"]["accessToken"]
        return self._token

    def get(self, path: str):
        data = self._request("GET", path, token=self.token())
        return data.get("result") if isinstance(data, dict) else data


# --------------------------------------------------------------------------- capability manifest

def capability_manifest(repo: "Repo") -> dict:
    """Detect each capability up front (determinism-standard §1). A check whose capability is
    absent emits a first-class NOT-ASSESSED(reason), never a silent pass. Each value is
    {"present": bool} or {"present": False, "reason": "..."} for the diff's manifest_delta."""
    manifest: dict[str, dict] = {}

    git_dir = (repo.root / ".git").exists()
    manifest["git"] = ({"present": True} if git_dir
                       else {"present": False, "reason": "NOT-ASSESSED(no .git: cannot read history / commit per check)"})

    nuget = repo.nuget_root()
    manifest["nuget_restore"] = ({"present": True} if nuget.is_dir()
                                 else {"present": False, "reason": f"NOT-ASSESSED(NuGet cache {nuget} absent: run `dotnet restore`)"})

    dll = repo.package_dll("Shesha.Application", "Shesha.Application.dll")
    manifest["shesha_assembly_symbols"] = ({"present": True} if dll is not None
                                           else {"present": False, "reason": "NOT-ASSESSED(Shesha assemblies not restored: capability gates fall back to the version table, an evidence downgrade)"})

    manifest["live_backend"] = ({"present": True, "base_url": repo.live.base_url} if repo.live
                                else {"present": False, "reason": "NOT-ASSESSED(no --base-url: live/effective-setting checks not reproduced)"})
    return manifest


# --------------------------------------------------------------------------- text helpers

def diff(repo: Repo, edit: Edit) -> str:
    old = repo.read(edit.path).splitlines(keepends=True)
    new = [] if edit.deletes else edit.new_text.splitlines(keepends=True)
    rel = repo.rel(edit.path)
    out = "".join(difflib.unified_diff(old, new, f"a/{rel}", "/dev/null" if edit.deletes else f"b/{rel}"))
    return redact_secrets(out, edit.redactions) if edit.redactions else out


def matching_brace(text: str, open_index: int) -> int | None:
    """Index of the brace closing text[open_index] ('{' or '('), skipping strings, chars and comments."""
    pairs = {"{": "}", "(": ")"}
    opener = text[open_index]
    closer = pairs[opener]
    depth, i, n = 0, open_index, len(text)
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            i = text.find("\n", i)
            if i < 0:
                return None
        elif text.startswith("/*", i):
            i = text.find("*/", i) + 1
            if i <= 0:
                return None
        elif c in "\"'":
            verbatim = i > 0 and text[i - 1] == "@"
            i += 1
            while i < n and text[i] != c:
                if text[i] == "\\" and not verbatim:
                    i += 1
                i += 1
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def line_indent(text: str, index: int) -> str:
    start = text.rfind("\n", 0, index) + 1
    return re.match(r"[ \t]*", text[start:]).group(0)


def newline_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def ensure_using(text: str, namespace: str) -> str:
    """Add `using namespace;` after the last top-level using directive, if not already present."""
    if re.search(rf"(?m)^\s*(global\s+)?using\s+{re.escape(namespace)}\s*;", text):
        return text
    nl = newline_of(text)
    usings = list(re.finditer(r"(?m)^using\s+[\w.]+\s*;[^\n]*\n", text))
    ns = re.search(r"(?m)^\s*namespace\b", text)
    usings = [u for u in usings if ns is None or u.start() < ns.start()]
    line = f"using {namespace};{nl}"
    if usings:
        at = usings[-1].end()
        return text[:at] + line + text[at:]
    return line + text

