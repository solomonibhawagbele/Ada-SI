"""Task Focus Tool - Persistent goal locking across turns (Ralph loop)."""

import json
from pathlib import Path
from datetime import datetime

FOCUS_FILE = Path(__file__).parent / "skill_data" / "task_focus.json"

def get_tool_schema():
    return {
        "type": "function",
        "function": {
            "name": "task_focus",
            "description": "Persistent task focus system. Lock the agent onto a goal that persists across turns. Actions: set (lock goal), get (current goal), clear (release focus), update (progress update), list (all active goals), priority (set priority level).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["set", "get", "clear", "update", "list", "priority"],
                        "description": "Action to perform"
                    },
                    "goal": {
                        "type": "string",
                        "description": "Goal description (for set/update)"
                    },
                    "goal_id": {
                        "type": "string",
                        "description": "Goal ID (for get/clear/update/priority)"
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low"],
                        "description": "Priority level (for priority action)"
                    },
                    "progress": {
                        "type": "string",
                        "description": "Progress notes (for update action)"
                    }
                },
                "required": ["action"]
            }
        }
    }

def _load_focus():
    if FOCUS_FILE.exists():
        return json.loads(FOCUS_FILE.read_text())
    return {"goals": [], "active_goal_id": None}

def _save_focus(data):
    FOCUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    FOCUS_FILE.write_text(json.dumps(data, indent=2))

def run(action: str, goal: str = "", goal_id: str = "", priority: str = "high", progress: str = "") -> str:
    data = _load_focus()
    
    if action == "set":
        if not goal:
            return json.dumps({"error": "goal required"})
        import hashlib
        goal_hash = hashlib.md5(goal.encode()).hexdigest()[:8]
        goal_id = f"goal_{goal_hash}"
        new_goal = {
            "id": goal_id,
            "goal": goal,
            "priority": priority,
            "status": "active",
            "created_at": datetime.now().isoformat(),
            "progress": [],
            "turns_focused": 0
        }
        existing = next((i for i, g in enumerate(data["goals"]) if g["id"] == goal_id), None)
        if existing is not None:
            data["goals"][existing]["goal"] = goal
            data["goals"][existing]["priority"] = priority
        else:
            data["goals"].append(new_goal)
        data["active_goal_id"] = goal_id
        _save_focus(data)
        return json.dumps({"action": "set", "goal_id": goal_id, "goal": goal, "priority": priority, "status": "locked"})
    
    elif action == "get":
        if goal_id:
            g = next((g for g in data["goals"] if g["id"] == goal_id), None)
            if g:
                return json.dumps({"action": "get", "goal": g})
            return json.dumps({"error": f"Goal not found: {goal_id}"})
        active_id = data.get("active_goal_id")
        if active_id:
            g = next((g for g in data["goals"] if g["id"] == active_id), None)
            if g:
                g["turns_focused"] = g.get("turns_focused", 0) + 1
                _save_focus(data)
                return json.dumps({"action": "get", "active": True, "goal": g})
        return json.dumps({"action": "get", "active": False, "message": "No active goal"})
    
    elif action == "clear":
        if goal_id:
            data["goals"] = [g for g in data["goals"] if g["id"] != goal_id]
            if data["active_goal_id"] == goal_id:
                data["active_goal_id"] = None
        else:
            data["active_goal_id"] = None
        _save_focus(data)
        return json.dumps({"action": "clear", "cleared": goal_id or "active goal"})
    
    elif action == "update":
        if not goal_id:
            goal_id = data.get("active_goal_id")
        if not goal_id:
            return json.dumps({"error": "No active goal to update"})
        g = next((g for g in data["goals"] if g["id"] == goal_id), None)
        if not g:
            return json.dumps({"error": f"Goal not found: {goal_id}"})
        entry = {"timestamp": datetime.now().isoformat(), "note": progress or goal}
        g["progress"].append(entry)
        _save_focus(data)
        return json.dumps({"action": "update", "goal_id": goal_id, "progress_added": entry})
    
    elif action == "list":
        active_id = data.get("active_goal_id")
        goals_summary = []
        for g in data["goals"]:
            goals_summary.append({
                "id": g["id"],
                "goal": g["goal"],
                "priority": g["priority"],
                "status": g["status"],
                "is_active": g["id"] == active_id,
                "progress_count": len(g.get("progress", []))
            })
        return json.dumps({"action": "list", "goals": goals_summary, "active_goal_id": active_id})
    
    elif action == "priority":
        if not goal_id:
            goal_id = data.get("active_goal_id")
        if not goal_id:
            return json.dumps({"error": "No goal specified"})
        g = next((g for g in data["goals"] if g["id"] == goal_id), None)
        if not g:
            return json.dumps({"error": f"Goal not found: {goal_id}"})
        g["priority"] = priority
        _save_focus(data)
        return json.dumps({"action": "priority", "goal_id": goal_id, "new_priority": priority})
    
    return json.dumps({"error": f"Unknown action: {action}"})

if __name__ == "__main__":
    print(run("list"))
