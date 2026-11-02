"""Shared plumbing for hardening checks: repository access, check registry, results, edits.

A check never writes to disk itself. It returns Edit objects; the runner shows them as a
diff and writes them only when --apply is given. That keeps every check dry-run by default.
"""
from __future__ import annotations

import difflib
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


@dataclass
class Issue:
    status: Status
    message: str
    location: str | None = None      # "relative/path.cs:123"
    fixable: bool = False


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
        return {
            "check": self.check_id, "status": self.status.value, "summary": self.summary,
            "fixable": self.fixable,
            "issues": [{"status": i.status.value, "message": i.message, "location": i.location,
                        "fixable": i.fixable} for i in self.issues],
            "notes": self.notes,
            "blocked": self.blocked,
        }


@dataclass
class Edit:
    path: Path              # absolute
    new_text: str | None    # None deletes the file
    description: str

    @property
    def deletes(self) -> bool:
        return self.new_text is None


class NotFixable(Exception):
    """Raised by Check.fix when the code shape is not one the check can safely rewrite."""


# --------------------------------------------------------------------------- checks

class Check:
    id: str = ""                 # kebab-case, stable; used on the command line
    title: str = ""
    severity: str = "medium"     # high | medium | low
    doc: str = ""                # e.g. "references/checks.md section 1"
    options: dict = {}           # defaults, overridable with --set <id>.<key>=<value>

    def __init__(self, overrides: dict | None = None):
        self.opts = {**self.options, **(overrides or {})}

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


# --------------------------------------------------------------------------- text helpers

def diff(repo: Repo, edit: Edit) -> str:
    old = repo.read(edit.path).splitlines(keepends=True)
    new = [] if edit.deletes else edit.new_text.splitlines(keepends=True)
    rel = repo.rel(edit.path)
    return "".join(difflib.unified_diff(old, new, f"a/{rel}", "/dev/null" if edit.deletes else f"b/{rel}"))


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

