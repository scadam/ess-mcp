import collections
import json

data = json.load(open("demo_agent/tests/fixtures/workday_inbox.json", encoding="utf-8"))
tasks = data["tasks"]
print(len(tasks), sorted(data))
process = collections.Counter(task["overallProcess"].split(":")[0] for task in tasks)
print(process)
print(collections.Counter((task["overallProcess"].split(":")[0], task["descriptor"], task["stepType"], task["status"]) for task in tasks).most_common(40))
print(collections.Counter(task["due"] for task in tasks))
print(collections.Counter(task["assigned"][:10] for task in tasks).most_common(10))
hires = collections.Counter(task["subject"] for task in tasks if task["overallProcess"].startswith("Hire"))
print(len(hires), hires.most_common(5))
for task in tasks:
    if not task["overallProcess"].startswith("Hire") or task["descriptor"] != "Edit Workday Account":
        print(task["overallProcess"], "|", task["descriptor"], "|", task["stepType"], "|", task["status"], "|", task["initiator"], "|", task["subject"])
