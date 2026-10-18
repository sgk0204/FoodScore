"""Twelve-factor configuration, validated at start-up (guide §13).

The app refuses to start if a required variable is missing or invalid.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ProviderName = Literal["claude", "gemini", "fake"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # repo-root .env, then backend/.env (later wins), so commands work from either folder.
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    # --- runtime ---
    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"
    release: str = "dev"
    api_prefix: str = "/api/v1"
    # Comma-separated in the environment; NoDecode stops pydantic-settings parsing it as JSON.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    public_base_url: str = "http://localhost:3000"

    # --- data stores (required) ---
    database_url: str
    redis_url: str

    # --- auth ---
    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_ttl_s: int = 15 * 60
    refresh_token_ttl_s: int = 7 * 24 * 3600
    login_max_failures: int = 5
    login_lockout_s: int = 15 * 60
    cookie_secure: bool = True

    # --- quotas & limits (user story 6, edge case 38) ---
    user_daily_scan_quota: int = 20
    guest_daily_scan_quota: int = 3
    global_daily_scan_budget: int = 2000
    rate_limit_auth_per_min: int = 10
    rate_limit_scan_per_min: int = 10
    max_image_bytes: int = 5 * 1024 * 1024
    max_image_px: int = 1600

    # --- object storage ---
    storage_backend: Literal["s3", "local"] = "local"
    storage_local_dir: str = ".data/images"
    s3_bucket: str = "foodscore-images"
    s3_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    image_ttl_s: int = 24 * 3600

    # --- jobs ---
    job_mode: Literal["arq", "inline"] = "arq"
    stuck_processing_s: int = 120
    stuck_queued_s: int = 600
    review_expiry_s: int = 24 * 3600

    # --- AI extraction ---
    llm_provider: ProviderName = "fake"
    llm_fallback_provider: ProviderName | None = None
    prompt_version: str = "v1"
    llm_timeout_s: float = 30.0
    llm_max_attempts: int = 3
    review_confidence_threshold: float = 0.7
    anthropic_api_key: SecretStr | None = None
    claude_model: str = "claude-opus-5-5"
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    claude_server_fallback: bool = True
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    fake_fixture: str = "chocolate_biscuit"

    # --- observability ---
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.1

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, v: str) -> str:
        return normalise_database_url(v)

    @field_validator("jwt_secret")
    @classmethod
    def _strong_secret(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return v

    @model_validator(mode="after")
    def _provider_keys(self) -> Settings:
        for provider in (self.llm_provider, self.llm_fallback_provider):
            if provider == "claude" and self.anthropic_api_key is None:
                raise ValueError("LLM provider 'claude' requires ANTHROPIC_API_KEY")
            if provider == "gemini" and self.gemini_api_key is None:
                raise ValueError("LLM provider 'gemini' requires GEMINI_API_KEY")
        if self.environment == "production" and self.llm_provider == "fake":
            raise ValueError("LLM_PROVIDER=fake is not allowed in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def normalise_database_url(url: str) -> str:
    """Accept the URLs managed providers hand out (Neon, Supabase, Render, Railway).

    They look like ``postgres://u:p@host/db?sslmode=require&channel_binding=require``; the
    asyncpg driver needs ``postgresql+asyncpg://`` and spells TLS as ``ssl=require``.
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix) :]
            break
    if not url.startswith("postgresql+asyncpg://") or "?" not in url:
        return url
    base, query = url.split("?", 1)
    params = []
    for pair in query.split("&"):
        key, _, value = pair.partition("=")
        if key == "sslmode":
            params.append(
                f"ssl={'require' if value in ('require', 'verify-ca', 'verify-full') else value}"
            )
        elif key != "channel_binding":  # libpq-only option; asyncpg rejects it
            params.append(pair)
    return f"{base}?{'&'.join(params)}" if params else base


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
