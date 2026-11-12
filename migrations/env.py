"""Alembic environment: connects Alembic to the app's settings and models.

- The database URL comes from core.config.settings (the .env file), never from
  alembic.ini.
- target_metadata is SQLModel.metadata after importing every model, so
  `alembic revision --autogenerate` sees all tables.
- Tests can pass an already-open connection in config.attributes["connection"].
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool
from sqlmodel import SQLModel

import models  # noqa: F401  (registers every table in SQLModel.metadata)
from core.config import settings

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def _configure(**kwargs) -> None:
    url = kwargs.get("url") or str(kwargs["connection"].engine.url)
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # SQLite cannot ALTER most things; batch mode rebuilds the table instead.
        render_as_batch=url.startswith("sqlite"),
        **kwargs,
    )


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: print the SQL instead of running it."""
    _configure(
        url=settings.effective_database_url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_with_connection(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run_with_connection(connection)
        return

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = settings.effective_database_url
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        _run_with_connection(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
