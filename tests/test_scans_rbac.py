import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.services.auth import get_current_user
from app.database import get_db


SAAS_ADMIN = {
    "role": "saas_admin",
    "tenant_id": "00000000-0000-0000-0000-000000000001",
    "sub": "saas-admin-id",
    "email": "admin@ojsdef.com",
}


def make_mock_db():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value = MagicMock(return_value=iter([]))
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalar.return_value = 0
    mock_session.execute.return_value = mock_result

    async def _db():
        yield mock_session

    return _db


@pytest.fixture
def client_saas():
    app.dependency_overrides[get_current_user] = lambda: SAAS_ADMIN
    app.dependency_overrides[get_db] = make_mock_db()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_saas_admin_cannot_start_scan(client_saas):
    resp = client_saas.post("/api/v1/scans", json={
        "target_id": str(uuid.uuid4()),
        "scan_type": "external",
    })
    assert resp.status_code == 403


def test_saas_admin_cannot_cancel_scan(client_saas):
    job_id = str(uuid.uuid4())
    resp = client_saas.post(f"/api/v1/scans/{job_id}/cancel")
    assert resp.status_code == 403


def test_saas_admin_can_list_scans(client_saas):
    resp = client_saas.get("/api/v1/scans")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
