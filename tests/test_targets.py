from datetime import datetime, timezone, timedelta
from app.models import OJSTarget
from app.services.targets import compute_plugin_status


def _target(last_seen):
    t = OJSTarget.__new__(OJSTarget)
    t.plugin_last_seen = last_seen
    return t


def test_plugin_connected_within_15_min():
    t = _target(datetime.now(timezone.utc) - timedelta(minutes=5))
    assert compute_plugin_status(t) is True


def test_plugin_disconnected_after_15_min():
    t = _target(datetime.now(timezone.utc) - timedelta(minutes=20))
    assert compute_plugin_status(t) is False


def test_plugin_never_connected():
    t = _target(None)
    assert compute_plugin_status(t) is False
