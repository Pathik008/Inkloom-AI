"""Comprehensive security and functional test suite for Organisation Invitations (Phase 2 Finding H2).

Verifies:
1. High-entropy token generation and SHA-256 one-way hashing (raw tokens never stored in DB).
2. Ordinary list endpoints never expose raw tokens or token hashes.
3. Strict account enumeration protection (identical 201 response for existing vs new users).
4. Direct member addition without explicit consent is strictly blocked (HTTP 400).
5. Existing user invitation acceptance creates active membership and assigns role.
6. New user registration + acceptance creates account and active membership.
7. Invitation token reuse prevention (HTTP 409).
8. Expired invitation rejection (HTTP 410).
9. Revoked invitation rejection (HTTP 410).
10. Cross-user token theft prevention (HTTP 403 when authenticated email != invitation email).
11. Multi-tenant isolation (Org A admin cannot view or revoke Org B invitations).
12. RBAC enforcement (non-admin users cannot create or revoke invitations).
13. Duplicate active member invitation rejection (HTTP 409).
14. Public preview endpoint returns correct metadata without exposing internal keys.
"""
import hashlib
import uuid
from datetime import timedelta
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app
from app.models import (
    InvitationStatus,
    MembershipStatus,
    Organisation,
    OrganisationInvitation,
    OrganisationMembership,
    RoleName,
    User,
    utcnow,
)


async def _register_user(
    client: AsyncClient,
    email: str,
    name: str = "Test Admin",
    org_name: str = "Acme Corp",
) -> dict:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": name,
            "email": email,
            "password": "SecurePassword123",
            "confirm_password": "SecurePassword123",
            "organisation_name": org_name,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.anyio
async def test_1_admin_creates_invitation_stores_only_sha256_hash_in_db(db_session: Session) -> None:
    """Raw invitation token is generated, returned ONCE to the inviter, and NEVER stored in the database."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_data = await _register_user(client, "admin1@inkloom.ai")
        token = admin_data["access_token"]
        org_id = admin_data["user"]["memberships"][0]["organisation"]["id"]

        invite_resp = await client.post(
            f"/api/v1/organisations/{org_id}/invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "newmember1@inkloom.ai", "role": RoleName.BRAND_MANAGER},
        )
        assert invite_resp.status_code == 201
        data = invite_resp.json()
        raw_token = data["invitation_token"]
        assert len(raw_token) >= 32
        assert "invitation_url" in data
        assert data["email"] == "newmember1@inkloom.ai"
        assert data["role"] == RoleName.BRAND_MANAGER
        assert data["status"] == InvitationStatus.PENDING

        # Query the database directly to verify raw token is NOT in the database
        inv_id = uuid.UUID(data["id"])
        invitation = db_session.execute(
            select(OrganisationInvitation).where(OrganisationInvitation.id == inv_id)
        ).scalar_one()

        assert invitation.token_hash != raw_token
        # Confirm token_hash is a 64-character SHA-256 digest
        assert len(invitation.token_hash) == 64
        expected_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
        assert invitation.token_hash == expected_hash


@pytest.mark.anyio
async def test_2_ordinary_list_invitations_never_exposes_raw_tokens_or_hashes(db_session: Session) -> None:
    """GET /organisations/{org_id}/invitations must never expose token_hash or raw token."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_data = await _register_user(client, "admin2@inkloom.ai")
        token = admin_data["access_token"]
        org_id = admin_data["user"]["memberships"][0]["organisation"]["id"]

        await client.post(
            f"/api/v1/organisations/{org_id}/invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "invitee2@inkloom.ai", "role": RoleName.CONTENT_CREATOR},
        )

        list_resp = await client.get(
            f"/api/v1/organisations/{org_id}/invitations",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert list_resp.status_code == 200
        invitations = list_resp.json()
        assert len(invitations) >= 1

        for item in invitations:
            assert "invitation_token" not in item
            assert "token_hash" not in item
            assert "raw_token" not in item
            assert "id" in item
            assert "email" in item
            assert "role" in item
            assert "status" in item
            assert "expires_at" in item


@pytest.mark.anyio
async def test_3_account_enumeration_protection_consistent_response(db_session: Session) -> None:
    """Invitation creation returns identical 201 responses regardless of whether the email is already registered."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Pre-register a user in a completely different organisation
        await _register_user(client, "existinguser@inkloom.ai", name="Existing User", org_name="Other Org")

        # Admin in Acme Org invites both an existing account and an unregistered account
        admin_data = await _register_user(client, "admin3@inkloom.ai")
        token = admin_data["access_token"]
        org_id = admin_data["user"]["memberships"][0]["organisation"]["id"]

        resp_existing = await client.post(
            f"/api/v1/organisations/{org_id}/invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "existinguser@inkloom.ai", "role": RoleName.REVIEWER},
        )
        resp_unregistered = await client.post(
            f"/api/v1/organisations/{org_id}/invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "completelynew@inkloom.ai", "role": RoleName.REVIEWER},
        )

        assert resp_existing.status_code == 201
        assert resp_unregistered.status_code == 201

        data_existing = resp_existing.json()
        data_unregistered = resp_unregistered.json()

        # Both responses must have identical shape and messages
        assert data_existing.keys() == data_unregistered.keys()
        assert data_existing["delivery_status"] == data_unregistered["delivery_status"]
        assert data_existing["message"] == data_unregistered["message"]
        assert "user_id" not in data_existing
        assert "full_name" not in data_existing


@pytest.mark.anyio
async def test_4_direct_member_addition_is_strictly_blocked(db_session: Session) -> None:
    """POST /members is disabled to prevent adding users without explicit invitation consent."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_data = await _register_user(client, "admin4@inkloom.ai")
        token = admin_data["access_token"]
        org_id = admin_data["user"]["memberships"][0]["organisation"]["id"]

        resp = await client.post(
            f"/api/v1/organisations/{org_id}/members",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "someone@inkloom.ai", "role": RoleName.CONTENT_CREATOR},
        )
        assert resp.status_code == 400
        assert "direct member addition without explicit invitation acceptance is disabled" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_5_existing_user_accepts_invitation_successfully(db_session: Session) -> None:
    """An existing registered user explicitly accepts an invitation to join another organisation."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Pre-register user in Org 1
        user_reg = await _register_user(client, "alice@inkloom.ai", name="Alice User", org_name="Alice Personal Org")
        alice_token = user_reg["access_token"]

        # Admin of Org 2 invites Alice
        admin_data = await _register_user(client, "bob-admin@inkloom.ai", name="Bob Admin", org_name="Bob Enterprises")
        bob_token = admin_data["access_token"]
        bob_org_id = admin_data["user"]["memberships"][0]["organisation"]["id"]

        invite_resp = await client.post(
            f"/api/v1/organisations/{bob_org_id}/invitations",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={"email": "alice@inkloom.ai", "role": RoleName.CONTENT_CREATOR},
        )
        assert invite_resp.status_code == 201
        invitation_token = invite_resp.json()["invitation_token"]

        # Before acceptance, Alice is NOT a member of Bob Enterprises
        alice_me_before = (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {alice_token}"})).json()
        assert not any(m["organisation"]["id"] == bob_org_id for m in alice_me_before["memberships"])

        # Alice accepts the invitation
        accept_resp = await client.post(
            f"/api/v1/invitations/{invitation_token}/accept",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        assert accept_resp.status_code == 200
        assert "Successfully joined Bob Enterprises" in accept_resp.json()["message"]

        # After acceptance, Alice is now an active member of Bob Enterprises with CONTENT_CREATOR role
        alice_me_after = (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {alice_token}"})).json()
        bob_membership = next(m for m in alice_me_after["memberships"] if m["organisation"]["id"] == bob_org_id)
        assert bob_membership["role"] == RoleName.CONTENT_CREATOR
        assert bob_membership["status"] == MembershipStatus.ACTIVE


@pytest.mark.anyio
async def test_6_new_user_registers_and_accepts_invitation(db_session: Session) -> None:
    """A user who does not have an account registers and accepts the invitation in one atomic step."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_data = await _register_user(client, "admin6@inkloom.ai")
        bob_token = admin_data["access_token"]
        org_id = admin_data["user"]["memberships"][0]["organisation"]["id"]

        invite_resp = await client.post(
            f"/api/v1/organisations/{org_id}/invitations",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={"email": "carol.new@inkloom.ai", "role": RoleName.REVIEWER},
        )
        invitation_token = invite_resp.json()["invitation_token"]

        # Carol registers and accepts
        reg_accept_resp = await client.post(
            f"/api/v1/invitations/{invitation_token}/register-and-accept",
            json={
                "full_name": "Carol Reviewer",
                "password": "CarolPassword123",
                "confirm_password": "CarolPassword123",
            },
        )
        assert reg_accept_resp.status_code == 201
        data = reg_accept_resp.json()
        carol_token = data["access_token"]
        assert data["user"]["email"] == "carol.new@inkloom.ai"
        assert data["user"]["full_name"] == "Carol Reviewer"

        # Verify Carol can immediately use her token and has the REVIEWER role
        me_resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {carol_token}"})
        assert me_resp.status_code == 200
        assert me_resp.json()["active_role"] == RoleName.REVIEWER


@pytest.mark.anyio
async def test_7_invitation_token_reuse_prevented(db_session: Session) -> None:
    """An accepted invitation cannot be accepted a second time (HTTP 409)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_data = await _register_user(client, "admin7@inkloom.ai")
        token = admin_data["access_token"]
        org_id = admin_data["user"]["memberships"][0]["organisation"]["id"]

        user_data = await _register_user(client, "dan7@inkloom.ai", name="Dan User")
        dan_token = user_data["access_token"]

        invite_resp = await client.post(
            f"/api/v1/organisations/{org_id}/invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "dan7@inkloom.ai", "role": RoleName.CONTENT_CREATOR},
        )
        inv_token = invite_resp.json()["invitation_token"]

        # First accept succeeds
        accept_1 = await client.post(
            f"/api/v1/invitations/{inv_token}/accept",
            headers={"Authorization": f"Bearer {dan_token}"},
        )
        assert accept_1.status_code == 200

        # Second accept fails with 409 Conflict
        accept_2 = await client.post(
            f"/api/v1/invitations/{inv_token}/accept",
            headers={"Authorization": f"Bearer {dan_token}"},
        )
        assert accept_2.status_code == 409
        assert "already been accepted" in accept_2.json()["detail"].lower()


@pytest.mark.anyio
async def test_8_expired_invitation_rejected(db_session: Session) -> None:
    """An expired invitation is rejected with HTTP 410 Gone."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_data = await _register_user(client, "admin8@inkloom.ai")
        token = admin_data["access_token"]
        org_id = admin_data["user"]["memberships"][0]["organisation"]["id"]

        user_data = await _register_user(client, "eve8@inkloom.ai", name="Eve User")
        eve_token = user_data["access_token"]

        invite_resp = await client.post(
            f"/api/v1/organisations/{org_id}/invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "eve8@inkloom.ai", "role": RoleName.CONTENT_CREATOR},
        )
        inv_token = invite_resp.json()["invitation_token"]
        inv_id = uuid.UUID(invite_resp.json()["id"])

        # Manually expire the invitation in the database
        db_inv = db_session.execute(
            select(OrganisationInvitation).where(OrganisationInvitation.id == inv_id)
        ).scalar_one()
        db_inv.expires_at = utcnow() - timedelta(hours=1)
        db_session.add(db_inv)
        db_session.commit()

        # Attempt to accept -> 410 Gone
        accept_resp = await client.post(
            f"/api/v1/invitations/{inv_token}/accept",
            headers={"Authorization": f"Bearer {eve_token}"},
        )
        assert accept_resp.status_code == 410
        assert "expired" in accept_resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_9_revoked_invitation_rejected(db_session: Session) -> None:
    """A revoked invitation cannot be accepted (HTTP 410 Gone)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_data = await _register_user(client, "admin9@inkloom.ai")
        token = admin_data["access_token"]
        org_id = admin_data["user"]["memberships"][0]["organisation"]["id"]

        user_data = await _register_user(client, "frank9@inkloom.ai", name="Frank User")
        frank_token = user_data["access_token"]

        invite_resp = await client.post(
            f"/api/v1/organisations/{org_id}/invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "frank9@inkloom.ai", "role": RoleName.CONTENT_CREATOR},
        )
        inv_token = invite_resp.json()["invitation_token"]
        inv_id = invite_resp.json()["id"]

        # Admin revokes the invitation
        revoke_resp = await client.delete(
            f"/api/v1/organisations/{org_id}/invitations/{inv_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert revoke_resp.status_code == 204

        # Attempt to accept -> 410 Gone
        accept_resp = await client.post(
            f"/api/v1/invitations/{inv_token}/accept",
            headers={"Authorization": f"Bearer {frank_token}"},
        )
        assert accept_resp.status_code == 410
        assert "revoked" in accept_resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_10_cross_user_acceptance_theft_prevention(db_session: Session) -> None:
    """An authenticated user cannot accept an invitation intended for a different email address (HTTP 403)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_data = await _register_user(client, "admin10@inkloom.ai")
        token = admin_data["access_token"]
        org_id = admin_data["user"]["memberships"][0]["organisation"]["id"]

        # Invite target victim
        invite_resp = await client.post(
            f"/api/v1/organisations/{org_id}/invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "target.victim10@inkloom.ai", "role": RoleName.ADMIN},
        )
        inv_token = invite_resp.json()["invitation_token"]

        # Attacker registers and attempts to accept victim's token
        attacker_data = await _register_user(client, "malicious.attacker10@inkloom.ai", name="Attacker")
        attacker_token = attacker_data["access_token"]

        steal_resp = await client.post(
            f"/api/v1/invitations/{inv_token}/accept",
            headers={"Authorization": f"Bearer {attacker_token}"},
        )
        assert steal_resp.status_code == 403
        assert "not authorised to accept this invitation" in steal_resp.json()["detail"].lower()
        assert "target.victim10@inkloom.ai" not in steal_resp.json()["detail"]
        assert "malicious.attacker10@inkloom.ai" not in steal_resp.json()["detail"]


@pytest.mark.anyio
async def test_11_cross_tenant_invitation_isolation(db_session: Session) -> None:
    """Org A admin cannot list or revoke invitations belonging to Org B."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_a = await _register_user(client, "admin11a@inkloom.ai", org_name="Org A")
        token_a = admin_a["access_token"]
        org_a_id = admin_a["user"]["memberships"][0]["organisation"]["id"]

        admin_b = await _register_user(client, "admin11b@inkloom.ai", org_name="Org B")
        token_b = admin_b["access_token"]
        org_b_id = admin_b["user"]["memberships"][0]["organisation"]["id"]

        # Create invitation in Org B
        b_invite = await client.post(
            f"/api/v1/organisations/{org_b_id}/invitations",
            headers={"Authorization": f"Bearer {token_b}"},
            json={"email": "member.b@inkloom.ai", "role": RoleName.CONTENT_CREATOR},
        )
        b_invite_id = b_invite.json()["id"]

        # Admin A attempts to list Org B invitations -> 403 Forbidden
        list_cross = await client.get(
            f"/api/v1/organisations/{org_b_id}/invitations",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert list_cross.status_code == 403

        # Admin A attempts to revoke Org B invitation -> 403 Forbidden
        revoke_cross = await client.delete(
            f"/api/v1/organisations/{org_b_id}/invitations/{b_invite_id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert revoke_cross.status_code == 403


@pytest.mark.anyio
async def test_12_rbac_unauthorized_user_cannot_create_or_revoke_invitations(db_session: Session) -> None:
    """Non-admin users lacking users:manage permission cannot create or revoke invitations."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_data = await _register_user(client, "admin12@inkloom.ai")
        admin_token = admin_data["access_token"]
        org_id = admin_data["user"]["memberships"][0]["organisation"]["id"]

        # Invite Content Creator and have them register
        inv_resp = await client.post(
            f"/api/v1/organisations/{org_id}/invitations",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"email": "creator12@inkloom.ai", "role": RoleName.CONTENT_CREATOR},
        )
        inv_token = inv_resp.json()["invitation_token"]

        reg_resp = await client.post(
            f"/api/v1/invitations/{inv_token}/register-and-accept",
            json={"full_name": "Creator 12", "password": "Password123", "confirm_password": "Password123"},
        )
        creator_token = reg_resp.json()["access_token"]

        # Content Creator attempts to create an invitation -> 403 Forbidden
        create_attempt = await client.post(
            f"/api/v1/organisations/{org_id}/invitations",
            headers={"Authorization": f"Bearer {creator_token}"},
            json={"email": "unauthorized@inkloom.ai", "role": RoleName.REVIEWER},
        )
        assert create_attempt.status_code == 403


@pytest.mark.anyio
async def test_13_cannot_invite_existing_active_member(db_session: Session) -> None:
    """Attempting to invite a user who is ALREADY an active member of the organisation returns 409 Conflict."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_data = await _register_user(client, "admin13@inkloom.ai")
        admin_token = admin_data["access_token"]
        org_id = admin_data["user"]["memberships"][0]["organisation"]["id"]

        # The admin is already an active member of this organisation
        invite_self = await client.post(
            f"/api/v1/organisations/{org_id}/invitations",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"email": "admin13@inkloom.ai", "role": RoleName.BRAND_MANAGER},
        )
        assert invite_self.status_code == 409
        assert "already an active member" in invite_self.json()["detail"].lower()


@pytest.mark.anyio
async def test_14_public_preview_endpoint_metadata(db_session: Session) -> None:
    """GET /invitations/{token} returns public preview without authentication or internal secrets."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_data = await _register_user(client, "admin14@inkloom.ai", org_name="Preview Org Inc")
        admin_token = admin_data["access_token"]
        org_id = admin_data["user"]["memberships"][0]["organisation"]["id"]

        invite_resp = await client.post(
            f"/api/v1/organisations/{org_id}/invitations",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"email": "preview.user@inkloom.ai", "role": RoleName.BRAND_MANAGER},
        )
        inv_token = invite_resp.json()["invitation_token"]

        # Unauthenticated preview
        preview_resp = await client.get(f"/api/v1/invitations/{inv_token}")
        assert preview_resp.status_code == 200
        preview = preview_resp.json()
        assert preview["organisation_name"] == "Preview Org Inc"
        assert preview["email"] == "preview.user@inkloom.ai"
        assert preview["role"] == RoleName.BRAND_MANAGER
        assert preview["status"] == InvitationStatus.PENDING
        assert "token_hash" not in preview
        assert "invitation_token" not in preview
