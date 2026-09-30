---
name: switch-model-provider
description: Switches Claude Code between Anthropic Claude models and Z.ai GLM models by editing the env block of the global (~/.claude/settings.json) and/or project (<repo>/.claude/settings.json) settings files. Switching to GLM adds the ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_MODEL / ANTHROPIC_DEFAULT_*_MODEL overrides plus CLAUDE_LOGGER_API_URL; switching back to Claude removes only those ANTHROPIC_* overrides. Asks whether to switch at the global level, the project level, or both, and bootstraps a missing project .claude/settings.json by copying the global settings first. Use when the user asks to switch, change, or toggle to GLM, Z.ai, or zhipu, switch back to Claude or Anthropic, check which provider is active, or use GLM models in Claude Code.
---
# Switch Model Provider (Claude ⇄ GLM)

Claude Code talks to Z.ai instead of Anthropic when these keys are in a settings `env` block:

```json
"env": {
  "CLAUDE_LOGGER_API_URL": "https://saa-testmanager-api-test.shesha.app",
  "ANTHROPIC_MODEL": "glm-5.3",
  "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
  "ANTHROPIC_AUTH_TOKEN": "<z.ai api key>",
  "ANTHROPIC_DEFAULT_HAIKU_MODEL": "glm-5.3-flash",
  "ANTHROPIC_DEFAULT_SONNET_MODEL": "glm-5.3",
  "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-5.3"
}
```

Switching back to Claude removes the six `ANTHROPIC_*` keys and keeps `CLAUDE_LOGGER_API_URL`
and every other key. All edits go through `scripts/switch_provider.py`, which preserves unrelated
keys, strips a UTF-8 BOM, and writes a `settings.json.bak` before changing a file.

## Workflow

1. **Show the current state**:

   ```bash
   python "<skill-dir>/scripts/switch_provider.py" --status --project-dir "<repo-root>"
   ```
2. **Confirm the direction** (to GLM or to Claude) if the request didn't say.
3. **Ask the scope** with AskUserQuestion. Always ask, even when the direction is clear:

   - **Both (Recommended)**: global and project. This is the only choice that guarantees the result, because `env` blocks merge across scopes (see *Scope rules*).
   - **Global only**: `~/.claude/settings.json`, applies to every repo.
   - **Project only**: `<repo-root>/.claude/settings.json`, applies to this repo only.
4. **For GLM, get the API key.** The script reuses an existing real `ANTHROPIC_AUTH_TOKEN` from the
   target files or the global file, or reads `$ZAI_API_KEY`. Only ask the user for a key when the
   script exits with `ERROR: no Z.ai API key`. Never echo the key back in chat.
5. **Run the switch**:

   ```bash
   python "<skill-dir>/scripts/switch_provider.py" --to glm    --scope both --project-dir "<repo-root>" [--api-key "<key>"]
   python "<skill-dir>/scripts/switch_provider.py" --to claude --scope both --project-dir "<repo-root>"
   ```

   Optional overrides for GLM: `--model` (default `glm-5.3`), `--fast-model` (default
   `glm-5.3-flash`, used for Haiku), `--base-url`, `--logger-url`. Use them only when the user
   asks for different models or endpoints.
6. **Report** each file changed, relay any `NOTE:` line, and tell the user to **restart Claude Code**
   (or start a new session) for the new env to take effect.

## Project bootstrap

If `<repo-root>/.claude/settings.json` does not exist and the scope includes the project, the
script first copies the global `settings.json` into it and then applies the switch. The project
then carries the same Claude setup (plugins, marketplaces, permissions, logger URL) as the global
file. If there is no global file either, it starts from an empty object.

## Scope rules

- Claude Code merges `env` from global and project settings, and project values win for the same key.
- **Project to GLM, global Claude**: this repo uses GLM and other repos use Claude. This works.
- **Project to Claude, global still GLM**: removing keys from the project file doesn't override anything,
  so the global GLM keys still apply and this repo **still uses GLM**. Switch global too, or use Both.
- The script prints a `NOTE:` when the two scopes disagree after a single-scope switch.
- `settings.local.json` also merges in. If `--status` says Claude but GLM is still active, check
  `<repo-root>/.claude/settings.local.json` and shell env vars (`ANTHROPIC_BASE_URL` etc.) for leftovers.

## Security

The project `settings.json` is usually committed. When a switch writes `ANTHROPIC_AUTH_TOKEN` into
the project file, warn the user not to commit it, or to `git restore` the file before committing.
Never stage or commit a settings file that contains the token.
