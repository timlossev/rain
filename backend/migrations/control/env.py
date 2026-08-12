"""Alembic environment for the `control` schema chain.

Run via rain.db.migrate.upgrade_control(), never invoked directly with the
bare `alembic` CLI in production (there'd be no way to pick a section).
For local development: `alembic -c alembic.ini -n control upgrade head`
from the backend/ directory.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config

from rain.db.control_models import CONTROL_SCHEMA, ControlBase

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = ControlBase.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        version_table_schema=CONTROL_SCHEMA,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: sa.Connection) -> None:
    # The control schema itself must exist before Alembic can create its
    # version table inside it.
    connection.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{CONTROL_SCHEMA}"'))

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=CONTROL_SCHEMA,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
