"""Application configuration.

All secrets come from environment variables (or a .env file in development).
Secrets are NEVER exposed to the frontend; `public_status()` returns only
non-sensitive operational facts.
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import __version__

# Risk categories used across the permission firewall.
RISK_READ = "read"
RISK_LOW_WRITE = "low_risk_write"
RISK_HIGH_WRITE = "high_risk_write"
RISK_EXTERNAL_COMM = "external_communication"
RISK_FINANCIAL = "financial"
RISK_SECURITY = "security"
RISK_DEVICE = "device_control"

RISK_ORDER = [
    RISK_READ,
    RISK_LOW_WRITE,
    RISK_HIGH_WRITE,
    RISK_EXTERNAL_COMM,
    RISK_FINANCIAL,
    RISK_SECURITY,
    RISK_DEVICE,
]


def _default_secret() -> str:
    """Session secret for ephemeral runs (tests / first boot).

    In production ALWAYS set MANISK_SESSION_SECRET explicitly; a random
    in-memory secret invalidates all sessions on every restart.
    """
    return secrets.token_urlsafe(48)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("MANISK_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        env_prefix="MANISK_",
        extra="ignore",
    )

    # --- Core ---------------------------------------------------------------
    app_name: str = "MANISK"
    version: str = __version__
    environment: str = "production"  # production | development | test
    debug: bool = False
    log_level: str = "INFO"

    # Where the built frontend lives (served as the single-origin UI).
    frontend_dist: Optional[str] = None

    # Security
    session_secret: str = Field(default_factory=_default_secret)
    session_ttl_hours: int = 24 * 7
    confirmation_ttl_minutes: int = 10
    cookie_secure: bool = True
    cookie_samesite: str = "lax"

    # CORS: empty means same-origin only (recommended; frontend is served
    # by the API server itself).
    cors_origins: list[str] = Field(default_factory=list)

    # Rate limiting (per-IP sliding window; swap backend for Redis in prod)
    rate_limit_enabled: bool = True
    rate_limit_auth_per_minute: int = 10
    rate_limit_chat_per_minute: int = 20
    rate_limit_default_per_minute: int = 240

    # --- Database -----------------------------------------------------------
    # sqlite+aiosqlite not used: sync engine, thread-safe sessions.
    database_url: str = "sqlite:///./mansik.db"

    # --- AI provider (OpenAI-compatible: NVIDIA NIM/Nemotron, OpenAI,
    #     Groq, Together, Ollama, vLLM, LM Studio ...) -----------------------
    ai_base_url: Optional[str] = None
    ai_api_key: Optional[str] = None
    ai_model: Optional[str] = None
    ai_fallback_base_url: Optional[str] = None
    ai_fallback_api_key: Optional[str] = None
    ai_fallback_model: Optional[str] = None
    ai_timeout_seconds: float = 120.0
    ai_max_retries: int = 2
    ai_max_tokens: int = 1024
    ai_temperature: float = 0.4

    # --- Tools --------------------------------------------------------------
    tavily_api_key: Optional[str] = None  # web.search provider (optional)
    allow_duckduckgo_search: bool = True  # no-key fallback search
    http_fetch_enabled: bool = True
    http_fetch_max_bytes: int = 2_000_000

    # File storage
    storage_dir: str = "./storage/files"
    max_upload_bytes: int = 20 * 1024 * 1024  # 20 MB
    allowed_upload_extensions: list[str] = Field(
        default_factory=lambda: [
            ".txt", ".md", ".json", ".csv", ".pdf", ".png", ".jpg", ".jpeg",
            ".webp", ".gif", ".yaml", ".yml", ".xml", ".html", ".log",
        ]
    )

    # Email (optional; requires real SMTP credentials)
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_starttls: bool = True

    # Workers
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 30

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_dev(self) -> bool:
        return self.environment == "development"

    def public_status(self) -> dict:
        """Non-secret operational status (safe for the frontend)."""
        from .ai.providers import ProviderRegistry

        registry = ProviderRegistry.from_settings(self)
        primary = registry.primary
        return {
            "app_name": self.app_name,
            "version": self.version,
            "environment": self.environment,
            "ai_provider": {
                "configured": primary is not None and primary.is_configured,
                "provider_kind": primary.kind if primary else None,
                "model": primary.model if primary else None,
                # NOTE: keys are intentionally never included.
            },
            "web_search": {
                "tavily": bool(self.tavily_api_key),
                "duckduckgo": self.allow_duckduckgo_search,
            },
            "email": {
                "configured": bool(self.smtp_host and self.smtp_from),
            },
            "scheduler_enabled": self.scheduler_enabled,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
