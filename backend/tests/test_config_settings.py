"""
Tests for backend/config.py — Settings class instantiation.

config.py has 0% coverage because nothing in the test suite
imports backend.config directly. This file:

1. Imports the Settings class to verify the env-var reading works
2. Verifies the database_url property composes a correct asyncpg URL
3. Verifies that overriding individual settings via env vars works
4. Locks down the default values that other modules rely on
   (e.g. main.py reads settings.postgres_host, llm_client reads
   settings.llm_cloud_*)

We use a fresh Settings() instance (not the module-level
`settings = Settings()`) so each test can construct one with
custom env vars without polluting the global.
"""
from __future__ import annotations

import pytest

# Note: we import as 'config' (not 'backend.config') to match
# the .coveragerc `source = .` so coverage tracks this module.
# Same import works in the rest of the codebase because the
# backend/ directory is on sys.path via the test runner.
from config import Settings


class TestSettingsDefaults:
    """Lock down default values that other modules depend on."""

    def test_default_postgres_host(self) -> None:
        s = Settings(_env_file=None)
        assert s.postgres_host == "localhost"

    def test_default_postgres_port(self) -> None:
        s = Settings(_env_file=None)
        assert s.postgres_port == 5432

    def test_default_postgres_db(self) -> None:
        s = Settings(_env_file=None)
        assert s.postgres_db == "sandbox_rpg"

    def test_default_backend_port(self) -> None:
        s = Settings(_env_file=None)
        assert s.backend_port == 8000

    def test_default_jwt_expiration(self) -> None:
        s = Settings(_env_file=None)
        # 24 hours is what auth.py expects when no override
        assert s.jwt_expiration_hours == 24

    def test_default_llm_provider(self) -> None:
        s = Settings(_env_file=None)
        assert s.llm_cloud_provider == "minimax"

    def test_default_lancedb_uri(self) -> None:
        s = Settings(_env_file=None)
        assert s.lancedb_uri == "./lancedb_data"

    def test_default_embedding_dim(self) -> None:
        s = Settings(_env_file=None)
        # 768 is what nomic-embed-text-v1.5 returns — vector_store
        # uses this when allocating the in-memory fallback
        assert s.embedding_dim == 768


class TestSettingsDatabaseURL:
    """The database_url property is what db.py uses to build the engine."""

    def test_database_url_default(self) -> None:
        s = Settings(_env_file=None)
        assert s.database_url == (
            "postgresql+asyncpg://rpg_user:dev_password@localhost:5432/sandbox_rpg"
        )

    def test_database_url_with_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POSTGRES_HOST", "db.example.com")
        monkeypatch.setenv("POSTGRES_PORT", "5433")
        monkeypatch.setenv("POSTGRES_DB", "prod_db")
        monkeypatch.setenv("POSTGRES_USER", "alice")
        monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
        s = Settings(_env_file=None)
        assert s.database_url == ("postgresql+asyncpg://alice:secret@db.example.com:5433/prod_db")

    def test_database_url_uses_asyncpg_driver(self) -> None:
        # Always use asyncpg — sync psycopg2 driver is in requirements
        # for alembic migrations, but the app uses asyncpg.
        s = Settings(_env_file=None)
        assert s.database_url.startswith("postgresql+asyncpg://")


class TestSettingsEnvOverrides:
    """Settings must read from env vars so CI can override defaults."""

    def test_jwt_algorithm_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JWT_ALGORITHM", "RS256")
        s = Settings(_env_file=None)
        assert s.jwt_algorithm == "RS256"

    def test_debug_flag_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEBUG", "true")
        s = Settings(_env_file=None)
        assert s.debug is True

    def test_cors_origins_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # CORS_ORIGINS comes through as a JSON-encoded list via pydantic
        # SettingsConfigDict; this test exercises the env-var path.
        monkeypatch.setenv(
            "CORS_ORIGINS", '["https://app.example.com", "https://staging.example.com"]'
        )
        s = Settings(_env_file=None)
        assert "https://app.example.com" in s.cors_origins
        assert "https://staging.example.com" in s.cors_origins

    def test_lancedb_uri_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANCEDB_URI", "/var/lib/lancedb")
        s = Settings(_env_file=None)
        assert s.lancedb_uri == "/var/lib/lancedb"

    def test_enable_api_docs_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_API_DOCS", "false")
        s = Settings(_env_file=None)
        assert s.enable_api_docs is False
