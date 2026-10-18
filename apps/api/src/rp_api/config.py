from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """All runtime configuration. Secrets are SecretStr and never logged."""

    model_config = SettingsConfigDict(env_prefix="RP_", env_file=".env", extra="ignore")

    environment: Literal["local", "test", "staging", "production"] = "local"
    product_name: str = "Research Manuscript Workspace"
    public_base_url: str = "http://localhost:3000"
    api_base_url: str = "http://localhost:8000"

    # Database roles (see docs/DATABASE_SCHEMA.md#roles)
    database_url: SecretStr = SecretStr("postgresql+psycopg://rp_app:rp_app_dev@localhost:5433/research_platform")
    database_url_owner: SecretStr = SecretStr(
        "postgresql+psycopg://rp_owner:rp_owner_dev@localhost:5433/research_platform"
    )
    database_url_system: SecretStr = SecretStr(
        "postgresql+psycopg://rp_system:rp_system_dev@localhost:5433/research_platform"
    )
    database_url_ingest: SecretStr = SecretStr(
        "postgresql+psycopg://rp_ingest:rp_ingest_dev@localhost:5433/research_platform"
    )
    db_pool_size: int = 10

    # Object storage
    object_store_backend: Literal["s3", "local"] = "s3"
    object_store_bucket: str = "research-artifacts"
    object_store_local_path: Path = REPO_ROOT / "var" / "objects"
    s3_endpoint_url: str | None = "http://localhost:8333"
    s3_region: str = "us-east-1"
    s3_access_key: SecretStr = SecretStr("rp_dev_access")
    s3_secret_key: SecretStr = SecretStr("rp_dev_secret_key")
    signed_url_ttl_seconds: int = 300
    temp_object_retention_seconds: int = 24 * 3600
    reservation_ttl_seconds: int = 6 * 3600

    # Identity (built-in OIDC-compatible issuer; external OIDC optional)
    oidc_issuer: str = "http://localhost:8000"
    oidc_audience: str = "research-platform"
    signing_key_path: Path = REPO_ROOT / "var" / "secrets" / "jwt_signing_key.pem"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 14 * 24 * 3600
    external_oidc_issuer: str | None = None
    external_oidc_audience: str | None = None
    external_oidc_jwks_url: str | None = None
    cookie_secure: bool = False
    allow_self_registration: bool = True
    password_min_length: int = 12

    # Service-to-service identity for Temporal workers
    service_clients: dict[str, SecretStr] = Field(
        default_factory=lambda: {"research-worker": SecretStr("dev-research-worker-secret")}
    )
    service_token_ttl_seconds: int = 600

    # Secrets manager (local: AES-GCM envelope with this KEK; production: external manager)
    secrets_backend: Literal["local"] = "local"
    master_key: SecretStr = SecretStr("ZGV2LW9ubHktbWFzdGVyLWtleS0zMi1ieXRlcy0hISE=")

    # Orchestration
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "research-platform"
    temporal_task_queue: str = "research-main"
    temporal_enabled: bool = True
    outbox_poll_interval_seconds: float = 1.0

    # Cost controls
    default_project_budget_cents: int = 5000
    default_currency: str = "USD"
    budget_alert_thresholds: tuple[int, ...] = (50, 80, 100)

    # Rate limiting (per process; Redis-backed coordination is optional at deployment)
    rate_limit_auth_per_minute: int = 20
    rate_limit_default_per_minute: int = 600

    # Fetch / ingestion
    fetch_max_bytes: int = 25 * 1024 * 1024
    fetch_timeout_seconds: float = 20.0

    # Platform operators may curate global reference data (venue registry, provider gates). MFA required.
    platform_operators: list[str] = Field(default_factory=list)
    # Experiment sandbox allowlist: key -> immutable image reference (local image ID or registry digest; infra/images.lock)
    experiment_images: dict[str, str] = Field(default_factory=lambda: {
        "python-sci:1": "sha256:81d4e66c6640c6a0dce663f3094d0578e2d771ab0f186ed4972e9fa09f783cda"})

    otel_exporter_endpoint: str | None = None
    log_level: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.environment in {"staging", "production"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
