"""Tests for Telegram webhook handler — run on VPS with live DB."""
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_webhook_invalid_secret(async_client: AsyncClient):
    """Webhook with wrong secret must return 403."""
    response = await async_client.post(
        "/telegram/webhook",
        json={"update_id": 1, "message": {}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrongsecret"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_webhook_no_message(async_client: AsyncClient, valid_webhook_headers: dict):
    """/telegram/webhook with no message field returns 200 ok."""
    response = await async_client.post(
        "/telegram/webhook",
        json={"update_id": 1},
        headers=valid_webhook_headers,
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_webhook_start_no_token_replies(
    async_client: AsyncClient,
    valid_webhook_headers: dict,
):
    """/start without token replies with guidance message."""
    update = {
        "update_id": 124,
        "message": {
            "message_id": 2,
            "from": {"id": 111, "first_name": "Anon"},
            "chat": {"id": 111, "type": "private"},
            "text": "/start",
        },
    }
    with patch("app.routers.telegram_bot._bot_reply", new_callable=AsyncMock) as mock_reply:
        response = await async_client.post(
            "/telegram/webhook",
            json=update,
            headers=valid_webhook_headers,
        )
    assert response.status_code == 200
    mock_reply.assert_called_once()
    args = mock_reply.call_args[0]
    assert "OJSDef Bot" in args[1]


@pytest.mark.asyncio
async def test_webhook_invalid_token_replies(
    async_client: AsyncClient,
    valid_webhook_headers: dict,
):
    """Invalid/expired token replies with error message."""
    update = {
        "update_id": 125,
        "message": {
            "message_id": 3,
            "from": {"id": 222, "first_name": "Hacker"},
            "chat": {"id": 222, "type": "private"},
            "text": "/start invalidtoken999xyz",
        },
    }
    with patch("app.routers.telegram_bot._bot_reply", new_callable=AsyncMock) as mock_reply:
        response = await async_client.post(
            "/telegram/webhook",
            json=update,
            headers=valid_webhook_headers,
        )
    assert response.status_code == 200
    mock_reply.assert_called_once()
    args = mock_reply.call_args[0]
    assert "tidak valid" in args[1]


@pytest.mark.asyncio
async def test_telegram_link_requires_auth(async_client: AsyncClient):
    """GET /api/v1/auth/telegram-link without auth must return 401."""
    response = await async_client.get("/api/v1/auth/telegram-link")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_telegram_link_returns_deeplink(
    async_client: AsyncClient,
    auth_headers: dict,
):
    """GET /api/v1/auth/telegram-link returns deeplink with t.me URL."""
    response = await async_client.get(
        "/api/v1/auth/telegram-link",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "deeplink" in data
    assert "t.me/" in data["deeplink"]
    assert "expires_at" in data
