"""Refresh only MCP endpoint strings in existing Cowork/agent package outputs.

Canonical URLs come from the seven declarative-agent source plugins. By default,
auth blocks, IDs, versions and skill contents remain unchanged. --sync-auth also
aligns only Workday/Salesforce/ServiceNow auth fields with their source manifests.
Source manifests are never written. This is not a full Toolkit rebuild or publication.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OLD_DOMAIN = "wittysand-460bf1d9.eastus.azurecontainerapps.io"
NEW_DOMAIN = "livelysky-91807d17.eastus2.azurecontainerapps.io"
SERVERS = ("workday", "servicenow", "salesforce", "jira", "sap-sf", "ariba", "coupa")
TEXT_EXTENSIONS = {".json", ".md", ".txt", ".yaml", ".yml"}
FALLBACK_PLUGINS = {"workday-mcp-plugin", "salesforce-mcp-plugin", "servicenow-mcp-plugin"}
FALLBACK_COWORK = {"workday-people-leader", "salesforce-sales-intelligence", "servicenow-it-operations"}


def endpoint_map(root: Path = ROOT) -> dict[bytes, bytes]:
    replacements = {}
    for server in SERVERS:
        source = root / "declarative_agent" / "appPackage" / f"{server}-mcp-plugin.json"
        plugin = json.loads(source.read_text(encoding="utf-8-sig"))
        runtimes = [runtime for runtime in plugin["runtimes"] if runtime["type"] == "RemoteMCPServer"]
        if len(runtimes) != 1:
            raise ValueError(f"Expected one MCP runtime in {source.name}")
        route = "sap_sf" if server == "sap-sf" else server
        expected = f"https://essmcp-caldova-{server}.{NEW_DOMAIN}/{route}/mcp"
        if runtimes[0]["spec"]["url"] != expected:
            raise ValueError(f"Unexpected canonical endpoint in {source.name}")
        old = f"https://essmcp-{server}.{OLD_DOMAIN}/{route}/mcp"
        replacements[old.encode()] = expected.encode()
    return replacements


def replace_endpoints(data: bytes, replacements: dict[bytes, bytes]) -> bytes:
    for old, new in replacements.items():
        data = data.replace(old, new)
    return data


def synchronize_auth(data: bytes, source: dict | None) -> bytes:
    if source is None:
        return data
    document = json.loads(data.decode("utf-8-sig"))
    original = json.dumps(document)
    if "agentConnectors" in source:
        connectors = {connector["id"]: connector for connector in source["agentConnectors"]}
        for connector in document.get("agentConnectors", []):
            if connector["id"] in connectors:
                target = connector.get("toolSource", {}).get("remoteMcpServer")
                canonical = connectors[connector["id"]].get("toolSource", {}).get("remoteMcpServer")
                if target is not None and canonical is not None:
                    target["authorization"] = canonical["authorization"]
    else:
        canonical = [runtime for runtime in source.get("runtimes", []) if runtime.get("type") == "RemoteMCPServer"]
        targets = [runtime for runtime in document.get("runtimes", []) if runtime.get("type") == "RemoteMCPServer"]
        if len(canonical) != 1 or len(targets) != 1:
            raise ValueError("Expected one source and packaged MCP runtime")
        targets[0]["auth"] = canonical[0]["auth"]
    if json.dumps(document) == original:
        return data
    indent = 4 if b'\n    "' in data else 2
    text = json.dumps(document, indent=indent, ensure_ascii=False) + "\n"
    if b"\r\n" in data:
        text = text.replace("\n", "\r\n")
    return text.encode("utf-8")


def rebuild_generated_copy(path: Path, replacements: dict[bytes, bytes], *, write: bool, auth_source: dict | None = None) -> dict:
    if path.is_symlink():
        raise ValueError("Refusing to replace a symlinked generated file")
    original = path.read_bytes()
    updated = replace_endpoints(original, replacements)
    updated = synchronize_auth(updated, auth_source)
    json.loads(updated.decode("utf-8-sig"))
    changed = updated != original
    if write and changed:
        descriptor, temp_name = tempfile.mkstemp(prefix=".endpoint-generated-", suffix=".json", dir=path.parent)
        temporary = Path(temp_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(updated)
            if temporary.read_bytes() != updated:
                raise ValueError("Generated output verification failed")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return {"generatedCopy": str(path), "endpointChanged": changed, "written": bool(write and changed)}


def rebuild_archive(path: Path, replacements: dict[bytes, bytes], *, write: bool, auth_sources: dict | None = None) -> dict:
    if path.is_symlink():
        raise ValueError("Refusing to replace a symlinked package")
    with zipfile.ZipFile(path) as source:
        entries = source.infolist()
        if len({entry.filename for entry in entries}) != len(entries):
            raise ValueError(f"Duplicate entries in {path.name}")
        original = [(entry, source.read(entry)) for entry in entries]
        comment = source.comment
    changed = []
    updated = []
    for entry, data in original:
        replacement = data
        if Path(entry.filename).suffix.lower() in TEXT_EXTENSIONS:
            replacement = replace_endpoints(data, replacements)
        if auth_sources and entry.filename in auth_sources:
            replacement = synchronize_auth(replacement, auth_sources[entry.filename])
        if replacement != data:
            if entry.filename.lower().endswith(".json"):
                json.loads(replacement.decode("utf-8-sig"))
            changed.append(entry.filename)
        updated.append((entry, replacement))
    if write and changed:
        descriptor, temp_name = tempfile.mkstemp(prefix=".endpoint-package-", suffix=".zip", dir=path.parent)
        os.close(descriptor)
        temporary = Path(temp_name)
        try:
            with zipfile.ZipFile(temporary, "w") as output:
                output.comment = comment
                for entry, data in updated:
                    output.writestr(entry, data)
            with zipfile.ZipFile(temporary) as check:
                if check.testzip() is not None or check.namelist() != [entry.filename for entry, _ in updated]:
                    raise ValueError("Package integrity verification failed")
                for entry, data in updated:
                    if check.read(entry.filename) != data:
                        raise ValueError("Unexpected package content change")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return {"archive": str(path), "changedEntries": changed, "written": bool(write and changed)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Write verified endpoint-only ZIP replacements; otherwise check only")
    parser.add_argument("--sync-auth", action="store_true", help="Also synchronize only Workday/Salesforce/ServiceNow packaged auth fields")
    args = parser.parse_args()
    replacements = endpoint_map()
    generated = sorted((ROOT / "declarative_agent" / "appPackage" / "build").glob("*-mcp-plugin.*.json"))
    generated_count = 0
    for path in generated:
        stem = path.name.split(".")[0]
        auth_source = None
        if args.sync_auth and stem in FALLBACK_PLUGINS:
            auth_source = json.loads((ROOT / "declarative_agent" / "appPackage" / f"{stem}.json").read_text(encoding="utf-8-sig"))
        report = rebuild_generated_copy(path, replacements, write=args.write, auth_source=auth_source)
        report["generatedCopy"] = path.relative_to(ROOT).as_posix()
        generated_count += int(report["endpointChanged"])
        print(json.dumps(report))
    archives = sorted((ROOT / "cowork" / "plugins").rglob("*.zip"))
    archives += sorted((ROOT / "declarative_agent" / "appPackage" / "build").glob("*.zip"))
    count = 0
    for path in archives:
        auth_sources = {}
        if args.sync_auth and path.parent.name in FALLBACK_COWORK:
            auth_sources["manifest.json"] = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8-sig"))
        elif args.sync_auth and path.parent == ROOT / "declarative_agent" / "appPackage" / "build":
            auth_sources = {f"{stem}.json": json.loads((path.parent.parent / f"{stem}.json").read_text(encoding="utf-8-sig")) for stem in FALLBACK_PLUGINS}
        report = rebuild_archive(path, replacements, write=args.write, auth_sources=auth_sources)
        report["archive"] = path.relative_to(ROOT).as_posix()
        if report["changedEntries"]:
            count += 1
        print(json.dumps(report))
    print(json.dumps({"packagesExamined": len(archives), "packagesWithEndpointChanges": count,
                      "generatedCopiesExamined": len(generated), "generatedCopiesWithEndpointChanges": generated_count,
                      "mode": "write" if args.write else "check"}))


if __name__ == "__main__":
    main()