# 🤖 Demo Agent

Minimal agentic loop (~12 lines) that connects the OpenAI tool-calling API to
the ESS-MCP servers via FastMCP's Python client. **Skills** are plain-text
markdown prompts that tell the LLM what to do.

## Quick start

```bash
pip install fastmcp openai python-dotenv aiohttp   # already in mcp_servers deps
cp .env.example .env                                # add your keys + tokens
```

### Web UI (recommended for demos)

```bash
python -m demo_agent.web          # open http://localhost:8091
```

The web UI lets you:
- Pick a **skill** from clickable pills (or type a custom prompt)
- Watch **tool calls** appear as pills in real time
- Click any tool pill to inspect its **input** and **output**
- See the **final result** rendered below
- Review **statistics** — duration, turns, tool calls, token usage, model

### CLI

```bash
python -m demo_agent.agent team-review     # run a skill from the command line
```

## Available skills

| Skill | File | Servers used |
|-------|------|--------------|
| `team-review` | `skills/team-review.md` | Workday + ServiceNow + Salesforce + Jira |
| `incident-triage` | `skills/incident-triage.md` | ServiceNow + Jira |
| `onboarding-audit` | `skills/onboarding-audit.md` | Workday + ServiceNow + Salesforce + Jira |
| `sprint-readiness` | `skills/sprint-readiness.md` | Jira + Workday + ServiceNow |

## How it works

```
agent.py          skills/*.md          MCP servers
─────────         ──────────           ───────────
connect()  ─────▶ list_tools()  ◀───── /workday/mcp
                                       /servicenow/mcp
run() loop:                            /salesforce/mcp
  OpenAI ──▶ tool_calls ──▶ call_tool  /jira/mcp
  ◀──────── results ◀──────
  repeat until final answer
```

The loop itself is intentionally tiny — all the intelligence lives in the skill
prompts and the 142 MCP tools.

## Auth: per-server Bearer tokens

Each MCP server hits a different SaaS API (Workday REST, ServiceNow REST, etc.)
so each one needs its own OAuth Bearer token. The token is injected as an HTTP
header when connecting:

```python
StreamableHttpTransport(url, headers={"Authorization": f"Bearer {token}"})
```

### How to get tokens

| Strategy | When to use | Setup |
|----------|-------------|-------|
| **Static tokens** | Dev / short demos | Acquire via `az account get-access-token`, Postman, or platform CLI. Set `ESS_<SERVER>_TOKEN`. |
| **Client credentials** | Production daemons | Register an OAuth app per platform, acquire tokens at startup. Swap the `os.getenv` call for a token-provider function. |
| **On-behalf-of (OBO)** | Delegated user context | Front-end acquires user token via auth-code flow, agent exchanges via Azure AD OBO. Same swap — just change how you get the token string. |

The agent doesn't care *how* the token was obtained — it just needs a string in
the `Authorization` header. For production, replace the `os.getenv()` lines in
`connect()` with your preferred token provider.

## Writing new skills

Create `skills/my-skill.md` with a system-prompt-style markdown file. The agent
reads it, sends it to the LLM with all discovered MCP tools, and lets the model
execute autonomously until it produces a final text answer.

```bash
python -m demo_agent.agent my-skill
```
