#!/usr/bin/env python3
"""Idempotently install the Claude Logger env vars, plugin, and marketplace into
one or more Claude Code settings.json files.

Usage:
    python install_logger_hooks.py --api-url <URL> SETTINGS_PATH [SETTINGS_PATH ...]

Each SETTINGS_PATH is created (with parent dirs) if missing. Existing settings are
preserved; only the logger-related keys are added or updated.

The ingest HOOKS themselves are NOT written here. They ship with the plugin in
``<plugin-root>/hooks/hooks.json`` and reference the bundled ``cc_logger.py`` via
``${CLAUDE_PLUGIN_ROOT}`` — so the hook command resolves from the plugin install
directory rather than a machine-specific absolute path. This installer only:
  * sets the logger env vars (CLAUDE_LOGGER_API_URL etc.),
  * enables the plugin and registers its marketplace, and
  * removes any logger hooks left in settings.json by older versions (the
    absolute-path standalone form and the legacy curl-to-localhost form) so the
    plugin-provided hooks are not duplicated.
"""
import argparse
import json
import os
import sys

# Markers used to recognise (and remove) logger hooks left in settings.json by
# older versions of this installer.
LEGACY_INGEST_URL = "/api/claude-logger/ingest"
LOGGER_SCRIPT_MARKER = "cc_logger.py"

ENABLED_PLUGIN = "shesha-utils@boxfusion-plugins"
MARKETPLACE_NAME = "boxfusion-plugins"
MARKETPLACE_VALUE = {"source": {"source": "github", "repo": "Boxfusion/Boxfusion-plugins"}}


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


def remove_settings_logger_hooks(settings):
    """Strip any logger hooks previously written into settings.json (the
    absolute-path standalone form and the legacy curl-to-localhost form). The
    canonical hooks now ship with the plugin's hooks/hooks.json, so leaving these
    behind would double-log. Empty hook events/containers are pruned."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return
    for event in list(hooks.keys()):
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        groups[:] = [g for g in groups if not is_logger_hook(g)]
        if not groups:
            del hooks[event]
    if not hooks:
        del settings["hooks"]


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
    remove_settings_logger_hooks(settings)
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
