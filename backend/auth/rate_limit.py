"""In-process fixed-window rate limiter for the authentication endpoints.

SCOPE / DEPLOYMENT MODEL
------------------------
This limiter is process-local (in-memory). It is correct for the current
single-instance deployment. A horizontally scaled deployment MUST replace
it with a shared store (e.g. Redis) so limits are consistent across
instances - this module does NOT pretend to be distributed-safe. No
request identity, email, IP or token value is ever written to logs.

KEYS
----
Callers pass one or more keys per request so the same budget shop can be
shared or separated as needed:

* login     -> per client IP  AND  per normalized email (unknown accounts
               included, so hammered non-existent emails are throttled the
               same way as real ones - no account-enumeration signal).
* register  -> per client IP.
* refresh   -> per client IP  AND  per SHA-256 hash of the refresh token
               (the raw token is never retained).

CLEANUP
-------
Expired windows are pruned opportunistically (at most once per window) and
can be pruned explicitly via  prune()  so memory cannot grow forever.
"""

import threading
import time

from fastapi import HTTPException, Request, status

from config import AUTH_MAX_REQUESTS_PER_WINDOW, AUTH_RATE_LIMIT_WINDOW_SECONDS

GENERIC_LIMIT_MESSAGE = "Too many requests. Please try again later."


class InMemoryRateLimiter:
    """Fixed-window limiter keyed by caller-supplied strings.

    Thread-safe: counters live behind a lock so concurrent requests can
    never both pass the same budget seat.
    """

    def __init__(
        self,
        max_requests: int = AUTH_MAX_REQUESTS_PER_WINDOW,
        window_seconds: int = AUTH_RATE_LIMIT_WINDOW_SECONDS,
        clock: callable = None,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        if max_requests <= 0 or window_seconds <= 0:
            raise ValueError("max_requests and window_seconds must be positive")
        self._clock = clock if clock is not None else time.time
        # key -> (window_start, count_in_window)
        self._buckets: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()
        self._last_prune = 0.0

    def hit(self, key: str, now: float = None) -> tuple[bool, int]:
        """Register one request for `key`.

        Returns (allowed, retry_after_seconds). When not allowed, the caller
        should respond 429 with Retry-After = retry_after_seconds.
        """
        now = self._clock() if now is None else now
        window_index = int(now // self.window_seconds)
        with self._lock:
            self._maybe_prune(now)
            window_start, count = self._buckets.get(key, (window_index, 0))
            if window_start != window_index:
                window_start = window_index
                count = 0
            count += 1
            self._buckets[key] = (window_start, count)
            if count > self.max_requests:
                retry_after = int((window_start + 1) * self.window_seconds - now) + 1
                return False, max(retry_after, 1)
            return True, 0

    def _maybe_prune(self, now: float) -> None:
        """Bound cleanup frequency so a burst of distinct keys stays cheap."""
        interval = min(float(self.window_seconds), 60.0)
        if now - self._last_prune < interval:
            return
        self._last_prune = now
        self.prune(now)

    def prune(self, now: float = None) -> None:
        """Drop keys whose last activity is at least one window old."""
        now = self._clock() if now is None else now
        window_index = int(now // self.window_seconds)
        stale = [
            key
            for key, (window_start, _count) in self._buckets.items()
            if window_index - window_start >= 1
        ]
        for key in stale:
            del self._buckets[key]

    def bucket_count(self) -> int:
        """Number of distinct keys currently tracked (for tests/metrics)."""
        with self._lock:
            return len(self._buckets)

    def reset(self) -> None:
        """Clear all tracked state (never used outside tests)."""
        with self._lock:
            self._buckets.clear()
            self._last_prune = 0.0


def client_ip(request: Request) -> str:
    """Best-available source identity for a request.

    Uses the direct peer address. A reverse proxy should enable uvicorn's
    forwarded-allow-ips only when it fully controls that header; trusting an
    unverified X-Forwarded-For would let attackers rotate the key at will.
    """
    return request.client.host if request.client else "unknown"


def hash_key(value: str) -> str:
    """Deterministic 64-hex key for a secret-bearing value (token/email)."""
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def enforce(request: Request, *keys: str) -> None:
    """Hit the shared limiter for each key; raise 429 when a key is over budget.

    The message is intentionally generic (identical to the account-lockout
    429) so clients cannot distinguish `request throttled` from `account
    locked`, which would otherwise be an account-enumeration signal.
    """
    for key in keys:
        allowed, retry_after = limiter.hit(key)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=GENERIC_LIMIT_MESSAGE,
                headers={"Retry-After": str(retry_after)},
            )


# Singleton used by the auth router. Tests replace it with a fresh instance
# (via `rate_limit.limiter = InMemoryRateLimiter(...)`) to isolate budgets.
limiter = InMemoryRateLimiter()