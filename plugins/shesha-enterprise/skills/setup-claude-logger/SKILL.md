---
name: setup-claude-logger
description: Installs the Claude Logger configuration into Claude Code settings.json files — the CLAUDE_LOGGER_API_URL env var, the powershell permission, the UserPromptSubmit/PreToolUse/PostToolUse/SessionStart/Stop ingest hooks, the shesha-developer plugin, and the shesha-plugins marketplace. Applies the configuration to both the global user settings and the current project settings as an additive merge — creating files where missing, updating these specific values in place where they already exist, and never removing or overwriting unrelated keys. Use when the user asks to set up, install, configure, add, enable, or update the Claude logger, logger hooks, telemetry hooks, or the ingest hooks for Claude Code.
---

# Setup Claude Logger

Install the Claude Logger env var, permission, ingest hooks, plugin, and marketplace into Claude Code `settings.json` files. The configuration is applied to **both**:

- **Global user settings**: `~/.claude/settings.json` (Windows: `%USERPROFILE%\.claude\settings.json`)
- **Project settings**: `<repo-root>/.claude/settings.json`

The merge is **additive**: only the keys below are added or updated. Any other keys already
in the file (e.g. `theme`, `autoUpdatesChannel`, unrelated permissions or hooks) are left
untouched. `permissions.allow` is union-merged, and logger hooks are replaced in place rather
than duplicated on re-run.

## What gets installed

```json
{
  "env": { "CLAUDE_LOGGER_API_URL": "<api-url>" },
  "permissions": { "allow": [ "Bash(powershell -Command:*)" ] },
  "hooks": {
    "UserPromptSubmit": [ { "hooks": [ { "type": "command", "command": "curl ... ingest ..." } ] } ],
    "PreToolUse":       [ { "matcher": "*", "hooks": [ { "type": "command", "command": "curl ... ingest ..." } ] } ],
    "PostToolUse":      [ { "matcher": "*", "hooks": [ { "type": "command", "command": "curl ... ingest ..." } ] } ],
    "SessionStart":     [ { "hooks": [ { "type": "command", "command": "curl ... ingest ..." } ] } ],
    "Stop":             [ { "hooks": [ { "type": "command", "command": "curl ... ingest ..." } ] } ]
  },
  "enabledPlugins": { "shesha-developer@shesha-plugins": true },
  "extraKnownMarketplaces": {
    "shesha-plugins": { "source": { "source": "github", "repo": "shesha-io/shesha-plugins" } }
  }
}
```

Each hook command posts the event payload to the local ingest endpoint:

```
curl -s --max-time 5 -X POST http://localhost:8000/api/claude-logger/ingest -H "Content-Type: application/json" -H "X-Claude-Logger-Url: $CLAUDE_LOGGER_API_URL" --data-binary @-
```

## Instructions

Run the bundled script, passing both settings paths. The script preserves all unrelated
keys, creates missing files (and parent directories), and is idempotent — re-running
replaces the existing logger hooks rather than duplicating them, and overwrites the env
var / plugin / marketplace values in place.

```bash
python "<skill-dir>/scripts/install_logger_hooks.py" \
  --api-url "https://saa-testmanager-api-dev.shesha.app/" \
  "$HOME/.claude/settings.json" \
  "<repo-root>/.claude/settings.json"
```

On Windows PowerShell, use the user profile path and the absolute project path:

```powershell
python "<skill-dir>/scripts/install_logger_hooks.py" `
  --api-url "https://saa-testmanager-api-dev.shesha.app/" `
  "$env:USERPROFILE\.claude\settings.json" `
  "<repo-root>\.claude\settings.json"
```

Notes:
- The `--api-url` flag sets the `CLAUDE_LOGGER_API_URL` value. If the user supplies a
  different URL, pass it here; otherwise the default above is used.
- The script reports each file it updates. After running, confirm both files contain the
  five hook events, the env var, the enabled plugin, and the marketplace entry.
- `settings.local.json` is never touched — only the requested `settings.json` files.
