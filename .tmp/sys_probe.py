"""Read-only probe of the demo ServiceNow and Salesforce orgs. Prints metadata only, never credentials."""
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "infra" / "caldova"))
from deployment_support import Vault  # noqa: E402
from validate_mcp import backend_token  # noqa: E402

SN = "https://dev407392.service-now.com"
SF = "https://microsoft-28a-dev-ed.develop.my.salesforce.com"


def sn(client, path, **params):
    r = client.get(f"{SN}{path}", params=params)
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:200])


def main():
    vault = Vault()
    sn_token, how = backend_token("servicenow", vault)
    print("servicenow token:", how, bool(sn_token))
    with httpx.Client(timeout=40, headers={"Authorization": f"Bearer {sn_token}", "Accept": "application/json"}) as c:
        for name in ("glide.email.smtp.active", "glide.email.read.active", "glide.servlet.uri", "instance_name"):
            code, body = sn(c, "/api/now/table/sys_properties", sysparm_query=f"name={name}", sysparm_fields="name,value")
            print("prop", name, code, body.get("result") if isinstance(body, dict) else body)
        for table in ("incident", "alm_hardware", "cmdb_ci_computer", "sys_user", "sc_cat_item", "kb_knowledge", "sys_script", "sys_email", "cmdb_ci_appl", "cmdb_ci_business_app"):
            r = c.get(f"{SN}/api/now/stats/{table}", params={"sysparm_count": "true"})
            print("count", table, r.status_code, r.json().get("result", {}).get("stats", {}).get("count") if r.status_code == 200 else r.text[:120])
        code, body = sn(c, "/api/now/table/sys_user_group", sysparm_fields="name,sys_id", sysparm_limit="40",
                        sysparm_query="nameLIKEdesk^ORnameLIKEhardware^ORnameLIKEapplication^ORnameLIKEautopilot")
        print("groups", code, [g["name"] for g in body.get("result", [])] if isinstance(body, dict) else body)
        code, body = sn(c, "/api/now/table/sys_script", sysparm_fields="name,collection,active", sysparm_query="nameLIKEAutopilot")
        print("business rules", code, body.get("result") if isinstance(body, dict) else body)
        code, body = sn(c, "/api/now/table/sys_email", sysparm_fields="type,state,subject,sys_created_on", sysparm_limit="5",
                        sysparm_query="ORDERBYDESCsys_created_on")
        print("recent email", code, body.get("result") if isinstance(body, dict) else body)
        code, body = sn(c, "/api/now/table/sys_user", sysparm_fields="user_name,email,name", sysparm_limit="10",
                        sysparm_query="emailLIKEcaldova")
        print("caldova users in SN", code, body.get("result") if isinstance(body, dict) else body)
        code, body = sn(c, "/api/now/table/incident", sysparm_fields="number,short_description,state,caller_id,assignment_group", sysparm_limit="5",
                        sysparm_display_value="true", sysparm_query="ORDERBYDESCsys_created_on")
        print("recent incidents", code, json.dumps(body.get("result") if isinstance(body, dict) else body)[:1500])
        code, body = sn(c, "/api/now/table/alm_hardware", sysparm_fields="asset_tag,display_name,assigned_to,warranty_expiration,install_status,model_category",
                        sysparm_limit="5", sysparm_display_value="true", sysparm_query="assigned_toISNOTEMPTY")
        print("hardware", code, json.dumps(body.get("result") if isinstance(body, dict) else body)[:1500])

    sf_token, how = backend_token("salesforce", vault)
    print("salesforce token:", how, bool(sf_token))
    with httpx.Client(timeout=40, headers={"Authorization": f"Bearer {sf_token}", "Accept": "application/json"}) as c:
        def q(soql, tooling=False):
            base = "/services/data/v61.0/tooling/query" if tooling else "/services/data/v61.0/query"
            r = c.get(f"{SF}{base}", params={"q": soql})
            return r.status_code, (r.json().get("records") if r.status_code == 200 else r.text[:300])
        print("org", q("SELECT OrganizationType, IsSandbox, Name FROM Organization"))
        print("users", q("SELECT Name, Username, Email, Profile.Name, IsActive, UserType FROM User WHERE IsActive = true LIMIT 20"))
        print("case count", q("SELECT COUNT() FROM Case"))
        print("cases", q("SELECT CaseNumber, Subject, Status, Type, Origin, Priority, Owner.Name FROM Case ORDER BY CreatedDate DESC LIMIT 5"))
        print("triggers", q("SELECT Name, TableEnumOrId, Status FROM ApexTrigger", tooling=True))
        print("classes", q("SELECT Name FROM ApexClass WHERE NamespacePrefix = null LIMIT 20", tooling=True))
        print("remote sites", q("SELECT SiteName, EndpointUrl, IsActive FROM RemoteProxy", tooling=True))
        r = c.get(f"{SF}/services/data/v61.0/sobjects/Case/describe")
        if r.status_code == 200:
            fields = {f["name"]: f for f in r.json()["fields"]}
            for name in ("Type", "Reason", "Origin", "Status", "Priority"):
                print("picklist", name, [v["value"] for v in fields[name].get("picklistValues", []) if v.get("active")])
            print("custom fields", [n for n in fields if n.endswith("__c")])
        else:
            print("describe", r.status_code, r.text[:200])
        r = c.get(f"{SF}/services/data/v61.0/limits")
        if r.status_code == 200:
            limits = r.json()
            for key in ("DailyApiRequests", "DailyAsyncApexExecutions", "SingleEmail", "MassEmail", "DailyStandardVolumePlatformEvents"):
                print("limit", key, limits.get(key))


if __name__ == "__main__":
    main()
