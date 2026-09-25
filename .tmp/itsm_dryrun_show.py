import json
import os

path = os.path.join(os.environ["TEMP"], "ap-itsm-dryrun-events.jsonl")
for line in open(path, encoding="utf-8"):
    item = json.loads(line)
    event, data = item["event"], item["data"]
    if event in {"result", "stats"}:
        print(event, json.dumps(data)[:3500])
    if event == "tool_result" and data.get("tool") in {"run_script"}:
        print("script-result", json.dumps(data)[:2500])
    if event == "policy_event":
        print("policy", json.dumps(data)[:400])
