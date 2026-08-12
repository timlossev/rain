"""Alembic environment for the `control` schema chain.

Run via rain.db.migrate.upgrade_control(), never invoked directly with the
bare `alembic` CLI in production (there'd be no way to pick a section).
For local development: `alembic -c alembic.ini -n control upgrade head`
from the backend/ directory.
"""
from __future__ import annotations

import asyncio

import sqlalchemy as sa
from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config

from rain.db.control_models import CONTROL_SCHEMA, ControlBase

config = context.config
# Deliberately not calling logging.config.fileConfig(config.config_file_name)
# here (the usual Alembic env.py boilerplate): it applies alembic.ini's
# [logger_root] level = WARN globally, which -- even with
# disable_existing_loggers=False -- silently filters out every INFO-level
# rain.* log call for the rest of the process's life, since they don't set
# their own explicit level and so inherit root's. Confirmed via a real
# run: the very first migration at app/worker startup made this app's
# entire logging output disappear, which is what made every subsequent
# bug look like it was raising with nothing logged anywhere. Alembic's own
# migration-progress messages ("Running upgrade ...") still show up fine
# without this -- they're plain logger.info() calls on "alembic.runtime.
# migration" that propagate through rain.main's own logging.basicConfig()
# same as everything else.

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

    # Explicit, not relying on context.begin_transaction()'s exit alone:
    # a real run against Docker showed Alembic logging every revision as
    # applied ("Running upgrade -> 0001", "0001 -> 0002", ...) while the
    # tables silently never persisted -- every container restart re-ran
    # both migrations from an empty schema again, with the same async
    # connect()+run_sync()+dispose() sequence the official Alembic async
    # template itself uses. Whatever the precise cause, an explicit
    # connection.commit() here (and again in run_migrations_online, after
    # run_sync returns) made it persist reliably; verified directly
    # against the running container (RestartCount stayed 0, and
    # `\dt control.*` in psql showed the tables) rather than assumed.
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
