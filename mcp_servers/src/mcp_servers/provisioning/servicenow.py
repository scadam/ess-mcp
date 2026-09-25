"""Idempotent provisioning for the case desk in the configured ServiceNow instance (Table and Attachment APIs).

Modes (python -m mcp_servers.provisioning.servicenow <mode> [scenario ...]):
  setup  groups, demo people with the roles the MCP tools need (and a sign-in password when
         AUTOPILOT_DEMO_USER_PASSWORD is set), assets, the loaner catalog item, webhook properties and the signed
         business rule that rings the Autopilot host whenever an incident in the desk's queue changes.
  demo   raise the demo incidents (battery, lockout; default both) that open cases on the desk.
  reset  close the open demo incidents and their tasks so the next demo starts clean (run setup afterwards to
         restore lock-outs, memberships and devices).
Needs the ServiceNow MCP server's settings plus AUTOPILOT_HOST_URL and AUTOPILOT_WEBHOOK_SECRET. Prints no secrets.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional

from ..auth import resolve_servicenow_token
from ..http import create_async_client
from ..settings import load_servicenow_settings

QUEUE = "Autopilot Service Desk"
DOMAIN = "Caldova74201480.OnMicrosoft.com"
GROUPS = {
    QUEUE: "Second-line queue worked by the Group Functions Autopilot IT colleague.",
    "Hardware Support": "Warranty claims and hardware repairs.",
    "Deskside Support": "Deskside device swaps and data transfer.",
    "Security Operations": "Suspected compromise, phishing and malware.",
    "Privileged Access Management": "Privileged account lifecycle and resets.",
    "Network Operations": "Network, VPN and connectivity incidents.",
    "Application Support (Treasury)": "TreasuryWorks and treasury applications.",
    "End User Computing": "Standard build, software packaging and device policy.",
    "CAB Approval": "Change Advisory Board approvers for production changes.",
    "Change Management": "Raises and implements changes.",
    "Database": "Database administration.",
}
# user_name, first, last, title, department, extra fields
PEOPLE = [
    ("kian.lambert", "Kian", "Lambert", "Senior Director, Field Sales", "Commercial Sales", {}),
    ("aisha.west", "Aisha", "West", "Sales Manager", "Commercial Sales", {"locked_out": "true", "failed_attempts": "6"}),
    ("colin.ballinger", "Colin", "Ballinger", "Sourcing and Procurement Manager", "Manufacturing & Supply", {}),
    ("karin.blair", "Karin", "Blair", "Manager, Distribution & Cold Chain Logistics", "Manufacturing & Supply", {}),
    ("daisy.phillips", "Daisy", "Phillips", "Customer Service Lead", "Customer Service", {}),
    ("elvia.atkins", "Elvia", "Atkins", "VP, IT & Digital", "IT & Digital", {}),
    ("kadji.bell", "Kadji", "Bell", "Security Operations Manager", "Security & Compliance", {}),
    ("kenvin.sturis", "Kenvin", "Sturis", "Manager, Data Governance & Analytics", "IT & Digital", {}),
    ("david.so", "David", "So", "Former Change Analyst", "IT & Digital", {"active": "false"}),
]
EMAILS = {"kian.lambert": "KianL", "aisha.west": "AishaW", "colin.ballinger": "ColinB", "karin.blair": "KarinB",
          "daisy.phillips": "DaisyP", "elvia.atkins": "ElviaA", "kadji.bell": "KadjiB", "kenvin.sturis": "KenvinS",
          "david.so": "DavidS"}
OWNERS = {"CAB Approval": "kadji.bell", "Change Management": "elvia.atkins", "Database": "kenvin.sturis",
          "Security Operations": "kadji.bell", QUEUE: "elvia.atkins"}
MEMBERS = {"CAB Approval": ["kadji.bell", "kenvin.sturis", "david.so"],
           "Change Management": ["kenvin.sturis", "karin.blair"],
           "Database": ["kenvin.sturis", "aisha.west"]}
# The declarative agent can sign in as these people (OAuth); the roles cover every MCP tool's REST calls but none
# of the privileged roles the IT desk refuses to reset or the access review scopes.
DEMO_GROUP = "Autopilot Demo Users"
DEMO_ROLES = ("itil", "approver_user", "knowledge", "catalog_admin", "asset", "snc_platform_rest_api_access")
DORMANT = {"aisha.west": "2025-11-03 09:12:00"}
DEVICES = [
    {"owner": "kian.lambert", "serial": "7GHX2Z3", "tag": "P1000742", "name": "LT-KIANL-7440", "warranty": "2026-06-30",
     "purchased": "2023-06-12", "ram": "16384", "cpu": "Intel Core i7-1365U"},
    {"owner": "aisha.west", "serial": "4KQM8R1", "tag": "P1000981", "name": "LT-AISHAW-7440", "warranty": "2027-11-30",
     "purchased": "2024-11-18", "ram": "16384", "cpu": "Intel Core i7-1365U"},
]
BATTERY_REPORT = """BATTERY REPORT
COMPUTER NAME LT-KIANL-7440
SYSTEM PRODUCT NAME Latitude 7440
BIOS 1.18.0
OS BUILD 26100.2314
SERIAL NUMBER 7GHX2Z3
REPORT TIME 2026-09-25 08:41:12

Installed batteries
NAME DELL 9JRV002
MANUFACTURER SMP
CHEMISTRY LiP
DESIGN CAPACITY 57,000 mWh
FULL CHARGE CAPACITY 26,904 mWh
CYCLE COUNT 912

Recent usage
2026-09-24 14:02:11 Active Battery 38 % 21,662 mWh
2026-09-24 14:23:40 Suspended Battery 4 % 1,076 mWh (critical shutdown)
2026-09-24 15:10:02 Active AC 12 %
"""
BUSINESS_RULE = r"""(function executeRule(current, previous) {
    var url = gs.getProperty('x_autopilot.webhook_url', '');
    var secret = gs.getProperty('x_autopilot.webhook_secret', '');
    if (!url || !secret) return;
    var caller = current.caller_id.getRefRecord();
    var payload = {
        event_id: current.getUniqueValue() + ':' + current.getValue('sys_mod_count'),
        table: 'incident', sys_id: current.getUniqueValue(), number: current.getValue('number'),
        operation: current.getValue('sys_mod_count') == '0' ? 'insert' : 'update',
        short_description: current.getValue('short_description') || '',
        updated_by: current.getValue('sys_updated_by') || '',
        caller: caller.isValidRecord() ? {name: caller.getValue('name') || '', email: caller.getValue('email') || '',
            sys_id: caller.getUniqueValue(), user_name: caller.getValue('user_name') || ''} : {}
    };
    var journal = new GlideRecord('sys_journal_field');
    journal.addQuery('element_id', current.getUniqueValue());
    journal.addQuery('element', 'comments');
    journal.orderByDesc('sys_created_on');
    journal.setLimit(1);
    journal.query();
    if (journal.next()) {
        var said = new GlideDateTime(journal.getValue('sys_created_on')).getNumericValue();
        var changed = new GlideDateTime(current.getValue('sys_updated_on')).getNumericValue();
        if (Math.abs(changed - said) < 5000) {
            payload.comment = {by: journal.getValue('sys_created_by') || '', text: (journal.getValue('value') || '').substring(0, 4000)};
        }
    }
    // ASCII-only JSON so the signed bytes and the sent bytes cannot differ by encoding.
    var body = JSON.stringify(payload).replace(/[\u007f-\uffff]/g, function (c) {
        return '\\u' + ('0000' + c.charCodeAt(0).toString(16)).slice(-4);
    });
    var stamp = '' + Math.floor(new GlideDateTime().getNumericValue() / 1000);
    var mac = new GlideCertificateEncryption().generateMac(GlideStringUtil.base64Encode(secret), 'HmacSHA256', stamp + '.' + body);
    var raw = GlideStringUtil.base64DecodeAsBytes(mac);
    var hex = '';
    for (var i = 0; i < raw.length; i++) {
        var b = raw[i] & 0xff;
        hex += (b < 16 ? '0' : '') + b.toString(16);
    }
    var request = new sn_ws.RESTMessageV2();
    request.setEndpoint(url);
    request.setHttpMethod('post');
    request.setHttpTimeout(15000);
    request.setRequestHeader('Content-Type', 'application/json');
    request.setRequestHeader('X-Autopilot-Timestamp', stamp);
    request.setRequestHeader('X-Autopilot-Signature', 'v1=' + hex);
    request.setRequestBody(body);
    var response = request.execute();
    if (response.getStatusCode() >= 300) {
        gs.warn('Autopilot case desk webhook returned ' + response.getStatusCode() + ' for ' + current.getValue('number'));
    }
})(current, previous);"""


class Now:
    def __init__(self) -> None:
        self.base = load_servicenow_settings().instance_url.rstrip("/")
        self.token = ""

    async def _headers(self, content: str = "application/json") -> Dict[str, str]:
        self.token = self.token or await resolve_servicenow_token(None)
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json", "Content-Type": content}

    async def find(self, table: str, query: str, fields: str = "sys_id") -> Optional[Dict[str, Any]]:
        rows = await self.rows(table, query, fields, 1)
        return rows[0] if rows else None

    async def rows(self, table: str, query: str, fields: str = "sys_id", limit: int = 50) -> List[Dict[str, Any]]:
        async with create_async_client(timeout=45.0) as client:
            response = await client.get(f"{self.base}/api/now/table/{table}", headers=await self._headers(), params={
                "sysparm_query": query, "sysparm_limit": limit, "sysparm_fields": fields})
            response.raise_for_status()
            return response.json().get("result", [])

    async def write(self, method: str, table: str, body: Dict[str, Any], sys_id: str = "",
                    params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        path = f"{self.base}/api/now/table/{table}" + (f"/{sys_id}" if sys_id else "")
        async with create_async_client(timeout=45.0) as client:
            response = await client.request(method, path, headers=await self._headers(), json=body, params=params or {})
            if response.status_code >= 400:
                raise RuntimeError(f"{method} {table} failed: HTTP {response.status_code} {response.text[:300]}")
            return response.json().get("result", {})

    async def ensure(self, table: str, query: str, body: Dict[str, Any], *, update: bool = True) -> tuple[str, str]:
        row = await self.find(table, query)
        if row is None:
            return (await self.write("POST", table, body))["sys_id"], "created"
        if update:
            await self.write("PATCH", table, body, row["sys_id"])
            return row["sys_id"], "updated"
        return row["sys_id"], "exists"

    async def attach(self, table: str, sys_id: str, name: str, content: str) -> str:
        async with create_async_client(timeout=45.0) as client:
            response = await client.post(f"{self.base}/api/now/attachment/file", headers=await self._headers("text/plain"),
                                         params={"table_name": table, "table_sys_id": sys_id, "file_name": name},
                                         content=content.encode("utf-8"))
            response.raise_for_status()
            return response.json()["result"]["sys_id"]


def _report(step: str, **values: Any) -> None:
    print(json.dumps({"step": step, **values}), flush=True)


async def setup(now: Now) -> None:
    users: Dict[str, str] = {}
    for user_name, first, last, title, department, extra in PEOPLE:
        body = {"user_name": user_name, "first_name": first, "last_name": last, "title": title,
                "email": f"{EMAILS[user_name]}@{DOMAIN}", "active": "true", **extra}
        users[user_name], state = await now.ensure("sys_user", f"user_name={user_name}", body)
        _report("user", user_name=user_name, state=state)
    for user_name, when in DORMANT.items():
        await now.write("PATCH", "sys_user", {"last_login_time": when}, users[user_name])
    groups: Dict[str, str] = {}
    for name, description in GROUPS.items():
        body: Dict[str, Any] = {"name": name, "description": description, "active": "true"}
        if name in OWNERS:
            body["manager"] = users[OWNERS[name]]
        groups[name], state = await now.ensure("sys_user_group", f"name={name}", body)
        _report("group", name=name, state=state)
    for group, members in MEMBERS.items():
        for user_name in members:
            _sys_id, state = await now.ensure("sys_user_grmember", f"group={groups[group]}^user={users[user_name]}",
                                              {"group": groups[group], "user": users[user_name]}, update=False)
            _report("membership", group=group, user_name=user_name, state=state)
    await demo_users(now, users)
    await devices(now, users)
    category = await now.find("sc_category", "title=Hardware")
    catalog = await now.find("sc_catalog", "title=Service Catalog")
    item = {"name": "Loaner Laptop (up to 10 working days)", "active": "true",
            "short_description": "A standard loaner laptop while yours is repaired or replaced (up to 10 working days).",
            "description": "<p>Issued by Deskside Support with your profile synced. Return it when your device is back.</p>"}
    if category:
        item["category"] = category["sys_id"]
    if catalog:
        item["sc_catalogs"] = catalog["sys_id"]
    _sys_id, state = await now.ensure("sc_cat_item", "name=Loaner Laptop (up to 10 working days)", item)
    _report("catalog_item", name=item["name"], state=state)
    host = os.environ["AUTOPILOT_HOST_URL"].rstrip("/")
    secret = os.environ["AUTOPILOT_WEBHOOK_SECRET"]
    if len(secret) < 32:
        raise RuntimeError("The webhook secret is too short.")
    properties = [
        ("x_autopilot.webhook_url", f"{host}/api/events/servicenow", "Group Functions Autopilot case desk webhook URL."),
        ("x_autopilot.webhook_secret", secret, "HMAC-SHA256 key for the case desk webhook (admin only)."),
        ("glide.email.smtp.active", "true", "Send outbound email (password-reset and incident notifications)."),
    ]
    for name, value, description in properties:
        body = {"name": name, "value": value, "type": "boolean" if value == "true" else "string",
                "description": description}
        if name == "x_autopilot.webhook_secret":
            body.update(is_private="true", read_roles="admin", write_roles="admin")
        if name == "glide.email.smtp.active":
            body = {"name": name, "value": value}
        _sys_id, state = await now.ensure("sys_properties", f"name={name}", body)
        _report("property", name=name, state=state)
    rule = {"name": "Autopilot case desk webhook", "collection": "incident", "when": "async", "order": "100",
            "action_insert": "true", "action_update": "true", "active": "true", "advanced": "true",
            "condition": f"current.assignment_group.getDisplayValue() == '{QUEUE}'", "script": BUSINESS_RULE,
            "description": "Signs and posts a doorbell to the Autopilot case desk; the desk re-reads the record."}
    _sys_id, state = await now.ensure("sys_script", "name=Autopilot case desk webhook^collection=incident", rule)
    _report("business_rule", name=rule["name"], state=state)


async def demo_users(now: Now, users: Dict[str, str]) -> None:
    """Every active demo person gets the MCP tool roles through one group, and a known password to sign in with."""
    group, state = await now.ensure("sys_user_group", f"name={DEMO_GROUP}", {
        "name": DEMO_GROUP, "active": "true",
        "description": "Demo people the declarative agent signs in as: the roles every MCP tool's REST calls need."})
    _report("group", name=DEMO_GROUP, state=state)
    for role_name in DEMO_ROLES:
        role = await now.find("sys_user_role", f"name={role_name}")
        if role is None:
            _report("role", name=role_name, state="not in this instance")
            continue
        _sys_id, state = await now.ensure("sys_group_has_role", f"group={group}^role={role['sys_id']}",
                                          {"group": group, "role": role["sys_id"], "inherits": "true"}, update=False)
        _report("role", name=role_name, state=state)
    active = [person[0] for person in PEOPLE if person[5].get("active", "true") == "true"]
    extras = {person[0]: person[5] for person in PEOPLE}
    for user_name in active:
        await now.ensure("sys_user_grmember", f"group={group}^user={users[user_name]}",
                         {"group": group, "user": users[user_name]}, update=False)
    password = os.environ.get("AUTOPILOT_DEMO_USER_PASSWORD", "")
    if password:
        for user_name in active:
            # Display-value input makes ServiceNow hash the password; the demo lock-outs are re-applied after it.
            await now.write("PATCH", "sys_user", {"user_password": password, "password_needs_reset": "false",
                                                  "web_service_access_only": "false", **extras[user_name]},
                            users[user_name], params={"sysparm_input_display_value": "true"})
    _report("sign_in", users=active, password="set" if password else "unchanged (AUTOPILOT_DEMO_USER_PASSWORD unset)")


async def devices(now: Now, users: Dict[str, str]) -> None:
    category = await now.find("cmdb_model_category", "name=Computer")
    company = await now.find("core_company", "nameSTARTSWITHDell")
    model = await now.find("cmdb_hardware_product_model", "nameLIKELatitude 7440")
    if model is None:
        body: Dict[str, Any] = {"name": "Latitude 7440", "display_name": "Dell Latitude 7440"}
        if category:
            body["cmdb_model_category"] = category["sys_id"]
        if company:
            body["manufacturer"] = company["sys_id"]
        model = await now.write("POST", "cmdb_hardware_product_model", body)
    for device in DEVICES:
        asset = await now.find("alm_hardware", f"serial_number={device['serial']}", "sys_id,ci")
        body = {"serial_number": device["serial"], "asset_tag": device["tag"], "model": model["sys_id"],
                "assigned_to": users[device["owner"]], "install_status": "1", "warranty_expiration": device["warranty"],
                "purchase_date": device["purchased"]}
        if category:
            body["model_category"] = category["sys_id"]
        if company:
            body["vendor"] = company["sys_id"]
        asset = await now.write("PATCH" if asset else "POST", "alm_hardware", body, asset["sys_id"] if asset else "")
        full = await now.find("alm_hardware", f"sys_id={asset['sys_id']}", "sys_id,ci")
        ci = (full or {}).get("ci")
        ci_id = ci.get("value") if isinstance(ci, dict) else ci
        details = {"name": device["name"], "serial_number": device["serial"], "os": "Windows 11 Enterprise",
                   "os_version": "24H2", "ram": device["ram"], "cpu_type": device["cpu"], "assigned_to": users[device["owner"]]}
        if ci_id:
            await now.write("PATCH", "cmdb_ci_computer", details, ci_id)
        else:
            created = await now.write("POST", "cmdb_ci_computer", {**details, "model_id": model["sys_id"]})
            await now.write("PATCH", "alm_hardware", {"ci": created["sys_id"]}, asset["sys_id"])
        _report("device", serial=device["serial"], owner=device["owner"], warranty=device["warranty"])


DEMO_INCIDENTS = {
    "battery": ("kian.lambert", "Laptop shuts down on battery after about 20 minutes",
                "Since last week my laptop dies after 20 minutes off the charger, even at 40%. I travel to clients most "
                "days so I need this fixed. I ran the battery report the self-service agent suggested; it's attached.",
                "hardware", "2", BATTERY_REPORT),
    "lockout": ("aisha.west", "Locked out of the TradeSupport Console",
                "I'm locked out of the TradeSupport Console after my password expired over the weekend. The "
                "self-service reset only covers my Windows account. I need it for the month-end trade confirmations "
                "today.", "inquiry", "2", None),
}


def _scenarios(names: List[str]) -> List[str]:
    unknown = sorted(set(names) - set(DEMO_INCIDENTS))
    if unknown:
        raise SystemExit(f"Unknown demo scenario(s): {', '.join(unknown)}; choose from {', '.join(DEMO_INCIDENTS)}.")
    return names or list(DEMO_INCIDENTS)


async def demo(now: Now, names: List[str]) -> None:
    group = await now.find("sys_user_group", f"name={QUEUE}")
    if group is None:
        raise RuntimeError("Run setup first.")
    for name in _scenarios(names):
        user_name, short, description, category, urgency, report = DEMO_INCIDENTS[name]
        user = await now.find("sys_user", f"user_name={user_name}", "sys_id,name")
        existing = await now.find("incident", f"caller_id={user['sys_id']}^short_description={short}^active=true",
                                  "sys_id,number")
        if existing:
            _report("incident", scenario=name, number=existing["number"], state="exists")
            continue
        created = await now.write("POST", "incident", {
            "caller_id": user["sys_id"], "short_description": short, "description": description,
            "category": category, "urgency": urgency, "impact": "3", "contact_type": "self-service",
            "assignment_group": group["sys_id"]})
        if report:
            await now.attach("incident", created["sys_id"], "battery-report.txt", report)
        _report("incident", scenario=name, number=created.get("number"), caller=user_name, state="created")


async def reset(now: Now, names: List[str]) -> None:
    """Close the open demo incidents (as the integration user, so the desk ignores the echo) and their tasks."""
    for name in _scenarios(names):
        user_name, short, *_rest = DEMO_INCIDENTS[name]
        user = await now.find("sys_user", f"user_name={user_name}")
        if user is None:
            continue
        for incident in await now.rows("incident", f"caller_id={user['sys_id']}^short_description={short}^active=true",
                                       "sys_id,number"):
            for task in await now.rows("incident_task", f"incident={incident['sys_id']}^active=true", "sys_id,number"):
                await now.write("PATCH", "incident_task", {"state": "4", "work_notes": "Closed by the demo reset."},
                                task["sys_id"])
            await now.write("PATCH", "incident", {"state": "7", "close_code": "Solution provided",
                                                  "close_notes": "Closed by the demo reset."}, incident["sys_id"])
            _report("incident", scenario=name, number=incident["number"], state="closed")


async def main(mode: str, names: Optional[List[str]] = None) -> None:
    now = Now()
    if mode == "setup":
        await setup(now)
    elif mode == "demo":
        await demo(now, names or [])
    elif mode == "reset":
        await reset(now, names or [])
    else:
        raise SystemExit("usage: python -m mcp_servers.provisioning.servicenow setup|demo|reset [battery|lockout ...]")
    _report("done", mode=mode)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "", sys.argv[2:]))
