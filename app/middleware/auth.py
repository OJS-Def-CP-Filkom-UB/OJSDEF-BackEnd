from fastapi import Request
from fastapi.responses import JSONResponse
from jose import JWTError
from app.services.auth import decode_access_token
from app.database import set_tenant_context, AsyncSessionLocal

WHITELIST = {
    "/api/v1/auth/login", "/api/v1/auth/refresh",
    "/health", "/docs", "/openapi.json", "/redoc",
}


async def jwt_middleware(request: Request, call_next):
    path = request.url.path
    if path in WHITELIST or path.startswith("/plugin/v1"):
        return await call_next(request)

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    token = auth.split(" ", 1)[1]
    try:
        payload = decode_access_token(token)
    except JWTError:
        return JSONResponse({"detail": "Invalid token"}, status_code=401)

    request.state.user_id = payload["sub"]
    request.state.tenant_id = payload["tenant_id"]
    request.state.role = payload["role"]

    async with AsyncSessionLocal() as session:
        await set_tenant_context(session, payload["tenant_id"])
        request.state.db_session = session
        response = await call_next(request)
    return response
