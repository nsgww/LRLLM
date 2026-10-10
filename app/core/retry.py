"""Shared retry helper for outbound provider HTTP calls.

Transient failures (connection errors, timeouts, 429, 5xx) are retried with
linear backoff; deterministic 4xx responses are surfaced immediately so we do
not burn attempts on a request that cannot succeed.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError,
                        httpx.RemoteProtocolError, httpx.WriteError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return False


async def with_retry(
    call: Callable[[], Awaitable[httpx.Response]],
    *,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    description: str = "provider request",
) -> httpx.Response:
    """Invoke ``call`` with bounded retries; returns the final response.

    Raises the last exception when every attempt fails.
    """
    attempts = max(1, max_attempts)
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = await call()
            response.raise_for_status()
            return response
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts or not _is_retryable(exc):
                raise
            delay = backoff_seconds * attempt
            logger.warning(
                "%s failed (attempt %s/%s), retrying in %.1fs: %s",
                description,
                attempt,
                attempts,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None  # unreachable: loop either returns or raises
    raise last_exc
