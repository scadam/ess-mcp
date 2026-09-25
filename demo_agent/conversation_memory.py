"""Bounded, tenant-scoped conversation memory; no agent actions or summarizer.

The Markdown summary lives inside one gzip-compressed JSON document. ``update``
is an optimistic read/modify/write operation: its synchronous transform may run
more than once and MUST NOT perform external side effects. A successful claim
is a durable receipt, not a transaction with a subsequently executed job.

TTL is conversation-wide inactivity expiry, measured from the last mutation.
Expired documents are validated before being reset, and retain their storage
version for the next CAS. Reads neither extend TTL nor physically delete data.

SQLite is for local development on a local filesystem. Azure requires an
existing container, managed identity, and the Storage Blob Data Contributor
role scoped to that container/account. Azure imports and clients are lazy;
there is deliberately no credential-chain or in-memory fallback. Close stores
after their in-flight operations finish (``async with`` or ``await close()``).
"""

from __future__ import annotations

import asyncio
import copy
import gzip
import hashlib
import inspect
import json
import math
import os
import random
import re
import sqlite3
import time
import zlib
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
MAX_ID_CHARS = 512
MAX_CONTENT_CHARS = 8_000
MAX_RECENT_MESSAGES = 16
MAX_SEEN_IDS = 512
MAX_JSON_DEPTH = 32
DEFAULT_TTL_SECONDS = 90 * 24 * 60 * 60
DEFAULT_MAX_COMPRESSED_BYTES = 256 * 1024
DEFAULT_MAX_UNCOMPRESSED_BYTES = 1024 * 1024
DEFAULT_CONTAINER = "autopilot-state"

_STATE_KEYS = frozenset(
    {"schemaVersion", "scope", "summary", "recent", "seen", "tasks",
     "welcomed", "active", "updatedAt"}
)
_MESSAGE_KEYS = frozenset({"role", "content", "senderId", "activityId", "at"})
_ROLES = frozenset({"user", "assistant", "system", "tool"})
_ACCOUNT_URL = re.compile(r"https://[a-z0-9]{3,24}\.blob\.core\.windows\.net")
_CONTAINER_NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])")
_STATE_BLOB = re.compile(r"[0-9a-f]{64}\.json\.gz")
_SQLITE_MAX_VERSION = (1 << 63) - 1


class ConversationStoreError(RuntimeError):
    """Base error. Messages deliberately exclude IDs, content and credentials."""


class StoreConfigurationError(ConversationStoreError):
    """Invalid storage configuration or missing optional Azure dependencies."""


class CorruptStateError(ConversationStoreError):
    """A stored or proposed document is corrupt, mismatched or unsupported."""


class StateTooLargeError(CorruptStateError):
    """A compressed, uncompressed or field-level limit was exceeded."""


class ConcurrentUpdateError(ConversationStoreError):
    """The bounded optimistic-concurrency attempt budget was exhausted."""


class StoreUnavailableError(ConversationStoreError):
    """Storage could not be accessed; no fallback state has been returned."""


class StoreClosedError(ConversationStoreError):
    """An operation was attempted after closing the store."""


def _identifier_is_valid(value: Any) -> bool:
    # Separators (including ../) are legal IDs, never filesystem components.
    return (
        type(value) is str
        and 0 < len(value) <= MAX_ID_CHARS
        and bool(value.strip())
        and value.isprintable()
    )


def _require_identifier(value: Any) -> None:
    if not _identifier_is_valid(value):
        raise ValueError("Identifiers must be nonblank printable strings of at most 512 characters.")


@dataclass(frozen=True)
class ChatScope:
    tenant_id: str
    agent_id: str
    conversation_id: str

    def __post_init__(self) -> None:
        for value in (self.tenant_id, self.agent_id, self.conversation_id):
            _require_identifier(value)

    @property
    def storage_key(self) -> str:
        """SHA-256 of the ordered, compact UTF-8 JSON array (no raw IDs)."""
        canonical = json.dumps(
            [self.tenant_id, self.agent_id, self.conversation_id],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def to_dict(self) -> dict[str, str]:
        return {
            "tenantId": self.tenant_id,
            "agentId": self.agent_id,
            "conversationId": self.conversation_id,
        }


def _fresh_state(scope: ChatScope, now: float) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "scope": scope.to_dict(),
        "summary": "",
        "recent": [],
        "seen": [],
        "tasks": {},
        "welcomed": False,
        "active": False,
        "updatedAt": now,
    }


def _is_epoch(value: Any) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return value >= 0 and math.isfinite(value)
    except OverflowError:
        return False


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CorruptStateError("Duplicate JSON property in conversation memory.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise CorruptStateError("Non-finite JSON number in conversation memory.")


def _same_json(left: Any, right: Any) -> bool:
    # Python's ordinary equality conflates True/1 and False/0. Those are
    # distinct JSON task values, so such a transform must not become a no-op.
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_same_json(value, right[key]) for key, value in left.items())
    if type(left) is list:
        return len(left) == len(right) and all(_same_json(a, b) for a, b in zip(left, right))
    return left == right


@dataclass(frozen=True)
class _Record:
    version: int | str
    payload: bytes


class Store(ABC):
    """Async storage contract shared by both backends.

    Bounds are byte limits for the entire document, in addition to character
    limits for text fields. ``max_attempts`` includes the initial attempt and
    must be 1..5. Transforms must preserve schema/identity and return None.
    Callers authoring task records directly must scrub sensitive text before
    storing it; tasks remain otherwise application-defined JSON objects.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_compressed_bytes: int = DEFAULT_MAX_COMPRESSED_BYTES,
        max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
        max_attempts: int = 5,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not _is_epoch(ttl_seconds) or ttl_seconds == 0:
            raise StoreConfigurationError("TTL must be a positive finite number of seconds.")
        for limit in (max_compressed_bytes, max_uncompressed_bytes):
            if type(limit) is not int or limit <= 0:
                raise StoreConfigurationError("Memory size limits must be positive integers.")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
            raise StoreConfigurationError("CAS must use between one and five attempts.")
        if not callable(clock):
            raise StoreConfigurationError("A callable clock is required.")
        self.ttl_seconds = float(ttl_seconds)
        self.max_compressed_bytes = max_compressed_bytes
        self.max_uncompressed_bytes = max_uncompressed_bytes
        self.max_attempts = max_attempts
        self._clock = clock
        self._closed = False

    def _now(self) -> float:
        now = self._clock()
        if not _is_epoch(now):
            raise StoreConfigurationError("The memory clock must return a finite nonnegative epoch.")
        return float(now)

    def _ensure_open(self) -> None:
        if self._closed:
            raise StoreClosedError("The conversation store is closed.")

    def _validate_text(self, text: Any, limit: int) -> None:
        if type(text) is not str:
            raise CorruptStateError("Conversation memory text must be a string.")
        if len(text) > limit:
            raise StateTooLargeError("Conversation memory text exceeds its limit.")
        try:
            size = len(text.encode("utf-8"))
        except UnicodeError:
            raise CorruptStateError("Invalid Unicode in conversation memory.") from None
        if size > self.max_uncompressed_bytes:
            raise StateTooLargeError("Conversation memory text exceeds the document byte limit.")

    def _validate_json(self, value: Any, depth: int = 0) -> None:
        # Also rejects cycles, subclasses with custom serialization, tuples and
        # non-string keys, so a committed value cannot silently change type.
        if depth > MAX_JSON_DEPTH:
            raise CorruptStateError("Conversation task JSON is too deeply nested or cyclic.")
        kind = type(value)
        if value is None or kind in (bool, int):
            return
        if kind is float:
            if not math.isfinite(value):
                raise CorruptStateError("Conversation task numbers must be finite.")
            return
        if kind is str:
            self._validate_text(value, self.max_uncompressed_bytes)
            return
        if kind is list:
            for item in value:
                self._validate_json(item, depth + 1)
            return
        if kind is dict:
            for key, item in value.items():
                self._validate_text(key, self.max_uncompressed_bytes)
                self._validate_json(item, depth + 1)
            return
        raise CorruptStateError("Conversation tasks must contain only JSON values.")

    def _validate_state(self, scope: ChatScope, state: Any) -> None:
        if type(state) is not dict or state.keys() != _STATE_KEYS:
            raise CorruptStateError("Unsupported conversation memory structure.")
        if type(state["schemaVersion"]) is not int or state["schemaVersion"] != SCHEMA_VERSION:
            raise CorruptStateError("Unsupported conversation memory schema version.")
        if type(state["scope"]) is not dict or state["scope"] != scope.to_dict():
            raise CorruptStateError("Conversation memory identity does not match its scope.")
        self._validate_text(state["summary"], MAX_CONTENT_CHARS)
        if type(state["welcomed"]) is not bool or type(state["active"]) is not bool:
            raise CorruptStateError("Conversation memory flags must be booleans.")
        if not _is_epoch(state["updatedAt"]):
            raise CorruptStateError("Invalid conversation memory timestamp.")

        recent = state["recent"]
        if type(recent) is not list:
            raise CorruptStateError("Conversation recent messages must be a list.")
        if len(recent) > MAX_RECENT_MESSAGES:
            raise StateTooLargeError("Too many recent conversation messages.")
        for message in recent:
            if type(message) is not dict or message.keys() != _MESSAGE_KEYS:
                raise CorruptStateError("Unsupported recent message structure.")
            if type(message["role"]) is not str or message["role"] not in _ROLES:
                raise CorruptStateError("Unsupported recent message role.")
            self._validate_text(message["content"], MAX_CONTENT_CHARS)
            if not all(_identifier_is_valid(message[key]) for key in ("senderId", "activityId")):
                raise CorruptStateError("Invalid recent message identifier.")
            if not _is_epoch(message["at"]):
                raise CorruptStateError("Invalid recent message timestamp.")

        seen = state["seen"]
        if type(seen) is not list or not all(_identifier_is_valid(item) for item in seen):
            raise CorruptStateError("Invalid conversation receipt list.")
        if len(seen) > MAX_SEEN_IDS:
            raise StateTooLargeError("Too many conversation receipts.")
        if len(set(seen)) != len(seen):
            raise CorruptStateError("Duplicate conversation receipts.")
        tasks = state["tasks"]
        if type(tasks) is not dict:
            raise CorruptStateError("Conversation tasks must be an object.")
        for task_id, record in tasks.items():
            if not _identifier_is_valid(task_id) or type(record) is not dict:
                raise CorruptStateError("Invalid conversation task record.")
            self._validate_json(record)

    def _decode(self, scope: ChatScope, payload: bytes) -> dict[str, Any]:
        if type(payload) is not bytes or not payload:
            raise CorruptStateError("Conversation memory is not a gzip document.")
        if len(payload) > self.max_compressed_bytes:
            raise StateTooLargeError("Compressed conversation memory exceeds its byte limit.")
        try:
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            raw = decoder.decompress(payload, self.max_uncompressed_bytes + 1)
            if len(raw) > self.max_uncompressed_bytes or decoder.unconsumed_tail:
                raise StateTooLargeError("Uncompressed conversation memory exceeds its byte limit.")
            # No unbounded flush(), concatenated members, or trailing garbage.
            if not decoder.eof or decoder.unused_data:
                raise CorruptStateError("Incomplete or trailing gzip conversation memory data.")
            state = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
        except (zlib.error, UnicodeError, ValueError, RecursionError):
            raise CorruptStateError("Invalid gzip or JSON conversation memory.") from None
        self._validate_state(scope, state)
        return state

    def _encode(self, scope: ChatScope, state: dict[str, Any]) -> bytes:
        self._validate_state(scope, state)
        raw = bytearray()
        encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        try:
            for chunk in encoder.iterencode(state):
                encoded = chunk.encode("utf-8")
                if len(raw) + len(encoded) > self.max_uncompressed_bytes:
                    raise StateTooLargeError("Uncompressed conversation memory exceeds its byte limit.")
                raw.extend(encoded)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise CorruptStateError("Conversation memory is not valid JSON.") from None
        payload = gzip.compress(bytes(raw), compresslevel=6, mtime=0)
        if len(payload) > self.max_compressed_bytes:
            raise StateTooLargeError("Compressed conversation memory exceeds its byte limit.")
        return payload

    async def _snapshot(self, scope: ChatScope) -> tuple[dict[str, Any], int | str | None]:
        self._ensure_open()
        if not isinstance(scope, ChatScope):
            raise TypeError("scope must be a ChatScope.")
        record = await self._read_record(scope.storage_key)
        if record is None:
            return _fresh_state(scope, self._now()), None
        state = await asyncio.to_thread(self._decode, scope, record.payload)
        now = self._now()
        if now - state["updatedAt"] >= self.ttl_seconds:
            # Do not turn an expired row/blob into a nonexistent CAS target.
            state = _fresh_state(scope, now)
        return state, record.version

    async def read(self, scope: ChatScope) -> dict[str, Any]:
        """Return a detached state; missing/expired state is fresh and inactive."""
        state, _ = await self._snapshot(scope)
        return state

    async def update(
        self, scope: ChatScope, transform: Callable[[dict[str, Any]], None]
    ) -> dict[str, Any]:
        """Commit a pure synchronous transform with at most five CAS attempts.

        A no-op does not write or renew TTL. Only conflicts retry; configuration,
        corruption and service errors propagate. Cancellation/transport failure
        can occur after a durable commit; use receipts for application retries.
        """
        if not callable(transform):
            raise TypeError("transform must be callable.")
        for attempt in range(self.max_attempts):
            original, version = await self._snapshot(scope)
            candidate = copy.deepcopy(original)
            result = transform(candidate)
            if result is not None:
                if inspect.iscoroutine(result):
                    result.close()
                raise TypeError("transform must be synchronous and return None.")
            self._validate_state(scope, candidate)
            if _same_json(candidate, original):
                return original
            candidate["updatedAt"] = self._now()
            # A transform may retain references. Isolate the committed snapshot
            # before yielding to a worker thread or network operation.
            candidate = copy.deepcopy(candidate)
            payload = await asyncio.to_thread(self._encode, scope, candidate)
            self._ensure_open()
            if await self._compare_and_swap(scope.storage_key, version, payload):
                return candidate
            if attempt + 1 < self.max_attempts:
                await asyncio.sleep(random.uniform(0.001, 0.01 * (2 ** attempt)))
        raise ConcurrentUpdateError("Conversation memory changed during all CAS attempts.")

    @abstractmethod
    async def _read_record(self, key: str) -> _Record | None:
        """Return bytes and version from the same storage snapshot."""

    @abstractmethod
    async def _compare_and_swap(self, key: str, version: int | str | None, payload: bytes) -> bool:
        """Return False only for a definite optimistic-concurrency conflict."""

    async def clear_all(self, keep: tuple[ChatScope, ...] = ()) -> int:
        """Operator reset: delete every document except ``keep``; returns how many were deleted."""
        self._ensure_open()
        return await self._delete_all(frozenset(scope.storage_key for scope in keep))

    async def _delete_all(self, keep: frozenset[str]) -> int:
        raise StoreConfigurationError("This store does not support an operator reset.")

    async def close(self) -> None:
        self._closed = True

    async def aclose(self) -> None:
        await self.close()

    async def __aenter__(self) -> Store:
        self._ensure_open()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self.close()


def _absolute_path(value: str | os.PathLike[str]) -> Path:
    try:
        path = Path(value).expanduser()
    except (TypeError, ValueError, RuntimeError):
        raise StoreConfigurationError("Invalid local conversation memory path.") from None
    if not path.is_absolute() or "\x00" in str(path):
        raise StoreConfigurationError("Local conversation memory requires an absolute file path.")
    return path


class SQLiteStore(Store):
    """Local SQLite CAS store; every connection/transaction runs in to_thread.

    No shared connection, process-local lock, or memory cache is needed for
    correctness across store instances. New database files use owner-only POSIX
    permissions; existing files/directories and their permissions are preserved.
    """

    def __init__(self, path: str | os.PathLike[str], **options: Any) -> None:
        super().__init__(**options)
        self.path = _absolute_path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        try:
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS conversation_memory ("
                "storage_key TEXT PRIMARY KEY NOT NULL, "
                "version INTEGER NOT NULL CHECK (typeof(version) = 'integer' AND version > 0), "
                "payload BLOB NOT NULL CHECK (typeof(payload) = 'blob'))"
            )
        except BaseException:
            connection.close()
            raise
        return connection

    def _read_sync(self, key: str) -> _Record | None:
        with closing(self._connect()) as connection:
            # Never materialize an oversized payload in Python. Metadata and
            # body come from the same SELECT, not two racing reads.
            row = connection.execute(
                "SELECT version, typeof(payload), length(payload), "
                "CASE WHEN typeof(payload) = 'blob' AND length(payload) <= ? "
                "THEN payload ELSE NULL END "
                "FROM conversation_memory WHERE storage_key = ?",
                (self.max_compressed_bytes, key),
            ).fetchone()
        if row is None:
            return None
        version, payload_type, size, payload = row
        if type(version) is not int or not 1 <= version <= _SQLITE_MAX_VERSION:
            raise CorruptStateError("Invalid SQLite conversation memory version.")
        if payload_type != "blob" or type(size) is not int:
            raise CorruptStateError("Invalid SQLite conversation memory payload.")
        if size > self.max_compressed_bytes:
            raise StateTooLargeError("Compressed conversation memory exceeds its byte limit.")
        return _Record(version, payload)

    def _cas_sync(self, key: str, version: int | str | None, payload: bytes) -> bool:
        if version is not None and (type(version) is not int or not 1 <= version < _SQLITE_MAX_VERSION):
            raise CorruptStateError("Invalid or exhausted SQLite conversation memory version.")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if version is None:
                cursor = connection.execute(
                    "INSERT INTO conversation_memory (storage_key, version, payload) VALUES (?, 1, ?) "
                    "ON CONFLICT(storage_key) DO NOTHING",
                    (key, payload),
                )
            else:
                cursor = connection.execute(
                    "UPDATE conversation_memory SET version = version + 1, payload = ? "
                    "WHERE storage_key = ? AND version = ?",
                    (payload, key, version),
                )
            return cursor.rowcount == 1

    async def _read_record(self, key: str) -> _Record | None:
        try:
            return await asyncio.to_thread(self._read_sync, key)
        except sqlite3.DatabaseError:
            raise StoreUnavailableError("SQLite conversation memory read failed.") from None
        except OSError:
            raise StoreUnavailableError("Local conversation memory could not be opened.") from None

    async def _compare_and_swap(self, key: str, version: int | str | None, payload: bytes) -> bool:
        try:
            return await asyncio.to_thread(self._cas_sync, key, version, payload)
        except sqlite3.DatabaseError:
            raise StoreUnavailableError("SQLite conversation memory write failed.") from None
        except OSError:
            raise StoreUnavailableError("Local conversation memory could not be written.") from None

    def _delete_all_sync(self, keep: frozenset[str]) -> int:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            keys = [row[0] for row in connection.execute("SELECT storage_key FROM conversation_memory")]
            doomed = [(key,) for key in keys if key not in keep]
            connection.executemany("DELETE FROM conversation_memory WHERE storage_key = ?", doomed)
            return len(doomed)

    async def _delete_all(self, keep: frozenset[str]) -> int:
        try:
            return await asyncio.to_thread(self._delete_all_sync, keep)
        except sqlite3.DatabaseError:
            raise StoreUnavailableError("SQLite conversation memory reset failed.") from None
        except OSError:
            raise StoreUnavailableError("Local conversation memory could not be reset.") from None


def _azure_error_code(error: Any) -> Any:
    code = getattr(error, "error_code", None)
    return getattr(code, "value", code)


class AzureBlobStore(Store):
    """Gzip JSON blobs with conditional writes and explicit managed identity.

    Only canonical public-Azure account URLs are accepted: no trailing slash,
    path, port, userinfo, query/SAS, fragment, emulator or arbitrary HTTP host.
    The container must already exist; a missing container is NOT missing state.
    """

    def __init__(self, account_url: str, container: str = DEFAULT_CONTAINER, **options: Any) -> None:
        super().__init__(**options)
        if type(account_url) is not str or not _ACCOUNT_URL.fullmatch(account_url):
            raise StoreConfigurationError("A canonical HTTPS Azure Blob account URL is required.")
        if type(container) is not str or not _CONTAINER_NAME.fullmatch(container) or "--" in container:
            raise StoreConfigurationError("A valid fixed Azure Blob container name is required.")
        self.account_url = account_url
        self.container = container
        self._client_lock = asyncio.Lock()
        self._credential: Any = None
        self._service: Any = None
        self._container_client: Any = None

    async def _get_container(self) -> Any:
        async with self._client_lock:
            self._ensure_open()
            if self._container_client is not None:
                return self._container_client
            try:
                from azure.identity.aio import ManagedIdentityCredential
                from azure.storage.blob.aio import BlobServiceClient
            except ImportError:
                raise StoreConfigurationError(
                    "Azure conversation memory requires azure-storage-blob and azure-identity."
                ) from None
            credential: Any = None
            service: Any = None
            try:
                # A user-assigned-only host rejects the system-identity request, so pass its client id.
                credential = ManagedIdentityCredential(client_id=os.getenv("AZURE_CLIENT_ID") or None)
                service = BlobServiceClient(
                    account_url=self.account_url,
                    credential=credential,
                    # Do not replay writes with an ambiguous response. The
                    # Store retries only explicit CAS conflicts, not timeouts.
                    retry_total=0,
                    max_single_get_size=self.max_compressed_bytes + 1,
                    max_chunk_get_size=self.max_compressed_bytes + 1,
                    logging_enable=False,
                )
                container = service.get_container_client(self.container)
            except BaseException as error:
                try:
                    try:
                        if service is not None:
                            await service.close()
                    finally:
                        if credential is not None:
                            await credential.close()
                except Exception:
                    # Preserve the initialization failure or cancellation;
                    # neither exception's potentially sensitive text is logged.
                    pass
                if isinstance(error, Exception):
                    raise StoreUnavailableError("Azure conversation memory initialization failed.") from None
                raise
            self._credential = credential
            self._service = service
            self._container_client = container
            return container

    async def _read_record(self, key: str) -> _Record | None:
        container = await self._get_container()
        from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

        try:
            blob = container.get_blob_client(f"{key}.json.gz")
            # Request at most limit+1 bytes, rather than downloading an
            # arbitrarily large object and checking its size afterwards.
            download = await blob.download_blob(
                offset=0, length=self.max_compressed_bytes + 1,
                max_concurrency=1, logging_enable=False,
            )
            payload = await download.readall()
            if len(payload) > self.max_compressed_bytes:
                raise StateTooLargeError("Compressed conversation memory exceeds its byte limit.")
            etag = download.properties.etag
            if type(etag) is not str or not 0 < len(etag) <= 512 or not etag.isprintable():
                raise CorruptStateError("Missing or invalid Azure conversation memory ETag.")
            return _Record(etag, payload)
        except ResourceNotFoundError as error:
            if _azure_error_code(error) == "BlobNotFound":
                return None
            raise StoreUnavailableError("Azure conversation memory container is unavailable.") from None
        except HttpResponseError as error:
            if error.status_code == 416:
                raise CorruptStateError("Empty or invalid Azure conversation memory blob.") from None
            raise StoreUnavailableError("Azure conversation memory read failed.") from None
        except ConversationStoreError:
            raise
        except Exception:
            raise StoreUnavailableError("Azure conversation memory read failed.") from None

    async def _compare_and_swap(self, key: str, version: int | str | None, payload: bytes) -> bool:
        container = await self._get_container()
        from azure.core import MatchConditions
        from azure.core.exceptions import HttpResponseError
        from azure.storage.blob import ContentSettings

        if version is not None and type(version) is not str:
            raise CorruptStateError("Invalid Azure conversation memory ETag.")
        options: dict[str, Any] = {"overwrite": False}
        if version is not None:
            options = {"overwrite": True, "etag": version, "match_condition": MatchConditions.IfNotModified}
        try:
            blob = container.get_blob_client(f"{key}.json.gz")
            await blob.upload_blob(
                payload,
                # Opaque gzip content, not Content-Encoding:gzip, prevents HTTP
                # automatic decompression from defeating the download bound.
                content_settings=ContentSettings(content_type="application/gzip"),
                logging_enable=False,
                **options,
            )
            # overwrite=False is the SDK's atomic create-if-absent block upload.
            return True
        except HttpResponseError as error:
            code = _azure_error_code(error)
            if version is None and error.status_code == 409 and code == "BlobAlreadyExists":
                return False
            if version is not None and (
                (error.status_code == 412 and code == "ConditionNotMet")
                or (error.status_code == 404 and code == "BlobNotFound")
            ):
                return False
            raise StoreUnavailableError("Azure conversation memory write failed.") from None
        except Exception:
            raise StoreUnavailableError("Azure conversation memory write failed.") from None

    async def _delete_all(self, keep: frozenset[str]) -> int:
        container = await self._get_container()
        from azure.core.exceptions import ResourceNotFoundError

        try:
            names = [blob.name async for blob in container.list_blobs(logging_enable=False)]
        except Exception:
            raise StoreUnavailableError("Azure conversation memory could not be listed.") from None
        deleted = 0
        for name in names:
            # Only this store's own state blobs; anything else in the container is left alone.
            if _STATE_BLOB.fullmatch(name) is None or name[:-len(".json.gz")] in keep:
                continue
            try:
                await container.delete_blob(name, logging_enable=False)
            except ResourceNotFoundError:
                continue
            except Exception:
                raise StoreUnavailableError("Azure conversation memory reset failed.") from None
            deleted += 1
        return deleted

    async def close(self) -> None:
        async with self._client_lock:
            self._closed = True
            try:
                try:
                    if self._service is not None:
                        await self._service.close()
                finally:
                    if self._credential is not None:
                        await self._credential.close()
            except Exception:
                raise StoreUnavailableError("Azure conversation memory client cleanup failed.") from None
            finally:
                self._service = self._credential = self._container_client = None


_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----[\s\S]*?"
    r"(?:-----END (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----|\Z)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bBearer\s+[^\s\"'`,;<>]+", re.IGNORECASE)
_JWT = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:eyJ[A-Za-z0-9_-]*|[A-Za-z0-9_-]{16,})"
    r"(?:\.[A-Za-z0-9_-]*){2,4}(?![A-Za-z0-9_.-])"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?P<prefix>(?<![\w.-])[\"']?"
    r"(?:[\w.-]{0,64}(?:password|passwd|pwd|token|secret)[\w.-]{0,64}"
    r"|api[_-]?key|accountkey|private[_-]?key)"
    r"[\"']?\s*[:=]\s*)"
    r"(?P<value>\[REDACTED\]|\"(?:\\[\s\S]|[^\"\\])*(?:\"|\Z)"
    r"|'(?:\\[\s\S]|[^'\\])*(?:'|\Z)"
    r"|`(?:\\[\s\S]|[^`\\])*(?:`|\Z)|[^\s,;`\"'<>}\]]+)",
    re.IGNORECASE,
)


def scrub_memory_text(text: str) -> str:
    """Best-effort secret-pattern redaction, then an 8,000-character cap.

    Redact before truncation so a long credential crossing the boundary is not
    retained as a partial secret. This is not a substitute for data governance
    or a secret classifier; arbitrary unlabelled sensitive prose is not detected.
    """
    if type(text) is not str:
        raise TypeError("Memory text must be a string.")
    text = _PRIVATE_KEY.sub("[REDACTED]", text)
    text = _BEARER.sub("Bearer [REDACTED]", text)
    text = _JWT.sub("[REDACTED]", text)

    def redact_assignment(match: re.Match[str]) -> str:
        value = match.group("value")
        quote = value[0] if value[0] in "\"'`" else ""
        return f"{match.group('prefix')}{quote}[REDACTED]{quote}"

    return _SECRET_ASSIGNMENT.sub(redact_assignment, text)[:MAX_CONTENT_CHARS]


def _remember_activity(state: dict[str, Any], activity_id: str) -> None:
    if activity_id not in state["seen"]:
        state["seen"].append(activity_id)
        state["seen"] = state["seen"][-MAX_SEEN_IDS:]


async def claim_activity(store: Store, scope: ChatScope, activity_id: str) -> bool:
    """Atomically claim an ID until TTL expiry or eviction from 512 receipts.

    Call before processing an activity. A crash after claiming does not release
    the claim; application job recovery/side effects are intentionally separate.
    """
    _require_identifier(activity_id)
    claimed = False

    def transform(state: dict[str, Any]) -> None:
        nonlocal claimed
        # Reset on EVERY invocation: a failed CAS may be followed by a no-op.
        claimed = activity_id not in state["seen"]
        if claimed:
            _remember_activity(state, activity_id)

    await store.update(scope, transform)
    return claimed


async def mark_welcomed(store: Store, scope: ChatScope) -> bool:
    """Return True only for the successful transition to welcomed (per TTL)."""
    changed = False

    def transform(state: dict[str, Any]) -> None:
        nonlocal changed
        changed = not state["welcomed"]
        if changed:
            state["welcomed"] = True

    await store.update(scope, transform)
    return changed


async def append_exchange(
    store: Store,
    scope: ChatScope,
    activity_id: str,
    user_id: str,
    user_text: str,
    assistant_text: str,
    summary: str | None = None,
) -> dict[str, Any]:
    """Store redacted messages and optionally replace the Markdown summary.

    Retains 16 messages (not 16 pairs), plus 512 receipt IDs. A preceding claim
    does not suppress this append. Completed exchanges still in ``recent`` are
    idempotent; use ``claim_activity`` for durable dedup beyond that short window.
    No model is called and no tasks, draft records, or active flag are changed.
    """
    _require_identifier(activity_id)
    _require_identifier(user_id)
    user_content = scrub_memory_text(user_text)
    assistant_content = scrub_memory_text(assistant_text)
    summary_content = None if summary is None else scrub_memory_text(summary)

    def transform(state: dict[str, Any]) -> None:
        if any(message["activityId"] == activity_id for message in state["recent"]):
            return
        now = store._now()
        state["recent"].extend(
            [
                {"role": "user", "content": user_content, "senderId": user_id,
                 "activityId": activity_id, "at": now},
                {"role": "assistant", "content": assistant_content, "senderId": scope.agent_id,
                 "activityId": activity_id, "at": now},
            ]
        )
        state["recent"] = state["recent"][-MAX_RECENT_MESSAGES:]
        _remember_activity(state, activity_id)
        if summary_content is not None:
            state["summary"] = summary_content

    return await store.update(scope, transform)


def _default_local_path() -> Path:
    cache_env = "LOCALAPPDATA" if os.name == "nt" else "XDG_CACHE_HOME"
    configured = os.environ.get(cache_env)
    if configured:
        base = _absolute_path(configured)
    else:
        home = _absolute_path(Path.home())
        base = home / "AppData" / "Local" if os.name == "nt" else home / ".cache"
    return base / "ess-mcp" / "autopilot" / "conversation-memory.sqlite3"


def create_conversation_store() -> Store:
    """Create (without I/O) the environment-selected store.

    AUTOPILOT_STORAGE_ACCOUNT_URL selects managed-identity Azure Blob storage.
    AUTOPILOT_STORAGE_CONTAINER defaults to autopilot-state.
    AUTOPILOT_STATE_PATH selects an absolute local SQLite file, otherwise use
    the per-user cache, never cwd or an implicit runtime temporary directory.
    AUTOPILOT_STATE_TTL_SECONDS optionally overrides the 90-day inactivity TTL.
    AUTOPILOT_ENVIRONMENT=production forbids the local backend even if a local
    path is explicitly supplied. An invalid Azure configuration never falls back.
    """
    account_url = os.environ.get("AUTOPILOT_STORAGE_ACCOUNT_URL")
    production = os.environ.get("AUTOPILOT_ENVIRONMENT", "").strip().casefold() == "production"
    if production and not account_url:
        raise StoreConfigurationError("Production conversation memory requires Azure Blob storage.")
    try:
        ttl = float(os.environ.get("AUTOPILOT_STATE_TTL_SECONDS", str(DEFAULT_TTL_SECONDS)))
    except ValueError:
        raise StoreConfigurationError("Invalid conversation memory TTL configuration.") from None
    if account_url:
        return AzureBlobStore(
            account_url,
            os.environ.get("AUTOPILOT_STORAGE_CONTAINER", DEFAULT_CONTAINER),
            ttl_seconds=ttl,
        )
    path = os.environ.get("AUTOPILOT_STATE_PATH")
    return SQLiteStore(path if path is not None else _default_local_path(), ttl_seconds=ttl)