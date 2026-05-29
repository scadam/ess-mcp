import json
d = json.load(open("purview-diag.json"))
print("endpoint:", d.get("last_graph_endpoint"))
print("label_count:", d.get("label_count"), "graph_sourced:", d.get("any_graph_sourced"))
print("error:", d.get("last_graph_error"))
for r in d.get("policy_match_preview", []):
    print(f"  {r['label']:38s} -> {r['action']:6s}  ({r['reason'][:60]})")
