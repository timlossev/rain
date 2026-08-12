"""Bootstrap-only configuration, read once from the environment.

This is deliberately the *only* place RAIN reads process environment
variables. Everything else -- instance name, branding, SMTP, Slack,
tenants, users, asset types, ... -- lives in Postgres and is edited at
runtime through the setup wizard / Admin UI. See rain.core.config_store
(instance-wide) and per-tenant config for the runtime side of things.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    database_url: str = "postgresql+asyncpg://rain:rain@localhost:5432/rain"
    app_secret_key: str = "insecure-dev-key-change-me"
    rain_domain: str = "localhost"
    uploads_dir: str = "/data/uploads"
    log_level: str = "info"
    syslog_port: int = 5514
    # Never enable on a real deployment: includes full tracebacks (source
    # paths, local variables, SQL text) in 500 responses. Off by default;
    # set DEBUG=true in .env for local development only.
    debug: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
