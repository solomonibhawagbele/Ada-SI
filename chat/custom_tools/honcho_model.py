"""Honcho User Model - Dialectic user profiling with personality analysis."""

import json
from pathlib import Path
from datetime import datetime

HONCHO_FILE = Path(__file__).parent / "skill_data" / "honcho_profile.json"

def _load_profile():
    if HONCHO_FILE.exists():
        return json.loads(HONCHO_FILE.read_text())
    return {
        "identity": {"name": "", "pronouns": ""},
        "personality": {"traits": [], "communication_style": "", "emotional_pattern": ""},
        "preferences": {"topics": [], "tools": [], "response_style": ""},
        "behaviors": {"active_hours": [], "session_frequency": "", "common_tasks": []},
        "relationships": {"trust_level": "building", "interaction_count": 0},
        "evolution": {"first_seen": datetime.now().isoformat(), "last_seen": "", "growth_notes": []}
    }

def _save_profile(profile):
    HONCHO_FILE.parent.mkdir(parents=True, exist_ok=True)
    HONCHO_FILE.write_text(json.dumps(profile, indent=2))

def get_tool_schema():
    return {
        "type": "function",
        "function": {
            "name": "honcho_model",
            "description": "Advanced user profiling. Actions: update (update any profile section), get (get full profile), analyze (analyze user patterns from recent conversations), insight (get a specific insight about the user).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["update", "get", "analyze", "insight"],
                        "description": "Action to perform"
                    },
                    "section": {
                        "type": "string",
                        "enum": ["identity", "personality", "preferences", "behaviors", "relationships", "evolution"],
                        "description": "Profile section to update"
                    },
                    "data": {
                        "type": "string",
                        "description": "JSON string of data to update with"
                    },
                    "insight_type": {
                        "type": "string",
                        "description": "Type of insight: communication, needs, patterns, growth"
                    }
                },
                "required": ["action"]
            }
        }
    }

def run(action: str, section: str = "", data: str = "", insight_type: str = "") -> str:
    profile = _load_profile()
    if action == "update":
        if not section or not data:
            return json.dumps({"error": "section and data required"})
        try:
            update_data = json.loads(data)
        except:
            update_data = {"value": data}
        if section in profile:
            if isinstance(profile[section], dict):
                profile[section].update(update_data)
            else:
                profile[section] = update_data
        else:
            profile[section] = update_data
        profile["evolution"]["last_seen"] = datetime.now().isoformat()
        _save_profile(profile)
        return json.dumps({"action": "update", "section": section, "updated": True})
    elif action == "get":
        profile["evolution"]["last_seen"] = datetime.now().isoformat()
        _save_profile(profile)
        return json.dumps({"action": "get", "profile": profile})
    elif action == "analyze":
        interactions = profile["relationships"].get("interaction_count", 0) + 1
        profile["relationships"]["interaction_count"] = interactions
        if interactions > 50:
            profile["relationships"]["trust_level"] = "established"
        elif interactions > 10:
            profile["relationships"]["trust_level"] = "growing"
        profile["evolution"]["last_seen"] = datetime.now().isoformat()
        _save_profile(profile)
        return json.dumps({
            "action": "analyze",
            "interactions": interactions,
            "trust_level": profile["relationships"]["trust_level"],
            "profile_summary": {
                "name": profile["identity"].get("name", "unknown"),
                "top_topics": profile["preferences"].get("topics", [])[:3],
                "communication_style": profile["personality"].get("communication_style", "unknown")
            }
        })
    elif action == "insight":
        insights = {
            "communication": profile["personality"].get("communication_style", "Not yet analyzed. Observe how the user communicates and update."),
            "needs": profile["preferences"].get("topics", ["Not enough data yet"]),
            "patterns": profile["behaviors"].get("common_tasks", ["Not enough data yet"]),
            "growth": profile["evolution"].get("growth_notes", ["No growth notes yet"])
        }
        return json.dumps({"action": "insight", "type": insight_type or "all", "insights": insights})
    return json.dumps({"error": f"Unknown action: {action}"})

if __name__ == "__main__":
    print(run("get"))
