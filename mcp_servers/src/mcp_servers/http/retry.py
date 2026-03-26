"""Retry policy helpers."""

from __future__ import annotations

from tenacity import RetryCallState, retry_if_exception_type


def log_retry_attempt(retry_state: RetryCallState) -> None:
    attempt_number = retry_state.attempt_number
    exception = retry_state.outcome.exception() if retry_state.outcome else None
    print(f"Retry attempt {attempt_number} after exception: {exception}")


retry_on_network_error = retry_if_exception_type((TimeoutError, ConnectionError))
