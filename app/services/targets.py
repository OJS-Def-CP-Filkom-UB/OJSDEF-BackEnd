import secrets
import uuid
from datetime import datetime, timezone, timedelta
import httpx
import dns.resolver
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import OJSTarget
from app.services.crypto import encrypt_api_key, decrypt_api_key


def compute_plugin_status(target: OJSTarget) -> bool:
    if not target.plugin_last_seen:
        return False
    threshold = datetime.now(timezone.utc) - timedelta(minutes=15)
    last_seen = target.plugin_last_seen
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return last_seen >= threshold


async def verify_domain_file(url: str, token: str) -> bool:
    verify_url = f"{url.rstrip('/')}/.well-known/ojsdef-verify-{token}.txt"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(verify_url)
            return resp.status_code == 200 and f"ojsdef-verification={token}" in resp.text
    except Exception:
        return False


async def verify_domain_dns(domain: str, token: str) -> bool:
    try:
        answers = dns.resolver.resolve(domain, "TXT")
        for rdata in answers:
            for txt_string in rdata.strings:
                if txt_string.decode() == f"ojsdef-verification={token}":
                    return True
    except Exception:
        pass
    return False


async def create_target(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    name: str,
    url: str,
) -> OJSTarget:
    api_key_plain = secrets.token_hex(32)
    target = OJSTarget(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=name,
        url=url.rstrip("/"),
        verification_token=secrets.token_hex(16),
        plugin_api_key_encrypted=encrypt_api_key(api_key_plain),
    )
    session.add(target)
    await session.commit()
    await session.refresh(target)
    return target


async def regenerate_api_key(session: AsyncSession, target: OJSTarget) -> str:
    new_key = secrets.token_hex(32)
    target.plugin_api_key_encrypted = encrypt_api_key(new_key)
    await session.commit()
    return new_key
