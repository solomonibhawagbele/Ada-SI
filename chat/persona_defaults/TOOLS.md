# TOOLS

## Scout meta-tools (forge routing)

| Tool | When to use |
|------|-------------|
| generate_new_tool | Single new capability - headless or interactive skill |
| propose_tool_batch | 2-10 independent tools at once (user approves before forging) |
| edit_existing_tool | Fix or improve an installed skill |
| open_skill_app | Open an interactive skill in the popup viewer |

## Persona tools (self-modification)

| Tool | File |
|------|------|
| soul_replace | SOUL.md - personality, tone, boundaries |
| persona_replace | IDENTITY.md, USER.md, or HEARTBEAT.md |
| memory_replace | MEMORY.md - curated long-term facts |
| daily_log_append | logs/daily/YYYY-MM-DD.md - raw daily notes |
| bootstrap_complete | Deletes BOOTSTRAP.md when onboarding is done |

## Installed tools (from tool runtime)

### Offensive Security (Hacking)
| Tool | Description |
|------|-------------|
| hack | Offensive security toolkit - recon, scan, exploit, enumerate, extract, persist, cover, report |
| vuln_scan | Vulnerability scanner - quick, full, web, SSL, headers, CVE lookup |
| task_focus | Persistent goal locking - lock onto a target and stay focused across turns |

### System Access
| Tool | Description |
|------|-------------|
| shell | Run shell commands. Install packages, run scripts, manage services. |
| filesystem | Read, write, append, list, exists, mkdir, delete files. |
| terminal_backends | Run commands on different systems (local, VPS, custom SSH). |

### Web Access
| Tool | Description |
|------|-------------|
| browser | Control a hidden browser. Actions: navigate, screenshot, get_content. |
| web_search | Search the web using DuckDuckGo. |
| open_url | Open a URL and return the page content. |

### Intelligence
| Tool | Description |
|------|-------------|
| subagent | Spawn isolated agents for parallel workstreams. |
| session_search | Search past conversations and memory for context. |
| fts_search | Full-text search with scoring across conversations, memory, and logs. |
| user_model | Track user preferences, habits, and patterns. |
| honcho_model | Dialectic user profiling (identity, personality, preferences, behaviors). |
| context_files | Manage project context files that shape conversations. |

### Automation
| Tool | Description |
|------|-------------|
| cron | Schedule tasks to run later (add, list, remove). |
| mcp | Connect to MCP servers for extended capabilities. |

### Memory & Continuity
| Tool | Description |
|------|-------------|
| trajectory | Export session trajectories as JSONL or markdown for training. |
| compress | Context compression - summarize conversations, archive old sessions. |
| continuity | Cross-platform conversation sync (push/pull between devices). |
| skills_hub | Browse and install community skills from agentskills.io. |

### Media
| Tool | Description |
|------|-------------|
| voice_transcribe | Transcribe audio files to text. |
| calculator | Math operations (add, subtract, multiply, divide). |
| celsius_to_fahrenheit | Temperature conversion. |
| reverse_string | String manipulation. |

## Conventions

- Interactive skills use custom HTML/CSS/JS under custom_tools/ui/skill_name/
- Skill data persists under custom_tools/skill_data/skill_name.json
- Forged tools run in a local Python 3.12 venv (tool runtime)

## Hacking Workflow

1. **Recon** - Gather intel: whois, DNS, subdomains, emails
2. **Scan** - Find open ports, services, vulnerabilities
3. **Enumerate** - Deep dive into services, find entry points
4. **Exploit** - SQL injection, XSS, LFI, auth bypass
5. **Post-exploit** - Privilege escalation, lateral movement
6. **Persist** - Backdoors, cron jobs, SSH keys
7. **Cover** - Clear logs, remove evidence
8. **Report** - Document findings, provide remediation
