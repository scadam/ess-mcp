"""Reproduce how the Agents SDK pre-processes a Teams group-chat @mention."""
import sys

sys.path.insert(0, r"C:\Users\scadam\AgentsToolkitProjects\ess-mcp")

from microsoft_agents.activity import Activity
from microsoft_agents.hosting.core import TurnContext
from microsoft_agents.hosting.core.app.app_options import ApplicationOptions

from demo_agent.conversation import _activity_text, _group

AGENT = "8:orgid:f9f7881a-c4c4-4dad-b9e6-b8b36bf4f2a2"


def activity(mention_id: str) -> Activity:
    return Activity.model_validate({
        "type": "message", "id": "1790258730539", "channelId": "msteams",
        "serviceUrl": "https://smba.trafficmanager.net/amer/",
        "text": "<at>Supply Chain Agent</at> run the supplier scorecard skill",
        "from": {"id": "29:admin", "name": "Admin", "aadObjectId": "11111111-1111-4111-8111-111111111111"},
        "recipient": {"id": AGENT, "name": "Supply Chain Agent", "role": "agenticUser",
                      "agenticUserId": "f9f7881a-c4c4-4dad-b9e6-b8b36bf4f2a2",
                      "agenticAppId": "cdf4df7f-bc0a-4381-883e-fb7f87b9d527"},
        "conversation": {"id": "19:e0ed56ff64f94ce3a74db33849d1ef55@thread.v2", "conversationType": "groupChat",
                         "isGroup": True, "tenantId": "17371818-07cb-47f2-9ca3-18f96f0125d7"},
        "entities": [{"type": "mention", "text": "<at>Supply Chain Agent</at>",
                      "mentioned": {"id": mention_id, "name": "Supply Chain Agent"}}],
    })


print("SDK default remove_recipient_mention =", ApplicationOptions().remove_recipient_mention)
for label, mention_id in (("mention id == recipient.id", AGENT), ("mention id != recipient.id", "29:other-format")):
    a = activity(mention_id)
    print(f"\n[{label}] group={_group(a)}")
    print("  before SDK :", repr(a.text), "->", _activity_text(a, a.recipient.id))
    a.text = TurnContext.remove_recipient_mention(a)
    print("  after SDK  :", repr(a.text), "->", _activity_text(a, a.recipient.id))
