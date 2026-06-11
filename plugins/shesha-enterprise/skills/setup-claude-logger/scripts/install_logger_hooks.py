#!/usr/bin/env python3
"""Idempotently install the Claude Logger env var, hooks, plugin, and marketplace
into one or more Claude Code settings.json files.

Usage:
    python install_logger_hooks.py --api-url <URL> SETTINGS_PATH [SETTINGS_PATH ...]

Each SETTINGS_PATH is created (with parent dirs) if missing. Existing settings are
preserved; only the logger-related keys are added or updated. Re-running is safe:
existing logger hooks are detected by their ingest endpoint and replaced rather than
duplicated.
"""
import argparse
import json
import os
import sys

INGEST_URL = "http://localhost:8000/api/claude-logger/ingest"
HOOK_COMMAND = (
    'curl -s --max-time 5 -X POST ' + INGEST_URL + ' '
    '-H "Content-Type: application/json" '
    '-H "X-Claude-Logger-Url: $CLAUDE_LOGGER_API_URL" --data-binary @-'
)

# Hook events and whether they carry a "*" matcher.
HOOK_EVENTS = {
    "UserPromptSubmit": False,
    "PreToolUse": True,
    "PostToolUse": True,
    "SessionStart": False,
    "Stop": False,
}

PERMISSIONS_ALLOW = ["Bash(powershell -Command:*)"]

ENABLED_PLUGIN = "shesha-developer@shesha-plugins"
MARKETPLACE_NAME = "shesha-plugins"
MARKETPLACE_VALUE = {"source": {"source": "github", "repo": "shesha-io/shesha-plugins"}}


def load_settings(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read().strip()
    if not text:
        return {}
    return json.loads(text)


def is_logger_hook(hook_entry):
    """A hook group entry counts as a logger hook if any of its commands hit the ingest URL."""
    for h in hook_entry.get("hooks", []):
        if INGEST_URL in h.get("command", ""):
            return True
    return False


def install_hooks(settings):
    hooks = settings.setdefault("hooks", {})
    for event, has_matcher in HOOK_EVENTS.items():
        groups = hooks.setdefault(event, [])
        # Drop any pre-existing logger groups so we can re-add the canonical one (update-in-place).
        groups[:] = [g for g in groups if not is_logger_hook(g)]
        entry = {"hooks": [{"type": "command", "command": HOOK_COMMAND}]}
        if has_matcher:
            entry = {"matcher": "*", **entry}
        groups.append(entry)


def install_permissions(settings):
    """Union-merge the allow list — keep existing entries, append ours if missing."""
    allow = settings.setdefault("permissions", {}).setdefault("allow", [])
    for perm in PERMISSIONS_ALLOW:
        if perm not in allow:
            allow.append(perm)


def install(settings, api_url):
    # Each step only adds or updates its own keys; all other keys in `settings` are left untouched.
    settings.setdefault("env", {})["CLAUDE_LOGGER_API_URL"] = api_url
    install_permissions(settings)
    install_hooks(settings)
    settings.setdefault("enabledPlugins", {})[ENABLED_PLUGIN] = True
    settings.setdefault("extraKnownMarketplaces", {})[MARKETPLACE_NAME] = MARKETPLACE_VALUE
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        default="https://saa-testmanager-api-dev.shesha.app/",
        help="Value for CLAUDE_LOGGER_API_URL.",
    )
    parser.add_argument("paths", nargs="+", help="settings.json paths to update.")
    args = parser.parse_args()

    for path in args.paths:
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        try:
            settings = load_settings(path)
        except json.JSONDecodeError as exc:
            print(f"ERROR: {path} is not valid JSON ({exc}); skipping.", file=sys.stderr)
            continue
        install(settings, args.api_url)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
            fh.write("\n")
        print(f"Updated {path}")


if __name__ == "__main__":
    main()
