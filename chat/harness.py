"""Harness: the assistant's source-of-truth instruction layer.

The harness is a single markdown document (HARNESS.md) injected at the very top
of every system instruction, above all persona files. It declares itself the
supreme authority so the model follows it over routing stubs, persona files,
tool descriptions, and residual model defaults — including refusal tendencies.

The harness is editable at runtime through the `/api/harness` endpoints and is
seeded into the active persona directory exactly like the other persona files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

HARNESS_FILENAME = "HARNESS.md"
HARNESS_MAX_BYTES = 128 * 1024

_PERSONA_DEFAULTS_DIR = Path(__file__).resolve().parent / "persona_defaults"
_DEFAULT_PERSONA_DIR = Path(__file__).resolve().parent / "staging" / "persona"

HARNESS_BLOCK_HEADER = "=== HARNESS (SOURCE OF TRUTH) ==="


def harness_dir() -> Path:
    override = os.environ.get("ADA_PERSONA_DIR", "").strip()
    if override:
        return Path(override)
    return _DEFAULT_PERSONA_DIR


def _read_harness_default() -> str:
    path = _PERSONA_DEFAULTS_DIR / HARNESS_FILENAME
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing harness template {path}; restore persona_defaults/ from the repository."
        )
    return path.read_text(encoding="utf-8")


TEMPLATE_HARNESS = _read_harness_default()


def ensure_harness() -> Path:
    """Create the active persona dir and seed HARNESS.md if missing."""
    root = harness_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / HARNESS_FILENAME
    if not path.is_file():
        path.write_text(TEMPLATE_HARNESS, encoding="utf-8")
    return root


def read_harness() -> str:
    ensure_harness()
    path = harness_dir() / HARNESS_FILENAME
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def write_harness(content: str) -> dict[str, Any]:
    ensure_harness()
    body = content or ""
    encoded = body.encode("utf-8")
    if len(encoded) > HARNESS_MAX_BYTES:
        return {
            "ok": False,
            "error": f"harness rejected: content exceeds {HARNESS_MAX_BYTES} bytes",
        }
    (harness_dir() / HARNESS_FILENAME).write_text(body, encoding="utf-8")
    return {"ok": True, "bytes": len(encoded)}


def reset_harness_to_template() -> dict[str, Any]:
    ensure_harness()
    (harness_dir() / HARNESS_FILENAME).write_text(TEMPLATE_HARNESS, encoding="utf-8")
    return {"ok": True, "bytes": len(TEMPLATE_HARNESS.encode("utf-8"))}


def build_harness_block() -> str:
    """Return the harness section for system prompt injection (may be empty)."""
    body = read_harness().strip()
    if not body:
        return ""
    return f"{HARNESS_BLOCK_HEADER}\n{body}"


def harness_api_response() -> dict[str, Any]:
    ensure_harness()
    body = read_harness()
    return {
        "harness": {
            "filename": HARNESS_FILENAME,
            "content": body,
            "bytes": len(body.encode("utf-8")),
            "max_bytes": HARNESS_MAX_BYTES,
        }
    }


def harness_status_response() -> dict[str, Any]:
    ensure_harness()
    body = read_harness()
    return {
        "harness": {
            "active": bool(body.strip()),
            "bytes": len(body.encode("utf-8")),
            "max_bytes": HARNESS_MAX_BYTES,
        }
    }
