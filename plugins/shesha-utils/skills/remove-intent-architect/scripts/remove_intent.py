#!/usr/bin/env python3
"""Remove Intent Architect artifacts from a .NET / Shesha project.

Usage: python remove_intent.py [REPO_ROOT]   (defaults to current directory)

Removes:
  - the root-level intent/ folder
  - *.isln solution files
  - Intent.* PackageReference lines in .csproj files
  - using Intent.RoslynWeaver.Attributes; statements
  - [assembly: IntentTemplate(...)] and [assembly: DefaultIntentManaged(...)] statements
  - standalone [IntentManaged(...)] attribute lines

Prints every change and any remaining "Intent" matches for manual review.
"""
import os
import re
import shutil
import sys

SKIP_DIRS = {".git", "bin", "obj", "node_modules", ".vs"}

# Line-level removal rules for .cs files. Each matches a whole (stripped) line.
CS_LINE_PATTERNS = [
    re.compile(r'^\s*using\s+Intent\.[\w.]+\s*;\s*$'),
    re.compile(r'^\s*\[assembly:\s*IntentTemplate\(.*\)\s*\]\s*$'),
    re.compile(r'^\s*\[assembly:\s*DefaultIntentManaged\(.*\)\s*\]\s*$'),
    re.compile(r'^\s*\[IntentManaged\(.*\)\s*\]\s*$'),
]

CSPROJ_PATTERN = re.compile(r'^\s*<PackageReference\s+Include="Intent\.[^"]*".*/>\s*$')


def walk_files(root, ext):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(ext):
                yield os.path.join(dirpath, name)


def strip_lines(path, patterns):
    with open(path, "r", encoding="utf-8-sig") as f:
        lines = f.readlines()
    kept, removed = [], []
    for line in lines:
        if any(p.match(line) for p in patterns):
            removed.append(line.rstrip("\n"))
        else:
            kept.append(line)
    if removed:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(kept)
    return removed


def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    changes = []

    # 1. root-level intent/ folder
    intent_dir = os.path.join(root, "intent")
    if os.path.isdir(intent_dir):
        shutil.rmtree(intent_dir)
        changes.append(f"Deleted folder: {intent_dir}")

    # 2. *.isln files
    for path in walk_files(root, ".isln"):
        os.remove(path)
        changes.append(f"Deleted file: {path}")

    # 3. .csproj package references
    for path in walk_files(root, ".csproj"):
        for line in strip_lines(path, [CSPROJ_PATTERN]):
            changes.append(f"{path}: removed {line.strip()}")

    # 4-7. .cs statements and attributes
    for path in walk_files(root, ".cs"):
        for line in strip_lines(path, CS_LINE_PATTERNS):
            changes.append(f"{path}: removed {line.strip()}")

    print("=== Changes ===")
    if changes:
        for c in changes:
            print("  " + c)
    else:
        print("  (nothing removed)")

    # Report remaining references for manual review.
    remaining = []
    for ext in (".cs", ".csproj"):
        for path in walk_files(root, ext):
            with open(path, "r", encoding="utf-8-sig") as f:
                for i, line in enumerate(f, 1):
                    if "Intent" in line:
                        remaining.append(f"{path}:{i}: {line.strip()}")

    print("\n=== Remaining 'Intent' matches (review manually) ===")
    if remaining:
        for r in remaining:
            print("  " + r)
        print(f"\n{len(remaining)} match(es) need manual review.")
    else:
        print("  none — all Intent references removed.")


if __name__ == "__main__":
    main()
