"""Alembic environment for the tenant-schema chain.

The exact same revision history is applied to every `tenant_<slug>` schema.
Target schema is passed in programmatically via Config.attributes["schema"]
(see rain.db.migrate / rain.db.provisioning) rather than a CLI -x argument,
since this is always driven from Python, never the bare `alembic` CLI.

This is SQLAlchemy/Alembic's documented "schema per tenant" recipe: models
in rain.db.tenant_models declare no explicit schema, so schema_translate_map
redirects every table (and type) to the target schema at execution time, and
each schema tracks its own alembic_version via version_table_schema.
"""
from __future__ import annotations

import asyncio

import sqlalchemy as sa
from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config

from rain.db.tenant_models import TenantBase

config = context.config
# See migrations/control/env.py for why this deliberately does not call
# logging.config.fileConfig(config.config_file_name).

target_metadata = TenantBase.metadata

schema = config.attributes.get("schema") or context.get_x_argument(as_dictionary=True).get("schema")
if not schema:
    raise RuntimeError(
        "tenant migrations require a target schema: set Config.attributes['schema'] "
        "(programmatic use) or pass -x schema=<name> (CLI use)"
    )


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        version_table_schema=schema,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: sa.Connection) -> None:
    connection.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    connection = connection.execution_options(schema_translate_map={None: schema})

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=schema,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()

    # Explicit, not relying on context.begin_transaction()'s exit alone --
    # see migrations/control/env.py for why (confirmed via a real run that
    # tables silently didn't persist without this).
    connection.commit()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
        await connection.commit()
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
