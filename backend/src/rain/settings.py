"""Bootstrap-only configuration, read once from the environment.

This is deliberately the *only* place RAIN reads process environment
variables. Everything else -- instance name, branding, SMTP, Slack,
tenants, users, asset types, ... -- lives in Postgres and is edited at
runtime through the setup wizard / Admin UI. See rain.core.config_store
(instance-wide) and per-tenant config for the runtime side of things.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_postgres_driver(value: str) -> str:
    """A bare "postgresql://"/"postgres://" DSN (what an external
    POSTGRES_URL typically arrives as) becomes asyncpg-specific. A plain
    function, not a method, so both database_url's own field_validator
    and Settings._use_postgres_url_fallback (which needs to apply the
    same normalization to a value pulled from a *different* field, after
    field-level validation has already run) can call it directly --
    calling a @field_validator-wrapped classmethod outside pydantic's own
    validation pipeline isn't a safe/documented thing to rely on."""
    for bare_scheme in ("postgresql://", "postgres://"):
        if value.startswith(bare_scheme):
            return "postgresql+asyncpg://" + value[len(bare_scheme) :]
    return value


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
    # Same field .env/.env.example carries (see the comment above and
    # postgres_url's own docstring below) -- present here too so a bare
    # `docker run --env-file .env` (no docker-compose.yml in the loop to
    # do the ${POSTGRES_URL:-...} substitution into DATABASE_URL itself)
    # still resolves the database correctly, not just the Compose path.
    # _use_postgres_url_fallback below is what actually applies it.
    postgres_url: str = ""
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

    # Document repository storage (rain.modules.documents.storage) --
    # local disk (uploads_dir above) unless s3_bucket is set, in which
    # case every document body reads/writes go to that bucket instead
    # and the local uploads volume no longer needs to persist them. The
    # branding assets (the logo, and the client portal's optional
    # background image) are still served from local disk either way
    # (see storage.py's docstring), but also back themselves up to this
    # same bucket when it's set (rain.web.uploads) so they survive the
    # local copy going missing; without s3_bucket, that backup goes to
    # Postgres instead. The CSV/JSON import stash stays on local disk unconditionally
    # -- it's transient, gone by design once the import finishes, nothing
    # worth backing up. s3_endpoint_url is what makes this work against
    # any S3-compatible service (MinIO, etc.), not just real AWS S3 --
    # leave blank for AWS, set it for anything self-hosted.
    # s3_access_key_id/s3_secret_access_key are optional: leave both
    # blank to fall back to boto3's normal
    # credential chain (an instance/task IAM role, ~/.aws/credentials,
    # AWS_* env vars) instead of a static pair in .env.
    s3_bucket: str = ""
    s3_region: str = ""
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    # Folds the worker's syslog listener + rule engine + notifications +
    # calendar sweep + LDAP sync into this same process/container instead
    # of a separate `worker` service -- see rain.cli.run_web and
    # docker-compose.yml's "minimal mode" comment. Off by default (the
    # two-container app+worker split is still the normal recommended
    # shape); on for a genuinely single-container deployment.
    embed_worker: bool = False

    # Reserves the `vector` Postgres extension/type for a future semantic-
    # search source (rain.db.tenant_models.Ticket/Document.embedding,
    # EMBEDDING_DIM) -- unused today (rain.modules.search is full-text
    # only), so safe to turn off outright. On by default to not change
    # behavior for an existing deployment that already migrated with it;
    # turn off for a Postgres that can't grant CREATE EXTENSION at all
    # (confirmed live: asyncpg.exceptions.InsufficientPrivilegeError
    # against a standard, non-superuser RDS role) or doesn't ship the
    # extension in the first place (e.g. standard RDS in AWS GovCloud).
    # Read at migration time by control migration 0006 and tenant
    # migration 0023, and at import time by the two embedding columns
    # below -- flipping it after either has already run against a given
    # schema has no retroactive effect (same as every other env-at-
    # deploy-time setting here), only on migrations/schemas from that
    # point on.
    enable_pgvector: bool = True

    @field_validator("database_url")
    @classmethod
    def _normalize_driver(cls, value: str) -> str:
        return _normalize_postgres_driver(value)

    @field_validator("s3_endpoint_url")
    @classmethod
    def _normalize_s3_endpoint(cls, value: str) -> str:
        # storage.py passes this straight through to boto3.client("s3",
        # endpoint_url=...) with no validation of its own -- botocore
        # requires a full URL, scheme included, and raises a bare
        # `ValueError: Invalid endpoint: <value>` for anything else.
        # Confirmed live against a real GovCloud FIPS endpoint entered as
        # just "s3-fips.dualstack.us-gov-west-1.amazonaws.com" (exactly
        # the shape someone copies out of AWS's own docs, which don't
        # include a scheme). Only prepended when no scheme is present at
        # all -- an explicit "http://" (e.g. a local MinIO without TLS)
        # is left alone rather than forced onto https.
        if value and "://" not in value:
            return f"https://{value}"
        return value

    @model_validator(mode="after")
    def _use_postgres_url_fallback(self) -> "Settings":
        # Mirrors docker-compose.yml's DATABASE_URL: ${POSTGRES_URL:-...}
        # at the app level instead of relying solely on Compose to do
        # that substitution -- a bare `docker run --env-file .env` (the
        # single-container path, no docker-compose.yml involved at all)
        # otherwise had no way to make POSTGRES_URL take effect, forcing
        # DATABASE_URL to be set redundantly alongside it even though
        # .env already carries POSTGRES_URL for exactly this purpose.
        # "database_url" not in model_fields_set means DATABASE_URL
        # itself was never explicitly set (only the class default
        # applied) -- an explicit DATABASE_URL (the normal Compose path,
        # which always sets it) still wins outright, same precedence the
        # Compose-level substitution already has.
        if "database_url" not in self.model_fields_set and self.postgres_url:
            self.database_url = _normalize_postgres_driver(self.postgres_url)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
