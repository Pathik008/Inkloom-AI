"""Comprehensive security tests for public invitation rate limiting in Inkloom AI.

Test Coverage:
1. Repeated public preview requests from the same client -> 429 with Retry-After.
2. Repeated registration-and-acceptance requests -> 429 with Retry-After.
3. Authenticated acceptance requests -> 429 with Retry-After.
4. Independent client IP limits (different IPs do not affect each other).
5. Spoofed forwarding headers (X-Forwarded-For ignored from untrusted peers).
6. Trusted reverse proxy X-Forwarded-For parsing (right-to-left traversal).
7. Redis failure behavior: falls back safely to in-memory limiting without crashing or silently disabling protection.
8. Redis failure behavior under fail-closed configuration.
9. Valid invitation acceptance remains fully functional under rate limits.
10. Existing token reuse and security protections remain fully functional.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import (
    InMemoryRateLimiter,
    RedisRateLimiter,
    get_rate_limiter,
    set_rate_limiter,
)
from app.main import app
from app.models import (
    MembershipStatus,
    Organisation,
    OrganisationMembership,
    Role,
    RoleName,
    User,
)
from app.services.invitation_service import (
    create_organisation_invitation,
)
from app.services.organisation_service import get_role_by_name


@pytest.fixture(autouse=True)
def reset_limiter_state():
    """Ensure limiter is clean and reset before and after each test."""
    set_rate_limiter(InMemoryRateLimiter())
    get_rate_limiter().reset()
    yield
    get_rate_limiter().reset()


def _create_test_org_and_admin(db: Session, prefix: str = "rate-limit") -> tuple[Organisation, User, Role]:
    admin_role = get_role_by_name(db, RoleName.ADMIN)
    admin_user = User(
        full_name=f"{prefix} Admin",
        email=f"{prefix}.admin.{uuid.uuid4().hex[:6]}@inkloom.test",
        password_hash="test-password-hash",
        is_active=True,
        is_verified=True,
    )
    db.add(admin_user)
    db.flush()

    org = Organisation(
        name=f"{prefix} Workspace",
        slug=f"{prefix}-{uuid.uuid4().hex[:6]}",
        created_by=admin_user.id,
    )
    db.add(org)
    db.flush()

    membership = OrganisationMembership(
        user_id=admin_user.id,
        organisation_id=org.id,
        role_id=admin_role.id,
        status=MembershipStatus.ACTIVE,
    )
    db.add(membership)
    db.commit()
    db.refresh(org)
    db.refresh(admin_user)
    return org, admin_user, admin_role


@pytest.mark.anyio
async def test_public_preview_rate_limit_exceeded_returns_429_and_retry_after(db_session: Session) -> None:
    """Repeated preview requests from same client exceed limit and return HTTP 429 with Retry-After."""
    transport = ASGITransport(app=app, client=("198.51.100.1", 50000))
    org, admin, admin_role = _create_test_org_and_admin(db_session, prefix="preview-rl")
    inv, raw_token = create_organisation_invitation(
        db=db_session,
        organisation=org,
        inviter=admin,
        email="invitee@inkloom.test",
        target_role=admin_role,
    )

    max_attempts = settings.INVITATION_RATE_LIMIT_PREVIEW_MAX

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Make exactly max_attempts requests (should succeed)
        for _ in range(max_attempts):
            resp = await client.get(f"/api/v1/invitations/{raw_token}")
            assert resp.status_code == 200

        # Next request must be throttled with 429
        throttled = await client.get(f"/api/v1/invitations/{raw_token}")
        assert throttled.status_code == 429
        assert "Retry-After" in throttled.headers
        assert int(throttled.headers["Retry-After"]) >= 1
        assert "Rate limit exceeded" in throttled.json()["detail"]


@pytest.mark.anyio
async def test_independent_client_ip_limits(db_session: Session) -> None:
    """Client A hitting the rate limit does not affect Client B from a different IP."""
    org, admin, admin_role = _create_test_org_and_admin(db_session, prefix="multi-ip")
    inv, raw_token = create_organisation_invitation(
        db=db_session,
        organisation=org,
        inviter=admin,
        email="multi-ip@inkloom.test",
        target_role=admin_role,
    )

    transport_a = ASGITransport(app=app, client=("198.51.100.10", 50000))
    transport_b = ASGITransport(app=app, client=("198.51.100.20", 50000))

    max_attempts = settings.INVITATION_RATE_LIMIT_PREVIEW_MAX

    async with AsyncClient(transport=transport_a, base_url="http://testserver") as client_a, \
               AsyncClient(transport=transport_b, base_url="http://testserver") as client_b:

        # Exhaust Client A's quota
        for _ in range(max_attempts):
            resp = await client_a.get(f"/api/v1/invitations/{raw_token}")
            assert resp.status_code == 200

        # Client A is now throttled
        throttled_a = await client_a.get(f"/api/v1/invitations/{raw_token}")
        assert throttled_a.status_code == 429

        # Client B should STILL succeed unimpeded
        resp_b = await client_b.get(f"/api/v1/invitations/{raw_token}")
        assert resp_b.status_code == 200


@pytest.mark.anyio
async def test_registration_and_accept_rate_limit_exceeded(db_session: Session) -> None:
    """Repeated registration-and-acceptance attempts are strictly rate-limited."""
    transport = ASGITransport(app=app, client=("198.51.100.33", 50000))
    max_attempts = settings.INVITATION_RATE_LIMIT_REGISTER_MAX

    payload = {
        "full_name": "Test User",
        "password": "Password123",
        "confirm_password": "Password123",
    }

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Generate attempts with dummy/nonexistent tokens
        for i in range(max_attempts):
            resp = await client.post(f"/api/v1/invitations/dummy-token-{i}/register-and-accept", json=payload)
            # Rejection is 404 (token not found), but not 429 yet
            assert resp.status_code == 404

        # Next attempt must be throttled with HTTP 429
        throttled = await client.post("/api/v1/invitations/dummy-token-next/register-and-accept", json=payload)
        assert throttled.status_code == 429
        assert "Retry-After" in throttled.headers
        assert int(throttled.headers["Retry-After"]) >= 1


@pytest.mark.anyio
async def test_authenticated_acceptance_rate_limit_exceeded(db_session: Session) -> None:
    """Authenticated acceptance endpoint enforces IP-scoped rate limiting."""
    transport = ASGITransport(app=app, client=("198.51.100.44", 50000))
    max_attempts = settings.INVITATION_RATE_LIMIT_ACCEPT_MAX

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        for i in range(max_attempts):
            resp = await client.post(
                f"/api/v1/invitations/dummy-token-{i}/accept",
                headers={"Authorization": "Bearer dummy-token"},
            )
            assert resp.status_code in (401, 404)

        throttled = await client.post(
            "/api/v1/invitations/dummy-token-next/accept",
            headers={"Authorization": "Bearer dummy-token"},
        )
        assert throttled.status_code == 429
        assert "Retry-After" in throttled.headers


@pytest.mark.anyio
async def test_spoofed_forwarding_headers_ignored_from_untrusted_peer(db_session: Session) -> None:
    """An untrusted client cannot bypass rate limits by sending rotating X-Forwarded-For headers."""
    untrusted_peer_ip = "198.51.100.77"
    transport = ASGITransport(app=app, client=(untrusted_peer_ip, 50000))
    max_attempts = settings.INVITATION_RATE_LIMIT_PREVIEW_MAX

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Client sends rotating spoofed X-Forwarded-For on every request
        for i in range(max_attempts):
            resp = await client.get(
                "/api/v1/invitations/non-existent-token",
                headers={"X-Forwarded-For": f"203.0.113.{i + 1}"},
            )
            assert resp.status_code == 404

        # The client MUST be rate limited based on its true peer IP (198.51.100.77), ignoring spoofed header
        throttled = await client.get(
            "/api/v1/invitations/non-existent-token",
            headers={"X-Forwarded-For": "203.0.113.250"},
        )
        assert throttled.status_code == 429


@pytest.mark.anyio
async def test_trusted_proxy_forwarded_for_parsed_correctly(db_session: Session) -> None:
    """When request comes from a trusted proxy (127.0.0.1), client IP is extracted from X-Forwarded-For."""
    trusted_proxy_transport = ASGITransport(app=app, client=("127.0.0.1", 50000))
    real_client_ip = "192.0.2.99"
    max_attempts = settings.INVITATION_RATE_LIMIT_PREVIEW_MAX

    async with AsyncClient(transport=trusted_proxy_transport, base_url="http://testserver") as client:
        for _ in range(max_attempts):
            resp = await client.get(
                "/api/v1/invitations/non-existent-token",
                headers={"X-Forwarded-For": real_client_ip},
            )
            assert resp.status_code == 404

        # Next request from this forwarded IP should trigger 429
        throttled = await client.get(
            "/api/v1/invitations/non-existent-token",
            headers={"X-Forwarded-For": real_client_ip},
        )
        assert throttled.status_code == 429

        # Another client forwarded through the same proxy should not be throttled
        different_forwarded_ip = "192.0.2.100"
        resp_different = await client.get(
            "/api/v1/invitations/non-existent-token",
            headers={"X-Forwarded-For": different_forwarded_ip},
        )
        assert resp_different.status_code == 404


def test_redis_failure_behavior_fallback_to_memory(monkeypatch) -> None:
    """When Redis is configured but raises a connection error, it fails safely to in-memory limiting."""
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute.side_effect = ConnectionError("Redis connection refused")
    mock_redis.pipeline.return_value = mock_pipe

    fallback = InMemoryRateLimiter()
    limiter = RedisRateLimiter(redis_client=mock_redis, fallback_limiter=fallback)
    set_rate_limiter(limiter)

    # settings.RATE_LIMIT_FAIL_CLOSED is False by default: should use fallback without crashing
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED", False)

    # Rate limit check should not raise 500, but should record hit in fallback
    limiter.check(key="test-redis-fail:1.2.3.4", max_attempts=2, window_seconds=60)
    limiter.check(key="test-redis-fail:1.2.3.4", max_attempts=2, window_seconds=60)

    # Third check must hit limit and raise 429 via fallback
    with pytest.raises(Exception) as excinfo:
        limiter.check(key="test-redis-fail:1.2.3.4", max_attempts=2, window_seconds=60)
    assert excinfo.value.status_code == 429


def test_redis_failure_behavior_fail_closed(monkeypatch) -> None:
    """When RATE_LIMIT_FAIL_CLOSED is True and Redis fails, it rejects traffic with 429 rather than bypassing."""
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute.side_effect = TimeoutError("Redis connection timeout")
    mock_redis.pipeline.return_value = mock_pipe

    limiter = RedisRateLimiter(redis_client=mock_redis)
    set_rate_limiter(limiter)

    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED", True)

    with pytest.raises(Exception) as excinfo:
        limiter.check(key="test-fail-closed:1.2.3.4", max_attempts=5, window_seconds=60)
    assert excinfo.value.status_code == 429
    assert "temporarily unavailable" in excinfo.value.detail


@pytest.mark.anyio
async def test_valid_invitation_acceptance_under_limit_remains_functional(db_session: Session) -> None:
    """Legitimate invitation acceptance under normal traffic succeeds smoothly with rate limits active."""
    org, admin, admin_role = _create_test_org_and_admin(db_session, prefix="valid-flow")
    inv, raw_token = create_organisation_invitation(
        db=db_session,
        organisation=org,
        inviter=admin,
        email="valid.recipient@inkloom.test",
        target_role=admin_role,
    )

    transport = ASGITransport(app=app, client=("198.51.100.88", 50000))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Preview
        preview_resp = await client.get(f"/api/v1/invitations/{raw_token}")
        assert preview_resp.status_code == 200
        assert preview_resp.json()["email"] == "valid.recipient@inkloom.test"

        # 2. Register & Accept
        reg_resp = await client.post(
            f"/api/v1/invitations/{raw_token}/register-and-accept",
            json={
                "full_name": "Valid Recipient",
                "password": "ValidPassword123",
                "confirm_password": "ValidPassword123",
            },
        )
        assert reg_resp.status_code == 201
        assert "access_token" in reg_resp.json()
        assert reg_resp.json()["user"]["email"] == "valid.recipient@inkloom.test"


@pytest.mark.anyio
async def test_token_reuse_protection_remains_functional_with_rate_limits(db_session: Session) -> None:
    """Invitation single-use protection (HTTP 409) remains functional and not masked by rate limits."""
    org, admin, admin_role = _create_test_org_and_admin(db_session, prefix="reuse-flow")
    inv, raw_token = create_organisation_invitation(
        db=db_session,
        organisation=org,
        inviter=admin,
        email="reuse.test@inkloom.test",
        target_role=admin_role,
    )

    transport = ASGITransport(app=app, client=("198.51.100.99", 50000))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # First acceptance succeeds
        first_resp = await client.post(
            f"/api/v1/invitations/{raw_token}/register-and-accept",
            json={
                "full_name": "Reuse User",
                "password": "Password123",
                "confirm_password": "Password123",
            },
        )
        assert first_resp.status_code == 201

        # Second acceptance should return 409 Conflict, preserving business logic
        second_resp = await client.post(
            f"/api/v1/invitations/{raw_token}/register-and-accept",
            json={
                "full_name": "Reuse User Two",
                "password": "Password123",
                "confirm_password": "Password123",
            },
        )
        assert second_resp.status_code == 409
        assert "already been accepted" in second_resp.json()["detail"]
