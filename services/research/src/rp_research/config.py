from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RP_WORKER_", env_file=".env", extra="ignore")

    environment: Literal["local", "test", "staging", "production"] = "local"
    api_base_url: str = "http://localhost:8000"
    client_id: str = "research-worker"
    client_secret: SecretStr = SecretStr("dev-research-worker-secret")

    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "research-platform"

    # Model gateway (one configured provider + fixture model for tests/demos)
    model_provider: Literal["anthropic", "claude_cli", "fixture"] = "fixture"
    # Local-only: run the installed Claude CLI (`claude -p`) with the operator's own terminal login. Refused outside
    # environment=local; Anthropic does not allow offering claude.ai login in products (use an API key to deploy).
    claude_cli_path: str = "claude"
    claude_cli_model: str | None = None
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    model_timeout_seconds: float = 600.0
    # Unit prices used only for pre-call estimates and ledger snapshots. [VERIFY] at deployment against the
    # provider's current price list; they are configuration, not quotes.
    model_price_input_per_mtok_usd: float = 4.0
    model_price_output_per_mtok_usd: float = 20.0
    fixture_dir: Path = Path(__file__).resolve().parent / "fixtures" / "model"

    # Controlled fetch
    fetch_max_bytes: int = 25 * 1024 * 1024
    fetch_timeout_seconds: float = 20.0
    fetch_max_redirects: int = 5
    fetch_user_agent: str = "ResearchPlatformFetcher/1.0 (+https://example.invalid/fetch-policy)"
    fetch_allow_private_for_tests: bool = False  # never enable outside isolated tests

    # Scholarly providers
    crossref_mailto: str = "ops@example.invalid"
    openaire_base_url: str = "https://api.openaire.eu/graph"
    crossref_base_url: str = "https://api.crossref.org"
    core_api_key: SecretStr | None = None

    # Sandboxes
    docker_binary: str = "docker"
    latex_image: str = "rp-latex-sandbox:1"
    experiment_image: str = "rp-experiment-python:1"


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
