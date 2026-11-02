"""Git plumbing for `harden.py fix --apply --commit`: one commit per check, containing only that check's change.

The user's own uncommitted work must never end up in a hardening commit. So:
- the run refuses to start if anything is already staged (the commit would include it);
- a file the check touched that was clean before is staged whole (`git add -A`);
- a file that already had uncommitted edits gets only the check's change, 3-way merged onto the
  index version; the user's edits stay unstaged in the working tree. If the hunks can't be
  isolated, the change is left in the working tree, uncommitted, and the report says so.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from core import Edit

BOM = bytes([0xEF, 0xBB, 0xBF])


class GitError(Exception):
    pass


class Git:
    def __init__(self, repo_root: Path):
        self.cwd = repo_root
        try:
            self.top = Path(self._run("rev-parse", "--show-toplevel").strip()).resolve()
        except GitError as exc:
            raise GitError(f"{repo_root} is not inside a git repository") from exc

    def _run(self, *args: str, input_text: str | None = None, check: bool = True) -> str:
        proc = subprocess.run(["git", *args], cwd=self.cwd, input=input_text, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        if check and proc.returncode != 0:
            raise GitError((proc.stderr or proc.stdout).strip().splitlines()[-1] if (proc.stderr or proc.stdout)
                           else f"git {' '.join(args)} failed")
        return proc.stdout

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.top).as_posix()

    # ---- preflight
    def branch(self) -> str:
        return self._run("rev-parse", "--abbrev-ref", "HEAD").strip()

    def default_branch(self) -> str | None:
        out = self._run("symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False).strip()
        if out:
            return out.split("/", 1)[-1]
        for name in ("main", "master"):
            if self._run("rev-parse", "--verify", "--quiet", f"refs/heads/{name}", check=False).strip():
                return name
        return None

    def has_staged_changes(self) -> bool:
        return subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=self.cwd).returncode != 0

    def preflight(self, allow_default_branch: bool) -> None:
        if self.has_staged_changes():
            raise GitError("changes are already staged; commit or unstage them first "
                           "(each hardening commit must contain only that check's change)")
        branch, default = self.branch(), self.default_branch()
        if branch == "HEAD":
            raise GitError("HEAD is detached; check out a branch first")
        if not allow_default_branch and branch == default:
            raise GitError(f"on the default branch '{branch}'; create a branch first "
                           "(or pass --allow-default-branch)")

    # ---- per-file state
    def status(self, path: Path) -> str:
        """'' clean, '??' untracked, otherwise the porcelain XY code."""
        out = self._run("status", "--porcelain", "--", self.rel(path))
        return out[:2].strip() if out else ""

    # ---- commit one check
    def commit_check(self, edits: list[Edit], originals: dict[Path, str], dirty: dict[Path, str],
                     message: str) -> tuple[str | None, list[str]]:
        """Stage exactly the check's edits and commit them. Returns (sha or None, problems).

        `originals` is each file's text before the check ran; `dirty` maps paths that already had
        uncommitted changes (or were untracked) to their status code.
        """
        problems: list[str] = []
        staged: list[str] = []
        for edit in edits:
            rel = self.rel(edit.path)
            state = dirty.get(edit.path.resolve())
            if state is None:                                  # clean before: stage the whole file
                self._run("add", "-A", "--", rel)
                staged.append(rel)
            elif state == "??":
                problems.append(f"{rel} is untracked, so its change cannot be committed on its own")
            elif edit.deletes:
                problems.append(f"{rel} had uncommitted changes; not deleting it in a commit")
            elif self._apply_hunks(rel, originals[edit.path.resolve()], edit.new_text):
                staged.append(rel)
            else:
                problems.append(f"{rel} had uncommitted changes that overlap this fix")
        if problems:
            if staged:
                self._run("reset", "-q", "--", *staged)        # all or nothing per check
            return None, problems
        if not staged:
            return None, ["nothing to commit"]
        try:
            self._run("commit", "-q", "-F", "-", input_text=message)
        except GitError as exc:                                # e.g. a hook rejected it
            self._run("reset", "-q", "--", *staged)
            return None, [f"git commit failed: {exc}"]
        return self._run("rev-parse", "--short", "HEAD").strip(), []

    def _apply_hunks(self, rel: str, before: str, after: str) -> bool:
        """Put (index version + the check's change) into the index, leaving the user's edits unstaged.

        A 3-way merge (base = working text before the check, other = after, current = index) on
        LF-normalised text, so CRLF working copies and LF blobs (core.autocrlf) still line up.
        The result keeps the index blob's own line endings and BOM.
        """
        raw = subprocess.run(["git", "show", f":{rel}"], cwd=self.top, capture_output=True).stdout
        bom = raw.startswith(BOM)
        index_text = raw.decode("utf-8-sig", errors="replace")
        crlf = "\r\n" in index_text
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for name, text in (("current", index_text), ("base", before), ("other", after)):
                f = Path(tmp) / name
                f.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
                files.append(str(f))
            merged = subprocess.run(["git", "merge-file", "-p", "--quiet", *files], cwd=self.top,
                                    capture_output=True)
        if merged.returncode != 0:                             # conflicts (>0) or error (<0)
            return False
        text = merged.stdout.decode("utf-8")
        data = (BOM if bom else b"") + (text.replace("\n", "\r\n") if crlf else text).encode("utf-8")
        sha = subprocess.run(["git", "hash-object", "-w", "--stdin", "--path", rel], cwd=self.top,
                             input=data, capture_output=True).stdout.decode().strip()
        mode = self._run("ls-files", "-s", "--", rel).split(" ", 1)[0]
        if not sha or not mode:
            return False
        self._run("update-index", "--cacheinfo", f"{mode},{sha},{rel}")
        return True
