import hmac
import hashlib
import time
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import OJSTarget
from app.services.crypto import decrypt_api_key


async def plugin_auth_middleware(request: Request, call_next):
    if not request.url.path.startswith("/plugin/v1"):
        return await call_next(request)

    target_id = request.headers.get("X-OJSDef-Target-ID", "")
    signature = request.headers.get("X-OJSDef-Signature", "")
    timestamp_str = request.headers.get("X-OJSDef-Timestamp", "")

    # 1. Timestamp replay prevention
    try:
        ts = int(timestamp_str)
        if abs(time.time() - ts) > 300:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    except (ValueError, TypeError):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    # 2. Lookup target + decrypt key
    body = await request.body()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OJSTarget).where(OJSTarget.id == target_id)
        )
        target = result.scalar_one_or_none()
    if not target or not target.plugin_api_key_encrypted:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    api_key = decrypt_api_key(target.plugin_api_key_encrypted).encode()

    # 3. Compute + constant-time compare
    expected = "sha256=" + hmac.new(api_key, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    request.state.plugin_target = target
    request.state.plugin_body = body
    return await call_next(request)
