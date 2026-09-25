"""Alembic environment — driven programmatically by mansik.migrations."""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# make the backend package importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mansik.config import get_settings  # noqa: E402
from mansik.database import get_engine  # noqa: E402
from mansik.models import (  # noqa: E402
    MEMORY_FTS_DDL, MEMORY_FTS_TRIGGERS, Base,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    url = os.environ.get("MANISK_DATABASE_URL") or get_settings().database_url
    # Normalize provider-injected URLs (Render/Heroku use postgres://)
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {"sqlalchemy.url": get_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        is_sqlite = get_url().startswith("sqlite")
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite,  # SQLite ALTER support
        )
        with context.begin_transaction():
            context.run_migrations()
            if is_sqlite and context.config.attributes.get("create_fts"):
                for ddl in [MEMORY_FTS_DDL, *MEMORY_FTS_TRIGGERS]:
                    connection.exec_driver_sql(ddl)


# The FTS index is created in the data migration of the initial revision.


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
