from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[4]
ENV_FILE = ROOT / ".env"
FRONTEND_DIST = ROOT / "src" / "frontend" / "dist"


class Settings(BaseSettings):
    """Bootstrap config from `/.env` (and real environment variables).

    Non-secret runtime options (modules, retention, intervals after first save)
    live in PostgreSQL `app_settings` and are edited via the Settings UI.
    """

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "production"] = Field(
        default="development",
        alias="LNXADMIN_ENV",
    )

    db_host: str = Field(default="localhost", alias="LNXADMIN_DB_HOST")
    db_port: int = Field(default=5432, alias="LNXADMIN_DB_PORT")
    db_user: str = Field(default="lnxadmin", alias="LNXADMIN_DB_USER")
    db_password: str = Field(default="", alias="LNXADMIN_DB_PASSWORD")
    db_name: str = Field(default="lnxadmin", alias="LNXADMIN_DB_NAME")

    jwt_secret: str = Field(default="change-me", alias="LNXADMIN_JWT_SECRET")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = Field(default=60 * 8, alias="LNXADMIN_JWT_EXPIRE_MINUTES")
    admin_user: str = Field(default="admin", alias="LNXADMIN_ADMIN_USER")
    admin_password: str = Field(default="admin", alias="LNXADMIN_ADMIN_PASSWORD")

    bind_host: str = Field(default="127.0.0.1", alias="LNXADMIN_BIND_HOST")
    bind_port: int = Field(default=8000, alias="LNXADMIN_BIND_PORT")

    cors_origins: str = Field(
        default="http://localhost:5173",
        alias="LNXADMIN_CORS_ORIGINS",
    )
    metrics_interval: float = Field(default=1.5, alias="LNXADMIN_METRICS_INTERVAL")
    history_interval: float = Field(default=15.0, alias="LNXADMIN_HISTORY_INTERVAL")
    retention_days: int = Field(default=30, alias="LNXADMIN_RETENTION_DAYS")

    # When true (default in production), OpenAPI /docs and /redoc are disabled
    disable_docs: bool | None = Field(default=None, alias="LNXADMIN_DISABLE_DOCS")

    @field_validator("app_env", mode="before")
    @classmethod
    def _normalize_env(cls, v: object) -> str:
        s = str(v or "development").strip().lower()
        if s in ("prod", "production"):
            return "production"
        return "development"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def docs_disabled(self) -> bool:
        if self.disable_docs is not None:
            return bool(self.disable_docs)
        return self.is_production

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def frontend_dist(self) -> Path:
        return FRONTEND_DIST

    def security_warnings(self) -> list[str]:
        """Non-fatal warnings for operators; fatal checks use `security_errors`."""
        warnings: list[str] = []
        if self.jwt_secret in {"change-me", "lnxadmin-dev-secret-change-in-production-7t5E"}:
            warnings.append("LNXADMIN_JWT_SECRET is a weak/default value — generate a long random secret")
        if len(self.jwt_secret) < 32:
            warnings.append("LNXADMIN_JWT_SECRET should be at least 32 characters")
        if self.admin_password in {"admin", "password", "changeme", "change-me"}:
            warnings.append("LNXADMIN_ADMIN_PASSWORD is weak — set a strong password")
        if not self.db_password or self.db_password in {"change-me", "password"}:
            warnings.append("LNXADMIN_DB_PASSWORD is empty or weak")
        if self.bind_host in {"0.0.0.0", "::"} and self.is_production:
            warnings.append(
                "LNXADMIN_BIND_HOST exposes all interfaces — prefer 127.0.0.1 behind a reverse proxy/VPN"
            )
        return warnings

    def security_errors(self) -> list[str]:
        """Fatal in production — refuse to start (skipped until setup wizard completes)."""
        from app.core.setup_state import is_setup_complete

        if not self.is_production:
            return []
        if not is_setup_complete():
            # First-run wizard mode — allow boot without strong secrets yet
            return []
        errors: list[str] = []
        if self.jwt_secret in {"change-me", "lnxadmin-dev-secret-change-in-production-7t5E"}:
            errors.append("Refuse to start: set a strong LNXADMIN_JWT_SECRET for production")
        if len(self.jwt_secret) < 32:
            errors.append("Refuse to start: LNXADMIN_JWT_SECRET must be >= 32 characters in production")
        if self.admin_password in {"admin", "password", "changeme", "change-me"}:
            errors.append("Refuse to start: set a strong LNXADMIN_ADMIN_PASSWORD for production")
        if not self.db_password:
            errors.append("Refuse to start: LNXADMIN_DB_PASSWORD is required in production")
        return errors


@lru_cache
def get_settings() -> Settings:
    return Settings()
