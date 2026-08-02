"""Context Compression Tool - Summarize long conversations to save context window."""

import json
from pathlib import Path

MEMORY_DIR = Path(__file__).parent.parent / "memory_store"

def get_tool_schema():
    return {
        "type": "function",
        "function": {
            "name": "compress",
            "description": "Compress/summarize a conversation to save context. Actions: summarize (create summary), stats (show conversation stats), archive (move old conversations to compressed format).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["summarize", "stats", "archive"],
                        "description": "Action to perform"
                    },
                    "date": {
                        "type": "string",
                        "description": "Date of conversation (YYYY-MM-DD)"
                    }
                },
                "required": ["action"]
            }
        }
    }

def _extract_topics(messages):
    topics = {}
    keywords = ["tool", "build", "create", "fix", "install", "search", "browser", "file", "code", "test", "deploy", "config", "memory", "schedule", "task"]
    for msg in messages:
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        for kw in keywords:
            if kw in content.lower():
                topics[kw] = topics.get(kw, 0) + 1
    return sorted(topics.keys(), key=lambda x: topics[x], reverse=True)[:5]

def _count_tokens_approx(text):
    return len(text) // 4

def run(action: str, date: str = "") -> str:
    if action == "stats":
        total_tokens = 0
        total_messages = 0
        sessions = []
        if MEMORY_DIR.exists():
            for f in sorted(MEMORY_DIR.glob("*.json"), reverse=True):
                try:
                    data = json.loads(f.read_text())
                    conversations = data if isinstance(data, list) else data.get("conversations", [])
                    session_tokens = 0
                    session_msgs = 0
                    for conv in conversations:
                        messages = conv if isinstance(conv, list) else conv.get("messages", [])
                        for msg in messages:
                            content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
                            session_tokens += _count_tokens_approx(content)
                            session_msgs += 1
                    total_tokens += session_tokens
                    total_messages += session_msgs
                    sessions.append({"date": f.stem, "tokens": session_tokens, "messages": session_msgs})
                except:
                    continue
        return json.dumps({
            "action": "stats",
            "total_tokens_approx": total_tokens,
            "total_messages": total_messages,
            "sessions": sessions[:10],
            "recommendation": "Compress old sessions if total > 100000 tokens"
        })
    elif action == "summarize":
        if not date:
            return json.dumps({"error": "date required"})
        source = MEMORY_DIR / f"{date}.json"
        if not source.exists():
            return json.dumps({"error": f"No session found for {date}"})
        data = json.loads(source.read_text())
        conversations = data if isinstance(data, list) else data.get("conversations", [])
        all_messages = []
        for conv in conversations:
            messages = conv if isinstance(conv, list) else conv.get("messages", [])
            all_messages.extend(messages)
        topics = _extract_topics(all_messages)
        user_msgs = [m for m in all_messages if isinstance(m, dict) and m.get("role") == "user"]
        assistant_msgs = [m for m in all_messages if isinstance(m, dict) and m.get("role") == "assistant"]
        summary = {
            "date": date,
            "total_messages": len(all_messages),
            "user_messages": len(user_msgs),
            "assistant_messages": len(assistant_msgs),
            "topics": topics,
            "tokens_approx": _count_tokens_approx(json.dumps(all_messages)),
            "key_exchanges": []
        }
        for msg in user_msgs[:3]:
            content = msg.get("content", "")[:100]
            summary["key_exchanges"].append({"user_said": content})
        return json.dumps({"action": "summarize", "summary": summary})
    elif action == "archive":
        archived = 0
        if MEMORY_DIR.exists():
            for f in sorted(MEMORY_DIR.glob("*.json")):
                try:
                    data = json.loads(f.read_text())
                    conversations = data if isinstance(data, list) else data.get("conversations", [])
                    total_msgs = sum(len(conv if isinstance(conv, list) else conv.get("messages", [])) for conv in conversations)
                    if total_msgs < 5:
                        archive_dir = MEMORY_DIR / "archived"
                        archive_dir.mkdir(exist_ok=True)
                        f.rename(archive_dir / f.name)
                        archived += 1
                except:
                    continue
        return json.dumps({"action": "archive", "archived": archived})
    return json.dumps({"error": f"Unknown action: {action}"})

if __name__ == "__main__":
    print(run("stats"))
