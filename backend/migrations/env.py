from alembic import context
from sqlalchemy import engine_from_config, pool

from app import models  # noqa: F401  (registers tables on Base.metadata)
from app.db import DATABASE_URL, Base

config = context.config
target_metadata = Base.metadata
# Tests/CI hand us an engine through config.attributes; otherwise build one from DATABASE_URL.
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))


def render_item(type_, obj, autogen_context):
    """Keep migrations independent of app code: our UTCDateTime is plain timestamptz in the schema."""
    if type_ == "type" and obj.__class__.__name__ == "UTCDateTime":
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    context.configure(url=DATABASE_URL, target_metadata=target_metadata, literal_binds=True, compare_type=True,
                      render_item=render_item)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        engine = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.",
                                    poolclass=pool.NullPool)
        with engine.connect() as connection:
            _run(connection)
    else:
        _run(connectable)


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                      render_item=render_item, render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
