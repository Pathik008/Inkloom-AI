"""Unit tests for the Railway judge credential setup utility target validation."""
import pytest
from app.scripts.setup_judge_password import (
    EXPECTED_RAILWAY_ENVIRONMENT,
    EXPECTED_RAILWAY_PROJECT,
    EXPECTED_RAILWAY_SERVICE,
    validate_password_complexity,
    verify_database_target,
)


def test_railway_target_with_valid_metadata_accepted(monkeypatch):
    """Actual Railway hostname + inkloom_db + valid metadata: accepted."""
    monkeypatch.setenv("RAILWAY_PROJECT_NAME", "inkloom-ai-production")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "inkloom-backend")
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "dep-019671e3-test")

    db_info = {
        "driver": "postgresql+psycopg",
        "host": "hearty-intuition.railway.internal",
        "port": "5432",
        "database": "inkloom_db",
        "username": "postgres",
    }
    result = verify_database_target(db_info, require_railway=True)
    assert result["database_host"] == "hearty-intuition.railway.internal"
    assert result["database_name"] == "inkloom_db"
    assert result["project"] == "inkloom-ai-production"
    assert result["environment"] == "production"
    assert result["service"] == "inkloom-backend"
    assert result["deployment_id"] == "dep-019671e3-test"


@pytest.mark.parametrize(
    "local_host",
    [
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "db",
        "inkloom-postgres",
        "inkloom-prod-postgres",
    ],
)
def test_local_docker_hosts_rejected(local_host):
    """Local Docker hosts: rejected."""
    db_info = {
        "driver": "postgresql+psycopg",
        "host": local_host,
        "port": "5432",
        "database": "inkloom_db",
        "username": "postgres",
    }
    with pytest.raises(RuntimeError, match="Database Target Violation: Execution attempted against local host"):
        verify_database_target(db_info, require_railway=False)
    with pytest.raises(RuntimeError, match="Database Target Violation: Execution attempted against local host"):
        verify_database_target(db_info, require_railway=True)


def test_inkloom_local_test_rejected():
    """inkloom_local_test database: rejected."""
    db_info = {
        "driver": "postgresql+psycopg",
        "host": "remote-cluster.internal",
        "port": "5432",
        "database": "inkloom_local_test",
        "username": "postgres",
    }
    with pytest.raises(RuntimeError, match="Database Target Violation: Execution attempted against local test database"):
        verify_database_target(db_info, require_railway=False)
    with pytest.raises(RuntimeError, match="Database Target Violation: Execution attempted against local test database"):
        verify_database_target(db_info, require_railway=True)


def test_railway_hostname_without_required_metadata_rejected(monkeypatch):
    """Railway hostname without required metadata: rejected."""
    for k in [
        "RAILWAY_PROJECT_NAME",
        "RAILWAY_PROJECT_ID",
        "RAILWAY_ENVIRONMENT_NAME",
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_SERVICE_NAME",
        "RAILWAY_SERVICE_ID",
        "RAILWAY_DEPLOYMENT_ID",
    ]:
        monkeypatch.delenv(k, raising=False)

    db_info = {
        "driver": "postgresql+psycopg",
        "host": "hearty-intuition.railway.internal",
        "port": "5432",
        "database": "inkloom_db",
        "username": "postgres",
    }
    with pytest.raises(RuntimeError, match="Missing required Railway metadata"):
        verify_database_target(db_info, require_railway=True)


def test_metadata_without_railway_hostname_rejected(monkeypatch):
    """Metadata without Railway hostname: rejected."""
    monkeypatch.setenv("RAILWAY_PROJECT_NAME", "inkloom-ai-production")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "inkloom-backend")
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "dep-test-123")

    db_info = {
        "driver": "postgresql+psycopg",
        "host": "my-database.internal",
        "port": "5432",
        "database": "inkloom_db",
        "username": "postgres",
    }
    with pytest.raises(RuntimeError, match="does not have the exact required Railway private hostname suffix"):
        verify_database_target(db_info, require_railway=True)


def test_incorrect_project_rejected(monkeypatch):
    """Incorrect project identity: rejected."""
    monkeypatch.setenv("RAILWAY_PROJECT_NAME", "some-other-project")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "inkloom-backend")
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "dep-test-123")

    db_info = {
        "driver": "postgresql+psycopg",
        "host": "hearty-intuition.railway.internal",
        "port": "5432",
        "database": "inkloom_db",
        "username": "postgres",
    }
    with pytest.raises(RuntimeError, match="Railway project mismatch"):
        verify_database_target(db_info, require_railway=True, expected_project="inkloom-ai-production")


def test_incorrect_environment_rejected(monkeypatch):
    """Incorrect environment identity: rejected."""
    monkeypatch.setenv("RAILWAY_PROJECT_NAME", "inkloom-ai-production")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "staging")
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "inkloom-backend")
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "dep-test-123")

    db_info = {
        "driver": "postgresql+psycopg",
        "host": "hearty-intuition.railway.internal",
        "port": "5432",
        "database": "inkloom_db",
        "username": "postgres",
    }
    with pytest.raises(RuntimeError, match="Railway environment mismatch"):
        verify_database_target(db_info, require_railway=True, expected_environment="production")


def test_incorrect_service_rejected(monkeypatch):
    """Incorrect service identity: rejected."""
    monkeypatch.setenv("RAILWAY_PROJECT_NAME", "inkloom-ai-production")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "inkloom-frontend")
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "dep-test-123")

    db_info = {
        "driver": "postgresql+psycopg",
        "host": "hearty-intuition.railway.internal",
        "port": "5432",
        "database": "inkloom_db",
        "username": "postgres",
    }
    with pytest.raises(RuntimeError, match="Railway service mismatch"):
        verify_database_target(db_info, require_railway=True, expected_service="inkloom-backend")


def test_sqlite_fallback_rejected():
    """SQLite driver: rejected."""
    db_info = {
        "driver": "sqlite",
        "host": "",
        "port": "",
        "database": "local.db",
        "username": "",
    }
    with pytest.raises(RuntimeError, match="SQLite fallback is strictly prohibited"):
        verify_database_target(db_info, require_railway=False)


def test_password_complexity_validation():
    """Password complexity rules (min 16 chars, alphanumeric)."""
    with pytest.raises(ValueError, match="at least 16 characters"):
        validate_password_complexity("Short1!")
    with pytest.raises(ValueError, match="at least one letter and one number"):
        validate_password_complexity("abcdefghijklmnop!")
    with pytest.raises(ValueError, match="at least one letter and one number"):
        validate_password_complexity("1234567890123456!")
    # Valid - does not raise
    validate_password_complexity("ValidSecurePassword2026!#")
