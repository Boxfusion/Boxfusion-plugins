#!/usr/bin/env python3
"""Lint, deploy and try bot flows (the pd-chat JSON flow engine). Python 3.9+, standard library only.

    flowtool.py lint   <flows-dir> [--actions actions.json] [--strict]
    flowtool.py actions --base-url URL [--token T | --user U]            (list what the host can run)
    flowtool.py deploy <flows-dir> --base-url URL [--user U] [--publish] [--entry NAME] [--allow-update] [--dry-run]
    flowtool.py chat   <script.json> --base-url URL [--mode draft|live]

<flows-dir> holds one <flowName>.json per flow (the file name is the flow name).

Credentials: --token (or FLOWTOOL_TOKEN), or --user with the password in FLOWTOOL_PASSWORD. Never put a password on
the command line or in a file you keep. Nothing here guesses credentials.

lint    offline: the engine's validation rules, plus WhatsApp length limits and a hardcoded-host check.
deploy  validates every flow on the host, saves each as a DRAFT (subflows first), and only with --publish makes
        them Live. Replacing a flow that is already Live needs --allow-update; changing the entry flow needs --entry.
chat    runs a scripted conversation through the host's bot tester and checks what comes back.
        Script: [{"say": "hi", "expect": ["Welcome"], "expectNot": ["error"]}, {"say": "option:Report a fault"}]
        "option:<title>" taps the option with that title from the previous reply. {"reset": true} restarts.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

NODE_TYPES = {"message", "prompt", "choice", "form", "condition", "set", "http", "action", "subflow", "end"}
NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,99}$")
RESERVED = {"draft", "validate", "versions", "actions", "ai"}
LIMITS = {"option title": 24, "option description": 72, "header": 60, "body": 1024, "form button label": 30}


# ------------------------------------------------------------------ lint

# .NET regex features Python's `re` does not know. A pattern using one cannot be checked offline; the host's
# validation (deploy, or POST api/bot-flows/validate) is authoritative for those.
DOTNET_ONLY = re.compile(r"\\[pP]\{|\(\?<[A-Za-z!=]|\\[hGzZ]|\(\?[imsnx]*-[imsnx]+[:)]|\[[^\]]*-\[")


def regex_problem(pattern: str):
    """None when the pattern compiles, else (message, checkable). checkable is False for .NET-only syntax."""
    try:
        re.compile(pattern)
        return None
    except re.error as ex:
        return str(ex), not DOTNET_ONLY.search(pattern)


def load_flows(folder: Path) -> dict:
    flows = {}
    for path in sorted(folder.glob("*.json")):
        try:
            flows[path.stem] = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as ex:
            flows[path.stem] = {"__error__": f"not valid JSON: {ex}"}
    return flows


def targets(node: dict):
    for key in ("next", "onError", "onMaxAttempts", "onBack", "else"):
        if node.get(key):
            yield key, node[key]
    for b in node.get("branches") or []:
        yield "branch next", b.get("next")
    for o in node.get("options") or []:
        yield f"option '{o.get('title')}' next", o.get("next")


def lint_flow(name: str, flow: dict, all_flows: dict, action_keys, strict: bool):
    errors, warnings = [], []
    if "__error__" in flow:
        return [flow["__error__"]], []
    if not NAME.match(name) or name.lower() in RESERVED:
        errors.append(f"flow name '{name}' must start with a letter, use letters/digits/-/_ and not be one of {sorted(RESERVED)}")
    nodes = flow.get("nodes") or {}
    if not nodes:
        return errors + ["the flow has no nodes"], warnings
    if flow.get("start") not in nodes:
        errors.append(f"start node '{flow.get('start')}' does not exist")

    for nid, n in nodes.items():
        def err(msg):
            errors.append(f"Node '{nid}' ({n.get('type')}): {msg}")

        t = n.get("type")
        if t not in NODE_TYPES:
            errors.append(f"Node '{nid}': unknown type '{t}'")
            continue
        for label, target in targets(n):
            if target and target not in nodes:
                err(f"{label} '{target}' does not exist")
        if "maxAttempts" in n and not (n.get("maxAttempts", 0) > 0 and n.get("onMaxAttempts")):
            err("'maxAttempts' needs a positive count and an 'onMaxAttempts' node")
        if n.get("pageSize") is not None and (t != "choice" or n["pageSize"] <= 0):
            err("'pageSize' must be positive and is only valid on a choice node")
        if t == "message" and not str(n.get("text", "")).strip():
            err("'text' is required")
        if t == "prompt":
            if not n.get("silent") and not str(n.get("text", "")).strip():
                err("'text' is required (unless the prompt is silent)")
            if not n.get("var"):
                err("'var' is required")
            problem = regex_problem(n["validate"]) if n.get("validate") else None
            if problem and problem[1]:
                err(f"invalid 'validate' regex: {problem[0]}")
            elif problem:
                warnings.append(f"Node '{nid}': 'validate' uses .NET-only regex syntax; cannot be checked offline (the host validates it on deploy)")
        if t == "choice":
            if not str(n.get("text", "")).strip():
                err("'text' is required")
            if not (n.get("options") or n.get("optionsFrom")):
                err("'options' or 'optionsFrom' is required")
            for o in n.get("options") or []:
                if not str(o.get("title", "")).strip():
                    err("every option needs a 'title'")
                if not o.get("next") and not n.get("next"):
                    err(f"option '{o.get('title')}' has no 'next' and the node has no default 'next'")
                if len(str(o.get("title", ""))) > LIMITS["option title"]:
                    warnings.append(f"Node '{nid}': option title '{o.get('title')}' is over {LIMITS['option title']} characters (cut on WhatsApp)")
                if len(str(o.get("description", ""))) > LIMITS["option description"]:
                    warnings.append(f"Node '{nid}': option description over {LIMITS['option description']} characters (cut on WhatsApp)")
        if t == "condition":
            if not n.get("branches"):
                err("at least one branch is required")
            if not n.get("else"):
                err("'else' is required")
        if t == "set" and not n.get("values"):
            err("'values' is required")
        if t == "http" and not str(n.get("url", "")).strip():
            err("'url' is required")
        if t == "action":
            if not n.get("action"):
                err("'action' is required")
            elif action_keys is not None and n["action"].lower() not in action_keys:
                (errors if strict else warnings).append(f"Node '{nid}': action '{n['action']}' is not in the known action list")
        if t == "subflow":
            if not n.get("flow"):
                err("'flow' is required")
            elif n["flow"] not in all_flows:
                (errors if strict else warnings).append(f"Node '{nid}': subflow '{n['flow']}' is not in this folder (it must already be Live on the host)")
        if t == "form":
            if not n.get("form"):
                err("choose the WhatsApp form to send ('form')")
            if not str(n.get("text", "")).strip():
                err("'text' (the message above the form's button) is required")
            if not n.get("var"):
                err("'var' (where the answers are saved) is required")
            if len(str(n.get("buttonLabel", ""))) > LIMITS["form button label"]:
                err("the button label must be 30 characters or fewer")
        for field in ("header",):
            if len(str(n.get(field, ""))) > LIMITS[field]:
                warnings.append(f"Node '{nid}': {field} is over {LIMITS[field]} characters (cut on WhatsApp)")
        if len(str(n.get("text", ""))) > LIMITS["body"] and t in ("message", "prompt", "choice"):
            warnings.append(f"Node '{nid}': text is over {LIMITS['body']} characters (long messages are split or cut on WhatsApp)")
        blob = json.dumps(n)
        if re.search(r"https?://(?!\{\{)[^\"'\s]*", n.get("url", "") or "") and t == "http":
            warnings.append(f"Node '{nid}': hardcoded host in 'url'; use {{{{config.apiBaseUrl}}}} so it follows the environment")
        if t != "http" and re.search(r"https?://localhost|127\.0\.0\.1", blob):
            warnings.append(f"Node '{nid}': refers to localhost")

    for i in flow.get("interrupts") or []:
        if not i.get("pattern"):
            errors.append("an interrupt has no pattern")
        else:
            problem = regex_problem(i["pattern"])
            if problem and problem[1]:
                errors.append(f"interrupt pattern '{i['pattern']}' is not a valid regular expression: {problem[0]}")
            elif problem:
                warnings.append(f"interrupt pattern '{i['pattern']}' uses .NET-only regex syntax; cannot be checked offline")
        if i.get("next") not in nodes:
            errors.append(f"interrupt '{i.get('pattern')}': next '{i.get('next')}' does not exist")

    if not errors:
        seen, stack = set(), [flow["start"]] + [i["next"] for i in flow.get("interrupts") or []]
        while stack:
            cur = stack.pop()
            if cur in seen or cur not in nodes:
                continue
            seen.add(cur)
            stack.extend(t for _, t in targets(nodes[cur]) if t)
        for nid in nodes:
            if nid not in seen:
                errors.append(f"Node '{nid}' is unreachable from '{flow['start']}'")
    return errors, warnings


def cmd_lint(args) -> int:
    folder = Path(args.dir)
    flows = load_flows(folder)
    if not flows:
        print(f"no .json flows in {folder}", file=sys.stderr)
        return 2
    keys = None
    if args.actions:
        data = json.loads(Path(args.actions).read_text(encoding="utf-8-sig"))
        data = data.get("result", data)
        keys = {a["key"].lower() for a in data}
    bad = 0
    for name, flow in flows.items():
        errors, warnings = lint_flow(name, flow, flows, keys, args.strict)
        for e in errors:
            print(f"ERROR   {name}: {e}")
        for w in warnings:
            print(f"warning {name}: {w}")
        bad += len(errors)
    print(f"\n{len(flows)} flow(s), {bad} error(s).")
    return 1 if bad else 0


# ------------------------------------------------------------------ http

class Api:
    def __init__(self, base: str, token: str):
        self.base, self.token = base.rstrip("/"), token

    def call(self, method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.base}{path}", data=data, method=method,
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                text = resp.read().decode("utf-8")
        except urllib.error.HTTPError as ex:
            text = ex.read().decode("utf-8", "replace")
            try:
                message = json.loads(text).get("error", {}).get("message")
            except (json.JSONDecodeError, AttributeError):
                message = None
            raise SystemExit(f"{method} {path} failed ({ex.code}): {message or text[:300]}")
        except urllib.error.URLError as ex:
            raise SystemExit(f"cannot reach {self.base}: {ex.reason}")
        payload = json.loads(text) if text else {}
        if isinstance(payload, dict) and payload.get("success") is False:
            raise SystemExit(f"{method} {path}: {(payload.get('error') or {}).get('message')}")
        return payload.get("result") if isinstance(payload, dict) and "result" in payload else payload


def connect(args) -> Api:
    token = args.token or os.environ.get("FLOWTOOL_TOKEN")
    if not token:
        password = os.environ.get("FLOWTOOL_PASSWORD")
        if not (args.user and password):
            raise SystemExit("give --token (or FLOWTOOL_TOKEN), or --user with FLOWTOOL_PASSWORD set. Ask the user; do not guess.")
        body = json.dumps({"userNameOrEmailAddress": args.user, "password": password}).encode()
        req = urllib.request.Request(f"{args.base_url.rstrip('/')}/api/TokenAuth/Authenticate", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                token = json.loads(resp.read().decode())["result"]["accessToken"]
        except (urllib.error.URLError, KeyError, json.JSONDecodeError) as ex:
            raise SystemExit(f"sign-in failed: {ex}. Stop and ask the user for working credentials.")
    return Api(args.base_url, token)


# ------------------------------------------------------------------ actions / deploy / chat

def cmd_actions(args) -> int:
    actions = connect(args).call("GET", "/api/bot-flows/actions")
    for a in sorted(actions, key=lambda a: (a.get("category") or "", a["key"])):
        params = ", ".join(f"{p['name']}{'*' if p.get('required') else ''}" for p in a.get("params", []))
        flag = "" if a.get("available", True) else f"  [UNAVAILABLE: {a.get('unavailableReason')}]"
        print(f"{a['key']}({params}) - {a.get('description') or ''}{flag}")
    if args.json:
        Path(args.json).write_text(json.dumps(actions, indent=2), encoding="utf-8")
    return 0


def order_by_dependencies(flows: dict) -> list:
    deps = {n: {x.get("flow") for x in (f.get("nodes") or {}).values() if x.get("type") == "subflow" and x.get("flow") in flows and x.get("flow") != n}
            for n, f in flows.items()}
    ordered, done = [], set()
    while len(ordered) < len(flows):
        ready = [n for n in sorted(flows) if n not in done and deps[n] <= done]
        if not ready:
            left = sorted(set(flows) - done)
            print(f"warning: these flows call each other in a cycle and cannot all be published in one pass: {left}", file=sys.stderr)
            ready = left
        for n in ready:
            ordered.append(n)
            done.add(n)
    return ordered


def cmd_deploy(args) -> int:
    flows = load_flows(Path(args.dir))
    if not flows:
        print("no flows found", file=sys.stderr)
        return 2
    api = connect(args)
    existing = {f["name"]: f for f in api.call("GET", "/api/bot-flows")}

    problems = 0
    for name, flow in flows.items():
        if "__error__" in flow:
            print(f"ERROR {name}: {flow['__error__']}")
            problems += 1
            continue
        result = api.call("POST", "/api/bot-flows/validate", {"definition": json.dumps(flow)})
        for e in result.get("errors", []):
            print(f"ERROR {name}: {e}")
            problems += 1
    if problems:
        print(f"\n{problems} validation error(s) on the host; nothing was saved.")
        return 1

    replaces_live = [n for n in flows if existing.get(n, {}).get("liveVersionId")]
    if args.publish and replaces_live and not args.allow_update:
        print(f"These flows are already Live and --publish would replace them: {sorted(replaces_live)}.\n"
              "Running conversations stay on their version, but new ones change. Get the user's go-ahead, then add --allow-update.")
        return 3
    current_entry = next((n for n, f in existing.items() if f.get("isEntryPoint")), None)
    if args.entry and args.publish and args.entry != current_entry and current_entry and not args.allow_update:
        print(f"'{args.entry}' would become the entry flow instead of '{current_entry}'. Add --allow-update once the user agrees.")
        return 3

    plan = order_by_dependencies(flows)
    print("Plan (subflows first): " + ", ".join(plan) + ("   [dry run]" if args.dry_run else ""))
    if args.dry_run:
        return 0
    for name in plan:
        flow = {k: v for k, v in flows[name].items()}
        saved = api.call("POST", "/api/bot-flows/draft", {
            "name": name, "label": flow.pop("label", None) or name, "description": flow.pop("description", None),
            "isEntryPoint": (name == args.entry) if args.entry else bool(existing.get(name, {}).get("isEntryPoint")), "definition": json.dumps(flow, indent=2)})
        print(f"saved draft  {name} v{saved['versionNo']}")
        if args.publish:
            out = api.call("POST", f"/api/bot-flows/versions/{saved['versionId']}/publish")
            if not out.get("published"):
                print(f"NOT published {name}: {out.get('errors')}")
                return 1
            print(f"published    {name} v{saved['versionNo']}")
    return 0


def cmd_chat(args) -> int:
    api = connect(args)
    steps = json.loads(Path(args.script).read_text(encoding="utf-8-sig"))
    mode = args.mode
    api.call("POST", f"/api/bot-tester/reset?mode={mode}")
    failures, last = 0, None
    for i, step in enumerate(steps, 1):
        if step.get("reset"):
            api.call("POST", f"/api/bot-tester/reset?mode={mode}")
            print(f"{i:>2}. (reset)")
            last = None
            continue
        say = step["say"]
        if say.startswith("option:"):
            wanted = say[7:].strip().lower()
            options = [o for m in (last or {}).get("messages", []) for o in m.get("options", [])]
            match = next((o for o in options if o["title"].strip().lower() == wanted), None)
            if not match:
                print(f"{i:>2}. FAIL: no option '{wanted}' in the previous reply (had: {[o['title'] for o in options]})")
                failures += 1
                continue
            say = match["postback"]
        reply = api.call("POST", "/api/bot-tester/message", {"text": say, "mode": mode})
        last = reply
        text = "\n".join(filter(None, [
            part for m in reply.get("messages", [])
            for part in [m.get("header"), m.get("text") or m.get("body"), m.get("footer"), *[o["title"] for o in m.get("options", [])]]]))
        state = reply.get("state") or {}
        print(f"{i:>2}. > {step['say']}\n    < {text.replace(chr(10), chr(10) + '      ')}\n    [flow={state.get('flow')} node={state.get('node')} completed={reply.get('completed')}]")
        if reply.get("error"):
            print(f"    ERROR from engine: {reply['error']}")
            failures += 1
        for want in step.get("expect", []):
            if want.lower() not in text.lower():
                print(f"    FAIL expected to see: {want!r}")
                failures += 1
        for bad in step.get("expectNot", []):
            if bad.lower() in text.lower():
                print(f"    FAIL did not expect: {bad!r}")
                failures += 1
        if "expectNode" in step and state.get("node") != step["expectNode"]:
            print(f"    FAIL expected node {step['expectNode']!r}, at {state.get('node')!r}")
            failures += 1
    print(f"\n{len(steps)} step(s), {failures} failure(s).")
    return 1 if failures else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def host(p):
        p.add_argument("--base-url", required=True)
        p.add_argument("--token")
        p.add_argument("--user")

    p = sub.add_parser("lint")
    p.add_argument("dir")
    p.add_argument("--actions", help="JSON from `actions --json` (or GET api/bot-flows/actions) to check action keys against")
    p.add_argument("--strict", action="store_true", help="unknown actions / subflows are errors, not warnings")
    p.set_defaults(fn=cmd_lint)

    p = sub.add_parser("actions")
    host(p)
    p.add_argument("--json")
    p.set_defaults(fn=cmd_actions)

    p = sub.add_parser("deploy")
    p.add_argument("dir")
    host(p)
    p.add_argument("--publish", action="store_true")
    p.add_argument("--entry", help="name of the flow new conversations start in")
    p.add_argument("--allow-update", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_deploy)

    p = sub.add_parser("chat")
    p.add_argument("script")
    host(p)
    p.add_argument("--mode", choices=["draft", "live"], default="draft")
    p.set_defaults(fn=cmd_chat)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
