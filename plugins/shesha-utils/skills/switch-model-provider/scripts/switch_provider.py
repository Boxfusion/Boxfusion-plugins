#!/usr/bin/env python3
"""Switch Claude Code between Anthropic (Claude) and Z.ai (GLM) via settings.json env vars.

GLM mode adds the ANTHROPIC_* override env vars (plus CLAUDE_LOGGER_API_URL) to the
`env` block. Claude mode removes only the ANTHROPIC_* override keys. Every other key
in the file is preserved. Standard library only.
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

DEFAULT_LOGGER_URL = "https://saa-testmanager-api-test.shesha.app"
DEFAULT_BASE_URL = "https://api.z.ai/api/anthropic"
DEFAULT_MODEL = "glm-5.3"
DEFAULT_FAST_MODEL = "glm-5.3-flash"
PLACEHOLDER_TOKENS = {"", "ApiKey", "<api-key>"}

# Keys that make Claude Code call Z.ai instead of Anthropic. Removed on switch back.
GLM_KEYS = [
    "ANTHROPIC_MODEL",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
]


def global_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def project_settings_path(project_dir: str) -> Path:
    return Path(project_dir).resolve() / ".claude" / "settings.json"


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def env_of(data: dict) -> dict:
    env = data.get("env")
    if not isinstance(env, dict):
        env = {}
        data["env"] = env
    return env


def provider_of(data: dict) -> str:
    env = data.get("env") if isinstance(data.get("env"), dict) else {}
    base = env.get("ANTHROPIC_BASE_URL", "")
    if "z.ai" in base or "bigmodel" in base:
        return "glm"
    if any(k in env for k in GLM_KEYS):
        return "mixed (partial GLM keys)"
    return "claude"


def resolve_token(explicit, candidates) -> str:
    if explicit and explicit not in PLACEHOLDER_TOKENS:
        return explicit
    for data in candidates:
        env = data.get("env") if isinstance(data.get("env"), dict) else {}
        token = env.get("ANTHROPIC_AUTH_TOKEN", "")
        if token not in PLACEHOLDER_TOKENS:
            return token
    token = os.environ.get("ZAI_API_KEY", "")
    if token not in PLACEHOLDER_TOKENS:
        return token
    return ""


def apply_glm(data: dict, args, token: str) -> None:
    env = env_of(data)
    env["CLAUDE_LOGGER_API_URL"] = args.logger_url
    env["ANTHROPIC_MODEL"] = args.model
    env["ANTHROPIC_BASE_URL"] = args.base_url
    env["ANTHROPIC_AUTH_TOKEN"] = token
    env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = args.fast_model
    env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = args.model
    env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = args.model


def apply_claude(data: dict) -> list:
    env = data.get("env")
    if not isinstance(env, dict):
        return []
    removed = [k for k in GLM_KEYS if env.pop(k, None) is not None]
    if not env:
        del data["env"]
    return removed


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--to", choices=["glm", "claude"], help="Target provider")
    p.add_argument("--scope", choices=["global", "project", "both"], default="both")
    p.add_argument("--project-dir", default=os.getcwd())
    p.add_argument("--status", action="store_true", help="Only report the current provider per scope")
    p.add_argument("--api-key", help="Z.ai API key (else reuses an existing token or $ZAI_API_KEY)")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--fast-model", default=DEFAULT_FAST_MODEL)
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--logger-url", default=DEFAULT_LOGGER_URL)
    args = p.parse_args()

    gpath = global_settings_path()
    ppath = project_settings_path(args.project_dir)

    if args.status:
        for label, path in (("global", gpath), ("project", ppath)):
            state = provider_of(load(path)) if path.exists() else "claude (no settings.json)"
            print(f"{label:8} {state:28} {path}")
        return 0

    if not args.to:
        p.error("--to is required unless --status is given")

    targets = []
    if args.scope in ("global", "both"):
        targets.append(("global", gpath))
    if args.scope in ("project", "both"):
        targets.append(("project", ppath))

    gdata = load(gpath)
    pdata = load(ppath)

    token = ""
    if args.to == "glm":
        token = resolve_token(args.api_key, [pdata, gdata])
        if not token:
            print("ERROR: no Z.ai API key. Pass --api-key or set ZAI_API_KEY.", file=sys.stderr)
            return 2

    docs = {"global": gdata, "project": pdata}
    if args.scope != "global" and not ppath.exists():
        # Bootstrap the project from the global Claude settings.
        docs["project"] = json.loads(json.dumps(gdata))
        print(f"project  bootstrapped from {gpath}" if gdata else "project  created (global settings.json was empty/missing)")

    for label, path in targets:
        data = docs[label]
        if args.to == "glm":
            apply_glm(data, args, token)
            print(f"{label:8} -> GLM ({args.model}, fast={args.fast_model})  {path}")
        else:
            removed = apply_claude(data)
            note = f"removed {len(removed)} key(s)" if removed else "already Claude"
            print(f"{label:8} -> Claude ({note})  {path}")
        save(path, data)

    # env blocks merge across scopes: a GLM key in either file makes this repo call GLM.
    if args.scope != "both":
        g = provider_of(load(gpath))
        pr = provider_of(load(ppath)) if ppath.exists() else "claude"
        if g != pr:
            print(f"NOTE: global is '{g}', project is '{pr}'. The env blocks merge, so while "
                  "either file holds the GLM keys this repo still calls GLM. Switch 'both' to be sure.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
