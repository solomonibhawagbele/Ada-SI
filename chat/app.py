import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from elevenlabs_tts import list_voices, stream_speech, synthesize_speech
from prompts_config import (
    PROMPT_KEYS,
    default_prompts_config,
    load_prompts_config,
    prompts_config_response,
    reset_prompts_config,
    save_prompts_config,
)
from secrets_config import (
    SUPPORTED_SECRET_KEYS,
    apply_secrets_to_environ,
    clear_secret,
    save_secrets_raw,
    secrets_status_response,
)
from build_ui_qa import stream_interactive_ui_qa
from forge_batch import (
    RUNTIME_INSTALL_LOCK,
    approve_all_plans,
    approve_plan,
    batch_sse,
    batch_terminal,
    build_resume_summary,
    build_batch_scout_resume_message,
    build_single_tool_scout_resume_message,
    cancel_batch,
    create_batch,
    get_pending_batch,
    merge_async_generators,
    mark_batch_tool_failed,
    mark_batch_tool_installed,
    plan_ids_ready_to_build,
    reject_plan,
    set_entry_status,
    stream_batch_plan_revision,
    stream_parallel_plan_phase,
    validate_batch_tools,
)
from build_pipeline import (
    PENDING_PIP_INSTALLS,
    PENDING_UI_PREVIEWS,
    PHASE_MAX_RETRIES,
    continue_tool_build,
    get_pending_pip,
    get_pending_ui_preview,
    maybe_pause_for_pip_approval,
    maybe_pause_for_ui_preview,
    run_sandbox_phase,
    stream_runtime_install,
)
from debug_log import (
    configure_logging,
    log_assistant_turn,
    log_build_event,
    log_chat_request,
    log_debug,
    log_error,
    log_generated_code,
    log_pip_install,
    log_plan,
    log_sandbox,
    log_stream_delta,
    log_tool_execution,
)
from heartbeat_service import heartbeat_supervisor_loop
from scout_persona import (
    PERSONA_TOOL_NAMES,
    BOOTSTRAP_OPENING_TRIGGER,
    ensure_persona_layout,
    execute_persona_tool,
    migrate_scout_additional_directives,
    parse_identity_display_name,
    parse_persona_api_file,
    persona_api_response,
    persona_status,
    read_bootstrap_markdown,
    reset_persona_markdown_to_templates,
    save_persona_config,
    start_bootstrap_ritual,
    write_persona_markdown,
)
from litellm_client import (
    SSE_HEADERS,
    ThinkStreamParser,
    extract_stream_delta,
    extract_stream_tool_calls,
    extract_search_sources_from_chunk,
    extract_search_sources_from_message,
    is_gemini_model,
    merge_search_sources,
    merge_tool_call_delta,
    new_stream_chunk_id,
    openai_stream_chunk,
    stream_chat_completion,
    tool_calls_from_acc,
)
from runtime_client import (
    runtime_health,
    runtime_install_tool,
    runtime_list_pip_packages,
    runtime_uninstall_pip_package,
    set_runtime_url,
)
from tool_creator import (
    draft_tool_edit_plan_stream,
    draft_tool_plan_stream,
    fix_validation_errors,
    forge_google_search_context,
    generate_tool_code_stream,
    normalize_preview_screenshot,
    parse_generated_tool_response,
    repair_generated_tool_response,
    revise_preview_code,
    revise_tool_plan_stream,
    validate_test_code,
)
from tools_engine import (
    aload_dynamic_tools,
    alist_tool_summaries,
    delete_tool_async,
    execute_dynamic_tool,
    execute_skill_action,
    get_package_usage,
    is_interactive_skill,
    prepare_agent_messages,
    read_skill_data,
    read_tool_file,
    read_tool_manifest,
    read_tool_requirements,
    read_tool_test,
    resolve_skill_ui_file,
    skill_ui_entry_path,
    tool_exists,
    ui_content_type,
    validate_tool_schema,
    validate_manifest,
    validate_ui_files,
    write_skill_data,
    write_tool_files,
)
from tool_build_stream import stream_tool_build

configure_logging()
logger = logging.getLogger(__name__)

LITELLM_URL = os.environ.get("LITELLM_URL", "http://litellm:4000").rstrip("/")
LITELLM_MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "")
LITE_MODEL = (
    os.environ.get("LITE_MODEL", "").strip()
    or os.environ.get("CHAT_MODEL", "").strip()
)
TOOL_CREATOR_MODEL = (
    os.environ.get("TOOL_CREATOR_MODEL", "").strip()
    or os.environ.get("SECOND_MODEL", "").strip()
)
LITE_MODEL_REASONING_EFFORT = (
    os.environ.get("LITE_MODEL_REASONING_EFFORT", "low").strip() or None
)
TOOL_CREATOR_REASONING_EFFORT = (
    os.environ.get("TOOL_CREATOR_REASONING_EFFORT", "high").strip() or "high"
)
TOOL_RUNTIME_URL = os.environ.get("TOOL_RUNTIME_URL", "http://tool-runtime:8090").rstrip(
    "/"
)

STATIC_DIR = Path(__file__).parent / "static"
MAX_TOOL_ITERATIONS = 5
PLAN_TTL_SECONDS = 3600

PENDING_PLANS: dict[str, dict] = {}
RUN_CANCEL_FLAGS: set[str] = set()

app = FastAPI(title="Ada-SI Chat")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def startup_check() -> None:
    apply_secrets_to_environ()
    set_runtime_url(TOOL_RUNTIME_URL)
    runtime_ok, runtime_reason = await runtime_health()
    if runtime_ok:
        logger.info("Tool runtime is available at %s.", TOOL_RUNTIME_URL)
    else:
        logger.warning("Tool runtime unavailable: %s", runtime_reason)

    load_prompts_config(refresh=True)
    logger.info("Prompts config loaded from staging.")

    ensure_persona_layout()
    config = load_prompts_config()
    directives = config.get("scout_additional_directives", "")
    if migrate_scout_additional_directives(directives):
        save_prompts_config({**config, "scout_additional_directives": ""})
        logger.info("Migrated scout_additional_directives into USER.md.")

    asyncio.create_task(
        heartbeat_supervisor_loop(
            lite_model=LITE_MODEL,
            litellm_url=LITELLM_URL,
            litellm_headers_fn=litellm_headers,
            reasoning_effort=LITE_MODEL_REASONING_EFFORT,
        )
    )


def litellm_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if LITELLM_MASTER_KEY:
        headers["Authorization"] = f"Bearer {LITELLM_MASTER_KEY}"
    return headers


def cleanup_expired_plans() -> None:
    now = time.time()
    expired = [
        plan_id
        for plan_id, plan in PENDING_PLANS.items()
        if now - plan["created_at"] > PLAN_TTL_SECONDS
    ]
    for plan_id in expired:
        del PENDING_PLANS[plan_id]


def get_pending_plan(plan_id: str) -> dict:
    cleanup_expired_plans()
    plan = PENDING_PLANS.get(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found or expired.")
    return plan


def is_run_cancelled(run_id: str) -> bool:
    return bool(run_id and run_id in RUN_CANCEL_FLAGS)


def mark_run_cancelled(run_id: str) -> None:
    if run_id:
        RUN_CANCEL_FLAGS.add(run_id)


def clear_run_cancelled(run_id: str) -> None:
    RUN_CANCEL_FLAGS.discard(run_id)


def cancelled_events(run_id: str, step_id: str, *, model: str = "") -> list[str]:
    events = [
        process_step(run_id, step_id, "Stopped by user", "error"),
        sse_data({"ada_event": "run_cancelled", "run_id": run_id}),
        "data: [DONE]\n\n",
    ]
    if model:
        events[0] = process_step(
            run_id, step_id, "Stopped by user", "error", model=model
        )
    return events


def normalize_reasoning_effort(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned or cleaned in ("off", "none"):
        return "off"
    if cleaned in ("low", "medium", "high"):
        return cleaned
    return None


def resolve_reasoning_effort(
    value: str | None,
    *,
    default: str | None = None,
) -> str | None:
    normalized = normalize_reasoning_effort(value)
    if normalized is not None:
        return normalized
    fallback = default or LITE_MODEL_REASONING_EFFORT
    return normalize_reasoning_effort(fallback) or fallback


def resolve_gemini_google_search(payload: dict, model: str) -> bool:
    """True when the user enabled search and the given model is Gemini."""
    return bool(payload.get("gemini_google_search")) and is_gemini_model(model)


def resolve_tts_enabled(payload: dict) -> bool:
    return bool(payload.get("tts_enabled"))


async def stream_lite_model_turn(
    run_id: str,
    lite_model: str,
    working_messages: list[dict],
    tools: list[dict],
    *,
    reasoning_effort: str | None = None,
    gemini_google_search: bool = False,
):
    """Stream one lite-model completion; yield OpenAI SSE strings and final message."""
    chunk_id = new_stream_chunk_id()
    tool_calls_acc: dict[int, dict] = {}
    content_acc = ""
    reasoning_acc = ""
    saw_tool_call = False
    think_parser = ThinkStreamParser()
    search_sources_acc: dict[str, dict[str, str]] = {}

    log_debug(run_id, "LITE_MODEL", f"streaming completion model={lite_model}")

    async for chunk in stream_chat_completion(
        LITELLM_URL,
        litellm_headers(),
        lite_model,
        working_messages,
        tools=tools,
        reasoning_effort=reasoning_effort or LITE_MODEL_REASONING_EFFORT,
        gemini_google_search=gemini_google_search,
    ):
        if gemini_google_search:
            merge_search_sources(
                search_sources_acc,
                extract_search_sources_from_chunk(chunk),
            )

        tc_deltas = extract_stream_tool_calls(chunk)
        if tc_deltas:
            saw_tool_call = True
            merge_tool_call_delta(tool_calls_acc, tc_deltas)
            log_stream_delta(run_id, "lite_model", "tool_call_fragment", str(tc_deltas))

        delta = extract_stream_delta(chunk, think_parser=think_parser)
        if delta["reasoning"]:
            reasoning_acc += delta["reasoning"]
            log_stream_delta(run_id, "lite_model", "reasoning", delta["reasoning"])
            yield sse_data(
                openai_stream_chunk(
                    chunk_id=chunk_id,
                    reasoning=delta["reasoning"],
                )
            )
        if delta["content"]:
            content_acc += delta["content"]
            log_stream_delta(run_id, "lite_model", "content", delta["content"])
            if not saw_tool_call:
                yield sse_data(
                    openai_stream_chunk(
                        chunk_id=chunk_id,
                        content=delta["content"],
                    )
                )

    tool_calls = tool_calls_from_acc(tool_calls_acc)
    message: dict = {"role": "assistant", "content": content_acc or None}
    if tool_calls:
        message["tool_calls"] = tool_calls

    log_assistant_turn(
        run_id,
        model=lite_model,
        content=content_acc,
        reasoning=reasoning_acc,
        tool_calls=tool_calls,
    )

    if gemini_google_search:
        merge_search_sources(
            search_sources_acc,
            extract_search_sources_from_message(message),
        )
        if search_sources_acc:
            yield sse_data(
                {
                    "ada_event": "search_sources",
                    "run_id": run_id,
                    "sources": list(search_sources_acc.values()),
                }
            )

    yield sse_data(
        openai_stream_chunk(chunk_id=chunk_id, finish_reason="stop")
    )
    yield {"_event": "message", "message": message, "tool_calls": tool_calls}


def parse_tool_arguments(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Model returned invalid tool arguments: {raw}",
        ) from exc


def sse_data(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _batch_tag_payload(
    payload: dict,
    *,
    batch_id: str,
    plan_id: str,
    tool_name: str,
) -> dict:
    if not batch_id:
        return payload
    tagged = dict(payload)
    tagged["batch_id"] = batch_id
    tagged["plan_id"] = plan_id
    tagged["tool_name"] = tool_name
    return tagged


def _maybe_emit_batch_complete(batch_id: str, run_id: str) -> str | None:
    if not batch_id:
        return None
    try:
        batch_ref = get_pending_batch(batch_id)
    except ValueError:
        return None
    if not batch_terminal(batch_ref):
        return None
    batch_ref["status"] = "complete"
    return batch_sse(
        {
            "ada_event": "forge_batch_complete",
            "run_id": run_id,
            "summary": build_resume_summary(batch_ref),
        },
        batch_id=batch_id,
    )


def process_step(
    run_id: str,
    step_id: str,
    label: str,
    status: str,
    *,
    model: str = "",
    detail: str = "",
) -> str:
    return sse_data(
        {
            "ada_event": "process_step",
            "run_id": run_id,
            "step_id": step_id,
            "label": label,
            "status": status,
            "model": model,
            "detail": detail,
        }
    )


def tool_build_phase(
    run_id: str, phase: str, status: str, *, detail: str = ""
) -> str:
    return sse_data(
        {
            "ada_event": "tool_build_phase",
            "run_id": run_id,
            "phase": phase,
            "status": status,
            "detail": detail,
        }
    )


def tool_build_log(run_id: str, message: str, *, level: str = "info") -> str:
    return sse_data(
        {
            "ada_event": "tool_build_log",
            "run_id": run_id,
            "level": level,
            "message": message,
        }
    )


async def stream_plan_draft_events(
    run_id: str,
    tool_name: str,
    plan_stream,
    *,
    kind: str = "create",
    plan_id: str = "",
    out: dict | None = None,
):
    """Stream plan drafting; yield SSE strings. Accumulated plan is stored in out['plan']."""
    if out is None:
        out = {}
    out["plan"] = ""

    started = {
        "ada_event": "tool_plan_draft_started",
        "run_id": run_id,
        "tool_name": tool_name,
        "kind": kind,
    }
    if plan_id:
        started["plan_id"] = plan_id
    yield sse_data(started)

    async for chunk_kind, delta in plan_stream:
        if chunk_kind == "reasoning":
            yield sse_data(
                {
                    "ada_event": "tool_plan_thinking_delta",
                    "run_id": run_id,
                    "delta": delta,
                }
            )
        elif chunk_kind == "content":
            out["plan"] += delta
            yield sse_data(
                {
                    "ada_event": "tool_plan_content_delta",
                    "run_id": run_id,
                    "delta": delta,
                }
            )


async def run_agent_stream(
    run_id: str,
    lite_model: str,
    tool_creator_model: str,
    messages: list[dict],
    request: Request,
    *,
    reasoning_effort: str | None = None,
    gemini_google_search: bool = False,
    forge_gemini_google_search: bool = False,
    tts_enabled: bool = False,
):
    """Async generator that yields SSE strings as each process step occurs."""
    clear_run_cancelled(run_id)
    yield process_step(
        run_id, "lite_model", "Lite model processing", "active", model=lite_model
    )

    tools = await aload_dynamic_tools()
    working_messages = prepare_agent_messages(messages, tts_enabled=tts_enabled)
    tool_names = [
        (t.get("function") or t).get("name", "?") for t in tools
    ]
    log_chat_request(
        run_id,
        lite_model=lite_model,
        tool_creator_model=tool_creator_model,
        message_count=len(working_messages),
        tool_names=tool_names,
    )

    for iteration in range(MAX_TOOL_ITERATIONS):
        log_debug(run_id, "AGENT", f"iteration {iteration + 1}/{MAX_TOOL_ITERATIONS}")
        if is_run_cancelled(run_id) or await request.is_disconnected():
            for event in cancelled_events(run_id, "lite_model", model=lite_model):
                yield event
            return

        message = None
        tool_calls: list[dict] = []

        async for item in stream_lite_model_turn(
            run_id,
            lite_model,
            working_messages,
            tools,
            reasoning_effort=reasoning_effort,
            gemini_google_search=gemini_google_search,
        ):
            if isinstance(item, str):
                yield item
                continue
            if item.get("_event") == "message":
                message = item["message"]
                tool_calls = item["tool_calls"]

        if message is None:
            raise HTTPException(status_code=502, detail="LiteLLM returned no response.")

        if tool_calls:
            yield process_step(
                run_id, "lite_model", "Lite model processing", "done", model=lite_model
            )
            working_messages.append(message)

            for tool_call in tool_calls:
                if is_run_cancelled(run_id) or await request.is_disconnected():
                    for event in cancelled_events(run_id, "lite_model", model=lite_model):
                        yield event
                    return

                fn = tool_call.get("function", {})
                name = fn.get("name", "")
                args = parse_tool_arguments(fn.get("arguments", "{}"))

                if name == "propose_tool_batch":
                    tools_raw = args.get("tools", [])
                    summary = str(args.get("summary", "")).strip()
                    log_tool_execution(
                        run_id,
                        name=name,
                        arguments=args,
                        result="(proposing multi-tool batch)",
                    )
                    if not summary:
                        raise HTTPException(
                            status_code=502,
                            detail="propose_tool_batch missing summary.",
                        )
                    if not tool_creator_model:
                        raise HTTPException(
                            status_code=400,
                            detail="No tool creator model configured. Select one in the UI.",
                        )
                    try:
                        tools = validate_batch_tools(tools_raw, tool_exists=tool_exists)
                    except ValueError as exc:
                        raise HTTPException(status_code=502, detail=str(exc)) from exc

                    batch_id, batch = create_batch(
                        run_id=run_id,
                        tools=tools,
                        summary=summary,
                        creator_model=tool_creator_model,
                        reasoning_effort=reasoning_effort,
                    )
                    yield process_step(
                        run_id,
                        "route_creator",
                        "Proposed multi-tool forge batch",
                        "done",
                        model=tool_creator_model,
                        detail=f"{len(tools)} tools",
                    )
                    yield {
                        "_event": "forge_batch_proposed",
                        "batch_id": batch_id,
                        "run_id": run_id,
                        "summary": summary,
                        "tools": [
                            {
                                "tool_name": entry["tool_name"],
                                "description": entry["description"],
                                "plan_id": entry["plan_id"],
                            }
                            for entry in batch["tools"]
                        ],
                    }
                    return

                if name == "generate_new_tool":
                    tool_name = args.get("tool_name", "").strip()
                    description = args.get("description", "").strip()
                    log_tool_execution(
                        run_id,
                        name=name,
                        arguments=args,
                        result="(routing to tool creator)",
                    )
                    if not tool_name or not description:
                        raise HTTPException(
                            status_code=502,
                            detail="generate_new_tool missing tool_name or description.",
                        )
                    if not tool_creator_model:
                        raise HTTPException(
                            status_code=400,
                            detail="No tool creator model configured. Select one in the UI.",
                        )

                    yield process_step(
                        run_id,
                        "route_creator",
                        "Routed to tool creator",
                        "active",
                        model=tool_creator_model,
                    )
                    yield process_step(
                        run_id,
                        "route_creator",
                        "Routed to tool creator",
                        "done",
                        model=tool_creator_model,
                    )
                    yield process_step(
                        run_id,
                        "plan_draft",
                        "Drafting tool plan",
                        "active",
                        model=tool_creator_model,
                    )

                    if is_run_cancelled(run_id) or await request.is_disconnected():
                        for event in cancelled_events(
                            run_id, "plan_draft", model=tool_creator_model
                        ):
                            yield event
                        return

                    plan_out: dict[str, str] = {}
                    with forge_google_search_context(forge_gemini_google_search):
                        async for event in stream_plan_draft_events(
                            run_id,
                            tool_name,
                            draft_tool_plan_stream(
                                tool_name,
                                description,
                                tool_creator_model,
                                litellm_url=LITELLM_URL,
                                headers=litellm_headers(),
                                run_id=run_id,
                                reasoning_effort=reasoning_effort,
                            ),
                            kind="create",
                            out=plan_out,
                        ):
                            yield event
                    plan = plan_out.get("plan", "")
                    log_plan(run_id, tool_name=tool_name, plan=plan, action="drafted")

                    if is_run_cancelled(run_id) or await request.is_disconnected():
                        for event in cancelled_events(
                            run_id, "plan_draft", model=tool_creator_model
                        ):
                            yield event
                        return

                    yield process_step(
                        run_id,
                        "plan_draft",
                        "Drafting tool plan",
                        "done",
                        model=tool_creator_model,
                    )
                    yield process_step(
                        run_id,
                        "plan_ready",
                        "Plan ready for approval",
                        "done",
                        detail=tool_name,
                    )
                    yield process_step(
                        run_id,
                        "awaiting_approval",
                        "Awaiting your approval",
                        "active",
                        detail=tool_name,
                    )

                    plan_id = uuid.uuid4().hex
                    PENDING_PLANS[plan_id] = {
                        "tool_name": tool_name,
                        "description": description,
                        "plan": plan,
                        "creator_model": tool_creator_model,
                        "created_at": time.time(),
                        "run_id": run_id,
                    }
                    yield {
                        "_event": "plan",
                        "plan_id": plan_id,
                        "run_id": run_id,
                        "tool_name": tool_name,
                        "plan": plan,
                        "kind": "create",
                    }
                    return

                if name == "edit_existing_tool":
                    tool_name = args.get("tool_name", "").strip()
                    description = args.get("description", "").strip()
                    log_tool_execution(
                        run_id,
                        name=name,
                        arguments=args,
                        result="(routing to tool editor)",
                    )
                    if not tool_name or not description:
                        raise HTTPException(
                            status_code=502,
                            detail="edit_existing_tool missing tool_name or description.",
                        )
                    if not tool_exists(tool_name):
                        raise HTTPException(
                            status_code=404,
                            detail=f"Tool '{tool_name}' is not installed.",
                        )
                    if not tool_creator_model:
                        raise HTTPException(
                            status_code=400,
                            detail="No tool creator model configured. Select one in the UI.",
                        )

                    existing_code = read_tool_file(tool_name)
                    existing_reqs = read_tool_requirements(tool_name)
                    existing_test = read_tool_test(tool_name)
                    existing_manifest = read_tool_manifest(tool_name)

                    yield process_step(
                        run_id,
                        "route_creator",
                        "Routed to tool editor",
                        "active",
                        model=tool_creator_model,
                    )
                    yield process_step(
                        run_id,
                        "route_creator",
                        "Routed to tool editor",
                        "done",
                        model=tool_creator_model,
                    )
                    yield process_step(
                        run_id,
                        "plan_draft",
                        "Drafting tool edit plan",
                        "active",
                        model=tool_creator_model,
                    )

                    plan_out: dict[str, str] = {}
                    with forge_google_search_context(forge_gemini_google_search):
                        async for event in stream_plan_draft_events(
                            run_id,
                            tool_name,
                            draft_tool_edit_plan_stream(
                                tool_name,
                                description,
                                existing_code,
                                existing_reqs,
                                tool_creator_model,
                                litellm_url=LITELLM_URL,
                                headers=litellm_headers(),
                                run_id=run_id,
                                existing_manifest=existing_manifest,
                                reasoning_effort=reasoning_effort,
                            ),
                            kind="edit",
                            out=plan_out,
                        ):
                            yield event
                    plan = plan_out.get("plan", "")
                    log_plan(run_id, tool_name=tool_name, plan=plan, action="edit_drafted")

                    yield process_step(
                        run_id,
                        "plan_draft",
                        "Drafting tool edit plan",
                        "done",
                        model=tool_creator_model,
                    )
                    yield process_step(
                        run_id,
                        "plan_ready",
                        "Edit plan ready for approval",
                        "done",
                        detail=tool_name,
                    )
                    yield process_step(
                        run_id,
                        "awaiting_approval",
                        "Awaiting your approval",
                        "active",
                        detail=tool_name,
                    )

                    plan_id = uuid.uuid4().hex
                    PENDING_PLANS[plan_id] = {
                        "kind": "edit",
                        "tool_name": tool_name,
                        "description": description,
                        "plan": plan,
                        "creator_model": tool_creator_model,
                        "created_at": time.time(),
                        "run_id": run_id,
                        "edit_context": {
                            "tool_code": existing_code,
                            "requirements": existing_reqs,
                            "test_code": existing_test,
                            "manifest": existing_manifest,
                        },
                    }
                    yield {
                        "_event": "plan",
                        "plan_id": plan_id,
                        "run_id": run_id,
                        "tool_name": tool_name,
                        "plan": plan,
                        "kind": "edit",
                    }
                    return

                if name == "open_skill_app":
                    skill_name = args.get("skill_name", "").strip()
                    log_tool_execution(
                        run_id,
                        name=name,
                        arguments=args,
                        result="(opening skill app)",
                    )
                    yield process_step(
                        run_id,
                        "tool_execute",
                        f"Opening skill app: {skill_name or '?'}",
                        "active",
                        detail=skill_name,
                    )
                    if not skill_name:
                        result = "open_skill_app missing skill_name."
                        yield process_step(
                            run_id,
                            "tool_execute",
                            "Opening skill app",
                            "error",
                            detail=result,
                        )
                    elif not tool_exists(skill_name):
                        result = f"Skill '{skill_name}' is not installed."
                        yield process_step(
                            run_id,
                            "tool_execute",
                            f"Opening skill app: {skill_name}",
                            "error",
                            detail=result,
                        )
                    elif not is_interactive_skill(skill_name):
                        result = (
                            f"Skill '{skill_name}' is not interactive. "
                            "Only interactive skills can be opened as apps."
                        )
                        yield process_step(
                            run_id,
                            "tool_execute",
                            f"Opening skill app: {skill_name}",
                            "error",
                            detail=result,
                        )
                    else:
                        yield {
                            "_event": "open_skill_app",
                            "run_id": run_id,
                            "skill_name": skill_name,
                        }
                        result = f"Opened {skill_name} in the skill app viewer."
                        yield process_step(
                            run_id,
                            "tool_execute",
                            f"Opening skill app: {skill_name}",
                            "done",
                            detail=skill_name,
                        )
                    working_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": result,
                        }
                    )
                    continue

                if name in PERSONA_TOOL_NAMES:
                    yield process_step(
                        run_id,
                        "tool_execute",
                        f"Persona tool: {name}",
                        "active",
                        detail=name,
                    )
                    result_dict = execute_persona_tool(name, args)
                    result = json.dumps(result_dict)
                    log_tool_execution(
                        run_id, name=name, arguments=args, result=result
                    )
                    yield process_step(
                        run_id,
                        "tool_execute",
                        f"Persona tool: {name}",
                        "done" if result_dict.get("ok") else "error",
                        detail=name,
                    )
                    if result_dict.get("ok"):
                        yield {
                            "_event": "persona_updated",
                            "run_id": run_id,
                            "tool": name,
                            "display_name": result_dict.get("display_name")
                            or parse_identity_display_name(),
                        }
                    working_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": result,
                        }
                    )
                    continue

                yield process_step(
                    run_id,
                    "tool_execute",
                    f"Executing tool: {name}",
                    "active",
                    detail=name,
                )

                try:
                    result = await execute_dynamic_tool(name, args, run_id=run_id)
                    log_tool_execution(
                        run_id, name=name, arguments=args, result=result
                    )
                    yield process_step(
                        run_id,
                        "tool_execute",
                        f"Executing tool: {name}",
                        "done",
                        detail=name,
                    )
                    if is_interactive_skill(name):
                        yield {
                            "_event": "skill_data_changed",
                            "run_id": run_id,
                            "skill_name": name,
                        }
                except Exception as exc:
                    result = f"Tool execution failed: {exc}"
                    log_tool_execution(
                        run_id,
                        name=name,
                        arguments=args,
                        result="",
                        error=str(exc),
                    )
                    yield process_step(
                        run_id,
                        "tool_execute",
                        f"Executing tool: {name}",
                        "error",
                        detail=str(exc),
                    )

                working_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": result,
                    }
                )

            yield process_step(
                run_id, "lite_model", "Lite model processing", "active", model=lite_model
            )
            continue

        yield process_step(
            run_id, "lite_model", "Lite model responded", "done", model=lite_model
        )
        yield {"_event": "done"}
        return

    raise HTTPException(
        status_code=502,
        detail=f"Exceeded maximum tool iterations ({MAX_TOOL_ITERATIONS}).",
    )


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
async def get_config() -> dict:
    return {
        "lite_model": LITE_MODEL,
        "tool_creator_model": TOOL_CREATOR_MODEL,
        "chat_model": LITE_MODEL,
        "second_model": TOOL_CREATOR_MODEL,
        "tools": await alist_tool_summaries(),
        "tool_runtime_available": (await runtime_health())[0],
        "tool_runtime_url": TOOL_RUNTIME_URL,
        "lite_model_reasoning_effort": LITE_MODEL_REASONING_EFFORT,
        "tool_creator_reasoning_effort": TOOL_CREATOR_REASONING_EFFORT,
    }


@app.get("/api/prompts")
async def get_prompts() -> dict:
    return prompts_config_response()


@app.put("/api/prompts")
async def update_prompts(payload: dict = Body(...)) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
    prompts = payload.get("prompts", payload)
    if not isinstance(prompts, dict):
        raise HTTPException(status_code=400, detail="Expected a prompts object.")
    unknown = [key for key in prompts if key not in PROMPT_KEYS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown prompt keys: {', '.join(unknown)}",
        )
    save_prompts_config({**load_prompts_config(), **prompts})
    return prompts_config_response()


@app.post("/api/prompts/reset")
async def reset_prompts() -> dict:
    reset_prompts_config()
    return prompts_config_response()


@app.get("/api/persona")
async def get_persona() -> dict:
    return persona_api_response()


@app.get("/api/persona/status")
async def get_persona_status() -> dict:
    return persona_status()


@app.put("/api/persona")
async def update_persona(payload: dict = Body(...)) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
    file_key = payload.get("file", "")
    content = payload.get("content")
    if not isinstance(content, str):
        raise HTTPException(status_code=400, detail="content must be a string.")
    parsed = parse_persona_api_file(str(file_key))
    if parsed is None:
        raise HTTPException(
            status_code=400,
            detail="file must be one of: agents, soul, identity, user, tools, memory, heartbeat",
        )
    write_persona_markdown(parsed, content)
    return persona_api_response()


@app.post("/api/persona/reset")
async def reset_persona() -> dict:
    reset_persona_markdown_to_templates()
    return persona_api_response()


@app.post("/api/persona/bootstrap")
async def bootstrap_persona() -> dict:
    result = start_bootstrap_ritual()
    return {**persona_api_response(), **result}


@app.put("/api/persona/config")
async def update_persona_config(payload: dict = Body(...)) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
    allowed = {"heartbeat_enabled", "heartbeat_interval_minutes"}
    updates = {k: v for k, v in payload.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid config keys provided.")
    save_persona_config(updates)
    return persona_api_response()


@app.get("/api/secrets")
async def get_secrets() -> dict:
    return {"secrets": secrets_status_response()}


@app.put("/api/secrets")
async def update_secrets(payload: dict = Body(...)) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
    updates = payload.get("secrets", payload)
    if not isinstance(updates, dict):
        raise HTTPException(status_code=400, detail="Expected a secrets object.")
    unknown = [key for key in updates if key not in SUPPORTED_SECRET_KEYS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown secret keys: {', '.join(unknown)}",
        )
    try:
        normalized = {str(key): str(value) for key, value in updates.items()}
        save_secrets_raw(normalized)
        apply_secrets_to_environ()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"secrets": secrets_status_response()}


@app.delete("/api/secrets/{key_name}")
async def remove_secret(key_name: str) -> dict:
    if key_name not in SUPPORTED_SECRET_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown secret key: {key_name}")
    clear_secret(key_name)
    apply_secrets_to_environ()
    return {"secrets": secrets_status_response()}


@app.post("/api/tts")
async def text_to_speech(payload: dict = Body(...)) -> Response:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
    text = payload.get("text", "")
    voice_id = payload.get("voice_id")
    try:
        audio = await synthesize_speech(text, voice_id=voice_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/api/tts/stream")
async def text_to_speech_stream(payload: dict = Body(...)) -> StreamingResponse:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
    text = payload.get("text", "")
    voice_id = payload.get("voice_id")
    try:
        audio_stream = stream_speech(text, voice_id=voice_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def audio_iter():
        async for chunk in audio_stream:
            yield chunk

    return StreamingResponse(audio_iter(), media_type="audio/mpeg")


@app.get("/api/tts/voices")
async def get_tts_voices() -> dict:
    try:
        voices = await list_voices()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"voices": voices}


@app.get("/api/forger-guidance")
async def get_forger_guidance() -> dict:
    config = load_prompts_config()
    return {"forger_runtime_context": config["forge_runtime_context"]}


@app.put("/api/forger-guidance")
async def update_forger_guidance(payload: dict = Body(...)) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
    mapped = {"forge_runtime_context": payload.get("forger_runtime_context", "")}
    save_prompts_config({**load_prompts_config(), **mapped})
    return await get_forger_guidance()


@app.post("/api/forger-guidance/reset")
async def reset_forger_guidance() -> dict:
    import importlib
    import prompts_config as pc_mod

    pc_mod = importlib.reload(pc_mod)
    save_prompts_config(
        {
            **load_prompts_config(refresh=True),
            "forge_runtime_context": pc_mod.default_prompts_config()[
                "forge_runtime_context"
            ],
        }
    )
    return await get_forger_guidance()


@app.get("/api/tools")
async def list_tools() -> dict:
    return {"tools": await alist_tool_summaries()}


@app.delete("/api/tools/{tool_name}")
async def remove_tool(tool_name: str) -> dict:
    try:
        await delete_tool_async(tool_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "deleted", "tool_name": tool_name}


SKILL_UI_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'"
)


@app.get("/api/skills/{skill_name}/ui")
async def get_skill_ui_entry(skill_name: str) -> FileResponse:
    if not tool_exists(skill_name):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found.")
    if not is_interactive_skill(skill_name):
        raise HTTPException(
            status_code=400,
            detail=f"Skill '{skill_name}' is not an interactive skill.",
        )
    entry = skill_ui_entry_path(skill_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Custom UI entry not found.")
    return FileResponse(
        entry,
        media_type=ui_content_type(entry),
        headers={"Content-Security-Policy": SKILL_UI_CSP},
    )


@app.get("/api/skills/{skill_name}/ui/{file_path:path}")
async def get_skill_ui_file(skill_name: str, file_path: str) -> FileResponse:
    if not tool_exists(skill_name):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found.")
    if not is_interactive_skill(skill_name):
        raise HTTPException(
            status_code=400,
            detail=f"Skill '{skill_name}' is not an interactive skill.",
        )
    resolved = resolve_skill_ui_file(skill_name, file_path)
    if resolved is None:
        raise HTTPException(status_code=404, detail="UI file not found.")
    return FileResponse(
        resolved,
        media_type=ui_content_type(resolved),
        headers={"Content-Security-Policy": SKILL_UI_CSP},
    )


@app.post("/api/skills/{skill_name}/action")
async def post_skill_action(skill_name: str, payload: dict = Body(...)) -> dict:
    if not tool_exists(skill_name):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
    try:
        return await execute_skill_action(skill_name, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail={"ok": False, "error": str(exc)}) from exc


@app.get("/api/skills/{skill_name}/data")
async def get_skill_data(skill_name: str) -> dict:
    if not tool_exists(skill_name):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found.")
    if not is_interactive_skill(skill_name):
        raise HTTPException(
            status_code=400,
            detail=f"Skill '{skill_name}' is not an interactive skill.",
        )
    try:
        return read_skill_data(skill_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/skills/{skill_name}/data")
async def put_skill_data(skill_name: str, payload: dict = Body(...)) -> dict:
    if not tool_exists(skill_name):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found.")
    if not is_interactive_skill(skill_name):
        raise HTTPException(
            status_code=400,
            detail=f"Skill '{skill_name}' is not an interactive skill.",
        )
    raise HTTPException(
        status_code=400,
        detail=(
            "Direct skill data writes are disabled. "
            f"Use POST /api/skills/{skill_name}/action instead."
        ),
    )


def _attach_package_usage(packages: list[dict]) -> list[dict]:
    usage = get_package_usage()
    enriched: list[dict] = []
    for pkg in packages:
        name = (pkg.get("name") or "").lower()
        enriched.append({**pkg, "used_by": usage.get(name, [])})
    return enriched


@app.get("/api/pip/packages")
async def list_pip_packages() -> dict:
    try:
        packages = await runtime_list_pip_packages()
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Tool runtime unreachable: {exc}",
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    return {"packages": _attach_package_usage(packages)}


@app.delete("/api/pip/packages/{package_name}")
async def uninstall_pip_package(package_name: str) -> dict:
    name = package_name.strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Package name is required.")

    usage = get_package_usage()
    dependents = usage.get(name, [])
    if dependents:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"Package '{name}' is required by installed tools.",
                "used_by": dependents,
            },
        )

    try:
        packages = await runtime_uninstall_pip_package(name)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Tool runtime unreachable: {exc}",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"status": "deleted", "package_name": name, "packages": _attach_package_usage(packages)}


@app.get("/api/models")
async def list_models() -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        for path in ("/v1/models", "/models"):
            response = await client.get(f"{LITELLM_URL}{path}", headers=litellm_headers())
            if response.status_code == 200:
                return response.json()

        raise HTTPException(
            status_code=response.status_code,
            detail=response.text or "Failed to fetch models from LiteLLM",
        )


@app.post("/api/chat")
async def chat(request: Request) -> StreamingResponse:
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from exc

    lite_model = (body.get("model") or LITE_MODEL).strip()
    tool_creator_model = (
        body.get("tool_creator_model") or TOOL_CREATOR_MODEL
    ).strip()
    messages = body.get("messages")
    run_id = body.get("run_id") or uuid.uuid4().hex
    reasoning_effort = resolve_reasoning_effort(body.get("reasoning_effort"))
    gemini_google_search = resolve_gemini_google_search(body, lite_model)
    forge_gemini_google_search = resolve_gemini_google_search(body, tool_creator_model)
    tts_enabled = resolve_tts_enabled(body)
    bootstrap_opening = bool(body.get("bootstrap_opening"))

    if not lite_model:
        raise HTTPException(status_code=400, detail="No lite model selected.")

    if bootstrap_opening:
        if not read_bootstrap_markdown().strip():
            raise HTTPException(
                status_code=400,
                detail="Bootstrap ritual is not active. Start it from Persona settings first.",
            )
        messages = [{"role": "user", "content": BOOTSTRAP_OPENING_TRIGGER}]
    elif not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="messages must be a non-empty list.")

    async def event_stream():
        async for chunk in stream_agent_sse(
            run_id=run_id,
            lite_model=lite_model,
            tool_creator_model=tool_creator_model,
            messages=messages,
            request=request,
            reasoning_effort=reasoning_effort,
            gemini_google_search=gemini_google_search,
            forge_gemini_google_search=forge_gemini_google_search,
            tts_enabled=tts_enabled,
        ):
            yield chunk

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=SSE_HEADERS
    )


async def stream_agent_sse(
    *,
    run_id: str,
    lite_model: str,
    tool_creator_model: str,
    messages: list[dict],
    request: Request,
    reasoning_effort: str | None,
    gemini_google_search: bool = False,
    forge_gemini_google_search: bool = False,
    tts_enabled: bool = False,
):
    """Yield SSE chunks from a Scout agent run (shared by chat and resume endpoints)."""
    try:
        async for item in run_agent_stream(
            run_id,
            lite_model,
            tool_creator_model,
            messages,
            request,
            reasoning_effort=reasoning_effort,
            gemini_google_search=gemini_google_search,
            forge_gemini_google_search=forge_gemini_google_search,
            tts_enabled=tts_enabled,
        ):
            if await request.is_disconnected():
                return

            if isinstance(item, str):
                yield item
                continue

            if item.get("_event") == "plan":
                yield sse_data(
                    {
                        "ada_event": "tool_plan_pending",
                        "run_id": item["run_id"],
                        "plan_id": item["plan_id"],
                        "tool_name": item["tool_name"],
                        "plan": item["plan"],
                        "kind": item.get("kind", "create"),
                    }
                )
                yield "data: [DONE]\n\n"
                return

            if item.get("_event") == "forge_batch_proposed":
                yield sse_data(
                    {
                        "ada_event": "forge_batch_proposed",
                        "run_id": item["run_id"],
                        "batch_id": item["batch_id"],
                        "summary": item["summary"],
                        "tools": item["tools"],
                    }
                )
                yield "data: [DONE]\n\n"
                return

            if item.get("_event") == "done":
                yield "data: [DONE]\n\n"
                return

            if item.get("_event") == "open_skill_app":
                yield sse_data(
                    {
                        "ada_event": "open_skill_app",
                        "run_id": item["run_id"],
                        "skill_name": item["skill_name"],
                    }
                )
                continue

            if item.get("_event") == "skill_data_changed":
                yield sse_data(
                    {
                        "ada_event": "skill_data_changed",
                        "run_id": item["run_id"],
                        "skill_name": item["skill_name"],
                    }
                )
                continue

            if item.get("_event") == "persona_updated":
                yield sse_data(
                    {
                        "ada_event": "persona_updated",
                        "run_id": item["run_id"],
                        "tool": item.get("tool", ""),
                        "display_name": item.get("display_name", ""),
                    }
                )
                continue
    except HTTPException as exc:
        log_error(run_id, "CHAT", f"HTTPException: {exc.detail}")
        yield process_step(
            run_id,
            "lite_model",
            "Request failed",
            "error",
            detail=str(exc.detail),
        )
        yield sse_data({"ada_event": "chat_error", "run_id": run_id, "detail": exc.detail})
        yield "data: [DONE]\n\n"
    except httpx.RequestError as exc:
        detail = f"LiteLLM unreachable: {exc}"
        log_error(run_id, "CHAT", detail)
        yield process_step(run_id, "lite_model", "Request failed", "error", detail=detail)
        yield sse_data({"ada_event": "chat_error", "run_id": run_id, "detail": detail})
        yield "data: [DONE]\n\n"
    except RuntimeError as exc:
        log_error(run_id, "CHAT", str(exc))
        yield process_step(run_id, "lite_model", "Request failed", "error", detail=str(exc))
        yield sse_data({"ada_event": "chat_error", "run_id": run_id, "detail": str(exc)})
        yield "data: [DONE]\n\n"


@app.post("/api/resume_scout")
async def resume_scout(request: Request, payload: dict = Body(...)) -> StreamingResponse:
    lite_model = (payload.get("model") or LITE_MODEL).strip()
    tool_creator_model = (
        payload.get("tool_creator_model") or TOOL_CREATOR_MODEL
    ).strip()
    messages = payload.get("messages")
    run_id = payload.get("run_id", "").strip() or uuid.uuid4().hex
    reasoning_effort = resolve_reasoning_effort(payload.get("reasoning_effort"))
    gemini_google_search = resolve_gemini_google_search(payload, lite_model)
    forge_gemini_google_search = resolve_gemini_google_search(payload, tool_creator_model)
    tts_enabled = resolve_tts_enabled(payload)
    tool_name = payload.get("tool_name", "").strip()
    install_message = payload.get("message", "").strip()
    context = payload.get("context", "").strip()

    if not lite_model:
        raise HTTPException(status_code=400, detail="No lite model selected.")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="messages must be a non-empty list.")
    if not context:
        if not tool_name:
            raise HTTPException(
                status_code=400,
                detail="tool_name or context is required.",
            )
        context = build_single_tool_scout_resume_message(tool_name, install_message)

    resume_messages = [*messages, {"role": "user", "content": context}]

    async def event_stream():
        async for chunk in stream_agent_sse(
            run_id=run_id,
            lite_model=lite_model,
            tool_creator_model=tool_creator_model,
            messages=resume_messages,
            request=request,
            reasoning_effort=reasoning_effort,
            gemini_google_search=gemini_google_search,
            forge_gemini_google_search=forge_gemini_google_search,
            tts_enabled=tts_enabled,
        ):
            yield chunk

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=SSE_HEADERS
    )


@app.post("/api/cancel_run")
async def cancel_run(payload: dict = Body(...)) -> dict:
    run_id = payload.get("run_id", "").strip()
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id is required.")
    mark_run_cancelled(run_id)
    log_debug(run_id, "CANCEL", "run cancelled by user")
    return {"status": "cancelled", "run_id": run_id}


@app.post("/api/approve_tool")
async def approve_tool(request: Request, payload: dict = Body(...)) -> StreamingResponse:
    plan_id = payload.get("plan_id", "").strip()
    run_id = payload.get("run_id", "").strip()
    if not plan_id:
        raise HTTPException(status_code=400, detail="plan_id is required.")

    plan_data = get_pending_plan(plan_id)
    tool_name = plan_data["tool_name"]
    creator_model = (
        payload.get("tool_creator_model") or plan_data["creator_model"]
    ).strip()
    run_id = run_id or plan_data.get("run_id", "")

    if not creator_model:
        raise HTTPException(status_code=400, detail="No tool creator model configured.")

    reasoning_effort = resolve_reasoning_effort(
        payload.get("reasoning_effort"),
        default=TOOL_CREATOR_REASONING_EFFORT,
    )

    async def approval_stream():
        with forge_google_search_context(
            resolve_gemini_google_search(payload, creator_model)
        ):
            async for event in stream_tool_build(
                plan_id=plan_id,
                plan_data=plan_data,
                run_id=run_id,
                creator_model=creator_model,
                reasoning_effort=reasoning_effort,
                request=request,
                litellm_url=LITELLM_URL,
                litellm_headers=litellm_headers(),
                pending_plans=PENDING_PLANS,
                process_step=process_step,
                tool_build_phase=tool_build_phase,
                tool_build_log=tool_build_log,
                sse_data=sse_data,
                cancelled_events=cancelled_events,
                is_run_cancelled=is_run_cancelled,
                clear_run_cancelled=clear_run_cancelled,
            ):
                yield event

    return StreamingResponse(
        approval_stream(), media_type="text/event-stream", headers=SSE_HEADERS
    )


@app.post("/api/forge_batch/confirm")
async def forge_batch_confirm(request: Request, payload: dict = Body(...)) -> StreamingResponse:
    batch_id = payload.get("batch_id", "").strip()
    if not batch_id:
        raise HTTPException(status_code=400, detail="batch_id is required.")

    try:
        batch = get_pending_batch(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if batch.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="Batch was cancelled.")

    creator_model = batch["creator_model"]
    forge_search = resolve_gemini_google_search(payload, creator_model)

    async def confirm_stream():
        with forge_google_search_context(forge_search):
            async def cancelled() -> bool:
                return is_run_cancelled(batch["run_id"]) or await request.is_disconnected()

            async for event in stream_parallel_plan_phase(
                batch_id=batch_id,
                litellm_url=LITELLM_URL,
                headers=litellm_headers(),
                pending_plans=PENDING_PLANS,
                cancelled=cancelled,
            ):
                yield event
        yield "data: [DONE]\n\n"

    return StreamingResponse(confirm_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/forge_batch/cancel")
async def forge_batch_cancel(payload: dict = Body(...)) -> dict:
    batch_id = payload.get("batch_id", "").strip()
    if not batch_id:
        raise HTTPException(status_code=400, detail="batch_id is required.")
    try:
        cancel_batch(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "cancelled", "batch_id": batch_id}


@app.post("/api/forge_batch/approve_plan")
async def forge_batch_approve_plan(payload: dict = Body(...)) -> dict:
    batch_id = payload.get("batch_id", "").strip()
    plan_id = payload.get("plan_id", "").strip()
    if not batch_id or not plan_id:
        raise HTTPException(status_code=400, detail="batch_id and plan_id are required.")
    try:
        approve_plan(batch_id, plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "approved", "batch_id": batch_id, "plan_id": plan_id}


@app.post("/api/forge_batch/approve_all_plans")
async def forge_batch_approve_all_plans(payload: dict = Body(...)) -> dict:
    batch_id = payload.get("batch_id", "").strip()
    if not batch_id:
        raise HTTPException(status_code=400, detail="batch_id is required.")
    try:
        approve_all_plans(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "approved_all", "batch_id": batch_id}


@app.post("/api/forge_batch/reject_plan")
async def forge_batch_reject_plan(payload: dict = Body(...)) -> dict:
    batch_id = payload.get("batch_id", "").strip()
    plan_id = payload.get("plan_id", "").strip()
    if not batch_id or not plan_id:
        raise HTTPException(status_code=400, detail="batch_id and plan_id are required.")
    try:
        reject_plan(batch_id, plan_id)
        if plan_id in PENDING_PLANS:
            del PENDING_PLANS[plan_id]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "skipped", "batch_id": batch_id, "plan_id": plan_id}


@app.post("/api/forge_batch/revise_plan")
async def forge_batch_revise_plan(request: Request, payload: dict = Body(...)) -> StreamingResponse:
    batch_id = payload.get("batch_id", "").strip()
    plan_id = payload.get("plan_id", "").strip()
    feedback = payload.get("feedback", "").strip()
    if not batch_id or not plan_id:
        raise HTTPException(status_code=400, detail="batch_id and plan_id are required.")
    if not feedback:
        raise HTTPException(status_code=400, detail="feedback is required.")

    try:
        batch = get_pending_batch(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    creator_model = batch["creator_model"]
    forge_search = resolve_gemini_google_search(payload, creator_model)

    async def revise_stream():
        with forge_google_search_context(forge_search):
            async def cancelled() -> bool:
                return is_run_cancelled(batch["run_id"]) or await request.is_disconnected()

            try:
                async for event in stream_batch_plan_revision(
                    batch_id=batch_id,
                    plan_id=plan_id,
                    feedback=feedback,
                    litellm_url=LITELLM_URL,
                    headers=litellm_headers(),
                    pending_plans=PENDING_PLANS,
                    cancelled=cancelled,
                ):
                    yield event
            except ValueError as exc:
                yield batch_sse(
                    {
                        "ada_event": "forge_batch_plan_failed",
                        "run_id": batch["run_id"],
                        "reason": str(exc),
                    },
                    batch_id=batch_id,
                    plan_id=plan_id,
                )
        yield "data: [DONE]\n\n"

    return StreamingResponse(revise_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/forge_batch/start_build")
async def forge_batch_start_build(request: Request, payload: dict = Body(...)) -> StreamingResponse:
    batch_id = payload.get("batch_id", "").strip()
    plan_id = payload.get("plan_id", "").strip() or None
    if not batch_id:
        raise HTTPException(status_code=400, detail="batch_id is required.")

    try:
        batch = get_pending_batch(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        plan_ids = plan_ids_ready_to_build(batch, plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    creator_model = (
        payload.get("tool_creator_model") or batch["creator_model"]
    ).strip()
    if not creator_model:
        raise HTTPException(status_code=400, detail="No tool creator model configured.")

    reasoning_effort = resolve_reasoning_effort(
        payload.get("reasoning_effort"),
        default=TOOL_CREATOR_REASONING_EFFORT,
    )
    run_id = batch["run_id"]

    def on_installed(pid: str, tool_name: str, message: str) -> None:
        batch_ref = get_pending_batch(batch_id)
        set_entry_status(batch_ref, pid, "done")
        batch_ref["results"][pid] = {
            "status": "installed",
            "tool_name": tool_name,
            "message": message,
        }

    def on_failed(pid: str, tool_name: str, reason: str) -> None:
        batch_ref = get_pending_batch(batch_id)
        set_entry_status(batch_ref, pid, "failed")
        batch_ref["results"][pid] = {
            "status": "failed",
            "tool_name": tool_name,
            "reason": reason,
        }

    async def build_one(pid: str) -> AsyncIterator[str]:
        plan_data = get_pending_plan(pid)
        set_entry_status(get_pending_batch(batch_id), pid, "building")
        async for event in stream_tool_build(
            plan_id=pid,
            plan_data=plan_data,
            run_id=run_id,
            creator_model=creator_model,
            reasoning_effort=reasoning_effort,
            request=request,
            litellm_url=LITELLM_URL,
            litellm_headers=litellm_headers(),
            pending_plans=PENDING_PLANS,
            process_step=process_step,
            tool_build_phase=tool_build_phase,
            tool_build_log=tool_build_log,
            sse_data=sse_data,
            cancelled_events=cancelled_events,
            is_run_cancelled=is_run_cancelled,
            clear_run_cancelled=clear_run_cancelled,
            batch_id=batch_id,
            install_lock=RUNTIME_INSTALL_LOCK,
            on_installed=on_installed,
            on_failed=on_failed,
            skip_plan_cleanup=False,
        ):
            yield event

    forge_search = resolve_gemini_google_search(payload, creator_model)

    async def merged_stream():
        with forge_google_search_context(forge_search):
            generators = [build_one(pid) for pid in plan_ids]
            async for event in merge_async_generators(generators):
                yield event
            batch_ref = get_pending_batch(batch_id)
            if batch_terminal(batch_ref):
                batch_ref["status"] = "complete"
                yield batch_sse(
                    {
                        "ada_event": "forge_batch_complete",
                        "run_id": run_id,
                        "summary": build_resume_summary(batch_ref),
                    },
                    batch_id=batch_id,
                )
        yield "data: [DONE]\n\n"

    return StreamingResponse(merged_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/forge_batch/resume_agent")
async def forge_batch_resume_agent(request: Request, payload: dict = Body(...)) -> StreamingResponse:
    batch_id = payload.get("batch_id", "").strip()
    if not batch_id:
        raise HTTPException(status_code=400, detail="batch_id is required.")

    try:
        batch = get_pending_batch(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    lite_model = (payload.get("model") or LITE_MODEL).strip()
    tool_creator_model = (
        payload.get("tool_creator_model") or batch["creator_model"] or TOOL_CREATOR_MODEL
    ).strip()
    messages = payload.get("messages")
    run_id = batch.get("run_id") or uuid.uuid4().hex
    reasoning_effort = resolve_reasoning_effort(payload.get("reasoning_effort"))
    gemini_google_search = resolve_gemini_google_search(payload, lite_model)
    forge_gemini_google_search = resolve_gemini_google_search(payload, tool_creator_model)
    tts_enabled = resolve_tts_enabled(payload)

    if not lite_model:
        raise HTTPException(status_code=400, detail="No lite model selected.")
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be a list.")

    summary = build_batch_scout_resume_message(batch)
    resume_messages = [*messages, {"role": "user", "content": summary}]

    async def resume_stream():
        async for chunk in stream_agent_sse(
            run_id=run_id,
            lite_model=lite_model,
            tool_creator_model=tool_creator_model,
            messages=resume_messages,
            request=request,
            reasoning_effort=reasoning_effort,
            gemini_google_search=gemini_google_search,
            forge_gemini_google_search=forge_gemini_google_search,
            tts_enabled=tts_enabled,
        ):
            yield chunk

    return StreamingResponse(resume_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/approve_pip")
async def approve_pip(request: Request, payload: dict = Body(...)) -> StreamingResponse:
    pip_id = payload.get("pip_id", "").strip()
    run_id = payload.get("run_id", "").strip()
    if not pip_id:
        raise HTTPException(status_code=400, detail="pip_id is required.")

    try:
        pip_data = get_pending_pip(pip_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    run_id = run_id or pip_data.get("run_id", "")
    plan_id = pip_data.get("plan_id", "")
    tool_name = pip_data["tool_name"]
    batch_id = (pip_data.get("batch_id") or "").strip()
    creator_model = pip_data.get("creator_model", "")

    if not creator_model:
        raise HTTPException(status_code=400, detail="No tool creator model configured.")

    reasoning_effort = resolve_reasoning_effort(
        payload.get("reasoning_effort") or pip_data.get("reasoning_effort"),
        default=TOOL_CREATOR_REASONING_EFFORT,
    )
    forge_search = resolve_gemini_google_search(payload, creator_model)

    async def pip_stream():
        with forge_google_search_context(forge_search):
            clear_run_cancelled(run_id)
            install_succeeded = False

            def step(step_id: str, label: str, status: str, *, detail: str = ""):
                if not run_id:
                    return ""
                return process_step(
                    run_id,
                    step_id,
                    label,
                    status,
                    model=creator_model,
                    detail=detail,
                )

            def emit(payload: dict) -> str:
                nonlocal install_succeeded
                if payload.get("ada_event") == "tool_installed":
                    install_succeeded = True
                return sse_data(
                    _batch_tag_payload(
                        payload,
                        batch_id=batch_id,
                        plan_id=plan_id,
                        tool_name=tool_name,
                    )
                )

            def phase(step_id: str, status: str, *, detail: str = ""):
                if batch_id:
                    return emit(
                        {
                            "ada_event": "tool_build_phase",
                            "run_id": run_id,
                            "phase": step_id,
                            "status": status,
                            "detail": detail,
                        }
                    )
                if not run_id:
                    return ""
                return tool_build_phase(run_id, step_id, status, detail=detail)

            def blog(message: str, *, level: str = "info"):
                if batch_id:
                    return emit(
                        {
                            "ada_event": "tool_build_log",
                            "run_id": run_id,
                            "message": message,
                            "level": level,
                        }
                    )
                if not run_id:
                    return ""
                return tool_build_log(run_id, message, level=level)

            async def cancelled() -> bool:
                return is_run_cancelled(run_id) or await request.is_disconnected()

            yield step("pip_review", "Awaiting pip install approval", "done")

            async for event in stream_runtime_install(
                run_id=run_id,
                plan_id=plan_id,
                tool_name=tool_name,
                tool_code=pip_data["tool_code"],
                test_code=pip_data["test_code"],
                requirements=pip_data.get("requirements", []),
                manifest=pip_data.get("manifest"),
                ui_files=pip_data.get("ui_files"),
                new_packages=pip_data.get("packages", []),
                creator_model=creator_model,
                litellm_url=LITELLM_URL,
                litellm_headers=litellm_headers(),
                step=step,
                phase=phase,
                blog=blog,
                sse_data=emit,
                cancelled=cancelled,
                skip_pip=False,
                reasoning_effort=reasoning_effort,
                install_lock=RUNTIME_INSTALL_LOCK if batch_id else None,
            ):
                yield event

            PENDING_PIP_INSTALLS.pop(pip_id, None)
            if plan_id in PENDING_PLANS:
                del PENDING_PLANS[plan_id]

            if install_succeeded and batch_id:
                message = f"Tool '{tool_name}' installed in the persistent tool runtime."
                mark_batch_tool_installed(batch_id, plan_id, tool_name, message)
                complete = _maybe_emit_batch_complete(batch_id, run_id)
                if complete:
                    yield complete

            clear_run_cancelled(run_id)

    return StreamingResponse(pip_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/approve_preview")
async def approve_preview(request: Request, payload: dict = Body(...)) -> StreamingResponse:
    preview_id = payload.get("preview_id", "").strip()
    run_id = payload.get("run_id", "").strip()
    if not preview_id:
        raise HTTPException(status_code=400, detail="preview_id is required.")

    try:
        preview_data = get_pending_ui_preview(preview_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    run_id = run_id or preview_data.get("run_id", "")
    plan_id = preview_data.get("plan_id", "")
    tool_name = preview_data["tool_name"]
    batch_id = (preview_data.get("batch_id") or "").strip()
    creator_model = preview_data.get("creator_model", "")

    if not creator_model:
        raise HTTPException(status_code=400, detail="No tool creator model configured.")

    reasoning_effort = resolve_reasoning_effort(
        payload.get("reasoning_effort") or preview_data.get("reasoning_effort"),
        default=TOOL_CREATOR_REASONING_EFFORT,
    )
    forge_search = resolve_gemini_google_search(payload, creator_model)

    async def preview_approve_stream():
        with forge_google_search_context(forge_search):
            clear_run_cancelled(run_id)
            install_succeeded = False
            build_failed = False
            fail_reason = ""

            def step(step_id: str, label: str, status: str, *, detail: str = ""):
                if not run_id:
                    return ""
                return process_step(
                    run_id,
                    step_id,
                    label,
                    status,
                    model=creator_model,
                    detail=detail,
                )

            def emit(payload: dict) -> str:
                nonlocal install_succeeded, build_failed, fail_reason
                event = payload.get("ada_event")
                if event == "tool_installed":
                    install_succeeded = True
                elif event == "tool_build_failed":
                    build_failed = True
                    fail_reason = payload.get("reason", "Build failed.")
                return sse_data(
                    _batch_tag_payload(
                        payload,
                        batch_id=batch_id,
                        plan_id=plan_id,
                        tool_name=tool_name,
                    )
                )

            def phase(step_id: str, status: str, *, detail: str = ""):
                if batch_id:
                    return emit(
                        {
                            "ada_event": "tool_build_phase",
                            "run_id": run_id,
                            "phase": step_id,
                            "status": status,
                            "detail": detail,
                        }
                    )
                if not run_id:
                    return ""
                return tool_build_phase(run_id, step_id, status, detail=detail)

            def blog(message: str, *, level: str = "info"):
                if batch_id:
                    return emit(
                        {
                            "ada_event": "tool_build_log",
                            "run_id": run_id,
                            "message": message,
                            "level": level,
                        }
                    )
                if not run_id:
                    return ""
                return tool_build_log(run_id, message, level=level)

            async def cancelled() -> bool:
                return is_run_cancelled(run_id) or await request.is_disconnected()

            yield step("ui_preview", "Awaiting app preview approval", "done")

            async for event in continue_tool_build(
                run_id=run_id,
                plan_id=plan_id,
                tool_name=tool_name,
                tool_code=preview_data["tool_code"],
                test_code=preview_data["test_code"],
                requirements=preview_data.get("requirements", []),
                manifest=preview_data.get("manifest"),
                ui_files=preview_data.get("ui_files"),
                creator_model=creator_model,
                litellm_url=LITELLM_URL,
                litellm_headers=litellm_headers(),
                step=step,
                phase=phase,
                blog=blog,
                sse_data=emit,
                cancelled=cancelled,
                reasoning_effort=reasoning_effort,
                preview_already_installed=bool(preview_data.get("preview_installed")),
                install_lock=RUNTIME_INSTALL_LOCK if batch_id else None,
                batch_id=batch_id or None,
            ):
                yield event

            PENDING_UI_PREVIEWS.pop(preview_id, None)
            if plan_id in PENDING_PLANS:
                del PENDING_PLANS[plan_id]

            if batch_id:
                if install_succeeded:
                    message = f"Tool '{tool_name}' installed in the persistent tool runtime."
                    mark_batch_tool_installed(batch_id, plan_id, tool_name, message)
                elif build_failed:
                    mark_batch_tool_failed(batch_id, plan_id, tool_name, fail_reason)
                complete = _maybe_emit_batch_complete(batch_id, run_id)
                if complete:
                    yield complete

            clear_run_cancelled(run_id)

    return StreamingResponse(
        preview_approve_stream(), media_type="text/event-stream", headers=SSE_HEADERS
    )


@app.post("/api/revise_preview")
async def revise_preview(request: Request, payload: dict = Body(...)) -> StreamingResponse:
    preview_id = payload.get("preview_id", "").strip()
    feedback = payload.get("feedback", "").strip()
    run_id = payload.get("run_id", "").strip()
    if not preview_id:
        raise HTTPException(status_code=400, detail="preview_id is required.")
    if not feedback:
        raise HTTPException(
            status_code=400,
            detail="Describe the changes you want before requesting a revision.",
        )

    try:
        preview_data = get_pending_ui_preview(preview_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    run_id = run_id or preview_data.get("run_id", "")
    plan_id = preview_data.get("plan_id", "")
    tool_name = preview_data["tool_name"]
    creator_model = preview_data.get("creator_model", "")

    if not creator_model:
        raise HTTPException(status_code=400, detail="No tool creator model configured.")

    reasoning_effort = resolve_reasoning_effort(
        payload.get("reasoning_effort") or preview_data.get("reasoning_effort"),
        default=TOOL_CREATOR_REASONING_EFFORT,
    )
    forge_search = resolve_gemini_google_search(payload, creator_model)

    async def preview_revise_stream():
        clear_run_cancelled(run_id)

        def step(step_id: str, label: str, status: str, *, detail: str = ""):
            if not run_id:
                return ""
            return process_step(
                run_id,
                step_id,
                label,
                status,
                model=creator_model,
                detail=detail,
            )

        def phase(step_id: str, status: str, *, detail: str = ""):
            if not run_id:
                return ""
            return tool_build_phase(run_id, step_id, status, detail=detail)

        def blog(message: str, *, level: str = "info"):
            if not run_id:
                return ""
            return tool_build_log(run_id, message, level=level)

        async def cancelled() -> bool:
            return is_run_cancelled(run_id) or await request.is_disconnected()

        yield step("ui_preview", "Revising app from your feedback", "active")
        yield phase("ui_preview", "active")
        yield blog("Revising skill from your app preview feedback…")

        screenshot_raw = payload.get("screenshot_base64")
        try:
            screenshot_b64 = normalize_preview_screenshot(
                str(screenshot_raw).strip() if screenshot_raw else None
            )
        except ValueError as exc:
            yield step("ui_preview", "Revising app from your feedback", "error", detail=str(exc))
            yield phase("ui_preview", "error", detail=str(exc)[:200])
            yield sse_data(
                {
                    "ada_event": "tool_build_failed",
                    "run_id": run_id,
                    "tool_name": tool_name,
                    "reason": str(exc),
                }
            )
            yield "data: [DONE]\n\n"
            return

        if screenshot_b64:
            yield blog("App screenshot attached for vision review.")
        else:
            yield blog("No screenshot attached — revising from text feedback only.", level="warn")

        try:
            with forge_google_search_context(forge_search):
                tool_code, test_code, manifest, ui_files = await revise_preview_code(
                    tool_name,
                    preview_data["tool_code"],
                    preview_data["test_code"],
                    preview_data.get("manifest"),
                    feedback,
                    creator_model,
                    litellm_url=LITELLM_URL,
                    headers=litellm_headers(),
                    run_id=run_id,
                    reasoning_effort=reasoning_effort,
                    screenshot_base64=screenshot_b64,
                    ui_files=preview_data.get("ui_files"),
                )
        except Exception as exc:
            yield step("ui_preview", "Revising app from your feedback", "error", detail=str(exc))
            yield phase("ui_preview", "error", detail=str(exc)[:200])
            yield sse_data(
                {
                    "ada_event": "tool_build_failed",
                    "run_id": run_id,
                    "tool_name": tool_name,
                    "reason": f"Preview revision failed: {exc}",
                }
            )
            yield "data: [DONE]\n\n"
            return

        yield sse_data(
            {
                "ada_event": "tool_code_ready",
                "run_id": run_id,
                "tool_name": tool_name,
                "tool_code": tool_code,
                "test_code": test_code,
                "requirements": preview_data.get("requirements", []),
            }
        )

        with forge_google_search_context(forge_search):
            sandbox_success, log_output, test_code, tool_code, updated_requirements, sandbox_notices = (
                await run_sandbox_phase(
                    run_id=run_id,
                    tool_name=tool_name,
                    tool_code=tool_code,
                    test_code=test_code,
                    requirements=preview_data.get("requirements", []),
                    manifest=manifest,
                    creator_model=creator_model,
                    litellm_url=LITELLM_URL,
                    headers=litellm_headers(),
                    step=step,
                    phase=phase,
                    blog=blog,
                    sse_data=sse_data,
                    cancelled=cancelled,
                    reasoning_effort=reasoning_effort,
                )
            )
        preview_data["requirements"] = updated_requirements
        for level, message in sandbox_notices:
            yield blog(message, level=level)
        log_sandbox(
            run_id,
            tool_name=tool_name,
            success=sandbox_success,
            logs=log_output,
            attempt=PHASE_MAX_RETRIES - 1 if not sandbox_success else 0,
        )

        if not sandbox_success:
            yield step("sandbox_test", "Running verification tests", "error", detail=log_output[:500])
            yield phase("sandbox_test", "error", detail=log_output[:200])
            yield blog(log_output, level="error")
            yield sse_data(
                {
                    "ada_event": "tool_build_failed",
                    "run_id": run_id,
                    "tool_name": tool_name,
                    "reason": "Verification failed after preview revision.",
                    "logs": log_output,
                }
            )
            yield "data: [DONE]\n\n"
            return

        preview_data["tool_code"] = tool_code
        preview_data["test_code"] = test_code
        preview_data["manifest"] = manifest
        preview_data["ui_files"] = ui_files

        yield blog(f"Re-installing preview of '{tool_name}'…")
        try:
            await runtime_install_tool(
                tool_name,
                tool_code,
                test_code,
                preview_data.get("requirements", []),
                skip_pip=True,
            )
            write_tool_files(
                tool_name,
                tool_code,
                preview_data.get("requirements", []),
                test_code,
                manifest=manifest,
                ui_files=ui_files,
            )
            preview_data["preview_installed"] = True
        except Exception as exc:
            yield step("ui_preview", "Revising app from your feedback", "error", detail=str(exc))
            yield phase("ui_preview", "error", detail=str(exc)[:200])
            yield sse_data(
                {
                    "ada_event": "tool_build_failed",
                    "run_id": run_id,
                    "tool_name": tool_name,
                    "reason": f"Preview re-install failed: {exc}",
                }
            )
            yield "data: [DONE]\n\n"
            return

        new_preview_id = uuid.uuid4().hex
        PENDING_UI_PREVIEWS[new_preview_id] = {
            **preview_data,
            "preview_id": new_preview_id,
            "created_at": time.time(),
        }
        PENDING_UI_PREVIEWS.pop(preview_id, None)

        yield step("ui_preview", "Revising app from your feedback", "done")
        yield phase("ui_preview", "active")
        yield sse_data(
            {
                "ada_event": "ui_preview_pending",
                "preview_id": new_preview_id,
                "run_id": run_id,
                "plan_id": plan_id,
                "tool_name": tool_name,
            }
        )
        yield sse_data(
            {
                "ada_event": "preview_skill_app",
                "run_id": run_id,
                "skill_name": tool_name,
            }
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        preview_revise_stream(), media_type="text/event-stream", headers=SSE_HEADERS
    )


@app.post("/api/reject_preview")
async def reject_preview(payload: dict = Body(...)) -> dict:
    preview_id = payload.get("preview_id", "").strip()
    if not preview_id:
        raise HTTPException(status_code=400, detail="preview_id is required.")

    preview_data = PENDING_UI_PREVIEWS.pop(preview_id, None)
    if preview_data is None:
        raise HTTPException(status_code=404, detail="UI preview request not found.")

    tool_name = preview_data.get("tool_name", "")
    if preview_data.get("preview_installed") and tool_name:
        try:
            await delete_tool_async(tool_name)
        except Exception as exc:
            logger.warning("Failed to remove preview tool %s: %s", tool_name, exc)

    log_build_event(
        preview_data.get("run_id", ""),
        phase="ui_preview",
        message=f"preview rejected for {tool_name}",
        level="warn",
    )
    return {"status": "rejected", "preview_id": preview_id, "tool_name": tool_name}


@app.post("/api/reject_pip")
async def reject_pip(payload: dict = Body(...)) -> dict:
    pip_id = payload.get("pip_id", "").strip()
    if not pip_id:
        raise HTTPException(status_code=400, detail="pip_id is required.")
    if pip_id in PENDING_PIP_INSTALLS:
        data = PENDING_PIP_INSTALLS.pop(pip_id)
        log_pip_install(
            data.get("run_id", ""),
            packages=data.get("packages", []),
            logs="rejected by user",
            approved=False,
        )
        return {"status": "rejected", "pip_id": pip_id}
    raise HTTPException(status_code=404, detail="Pip install request not found.")


@app.post("/api/revise_tool")
async def revise_tool(request: Request, payload: dict = Body(...)) -> StreamingResponse:
    plan_id = payload.get("plan_id", "").strip()
    feedback = payload.get("feedback", "").strip()
    run_id = payload.get("run_id", "").strip()
    if not plan_id:
        raise HTTPException(status_code=400, detail="plan_id is required.")
    if not feedback:
        raise HTTPException(
            status_code=400,
            detail="Describe the changes you want before requesting a revision.",
        )

    plan_data = get_pending_plan(plan_id)
    tool_name = plan_data["tool_name"]
    creator_model = (
        payload.get("tool_creator_model") or plan_data["creator_model"]
    ).strip()
    run_id = run_id or plan_data.get("run_id", "")

    if not creator_model:
        raise HTTPException(status_code=400, detail="No tool creator model configured.")

    reasoning_effort = resolve_reasoning_effort(
        payload.get("reasoning_effort"),
        default=TOOL_CREATOR_REASONING_EFFORT,
    )
    forge_search = resolve_gemini_google_search(payload, creator_model)

    async def revision_stream():
        clear_run_cancelled(run_id)
        log_build_event(
            run_id,
            phase="revise",
            message=f"revising plan plan_id={plan_id} tool={tool_name}",
        )

        def step(step_id: str, label: str, status: str, *, detail: str = ""):
            if not run_id:
                return ""
            return process_step(
                run_id,
                step_id,
                label,
                status,
                model=creator_model,
                detail=detail,
            )

        yield step("awaiting_approval", "Awaiting your approval", "done")
        yield step("plan_revise", "Revising plan from your feedback", "active")
        if is_run_cancelled(run_id) or await request.is_disconnected():
            for event in cancelled_events(run_id, "plan_revise", model=creator_model):
                yield event
            return

        try:
            plan_out: dict[str, str] = {}
            with forge_google_search_context(forge_search):
                async for event in stream_plan_draft_events(
                    run_id,
                    tool_name,
                    revise_tool_plan_stream(
                        tool_name,
                        plan_data["description"],
                        plan_data["plan"],
                        feedback,
                        creator_model,
                        litellm_url=LITELLM_URL,
                        headers=litellm_headers(),
                        run_id=run_id,
                        reasoning_effort=reasoning_effort,
                    ),
                    kind=plan_data.get("kind", "create"),
                    plan_id=plan_id,
                    out=plan_out,
                ):
                    yield event
            revised_plan = plan_out.get("plan", "")
            log_plan(run_id, tool_name=tool_name, plan=revised_plan, action="revised")
        except (RuntimeError, ValueError) as exc:
            yield step(
                "plan_revise",
                "Revising plan from your feedback",
                "error",
                detail=str(exc),
            )
            yield sse_data(
                {
                    "ada_event": "tool_plan_revise_failed",
                    "run_id": run_id,
                    "plan_id": plan_id,
                    "tool_name": tool_name,
                    "reason": str(exc),
                }
            )
            yield "data: [DONE]\n\n"
            return

        if is_run_cancelled(run_id) or await request.is_disconnected():
            for event in cancelled_events(run_id, "plan_revise", model=creator_model):
                yield event
            return

        plan_data["plan"] = revised_plan
        plan_data["created_at"] = time.time()
        clear_run_cancelled(run_id)

        yield step("plan_revise", "Revising plan from your feedback", "done")
        yield step(
            "awaiting_approval",
            "Awaiting your approval",
            "active",
            detail=tool_name,
        )
        yield sse_data(
            {
                "ada_event": "tool_plan_revised",
                "run_id": run_id,
                "plan_id": plan_id,
                "tool_name": tool_name,
                "plan": revised_plan,
            }
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        revision_stream(), media_type="text/event-stream", headers=SSE_HEADERS
    )


@app.post("/api/reject_tool")
async def reject_tool(payload: dict = Body(...)) -> dict:
    plan_id = payload.get("plan_id", "").strip()
    if not plan_id:
        raise HTTPException(status_code=400, detail="plan_id is required.")

    cleanup_expired_plans()
    if plan_id in PENDING_PLANS:
        del PENDING_PLANS[plan_id]
        return {"status": "rejected", "message": "Plan rejected."}

    raise HTTPException(status_code=404, detail="Plan not found or expired.")
