import hmac
import hashlib
import time
import json
import pytest


def _make_headers(body: bytes, api_key: str, target_id: str) -> dict:
    ts = str(int(time.time()))
    sig = "sha256=" + hmac.new(api_key.encode(), body, hashlib.sha256).hexdigest()
    return {
        "X-OJSDef-Target-ID": target_id,
        "X-OJSDef-Signature": sig,
        "X-OJSDef-Timestamp": ts,
        "Content-Type": "application/json",
    }


@pytest.mark.asyncio
async def test_callback_missing_headers_returns_401(client):
    resp = await client.post("/plugin/v1/callback", content=b"{}")
    assert resp.status_code == 401
