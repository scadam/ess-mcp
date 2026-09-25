"""Run records: what a colleague created in a run is filed, as that colleague, in the tenant's records library.

Every workspace file plus a manifest (who asked, which skill and version, what was done, SHA-256 of each file) goes
to a folder in a SharePoint document library, uploaded with the colleague's own agentic identity so Purview's audit
log, retention and eDiscovery cover it like any employee's work. The run's answer then links to the files.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any

from .agent_comms import AgentComms, Colleague, CommsError

_logger = logging.getLogger("group-functions-autopilot.run-records")

MAX_FILES = 64
_UNSAFE = re.compile(r'[\x00-\x1f"*:<>?/\\|#%()\[\]{}~&]+')
_TYPES = {".md": "text/markdown", ".json": "application/json", ".csv": "text/csv", ".txt": "text/plain",
          ".html": "text/html", ".xml": "application/xml", ".py": "text/x-python"}
_PATH = re.compile(r"`([A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+){0,4})`")


def safe_name(value: str, limit: int = 80) -> str:
    """A folder name SharePoint accepts: no reserved characters, no trailing dots or spaces."""
    text = " ".join(_UNSAFE.sub(" ", value or "").split())[:limit]
    return text.rstrip(". ") or "Untitled"


def folder_for(colleague: str, title: str, run_id: str, *, case_label: str = "", at: float | None = None) -> str:
    stamp = time.strftime("%Y-%m-%d %H%M", time.gmtime(at or time.time()))
    short = run_id.removeprefix("run-")[:8]
    if case_label:
        return f"{safe_name(colleague, 60)}/Cases/{safe_name(case_label)}/{stamp} {short}"
    return f"{safe_name(colleague, 60)}/Runs/{stamp} {safe_name(title, 60)} {short}"


def _content_type(path: str) -> str:
    suffix = path[path.rfind("."):].lower() if "." in path else ""
    return _TYPES.get(suffix, "application/octet-stream")


class RunRecords:
    def __init__(self, comms: AgentComms, drive_id: str, library_url: str = "") -> None:
        self.comms = comms
        self.drive_id = drive_id
        self.library_url = library_url

    def available(self, colleague: Colleague | None) -> bool:
        return bool(self.drive_id) and self.comms.available(colleague)

    async def file(self, colleague: Colleague, folder: str, files: list[dict[str, Any]], manifest: dict[str, Any],
                   *, share_with: list[str] = ()) -> dict[str, Any]:
        """Upload the files and the manifest; returns the folder link and each file's link and hash."""
        filed: list[dict[str, Any]] = []
        for entry in files[:MAX_FILES]:
            data = entry["data"]
            item = await self.comms.upload(colleague, self.drive_id, f"{folder}/{entry['path']}", data,
                                           _content_type(entry["path"]))
            filed.append({"path": entry["path"], "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                          "writtenBy": entry.get("source", ""), "url": item.get("webUrl", "")})
        record = {**manifest, "files": [{key: value for key, value in item.items() if key != "url"} for item in filed],
                  "omittedFiles": max(0, len(files) - MAX_FILES)}
        body = json.dumps(record, indent=2, default=str).encode("utf-8")
        manifest_item = await self.comms.upload(colleague, self.drive_id, f"{folder}/run-manifest.json", body,
                                                "application/json")
        folder_item = await self.comms.item(colleague, self.drive_id, folder)
        if share_with:
            try:
                await self.comms.share(colleague, self.drive_id, folder_item["id"], list(share_with))
            except CommsError:
                _logger.info("run records: the folder could not be shared with the requester")
        return {"folder": folder, "folderUrl": folder_item.get("webUrl", ""), "manifestUrl": manifest_item.get("webUrl", ""),
                "manifestSha256": hashlib.sha256(body).hexdigest(), "files": filed, "libraryUrl": self.library_url}


def link_files(answer: str, record: dict[str, Any], colleague: str) -> str:
    """Turn each `path` the answer mentions into a link, and add where the run's files are filed."""
    urls = {item["path"]: item["url"] for item in record.get("files", []) if item.get("url")}

    def replace(match: re.Match[str]) -> str:
        url = urls.get(match.group(1))
        return f"[{match.group(1)}]({url})" if url else match.group(0)

    text = _PATH.sub(replace, answer or "").rstrip()
    count = len(record.get("files", []))
    if record.get("folderUrl"):
        text += (f"\n\n**Files:** [{record['folder'].rsplit('/', 1)[-1]}]({record['folderUrl']}) \u00b7 {count} "
                 f"file{'' if count == 1 else 's'} and a run manifest, filed by {colleague} in the Autopilot records "
                 "library.")
    return text
