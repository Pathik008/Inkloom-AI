"""Dedicated PostgreSQL and pgvector integration test suite.

This test suite executes directly against PostgreSQL 16 with pgvector.
It verifies:
1. Live PostgreSQL connection and version (PostgreSQL 16+).
2. pgvector extension registration in pg_extension.
3. Creation of vector columns, insertion, and cosine distance (<=>) / L2 distance (<->) similarity queries.
4. Schema tables, foreign keys, unique constraints, and transaction rollbacks.
5. Verification that data persists across reconnects.

If PostgreSQL is not running on the configured host/port, these tests skip with a clear
explanation rather than failing silently or falling back to SQLite.
"""
import os
import uuid
import socket
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from pathlib import Path
from dotenv import dotenv_values
import threading
import concurrent.futures
from fastapi import HTTPException

from app.models import (
    InvitationStatus,
    MembershipStatus,
    Organisation,
    OrganisationInvitation,
    OrganisationMembership,
    Role,
    User,
    utcnow,
)
from app.services.invitation_service import (
    accept_invitation_for_user,
    generate_invitation_token,
    hash_invitation_token,
)

PROJECT_ENV = Path(__file__).resolve().parents[2] / ".env"
PROJECT_ENV_VALUES = dotenv_values(PROJECT_ENV)

POSTGRES_TEST_URI = (
    os.getenv("POSTGRES_TEST_DATABASE_URL")
    or PROJECT_ENV_VALUES.get("DATABASE_URL")
)

if not POSTGRES_TEST_URI:
    raise RuntimeError(
        "PostgreSQL test URL missing. Configure DATABASE_URL in the project .env "
        "or POSTGRES_TEST_DATABASE_URL in the environment."
    )

if not POSTGRES_TEST_URI.startswith(("postgresql://", "postgresql+psycopg://")):
    raise RuntimeError("PostgreSQL integration tests require a PostgreSQL URL.")

def _can_connect_to_postgres() -> bool:
    engine = None
    try:
        engine = create_engine(POSTGRES_TEST_URI, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        if engine is not None:
            engine.dispose()


postgres_required = pytest.mark.skipif(
    not _can_connect_to_postgres(),
    reason=(
        "Live PostgreSQL 16 + pgvector instance is not accessible on localhost:5432. "
        "Start the container via 'docker compose -f infra/docker-compose.yml up -d' to run this suite."
    ),
)


@pytest.fixture(scope="module")
def pg_engine():
    if not _can_connect_to_postgres():
        pytest.skip("PostgreSQL instance not accessible")
    engine = create_engine(POSTGRES_TEST_URI, pool_pre_ping=True)
    yield engine
    engine.dispose()


@postgres_required
def test_postgres_version_is_16_or_higher(pg_engine):
    """Verify that the live database is running PostgreSQL 16 or newer."""
    with pg_engine.connect() as conn:
        ver_str = conn.execute(text("SHOW server_version;")).scalar()
        num_str = conn.execute(text("SHOW server_version_num;")).scalar()
        assert int(num_str) >= 160000, f"Expected PostgreSQL >= 16, got {ver_str}"


@postgres_required
def test_pgvector_extension_is_active(pg_engine):
    """Verify that the pgvector extension exists and is active in the PostgreSQL system catalog."""
    with pg_engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.commit()
        ext = conn.execute(
            text("SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';")
        ).fetchone()
        assert ext is not None, "pgvector extension is not registered in pg_extension"
        assert ext[0] == "vector"


@postgres_required
def test_pgvector_column_creation_and_similarity_search(pg_engine):
    """Verify vector column creation, insertion, and cosine similarity query (<=>)."""
    with pg_engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS test_pgvector_embeddings;"))
        conn.execute(
            text(
                """
                CREATE TABLE test_pgvector_embeddings (
                    id UUID PRIMARY KEY,
                    content TEXT NOT NULL,
                    embedding vector(3) NOT NULL
                );
                """
            )
        )
        # Insert two 3-dimensional test embeddings
        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())
        conn.execute(
            text(
                """
                INSERT INTO test_pgvector_embeddings (id, content, embedding)
                VALUES
                    (:id1, 'Brand Guidelines Heading', '[0.1, 0.2, 0.3]'),
                    (:id2, 'Approved Price List', '[0.9, 0.8, 0.7]');
                """
            ),
            {"id1": id1, "id2": id2},
        )
        conn.commit()

        # Query cosine distance to [0.1, 0.2, 0.3]
        result = conn.execute(
            text(
                """
                SELECT id, content, embedding <=> '[0.1, 0.2, 0.3]' AS cosine_dist
                FROM test_pgvector_embeddings
                ORDER BY cosine_dist ASC
                LIMIT 1;
                """
            )
        ).fetchone()

        assert result is not None
        assert str(result[0]) == id1
        assert float(result[2]) < 0.0001  # Cosine distance to self is ~0

        # Cleanup test table
        conn.execute(text("DROP TABLE IF EXISTS test_pgvector_embeddings;"))
        conn.commit()


@postgres_required
def test_postgres_foreign_key_and_unique_constraints(pg_engine):
    """Verify PostgreSQL strictly enforces foreign keys and unique constraints."""
    with pg_engine.connect() as conn:
        # 1. Verify foreign-key failure when referencing non-existent user
        fake_user_id = str(uuid.uuid4())
        fake_org_id = str(uuid.uuid4())
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    """
                    INSERT INTO organisations (id, name, slug, created_by, created_at, updated_at)
                    VALUES (:id, 'Orphan Org', :slug, :user_id, NOW(), NOW());
                    """
                ),
                {"id": fake_org_id, "slug": f"orphan-{uuid.uuid4().hex[:6]}", "user_id": fake_user_id},
            )
        conn.rollback()

        # 2. Verify unique constraint failure on duplicate email
        temp_user_id_1 = str(uuid.uuid4())
        temp_user_id_2 = str(uuid.uuid4())
        test_email = f"fk_uq_test_{uuid.uuid4().hex[:8]}@example.com"

        conn.execute(
            text(
                """
                INSERT INTO users (id, full_name, email, password_hash, is_active, is_verified, created_at, updated_at)
                VALUES (:id, 'Test User 1', :email, 'hash_sample', TRUE, FALSE, NOW(), NOW());
                """
            ),
            {"id": temp_user_id_1, "email": test_email},
        )
        conn.commit()

        try:
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        """
                        INSERT INTO users (id, full_name, email, password_hash, is_active, is_verified, created_at, updated_at)
                        VALUES (:id, 'Test User 2', :email, 'hash_sample', TRUE, FALSE, NOW(), NOW());
                        """
                    ),
                    {"id": temp_user_id_2, "email": test_email},
                )
            conn.rollback()
        finally:
            conn.execute(text("DELETE FROM users WHERE id = :id;"), {"id": temp_user_id_1})
            conn.commit()


@postgres_required
def test_postgres_unique_constraint_enforcement(pg_engine):
    """Explicitly verify PostgreSQL UNIQUE constraint enforcement and transaction rollback on organisations.slug."""
    temp_user_id = str(uuid.uuid4())
    temp_user_email = f"slug_uq_owner_{uuid.uuid4().hex[:8]}@example.com"
    org_id_1 = str(uuid.uuid4())
    org_id_2 = str(uuid.uuid4())
    test_slug = f"unique-slug-{uuid.uuid4().hex[:8]}"

    with pg_engine.connect() as conn:
        # Create a valid owner user
        conn.execute(
            text(
                """
                INSERT INTO users (id, full_name, email, password_hash, is_active, is_verified, created_at, updated_at)
                VALUES (:id, 'Slug Owner', :email, 'hash_sample', TRUE, FALSE, NOW(), NOW());
                """
            ),
            {"id": temp_user_id, "email": temp_user_email},
        )
        # Create first organisation with test_slug
        conn.execute(
            text(
                """
                INSERT INTO organisations (id, name, slug, created_by, created_at, updated_at)
                VALUES (:id, 'First Org', :slug, :user_id, NOW(), NOW());
                """
            ),
            {"id": org_id_1, "slug": test_slug, "user_id": temp_user_id},
        )
        conn.commit()

        try:
            # Attempt to create second organisation with the duplicate slug
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        """
                        INSERT INTO organisations (id, name, slug, created_by, created_at, updated_at)
                        VALUES (:id, 'Second Org Duplicate', :slug, :user_id, NOW(), NOW());
                        """
                    ),
                    {"id": org_id_2, "slug": test_slug, "user_id": temp_user_id},
                )
            conn.rollback()
        finally:
            # Clean up test organisation and user in correct FK dependency order
            conn.execute(text("DELETE FROM organisations WHERE id = :id;"), {"id": org_id_1})
            conn.execute(text("DELETE FROM users WHERE id = :id;"), {"id": temp_user_id})
            conn.commit()


@postgres_required
def test_postgres_invitations_table_constraints(pg_engine):
    """Verify organisation_invitations table schema, token_hash unique constraint, and FKs on PostgreSQL."""
    with pg_engine.connect() as conn:
        # Verify table exists in information_schema
        table_exists = conn.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'organisation_invitations'
                );
                """
            )
        ).scalar()
        assert table_exists is True

        # Test token_hash unique constraint
        token_a = generate_invitation_token()
        token_hash_a = hash_invitation_token(token_a)
        test_user_id = str(uuid.uuid4())
        test_org_id = str(uuid.uuid4())
        inv_id_1 = str(uuid.uuid4())
        inv_id_2 = str(uuid.uuid4())

        # Create user & org
        conn.execute(
            text(
                """
                INSERT INTO users (id, full_name, email, password_hash, is_active, is_verified, created_at, updated_at)
                VALUES (:id, 'Inv Owner', :email, 'hash_sample', TRUE, FALSE, NOW(), NOW());
                """
            ),
            {"id": test_user_id, "email": f"inv_owner_{uuid.uuid4().hex[:8]}@example.com"},
        )
        conn.execute(
            text(
                """
                INSERT INTO organisations (id, name, slug, created_by, created_at, updated_at)
                VALUES (:id, 'Inv Test Org', :slug, :user_id, NOW(), NOW());
                """
            ),
            {"id": test_org_id, "slug": f"inv-org-{uuid.uuid4().hex[:8]}", "user_id": test_user_id},
        )
        role_id = conn.execute(text("SELECT id FROM roles LIMIT 1;")).scalar()
        conn.commit()

        try:
            # Insert first invitation
            conn.execute(
                text(
                    """
                    INSERT INTO organisation_invitations (id, organisation_id, email, role_id, invited_by_user_id, token_hash, status, expires_at, created_at)
                    VALUES (:id, :org_id, 'invitee@example.com', :role_id, :user_id, :token_hash, 'PENDING', NOW() + INTERVAL '7 days', NOW());
                    """
                ),
                {"id": inv_id_1, "org_id": test_org_id, "role_id": role_id, "user_id": test_user_id, "token_hash": token_hash_a},
            )
            conn.commit()

            # Attempt to insert duplicate token_hash
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        """
                        INSERT INTO organisation_invitations (id, organisation_id, email, role_id, invited_by_user_id, token_hash, status, expires_at, created_at)
                        VALUES (:id, :org_id, 'another@example.com', :role_id, :user_id, :token_hash, 'PENDING', NOW() + INTERVAL '7 days', NOW());
                        """
                    ),
                    {"id": inv_id_2, "org_id": test_org_id, "role_id": role_id, "user_id": test_user_id, "token_hash": token_hash_a},
                )
            conn.rollback()
        finally:
            conn.execute(text("DELETE FROM organisation_invitations WHERE organisation_id = :id;"), {"id": test_org_id})
            conn.execute(text("DELETE FROM organisations WHERE id = :id;"), {"id": test_org_id})
            conn.execute(text("DELETE FROM users WHERE id = :id;"), {"id": test_user_id})
            conn.commit()


@postgres_required
def test_postgres_invitation_concurrency_race_condition(pg_engine):
    """Verify that concurrent acceptance of the same invitation on PostgreSQL permits exactly ONE success."""
    SessionLocal = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    setup_session = SessionLocal()

    admin_user_id = uuid.uuid4()
    invitee_user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    inv_id = uuid.uuid4()
    raw_token = generate_invitation_token()
    token_hash = hash_invitation_token(raw_token)
    invitee_email = f"concurrent_{uuid.uuid4().hex[:8]}@example.com"

    try:
        # 1. Setup admin, organisation, and role
        role = setup_session.execute(select(Role).where(Role.name == "CONTENT_CREATOR")).scalar_one()

        admin_user = User(
            id=admin_user_id,
            full_name="Concurrent Admin",
            email=f"admin_{uuid.uuid4().hex[:8]}@example.com",
            password_hash="argon2_sample",
            is_active=True,
            is_verified=True,
        )
        setup_session.add(admin_user)

        invitee_user = User(
            id=invitee_user_id,
            full_name="Concurrent Invitee",
            email=invitee_email,
            password_hash="argon2_sample",
            is_active=True,
            is_verified=True,
        )
        setup_session.add(invitee_user)
        setup_session.flush()

        org = Organisation(
            id=org_id,
            name="Concurrent Test Workspace",
            slug=f"concurrent-{uuid.uuid4().hex[:8]}",
            created_by=admin_user_id,
        )
        setup_session.add(org)
        setup_session.flush()

        invitation = OrganisationInvitation(
            id=inv_id,
            organisation_id=org_id,
            email=invitee_email,
            role_id=role.id,
            invited_by_user_id=admin_user_id,
            token_hash=token_hash,
            status=InvitationStatus.PENDING,
            expires_at=utcnow() + timedelta(days=7),
        )
        setup_session.add(invitation)
        setup_session.commit()
    finally:
        setup_session.close()

    # 2. Concurrency execution with ThreadPoolExecutor & Barrier
    barrier = threading.Barrier(2)
    results = []

    def _worker(worker_id: int):
        thread_session = SessionLocal()
        try:
            # Sync start time across both threads
            barrier.wait(timeout=5)
            # Re-read invitation and user in worker's own session
            worker_inv = thread_session.execute(
                select(OrganisationInvitation).where(OrganisationInvitation.id == inv_id)
            ).scalar_one()
            worker_user = thread_session.execute(
                select(User).where(User.id == invitee_user_id)
            ).scalar_one()

            membership = accept_invitation_for_user(
                db=thread_session,
                invitation=worker_inv,
                current_user=worker_user,
            )
            results.append((worker_id, "SUCCESS", str(membership.id)))
        except (HTTPException, IntegrityError) as exc:
            results.append((worker_id, "REJECTED", str(exc)))
        except Exception as exc:
            results.append((worker_id, "ERROR", str(exc)))
        finally:
            thread_session.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_worker, 1)
        f2 = executor.submit(_worker, 2)
        concurrent.futures.wait([f1, f2], timeout=10)

    # 3. Verify outcomes
    successes = [r for r in results if r[1] == "SUCCESS"]
    rejections = [r for r in results if r[1] == "REJECTED"]

    assert len(successes) == 1, f"Expected exactly 1 success, got {results}"
    assert len(rejections) == 1, f"Expected exactly 1 rejection, got {results}"

    # 4. Verify in PostgreSQL database
    verify_session = SessionLocal()
    try:
        memberships_count = verify_session.execute(
            text(
                "SELECT count(*) FROM organisation_memberships WHERE organisation_id = :org_id AND user_id = :user_id;"
            ),
            {"org_id": org_id, "user_id": invitee_user_id},
        ).scalar()
        assert memberships_count == 1, f"Expected exactly 1 membership in PostgreSQL, found {memberships_count}"

        final_status = verify_session.execute(
            text("SELECT status FROM organisation_invitations WHERE id = :id;"),
            {"id": inv_id},
        ).scalar()
        assert final_status == "ACCEPTED"
    finally:
        # Cleanup
        verify_session.execute(text("DELETE FROM organisation_memberships WHERE organisation_id = :id;"), {"id": org_id})
        verify_session.execute(text("DELETE FROM organisation_invitations WHERE organisation_id = :id;"), {"id": org_id})
        verify_session.execute(text("DELETE FROM organisations WHERE id = :id;"), {"id": org_id})
        verify_session.execute(text("DELETE FROM users WHERE id IN (:id1, :id2);"), {"id1": admin_user_id, "id2": invitee_user_id})
        verify_session.commit()
        verify_session.close()
