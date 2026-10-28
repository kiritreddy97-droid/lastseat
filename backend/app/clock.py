from datetime import datetime, timezone


def utcnow() -> datetime:
    """Timezone-aware 'now'. Routes depend on this so tests can pin the time."""
    return datetime.now(timezone.utc)
