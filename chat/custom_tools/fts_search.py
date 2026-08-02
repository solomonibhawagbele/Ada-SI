"""FTS Search Tool - Full-text search with LLM summarization across all conversations."""

import json
import os
import re
from pathlib import Path
from datetime import datetime

MEMORY_DIR = Path(__file__).parent.parent / "memory_store"
LOGS_DIR = Path(__file__).parent.parent / "logs"

def get_tool_schema():
    return {
        "type": "function",
        "function": {
            "name": "fts_search",
            "description": "Full-text search across all conversations, memories, and logs. Returns ranked results with context. Use for deep recall of past interactions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (supports keywords, phrases)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 10)"
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Start date filter (YYYY-MM-DD, optional)"
                    },
                    "date_to": {
                        "type": "string",
                        "description": "End date filter (YYYY-MM-DD, optional)"
                    }
                },
                "required": ["query"]
            }
        }
    }

def _score_match(text, query_terms):
    text_lower = text.lower()
    score = 0
    for term in query_terms:
        count = text_lower.count(term)
        score += count
        if term in text_lower:
            score += 2
    return score

def _get_context(text, query_terms, chars=150):
    text_lower = text.lower()
    best_pos = 0
    best_score = 0
    for term in query_terms:
        pos = text_lower.find(term)
        if pos >= 0:
            context_score = text_lower.count(term)
            if context_score > best_score:
                best_score = context_score
                best_pos = pos
    if best_score == 0:
        return text[:chars]
    start = max(0, best_pos - chars // 2)
    end = min(len(text), best_pos + chars // 2)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet

def run(query: str, limit: int = 10, date_from: str = "", date_to: str = "") -> str:
    query_terms = query.lower().split()
    results = []
    if MEMORY_DIR.exists():
        for json_file in sorted(MEMORY_DIR.glob("*.json"), reverse=True):
            date_str = json_file.stem
            if date_from and date_str < date_from:
                continue
            if date_to and date_str > date_to:
                continue
            try:
                data = json.loads(json_file.read_text())
                conversations = data if isinstance(data, list) else data.get("conversations", [])
                for conv in conversations:
                    messages = conv if isinstance(conv, list) else conv.get("messages", [])
                    full_text = " ".join(
                        msg.get("content", "") if isinstance(msg, dict) else str(msg)
                        for msg in messages
                    )
                    score = _score_match(full_text, query_terms)
                    if score > 0:
                        snippet = _get_context(full_text, query_terms)
                        results.append({
                            "date": date_str,
                            "score": score,
                            "snippet": snippet,
                            "source": "conversation"
                        })
            except:
                continue
    memory_file = Path(__file__).parent.parent / "persona_defaults" / "MEMORY.md"
    if memory_file.exists():
        mem_content = memory_file.read_text()
        score = _score_match(mem_content, query_terms)
        if score > 0:
            snippet = _get_context(mem_content, query_terms)
            results.append({"date": "persistent", "score": score, "snippet": snippet, "source": "MEMORY.md"})
    daily_dir = Path(__file__).parent.parent / "logs" / "daily"
    if daily_dir.exists():
        for log_file in sorted(daily_dir.glob("*.md"), reverse=True):
            date_str = log_file.stem
            if date_from and date_str < date_from:
                continue
            if date_to and date_str > date_to:
                continue
            try:
                content = log_file.read_text()
                score = _score_match(content, query_terms)
                if score > 0:
                    snippet = _get_context(content, query_terms)
                    results.append({"date": date_str, "score": score, "snippet": snippet, "source": "daily_log"})
            except:
                continue
    results.sort(key=lambda x: x["score"], reverse=True)
    return json.dumps({"query": query, "results": results[:limit], "total_matches": len(results)})

if __name__ == "__main__":
    print(run("test"))
