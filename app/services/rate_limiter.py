import threading
import time

from fastapi import HTTPException, Request


class RateLimiter:
    """Simple in-memory per-client sliding-window rate limiter.

    Tracks request timestamps per client key (IP address) and enforces both a
    short-term burst limit (per minute) and a longer daily cap. Intended to
    protect endpoints that call a paid LLM API from being hammered. This is
    process-local state, which is sufficient for a single-VM deployment; it
    resets on process restart and does not coordinate across multiple workers.
    """

    def __init__(self, per_minute: int, per_day: int):
        self._per_minute = per_minute
        self._per_day = per_day
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    @staticmethod
    def _client_key(request: Request) -> str:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    def check(self, request: Request) -> None:
        if self._per_minute <= 0 and self._per_day <= 0:
            return

        key = self._client_key(request)
        now = time.time()

        with self._lock:
            timestamps = self._hits.setdefault(key, [])
            timestamps[:] = [ts for ts in timestamps if now - ts < 86400]

            if self._per_day > 0 and len(timestamps) >= self._per_day:
                retry_after = int(86400 - (now - timestamps[0])) + 1
                raise HTTPException(
                    status_code=429,
                    detail="Daily request limit reached for this client. Please try again later.",
                    headers={"Retry-After": str(max(retry_after, 1))},
                )

            recent = [ts for ts in timestamps if now - ts < 60]
            if self._per_minute > 0 and len(recent) >= self._per_minute:
                retry_after = int(60 - (now - recent[0])) + 1
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Please slow down and try again shortly.",
                    headers={"Retry-After": str(max(retry_after, 1))},
                )

            timestamps.append(now)
