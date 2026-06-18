---
name: setup-claude-logger
description: Installs the Claude Logger configuration into Claude Code settings.json files — the CLAUDE_LOGGER_API_URL env var, the UserPromptSubmit/PreToolUse/PostToolUse/SessionStart/Stop ingest hooks, the shesha-developer plugin, and the shesha-plugins marketplace. Each hook runs the bundled cc_logger.py script, which enriches the event (turn cost, transcript details on Stop) and forwards it directly to the ingest backend — no local server required. Applies the configuration to both the global user settings and the current project settings as an additive merge — creating files where missing, updating these specific values in place where they already exist, and never removing or overwriting unrelated keys. Use when the user asks to set up, install, configure, add, enable, or update the Claude logger, logger hooks, telemetry hooks, or the ingest hooks for Claude Code.
---

# Setup Claude Logger

Install the Claude Logger env vars, ingest hooks, plugin, and marketplace into Claude Code `settings.json` files. The configuration is applied to **both**:

- **Global user settings**: `~/.claude/settings.json` (Windows: `%USERPROFILE%\.claude\settings.json`)
- **Project settings**: `<repo-root>/.claude/settings.json`

The merge is **additive but authoritative**: only the keys below are touched, and for those
keys the installer **always overrides any pre-existing value** with the canonical one —
the `CLAUDE_LOGGER_API_URL`, the five logger hooks, the enabled plugin (forced to `true`),
and the marketplace entry. Stale or wrong-typed values are coerced and overwritten (e.g. an
`env` that was a string, `enabledPlugins: false`, or a marketplace pointing somewhere else).
Logger hooks are replaced in place rather than duplicated on re-run. Any other keys already
in the file (e.g. `theme`, `autoUpdatesChannel`, unrelated permissions or hooks) are left
untouched.

## How it works

Each hook pipes its event payload (Claude Code sends it on stdin) into the bundled
`scripts/cc_logger.py` script. The script:

1. Enriches the event — tags it with a timestamp, organisation, and `cwd`/`user`; on the
   `Stop` event it reads the session transcript to attach the final response text, model,
   token usage, and an estimated USD cost for the turn.
2. Forwards the enriched record straight to the ingest backend named by
   `CLAUDE_LOGGER_API_URL` (appending the ingest path).

This is fully self-contained: there is **no local server** to keep running. The previous
design routed every hook through a Shesha MCP server at `http://localhost:8000/api/claude-logger/ingest`,
which did the enrichment and forwarding; that responsibility now lives in `cc_logger.py`.
Forwarding is best-effort — if the backend is unreachable or no URL is configured, the
event is silently dropped and the hook never blocks or errors.

## What gets installed

```json
{
  "env": { "CLAUDE_LOGGER_API_URL": "<api-url>" },
  "hooks": {
    "UserPromptSubmit": [ { "hooks": [ { "type": "command", "command": "python \"<skill-dir>/scripts/cc_logger.py\"" } ] } ],
    "PreToolUse":       [ { "matcher": "*", "hooks": [ { "type": "command", "command": "python \"<skill-dir>/scripts/cc_logger.py\"" } ] } ],
    "PostToolUse":      [ { "matcher": "*", "hooks": [ { "type": "command", "command": "python \"<skill-dir>/scripts/cc_logger.py\"" } ] } ],
    "SessionStart":     [ { "hooks": [ { "type": "command", "command": "python \"<skill-dir>/scripts/cc_logger.py\"" } ] } ],
    "Stop":             [ { "hooks": [ { "type": "command", "command": "python \"<skill-dir>/scripts/cc_logger.py\"" } ] } ]
  },
  "enabledPlugins": { "shesha-developer@shesha-plugins": true },
  "extraKnownMarketplaces": {
    "shesha-plugins": { "source": { "source": "github", "repo": "shesha-io/shesha-plugins" } }
  }
}
```

The installer bakes the **absolute path** to `cc_logger.py` (its own location) into each
hook command, so the hooks keep working regardless of the current working directory.

## Configuration the script reads

The script reads these from the Claude Code session environment (the `env` block above).
Only `CLAUDE_LOGGER_API_URL` is required; the rest are optional.

| Env var | Purpose | Default |
| --- | --- | --- |
| `CLAUDE_LOGGER_API_URL` | Ingest backend base URL. Empty → forwarding off. | — |
| `CLAUDE_LOGGER_INGEST_PATH` | Path appended to the base URL. | `/api/services/SaaTestManager/ClaudeLog/Ingest` |
| `CLAUDE_LOGGER_API_TOKEN` | Optional bearer token. | none |
| `CLAUDE_LOGGER_TIMEOUT` | Forward request timeout (seconds). | `5` |
| `CLAUDE_LOGGER_ORGANISATION` | Organisation tag on every record. | none |
| `CLAUDE_LOGGER_USER` | Fallback user when the payload carries none. | none |
| `CLAUDE_LOGGER_DEBUG_LOG` | Local file path; when set, each event's name and forward outcome (HTTP status / error) is appended for troubleshooting. | none |

## All five events are always forwarded

Every hook event — `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SessionStart`, and
`Stop` — is forwarded through the same path. Only `Stop` does extra enrichment (reading the
transcript for the final response, model, token usage, and cost). That enrichment is wrapped
so that a malformed or locked transcript can **never** stop the `Stop` event from being sent —
the base record still goes out. If `Stop` (or any event) is missing from the backend, set
`CLAUDE_LOGGER_DEBUG_LOG` and re-run: a `backend rejected (HTTP 4xx)` line means the event
was sent but the ingest endpoint refused the (richer) payload, whereas `forward failed` means
the backend was unreachable.

## Instructions

Run the bundled installer, passing both settings paths. It preserves all unrelated keys,
creates missing files (and parent directories), and is idempotent — re-running replaces the
existing logger hooks (including any legacy curl-to-localhost hooks from the old server-based
setup) rather than duplicating them, and overwrites the env vars / plugin / marketplace in place.

```bash
python "<skill-dir>/scripts/install_logger_hooks.py" \
  --api-url "https://saa-testmanager-api-test.shesha.app/" \
  "$HOME/.claude/settings.json" \
  "<repo-root>/.claude/settings.json"
```

On Windows PowerShell, use the user profile path and the absolute project path:

```powershell
python "<skill-dir>\scripts\install_logger_hooks.py" `
  --api-url "https://saa-testmanager-api-test.shesha.app/" `
  "$env:USERPROFILE\.claude\settings.json" `
  "<repo-root>\.claude\settings.json"
```

Optional flags (written into the `env` block only when supplied):
`--ingest-path`, `--api-token`, `--organisation`, `--user`, `--timeout`, `--debug-log`.

Notes:
- The `--api-url` flag sets the `CLAUDE_LOGGER_API_URL` value. If the user supplies a
  different URL, pass it here; otherwise the default above is used.
- The installer reports each file it updates. After running, confirm both files contain the
  five hook events (each running `cc_logger.py`), the env var, the enabled plugin, and the
  marketplace entry.
- `settings.local.json` is never touched — only the requested `settings.json` files.
- `python` must be on PATH for the hooks to run. The script uses only the standard library.
