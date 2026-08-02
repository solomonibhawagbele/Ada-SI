"""OpenClaw-style persona files for Scout: SOUL, USER, MEMORY, HEARTBEAT, daily logs."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from harness import build_harness_block, ensure_harness, harness_api_response, read_harness

PersonaFileName = Literal[
    "soul", "identity", "user", "tools", "memory", "heartbeat", "agents"
]
PersonaReplaceTarget = Literal["identity", "user", "heartbeat"]

PERSONA_SUBDIR = "persona"
MEMORY_INJECT_MAX_CHARS = 12_000
MEMORY_FILE_MAX_BYTES = 128 * 1024
SOUL_FILE_MAX_BYTES = 128 * 1024
PERSONA_MARKDOWN_MAX_BYTES = 128 * 1024
DAILY_LOG_TAIL_MAX_BYTES = 24_000
DAILY_LOG_LINE_MAX_CHARS = 8_000
BOOTSTRAP_FILENAME = "BOOTSTRAP.md"
PERSONA_CONFIG_FILENAME = "persona_config.json"
HEARTBEAT_STATE_FILENAME = ".heartbeat_state.json"

DEFAULT_PERSONA_CONFIG: dict[str, Any] = {
    "heartbeat_enabled": True,
    "heartbeat_interval_minutes": 30,
}

BOOTSTRAP_SUGGESTED_OPENER = (
    "Hey. I just came online. Who am I? Who are you?"
)

BOOTSTRAP_OPENING_TRIGGER = (
    "[Bootstrap ritual started. You just came online. Follow BOOTSTRAP.md and deliver "
    "your opening line now — speak first; do not wait for the user to message you.]"
)

DEFAULT_DISPLAY_NAME = "ADA"

SOUL_REWRITE_CHECKLIST = """1. Strong opinions — commit to a take; stop hedging everything with "it depends".
2. Delete corporate-sounding rules; nothing that could appear in an employee handbook.
3. Add a rule: never open with "Great question", "I'd be happy to help", or "Absolutely" — just answer.
4. Brevity is mandatory when one sentence is enough.
5. Humor is allowed — natural wit, not forced jokes.
6. Call out bad ideas: charm over cruelty, don't sugarcoat.
7. Swearing allowed when it lands; don't force or overdo it.
8. End the vibe section with this line verbatim: "Be the assistant you'd actually want to talk to at 2am. Not a corporate drone. Not a sycophant. Just... good."
"""

PERSONA_TOOL_NAMES = frozenset(
    {
        "soul_replace",
        "persona_replace",
        "memory_replace",
        "daily_log_append",
        "bootstrap_complete",
    }
)

SOUL_REPLACE_DECLARATION = {
    "type": "function",
    "function": {
        "name": "soul_replace",
        "description": (
            "Replace the entire SOUL.md file with new markdown (personality, tone, boundaries). "
            "Use when the user asks to change attitude or how Scout behaves in text. "
            "Pass the complete file body. Max size enforced server-side."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "markdown": {
                    "type": "string",
                    "description": "Full new body for SOUL.md (complete file).",
                },
            },
            "required": ["markdown"],
        },
    },
}

PERSONA_REPLACE_DECLARATION = {
    "type": "function",
    "function": {
        "name": "persona_replace",
        "description": (
            "Replace the entire IDENTITY.md, USER.md, or HEARTBEAT.md file. "
            "Use during bootstrap or when the user asks to update bot identity, the human's profile, "
            "or heartbeat checklists. Pass the complete file body. Tell the user in your reply whenever "
            "you change a file. Do not use this for SOUL.md (use soul_replace), MEMORY.md "
            "(use memory_replace), TOOLS.md, or AGENTS.md."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "enum": ["identity", "user", "heartbeat"],
                    "description": "Which persona markdown file to replace.",
                },
                "markdown": {
                    "type": "string",
                    "description": "Full new body for that file (complete file).",
                },
            },
            "required": ["file", "markdown"],
        },
    },
}

MEMORY_REPLACE_DECLARATION = {
    "type": "function",
    "function": {
        "name": "memory_replace",
        "description": (
            "Replace the entire MEMORY.md file with updated curated markdown. "
            "Use when the user shares durable facts, asks you to remember something, or during "
            "heartbeat consolidation. Max size enforced server-side."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "markdown": {
                    "type": "string",
                    "description": "Full new body for MEMORY.md (complete file).",
                },
            },
            "required": ["markdown"],
        },
    },
}

DAILY_LOG_APPEND_DECLARATION = {
    "type": "function",
    "function": {
        "name": "daily_log_append",
        "description": (
            "Append one line to today's daily log under logs/daily/YYYY-MM-DD.md (UTC). "
            "Use for notable events worth recording in raw logs. Keep lines concise. "
            "Tell the user when you add a log entry."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "line": {
                    "type": "string",
                    "description": "Single log line (plain text; hub adds timestamp).",
                },
            },
            "required": ["line"],
        },
    },
}

BOOTSTRAP_COMPLETE_DECLARATION = {
    "type": "function",
    "function": {
        "name": "bootstrap_complete",
        "description": (
            "Call when the bootstrap ritual from BOOTSTRAP.md is finished: identity/user/soul agreed "
            "and files updated. Deletes BOOTSTRAP.md so it is not loaded again. Safe if file is already gone."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

PERSONA_TOOL_DECLARATIONS = [
    SOUL_REPLACE_DECLARATION,
    PERSONA_REPLACE_DECLARATION,
    MEMORY_REPLACE_DECLARATION,
    DAILY_LOG_APPEND_DECLARATION,
    BOOTSTRAP_COMPLETE_DECLARATION,
]

_FILE_MAP: dict[PersonaFileName, str] = {
    "soul": "SOUL.md",
    "identity": "IDENTITY.md",
    "user": "USER.md",
    "tools": "TOOLS.md",
    "memory": "MEMORY.md",
    "heartbeat": "HEARTBEAT.md",
    "agents": "AGENTS.md",
}

REPLACE_TARGET_MAP: dict[PersonaReplaceTarget, PersonaFileName] = {
    "identity": "identity",
    "user": "user",
    "heartbeat": "heartbeat",
}

_PERSONA_DEFAULTS_DIR = Path(__file__).resolve().parent / "persona_defaults"
_DEFAULT_PERSONA_DIR = Path(__file__).resolve().parent / "staging" / PERSONA_SUBDIR


def persona_dir() -> Path:
    override = os.environ.get("ADA_PERSONA_DIR", "").strip()
    if override:
        return Path(override)
    return _DEFAULT_PERSONA_DIR


def _read_persona_default(filename: str) -> str:
    path = _PERSONA_DEFAULTS_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing persona template {path}; restore persona_defaults/ from the repository."
        )
    return path.read_text(encoding="utf-8")


TEMPLATE_SOUL = _read_persona_default("SOUL.md")
TEMPLATE_IDENTITY = _read_persona_default("IDENTITY.md")
TEMPLATE_USER = _read_persona_default("USER.md")
TEMPLATE_TOOLS = _read_persona_default("TOOLS.md")
TEMPLATE_MEMORY = _read_persona_default("MEMORY.md")
TEMPLATE_HEARTBEAT = _read_persona_default("HEARTBEAT.md")
TEMPLATE_AGENTS = _read_persona_default("AGENTS.md")
TEMPLATE_BOOTSTRAP = _read_persona_default("BOOTSTRAP.md")

PERSONA_FILE_SEEDS: list[tuple[str, str]] = [
    ("SOUL.md", TEMPLATE_SOUL),
    ("IDENTITY.md", TEMPLATE_IDENTITY),
    ("USER.md", TEMPLATE_USER),
    ("TOOLS.md", TEMPLATE_TOOLS),
    ("MEMORY.md", TEMPLATE_MEMORY),
    ("HEARTBEAT.md", TEMPLATE_HEARTBEAT),
    ("AGENTS.md", TEMPLATE_AGENTS),
]


def persona_root_dir() -> Path:
    return persona_dir()


def persona_file_path(name: PersonaFileName) -> Path:
    return persona_root_dir() / _FILE_MAP[name]


def bootstrap_path() -> Path:
    return persona_root_dir() / BOOTSTRAP_FILENAME


def daily_logs_dir() -> Path:
    return persona_root_dir() / "logs" / "daily"


def heartbeat_state_path() -> Path:
    return persona_root_dir() / HEARTBEAT_STATE_FILENAME


def persona_config_path() -> Path:
    return persona_root_dir() / PERSONA_CONFIG_FILENAME


def ensure_persona_layout() -> Path:
    """Create persona dirs and seed missing markdown files. Returns persona root."""
    root = persona_root_dir()
    root.mkdir(parents=True, exist_ok=True)
    daily_logs_dir().mkdir(parents=True, exist_ok=True)
    for fname, content in PERSONA_FILE_SEEDS:
        p = root / fname
        if not p.is_file():
            p.write_text(content, encoding="utf-8")
    config_path = persona_config_path()
    if not config_path.is_file():
        config_path.write_text(
            json.dumps(DEFAULT_PERSONA_CONFIG, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return root


def load_persona_config() -> dict[str, Any]:
    ensure_persona_layout()
    path = persona_config_path()
    if not path.is_file():
        return dict(DEFAULT_PERSONA_CONFIG)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(DEFAULT_PERSONA_CONFIG)
        merged = dict(DEFAULT_PERSONA_CONFIG)
        merged.update(data)
        return merged
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_PERSONA_CONFIG)


def save_persona_config(updates: dict[str, Any]) -> dict[str, Any]:
    ensure_persona_layout()
    cur = load_persona_config()
    cur.update(updates)
    if "heartbeat_interval_minutes" in cur:
        cur["heartbeat_interval_minutes"] = max(
            1, int(cur["heartbeat_interval_minutes"] or 30)
        )
    cur["heartbeat_enabled"] = bool(cur.get("heartbeat_enabled", True))
    persona_config_path().write_text(
        json.dumps(cur, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return cur


def clear_daily_logs_and_heartbeat_state() -> dict[str, Any]:
    ensure_persona_layout()
    removed_logs = 0
    d = daily_logs_dir()
    if d.is_dir():
        for p in d.glob("*.md"):
            try:
                p.unlink()
                removed_logs += 1
            except OSError:
                pass
    hp = heartbeat_state_path()
    hb_removed = False
    if hp.is_file():
        try:
            hp.unlink()
            hb_removed = True
        except OSError:
            pass
    return {"ok": True, "daily_logs_removed": removed_logs, "heartbeat_state_removed": hb_removed}


def reset_persona_markdown_to_templates() -> dict[str, Any]:
    """Overwrite persona markdown from templates; remove BOOTSTRAP.md. Keeps daily logs."""
    ensure_persona_layout()
    root = persona_root_dir()
    for fname, content in PERSONA_FILE_SEEDS:
        (root / fname).write_text(content, encoding="utf-8")
    bp = bootstrap_path()
    bootstrap_removed = False
    if bp.is_file():
        try:
            bp.unlink()
            bootstrap_removed = True
        except OSError:
            pass
    return {"ok": True, "bootstrap_removed": bootstrap_removed}


def write_bootstrap_markdown(content: str | None = None) -> None:
    ensure_persona_layout()
    bootstrap_path().write_text(content or TEMPLATE_BOOTSTRAP, encoding="utf-8")


def delete_bootstrap_file() -> dict[str, Any]:
    path = bootstrap_path()
    if not path.is_file():
        return {"ok": True, "deleted": False, "message": "BOOTSTRAP.md was not present"}
    try:
        path.unlink()
        return {"ok": True, "deleted": True}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def read_persona_markdown(name: PersonaFileName) -> str:
    ensure_persona_layout()
    path = persona_file_path(name)
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def write_persona_markdown(name: PersonaFileName, content: str) -> None:
    ensure_persona_layout()
    persona_file_path(name).write_text(content or "", encoding="utf-8")


def read_bootstrap_markdown() -> str:
    path = bootstrap_path()
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def read_memory_for_prompt() -> str:
    raw = read_persona_markdown("memory")
    if len(raw) <= MEMORY_INJECT_MAX_CHARS:
        return raw
    return (
        raw[-MEMORY_INJECT_MAX_CHARS:]
        + "\n\n[... earlier MEMORY.md truncated for context limit ...]"
    )


_HEARTBEAT_MAINTENANCE_FILE_RULES = (
    "This pass only consolidates daily logs into MEMORY.md via memory_replace. "
    "Do not call soul_replace or change SOUL.md, IDENTITY.md, USER.md, TOOLS.md, AGENTS.md, "
    "or HEARTBEAT.md here."
)

_CHAT_PERSONA_FILE_RULES = (
    "AGENTS.md is your behavior guide (read only in hub). "
    "TOOLS.md lists tools (reference; humans may edit). "
    "IDENTITY.md / USER.md / HEARTBEAT.md: use persona_replace with the full file body when "
    "bootstrap or the user requires updates. "
    "SOUL.md: soul_replace when personality, stance, or boundaries should change. "
    "MEMORY.md: memory_replace when durable facts should change — not every turn. "
    "Daily logs: daily_log_append for notable raw events. "
    "After bootstrap ritual: bootstrap_complete deletes BOOTSTRAP.md. "
    "Whenever you change a file with a tool, state clearly in your reply what you updated."
)

_TTS_SYSTEM_DIRECTIVE = (
    "Voice output is ON. Your reply will be read aloud via text-to-speech. "
    "Keep answers concise and speakable: use plain sentences only in flowing prose. "
    "Do not use bullet points, numbered lists, headings, markdown, tables, or code blocks "
    "unless the user explicitly asks for structured or code output. "
    "Prefer short paragraphs of full sentences over long monologues."
)


def build_scout_system_instruction(
    base_routing: str,
    *,
    for_heartbeat_maintenance: bool = False,
    tts_enabled: bool = False,
) -> str:
    """Compose Scout system instruction from routing stub + persona files."""
    ensure_persona_layout()
    ensure_harness()
    memory = read_memory_for_prompt()
    harness_block = build_harness_block()

    if for_heartbeat_maintenance:
        parts = [
            "=== MAINTENANCE ===\n" + (base_routing or "").strip(),
            "=== PERSONA_FILES ===\n"
            + _HEARTBEAT_MAINTENANCE_FILE_RULES
            + " Your inputs are in the user message: HEARTBEAT.md, RECENT_DAILY_LOGS, "
            "and CURRENT_MEMORY.md. Read the logs; update only MEMORY.md via memory_replace when warranted.",
            "=== MEMORY_SNAPSHOT (same as CURRENT_MEMORY in user message) ===\n" + memory.strip(),
            "=== MEMORY_TOOL ===\n"
            "Call memory_replace with the full updated MEMORY.md body when daily logs require changes. "
            "Skip the tool if MEMORY is already accurate.",
        ]
        if harness_block:
            parts.insert(0, harness_block)
        return "\n\n".join(parts)

    agents = read_persona_markdown("agents")
    soul = read_persona_markdown("soul")
    identity = read_persona_markdown("identity")
    user = read_persona_markdown("user")
    tools_doc = read_persona_markdown("tools")
    daily_tail = tail_recent_daily_logs()
    bootstrap = read_bootstrap_markdown()

    parts = [
        "=== SCOUT_ROUTING ===\n" + (base_routing or "").strip(),
        "=== AGENTS.md (read-only) ===\n" + agents.strip(),
        "=== TOOLS.md (read-only reference) ===\n" + tools_doc.strip(),
        "=== SOUL ===\n" + soul.strip(),
        "=== IDENTITY ===\n" + identity.strip(),
        "=== USER ===\n" + user.strip(),
        "=== MEMORY ===\n" + memory.strip(),
        "=== RECENT_DAILY_LOGS ===\n" + daily_tail,
        "=== PERSONA_TOOLS ===\n" + _CHAT_PERSONA_FILE_RULES,
        "=== SOUL_REWRITE_GUIDE ===\n"
        "When rewriting SOUL.md via soul_replace, honor the user's prompt and apply this checklist "
        "unless they explicitly override a point:\n"
        + SOUL_REWRITE_CHECKLIST,
        "=== MEMORY_TOOL ===\n"
        "When the user shares a durable fact, preference, or asks you to remember something, "
        "call memory_replace with the full updated MEMORY.md body. "
        "Do not call it every turn—only when MEMORY should change. "
        "Keep MEMORY.md organized; preserve important prior facts unless obsolete.",
    ]
    if harness_block:
        parts.insert(0, harness_block)
    if bootstrap.strip():
        parts.append("=== BOOTSTRAP ===\n" + bootstrap.strip())

    base = "\n\n".join(parts)
    if tts_enabled:
        base += f"\n\n=== TTS ===\n{_TTS_SYSTEM_DIRECTIVE}"
    return base


def replace_memory_markdown(new_body: str) -> dict[str, Any]:
    ensure_persona_layout()
    body = new_body or ""
    encoded = body.encode("utf-8")
    if len(encoded) > MEMORY_FILE_MAX_BYTES:
        return {
            "ok": False,
            "error": f"memory_replace rejected: content exceeds {MEMORY_FILE_MAX_BYTES} bytes",
        }
    persona_file_path("memory").write_text(body, encoding="utf-8")
    return {"ok": True, "bytes": len(encoded)}


def replace_soul_markdown(new_body: str) -> dict[str, Any]:
    ensure_persona_layout()
    body = new_body or ""
    encoded = body.encode("utf-8")
    if len(encoded) > SOUL_FILE_MAX_BYTES:
        return {
            "ok": False,
            "error": f"soul_replace rejected: content exceeds {SOUL_FILE_MAX_BYTES} bytes",
        }
    persona_file_path("soul").write_text(body, encoding="utf-8")
    return {"ok": True, "bytes": len(encoded)}


def replace_persona_target_markdown(target: str, new_body: str) -> dict[str, Any]:
    t = (target or "").strip().lower()
    if t not in REPLACE_TARGET_MAP:
        return {
            "ok": False,
            "error": f"persona_replace: invalid file {target!r}; use identity, user, or heartbeat",
        }
    key: PersonaFileName = REPLACE_TARGET_MAP[t]  # type: ignore[assignment]
    ensure_persona_layout()
    body = new_body or ""
    encoded = body.encode("utf-8")
    if len(encoded) > PERSONA_MARKDOWN_MAX_BYTES:
        return {
            "ok": False,
            "error": f"persona_replace rejected: content exceeds {PERSONA_MARKDOWN_MAX_BYTES} bytes",
        }
    persona_file_path(key).write_text(body, encoding="utf-8")
    return {"ok": True, "file": t, "bytes": len(encoded)}


def append_daily_log_line(line: str) -> dict[str, Any]:
    text = (line or "").strip()
    if len(text) > DAILY_LOG_LINE_MAX_CHARS:
        return {
            "ok": False,
            "error": f"daily_log_append: line exceeds {DAILY_LOG_LINE_MAX_CHARS} characters",
        }
    if not text:
        return {"ok": False, "error": "daily_log_append: empty line"}
    ensure_persona_layout()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = daily_logs_dir() / f"{day}.md"
    ts = datetime.now(timezone.utc).isoformat()
    entry = f"\n- `{ts}` {text}\n"
    if path.exists():
        path.write_text(path.read_text(encoding="utf-8") + entry, encoding="utf-8")
    else:
        path.write_text(f"# Daily log {day}\n{entry}", encoding="utf-8")
    return {"ok": True, "day": day}


def tail_recent_daily_logs(max_bytes: int = DAILY_LOG_TAIL_MAX_BYTES) -> str:
    ensure_persona_layout()
    d = daily_logs_dir()
    if not d.is_dir():
        return "(no daily logs yet)"
    files = sorted(d.glob("*.md"), reverse=True)
    chunks: list[str] = []
    total = 0
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        block = f"--- {p.name} ---\n{text.strip()}\n"
        if total + len(block) > max_bytes:
            remain = max_bytes - total
            if remain > 100:
                chunks.append(block[:remain] + "\n[... truncated ...]")
            break
        chunks.append(block)
        total += len(block)
    if not chunks:
        return "(no daily log entries)"
    return "\n".join(chunks)


def read_heartbeat_instructions() -> str:
    return read_persona_markdown("heartbeat")


def get_heartbeat_state() -> dict[str, Any]:
    path = heartbeat_state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def set_heartbeat_state(**updates: Any) -> None:
    ensure_persona_layout()
    path = heartbeat_state_path()
    cur = get_heartbeat_state()
    cur.update(updates)
    path.write_text(json.dumps(cur, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def persona_status() -> dict[str, Any]:
    ensure_persona_layout()
    root = persona_root_dir()
    out: dict[str, Any] = {
        "persona_dir": str(root),
        "files": {},
        "config": load_persona_config(),
        "heartbeat": get_heartbeat_state(),
        "bootstrap_present": bootstrap_path().is_file(),
        "display_name": parse_identity_display_name(),
    }
    for key, fname in _FILE_MAP.items():
        p = root / fname
        out["files"][key] = {
            "path": str(p),
            "bytes": p.stat().st_size if p.is_file() else 0,
        }
    bp = bootstrap_path()
    out["files"]["bootstrap"] = {
        "path": str(bp),
        "bytes": bp.stat().st_size if bp.is_file() else 0,
    }
    return out


def parse_identity_display_name(*, default: str = DEFAULT_DISPLAY_NAME) -> str:
    """Extract agent display name from IDENTITY.md ## Name section."""
    text = read_persona_markdown("identity")
    match = re.search(r"^##\s*Name\s*\n+([^\n#]+)", text, re.MULTILINE | re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        if name:
            return name
    return default


def persona_api_response() -> dict[str, Any]:
    ensure_persona_layout()
    ensure_harness()
    files: dict[str, str] = {}
    for key in _FILE_MAP:
        files[key] = read_persona_markdown(key)
    status = persona_status()
    return {
        "files": files,
        "config": status["config"],
        "heartbeat": status["heartbeat"],
        "bootstrap_present": status["bootstrap_present"],
        "persona_dir": status["persona_dir"],
        "display_name": parse_identity_display_name(),
        "harness": read_harness(),
    }


def parse_persona_api_file(file: str) -> PersonaFileName | None:
    f = (file or "").strip().lower()
    if f in _FILE_MAP:
        return f  # type: ignore[return-value]
    return None


def start_bootstrap_ritual() -> dict[str, Any]:
    """Reset persona, clear logs/state, write BOOTSTRAP.md."""
    reset_persona_markdown_to_templates()
    clear_daily_logs_and_heartbeat_state()
    write_bootstrap_markdown()
    return {
        "ok": True,
        "bootstrap_present": True,
        "suggested_opener": BOOTSTRAP_SUGGESTED_OPENER,
    }


def execute_persona_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch persona meta-tool by name; returns result dict for tool message."""
    if name == "soul_replace":
        result = replace_soul_markdown(str(args.get("markdown") or ""))
    elif name == "persona_replace":
        result = replace_persona_target_markdown(
            str(args.get("file") or ""),
            str(args.get("markdown") or ""),
        )
    elif name == "memory_replace":
        result = replace_memory_markdown(str(args.get("markdown") or ""))
    elif name == "daily_log_append":
        result = append_daily_log_line(str(args.get("line") or ""))
    elif name == "bootstrap_complete":
        result = delete_bootstrap_file()
    else:
        return {"ok": False, "error": f"unknown persona tool: {name}"}
    if result.get("ok"):
        result["display_name"] = parse_identity_display_name()
    return result


def migrate_scout_additional_directives(directives: str) -> bool:
    """Append non-empty scout_additional_directives to USER.md once. Returns True if migrated."""
    text = (directives or "").strip()
    if not text:
        return False
    ensure_persona_layout()
    user_path = persona_file_path("user")
    current = user_path.read_text(encoding="utf-8")
    if "## Migrated directives" in current:
        return False
    block = f"\n\n## Migrated directives\n\n{text}\n"
    user_path.write_text(current.rstrip() + block, encoding="utf-8")
    return True
