"""Persisted Teams conversation references for proactive messaging.

Whenever the bot receives an inbound activity (message, conversationUpdate,
installationUpdate) we capture the activity's ConversationReference so the
agent can later push a message back to that conversation without an inbound
trigger.  The store is keyed by the user's AAD object id and persisted to a
JSON file on the container's writable filesystem.

For ephemeral container restarts this is acceptable; for production, replace
the file backing with an Azure Storage / Cosmos DB store.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("ess.teams_refs")

_DEFAULT_PATH = Path(os.getenv("TEAMS_REFS_PATH", "/tmp/ess-teams-refs.json"))


class ConversationReferenceStore:
    """Tiny thread-safe JSON-backed key/value store of ConversationReference dicts."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _DEFAULT_PATH
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not load conversation refs from %s: %s", self.path, exc)
            self._data = {}

    def _persist(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2, default=str), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not persist conversation refs to %s: %s", self.path, exc)

    def upsert(self, key: str, reference: dict[str, Any], *, extra: dict[str, Any] | None = None) -> None:
        if not key:
            return
        record = {
            "reference": reference,
            "updated_at": time.time(),
        }
        if extra:
            record.update(extra)
        with self._lock:
            self._data[key] = record
            self._persist()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._data.get(key)

    def all(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self._data)


def conversation_reference_from_dict(data: dict[str, Any]) -> Any | None:
    """Best-effort deserialization of a stored ConversationReference dict.

    Returns a botbuilder ConversationReference object (msrest model) or ``None``
    if the SDK is not importable. The msrest ``deserialize`` classmethod accepts
    the same JSON shape produced by ``conversation_reference_to_dict``.
    """
    try:
        from botbuilder.schema import ConversationReference  # type: ignore
    except Exception:  # pragma: no cover - SDK not installed
        return None
    try:
        # msrest models accept a snake_case dict via deserialize via the
        # internal _attribute_map; constructing directly with **data is the
        # simplest path because all fields are optional kwargs.
        return ConversationReference(**{k: v for k, v in data.items() if v is not None})
    except Exception:
        try:
            return ConversationReference().deserialize(data)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("Could not rehydrate ConversationReference: %s", exc)
            return None


def conversation_reference_to_dict(ref: Any) -> dict[str, Any]:
    """Best-effort serialisation of a ConversationReference object/dict."""
    if isinstance(ref, dict):
        return ref
    out: dict[str, Any] = {}
    for attr in (
        "activity_id",
        "user",
        "bot",
        "conversation",
        "channel_id",
        "service_url",
        "locale",
        "agent",
    ):
        val = getattr(ref, attr, None)
        if val is None:
            continue
        if hasattr(val, "__dict__") or hasattr(val, "_asdict"):
            try:
                out[attr] = {
                    k: v
                    for k, v in vars(val).items()
                    if not k.startswith("_") and not callable(v)
                }
                continue
            except Exception:
                pass
        out[attr] = val
    return out
