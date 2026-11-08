"""Comprehensive Phase 2 automated test suite: Authentication, RBAC, and Tenant Isolation."""
import uuid
from datetime import timedelta
from collections.abc import Generator
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import auth_rate_limiter, create_access_token
from app.database import Base, get_db
from app.main import app
from app.models import (
    OrganisationMembership,
    RoleName,
    User,
)
from app.services.rbac_service import seed_roles_and_permissions


async def _register_account(
    client: AsyncClient,
    email: str = "founder@inkloom.ai",
    password: str = "SecurePass123",
    full_name: str = "Aarav Sharma",
    org_name: str = "Inkloom Enterprise",
) -> dict:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": full_name,
            "email": email,
            "password": password,
            "confirm_password": password,
            "organisation_name": org_name,
            "organisation_description": "Primary enterprise workspace",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# 1. Successful user registration
@pytest.mark.anyio
async def test_1_successful_user_registration(db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        data = await _register_account(client, email="  Founder@Inkloom.AI ")
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        user = data["user"]
        assert user["email"] == "founder@inkloom.ai"
        assert user["full_name"] == "Aarav Sharma"
        assert "password" not in user
        assert "password_hash" not in user
        assert len(user["memberships"]) == 1
        membership = user["memberships"][0]
        assert membership["role"] == RoleName.ADMIN
        assert "organisation:manage" in membership["permissions"]
        assert "users:manage" in membership["permissions"]

        # Verify password hash in DB is Argon2id and never plaintext
        db_user = db_session.execute(select(User).where(User.email == "founder@inkloom.ai")).scalar_one()
        assert db_user.password_hash.startswith("$argon2id$")
        assert "SecurePass123" not in db_user.password_hash


# 2. Duplicate email registration rejection
@pytest.mark.anyio
async def test_2_duplicate_email_registration_rejection(db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _register_account(client, email="dup@inkloom.ai")
        resp2 = await client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Second User",
                "email": "DUP@inkloom.ai",
                "password": "AnotherPassword123",
                "confirm_password": "AnotherPassword123",
                "organisation_name": "Second Org",
            },
        )
        assert resp2.status_code == 409
        assert "already exists" in resp2.json()["detail"].lower()


# 3. Successful login
@pytest.mark.anyio
async def test_3_successful_login(db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _register_account(client, email="login@inkloom.ai", password="LoginPass123")
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "LOGIN@inkloom.ai", "password": "LoginPass123"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"]
        assert body["user"]["email"] == "login@inkloom.ai"
        assert body["user"]["active_role"] == RoleName.ADMIN


# 4. Incorrect password rejection
@pytest.mark.anyio
async def test_4_incorrect_password_rejection(db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _register_account(client, email="wrongpass@inkloom.ai", password="CorrectPassword123")
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "wrongpass@inkloom.ai", "password": "WrongPassword999"},
        )
        assert resp.status_code == 401
        assert "invalid email or password" in resp.json()["detail"].lower()


# 5. Disabled user rejection
@pytest.mark.anyio
async def test_5_disabled_user_rejection(db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        reg = await _register_account(client, email="disabled@inkloom.ai", password="ValidPassword123")
        token = reg["access_token"]

        db_user = db_session.execute(select(User).where(User.email == "disabled@inkloom.ai")).scalar_one()
        db_user.is_active = False
        db_session.commit()

        # Login must fail with 403
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "disabled@inkloom.ai", "password": "ValidPassword123"},
        )
        assert login_resp.status_code == 403

        # Existing token must also be rejected on /me
        me_resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_resp.status_code == 403


# 6. Invalid or expired JWT rejection (and revoked token rejection on logout)
@pytest.mark.anyio
async def test_6_invalid_expired_and_revoked_jwt_rejection(db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        reg = await _register_account(client, email="token@inkloom.ai")
        user_id = reg["user"]["id"]

        # Tampered token
        tampered_resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {reg['access_token']}tampered"},
        )
        assert tampered_resp.status_code == 401

        # Expired token
        expired_token, _, _ = create_access_token(
            subject=user_id,
            email="token@inkloom.ai",
            expires_delta=timedelta(seconds=-10),
        )
        exp_resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert exp_resp.status_code == 401
        assert "expired" in exp_resp.json()["detail"].lower()

        # Logout revokes valid token
        logout_resp = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {reg['access_token']}"},
        )
        assert logout_resp.status_code == 200
        after_logout = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {reg['access_token']}"},
        )
        assert after_logout.status_code == 401
        assert "revoked" in after_logout.json()["detail"].lower()


# 7. Authenticated /auth/me
@pytest.mark.anyio
async def test_7_authenticated_auth_me(db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        reg = await _register_account(client, email="me@inkloom.ai", full_name="Meera Nair")
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {reg['access_token']}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "me@inkloom.ai"
        assert body["full_name"] == "Meera Nair"
        assert body["is_active"] is True
        assert body["active_role"] == RoleName.ADMIN
        assert len(body["memberships"]) == 1


# 8. Unauthenticated protected endpoint rejection
@pytest.mark.anyio
async def test_8_unauthenticated_protected_endpoint_rejection(db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        r1 = await client.get("/api/v1/auth/me")
        r2 = await client.get("/api/v1/organisations")
        r3 = await client.post("/api/v1/organisations", json={"name": "Unauthorized Org"})
        assert r1.status_code == 401
        assert r2.status_code == 401
        assert r3.status_code == 401


# 9. Organisation creation
@pytest.mark.anyio
async def test_9_organisation_creation(db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        reg = await _register_account(client, email="orgcreator@inkloom.ai")
        headers = {"Authorization": f"Bearer {reg['access_token']}"}

        create_resp = await client.post(
            "/api/v1/organisations",
            headers=headers,
            json={"name": "Second Brand Workspace", "description": "Regional division"},
        )
        assert create_resp.status_code == 201
        org_data = create_resp.json()
        assert org_data["name"] == "Second Brand Workspace"
        assert org_data["slug"] == "second-brand-workspace"
        assert org_data["current_user_role"] == RoleName.ADMIN

        list_resp = await client.get("/api/v1/organisations", headers=headers)
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 2


# 10. Organisation membership validation
@pytest.mark.anyio
async def test_10_organisation_membership_validation(db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        reg = await _register_account(client, email="admin10@inkloom.ai")
        headers = {"Authorization": f"Bearer {reg['access_token']}"}
        org_id = reg["user"]["memberships"][0]["organisation"]["id"]

        # Non-existent or non-member UUID must return 403
        random_org_id = str(uuid.uuid4())
        bad_resp = await client.get(f"/api/v1/organisations/{random_org_id}", headers=headers)
        assert bad_resp.status_code == 403

        good_resp = await client.get(f"/api/v1/organisations/{org_id}", headers=headers)
        assert good_resp.status_code == 200
        assert good_resp.json()["id"] == org_id


# 11. ADMIN permission checks
@pytest.mark.anyio
async def test_11_admin_permission_checks(db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        reg = await _register_account(client, email="admin11@inkloom.ai")
        headers = {"Authorization": f"Bearer {reg['access_token']}"}
        org_id = reg["user"]["memberships"][0]["organisation"]["id"]

        # Admin can update organisation details
        patch_resp = await client.patch(
            f"/api/v1/organisations/{org_id}",
            headers=headers,
            json={"name": "Updated Enterprise Name", "description": "Updated description"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["name"] == "Updated Enterprise Name"

        # Direct member addition without invitation acceptance is blocked (400)
        direct_add = await client.post(
            f"/api/v1/organisations/{org_id}/members",
            headers=headers,
            json={"email": "bm@inkloom.ai", "role": RoleName.BRAND_MANAGER},
        )
        assert direct_add.status_code == 400

        # Admin invites member via secure invitation flow
        invite_resp = await client.post(
            f"/api/v1/organisations/{org_id}/invitations",
            headers=headers,
            json={
                "email": "bm@inkloom.ai",
                "role": RoleName.BRAND_MANAGER,
            },
        )
        assert invite_resp.status_code == 201
        assert invite_resp.json()["role"] == RoleName.BRAND_MANAGER
        inv_token = invite_resp.json()["invitation_token"]

        # Recipient registers and accepts
        accept_resp = await client.post(
            f"/api/v1/invitations/{inv_token}/register-and-accept",
            json={
                "full_name": "Riddhi BrandManager",
                "password": "BrandPassword123",
                "confirm_password": "BrandPassword123",
            },
        )
        assert accept_resp.status_code == 201
        assert accept_resp.json()["user"]["active_role"] == RoleName.BRAND_MANAGER


async def _setup_org_with_role_member(
    client: AsyncClient,
    role: str,
    member_email: str,
) -> tuple[str, str, str, str]:
    """Helper returning (org_id, admin_token, member_token, member_membership_id) via invitation flow."""
    admin_reg = await _register_account(
        client,
        email=f"admin-{role.lower()}@inkloom.ai",
        org_name=f"Org {role}",
    )
    admin_token = admin_reg["access_token"]
    org_id = admin_reg["user"]["memberships"][0]["organisation"]["id"]

    # 1. Admin creates invitation via POST /api/v1/organisations/{org_id}/invitations
    invite_resp = await client.post(
        f"/api/v1/organisations/{org_id}/invitations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": member_email,
            "role": role,
        },
    )
    assert invite_resp.status_code == 201
    inv_token = invite_resp.json()["invitation_token"]

    # 2. Member registers and accepts the invitation atomically
    reg_accept_resp = await client.post(
        f"/api/v1/invitations/{inv_token}/register-and-accept",
        json={
            "full_name": f"Test {role}",
            "password": "RolePassword123",
            "confirm_password": "RolePassword123",
        },
    )
    assert reg_accept_resp.status_code == 201
    member_data = reg_accept_resp.json()
    member_token = member_data["access_token"]
    membership_id = member_data["user"]["memberships"][0]["membership_id"]

    return org_id, admin_token, member_token, membership_id


# 12. Brand Manager permission checks
@pytest.mark.anyio
async def test_12_brand_manager_permission_checks(db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        org_id, _, bm_token, _ = await _setup_org_with_role_member(
            client, RoleName.BRAND_MANAGER, "bm12@inkloom.ai"
        )
        headers = {"Authorization": f"Bearer {bm_token}", "X-Organisation-ID": org_id}

        # Verify /me permissions for BRAND_MANAGER
        me = (await client.get("/api/v1/auth/me", headers=headers)).json()
        assert me["active_role"] == RoleName.BRAND_MANAGER
        assert "brand:manage" in me["active_permissions"]
        assert "brand:read" in me["active_permissions"]
        assert "users:manage" not in me["active_permissions"]
        assert "organisation:manage" not in me["active_permissions"]

        # Can read members (users:read)
        members_resp = await client.get(f"/api/v1/organisations/{org_id}/members", headers=headers)
        assert members_resp.status_code == 200

        # Cannot update organisation details (requires organisation:manage)
        patch_org = await client.patch(
            f"/api/v1/organisations/{org_id}",
            headers=headers,
            json={"name": "Unauthorized Rename"},
        )
        assert patch_org.status_code == 403

        # Cannot add members (requires users:manage)
        add_member = await client.post(
            f"/api/v1/organisations/{org_id}/members",
            headers=headers,
            json={"email": "new@inkloom.ai", "role": RoleName.CONTENT_CREATOR},
        )
        assert add_member.status_code == 403


# 13. Content Creator permission checks
@pytest.mark.anyio
async def test_13_content_creator_permission_checks(db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        org_id, _, cc_token, _ = await _setup_org_with_role_member(
            client, RoleName.CONTENT_CREATOR, "cc13@inkloom.ai"
        )
        headers = {"Authorization": f"Bearer {cc_token}", "X-Organisation-ID": org_id}

        me = (await client.get("/api/v1/auth/me", headers=headers)).json()
        assert me["active_role"] == RoleName.CONTENT_CREATOR
        assert "content:create" in me["active_permissions"]
        assert "content:edit" in me["active_permissions"]
        assert "brand:manage" not in me["active_permissions"]
        assert "approval:decide" not in me["active_permissions"]
        assert "users:manage" not in me["active_permissions"]

        # Cannot modify organisation or add members
        assert (
            await client.patch(f"/api/v1/organisations/{org_id}", headers=headers, json={"name": "Nope"})
        ).status_code == 403


# 14. Reviewer permission checks
@pytest.mark.anyio
async def test_14_reviewer_permission_checks(db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        org_id, _, rev_token, _ = await _setup_org_with_role_member(
            client, RoleName.REVIEWER, "rev14@inkloom.ai"
        )
        headers = {"Authorization": f"Bearer {rev_token}", "X-Organisation-ID": org_id}

        me = (await client.get("/api/v1/auth/me", headers=headers)).json()
        assert me["active_role"] == RoleName.REVIEWER
        assert "approval:decide" in me["active_permissions"]
        assert "content:review" in me["active_permissions"]
        assert "content:create" not in me["active_permissions"]
        assert "users:manage" not in me["active_permissions"]

        # Reviewer cannot add or remove members
        assert (
            await client.post(
                f"/api/v1/organisations/{org_id}/members",
                headers=headers,
                json={"email": "x@inkloom.ai", "role": RoleName.REVIEWER},
            )
        ).status_code == 403


# 15. Cross-organisation access rejection (Tenant Isolation & IDOR protection)
@pytest.mark.anyio
async def test_15_cross_organisation_access_rejection(db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        tenant_a = await _register_account(client, email="admin_a@tenant-a.com", org_name="Tenant Alpha")
        tenant_b = await _register_account(client, email="admin_b@tenant-b.com", org_name="Tenant Beta")

        org_a_id = tenant_a["user"]["memberships"][0]["organisation"]["id"]
        org_b_id = tenant_b["user"]["memberships"][0]["organisation"]["id"]
        org_b_membership_id = tenant_b["user"]["memberships"][0]["membership_id"]

        headers_a = {"Authorization": f"Bearer {tenant_a['access_token']}"}

        # Tenant A Admin attempting to read Tenant B details, members, or modify Tenant B must get 403
        assert (await client.get(f"/api/v1/organisations/{org_b_id}", headers=headers_a)).status_code == 403
        assert (
            await client.get(f"/api/v1/organisations/{org_b_id}/members", headers=headers_a)
        ).status_code == 403
        assert (
            await client.patch(
                f"/api/v1/organisations/{org_b_id}",
                headers=headers_a,
                json={"name": "Hijacked by Tenant A"},
            )
        ).status_code == 403
        assert (
            await client.delete(
                f"/api/v1/organisations/{org_b_id}/members/{org_b_membership_id}",
                headers=headers_a,
            )
        ).status_code == 403

        # Even using Tenant A's own org path with Tenant B's membership_id must fail (404)
        cross_member_patch = await client.patch(
            f"/api/v1/organisations/{org_a_id}/members/{org_b_membership_id}",
            headers=headers_a,
            json={"role": RoleName.REVIEWER},
        )
        assert cross_member_patch.status_code == 404

        # Spoofing X-Organisation-ID header for Tenant B on /auth/me must be rejected with 403
        spoof_me = await client.get(
            "/api/v1/auth/me",
            headers={**headers_a, "X-Organisation-ID": org_b_id},
        )
        assert spoof_me.status_code == 403


# 16. User cannot change their own role without permission
@pytest.mark.anyio
async def test_16_user_cannot_change_own_role_without_permission(db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        org_id, _, cc_token, cc_membership_id = await _setup_org_with_role_member(
            client, RoleName.CONTENT_CREATOR, "selfpromote@inkloom.ai"
        )
        resp = await client.patch(
            f"/api/v1/organisations/{org_id}/members/{cc_membership_id}",
            headers={"Authorization": f"Bearer {cc_token}"},
            json={"role": RoleName.ADMIN},
        )
        assert resp.status_code == 403
        assert "users:manage" in resp.json()["detail"]


# 17. Last active ADMIN cannot be removed or demoted
@pytest.mark.anyio
async def test_17_last_active_admin_cannot_be_removed_or_demoted(db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        reg = await _register_account(client, email="soleadmin@inkloom.ai")
        headers = {"Authorization": f"Bearer {reg['access_token']}"}
        org_id = reg["user"]["memberships"][0]["organisation"]["id"]
        admin_membership_id = reg["user"]["memberships"][0]["membership_id"]

        # Attempt to demote sole ADMIN -> 400
        demote_resp = await client.patch(
            f"/api/v1/organisations/{org_id}/members/{admin_membership_id}",
            headers=headers,
            json={"role": RoleName.BRAND_MANAGER},
        )
        assert demote_resp.status_code == 400
        assert "last active admin" in demote_resp.json()["detail"].lower()

        # Attempt to delete sole ADMIN -> 400
        delete_resp = await client.delete(
            f"/api/v1/organisations/{org_id}/members/{admin_membership_id}",
            headers=headers,
        )
        assert delete_resp.status_code == 400
        assert "last active admin" in delete_resp.json()["detail"].lower()

        # Invite and accept a second ADMIN, then demoting the first ADMIN succeeds
        second_admin_invite = await client.post(
            f"/api/v1/organisations/{org_id}/invitations",
            headers=headers,
            json={
                "email": "secondadmin@inkloom.ai",
                "role": RoleName.ADMIN,
            },
        )
        assert second_admin_invite.status_code == 201
        second_token = second_admin_invite.json()["invitation_token"]

        second_admin_accept = await client.post(
            f"/api/v1/invitations/{second_token}/register-and-accept",
            json={
                "full_name": "Second Admin",
                "password": "SecondPassword123",
                "confirm_password": "SecondPassword123",
            },
        )
        assert second_admin_accept.status_code == 201

        demote_after_second = await client.patch(
            f"/api/v1/organisations/{org_id}/members/{admin_membership_id}",
            headers=headers,
            json={"role": RoleName.BRAND_MANAGER},
        )
        assert demote_after_second.status_code == 200
        assert demote_after_second.json()["role"] == RoleName.BRAND_MANAGER
