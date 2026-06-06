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
ADMIN_OJS = {
    "role": "admin_ojs",
    "tenant_id": "00000000-0000-0000-0000-000000000002",
    "sub": "ojs-admin-id",
    "email": "admin@ub.ac.id",
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


@pytest.fixture
def client_ojs():
    app.dependency_overrides[get_current_user] = lambda: ADMIN_OJS
    app.dependency_overrides[get_db] = make_mock_db()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_saas_admin_cannot_create_target(client_saas):
    resp = client_saas.post("/api/v1/targets", json={"name": "Test", "url": "http://test.com"})
    assert resp.status_code == 403


def test_saas_admin_cannot_delete_target(client_saas):
    tid = str(uuid.uuid4())
    resp = client_saas.delete(f"/api/v1/targets/{tid}")
    assert resp.status_code == 403


def test_saas_admin_cannot_verify_target(client_saas):
    tid = str(uuid.uuid4())
    resp = client_saas.post(f"/api/v1/targets/{tid}/verify")
    assert resp.status_code == 403


def test_saas_admin_cannot_regenerate_key(client_saas):
    tid = str(uuid.uuid4())
    resp = client_saas.post(f"/api/v1/targets/{tid}/regenerate-key")
    assert resp.status_code == 403


def test_saas_admin_can_list_targets(client_saas):
    resp = client_saas.get("/api/v1/targets")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_admin_ojs_list_targets_returns_200(client_ojs):
    resp = client_ojs.get("/api/v1/targets")
    assert resp.status_code == 200
