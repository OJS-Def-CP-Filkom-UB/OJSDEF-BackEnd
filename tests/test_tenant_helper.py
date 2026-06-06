import uuid
import pytest
from app.routers._tenant_helper import resolve_tenant_filter


SAAS_ADMIN = {"role": "saas_admin", "tenant_id": "00000000-0000-0000-0000-000000000001"}
ADMIN_OJS = {"role": "admin_ojs", "tenant_id": "00000000-0000-0000-0000-000000000002"}
VIEWER = {"role": "viewer", "tenant_id": "00000000-0000-0000-0000-000000000003"}


def test_non_saas_returns_own_tenant_admin_ojs():
    result = resolve_tenant_filter(ADMIN_OJS, None)
    assert result == uuid.UUID(ADMIN_OJS["tenant_id"])


def test_non_saas_returns_own_tenant_viewer():
    result = resolve_tenant_filter(VIEWER, None)
    assert result == uuid.UUID(VIEWER["tenant_id"])


def test_non_saas_ignores_tenant_id_param():
    other_tid = str(uuid.uuid4())
    result = resolve_tenant_filter(ADMIN_OJS, other_tid)
    assert result == uuid.UUID(ADMIN_OJS["tenant_id"])


def test_saas_no_param_returns_none():
    result = resolve_tenant_filter(SAAS_ADMIN, None)
    assert result is None


def test_saas_with_valid_param_returns_uuid():
    target_tid = str(uuid.uuid4())
    result = resolve_tenant_filter(SAAS_ADMIN, target_tid)
    assert result == uuid.UUID(target_tid)


def test_saas_with_invalid_uuid_param_returns_none():
    result = resolve_tenant_filter(SAAS_ADMIN, "bukan-uuid-valid")
    assert result is None


def test_saas_with_empty_string_param_returns_none():
    result = resolve_tenant_filter(SAAS_ADMIN, "")
    assert result is None
