"""Shared HTTPX client factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict

import httpx


DEFAULT_HEADERS: Dict[str, str] = {
    "User-Agent": "mcp-servers/0.1.0",
}


@asynccontextmanager
async def create_async_client(timeout: float = 30.0) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=timeout, headers=DEFAULT_HEADERS) as client:
        yield client
