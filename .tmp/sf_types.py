import json
import os

samples = json.load(open(os.path.join(os.environ["TEMP"], "ap-data-samples.json"), encoding="utf-8"))
value = samples["salesforce"]["list_cases"]
value = value.get("text", value) if isinstance(value, dict) else value
data = json.loads(value) if isinstance(value, str) else value
print(data.get("compliance_types"))
print([(case["case_number"], case["status"], case["type"], case["subject"][:60]) for case in data.get("cases", [])])
