import uuid
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient, ASGITransport
from jose import jwt
from app.main import app
from app.config import get_settings

settings = get_settings()


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def async_client(client: AsyncClient):
    """Alias for the existing async test client."""
    return client


@pytest.fixture
def valid_webhook_headers() -> dict:
    """Telegram webhook headers with correct secret token."""
    return {
        "X-Telegram-Bot-Api-Secret-Token": settings.telegram_webhook_secret or "test_secret"
    }


@pytest.fixture
def user_token() -> str:
    """Minimal valid JWT access token for a test user (no DB required)."""
    payload = {
        "sub": str(uuid.uuid4()),
        "email": "testuser@ojsdef.com",
        "tenant_id": str(uuid.uuid4()),
        "role": "admin_ojs",
        "jti": str(uuid.uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.fixture
def auth_headers(user_token: str) -> dict:
    """Bearer token headers for an authenticated user."""
    return {"Authorization": f"Bearer {user_token}"}
