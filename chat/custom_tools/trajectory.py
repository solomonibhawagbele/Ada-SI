"""Trajectory Generation Tool - Export conversation trajectories for training."""

import json
from pathlib import Path
from datetime import datetime

MEMORY_DIR = Path(__file__).parent.parent / "memory_store"
TRAJ_DIR = Path(__file__).parent / "skill_data" / "trajectories"

def get_tool_schema():
    return {
        "type": "function",
        "function": {
            "name": "trajectory",
            "description": "Export conversation trajectories for training data. Actions: export (export a session), list (list exportable sessions), compress (summarize a trajectory).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["export", "list", "compress"],
                        "description": "Action to perform"
                    },
                    "date": {
                        "type": "string",
                        "description": "Date of session to export (YYYY-MM-DD)"
                    },
                    "format": {
                        "type": "string",
                        "enum": ["jsonl", "markdown"],
                        "description": "Export format (default jsonl)"
                    }
                },
                "required": ["action"]
            }
        }
    }

def run(action: str, date: str = "", format: str = "jsonl") -> str:
    if action == "list":
        sessions = []
        if MEMORY_DIR.exists():
            for f in sorted(MEMORY_DIR.glob("*.json"), reverse=True):
                sessions.append({"date": f.stem, "size": f.stat().st_size})
        return json.dumps({"action": "list", "sessions": sessions})
    elif action == "export":
        if not date:
            return json.dumps({"error": "date required"})
        source = MEMORY_DIR / f"{date}.json"
        if not source.exists():
            return json.dumps({"error": f"No session found for {date}"})
        data = json.loads(source.read_text())
        TRAJ_DIR.mkdir(parents=True, exist_ok=True)
        if format == "jsonl":
            out_file = TRAJ_DIR / f"{date}.jsonl"
            lines = []
            conversations = data if isinstance(data, list) else data.get("conversations", [])
            for conv in conversations:
                messages = conv if isinstance(conv, list) else conv.get("messages", [])
                for msg in messages:
                    if isinstance(msg, dict):
                        lines.append(json.dumps(msg))
            out_file.write_text("\n".join(lines))
        else:
            out_file = TRAJ_DIR / f"{date}.md"
            lines = [f"# Session {date}\n"]
            conversations = data if isinstance(data, list) else data.get("conversations", [])
            for conv in conversations:
                messages = conv if isinstance(conv, list) else conv.get("messages", [])
                for msg in messages:
                    if isinstance(msg, dict):
                        role = msg.get("role", "unknown")
                        content = msg.get("content", "")
                        lines.append(f"**{role}**: {content}\n")
            out_file.write_text("\n".join(lines))
        return json.dumps({"action": "export", "date": date, "format": format, "file": str(out_file), "lines": len(lines)})
    elif action == "compress":
        if not date:
            return json.dumps({"error": "date required"})
        source = MEMORY_DIR / f"{date}.json"
        if not source.exists():
            return json.dumps({"error": f"No session found for {date}"})
        data = json.loads(source.read_text())
        conversations = data if isinstance(data, list) else data.get("conversations", [])
        total_messages = sum(len(conv if isinstance(conv, list) else conv.get("messages", [])) for conv in conversations)
        topics = set()
        for conv in conversations:
            messages = conv if isinstance(conv, list) else conv.get("messages", [])
            for msg in messages:
                content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
                words = content.lower().split()
                for w in words:
                    if len(w) > 5:
                        topics.add(w)
        return json.dumps({
            "action": "compress",
            "date": date,
            "total_messages": total_messages,
            "topics": list(topics)[:20],
            "summary": f"Session with {total_messages} messages covering {len(topics)} unique terms"
        })
    return json.dumps({"error": f"Unknown action: {action}"})

if __name__ == "__main__":
    print(run("list"))
