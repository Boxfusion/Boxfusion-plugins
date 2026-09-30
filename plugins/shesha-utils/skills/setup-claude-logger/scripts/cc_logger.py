#!/usr/bin/env python3
"""Standalone Claude Code hook logger.

Reads a Claude Code hook event payload from stdin, enriches it (turn cost,
transcript details on ``Stop``), and forwards the record directly to the
configured ingest backend. This replaces the previous setup where each hook
posted to a running Shesha MCP server (``/api/claude-logger/ingest``) which
did the enrichment and forwarding — there is no longer any local server to
keep running.

Everything is best-effort: this script NEVER raises and NEVER blocks the
caller for long. If forwarding is not configured (no API URL) or the backend
is unreachable, the event is silently dropped.

Configuration (all via environment variables — installed into the Claude Code
``settings.json`` ``env`` block by ``install_logger_hooks.py``):

    CLAUDE_LOGGER_API_URL       Base URL of the ingest backend. Required;
                                without it forwarding is a no-op.
    CLAUDE_LOGGER_INGEST_PATH   Path appended to the base URL
                                (default: /api/services/SaaTestManager/ClaudeLog/Ingest).
    CLAUDE_LOGGER_API_TOKEN     Optional bearer token.
    CLAUDE_LOGGER_TIMEOUT       Forward request timeout in seconds (default: 5).
    CLAUDE_LOGGER_ORGANISATION  Organisation name tagged onto every record.
    CLAUDE_LOGGER_USER          Fallback user when the payload carries none.
    CLAUDE_LOGGER_DEBUG_LOG     Optional path to a local file; when set, each
                                event's name and forward outcome (HTTP status or
                                error) is appended for troubleshooting.

Test-harness linkage (optional; set by the SAA test harness per agent /
evaluator run so each ClaudeLog row can be tied to the run that produced it):

    CLAUDE_LOGGER_TEST_RUN_ID     -> test_run_id
    CLAUDE_LOGGER_TEST_CASE_ID    -> test_case_id
    CLAUDE_LOGGER_TEST_CASE_NAME  -> test_case_name
    CLAUDE_LOGGER_ITERATION       -> iteration (int)
    CLAUDE_LOGGER_HARNESS_ROLE    -> harness_role ("agent" / "evaluator")
"""

from __future__ import annotations

import getpass
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

DEFAULT_INGEST_PATH = "/api/services/SaaTestManager/ClaudeLog/Ingest"
DEFAULT_TIMEOUT = 5.0


def _debug(message: str) -> None:
    """Append a diagnostic line to CLAUDE_LOGGER_DEBUG_LOG, if configured.
    Best-effort: any failure here is ignored so it never disrupts the hook."""
    path = os.environ.get("CLAUDE_LOGGER_DEBUG_LOG")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")
    except OSError:
        pass

# Free-form payloads whose inner keys belong to external tool schemas and must
# not be camelized. Sent as JSON strings so the backend stores them verbatim
# instead of trying to deserialize them into a typed structure.
_OPAQUE_KEYS = frozenset({"tool_input", "tool_response"})

# USD per 1M tokens: (input, output, cache_write_5m, cache_read).
# Matched by longest prefix so dated IDs (e.g. claude-haiku-4-5-20251001) and
# suffixes like "[1m]" work, and "claude-opus-5-5" isn't priced as "claude-opus-5".
PRICING: dict[str, tuple[float, float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 12.50, 0.25),
    "claude-mythos-5-1": (10.0, 50.0, 12.50, 0.25),
    "claude-fable-5": (10.0, 50.0, 12.50, 1.00),
    "claude-mythos-5": (10.0, 50.0, 12.50, 1.00),
    "claude-opus-5-5": (4.0, 20.0, 5.00, 0.20),
    "claude-opus-5": (5.0, 25.0, 6.25, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 6.25, 0.50),
    "claude-opus-4-7": (5.0, 25.0, 6.25, 0.50),
    "claude-opus-4-6": (5.0, 25.0, 6.25, 0.50),
    "claude-opus-4-5": (5.0, 25.0, 6.25, 0.50),
    "claude-opus-4": (15.0, 75.0, 18.75, 1.50),
    "claude-sonnet-5": (2.0, 10.0, 2.50, 0.20),
    "claude-sonnet-4": (3.0, 15.0, 3.75, 0.30),
    "claude-haiku-4-5": (1.0, 5.0, 1.25, 0.10),
    # Z.ai GLM (docs.z.ai/guides/overview/pricing). Cache storage is free, so
    # cache writes are billed at the plain input rate.
    "glm-5.3-flashx": (0.37, 1.25, 0.37, 0.075),
    "glm-5.3-flash": (0.15, 0.50, 0.15, 0.03),
    "glm-5.3": (1.4, 4.4, 1.4, 0.26),
    "glm-5.2": (1.4, 4.4, 1.4, 0.26),
    "glm-5.1": (1.4, 4.4, 1.4, 0.26),
    "glm-5": (1.0, 3.2, 1.0, 0.20),
    "glm-4.7-flashx": (0.07, 0.40, 0.07, 0.01),
    "glm-4.7-flash": (0.0, 0.0, 0.0, 0.0),
    "glm-4.7": (0.6, 2.2, 0.6, 0.11),
    "glm-4.6v-flashx": (0.04, 0.40, 0.04, 0.004),
    "glm-4.6v-flash": (0.0, 0.0, 0.0, 0.0),
    "glm-4.6v": (0.3, 0.9, 0.3, 0.05),
    "glm-4.6": (0.6, 2.2, 0.6, 0.11),
    "glm-4.5v": (0.6, 1.8, 0.6, 0.11),
    "glm-4.5-airx": (1.1, 4.5, 1.1, 0.22),
    "glm-4.5-air": (0.2, 1.1, 0.2, 0.03),
    "glm-4.5-x": (2.2, 8.9, 2.2, 0.45),
    "glm-4.5-flash": (0.0, 0.0, 0.0, 0.0),
    "glm-4.5": (0.6, 2.2, 0.6, 0.11),
    "glm-4-32b": (0.1, 0.1, 0.1, 0.1),
    "glm-ocr": (0.03, 0.03, 0.03, 0.03),
}

# Last-resort rates by family, so a model newer than the table above still gets
# a (approximate) cost instead of null.
FAMILY_FALLBACK: dict[str, tuple[float, float, float, float]] = {
    "fable": PRICING["claude-fable-5-1"],
    "mythos": PRICING["claude-mythos-5-1"],
    "opus": PRICING["claude-opus-5-5"],
    "sonnet": PRICING["claude-sonnet-5"],
    "haiku": PRICING["claude-haiku-4-5"],
    "glm": PRICING["glm-5.3"],
}
DEFAULT_PRICING = PRICING["claude-opus-5-5"]


# --------------------------------------------------------------------------- #
# Enrichment (ported from log_processor.py)
# --------------------------------------------------------------------------- #
def _lookup_pricing(model: str | None) -> tuple[float, float, float, float]:
    # Drop router prefixes such as "z-ai/glm-4.6" or "anthropic/claude-...".
    name = (model or "").strip().lower().rsplit("/", 1)[-1]
    for key in sorted(PRICING, key=len, reverse=True):
        if name.startswith(key):
            return PRICING[key]
    for family, prices in FAMILY_FALLBACK.items():
        if family in name:
            return prices
    _debug(f"no pricing for model {model!r}; using default rates")
    return DEFAULT_PRICING


def _calculate_cost(usage: dict[str, Any], model: str | None) -> float:
    in_p, out_p, cache_w_p, cache_r_p = _lookup_pricing(model)
    cost = (
        (usage.get("input_tokens") or 0) * in_p
        + (usage.get("output_tokens") or 0) * out_p
        + (usage.get("cache_creation_input_tokens") or 0) * cache_w_p
        + (usage.get("cache_read_input_tokens") or 0) * cache_r_p
    ) / 1_000_000
    return round(cost, 6)


_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def _extract_user_prompt(message: dict[str, Any]) -> str | None:
    """Pull plain-text prompt out of a user message. Returns None for
    tool_result-only messages (those are not real user prompts)."""
    content = message.get("content")
    if isinstance(content, str):
        return content or None
    if isinstance(content, list):
        text_parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text") or "")
        return "".join(text_parts) or None
    return None


def _os_username() -> str | None:
    """Best-effort name of the OS user running Claude Code. getpass.getuser()
    consults LOGNAME/USER/LNAME/USERNAME (so it works on POSIX and Windows).
    Returns None if no username can be resolved."""
    try:
        return getpass.getuser() or None
    except Exception:  # noqa: BLE001 - never let user resolution break logging
        return None


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _read_last_turn(transcript_path: str) -> dict[str, Any]:
    """Return {prompt, prompt_ts, response, response_ts, duration_ms,
    model, usage, cost_usd} for the final user-prompt -> assistant-response
    pair in the transcript.

    The transcript file lives on the machine running Claude Code, which is the
    same machine running this hook, so the path is readable.
    """
    try:
        with open(transcript_path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return {}

    result: dict[str, Any] = {}
    # A turn spans many API calls (one per tool round-trip), and Claude Code
    # writes one transcript entry per content block, repeating the message's
    # usage on each. Collect usage per message id so every call in the turn is
    # billed exactly once.
    usage_by_msg: dict[str, tuple[dict[str, Any], str | None]] = {}
    response_parts: list[str] = []
    response_msg_id: str | None = None

    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = entry.get("message") or {}
        role = message.get("role")

        if role == "assistant" or entry.get("type") == "assistant":
            model = message.get("model") or entry.get("model")
            msg_id = message.get("id") or entry.get("uuid") or str(len(usage_by_msg))
            if "response_ts" not in result:
                result["response_ts"] = entry.get("timestamp")
            if model and model != "<synthetic>":
                result.setdefault("model", model)
                usage = message.get("usage") or {}
                # Reverse order: the first entry seen per id is the latest,
                # carrying the final output token count.
                if usage and msg_id not in usage_by_msg:
                    usage_by_msg[msg_id] = (usage, model)
            text = "".join(
                block.get("text") or ""
                for block in message.get("content") or []
                if isinstance(block, dict) and block.get("type") == "text"
            )
            if text and (response_msg_id is None or response_msg_id == msg_id):
                response_msg_id = msg_id
                response_parts.insert(0, text)
            continue

        if role == "user" or entry.get("type") == "user":
            prompt_text = _extract_user_prompt(message)
            if prompt_text:
                result["prompt"] = prompt_text
                result["prompt_ts"] = entry.get("timestamp")
                break

    totals = {key: 0 for key in _USAGE_KEYS}
    cost = 0.0
    for usage, model in usage_by_msg.values():
        for key in _USAGE_KEYS:
            totals[key] += usage.get(key) or 0
        cost += _calculate_cost(usage, model)
    result["response"] = "".join(response_parts) or None
    result["usage"] = totals
    result["cost_usd"] = round(cost, 6)

    t_prompt = _parse_ts(result.get("prompt_ts"))
    t_response = _parse_ts(result.get("response_ts"))
    if t_prompt and t_response:
        result["duration_ms"] = round((t_response - t_prompt).total_seconds() * 1000, 2)
    return result


_HARNESS_TAG_ENV = {
    "test_run_id": "CLAUDE_LOGGER_TEST_RUN_ID",
    "test_case_id": "CLAUDE_LOGGER_TEST_CASE_ID",
    "test_case_name": "CLAUDE_LOGGER_TEST_CASE_NAME",
    "iteration": "CLAUDE_LOGGER_ITERATION",
    "harness_role": "CLAUDE_LOGGER_HARNESS_ROLE",
}


def _harness_tags() -> dict[str, Any]:
    """Test-harness linkage tags from the environment (empty outside the harness)."""
    tags: dict[str, Any] = {}
    for field, var in _HARNESS_TAG_ENV.items():
        value = (os.environ.get(var) or "").strip()
        if not value:
            continue
        if field == "iteration":
            try:
                tags[field] = int(value)
            except ValueError:
                continue
        else:
            tags[field] = value
    return tags


def build_log_record(
    payload: dict[str, Any],
    *,
    organisation: str | None = None,
    default_user: str | None = None,
) -> dict[str, Any]:
    """Build the enriched log record from a hook event payload."""
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "organisation": organisation,
        **payload,
    }
    record.setdefault("cwd", payload.get("cwd"))
    for key, value in _harness_tags().items():
        record.setdefault(key, value)
    # Precedence: a user supplied in the payload (rare) → the explicit
    # CLAUDE_LOGGER_USER override → the OS user running Claude Code. So every
    # record is tagged with whoever is prompting, even with no configuration.
    if not record.get("user"):
        record["user"] = default_user or _os_username()

    if payload.get("hook_event_name") == "Stop":
        transcript_path = payload.get("transcript_path")
        if transcript_path:
            # Enrichment is best-effort: a malformed/locked transcript or an
            # unexpected entry shape must never stop the Stop event itself from
            # being forwarded. Without this guard a failure here propagated up
            # and the whole event was silently dropped.
            try:
                record.update(_read_last_turn(transcript_path))
            except Exception as exc:  # noqa: BLE001 - never let enrichment break logging
                _debug(f"Stop enrichment failed: {exc!r}")
        # Always send a cost on Stop, even when the transcript was unreadable.
        if record.get("cost_usd") is None:
            record["cost_usd"] = 0.0

    return record


# --------------------------------------------------------------------------- #
# Forwarding (ported from backend_client.py)
# --------------------------------------------------------------------------- #
def _snake_to_camel(key: str) -> str:
    if "_" not in key:
        return key
    head, *rest = key.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def _camelize(value: Any) -> Any:
    if isinstance(value, dict):
        return {_snake_to_camel(k): _camelize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_camelize(v) for v in value]
    return value


def _stringify_opaque(record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    for key in _OPAQUE_KEYS:
        if key in out and not isinstance(out[key], str):
            out[key] = json.dumps(out[key], ensure_ascii=False, default=str)
    return out


def _valid_base_url(candidate: str | None) -> str:
    """Return ``candidate`` only if it is a usable http(s) base URL."""
    value = (candidate or "").strip()
    if value.startswith(("http://", "https://")):
        return value
    return ""


def forward_event(
    record: dict[str, Any],
    *,
    api_url: str,
    ingest_path: str,
    api_token: str | None,
    timeout: float,
) -> None:
    """Forward one enriched log record to the ingest backend.

    Silently swallows all errors so logging never disrupts the hook caller.
    """
    event_name = record.get("hook_event_name") or record.get("hookEventName") or "?"
    base = _valid_base_url(api_url).rstrip("/")
    if not base:
        _debug(f"{event_name}: not forwarded (no/invalid CLAUDE_LOGGER_API_URL)")
        return

    body = json.dumps(
        _camelize(_stringify_opaque(record)),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")

    req = urllib.request.Request(
        url=base + ingest_path,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    if api_token:
        req.add_header("Authorization", f"Bearer {api_token}")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()  # drain
            _debug(f"{event_name}: forwarded ({resp.status})")
    except urllib.error.HTTPError as exc:
        # Backend reached but rejected the payload (e.g. 400/500). Previously
        # indistinguishable from success — surface it so dropped events (often
        # the richer Stop record) can be diagnosed.
        _debug(f"{event_name}: backend rejected (HTTP {exc.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Backend down, slow, or unreachable - that's fine, logging is
        # best-effort and must never break the caller.
        _debug(f"{event_name}: forward failed ({exc!r})")
        return


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main() -> int:
    raw = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {"_raw": payload}
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {"_raw": raw.decode("utf-8", errors="replace"), "_parse_error": True}

    try:
        timeout = float(os.environ.get("CLAUDE_LOGGER_TIMEOUT") or DEFAULT_TIMEOUT)
    except ValueError:
        timeout = DEFAULT_TIMEOUT

    try:
        record = build_log_record(
            payload,
            organisation=os.environ.get("CLAUDE_LOGGER_ORGANISATION") or None,
            default_user=os.environ.get("CLAUDE_LOGGER_USER") or None,
        )
    except Exception as exc:  # noqa: BLE001 - forward the raw event regardless
        _debug(f"build_log_record failed: {exc!r}; forwarding raw payload")
        record = {"ts": datetime.now(timezone.utc).isoformat(), **payload}

    forward_event(
        record,
        api_url=os.environ.get("CLAUDE_LOGGER_API_URL", ""),
        ingest_path=os.environ.get("CLAUDE_LOGGER_INGEST_PATH") or DEFAULT_INGEST_PATH,
        api_token=os.environ.get("CLAUDE_LOGGER_API_TOKEN") or None,
        timeout=timeout,
    )
    return 0


if __name__ == "__main__":
    # Never let an unexpected error surface to the hook caller.
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
