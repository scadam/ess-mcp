import json
import os

path = os.path.join(os.environ["TEMP"], "ap-itsm-dryrun-events.jsonl")
for line in open(path, encoding="utf-8"):
    if '"tool_result"' in line[:40] and "triage_queue.py" in line[:600]:
        text = line.split('\\"stdout\\": \\"', 1)[-1]
        text = text.replace("\\\\n", "\n").replace('\\\\\\"', '"')
        print(text[:3800])
