"""Unit and security tests for C1 JWT secret validation and rejection of insecure keys."""
import os
import secrets
import uuid
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
import jwt

from app.core.config import Settings
from app.core.security import decode_access_token


OLD_INSECURE_DEFAULT = "inkloom-ai-dev-jwt-secret-key-at-least-32-bytes-long-2026"
VALID_STRONG_SECRET = secrets.token_hex(32)


def test_settings_fails_when_secret_key_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup must fail validation when SECRET_KEY is completely unset or empty."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)
    errors = exc_info.value.errors()
    assert any("SECRET_KEY" in str(err) for err in errors)


def test_settings_fails_when_secret_key_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup must fail validation when SECRET_KEY is blank or whitespace."""
    monkeypatch.setenv("SECRET_KEY", "    ")
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)
    assert "SECRET_KEY is required and cannot be empty" in str(exc_info.value)


def test_settings_fails_when_secret_key_is_too_short(monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup must fail validation when SECRET_KEY is under 32 characters."""
    monkeypatch.setenv("SECRET_KEY", "short-secret-123")
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)
    assert "too short" in str(exc_info.value)


def test_settings_fails_for_known_insecure_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup must fail safely when SECRET_KEY matches known repo defaults or placeholders."""
    disallowed = [
        OLD_INSECURE_DEFAULT,
        "dev-only-secret-key-replace-in-env",
        "change-this-in-production-to-a-strong-random-hex-secret-key",
        "replace-with-a-secure-random-secret-key-minimum-32-chars",
        "generate-with-openssl-rand-hex-32-do-not-use-in-production",
    ]
    for bad_key in disallowed:
        monkeypatch.setenv("SECRET_KEY", bad_key)
        with pytest.raises(ValidationError) as exc_info:
            Settings(_env_file=None)
        assert "Insecure SECRET_KEY detected" in str(exc_info.value)


def test_settings_succeeds_with_strong_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Application settings load cleanly when provided with a strong >= 32 char secret."""
    monkeypatch.setenv("SECRET_KEY", VALID_STRONG_SECRET)
    cfg = Settings(_env_file=None)
    assert cfg.SECRET_KEY == VALID_STRONG_SECRET


def test_token_signed_with_old_insecure_default_is_rejected() -> None:
    """Tokens signed with the old public default secret must be rejected by active security decoding."""
    now = int(datetime.now(timezone.utc).timestamp())
    forged_claims = {
        "sub": str(uuid.uuid4()),
        "email": "admin@target-victim.com",
        "iss": "inkloom-ai-api",
        "iat": now,
        "exp": now + 3600,
        "jti": str(uuid.uuid4()),
        "type": "access",
    }
    # Forged using the old known repository string
    forged_token = jwt.encode(forged_claims, OLD_INSECURE_DEFAULT, algorithm="HS256")

    # decode_access_token uses the running settings.SECRET_KEY (which is randomized in conftest)
    with pytest.raises(Exception) as exc_info:
        decode_access_token(forged_token)
    assert "Invalid authentication credentials" in str(exc_info.value) or exc_info.value.status_code == 401


def test_settings_fails_in_production_with_default_postgres_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production startup must fail if POSTGRES_PASSWORD matches development default."""
    monkeypatch.setenv("SECRET_KEY", VALID_STRONG_SECRET)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ALLOW_SQLITE_DEV_FALLBACK", "false")
    monkeypatch.setenv("POSTGRES_PASSWORD", "inkloom_dev_password_change_me")
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)
    assert "Default development POSTGRES_PASSWORD detected" in str(exc_info.value)


def test_settings_fails_in_production_with_sqlite_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production startup must fail if SQLite fallback is enabled."""
    monkeypatch.setenv("SECRET_KEY", VALID_STRONG_SECRET)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("POSTGRES_PASSWORD", "strong_prod_pg_password_987654")
    monkeypatch.setenv("ALLOW_SQLITE_DEV_FALLBACK", "true")
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)
    assert "ALLOW_SQLITE_DEV_FALLBACK must not be enabled in production" in str(exc_info.value)
