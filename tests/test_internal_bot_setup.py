import pytest
from unittest.mock import AsyncMock

from app.workers import internal_bot


class _Target:
    def __init__(self, **kw):
        self.id = "t1"
        self.plugin_api_key_encrypted = "enc"
        self.probe_endpoint = "https://x/probe"
        self.trigger_endpoint = "https://x/trigger"
        self.force_heartbeat = False
        self.pending_scan_job_id = None
        self.connection_mode = "unknown"
        self.__dict__.update(kw)


@pytest.mark.asyncio
async def test_fail_fast_when_probe_fails(monkeypatch):
    monkeypatch.setattr(internal_bot, "decrypt_api_key", lambda _: "k")
    monkeypatch.setattr(internal_bot, "_load_target_and_job",
                        AsyncMock(return_value=(_Target(), True)))
    monkeypatch.setattr(internal_bot, "_probe_for_scan",
                        AsyncMock(return_value=("FAIL", "PROBE_HTTP_500", "HTTP 500")))
    fail = AsyncMock()
    monkeypatch.setattr(internal_bot, "_fail_job", fail)
    monkeypatch.setattr(internal_bot, "write_progress", AsyncMock())
    trig = AsyncMock()
    monkeypatch.setattr(internal_bot, "_trigger_plugin_direct", trig)

    await internal_bot._setup_internal_scan("job1", "t1")

    fail.assert_awaited_once()
    assert fail.await_args.args[1] == "PROBE_HTTP_500"
    trig.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_trigger_on_probe_success(monkeypatch):
    monkeypatch.setattr(internal_bot, "decrypt_api_key", lambda _: "k")
    monkeypatch.setattr(internal_bot, "_load_target_and_job",
                        AsyncMock(return_value=(_Target(), True)))
    monkeypatch.setattr(internal_bot, "_probe_for_scan",
                        AsyncMock(return_value=("DIRECT", None, None)))
    monkeypatch.setattr(internal_bot, "_trigger_plugin_direct",
                        AsyncMock(return_value=True))
    monkeypatch.setattr(internal_bot, "write_progress", AsyncMock())
    monkeypatch.setattr(internal_bot, "_set_connection_mode", AsyncMock())
    fail = AsyncMock()
    monkeypatch.setattr(internal_bot, "_fail_job", fail)

    await internal_bot._setup_internal_scan("job1", "t1")
    fail.assert_not_awaited()


@pytest.mark.asyncio
async def test_force_heartbeat_skips_probe(monkeypatch):
    monkeypatch.setattr(internal_bot, "decrypt_api_key", lambda _: "k")
    monkeypatch.setattr(internal_bot, "_load_target_and_job",
                        AsyncMock(return_value=(_Target(force_heartbeat=True), True)))
    probe = AsyncMock()
    monkeypatch.setattr(internal_bot, "_probe_for_scan", probe)
    monkeypatch.setattr(internal_bot, "write_progress", AsyncMock())
    monkeypatch.setattr(internal_bot, "_queue_heartbeat_job", AsyncMock())

    await internal_bot._setup_internal_scan("job1", "t1")
    probe.assert_not_awaited()
