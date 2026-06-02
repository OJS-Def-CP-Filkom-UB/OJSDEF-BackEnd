import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_make_worker_session_yields_session_and_disposes_engine():
    """make_worker_session harus yield session dan panggil engine.dispose() setelah blok selesai."""
    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()

    mock_session = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_session_local = MagicMock(return_value=mock_cm)

    with patch("app.database.create_async_engine", return_value=mock_engine), \
         patch("app.database.async_sessionmaker", return_value=mock_session_local):
        from app.database import make_worker_session
        async with make_worker_session() as s:
            assert s is mock_session

    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_make_worker_session_disposes_on_exception():
    """engine.dispose() harus tetap dipanggil meskipun blok raise exception."""
    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()

    mock_session = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_session_local = MagicMock(return_value=mock_cm)

    with patch("app.database.create_async_engine", return_value=mock_engine), \
         patch("app.database.async_sessionmaker", return_value=mock_session_local):
        from app.database import make_worker_session
        with pytest.raises(RuntimeError):
            async with make_worker_session() as s:
                raise RuntimeError("simulasi error di dalam task")

    mock_engine.dispose.assert_called_once()
