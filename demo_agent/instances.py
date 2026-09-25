"""Discover and resolve per-user agentic AI Teammate instances.

Each Teams user that has been provisioned an AI Teammate from our blueprint
gets their own service principal in Entra (e.g. "ESS AI Teammate for Siva").
The control plane uses this module to enumerate those instances, resolve the
human user they belong to, and look up that user's manager so a completed run
can be reported back to the manager via Teams.

Discovery strategy (kept deliberately simple for the demo):
1. List ServicePrincipals whose displayName starts with the configured prefix
   (default: "Compliance Partner").
2. The text after the prefix is the user's displayName; look the user up in
   Microsoft Graph by displayName (best-effort).
3. Resolve `/users/{id}/manager` for the manager.

Results are cached in-process for AGENTIC_INSTANCE_CACHE_TTL seconds (default
300).  This is read-only Graph traffic; no writes are performed here.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import urllib.parse
from dataclasses import dataclass, field, asdict
from typing import Any, Callable

import httpx

logger = logging.getLogger("ess.instances")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
# Per-instance `agentIdentity` SPs carry `agentIdentityBlueprintId` pointing at
# the blueprint app they were spawned from. That's the authoritative link --
# name-prefix matching is a legacy fallback for tenants that don't expose the
# field yet.
DEFAULT_INSTANCE_PREFIXES = "Compliance Partner"


@dataclass
class AgenticInstance:
    """A per-user AI Teammate instance discovered from Microsoft Graph."""

    instance_id: str          # ServicePrincipal objectId (the agentic_app_id seen on inbound activities)
    instance_app_id: str      # ServicePrincipal appId
    display_name: str         # SP displayName, e.g. "ESS AI Teammate for Siva"
    user_id: str = ""         # owning user objectId (best-effort)
    user_display_name: str = ""
    user_upn: str = ""
    user_aad_object_id: str = ""
    manager_id: str = ""
    manager_display_name: str = ""
    manager_upn: str = ""
    manager_email: str = ""
    discovered_at: float = field(default_factory=time.time)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InstanceDirectory:
    """Thin Graph wrapper that lists and resolves AI Teammate instances."""

    def __init__(
        self,
        graph_token_provider: Callable[[], str] | None,
        *,
        prefix: str | None = None,
        blueprint_app_id: str | None = None,
        cache_ttl: float | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._token_provider = graph_token_provider
        # Primary discovery key: blueprint app id (from env or explicit arg).
        # Per-instance `agentIdentity` SPs expose `agentIdentityBlueprintId` that
        # equals this value -- much more reliable than name-prefix matching.
        self.blueprint_app_id = (
            blueprint_app_id
            or os.getenv("AGENTIC_BLUEPRINT_APP_ID")
            or os.getenv("AGENT_ID")
            or os.getenv("CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID")
            or ""
        ).strip()
        # The primary blueprint agent identity (the "operator" SP backing the
        # control plane itself) lives in the same blueprint group as per-user
        # teammates, but it isn't a per-user instance and shouldn't be listed
        # in the AI Teammate Instances panel. Exclude its appId / objectId.
        self.primary_agent_app_id = (
            os.getenv("ENTRA_AGENT_IDENTITY_CLIENT_ID") or ""
        ).strip().lower()
        self.primary_agent_object_id = (
            os.getenv("ENTRA_AGENT_IDENTITY_OBJECT_ID") or ""
        ).strip().lower()
        # Legacy name-prefix fallback (used if blueprint filter returns 0 or the
        # tenant's Graph endpoint doesn't yet expose agentIdentityBlueprintId).
        raw_prefixes = prefix or os.getenv("AGENTIC_INSTANCE_NAME_PREFIX", DEFAULT_INSTANCE_PREFIXES)
        self.prefixes = [p.strip() for p in raw_prefixes.split(",") if p.strip()] or ["Compliance Partner"]
        self.prefix = self.prefixes[0]
        self.cache_ttl = float(cache_ttl if cache_ttl is not None else os.getenv("AGENTIC_INSTANCE_CACHE_TTL", "300"))
        self.timeout = timeout
        self._cache: list[AgenticInstance] = []
        self._cache_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self._token_provider is not None

    # ---- Public API -----------------------------------------------------

    async def list_instances(self, *, force_refresh: bool = False) -> list[AgenticInstance]:
        if not self.enabled:
            return []
        now = time.time()
        if not force_refresh and self._cache and (now - self._cache_at) < self.cache_ttl:
            return list(self._cache)
        async with self._lock:
            if not force_refresh and self._cache and (time.time() - self._cache_at) < self.cache_ttl:
                return list(self._cache)
            try:
                instances = await self._discover()
            except Exception as exc:
                logger.warning("Instance discovery failed: %s", exc)
                if self._cache:
                    return list(self._cache)
                return []
            self._cache = instances
            self._cache_at = time.time()
            return list(instances)

    async def get_instance(self, instance_id: str) -> AgenticInstance | None:
        for inst in await self.list_instances():
            if inst.instance_id == instance_id or inst.instance_app_id == instance_id:
                return inst
        return None

    async def invalidate(self) -> None:
        self._cache = []
        self._cache_at = 0.0

    # ---- Internals ------------------------------------------------------

    def _token(self) -> str:
        if not self._token_provider:
            raise RuntimeError("Graph token provider is not configured")
        return self._token_provider()

    async def _graph_get(self, client: httpx.AsyncClient, url: str) -> dict[str, Any]:
        token = self._token()
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()

    async def _discover(self) -> list[AgenticInstance]:
        instances: list[AgenticInstance] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Strategy 1: filter by agentIdentityBlueprintId (authoritative link).
            if self.blueprint_app_id:
                instances = await self._discover_by_blueprint(client, self.blueprint_app_id)
            # Strategy 2: legacy name-prefix filter (used when blueprint id not set
            # or the tenant's Graph endpoint hasn't surfaced agentIdentityBlueprintId).
            if not instances:
                instances = await self._discover_by_prefixes(client, self.prefixes)
            # The blueprint's own principal is never a per-user instance.
            instances = [i for i in instances if (i.instance_app_id or "").lower() != self.blueprint_app_id.lower()]

            # Drop the primary blueprint agent identity itself -- it's the
            # operator/service principal, not a per-user teammate instance.
            if self.primary_agent_app_id or self.primary_agent_object_id:
                before = len(instances)
                instances = [
                    i for i in instances
                    if (i.instance_app_id or "").lower() != self.primary_agent_app_id
                    and (i.instance_id or "").lower() != self.primary_agent_object_id
                ]
                if before != len(instances):
                    logger.info(
                        "Excluded primary agent identity from instance list (appId=%s objectId=%s)",
                        self.primary_agent_app_id or "<unset>",
                        self.primary_agent_object_id or "<unset>",
                    )

            # Resolve owning users + managers in parallel (bounded).
            sem = asyncio.Semaphore(8)

            async def _resolve(inst: AgenticInstance) -> None:
                async with sem:
                    await self._resolve_user_and_manager(client, inst)

            await asyncio.gather(*(_resolve(i) for i in instances), return_exceptions=True)

        instances.sort(key=lambda i: i.display_name.lower())
        logger.info(
            "Discovered %d AI Teammate instance(s) (blueprint=%s, prefixes=%r)",
            len(instances), self.blueprint_app_id or "<unset>", self.prefixes,
        )
        return instances

    async def _discover_by_blueprint(
        self, client: httpx.AsyncClient, blueprint_app_id: str
    ) -> list[AgenticInstance]:
        """List agentIdentity SPs whose agentIdentityBlueprintId == our blueprint.

        agentIdentityBlueprintId is a property of `microsoft.graph.agentIdentity`
        SPs only, so we cast the collection and filter on it directly.
        """
        token = self._token()
        # Cast to agentIdentity to expose agentIdentityBlueprintId in $filter/$select.
        # agentIdentityBlueprintId is Edm.String -> GUID literal must be quoted.
        url = (
            f"{GRAPH_BASE}/servicePrincipals/microsoft.graph.agentIdentity"
            f"?$filter=agentIdentityBlueprintId eq '{blueprint_app_id}'"
            f"&$select=id,appId,displayName,agentIdentityBlueprintId,servicePrincipalType,notes"
            f"&$top=200"
        )
        out: list[AgenticInstance] = []
        pages = 0
        while url and pages < 25:
            pages += 1
            resp = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "ConsistencyLevel": "eventual",
                },
            )
            if resp.status_code >= 400:
                logger.warning(
                    "agentIdentity filter query failed (HTTP %s): %s | url=%s",
                    resp.status_code,
                    (resp.text or "")[:400],
                    url,
                )
                # On 400/404 the cast endpoint may not be available in this tenant
                # -- caller will fall back to the prefix scan.
                return []
            data = resp.json()
            for sp in data.get("value", []):
                out.append(
                    AgenticInstance(
                        instance_id=sp.get("id", ""),
                        instance_app_id=sp.get("appId", ""),
                        display_name=sp.get("displayName", ""),
                        notes=sp.get("notes", "") or "",
                    )
                )
            url = data.get("@odata.nextLink")
        return out

    async def _discover_by_prefixes(
        self, client: httpx.AsyncClient, prefixes: list[str]
    ) -> list[AgenticInstance]:
        """Legacy displayName startswith() query, OR-joined across prefixes."""
        filter_clauses = [
            f"startswith(displayName,'{urllib.parse.quote(p.replace(chr(39), chr(39)*2))}')"
            for p in prefixes
        ]
        joined = " or ".join(filter_clauses)
        url = (
            f"{GRAPH_BASE}/servicePrincipals?$count=true"
            f"&$filter=({joined})"
            f"&$select=id,appId,displayName,servicePrincipalType,tags,notes"
            f"&$top=200"
        )
        token = self._token()
        resp = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "ConsistencyLevel": "eventual",
            },
        )
        if resp.status_code >= 400:
            body_preview = (resp.text or "")[:600]
            logger.warning(
                "Graph servicePrincipals query failed (HTTP %s): %s | url=%s",
                resp.status_code, body_preview, url,
            )
            if resp.status_code in (400, 403):
                fallback = await self._discover_fallback(client, prefixes)
                if fallback is not None:
                    return fallback
        resp.raise_for_status()
        data = resp.json()
        out: list[AgenticInstance] = []
        for sp in data.get("value", []):
            out.append(
                AgenticInstance(
                    instance_id=sp.get("id", ""),
                    instance_app_id=sp.get("appId", ""),
                    display_name=sp.get("displayName", ""),
                    notes=sp.get("notes", "") or "",
                )
            )
        return out

    async def _discover_fallback(self, client: httpx.AsyncClient, prefixes: list[str]) -> list[AgenticInstance] | None:
        """Last-resort discovery: page through servicePrincipals without advanced query
        and filter client-side. Used when the $count+$filter+startswith path returns 4xx
        (typically because the IMDS-issued MI token has not picked up Application.Read.All
        yet, or a Conditional Access policy blocks advanced queries).
        """
        prefixes_lc = [p.lower() for p in prefixes]
        token = self._token()
        url: str | None = (
            f"{GRAPH_BASE}/servicePrincipals?$select=id,appId,displayName,notes&$top=200"
        )
        out: list[AgenticInstance] = []
        pages = 0
        while url and pages < 25:
            pages += 1
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code >= 400:
                logger.warning(
                    "Fallback servicePrincipals enumeration failed (HTTP %s): %s",
                    resp.status_code,
                    (resp.text or "")[:400],
                )
                return None
            data = resp.json()
            for sp in data.get("value", []):
                name = (sp.get("displayName") or "")
                name_lc = name.lower()
                if any(name_lc.startswith(p) for p in prefixes_lc):
                    out.append(
                        AgenticInstance(
                            instance_id=sp.get("id", ""),
                            instance_app_id=sp.get("appId", ""),
                            display_name=name,
                            notes=sp.get("notes", "") or "",
                        )
                    )
            url = data.get("@odata.nextLink")

        sem = asyncio.Semaphore(8)

        async def _resolve(inst: AgenticInstance) -> None:
            async with sem:
                await self._resolve_user_and_manager(client, inst)

        await asyncio.gather(*(_resolve(i) for i in out), return_exceptions=True)
        out.sort(key=lambda i: i.display_name.lower())
        logger.info(
            "Fallback discovery found %d AI Teammate instance(s) (scanned %d page(s))",
            len(out),
            pages,
        )
        return out

    async def _resolve_user_and_manager(self, client: httpx.AsyncClient, inst: AgenticInstance) -> None:
        # Each AI Teammate instance has its OWN Entra User object whose displayName
        # exactly matches the ServicePrincipal (e.g. "ESS AI Teammate for Siva").
        # That user's `manager` relationship points to the human owner (e.g. Siva
        # Vasireddy), which is exactly who we want to deliver run results to.
        if not inst.display_name:
            return
        user = await self._lookup_user(client, inst.display_name)
        if not user:
            # Fallback: try the suffix as a displayName (covers cases where the
            # instance is just named after a person without its own user account).
            suffix = inst.display_name[len(self.prefix):].strip() if inst.display_name.startswith(self.prefix) else ""
            if suffix:
                user = await self._lookup_user(client, suffix)
        if not user:
            return
        inst.user_id = user.get("id", "")
        inst.user_display_name = user.get("displayName", "")
        inst.user_upn = user.get("userPrincipalName", "") or ""
        inst.user_aad_object_id = inst.user_id
        manager = await self._lookup_manager(client, inst.user_id)
        if manager:
            inst.manager_id = manager.get("id", "")
            inst.manager_display_name = manager.get("displayName", "")
            inst.manager_upn = manager.get("userPrincipalName", "") or ""
            inst.manager_email = manager.get("mail", "") or inst.manager_upn

    async def _lookup_user(self, client: httpx.AsyncClient, name_or_upn: str) -> dict[str, Any] | None:
        # Try UPN/email first if it looks like one.
        if "@" in name_or_upn:
            data = await self._graph_get(
                client, f"{GRAPH_BASE}/users/{urllib.parse.quote(name_or_upn)}?$select=id,displayName,userPrincipalName,mail"
            )
            if data.get("id"):
                return data
        # Fall back to displayName search.
        encoded = urllib.parse.quote(name_or_upn.replace("'", "''"))
        token = self._token()
        url = (
            f"{GRAPH_BASE}/users?$filter=displayName eq '{encoded}'"
            f"&$select=id,displayName,userPrincipalName,mail&$top=2"
        )
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {token}", "ConsistencyLevel": "eventual"},
        )
        if resp.status_code != 200:
            return None
        values = resp.json().get("value", [])
        if not values:
            # Try startswith as a last resort.
            url = (
                f"{GRAPH_BASE}/users?$filter=startswith(displayName,'{encoded}')"
                f"&$select=id,displayName,userPrincipalName,mail&$top=2&$count=true"
            )
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}", "ConsistencyLevel": "eventual"},
            )
            if resp.status_code != 200:
                return None
            values = resp.json().get("value", [])
        return values[0] if values else None

    async def _lookup_manager(self, client: httpx.AsyncClient, user_id: str) -> dict[str, Any] | None:
        try:
            data = await self._graph_get(
                client,
                f"{GRAPH_BASE}/users/{user_id}/manager?$select=id,displayName,userPrincipalName,mail",
            )
            return data if data.get("id") else None
        except httpx.HTTPStatusError:
            return None


def build_default_directory() -> InstanceDirectory:
    """Build an InstanceDirectory using the container managed identity for Graph."""
    provider: Callable[[], str] | None = None
    try:
        from azure.identity import ManagedIdentityCredential  # type: ignore

        cred = ManagedIdentityCredential(client_id=os.getenv("AZURE_CLIENT_ID") or None)

        def _get() -> str:
            return cred.get_token("https://graph.microsoft.com/.default").token

        provider = _get
    except Exception as exc:  # pragma: no cover - local dev path
        logger.info("Managed identity Graph token unavailable: %s", exc)
    return InstanceDirectory(provider)
