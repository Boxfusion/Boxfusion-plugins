#!/usr/bin/env python3
"""Idempotently install the Claude Logger env vars, hooks, plugin, and marketplace
into one or more Claude Code settings.json files.

Usage:
    python install_logger_hooks.py --api-url <URL> SETTINGS_PATH [SETTINGS_PATH ...]

Each SETTINGS_PATH is created (with parent dirs) if missing. Existing settings are
preserved; only the logger-related keys are added or updated. Re-running is safe:
existing logger hooks (both the new standalone form and the legacy curl-to-localhost
form) are detected and replaced rather than duplicated.

The installed hooks run the bundled ``cc_logger.py`` script directly: each hook pipes
its event payload into the script, which enriches the event and forwards it straight
to the ingest backend named by CLAUDE_LOGGER_API_URL. No local server is required.
"""
import argparse
import json
import os
import sys

# Absolute path to the standalone logger script that sits next to this installer.
LOGGER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cc_logger.py")

# Markers used to recognise (and replace) previously-installed logger hooks.
LEGACY_INGEST_URL = "/api/claude-logger/ingest"
LOGGER_SCRIPT_MARKER = "cc_logger.py"


def hook_command():
    """The command each logger hook runs. The event payload arrives on stdin
    (Claude Code pipes it in); the script reads it and forwards directly."""
    return f'python "{LOGGER_SCRIPT}"'


# Hook events and whether they carry a "*" matcher.
HOOK_EVENTS = {
    "UserPromptSubmit": False,
    "PreToolUse": True,
    "PostToolUse": True,
    "SessionStart": False,
    "Stop": False,
}

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
    """A hook group counts as a logger hook if any of its commands runs the
    standalone logger script OR hits the legacy localhost ingest endpoint."""
    if not isinstance(hook_entry, dict):
        return False
    for h in hook_entry.get("hooks", []):
        cmd = h.get("command", "") if isinstance(h, dict) else ""
        if LOGGER_SCRIPT_MARKER in cmd or LEGACY_INGEST_URL in cmd:
            return True
    return False


def force_dict(settings, key):
    """Return settings[key] as a dict, coercing any pre-existing non-dict value
    (or absent key) to a fresh dict. Guarantees the POI keys below are always
    writable so their values are overridden rather than silently skipped."""
    value = settings.get(key)
    if not isinstance(value, dict):
        value = {}
        settings[key] = value
    return value


def install_hooks(settings):
    command = hook_command()
    hooks = force_dict(settings, "hooks")
    for event, has_matcher in HOOK_EVENTS.items():
        groups = hooks.get(event)
        if not isinstance(groups, list):
            groups = []
            hooks[event] = groups
        # Drop any pre-existing logger groups (new or legacy) so we re-add the
        # canonical one (update-in-place, no duplicates on re-run).
        groups[:] = [g for g in groups if not is_logger_hook(g)]
        entry = {"hooks": [{"type": "command", "command": command}]}
        if has_matcher:
            entry = {"matcher": "*", **entry}
        groups.append(entry)


def install_env(settings, args):
    """Write the logger env vars. API_URL is always overridden; the optional
    ones are overridden when provided. Unrelated env keys are never disturbed."""
    env = force_dict(settings, "env")
    env["CLAUDE_LOGGER_API_URL"] = args.api_url
    optional = {
        "CLAUDE_LOGGER_INGEST_PATH": args.ingest_path,
        "CLAUDE_LOGGER_API_TOKEN": args.api_token,
        "CLAUDE_LOGGER_ORGANISATION": args.organisation,
        "CLAUDE_LOGGER_USER": args.user,
        "CLAUDE_LOGGER_TIMEOUT": args.timeout,
        "CLAUDE_LOGGER_DEBUG_LOG": args.debug_log,
    }
    for key, value in optional.items():
        if value:
            env[key] = value


def install(settings, args):
    # Each step only adds or updates its own keys; all other keys in `settings`
    # are left untouched.
    install_env(settings, args)
    install_hooks(settings)
    force_dict(settings, "enabledPlugins")[ENABLED_PLUGIN] = True
    force_dict(settings, "extraKnownMarketplaces")[MARKETPLACE_NAME] = MARKETPLACE_VALUE
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        default="https://saa-testmanager-api-test.shesha.app/",
        help="Value for CLAUDE_LOGGER_API_URL (the ingest backend base URL).",
    )
    parser.add_argument(
        "--ingest-path",
        default="",
        help="Override CLAUDE_LOGGER_INGEST_PATH (path appended to the base URL). "
        "Leave empty to use the script default.",
    )
    parser.add_argument("--api-token", default="", help="Optional bearer token for the ingest backend.")
    parser.add_argument("--organisation", default="", help="Organisation name tagged onto every record.")
    parser.add_argument("--user", default="", help="Fallback user when the hook payload carries none.")
    parser.add_argument("--timeout", default="", help="Forward request timeout in seconds (default: 5).")
    parser.add_argument(
        "--debug-log",
        default="",
        help="Optional local file path; when set, cc_logger.py appends each event's "
        "name and forward outcome (HTTP status or error) for troubleshooting.",
    )
    parser.add_argument("paths", nargs="+", help="settings.json paths to update.")
    args = parser.parse_args()

    if not os.path.exists(LOGGER_SCRIPT):
        print(f"WARNING: logger script not found at {LOGGER_SCRIPT}; hooks will fail until it exists.", file=sys.stderr)

    for path in args.paths:
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        try:
            settings = load_settings(path)
        except json.JSONDecodeError as exc:
            print(f"ERROR: {path} is not valid JSON ({exc}); skipping.", file=sys.stderr)
            continue
        install(settings, args)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
            fh.write("\n")
        print(f"Updated {path}")


if __name__ == "__main__":
    main()
