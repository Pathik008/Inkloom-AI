"""Production-grade rate limiting module for Inkloom AI.

Architecture & Security:
1. Trustworthy Client IP Extraction:
   - Evaluates peer address (request.client.host).
   - Only trusts X-Forwarded-For if the immediate peer is in settings.TRUSTED_PROXIES.
   - Parses X-Forwarded-For right-to-left to prevent client header spoofing.
   - Untrusted peer IPs ignore X-Forwarded-For entirely.
2. Shared Redis & Local In-Memory Backends:
   - RedisRateLimiter: Shared sliding-window rate limiter via Redis sorted sets for multi-worker deployments.
   - InMemoryRateLimiter: Thread-safe process-local limiter for single-worker/local development fallback.
   - Fail-Safe Protocol: When Redis is configured but fails, logs high-priority security warnings
     and defaults to local limiting (or fails closed if RATE_LIMIT_FAIL_CLOSED=True). Protection is never silently disabled.
3. Standardised 429 Envelope:
   - Returns HTTP 429 with Retry-After header and standard {"detail": ...} error envelope.
4. Privacy & Token Safety:
   - Rate limit keys are derived from endpoint action + client IP.
   - Raw invitation tokens and token hashes are never used in rate limiter keys or error details.
"""
from __future__ import annotations

import ipaddress
import logging
import secrets
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from typing import Any

from fastapi import HTTPException, Request, status

from app.core.config import settings

logger = logging.getLogger(__name__)


def is_ip_in_trusted(ip_str: str, trusted_list: list[str]) -> bool:
    """Check whether an IP string is present in or covered by trusted proxies/CIDRs."""
    try:
        ip = ipaddress.ip_address(ip_str.strip())
    except ValueError:
        return False

    for trusted in trusted_list:
        trusted_clean = trusted.strip()
        if not trusted_clean:
            continue
        try:
            if "/" in trusted_clean:
                if ip in ipaddress.ip_network(trusted_clean, strict=False):
                    return True
            else:
                if ip == ipaddress.ip_address(trusted_clean):
                    return True
        except ValueError:
            continue
    return False


def get_client_ip(request: Request, trusted_proxies: list[str] | None = None) -> str:
    """Extract trustworthy client IP.

    If peer (request.client.host) is in trusted_proxies, inspects X-Forwarded-For
    from right to left and returns the first untrusted IP.
    If peer is NOT in trusted_proxies, ignores X-Forwarded-For entirely to prevent
    header spoofing.
    """
    if trusted_proxies is None:
        trusted_proxies = settings.trusted_proxies_list

    peer_ip = request.client.host if request.client else "127.0.0.1"

    # If peer is untrusted, treat peer_ip as the client IP (ignore client-supplied headers)
    if not is_ip_in_trusted(peer_ip, trusted_proxies):
        return peer_ip

    # Peer is a trusted reverse proxy: inspect X-Forwarded-For
    forwarded_for = request.headers.get("X-Forwarded-For")
    if not forwarded_for:
        return peer_ip

    raw_hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
    if not raw_hops:
        return peer_ip

    # Walk from right to left (most recent proxy to original client)
    for hop in reversed(raw_hops):
        if not is_ip_in_trusted(hop, trusted_proxies):
            return hop

    # If all hops were trusted proxies, return the leftmost hop
    return raw_hops[0]


class BaseRateLimiter(ABC):
    """Abstract base rate limiter."""

    @abstractmethod
    def check(self, key: str, max_attempts: int, window_seconds: int) -> None:
        """Check rate limit for key. Raises HTTPException(429) if exceeded."""

    @abstractmethod
    def reset(self) -> None:
        """Reset rate limiter state (used in testing)."""


class InMemoryRateLimiter(BaseRateLimiter):
    """Thread-safe in-memory sliding-window rate limiter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, max_attempts: int, window_seconds: int) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= max_attempts:
                oldest_hit = bucket[0]
                retry_after = max(1, int(oldest_hit + window_seconds - now))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Please wait {retry_after} seconds before retrying.",
                    headers={"Retry-After": str(retry_after)},
                )

            bucket.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class RedisRateLimiter(BaseRateLimiter):
    """Shared Redis-backed sliding-window rate limiter.

    Uses Redis sorted sets for atomic distributed rate counting across multiple workers.
    Falls back safely if Redis encounters connection or operational errors.
    """

    def __init__(self, redis_client: Any = None, fallback_limiter: BaseRateLimiter | None = None) -> None:
        self._client = redis_client
        self._fallback = fallback_limiter or InMemoryRateLimiter()

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not settings.REDIS_URL:
            return None
        try:
            import redis
            self._client = redis.from_url(settings.REDIS_URL, decode_responses=True)
            return self._client
        except Exception as exc:
            logger.warning("Failed to initialize Redis client for rate limiting: %s", exc)
            return None

    def check(self, key: str, max_attempts: int, window_seconds: int) -> None:
        client = self._get_client()
        if client is None:
            # Fall back to local limiter if Redis not configured
            self._fallback.check(key, max_attempts, window_seconds)
            return

        redis_key = f"inkloom:ratelimit:{key}"
        now = time.time()
        cutoff = now - window_seconds
        member_id = f"{now}:{secrets.token_hex(4)}"

        try:
            pipe = client.pipeline()
            pipe.zremrangebyscore(redis_key, 0, cutoff)
            pipe.zcard(redis_key)
            pipe.zrange(redis_key, 0, 0, withscores=True)
            pipe.zadd(redis_key, {member_id: now})
            pipe.expire(redis_key, window_seconds + 5)
            results = pipe.execute()

            current_count = results[1]
            oldest_entries = results[2]

            if current_count >= max_attempts:
                oldest_score = oldest_entries[0][1] if oldest_entries else now
                retry_after = max(1, int(oldest_score + window_seconds - now))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Please wait {retry_after} seconds before retrying.",
                    headers={"Retry-After": str(retry_after)},
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Redis rate limiter error: %s", exc)
            if settings.RATE_LIMIT_FAIL_CLOSED:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limiting service temporarily unavailable. Please retry later.",
                    headers={"Retry-After": str(window_seconds)},
                ) from exc
            # Fail safely to in-memory fallback without disabling protection
            self._fallback.check(key, max_attempts, window_seconds)

    def reset(self) -> None:
        client = self._get_client()
        if client is not None:
            try:
                # Flush rate limit keys in Redis
                keys = client.keys("inkloom:ratelimit:*")
                if keys:
                    client.delete(*keys)
            except Exception as exc:
                logger.warning("Failed to reset Redis rate limit keys: %s", exc)
        self._fallback.reset()


_limiter_instance: BaseRateLimiter | None = None
_limiter_lock = threading.Lock()


def get_rate_limiter() -> BaseRateLimiter:
    """Retrieve or initialize the active rate limiter instance."""
    global _limiter_instance
    if _limiter_instance is None:
        with _limiter_lock:
            if _limiter_instance is None:
                if settings.REDIS_URL or settings.RATE_LIMIT_STORAGE_BACKEND == "redis":
                    _limiter_instance = RedisRateLimiter()
                else:
                    _limiter_instance = InMemoryRateLimiter()
    return _limiter_instance


def set_rate_limiter(limiter: BaseRateLimiter) -> None:
    """Explicitly set the rate limiter instance (used in tests)."""
    global _limiter_instance
    with _limiter_lock:
        _limiter_instance = limiter


# ==============================================================================
# FastAPI Dependencies
# ==============================================================================


def enforce_invitation_preview_rate_limit(request: Request) -> None:
    """Rate limit dependency for GET /api/v1/invitations/{token}."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    client_ip = get_client_ip(request)
    key = f"invitation_preview:{client_ip}"
    get_rate_limiter().check(
        key=key,
        max_attempts=settings.INVITATION_RATE_LIMIT_PREVIEW_MAX,
        window_seconds=settings.INVITATION_RATE_LIMIT_WINDOW_SECONDS,
    )


def enforce_invitation_accept_rate_limit(request: Request) -> None:
    """Rate limit dependency for POST /api/v1/invitations/{token}/accept."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    client_ip = get_client_ip(request)
    key = f"invitation_accept:{client_ip}"
    get_rate_limiter().check(
        key=key,
        max_attempts=settings.INVITATION_RATE_LIMIT_ACCEPT_MAX,
        window_seconds=settings.INVITATION_RATE_LIMIT_WINDOW_SECONDS,
    )


def enforce_invitation_register_rate_limit(request: Request) -> None:
    """Rate limit dependency for POST /api/v1/invitations/{token}/register-and-accept."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    client_ip = get_client_ip(request)
    key = f"invitation_register:{client_ip}"
    get_rate_limiter().check(
        key=key,
        max_attempts=settings.INVITATION_RATE_LIMIT_REGISTER_MAX,
        window_seconds=settings.INVITATION_RATE_LIMIT_WINDOW_SECONDS,
    )


def enforce_auth_rate_limit(request: Request) -> None:
    """Rate limit dependency for /api/v1/auth/login and /api/v1/auth/register."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    client_ip = get_client_ip(request)
    key = f"auth:{client_ip}:{request.url.path}"
    get_rate_limiter().check(
        key=key,
        max_attempts=settings.AUTH_RATE_LIMIT_MAX_ATTEMPTS,
        window_seconds=settings.AUTH_RATE_LIMIT_WINDOW_SECONDS,
    )
