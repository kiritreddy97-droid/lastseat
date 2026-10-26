import os
import tempfile
from datetime import datetime, timezone

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.clock import utcnow  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.payments import FakeGateway  # noqa: E402
from app.providers import get_gateway, get_notifier, get_otp_sender  # noqa: E402
from app.ratelimit import limiter  # noqa: E402

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)


def _engine():
    """In-memory SQLite by default; set TEST_DATABASE_URL (a throwaway Postgres) to run the suite there."""
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        engine = create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))
        Base.metadata.drop_all(engine)
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db():
    session = sessionmaker(bind=_engine(), autoflush=False)()
    yield session
    session.close()


class RecordingOtpSender:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, destination, code):
        self.sent.append((destination, code))

    @property
    def last_code(self):
        return self.sent[-1][1]


class RecordingNotifier:
    def __init__(self):
        self.bumps: list[dict] = []

    def booking_bumped(self, **kw):
        self.bumps.append(kw)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


@pytest.fixture
def env(monkeypatch):
    """A TestClient wired to an in-memory DB, pinned clock and recording fakes."""
    monkeypatch.setattr(settings, "rate_limit_default", 10_000)
    monkeypatch.setattr(settings, "rate_limit_auth", 10_000)
    monkeypatch.setattr(settings, "admin_api_key", "admin-test-key")
    limiter.reset()
    sessions = sessionmaker(bind=_engine(), autoflush=False)

    def get_test_db():
        s = sessions()
        try:
            yield s
        finally:
            s.close()

    class Env:
        pass

    e = Env()
    e.clock, e.otp, e.notifier = Clock(), RecordingOtpSender(), RecordingNotifier()
    e.gateway = FakeGateway(settings.webhook_secret)
    app.dependency_overrides.update({
        get_db: get_test_db, utcnow: e.clock, get_otp_sender: lambda: e.otp,
        get_gateway: lambda: e.gateway, get_notifier: lambda: e.notifier,
    })
    with TestClient(app) as client:
        e.client = client
        yield e
    app.dependency_overrides.clear()
    limiter.reset()
