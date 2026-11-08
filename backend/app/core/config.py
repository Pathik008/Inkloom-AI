from functools import lru_cache
from typing import List
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    APP_NAME: str = "Inkloom AI"
    APP_ENV: str = "development"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"

    # Security & JWT Configuration
    SECRET_KEY: str
    JWT_ISSUER: str = "inkloom-ai-api"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    ALGORITHM: str = "HS256"

    # Rate Limiting Configuration
    RATE_LIMIT_ENABLED: bool = True
    REDIS_URL: str | None = None
    TRUSTED_PROXIES: str = "127.0.0.1,::1"
    RATE_LIMIT_STORAGE_BACKEND: str = "auto"
    RATE_LIMIT_FAIL_CLOSED: bool = False

    AUTH_RATE_LIMIT_MAX_ATTEMPTS: int = 15
    AUTH_RATE_LIMIT_WINDOW_SECONDS: int = 60

    INVITATION_RATE_LIMIT_PREVIEW_MAX: int = 20
    INVITATION_RATE_LIMIT_ACCEPT_MAX: int = 10
    INVITATION_RATE_LIMIT_REGISTER_MAX: int = 5
    INVITATION_RATE_LIMIT_WINDOW_SECONDS: int = 60

    @field_validator("SECRET_KEY", mode="before")
    @classmethod
    def validate_secret_key(cls, value: str | None) -> str:
        if not value or not str(value).strip():
            raise ValueError(
                "SECRET_KEY is required and cannot be empty. "
                "Configure a secure random secret (min 32 characters) via environment variable or .env file."
            )
        cleaned = str(value).strip()
        if len(cleaned) < 32:
            raise ValueError(
                f"SECRET_KEY is too short ({len(cleaned)} characters). "
                "JWT signing requires at least 32 characters for security."
            )
        # Block known insecure development default strings and common placeholders
        disallowed_known_defaults = {
            "inkloom-ai-dev-jwt-secret-key-at-least-32-bytes-long-2026",
            "dev-only-secret-key-replace-in-env",
            "change-this-in-production-to-a-strong-random-hex-secret-key",
            "replace-with-a-secure-random-secret-key-minimum-32-chars",
            "generate-with-openssl-rand-hex-32-do-not-use-in-production",
            "your-secret-key-here-minimum-32-characters-long",
        }
        if cleaned.lower() in {d.lower() for d in disallowed_known_defaults}:
            raise ValueError(
                "Insecure SECRET_KEY detected: matches a known placeholder/default string. "
                "Generate a cryptographically secure random secret (e.g. using 'openssl rand -hex 32')."
            )
        return cleaned

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"

    # PostgreSQL + pgvector (Primary Production Database)
    POSTGRES_USER: str = "inkloom_user"
    POSTGRES_PASSWORD: str = "inkloom_dev_password_change_me"
    POSTGRES_DB: str = "inkloom_db"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: str | None = None

    # Opt-in SQLite Fallback for offline development/unit-testing ONLY.
    # Defaults to False: PostgreSQL is strictly required unless explicitly enabled.
    ALLOW_SQLITE_DEV_FALLBACK: bool = False
    SQLITE_FALLBACK_URL: str = "sqlite:///./inkloom_dev.db"

    @model_validator(mode="after")
    def validate_production_database_security(self) -> "Settings":
        is_production = self.APP_ENV.lower() in ("production", "staging")
        if is_production:
            if self.ALLOW_SQLITE_DEV_FALLBACK:
                raise ValueError("ALLOW_SQLITE_DEV_FALLBACK must not be enabled in production or staging environments.")
            if self.POSTGRES_PASSWORD == "inkloom_dev_password_change_me":
                raise ValueError(
                    "Default development POSTGRES_PASSWORD detected. In production or staging, "
                    "a secure, unique POSTGRES_PASSWORD must be configured."
                )
            if self.DATABASE_URL and "inkloom_dev_password_change_me" in self.DATABASE_URL:
                raise ValueError(
                    "Default development password detected in DATABASE_URL. In production or staging, "
                    "a secure production database connection URL must be configured."
                )
        return self

    # AI & RAG Configuration
    LLM_PROVIDER: str = "openai_compatible"
    LLM_API_KEY: str = ""
    LLM_MODEL_NAME: str = "gpt-4o-mini"
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-large-en-v1.5"
    EMBEDDING_DIMENSION: int = 1024
    RAG_CHUNK_SIZE: int = 512
    RAG_CHUNK_OVERLAP: int = 64
    RAG_TOP_K: int = 8
    RAG_SIMILARITY_THRESHOLD: float = 0.72

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def trusted_proxies_list(self) -> List[str]:
        return [origin.strip() for origin in self.TRUSTED_PROXIES.split(",") if origin.strip()]

    @property
    def sqlalchemy_database_uri(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
