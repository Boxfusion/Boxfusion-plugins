#!/usr/bin/env python3
"""Remove Intent Architect artifacts from a .NET / Shesha project.

Usage: python remove_intent.py [REPO_ROOT] [--dry-run]   (REPO_ROOT defaults to cwd)

Removes:
  - root-level intent/ and Intent.Modules/ folders, and any nested intent/ folder
    that holds an .isln (e.g. backend/intent/)
  - *.isln solution files
  - Intent.* <PackageReference>/<PackageVersion> entries (single- or multi-line)
    in .csproj / .props / .targets files
  - using Intent.*; statements
  - [assembly: IntentTemplate(...)] / [assembly: DefaultIntentManaged(...)] statements
  - standalone Intent attribute lines ([IntentManaged(...)], [IntentIgnore], [IntentMerge], ...),
    including commented-out ones
  - Azure DevOps YAML: Intent CLI steps (live or commented out), the intentSolutionPath
    variable and the 'Intent Architect Credentials' variable group

File encoding (BOM) and line endings (LF/CRLF) are preserved byte-for-byte.
Blank lines orphaned by a removal are collapsed so no double blank lines remain.

Reports, but does not edit:
  - remaining Intent references in code (inline attributes etc.)
  - packages.lock.json files with a direct Intent pin (regenerate with dotnet restore),
    separated from those where Intent is only a transitive dependency of upstream packages
  - Intent references in pipelines, scripts, docs and config (.yml/.yaml/.ps1/.md/...)
"""
import json
import os
import re
import shutil
import sys

BOM = b"\xef\xbb\xbf"
SKIP_DIRS ={".git", "bin", "obj", "node_modules", ".vs", ".idea"}
ROOT_DIRS = ["intent", "Intent.Modules"]

# Each may be commented out (// prefix); those lines are removed too.
CS_LINE_PATTERNS = [
    re.compile(rb'^\s*(//\s*)?using\s+Intent\.[\w.]+\s*;\s*$'),
    re.compile(rb'^\s*(//\s*)?\[\s*assembly:\s*IntentTemplate\(.*\)\s*\]\s*$'),
    re.compile(rb'^\s*(//\s*)?\[\s*assembly:\s*DefaultIntentManaged\(.*\)\s*\]\s*$'),
    # Every attribute in Intent.RoslynWeaver.Attributes, with or without arguments.
    re.compile(rb'^\s*(//\s*)?\[\s*(IntentManaged|IntentIgnore|IntentIgnoreBody|IntentMerge|IntentInitialGen'
               rb'|IntentCanAdd|IntentCanUpdate|IntentCanRemove)(\(.*\))?\s*\]\s*$'),
]

PKG_SINGLE = re.compile(rb'^\s*<(PackageReference|PackageVersion)\s+(Include|Update)="Intent\.[^"]*"[^>]*/>\s*$')
PKG_OPEN = re.compile(rb'^\s*<(PackageReference|PackageVersion)\s+(Include|Update)="Intent\.[^"]*"[^>]*>\s*$')
PKG_CLOSE = re.compile(rb'</(PackageReference|PackageVersion)>\s*$')

# Precise markers of Intent Architect (avoids false positives such as "IntentResult").
INTENT_MARKER = re.compile(
    rb'Intent\.(RoslynWeaver|VisualStudio|SoftwareFactory|Modules|Metadata)'
    rb'|IntentManaged|IntentTemplate|IntentIgnore|IntentMerge|IntentInitialGen|IntentCan(Add|Update|Remove)'
    rb'|intent-cli|intent-packager|IntentArchitect|INTENT_(USER|PASS|SOLUTION)'
    rb'|\.isln\b|intentSolutionPath|intent-architect'
)
CODE_EXTS = (".cs", ".csproj", ".props", ".targets")
YAML_EXTS = (".yml", ".yaml")
OTHER_EXTS = (".yml", ".yaml", ".ps1", ".sh", ".cmd", ".bat", ".md", ".json",
              ".config", ".sln", ".dockerfile", ".gitignore", ".editorconfig")


INTENT_DIRS = set()  # metadata folders being deleted; filled by find_intent_dirs()


def find_intent_dirs(root):
    """Root intent/ and Intent.Modules/, plus any intent/ folder holding an .isln (e.g. backend/intent/)."""
    found = {os.path.join(root, n) for n in ROOT_DIRS if os.path.isdir(os.path.join(root, n))}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                       and os.path.join(dirpath, d) not in found]
        if os.path.basename(dirpath).lower() == "intent" and any(f.endswith(".isln") for f in filenames):
            found.add(dirpath)
            dirnames[:] = []
    return sorted(found)


def walk_files(root, exts):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                       and os.path.join(dirpath, d) not in INTENT_DIRS]
        for name in filenames:
            if name.lower().endswith(exts) or name in exts:
                yield os.path.join(dirpath, name)


def is_blank(line):
    return line.strip() == b""


def remove_lines(path, should_remove, dry_run):
    """Remove lines selected by should_remove(lines) -> set(indices). Preserves bytes."""
    with open(path, "rb") as f:
        data = f.read()
    bom = BOM if data.startswith(BOM) else b""
    lines = data[len(bom):].splitlines(keepends=True)
    drop = should_remove(lines)
    if not drop:
        return []
    # A run of blank lines between two removed regions goes with them.
    for i, line in enumerate(lines):
        if is_blank(line) and i not in drop:
            above = next((k for k in range(i - 1, -1, -1) if not is_blank(lines[k])), None)
            below = next((k for k in range(i + 1, len(lines)) if not is_blank(lines[k])), None)
            if above in drop and below in drop:
                drop.add(i)

    kept = []
    removed_before = False  # True when lines were removed just before the next kept line
    for i, line in enumerate(lines):
        if i in drop:
            removed_before = True
            continue
        # Collapse a blank line orphaned by a removal: blank after blank, or blank at file start.
        if removed_before and is_blank(line) and (not kept or is_blank(kept[-1])):
            removed_before = False
            continue
        removed_before = False
        kept.append(line)

    if not dry_run:
        with open(path, "wb") as f:
            f.write(bom + b"".join(kept))
    return [lines[i].decode("utf-8", "replace").strip() for i in sorted(drop)]


def cs_targets(lines):
    return {i for i, l in enumerate(lines) if any(p.match(l) for p in CS_LINE_PATTERNS)}


def pkg_targets(lines):
    drop, i = set(), 0
    while i < len(lines):
        if PKG_SINGLE.match(lines[i]):
            drop.add(i)
        elif PKG_OPEN.match(lines[i]):
            j = i
            while j < len(lines) and not PKG_CLOSE.search(lines[j]):
                j += 1
            drop.update(range(i, min(j, len(lines) - 1) + 1))
            i = j
        i += 1
    return drop


# Azure DevOps YAML: Intent variables (live or commented) and step blocks.
YAML_VAR = re.compile(rb"^\s*(#\s*)?-\s*name:\s*['\"]?intentSolutionPath['\"]?\s*$")
YAML_VAR_VALUE = re.compile(rb"^\s*(#\s*)?value:\s*['\"]?intent['\"]?\s*$")
YAML_GROUP = re.compile(rb"^\s*(#\s*)?-\s*group:\s*['\"]?Intent Architect Credentials['\"]?\s*$")
YAML_ITEM = re.compile(rb"^(\s*)(#\s*)?(\s*)-\s+\w")  # list item, possibly commented out


def yaml_shape(line):
    """(commented, indent of the content after any '#'), or None for a blank line."""
    if is_blank(line):
        return None
    stripped = line.lstrip()
    if stripped.startswith(b"#"):
        body = stripped[1:]
        return True, len(body) - len(body.lstrip())
    return False, len(line) - len(stripped)


def yaml_targets(lines):
    """Intent variable lines, plus whole list items (steps) whose block mentions Intent.

    A block is a list item plus following lines of the same kind (live or commented)
    indented deeper than its dash; blank lines are kept in the block only when it continues after them.
    """
    drop, i = set(), 0
    while i < len(lines):
        line = lines[i]
        if YAML_GROUP.match(line):
            drop.add(i)
        elif YAML_VAR.match(line):
            drop.add(i)
            if i + 1 < len(lines) and YAML_VAR_VALUE.match(lines[i + 1]):
                drop.add(i + 1)
                i += 1
        elif YAML_ITEM.match(line):
            commented, indent = yaml_shape(line)
            end, j = i, i + 1
            while j < len(lines):
                shape = yaml_shape(lines[j])
                if shape is None:
                    j += 1
                    continue
                if shape[0] != commented or shape[1] <= indent:
                    break
                end = j
                j += 1
            block = range(i, end + 1)
            # Drop only innermost items: a stage/job holding nested items is descended into instead.
            nested = any(YAML_ITEM.match(lines[k]) and yaml_shape(lines[k])[0] == commented
                         for k in block[1:])
            if not nested and any(INTENT_MARKER.search(lines[k]) for k in block):
                drop.update(block)
                i = end
        i += 1
    return drop


REMOVABLE = CS_LINE_PATTERNS + [PKG_SINGLE, PKG_OPEN]


def scan(path, removable_lines=None):
    """Intent references the removal rules do not handle (so dry runs show only true leftovers)."""
    hits = []
    with open(path, "rb") as f:
        data = f.read()
    lines = data[len(BOM):].splitlines(keepends=True) if data.startswith(BOM) else data.splitlines(keepends=True)
    skip = removable_lines(lines) if removable_lines else set()
    for n, line in enumerate(lines, 1):
        if n - 1 not in skip:
            if INTENT_MARKER.search(line) and not any(p.match(line) for p in REMOVABLE):
                text = line.decode("utf-8", "replace").lstrip("﻿").strip()
                hits.append(f"{path}:{n}: {text[:160]}")
    return hits


def lock_status(path):
    """Classify Intent entries in a packages.lock.json: ('direct', []) or ('transitive', [parents])."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            frameworks = json.load(f).get("dependencies", {})
    except (OSError, ValueError):
        return None
    direct, parents = False, set()
    for packages in frameworks.values():
        for name, info in packages.items():
            if name.startswith("Intent.") and info.get("type") == "Direct":
                direct = True
            if any(dep.startswith("Intent.") for dep in (info.get("dependencies") or {})):
                parents.add(name)
    if direct:
        return ("direct", [])
    return ("transitive", sorted(parents)) if parents else None


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in sys.argv
    root = os.path.abspath(args[0] if args else ".")
    changes = []
    verb = "Would delete" if dry_run else "Deleted"

    INTENT_DIRS.update(find_intent_dirs(root))
    for d in sorted(INTENT_DIRS):
        if not dry_run:
            shutil.rmtree(d)
        changes.append(f"{verb} folder: {d}")

    for path in walk_files(root, (".isln",)):
        if not dry_run:
            os.remove(path)
        changes.append(f"{verb} file: {path}")

    for path in walk_files(root, (".csproj", ".props", ".targets")):
        for line in remove_lines(path, pkg_targets, dry_run):
            changes.append(f"{path}: removed {line}")

    cs_files = 0
    for path in walk_files(root, (".cs",)):
        removed = remove_lines(path, cs_targets, dry_run)
        if removed:
            cs_files += 1
            changes.append(f"{path}: removed {len(removed)} line(s)")

    for path in walk_files(root, YAML_EXTS):
        removed = remove_lines(path, yaml_targets, dry_run)
        if removed:
            changes.append(f"{path}: removed {len(removed)} pipeline line(s)")

    print(f"=== Changes{' (dry run)' if dry_run else ''} ===")
    print("\n".join("  " + c for c in changes) if changes else "  (nothing removed)")
    print(f"  -- {cs_files} .cs file(s) cleaned")

    code_left, stale_locks, transitive, other = [], [], [], []
    for path in walk_files(root, CODE_EXTS):
        code_left += scan(path)
    for path in walk_files(root, OTHER_EXTS):
        if os.path.basename(path) == "packages.lock.json":
            status = lock_status(path)
            if status and status[0] == "direct":
                stale_locks.append(path)
            elif status:
                transitive.append(f"{path}  (via {', '.join(status[1])})")
        else:
            other += scan(path, yaml_targets if path.lower().endswith(YAML_EXTS) else None)

    print("\n=== Remaining Intent references in code (fix by hand) ===")
    print("\n".join("  " + r for r in code_left) if code_left else "  none")

    print("\n=== packages.lock.json with a direct Intent pin (regenerate with dotnet restore) ===")
    print("\n".join("  " + p for p in stale_locks) if stale_locks else "  none")

    print("\n=== packages.lock.json with Intent only as a transitive dependency (expected, leave) ===")
    print("\n".join("  " + p for p in transitive) if transitive else "  none")

    print("\n=== Intent references in pipelines / scripts / docs / config (review) ===")
    print("\n".join("  " + r for r in other) if other else "  none")


if __name__ == "__main__":
    main()
