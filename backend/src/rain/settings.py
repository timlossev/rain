"""Bootstrap-only configuration, read once from the environment.

This is deliberately the *only* place RAIN reads process environment
variables. Everything else -- instance name, branding, SMTP, Slack,
tenants, users, asset types, ... -- lives in Postgres and is edited at
runtime through the setup wizard / Admin UI. See rain.core.config_store
(instance-wide) and per-tenant config for the runtime side of things.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    # docker-compose.yml sets this to POSTGRES_URL verbatim when that's
    # provided (an external/managed Postgres -- see .env.example), else
    # builds one pointing at the local "db" container. Either way it lands
    # here as plain DATABASE_URL -- this is the only place that
    # distinction matters. An external POSTGRES_URL typically arrives as
    # a bare "postgresql://" (or "postgres://") DSN, not asyncpg-specific,
    # so the driver segment is normalized below rather than pushing that
    # detail onto whoever sets POSTGRES_URL.
    database_url: str = "postgresql+asyncpg://rain:rain@localhost:5432/rain"
    app_secret_key: str = "insecure-dev-key-change-me"
    rain_domain: str = "localhost"
    uploads_dir: str = "/data/uploads"
    log_level: str = "info"
    syslog_port: int = 5514
    # What the app container's own HTTP server listens on -- Caddy (when
    # present) proxies to this same port, see docker-compose.yml/Caddyfile.
    app_port: int = 8000
    # Never enable on a real deployment: includes full tracebacks (source
    # paths, local variables, SQL text) in 500 responses. Off by default;
    # set DEBUG=true in .env for local development only.
    debug: bool = False

    @field_validator("database_url")
    @classmethod
    def _normalize_driver(cls, value: str) -> str:
        for bare_scheme in ("postgresql://", "postgres://"):
            if value.startswith(bare_scheme):
                return "postgresql+asyncpg://" + value[len(bare_scheme) :]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
