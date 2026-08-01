"""Periodic HEARTBEAT maintenance: consolidate logs into MEMORY via Scout model (memory_replace only)."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from litellm_client import build_completion_payload, sanitize_tools_for_model
from prompts_config import get_scout_routing_prompt
from scout_persona import (
    MEMORY_REPLACE_DECLARATION,
    build_scout_system_instruction,
    get_heartbeat_state,
    read_heartbeat_instructions,
    read_persona_markdown,
    replace_memory_markdown,
    set_heartbeat_state,
    tail_recent_daily_logs,
    load_persona_config,
)

logger = logging.getLogger(__name__)

_SCOUT_TURN_LOCK = asyncio.Lock()


def scout_turn_lock() -> asyncio.Lock:
    return _SCOUT_TURN_LOCK


def _maintenance_rules() -> str:
    return (
        "You are the Ada-SI maintenance brain for Scout. Follow HEARTBEAT.md and read "
        "RECENT_DAILY_LOGS in the user message. You may only change MEMORY.md (via memory_replace). "
        "Do not use soul_replace in this pass; SOUL, IDENTITY, USER, and TOOLS are out of scope. "
        "Use only the provided tools. Do not invent web facts. Be concise; the user does not see this turn."
    )


def _heartbeat_tools_payload() -> list[dict]:
    return sanitize_tools_for_model([MEMORY_REPLACE_DECLARATION], model="")


async def run_heartbeat_tick(
    *,
    lite_model: str,
    litellm_url: str,
    litellm_headers: dict[str, str],
    reasoning_effort: str | None = None,
) -> None:
    config = load_persona_config()
    if not config.get("heartbeat_enabled", True):
        return

    if _SCOUT_TURN_LOCK.locked():
        return

    if not lite_model:
        return

    hb_text = read_heartbeat_instructions()
    logs_tail = tail_recent_daily_logs()
    memory_current = read_persona_markdown("memory")

    user_msg = (
        "Run your HEARTBEAT maintenance pass now.\n\n"
        f"=== HEARTBEAT_MD ===\n{hb_text}\n\n"
        f"=== RECENT_DAILY_LOGS ===\n{logs_tail}\n\n"
        f"=== CURRENT_MEMORY_MD ===\n{memory_current}\n"
    )

    sys_instr = build_scout_system_instruction(
        get_scout_routing_prompt(),
        for_heartbeat_maintenance=True,
    )
    # Replace generic maintenance header with Ada-specific rules
    sys_instr = sys_instr.replace(
        "=== MAINTENANCE ===\n" + get_scout_routing_prompt().strip(),
        "=== MAINTENANCE ===\n" + _maintenance_rules(),
        1,
    )

    model = lite_model
    if model and "live" in str(model).lower():
        return

    tools = _heartbeat_tools_payload()
    messages = [
        {"role": "system", "content": sys_instr},
        {"role": "user", "content": user_msg},
    ]

    memory_updated = False
    async with _SCOUT_TURN_LOCK:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                working = list(messages)
                for _ in range(5):
                    req_payload = build_completion_payload(
                        model=model,
                        messages=working,
                        tools=tools,
                        stream=False,
                        
                        reasoning_effort=reasoning_effort,
                    )
                    resp = await client.post(
                        f"{litellm_url.rstrip('/')}/chat/completions",
                        headers=litellm_headers,
                        json=req_payload,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    choice = (data.get("choices") or [{}])[0]
                    message = choice.get("message") or {}
                    tool_calls = message.get("tool_calls") or []
                    if not tool_calls:
                        break
                    working.append(message)
                    for tc in tool_calls:
                        fn = tc.get("function") or {}
                        fname = fn.get("name", "")
                        raw_args = fn.get("arguments") or "{}"
                        try:
                            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        except json.JSONDecodeError:
                            args = {}
                        if fname != "memory_replace":
                            result = {"ok": False, "error": "unknown function"}
                        else:
                            md = str(args.get("markdown") or "")
                            result = replace_memory_markdown(md)
                            if result.get("ok"):
                                memory_updated = True
                        working.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.get("id", ""),
                                "content": json.dumps(result),
                            }
                        )
        except Exception as e:
            logger.warning("[heartbeat] error: %s", e)
            return

    set_heartbeat_state(
        last_run_utc=datetime.now(timezone.utc).isoformat(),
        last_memory_updated=memory_updated,
    )


async def heartbeat_supervisor_loop(
    *,
    lite_model: str,
    litellm_url: str,
    litellm_headers_fn,
    reasoning_effort: str | None,
) -> None:
    """Wake periodically; run tick if interval elapsed."""
    while True:
        try:
            await asyncio.sleep(30.0)
            config = load_persona_config()
            if not config.get("heartbeat_enabled", True):
                continue
            interval_min = max(1, int(config.get("heartbeat_interval_minutes", 30) or 30))
            st = get_heartbeat_state()
            last = st.get("last_run_utc")
            now = datetime.now(timezone.utc)
            need = False
            if not last:
                need = True
            else:
                try:
                    lp = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                    if lp.tzinfo is None:
                        lp = lp.replace(tzinfo=timezone.utc)
                    if (now - lp).total_seconds() >= interval_min * 60:
                        need = True
                except Exception:
                    need = True
            if not need:
                continue
            await run_heartbeat_tick(
                lite_model=lite_model,
                litellm_url=litellm_url,
                litellm_headers=litellm_headers_fn(),
                reasoning_effort=reasoning_effort,
            )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("[heartbeat] supervisor error: %s", e)
            await asyncio.sleep(5.0)
