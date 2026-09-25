import json
import os

path = os.path.join(os.environ["TEMP"], "ap-itsm-dryrun-events.jsonl")
for line in open(path, encoding="utf-8"):
    try:
        item = json.loads(line)
    except ValueError:
        head = line[:60]
        if any(f'"event": "{name}"' in head for name in ("result", "stats", "policy_event")):
            print("truncated", line[:3500])
        elif '"run_script"' in line[:400]:
            print("script-result(truncated)", line[:3000])
        continue
    event, data = item["event"], item["data"]
    if event in {"result", "stats"}:
        print(event, json.dumps(data)[:3500])
    elif event == "tool_result" and "run_script" in json.dumps(data)[:300]:
        print("script-result", json.dumps(data)[:3000])
    elif event == "policy_event":
        print("policy", json.dumps(data)[:400])
