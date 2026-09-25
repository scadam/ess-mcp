"""Exercise the MCP tools behind each Employee Self Service prompt and skill (read-only; forms only prefill).

Writes a compact report to %TEMP%/ap-da-prompt-tests.txt and full JSON results to %TEMP%/da-tests/.
"""

import asyncio
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from fastmcp import Client

BASE = "https://essmcp-caldova-{0}.livelysky-91807d17.eastus2.azurecontainerapps.io/{1}/mcp"
URLS = {name: BASE.format(name, name) for name in ("workday", "servicenow", "coupa", "salesforce")}
OUT = Path(os.environ["TEMP"]) / "da-tests"
OUT.mkdir(exist_ok=True)
report = open(Path(os.environ["TEMP"]) / "ap-da-prompt-tests.txt", "w", encoding="utf-8")


def log(text: str) -> None:
    report.write(text + "\n")
    report.flush()


def shape(value, depth: int = 0) -> str:
    if isinstance(value, dict):
        parts = []
        for key, item in list(value.items())[:14]:
            if key.startswith("_"):
                continue
            if isinstance(item, list):
                parts.append(f"{key}[{len(item)}]")
            elif isinstance(item, dict) and depth < 1:
                parts.append(f"{key}{{{shape(item, depth + 1)}}}")
            else:
                parts.append(key)
        return ", ".join(parts)
    if isinstance(value, list):
        return f"list[{len(value)}]"
    return type(value).__name__


def payload(result) -> object:
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict) and structured:
        return structured.get("result", structured) if set(structured) == {"result"} else structured
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except ValueError:
                return {"text": text[:400]}
    return {}


async def call(clients: dict, server: str, tool: str, args: dict | None = None, label: str = "") -> object:
    args = args or {}
    try:
        result = await clients[server].call_tool(tool, args, raise_on_error=False)
        data = payload(result)
        (OUT / f"{server}.{tool}{('.' + label) if label else ''}.json").write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
        error = getattr(result, "is_error", False) or (isinstance(data, dict) and (data.get("error") or data.get("success") is False))
        log(f"   {'FAIL' if error else 'ok  '} {server}.{tool} {json.dumps(args)[:120]} -> {shape(data)[:300]}"
            + (f" | error: {str(data.get('error') if isinstance(data, dict) else '')[:200]}" if error else ""))
        return data
    except Exception as exc:  # noqa: BLE001 - report every failure and keep going
        log(f"   FAIL {server}.{tool} {json.dumps(args)[:120]} -> {type(exc).__name__}: {str(exc)[:240]}")
        try:
            await clients[server].__aexit__(None, None, None)
        except Exception:  # noqa: BLE001 - the broken session may already be gone
            pass
        clients[server] = Client(URLS[server], timeout=90)
        await clients[server].__aenter__()
        return None


def first(data, *keys):
    for key in keys:
        if isinstance(data, dict) and isinstance(data.get(key), list) and data[key]:
            return data[key]
    return []


async def main() -> None:
    clients = {name: Client(url, timeout=90) for name, url in URLS.items()}
    for client in clients.values():
        await client.__aenter__()
    try:
        friday = date.today() + timedelta(days=(4 - date.today().weekday()) % 7 or 7)
        log("# Show My Org Chart")
        await call(clients, "workday", "get_org_chart")
        await call(clients, "workday", "get_worker")
        log("# Team health check (skill) / Open Team Dashboard / Review Team Goals")
        await call(clients, "workday", "get_direct_reports")
        await call(clients, "workday", "get_team_overview")
        await call(clients, "workday", "get_team_goals")
        await call(clients, "workday", "get_team_performance_summary")
        await call(clients, "workday", "get_check_ins")
        await call(clients, "workday", "get_inbox_tasks")
        log(f"# Plan time off (skill) / Book Vacation — next Friday {friday}")
        balances = await call(clients, "workday", "get_leave_balances")
        await call(clients, "workday", "get_team_calendar")
        await call(clients, "workday", "get_time_off_entries")
        types = first(balances, "eligibleAbsenceTypes", "eligible_absence_types")
        type_id = (types[0].get("id") if types and isinstance(types[0], dict) else None)
        log(f"   eligible absence types: {len(types)}; first: {(types[0].get('descriptor') or types[0].get('name')) if types else None}")
        await call(clients, "workday", "prepare_request_leave", {"startDate": friday.isoformat(), "endDate": friday.isoformat(),
                                                                "quantity": "8", "unit": "Hours", "timeOffTypeId": type_id,
                                                                "reason": "Vacation"})
        log("# IT issue (skill) / Get IT Help")
        for term in ("laptop", "wifi", "VPN", "password"):
            await call(clients, "servicenow", "search_knowledge", {"search_text": term, "limit": 5}, label=term)
        await call(clients, "servicenow", "list_incidents", {"search_text": "laptop", "active": True, "limit": 5})
        await call(clients, "servicenow", "show_create_incident_form", {"short_description": "Laptop keeps losing Wi-Fi",
                                                                        "category": "hardware", "urgency": "3"})
        log("# Order IT equipment (skill) / Order A New Laptop")
        laptops = await call(clients, "servicenow", "list_catalog_items", {"search": "laptop", "limit": 20}, label="laptop")
        items = first(laptops, "items", "results")
        log("   laptops: " + "; ".join(f"{item.get('name')} ({item.get('price')})" for item in items[:10]))
        developer = next((item for item in items if "develop" in str(item.get("name", "")).lower()), items[0] if items else None)
        if developer:
            await call(clients, "servicenow", "get_catalog_item", {"sys_id": developer["sys_id"]})
        await call(clients, "servicenow", "list_catalog_categories", {"limit": 30})
        await call(clients, "servicenow", "list_my_requests", {"limit": 10})
        log("# Track Hardware Orders")
        await call(clients, "coupa", "list_it_hardware_orders", {"limit": 50})
        log("# Procurement Manager View")
        await call(clients, "coupa", "get_category_manager_dashboard")
        log("# Supplier scorecard (skill) / Supplier Performance")
        await call(clients, "coupa", "get_supplier_performance")
        await call(clients, "coupa", "list_suppliers")
        log("# Demand And Stock")
        await call(clients, "coupa", "get_item_demand")
        log("# Trace hardware request (skill) / Trace Request Flow")
        flows = await call(clients, "coupa", "get_servicenow_coupa_flow")
        chains = first(flows, "flows")
        log(f"   chains: {len(chains)}; requests: {[chain.get('service-now-request') for chain in chains][:10]}")
        if chains:
            await call(clients, "coupa", "get_servicenow_coupa_flow", {"request_number": chains[0].get("service-now-request")}, label="one")
        log("# Invoice three-way match (skill) / Resolve Invoice Mismatch")
        for chain in chains:
            for invoice in chain.get("invoices") or []:
                number = invoice.get("invoice-number")
                po = (chain.get("purchase_order") or {}).get("po-number")
                log(f"   chain {chain.get('service-now-request')}: invoice {number} status={invoice.get('status')} total={invoice.get('total')} po={po}"
                    f" received={(chain.get('purchase_order') or {}).get('received-value')}")
        target = next((invoice for chain in chains for invoice in chain.get("invoices") or []
                       if str(invoice.get("invoice-number")) == "INV-2026-0412"), None)
        if target:
            await call(clients, "coupa", "get_invoice_status", {"invoice_number": "INV-2026-0412"})
        po_number = next(((chain.get("purchase_order") or {}).get("po-number") for chain in chains
                          for invoice in chain.get("invoices") or [] if str(invoice.get("invoice-number")) == "INV-2026-0412"), None)
        if po_number:
            await call(clients, "coupa", "get_po_status", {"po_number": po_number})
            await call(clients, "coupa", "list_receipts", {"po_number": po_number})
        log("# Salesforce (live discovery) smoke")
        tools = await clients["salesforce"].list_tools()
        log(f"   salesforce tools: {len(tools)}")
        await call(clients, "salesforce", "list_cases", {"limit": 3})
    finally:
        for client in clients.values():
            try:
                await client.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001 - closing a failed session
                pass


asyncio.run(main())
report.close()
