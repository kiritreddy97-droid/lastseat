from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.db import Base


def test_migrations_match_models_and_round_trip(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/m.db")
    cfg = Config("alembic.ini")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert diff == [], f"models changed without a migration: {diff}"
        command.downgrade(cfg, "base")
