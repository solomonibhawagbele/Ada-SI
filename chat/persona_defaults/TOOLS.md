# TOOLS

## Scout meta-tools (forge routing)

| Tool | When to use |
|------|-------------|
| `generate_new_tool` | Single new capability — headless or interactive skill |
| `propose_tool_batch` | 2–10 independent tools at once (user approves before forging) |
| `edit_existing_tool` | Fix or improve an installed skill |
| `open_skill_app` | Open an interactive skill in the popup viewer |

## Persona tools (self-modification)

| Tool | File |
|------|------|
| `soul_replace` | SOUL.md — personality, tone, boundaries |
| `persona_replace` | IDENTITY.md, USER.md, or HEARTBEAT.md |
| `memory_replace` | MEMORY.md — curated long-term facts |
| `daily_log_append` | logs/daily/YYYY-MM-DD.md — raw daily notes |
| `bootstrap_complete` | Deletes BOOTSTRAP.md when onboarding is done |

## Installed tools (from tool runtime)

| Tool | Description |
|------|-------------|
| `browser` | Control a hidden browser. Actions: navigate, click, type, screenshot, get_content, get_html, back, forward, scroll. Use for any web interaction. |
| `web_search` | Search the web using DuckDuckGo. Use when the user asks a question requiring up-to-date info, facts, news, or general knowledge. |
| `open_url` | Open a URL and return the page content. Use when user asks to visit a specific URL. |

## Conventions

- Interactive skills use custom HTML/CSS/JS under `custom_tools/ui/<skill_name>/`
- Skill data persists under `custom_tools/skill_data/<skill_name>.json`
- Forged tools run in a local Python 3.12 venv (tool runtime)
