import pytest
from unittest.mock import AsyncMock, MagicMock
from app.core.audit import create_audit_log


@pytest.mark.asyncio
async def test_create_audit_log_commits_session():
    """create_audit_log must call db.commit() so the row actually persists."""
    mock_db = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()
    # begin_nested must be a regular MagicMock so it returns the async CM directly
    # (not a coroutine), allowing `async with db.begin_nested():` to work
    mock_db.begin_nested = MagicMock(return_value=AsyncMock())

    await create_audit_log(
        mock_db,
        user_id=None,
        user_email="test@example.com",
        tenant_id=None,
        action="user.login",
        resource_type="auth",
    )

    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_create_audit_log_silent_on_db_error():
    """Exceptions must be swallowed — audit failure must never crash the request."""
    mock_db = MagicMock()
    mock_db.begin_nested = MagicMock(side_effect=Exception("DB connection lost"))

    await create_audit_log(
        mock_db,
        user_id=None,
        user_email="test@example.com",
        tenant_id=None,
        action="user.login",
        resource_type="auth",
    )
