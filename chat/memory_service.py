"""
Memory Service - Long-term conversation memory for Ada-SI.

Stores and retrieves conversation context to help the model remember
past interactions beyond the context window.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

MEMORY_STORE = Path(__file__).parent / "memory_store"


def _ensure_memory_store():
    """Create memory store directory if it doesn't exist."""
    MEMORY_STORE.mkdir(exist_ok=True)


def _get_today_file() -> Path:
    """Get today's memory file."""
    _ensure_memory_store()
    today = datetime.now().strftime("%Y-%m-%d")
    return MEMORY_STORE / f"{today}.json"


def _load_today_memories() -> list[dict]:
    """Load today's memories."""
    today_file = _get_today_file()
    if today_file.exists():
        try:
            return json.loads(today_file.read_text())
        except (json.JSONDecodeError, IOError):
            return []
    return []


def _save_today_memories(memories: list[dict]):
    """Save today's memories."""
    today_file = _get_today_file()
    today_file.write_text(json.dumps(memories, indent=2))


def _extract_key_info(messages: list[dict]) -> dict:
    """Extract key information from messages for memory storage."""
    user_msgs = [m["content"] for m in messages if m.get("role") == "user"]
    assistant_msgs = [m["content"] for m in messages if m.get("role") == "assistant"]
    
    # Combine all text for keyword extraction
    all_text = " ".join(user_msgs + assistant_msgs)
    
    # Extract simple keywords (words > 3 chars, not common)
    common_words = {"the", "and", "for", "are", "but", "not", "you", "all", "can", 
                    "had", "her", "was", "one", "our", "out", "has", "his", "how",
                    "its", "may", "new", "now", "old", "see", "way", "who", "did",
                    "get", "let", "say", "she", "too", "use", "with", "that", "this",
                    "have", "from", "they", "been", "said", "each", "make", "like",
                    "long", "look", "many", "some", "than", "them", "then", "what",
                    "when", "your", "will", "would", "there", "their", "about", "could",
                    "other", "which", "after", "these", "first", "going", "still",
                    "where", "think", "really", "actually", "something", "anything"}
    
    words = re.findall(r"\b[a-z]{4,}\b", all_text.lower())
    keywords = list(set(w for w in words if w not in common_words))[:20]
    
    return {
        "timestamp": datetime.now().isoformat(),
        "user_message": user_msgs[-1] if user_msgs else "",
        "assistant_response": assistant_msgs[-1] if assistant_msgs[:1] else "",
        "keywords": keywords,
        "summary": _create_summary(user_msgs, assistant_msgs)
    }


def _create_summary(user_msgs: list[str], assistant_msgs: list[str]) -> str:
    """Create a brief summary of the conversation."""
    if not user_msgs:
        return ""
    
    last_user = user_msgs[-1][:200] if user_msgs else ""
    last_assistant = assistant_msgs[-1][:200] if assistant_msgs else ""
    
    return f"User asked: {last_user}... | Assistant responded: {last_assistant}..."


def save_conversation(messages: list[dict]):
    """Save a conversation to memory store."""
    if not messages or len(messages) < 2:
        return
    
    memory = _extract_key_info(messages)
    memories = _load_today_memories()
    memories.append(memory)
    _save_today_memories(memories)


def retrieve_context(query: str, limit: int = 5) -> str:
    """Retrieve relevant context from past conversations."""
    _ensure_memory_store()
    
    query_lower = query.lower()
    query_words = set(re.findall(r"\b[a-z]{4,}\b", query_lower))
    
    scored_memories = []
    
    # Search all memory files
    for memory_file in sorted(MEMORY_STORE.glob("*.json"), reverse=True)[:7]:  # Last 7 days
        try:
            memories = json.loads(memory_file.read_text())
            for memory in memories:
                score = 0
                
                # Score by keyword overlap
                memory_keywords = set(memory.get("keywords", []))
                overlap = query_words.intersection(memory_keywords)
                score += len(overlap) * 2
                
                # Score by text similarity (simple)
                user_msg = memory.get("user_message", "").lower()
                for word in query_words:
                    if word in user_msg:
                        score += 1
                
                if score > 0:
                    scored_memories.append((score, memory))
        except (json.JSONDecodeError, IOError):
            continue
    
    # Sort by score and return top results
    scored_memories.sort(key=lambda x: x[0], reverse=True)
    top_memories = scored_memories[:limit]
    
    if not top_memories:
        return ""
    
    context_parts = ["[Past conversation context]"]
    for score, memory in top_memories:
        summary = memory.get("summary", "")
        timestamp = memory.get("timestamp", "")
        context_parts.append(f"- [{timestamp}] {summary}")
    
    return "\n".join(context_parts)


def get_memory_stats() -> dict:
    """Get memory store statistics."""
    _ensure_memory_store()
    
    total_memories = 0
    total_files = 0
    
    for memory_file in MEMORY_STORE.glob("*.json"):
        total_files += 1
        try:
            memories = json.loads(memory_file.read_text())
            total_memories += len(memories)
        except (json.JSONDecodeError, IOError):
            continue
    
    return {
        "total_memories": total_memories,
        "total_files": total_files,
        "store_path": str(MEMORY_STORE)
    }


# Initialize on import
_ensure_memory_store()
