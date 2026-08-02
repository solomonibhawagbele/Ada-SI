"""Terminal Backends Tool - Run commands on different systems."""

import json
import subprocess
from pathlib import Path

BACKENDS_FILE = Path(__file__).parent / "skill_data" / "backends.json"

def _load_backends():
    if BACKENDS_FILE.exists():
        return json.loads(BACKENDS_FILE.read_text())
    return {
        "backends": [
            {"name": "local", "type": "local", "status": "active", "description": "Local Codespace"},
            {"name": "vps", "type": "ssh", "host": "153.75.224.162", "user": "root", "status": "configured", "description": "Ubuntu VPS"}
        ],
        "active": "local"
    }

def _save_backends(data):
    BACKENDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    BACKENDS_FILE.write_text(json.dumps(data, indent=2))

def get_tool_schema():
    return {
        "type": "function",
        "function": {
            "name": "terminal_backends",
            "description": "Run commands on different systems. Actions: list (show backends), switch (change active backend), run (execute command on active backend), add (register a new backend).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "switch", "run", "add"],
                        "description": "Action to perform"
                    },
                    "backend": {
                        "type": "string",
                        "description": "Backend name (for switch/run)"
                    },
                    "command": {
                        "type": "string",
                        "description": "Command to run (for run action)"
                    },
                    "host": {
                        "type": "string",
                        "description": "SSH host (for add)"
                    },
                    "user": {
                        "type": "string",
                        "description": "SSH user (for add)"
                    }
                },
                "required": ["action"]
            }
        }
    }

def run(action: str, backend: str = "", command: str = "", host: str = "", user: str = "") -> str:
    data = _load_backends()
    if action == "list":
        return json.dumps({"action": "list", "backends": data["backends"], "active": data["active"]})
    elif action == "switch":
        if not backend:
            return json.dumps({"error": "backend name required"})
        names = [b["name"] for b in data["backends"]]
        if backend not in names:
            return json.dumps({"error": f"Unknown backend: {backend}. Available: {names}"})
        data["active"] = backend
        _save_backends(data)
        return json.dumps({"action": "switch", "active": backend})
    elif action == "run":
        if not command:
            return json.dumps({"error": "command required"})
        active = data["active"]
        backend_info = next((b for b in data["backends"] if b["name"] == active), None)
        if not backend_info:
            return json.dumps({"error": f"Active backend not found: {active}"})
        if backend_info["type"] == "local":
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30, cwd="/workspaces/Ada-SI")
            return json.dumps({"backend": active, "command": command, "returncode": result.returncode, "output": result.stdout[:5000], "stderr": result.stderr[:2000]})
        elif backend_info["type"] == "ssh":
            ssh_cmd = f"ssh {backend_info.get(user,root)}@{backend_info[host]} \"{command}\""
            result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True, timeout=30)
            return json.dumps({"backend": active, "command": command, "returncode": result.returncode, "output": result.stdout[:5000], "stderr": result.stderr[:2000]})
        return json.dumps({"error": f"Unknown backend type: {backend_info[type]}"})
    elif action == "add":
        if not backend or not host:
            return json.dumps({"error": "backend name and host required"})
        data["backends"].append({"name": backend, "type": "ssh", "host": host, "user": user or "root", "status": "configured", "description": f"SSH: {host}"})
        _save_backends(data)
        return json.dumps({"action": "add", "name": backend, "host": host})
    return json.dumps({"error": f"Unknown action: {action}"})

if __name__ == "__main__":
    print(run("list"))
