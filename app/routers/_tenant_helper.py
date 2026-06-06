import uuid


def resolve_tenant_filter(current: dict, tenant_id_param: str | None) -> uuid.UUID | None:
    """
    Return tenant UUID to filter by, or None (no filter = semua tenant).
    - Non-saas_admin: selalu filter ke tenant sendiri (dari JWT).
    - saas_admin tanpa param: None (semua tenant).
    - saas_admin dengan param valid: filter ke tenant yang diminta.
    - saas_admin dengan param UUID tidak valid: None (abaikan, return semua).
    """
    if current["role"] == "saas_admin":
        if tenant_id_param:
            try:
                return uuid.UUID(tenant_id_param)
            except ValueError:
                return None
        return None
    return uuid.UUID(current["tenant_id"])
