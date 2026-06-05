import pytest
from unittest.mock import AsyncMock, MagicMock
from app.core.audit import create_audit_log


@pytest.mark.asyncio
async def test_create_audit_log_commits_session():
    """create_audit_log must stage the log row and commit it."""
    mock_db = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()

    await create_audit_log(
        mock_db,
        user_id=None,
        user_email="test@example.com",
        tenant_id=None,
        action="user.login",
        resource_type="auth",
    )

    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_create_audit_log_silent_on_db_error():
    """Exceptions must be swallowed — audit failure must never crash the request."""
    mock_db = MagicMock()
    mock_db.add = MagicMock(side_effect=Exception("DB write error"))
    mock_db.commit = AsyncMock()

    await create_audit_log(
        mock_db,
        user_id=None,
        user_email="test@example.com",
        tenant_id=None,
        action="user.login",
        resource_type="auth",
    )

    mock_db.commit.assert_not_called()
