from datetime import datetime, timedelta, timezone
from app.workers.tasks import classify_stale_job

NOW = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)


def _ago(minutes):
    return NOW - timedelta(minutes=minutes)


def test_internal_running_6min_is_callback_timeout():
    assert classify_stale_job(
        status="running", scan_type="internal",
        started_at=_ago(6), created_at=_ago(6), now=NOW,
    ) == "CALLBACK_TIMEOUT"


def test_internal_running_3min_is_none():
    assert classify_stale_job(
        status="running", scan_type="internal",
        started_at=_ago(3), created_at=_ago(3), now=NOW,
    ) is None


def test_external_running_6min_not_callback_timeout():
    assert classify_stale_job(
        status="running", scan_type="external",
        started_at=_ago(6), created_at=_ago(6), now=NOW,
    ) is None


def test_any_queued_31min_is_stale():
    assert classify_stale_job(
        status="queued", scan_type="external",
        started_at=None, created_at=_ago(31), now=NOW,
    ) == "STALE"


def test_completed_is_none():
    assert classify_stale_job(
        status="completed", scan_type="internal",
        started_at=_ago(99), created_at=_ago(99), now=NOW,
    ) is None
