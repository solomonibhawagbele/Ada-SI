"""Skills Hub Tool - Browse and install community skills."""

import json
import httpx
from pathlib import Path

SKILLS_DIR = Path(__file__).parent / "skill_data" / "installed_skills"

def get_tool_schema():
    return {
        "type": "function",
        "function": {
            "name": "skills_hub",
            "description": "Browse and install community skills from agentskills.io. Actions: search (find skills), install (add a skill), list (show installed skills), info (get skill details).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["search", "install", "list", "info"],
                        "description": "Action to perform"
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query (for search)"
                    },
                    "skill_name": {
                        "type": "string",
                        "description": "Skill name (for install/info)"
                    }
                },
                "required": ["action"]
            }
        }
    }

LOCAL_SKILLS = [
    {"name": "shell", "description": "Run shell commands", "category": "system", "author": "ada"},
    {"name": "filesystem", "description": "Read/write files", "category": "system", "author": "ada"},
    {"name": "browser", "description": "Browse the web", "category": "web", "author": "ada"},
    {"name": "web_search", "description": "Search the web", "category": "web", "author": "ada"},
    {"name": "cron", "description": "Schedule tasks", "category": "automation", "author": "ada"},
    {"name": "subagent", "description": "Spawn parallel agents", "category": "intelligence", "author": "ada"},
    {"name": "calculator", "description": "Math operations", "category": "utility", "author": "ada"},
    {"name": "voice_transcribe", "description": "Transcribe audio", "category": "media", "author": "ada"},
    {"name": "tts_speak", "description": "Text to speech", "category": "media", "author": "ada"},
]

def run(action: str, query: str = "", skill_name: str = "") -> str:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    if action == "search":
        if not query:
            return json.dumps({"error": "query required"})
        query_lower = query.lower()
        results = [s for s in LOCAL_SKILLS if query_lower in s["name"].lower() or query_lower in s["description"].lower()]
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(f"https://agentskills.io/api/search?q={query}")
                if resp.status_code == 200:
                    remote = resp.json()
                    results.extend(remote if isinstance(remote, list) else [])
        except:
            pass
        return json.dumps({"action": "search", "query": query, "results": results})
    elif action == "install":
        if not skill_name:
            return json.dumps({"error": "skill_name required"})
        skill_file = SKILLS_DIR / f"{skill_name}.json"
        local = next((s for s in LOCAL_SKILLS if s["name"] == skill_name), None)
        if local:
            skill_file.write_text(json.dumps(local, indent=2))
            return json.dumps({"action": "install", "skill_name": skill_name, "status": "installed_locally"})
        return json.dumps({"action": "install", "skill_name": skill_name, "status": "not_found"})
    elif action == "list":
        installed = [f.stem for f in SKILLS_DIR.glob("*.json")]
        return json.dumps({"action": "list", "installed": installed, "available": [s["name"] for s in LOCAL_SKILLS]})
    elif action == "info":
        if not skill_name:
            return json.dumps({"error": "skill_name required"})
        skill = next((s for s in LOCAL_SKILLS if s["name"] == skill_name), None)
        if skill:
            return json.dumps({"action": "info", "skill": skill})
        return json.dumps({"error": f"Skill not found: {skill_name}"})
    return json.dumps({"error": f"Unknown action: {action}"})

if __name__ == "__main__":
    print(run("list"))
