import pytest


@pytest.mark.asyncio
async def test_login_invalid_credentials(client):
    resp = await client.post("/api/v1/auth/login", json={
        "email": "nobody@test.com", "password": "wrong"
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
