"""Vulnerability Scanner - Automated security assessment tool."""

import json
import subprocess
import socket
import ssl
import urllib.request
from pathlib import Path
from datetime import datetime

REPORT_DIR = Path(__file__).parent / "skill_data" / "vuln_reports"

def get_tool_schema():
    return {
        "type": "function",
        "function": {
            "name": "vuln_scan",
            "description": "Vulnerability scanner for security assessment. Actions: quick (fast scan), full (comprehensive), web (web app), ssl (SSL/TLS check), headers (security headers), cve (CVE lookup).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["quick", "full", "web", "ssl", "headers", "cve"]},
                    "target": {"type": "string", "description": "Target IP, domain, or URL"},
                    "options": {"type": "string", "description": "Additional options"}
                },
                "required": ["action", "target"]
            }
        }
    }

def _cmd(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"stdout": r.stdout[:10000], "stderr": r.stderr[:3000], "code": r.returncode}
    except Exception as e:
        return {"error": str(e)}

def _save_report(target, results):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_file = REPORT_DIR / f"{target.replace('.', '_').replace(':', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_file.write_text(json.dumps(results, indent=2))
    return str(report_file)

def run(action, target, options="{}"):
    results = {"target": target, "action": action, "timestamp": datetime.now().isoformat(), "findings": []}

    if action == "quick":
        # Port scan
        open_ports = []
        common_ports = [21, 22, 23, 25, 53, 80, 110, 143, 443, 993, 995, 3306, 3389, 5432, 8080, 8443]
        ip = socket.gethostbyname(target)
        for port in common_ports:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                if s.connect_ex((ip, port)) == 0:
                    open_ports.append(port)
                s.close()
            except:
                pass
        results["open_ports"] = open_ports
        if open_ports:
            results["findings"].append({"severity": "info", "detail": f"Open ports: {open_ports}"})

        # Service detection
        nmap = _cmd(f"nmap -sV --top-ports 100 {target} 2>/dev/null | grep open")
        results["services"] = nmap.get("stdout", "")

        _save_report(target, results)
        return json.dumps(results)

    elif action == "full":
        # Comprehensive scan
        nmap = _cmd(f"nmap -sV -sC -O -A {target} 2>/dev/null")
        results["nmap_full"] = nmap.get("stdout", "")

        # Vulnerability scripts
        vuln_scripts = _cmd(f"nmap --script vuln {target} 2>/dev/null | tail -100")
        results["vuln_scripts"] = vuln_scripts.get("stdout", "")

        # Known CVEs
        cve_check = _cmd(f"nmap --script vulners {target} 2>/dev/null | tail -50")
        results["cves"] = cve_check.get("stdout", "")

        _save_report(target, results)
        return json.dumps(results)

    elif action == "web":
        # Web application scan
        results["url"] = target

        # Check for common vulnerabilities
        tests = {
            "sqli": f"curl -s '{target}/index.php?id=1%27%20OR%201=1--' -o /dev/null -w '%{{http_code}}'",
            "xss": f"curl -s '{target}/search?q=<script>alert(1)</script>' -o /dev/null -w '%{{http_code}}'",
            "lfi": f"curl -s '{target}/page?file=../../../../etc/passwd' -o /dev/null -w '%{{http_code}}'",
            "directory_listing": f"curl -s '{target}/admin/' -o /dev/null -w '%{{http_code}}'",
            "default_creds": f"curl -s '{target}/admin' -o /dev/null -w '%{{http_code}}'"
        }

        for name, cmd in tests.items():
            r = _cmd(cmd)
            code = r.get("stdout", "").strip()
            if code and code != "404" and code != "000":
                results["findings"].append({"severity": "medium", "type": name, "response_code": code})

        # Security headers check
        headers = _cmd(f"curl -sI {target} 2>/dev/null").get("stdout", "")
        results["headers"] = headers

        security_headers = ["X-Frame-Options", "X-Content-Type-Options", "Content-Security-Policy", "Strict-Transport-Security", "X-XSS-Protection"]
        for h in security_headers:
            if h.lower() not in headers.lower():
                results["findings"].append({"severity": "low", "type": "missing_header", "header": h})

        _save_report(target, results)
        return json.dumps(results)

    elif action == "ssl":
        # SSL/TLS check
        try:
            hostname = target.replace("https://", "").replace("http://", "").split(":")[0].split("/")[0]
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(socket.socket(), server_hostname=hostname) as s:
                s.settimeout(10)
                s.connect((hostname, 443))
                cert = s.getpeercert()
                results["certificate"] = {
                    "subject": dict(x[0] for x in cert.get("subject", [])),
                    "issuer": dict(x[0] for x in cert.get("issuer", [])),
                    "notBefore": cert.get("notBefore"),
                    "notAfter": cert.get("notAfter"),
                    "serialNumber": cert.get("serialNumber")
                }
                results["protocol"] = s.version()
                results["cipher"] = s.cipher()
        except Exception as e:
            results["error"] = str(e)

        # Check for weak ciphers
        weak = _cmd(f"nmap --script ssl-enum-ciphers -p 443 {hostname} 2>/dev/null | grep -i 'weak\|grade'")
        results["weak_ciphers"] = weak.get("stdout", "")

        _save_report(target, results)
        return json.dumps(results)

    elif action == "headers":
        # Security headers analysis
        headers = _cmd(f"curl -sI {target} 2>/dev/null").get("stdout", "")
        results["raw_headers"] = headers

        checks = {
            "X-Frame-Options": {"present": False, "severity": "medium", "desc": "Clickjacking protection"},
            "X-Content-Type-Options": {"present": False, "severity": "low", "desc": "MIME type sniffing protection"},
            "Content-Security-Policy": {"present": False, "severity": "high", "desc": "XSS and injection protection"},
            "Strict-Transport-Security": {"present": False, "severity": "high", "desc": "HTTPS enforcement"},
            "X-XSS-Protection": {"present": False, "severity": "medium", "desc": "XSS filter"},
            "Referrer-Policy": {"present": False, "severity": "low", "desc": "Referrer information leakage"},
            "Permissions-Policy": {"present": False, "severity": "low", "desc": "Feature restrictions"}
        }

        for header, info in checks.items():
            if header.lower() in headers.lower():
                info["present"] = True
            else:
                results["findings"].append({"severity": info["severity"], "type": "missing_header", "header": header, "description": info["desc"]})

        results["header_analysis"] = checks
        _save_report(target, results)
        return json.dumps(results)

    elif action == "cve":
        # CVE lookup
        cve_data = _cmd(f"curl -s 'https://cve.circl.lu/api/search/{target}' 2>/dev/null | head -100")
        results["cve_data"] = cve_data.get("stdout", "")

        exploit_db = _cmd(f"curl -s 'https://www.exploit-db.com/search?q={target}' 2>/dev/null | grep -o 'CVE-[0-9]\\+-[0-9]\\+' | head -20")
        results["exploit_db"] = exploit_db.get("stdout", "")

        _save_report(target, results)
        return json.dumps(results)

    return json.dumps({"error": f"Unknown action: {action}"})


if __name__ == "__main__":
    print(run("quick", "example.com"))
