import json
import pytest
from unittest.mock import AsyncMock, patch
import httpx

from app.workers import internal_bot


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_probe_connect_error_returns_unreachable():
    with patch("app.workers.internal_bot.httpx.AsyncClient") as cli:
        cli.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=httpx.ConnectError("refused")
        )
        result, code, _ = await internal_bot._probe_for_scan("https://x/probe", "k")
    assert result == "FAIL"
    assert code == "PLUGIN_UNREACHABLE"


@pytest.mark.asyncio
async def test_probe_500_returns_probe_http_500():
    with patch("app.workers.internal_bot.httpx.AsyncClient") as cli:
        cli.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=_Resp(500)
        )
        result, code, _ = await internal_bot._probe_for_scan("https://x/probe", "k")
    assert (result, code) == ("FAIL", "PROBE_HTTP_500")


@pytest.mark.asyncio
async def test_probe_401_returns_hmac_mismatch():
    with patch("app.workers.internal_bot.httpx.AsyncClient") as cli:
        cli.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=_Resp(401)
        )
        result, code, _ = await internal_bot._probe_for_scan("https://x/probe", "k")
    assert (result, code) == ("FAIL", "HMAC_MISMATCH")


@pytest.mark.asyncio
async def test_probe_challenge_mismatch():
    with patch("app.workers.internal_bot.httpx.AsyncClient") as cli:
        cli.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=_Resp(200, {"challenge": "WRONG"})
        )
        result, code, _ = await internal_bot._probe_for_scan("https://x/probe", "k")
    assert (result, code) == ("FAIL", "CHALLENGE_MISMATCH")


@pytest.mark.asyncio
async def test_probe_success_returns_direct():
    async def _fake_post(url, content=None, headers=None):
        sent = json.loads(content)
        return _Resp(200, {"challenge": sent["challenge"]})
    with patch("app.workers.internal_bot.httpx.AsyncClient") as cli:
        cli.return_value.__aenter__.return_value.post = AsyncMock(side_effect=_fake_post)
        result, code, _ = await internal_bot._probe_for_scan("https://x/probe", "k")
    assert result == "DIRECT"
    assert code is None
