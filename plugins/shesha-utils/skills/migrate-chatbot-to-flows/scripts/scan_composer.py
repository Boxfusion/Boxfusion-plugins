#!/usr/bin/env python3
"""Inventory the Bot Framework Composer (adaptive dialog) leftovers in a Shesha project.

Read-only. Prints a markdown report and, with --json, writes the same data for later steps.

    python scan_composer.py --repo <repo-root> [--json inventory.json]

What it finds:
  * Composer dialog files (*.dialog / *.botproj / *.lu / *.qna / *.lg), and for each main dialog the
    $kind values, custom (non Microsoft.*) kinds, dialogs it begins, triggers, memory paths and URLs
  * C# custom dialog actions, DeclarativeType registrations, AddBotRuntime* calls, BotConfiguration use
  * the admin portal's Bot Composer component, and the chat package/version the project consumes
  * .shaconfig packages that carry bot-configuration items (the Composer projects stored in the DB)
"""
import argparse
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

SKIP_DIRS = {"node_modules", "bin", "obj", ".git", ".next", "dist", ".vs", "TestResults"}
# Recogniser / generated companions of a dialog, not dialogs in their own right.
COMPANION = re.compile(r"\.(lu|qna|en-us\.lu|lu\.qna|[a-z]{2}(-[a-z]{2})?\.lu)\.dialog$|/recognizers/|/generated/", re.I)
MEMORY = re.compile(r"\b((?:user|dialog|conversation|turn|this)\.[A-Za-z_][\w.]*)")
URL = re.compile(r"https?://[^\s\"'`)]+")


def walk(root: Path):
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file():
            yield path


def read(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeError, OSError):
            continue
    return ""


def scan_dialog(path: Path) -> dict:
    text = read(path)
    info = {"file": str(path), "kinds": {}, "customKinds": [], "begins": [], "triggers": [], "memory": [], "urls": [],
            "recognisers": [], "unreadable": False}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        info["unreadable"] = True
        return info
    kinds, begins, triggers = Counter(), set(), set()

    def visit(node):
        if isinstance(node, dict):
            kind = node.get("$kind")
            if isinstance(kind, str):
                kinds[kind] += 1
                if kind == "Microsoft.BeginDialog" and isinstance(node.get("dialog"), str):
                    begins.add(node["dialog"])
                if kind.startswith("Microsoft.On"):
                    triggers.add(kind.removeprefix("Microsoft."))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(data)
    info["kinds"] = dict(kinds.most_common())
    info["customKinds"] = sorted(k for k in kinds if not k.startswith("Microsoft."))
    info["begins"] = sorted(begins)
    info["triggers"] = sorted(triggers)
    info["memory"] = sorted(set(MEMORY.findall(text)))
    info["urls"] = sorted(set(URL.findall(text)))[:20]
    info["recognisers"] = sorted(k.removeprefix("Microsoft.") for k in kinds if "Recognizer" in k)
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, help="repository root")
    parser.add_argument("--json", help="write the inventory to this file")
    args = parser.parse_args()
    root = Path(args.repo).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    dialogs, other_assets = [], Counter()
    actions, registrations, runtime_calls, config_users = [], [], [], []
    composer_components, props, packages_with_bot_config, package_json = [], [], [], []
    projects_dirs = set()

    for path in walk(root):
        rel = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()
        if suffix == ".dialog" and not COMPANION.search(rel):
            dialogs.append(scan_dialog(path))
        elif suffix in (".botproj", ".lu", ".qna", ".lg"):
            other_assets[suffix] += 1
            if suffix == ".botproj":
                projects_dirs.add(str(path.parent.relative_to(root).as_posix()))
        elif suffix == ".cs":
            text = read(path)
            if re.search(r":\s*(Dialog|DialogAction|DialogBase)\b", text) and re.search(r"\$kind|DeclarativeType|Kind\s*=", text):
                kind = re.search(r'Kind\s*=\s*"([^"]+)"', text)
                actions.append({"file": rel, "class": (re.search(r"class\s+(\w+)", text) or [None, "?"])[1], "kind": kind.group(1) if kind else None})
            if "DeclarativeType" in text and "RegisterType" in text or re.search(r"DeclarativeType<", text):
                registrations.append(rel)
            if re.search(r"AddBotRuntime(Configuration)?\s*\(", text):
                runtime_calls.append(rel)
            if re.search(r"\bBotConfiguration\b|\bBotComposerSetting\b|BotComposerAppService", text):
                config_users.append(rel)
        elif suffix in (".tsx", ".ts") and re.search(r"botcomposer|BotComposer", text := read(path)):
            composer_components.append(rel)
        elif path.name == "Directory.Build.props":
            for line in read(path).splitlines():
                if re.search(r"Chat|Shesha(Version)?>|UseLocal", line):
                    props.append(f"{rel}: {line.strip()}")
        elif path.name == "package.json" and "adminportal" in rel or path.name == "package.json" and rel.count("/") == 0:
            for line in read(path).splitlines():
                if "chat-service" in line or "shesha-io/reactjs" in line:
                    package_json.append(f"{rel}: {line.strip()}")
        elif suffix == ".shaconfig":
            try:
                with zipfile.ZipFile(path) as z:
                    if any("bot-configuration" in name.lower() or "botconfiguration" in name.lower() for name in z.namelist()) or \
                            any(b"bot-configuration" in z.read(n) for n in z.namelist() if n.endswith(".json") and z.getinfo(n).file_size < 5_000_000):
                        packages_with_bot_config.append(rel)
            except (zipfile.BadZipFile, OSError):
                pass

    memory_all = sorted({m for d in dialogs for m in d["memory"]})
    kinds_all = Counter()
    for d in dialogs:
        kinds_all.update(d["kinds"])
    custom = sorted({k for d in dialogs for k in d["customKinds"]})
    result = {
        "repo": str(root),
        "composerProjects": sorted(projects_dirs),
        "dialogFiles": len(dialogs),
        "otherComposerAssets": dict(other_assets),
        "dialogs": dialogs,
        "customKindsUsed": custom,
        "customActionClasses": actions,
        "declarativeTypeRegistrations": registrations,
        "botRuntimeCalls": runtime_calls,
        "botConfigurationUsers": config_users,
        "adminPortalComposerComponent": composer_components,
        "chatReferences": props + package_json,
        "packagesWithBotConfigurationItems": packages_with_bot_config,
        "memoryPaths": memory_all,
        "kindsTotal": dict(kinds_all.most_common()),
    }
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2), encoding="utf-8")

    out = [f"# Composer inventory: {root.name}", ""]
    out.append(f"- Composer projects (.botproj): {len(projects_dirs)} {sorted(projects_dirs)[:5]}")
    out.append(f"- Dialog files: {len(dialogs)}; other assets: {dict(other_assets) or 'none'}")
    out.append(f"- Custom dialog action classes: {len(actions)}; DeclarativeType registrations in: {len(registrations)} file(s)")
    out.append(f"- AddBotRuntime* calls: {runtime_calls or 'none'}")
    out.append(f"- Code touching BotConfiguration/BotComposerSetting: {len(config_users)} file(s)")
    out.append(f"- Admin-portal Bot Composer component used in: {composer_components or 'none'}")
    shipped = [p for p in packages_with_bot_config if "/App_Data/" not in p]
    runtime = len(packages_with_bot_config) - len(shipped)
    out.append(f"- .shaconfig packages carrying bot-configuration items: {shipped[:8] or 'none'}"
               + (f" (+{len(shipped) - 8} more)" if len(shipped) > 8 else "")
               + (f"; {runtime} more under App_Data (runtime uploads, not shipped)" if runtime else ""))
    out.append("")
    out.append("## Chat references")
    out.extend(f"- {line}" for line in (props + package_json) or ["none found"])
    out.append("")
    out.append("## Custom actions to port (or replace with an action the chat module already ships)")
    out.extend(f"- {a['class']}" + (f" (kind `{a['kind']}`)" if a["kind"] else "") + f" - {a['file']}" for a in actions) if actions else out.append("- none")
    out.append("")
    out.append("## $kind usage across dialogs")
    out.extend(f"- {k}: {n}" for k, n in kinds_all.most_common()) if kinds_all else out.append("- none")
    out.append("")
    out.append(f"## Dialogs ({len(dialogs)})")
    for d in sorted(dialogs, key=lambda d: d["file"]):
        flag = " UNREADABLE" if d["unreadable"] else ""
        out.append(f"- {Path(d['file']).name}{flag}: begins {d['begins'] or '-'}; triggers {d['triggers'] or '-'}; "
                   f"custom {d['customKinds'] or '-'}; recognisers {d['recognisers'] or '-'}")
    out.append("")
    out.append(f"## Memory paths read or written ({len(memory_all)})")
    out.append(", ".join(memory_all) if memory_all else "none")
    print("\n".join(out))
    clean = not (dialogs or actions or registrations or runtime_calls or config_users or composer_components or packages_with_bot_config or projects_dirs)
    print("\nNo Composer leftovers found." if clean else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
