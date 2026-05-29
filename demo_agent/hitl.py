"""Human-in-the-loop coordinator for proactive Teams approvals.

When an agent invokes the synthetic ``human__ask_manager`` tool, a
``HumanRequest`` is registered here keyed by the manager's AAD object id.
The tool call awaits ``request.future``; the bot's ``on_message`` handler
resolves that future when the manager replies in Teams.

This is intentionally tiny: in-memory only, FIFO per manager. For multi-pod
deployments swap the dict for Redis or Cosmos.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("ess.hitl")


@dataclass
class HumanRequest:
    request_id: str
    run_id: str
    manager_aad_id: str
    manager_name: str
    question: str
    asked_at: float
    future: asyncio.Future
    asker_name: str = ""
    asker_aad_id: str = ""

    def to_summary(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "runId": self.run_id,
            "managerAadId": self.manager_aad_id,
            "managerName": self.manager_name,
            "askerName": self.asker_name,
            "question": self.question,
            "askedAt": int(self.asked_at * 1000),
        }


class HitlCoordinator:
    """FIFO per-manager pending request queue."""

    def __init__(self) -> None:
        self._pending: dict[str, deque[HumanRequest]] = {}
        self._by_id: dict[str, HumanRequest] = {}
        self._lock = asyncio.Lock()

    async def request(
        self,
        *,
        run_id: str,
        manager_aad_id: str,
        manager_name: str,
        question: str,
        asker_name: str = "",
        asker_aad_id: str = "",
        timeout: float = 600.0,
    ) -> tuple[HumanRequest, asyncio.Future]:
        loop = asyncio.get_running_loop()
        req = HumanRequest(
            request_id=uuid.uuid4().hex,
            run_id=run_id,
            manager_aad_id=manager_aad_id,
            manager_name=manager_name,
            question=question,
            asked_at=time.time(),
            future=loop.create_future(),
            asker_name=asker_name,
            asker_aad_id=asker_aad_id,
        )
        async with self._lock:
            self._pending.setdefault(manager_aad_id, deque()).append(req)
            self._by_id[req.request_id] = req
        # Schedule a timeout cancellation; on timeout the awaiter sees TimeoutError.
        loop.call_later(timeout, self._timeout, req.request_id)
        return req, req.future

    def _timeout(self, request_id: str) -> None:
        req = self._by_id.get(request_id)
        if req is None or req.future.done():
            return
        req.future.set_exception(asyncio.TimeoutError())
        self._discard(req)

    async def resolve(self, manager_aad_id: str, reply_text: str) -> HumanRequest | None:
        """Resolve the oldest pending request for this manager. Returns the request or None."""
        async with self._lock:
            queue = self._pending.get(manager_aad_id)
            if not queue:
                return None
            req = queue.popleft()
            if not queue:
                self._pending.pop(manager_aad_id, None)
        if not req.future.done():
            req.future.set_result(reply_text)
        self._by_id.pop(req.request_id, None)
        return req

    async def resolve_by_request_id(self, request_id: str, reply_text: str) -> HumanRequest | None:
        """Resolve a specific pending request (used by the headless web-form path)."""
        async with self._lock:
            req = self._by_id.get(request_id)
            if req is None:
                return None
            self._by_id.pop(request_id, None)
            queue = self._pending.get(req.manager_aad_id)
            if queue:
                try:
                    queue.remove(req)
                except ValueError:
                    pass
                if not queue:
                    self._pending.pop(req.manager_aad_id, None)
        if not req.future.done():
            req.future.set_result(reply_text)
        return req

    def get(self, request_id: str) -> HumanRequest | None:
        return self._by_id.get(request_id)

    def _discard(self, req: HumanRequest) -> None:
        queue = self._pending.get(req.manager_aad_id)
        if queue:
            try:
                queue.remove(req)
            except ValueError:
                pass
            if not queue:
                self._pending.pop(req.manager_aad_id, None)
        self._by_id.pop(req.request_id, None)

    def has_pending(self, manager_aad_id: str) -> bool:
        queue = self._pending.get(manager_aad_id)
        return bool(queue)

    def snapshot(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for queue in self._pending.values():
            for req in queue:
                out.append(req.to_summary())
        out.sort(key=lambda r: r["askedAt"])
        return out
