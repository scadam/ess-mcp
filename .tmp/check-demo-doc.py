"""Checks the demo draft: the editor reads it, the demo comment targets resolve, and both colleagues' edits apply."""
import json
import sys

from demo_agent import doc_edit

data = open(sys.argv[1], "rb").read()
view = doc_edit.read(data)
paragraphs = view["paragraphs"]
print(f"{len(paragraphs)} paragraphs, {len({p['ref'] for p in paragraphs})} unique refs, "
      f"refs all stable: {all(p['ref'].startswith('p') for p in paragraphs)}")
by_text = {p["text"]: p for p in paragraphs}
section4 = next(p for p in paragraphs if p["text"].startswith("Talk to your line manager"))
section5 = next(p for p in paragraphs if p["text"].startswith("Use your bank laptop"))
heading4 = next(p for p in paragraphs if p["text"].startswith("4. Working temporarily"))
print("section 4 anchor:", section4["ref"], "| section 5 anchor:", section5["ref"], "| heading:", heading4["ref"])
hr, _ = doc_edit.apply_changes(data, author="HR Agent", edits=[
    {"paragraph": section4["ref"], "mode": "insert_after",
     "text": "**Up to 20 working days:** in a rolling 12 months, in an approved country, with your line manager's "
             "agreement (W1).\n\n**21 to 60 working days:** an exception panel decides (W2)."}])
both, summary = doc_edit.apply_changes(hr, author="Compliance Agent", edits=[
    {"paragraph": section5["ref"], "mode": "replace",
     "find": "If the VPN is unavailable, you may email documents to a personal address so that you can keep working.",
     "text": "If the VPN or an app is unavailable, stop and contact the IT Service Desk; never forward bank documents "
             "to a personal address (D2)."},
    {"paragraph": section5["ref"], "mode": "insert_after",
     "text": "**Bank devices only:** handle bank data only on bank-issued devices and approved apps (D1)."}])
after = doc_edit.read(both)
print("tracked paragraphs after both edits:", sum(1 for p in after["paragraphs"] if p.get("trackedChanges")),
      "| applied:", json.dumps(summary["applied"]))
open(sys.argv[2], "wb").write(both) if len(sys.argv) > 2 else None
