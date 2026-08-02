"""Cross-Platform Continuity - Sync conversations across platforms."""

import json
from pathlib import Path
from datetime import datetime

SYNC_DIR = Path(__file__).parent / "skill_data" / "sync"
MEMORY_DIR = Path(__file__).parent.parent / "memory_store"

def get_tool_schema():
    return {
        "type": "function",
        "function": {
            "name": "continuity",
            "description": "Manage cross-platform conversation continuity. Actions: push (upload current session), pull (download latest state), sync_status (check sync state).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["push", "pull", "sync_status"],
                        "description": "Action to perform"
                    },
                    "platform": {
                        "type": "string",
                        "description": "Platform name (web, cli, telegram, etc)"
                    }
                },
                "required": ["action"]
            }
        }
    }

def run(action: str, platform: str = "web") -> str:
    SYNC_DIR.mkdir(parents=True, exist_ok=True)
    if action == "push":
        today = datetime.now().strftime("%Y-%m-%d")
        source = MEMORY_DIR / f"{today}.json"
        if not source.exists():
            return json.dumps({"error": f"No session for today ({today})"})
        sync_file = SYNC_DIR / f"{platform}_{today}.json"
        data = json.loads(source.read_text())
        sync_data = {"platform": platform, "date": today, "synced_at": datetime.now().isoformat(), "data": data}
        sync_file.write_text(json.dumps(sync_data))
        return json.dumps({"action": "push", "platform": platform, "date": today, "synced": True})
    elif action == "pull":
        files = sorted(SYNC_DIR.glob("*.json"), reverse=True)
        if not files:
            return json.dumps({"action": "pull", "sessions": [], "message": "No synced sessions found"})
        sessions = []
        for f in files[:10]:
            try:
                data = json.loads(f.read_text())
                sessions.append({"file": f.name, "platform": data.get("platform", "unknown"), "date": data.get("date", "unknown"), "synced_at": data.get("synced_at", "unknown")})
            except:
                continue
        return json.dumps({"action": "pull", "sessions": sessions})
    elif action == "sync_status":
        files = list(SYNC_DIR.glob("*.json"))
        platforms = set()
        for f in files:
            try:
                data = json.loads(f.read_text())
                platforms.add(data.get("platform", "unknown"))
            except:
                pass
        return json.dumps({"action": "sync_status", "total_synced": len(files), "platforms": list(platforms)})
    return json.dumps({"error": f"Unknown action: {action}"})

if __name__ == "__main__":
    print(run("sync_status"))
