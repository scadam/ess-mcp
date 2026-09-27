"""Runs both colleagues' document steps on a Word-authored copy: find their comment, edit, reply in the thread."""
import json
import sys

from demo_agent import doc_edit

data = open(sys.argv[1], "rb").read()
steps = [
    ("HR Agent", "please add our rules for working temporarily from another country", lambda anchor: [
        {"paragraph": anchor, "mode": "insert_after",
         "text": "**Up to 20 working days:** in a rolling 12 months, in an approved country, with your line manager's "
                 "agreement (W1).\n\n**21 to 60 working days:** an exception panel decides: your HR Business "
                 "Partner, Tax & Global Mobility, Employment Counsel and your line manager (W2)."}],
     "I've added the rules under section 4 from the HR exceptions policy (W1 and W2). Accept or reject them in Review."),
    ("Compliance Agent", "review this section client data and conduct when working abroad", lambda anchor: [
        {"paragraph": anchor, "mode": "replace",
         "find": "If the VPN is unavailable, you may email documents to a personal address so that you can keep working.",
         "text": "If the VPN or an app is unavailable, stop and contact the IT Service Desk. Never forward bank "
                 "documents to a personal address (D2)."},
        {"paragraph": anchor, "mode": "insert_after",
         "text": "**Bank devices only:** handle bank data only on bank-issued devices and approved apps (D1)."}],
     "D2: replaced the personal-email workaround (it is a data breach). D1: added the bank-devices rule."),
]
for colleague, hint, edits, reply in steps:
    view = doc_edit.read(data, hint=hint, colleague=colleague, requester="Scott Adams")
    target = next(item for item in view["comments"] if item["id"] == view["target"])
    anchor = target["paragraphs"][0]
    anchored_text = next(p["text"] for p in view["paragraphs"] if p["ref"] == anchor)
    print(f"{colleague}: {len(view['comments'])} comments, target {view['target']} by {target['author']!r} -> "
          f"{anchor} ({anchored_text[:48]!r})")
    data, summary = doc_edit.apply_changes(data, author=colleague, edits=edits(anchor), reply_to=view["target"],
                                           reply=reply)
    print("   applied:", json.dumps(summary["applied"]), "| reply id:", summary["reply"])
final = doc_edit.read(data)
threads = {item["id"]: (item["author"], item.get("parent")) for item in final["comments"]}
print("comments now:", json.dumps(threads))
open(sys.argv[2], "wb").write(data)
