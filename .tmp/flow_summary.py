import json
import os

data = json.load(open(os.path.join(os.environ["TEMP"], "ap-flows.json"), encoding="utf-8"))
lines = []
for flow in data["flows"]:
    requisition, order = flow["requisition"], flow["purchase_order"]
    lines.append(" | ".join([
        flow["service-now-request"], f"req {requisition['status']} {requisition['requester']} {requisition['total']}",
        f"po {order['status']} {order['created-at']} risk={order.get('delivery-risk')} recv={order.get('received-value')}",
        "rcpt " + str([(item["status"], item["received-by"]) for item in flow["receipts"]]),
        "inv " + str([(item["invoice-number"], item["status"], item["total"], item.get("payment-status")) for item in flow["invoices"]]),
        "sup " + flow["supplier"]["number"],
    ]))
open(os.path.join(os.environ["TEMP"], "ap-flow-summary.txt"), "w", encoding="utf-8").write("\n".join(lines))
print(len(lines))
