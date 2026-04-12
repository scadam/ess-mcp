"""Bearer token extraction from MCP request context."""
from __future__ import annotations
from typing import Optional
from fastmcp import Context
from ..logging import get_logger

LOGGER = get_logger(__name__)


class TokenValidationError(Exception):
    """Raised when no valid bearer token is found."""


def get_bearer_token(ctx: Optional[Context]) -> str:
    """Extract the OAuth 2.0 Bearer token from the Authorization request header.

    The token is NOT validated here - it will be validated by the SaaS API.
    Tool listing is anonymous; tool execution requires this token.

    Raises:
        TokenValidationError: When no valid Bearer token is present.
    """
    if ctx is None:
        raise TokenValidationError("HTTP context not available; provide Authorization header")
    try:
        request = ctx.request_context.request  # type: ignore[union-attr]
    except (ValueError, AttributeError) as exc:
        raise TokenValidationError("Authorization header unavailable for this request") from exc

    auth_header = request.headers.get("authorization") if request else None
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise TokenValidationError("Authorization: Bearer <token> header is required")

    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        raise TokenValidationError("Authorization: Bearer <token> header is required")

    LOGGER.debug("bearer_token_extracted")
    return token
