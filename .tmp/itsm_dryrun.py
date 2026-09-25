"""Live DRY RUN of the zero-touch service desk skill: reads ServiceNow, changes nothing. Prints a compact event log."""

import json
import os
import subprocess
import sys
import time

import httpx

BASE = "https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io"
env = dict(os.environ, AZURE_CONFIG_DIR=os.path.join(os.environ["LOCALAPPDATA"], "ess-mcp", "azure-caldova74201480"))
token = subprocess.run(["az.cmd", "account", "get-access-token", "--scope",
                        "api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user", "--query", "accessToken", "-o", "tsv"],
                       env=env, capture_output=True, text=True, check=True).stdout.strip()
body = {"prompt": "Work the service desk queue. Resolve everything you can without a person, and show me what still needs one.",
        "skill": "zero-touch-service-desk", "dryRun": True, "servers": ["servicenow"], "title": "Zero-Touch Service Desk (dry run)"}
started = time.time()
counts: dict[str, int] = {}
out = open(os.path.join(os.environ["TEMP"], "ap-itsm-dryrun-events.jsonl"), "w", encoding="utf-8")
with httpx.Client(timeout=httpx.Timeout(1500, connect=30)) as client:
    with client.stream("POST", f"{BASE}/api/run", json=body, headers={"Authorization": f"Bearer {token}"}) as resp:
        print("status", resp.status_code)
        if resp.status_code != 200:
            print(resp.read().decode()[:500])
            sys.exit(1)
        event = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event:
                data = json.loads(line[6:])
                out.write(json.dumps({"event": event, "data": data})[:4000] + "\n")
                counts[event] = counts.get(event, 0) + 1
                t = f"{time.time() - started:6.0f}s"
                if event == "turn" and data.get("phase") == "starting":
                    print(t, "turn", data.get("turn"), data.get("model"), data.get("role"))
                elif event in {"subagent", "script", "artifact", "approval"}:
                    print(t, event, json.dumps({k: v for k, v in data.items() if k in {"name", "status", "model", "script", "exitCode", "path", "summary", "tool", "turns"}})[:300])
                elif event == "policy_event":
                    print(t, "policy", data.get("action"), data.get("tool"), str(data.get("reason"))[:160])
                elif event == "tool_call":
                    print(t, "call", data.get("server") or "", data.get("tool") or data.get("name") or "", json.dumps(data.get("args") or data.get("arguments") or {})[:140])
                elif event in {"answer", "done", "final", "error"}:
                    print(t, event, json.dumps(data)[:3000])
                event = None
out.close()
print("counts", counts, "elapsed", round(time.time() - started))
