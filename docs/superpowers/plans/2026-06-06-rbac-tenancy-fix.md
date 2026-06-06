# RBAC & Multi-Tenancy Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Perbaiki isolasi data antar-tenant dengan mengaktifkan FORCE Row Level Security di PostgreSQL dan menambahkan explicit `tenant_id` filter di semua router FastAPI.

**Architecture:** Dua lapisan perlindungan: (1) database-level — PostgreSQL RLS dengan `FORCE ROW LEVEL SECURITY` dan role `ojsdef_app` non-owner yang wajib kena RLS; (2) application-level — explicit `WHERE tenant_id = X` di setiap query sebagai defense-in-depth. `saas_admin` dapat cross-tenant access via RLS policy exception `app.current_role = 'saas_admin'`. Login endpoint menggunakan owner session (bypass RLS) karena belum ada JWT saat autentikasi.

**Tech Stack:** FastAPI 0.110, SQLAlchemy 2.0 async, Alembic, PostgreSQL 16, Pydantic v2, Python 3.11+

**Constraint:** Tidak ada database lokal — tidak ada tes yang membutuhkan koneksi DB. Verifikasi hanya via syntax check Python (`ast.parse`).

**Spec:** `docs/superpowers/specs/2026-06-06-rbac-tenancy-fix-design.md`

---

## Urutan Eksekusi (Dependency Graph)

```
Wave 1 (PARALLEL): Task 1 + Task 2
         ↓
Wave 2 (SEQUENTIAL): Task 3
         ↓
Wave 3 (PARALLEL): Task 4 + Task 5 + Task 6 + Task 7 + Task 8 + Task 9
         ↓
Wave 4 (SEQUENTIAL): Task 10
```

---

## Wave 1 — Parallel

### Task 1: `config.py` + `.env.example`

**Files:**
- Modify: `app/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Tulis ulang `app/config.py` — tambah field `database_url_app`**

Ganti seluruh isi `app/config.py` dengan:

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    database_url_app: str
    redis_url: str

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    plugin_hmac_secret: str
    plugin_api_key_secret: str  # 32-byte hex for AES-256-GCM

    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str = "ojsdef-reports"
    minio_use_ssl: bool = False

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = "noreply@ojsdef.com"

    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_bot_username: str = ""
    frontend_base_url: str = "http://localhost:3000"
    cve_api_key: str = ""
    sentry_dsn: str = ""

    environment: str = "development"
    allowed_origins: str = "http://localhost:3000"
    app_base_url: str = "http://localhost:8000"

    seed_admin_email: str = "admin@ojsdef.com"
    seed_admin_password: str = ""

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 2: Tambah `DATABASE_URL_APP` ke `.env.example`**

Buka `.env.example`. Temukan baris `DATABASE_URL=...` dan tambahkan baris baru tepat di bawahnya:

```
DATABASE_URL=postgresql+asyncpg://ojsdef:<password>@localhost:5432/ojsdef
DATABASE_URL_APP=postgresql+asyncpg://ojsdef_app:<password>@localhost:5432/ojsdef
```

- [ ] **Step 3: Syntax check**

```bash
python -c "import ast; ast.parse(open('app/config.py').read()); print('OK')"
```
Expected output: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/config.py .env.example
git commit -m "feat(config): add database_url_app field for RLS-enforced runtime connection"
```

---

### Task 2: Migration 005

**Files:**
- Create: `migrations/versions/005_rbac_tenancy_fix.py`

- [ ] **Step 1: Buat file migration baru**

Buat file `migrations/versions/005_rbac_tenancy_fix.py` dengan konten berikut:

```python
"""rbac tenancy fix — FORCE RLS + policy update + ojsdef_app role

Revision ID: 005
Revises: 004
Create Date: 2026-06-06
"""
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

RLS_TABLES = [
    "users", "ojs_targets", "scan_jobs", "scan_findings",
    "scan_schedules", "reports", "notifications", "audit_logs",
]


def upgrade() -> None:
    # Buat role ojsdef_app (non-owner, subject to RLS)
    # Jika DATABASE_URL user bukan superuser, buat role manual dulu di psql:
    #   CREATE ROLE ojsdef_app WITH LOGIN PASSWORD 'ganti_password_aman';
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ojsdef_app'
            ) THEN
                CREATE ROLE ojsdef_app WITH LOGIN PASSWORD 'changeme_set_via_psql';
            END IF;
        END
        $$;
    """)

    op.execute("GRANT USAGE ON SCHEMA public TO ojsdef_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ojsdef_app"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ojsdef_app")

    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                current_setting('app.current_role', true) = 'saas_admin'
                OR tenant_id = current_setting('app.current_tenant_id', true)::uuid
            )
        """)


def downgrade() -> None:
    for table in reversed(RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                tenant_id = current_setting('app.current_tenant_id', true)::uuid
                OR current_setting('app.current_tenant_id', true) = ''
            )
        """)
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")

    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM ojsdef_app")
    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM ojsdef_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM ojsdef_app")
    op.execute("DROP ROLE IF EXISTS ojsdef_app")
```

- [ ] **Step 2: Syntax check**

```bash
python -c "import ast; ast.parse(open('migrations/versions/005_rbac_tenancy_fix.py').read()); print('OK')"
```
Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add migrations/versions/005_rbac_tenancy_fix.py
git commit -m "feat(migration): 005 — FORCE RLS, ojsdef_app role, updated tenant_isolation policy"
```

---

## Wave 2 — Sequential (tunggu Wave 1 selesai)

### Task 3: `database.py`

**Files:**
- Modify: `app/database.py`

- [ ] **Step 1: Tulis ulang `app/database.py` sepenuhnya**

Ganti seluruh isi `app/database.py` dengan:

```python
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker,
)
from fastapi import Request
from app.config import get_settings

settings = get_settings()

# Runtime engine — menggunakan role ojsdef_app (non-owner, kena FORCE RLS)
engine = create_async_engine(
    settings.database_url_app,
    echo=settings.environment == "development",
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession,
    expire_on_commit=False, autoflush=False,
)

# Owner engine — menggunakan role ojsdef (table owner, bypass RLS)
# Dipakai oleh: Celery workers, auth endpoints (login/refresh)
owner_engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
)

OwnerSessionLocal = async_sessionmaker(
    owner_engine, class_=AsyncSession,
    expire_on_commit=False, autoflush=False,
)


@asynccontextmanager
async def make_worker_session():
    """Buat fresh async engine + session untuk Celery task.

    Mencegah RuntimeError 'Future attached to a different loop' yang terjadi
    saat engine module-level dipakai ulang lintas asyncio.run() calls di
    Celery prefork workers. Pakai owner engine — bypass RLS secara legitimate.
    """
    worker_engine = create_async_engine(
        settings.database_url,
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
    )
    SessionLocal = async_sessionmaker(
        worker_engine, class_=AsyncSession,
        expire_on_commit=False, autoflush=False,
    )
    try:
        async with SessionLocal() as session:
            yield session
    finally:
        await worker_engine.dispose()


async def set_tenant_context(session: AsyncSession, tenant_id: str, role: str) -> None:
    """Set PostgreSQL session-level variables untuk RLS tenant isolation.

    Menggunakan SET (bukan SET LOCAL) agar context bertahan setelah commit().
    Caller wajib reset ke '' setelah selesai (lihat get_db finally block).
    """
    import uuid as _uuid
    _uuid.UUID(tenant_id)  # validasi format UUID — raise ValueError jika invalid
    await session.execute(text(f"SET app.current_tenant_id = '{tenant_id}'"))
    await session.execute(text(f"SET app.current_role = '{role}'"))


async def get_db(request: Request):
    """Yield DB session dengan RLS tenant context (session-level SET).

    Context di-reset ke '' di finally block sebelum koneksi dikembalikan ke pool
    agar tidak ada tenant context yang bocor ke request berikutnya.
    """
    async with AsyncSessionLocal() as session:
        tenant_id = getattr(request.state, "tenant_id", None)
        role = getattr(request.state, "role", None)
        if tenant_id and role:
            await set_tenant_context(session, tenant_id, role)
        try:
            yield session
        finally:
            await session.execute(text("SET app.current_tenant_id = ''"))
            await session.execute(text("SET app.current_role = ''"))


async def get_auth_db():
    """Yield owner DB session untuk auth endpoints (login, refresh).

    Login belum punya JWT sehingga tidak ada tenant context yang bisa di-set.
    Owner session bypass RLS agar user lookup by email bisa berjalan.
    """
    async with OwnerSessionLocal() as session:
        yield session
```

- [ ] **Step 2: Syntax check**

```bash
python -c "import ast; ast.parse(open('app/database.py').read()); print('OK')"
```
Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/database.py
git commit -m "feat(database): owner_engine/get_auth_db, SET session-level context, reset on pool return"
```

---

## Wave 3 — Parallel (tunggu Wave 2 selesai)

### Task 4: `routers/auth.py`

**Files:**
- Modify: `app/routers/auth.py`

- [ ] **Step 1: Ganti `get_db` ke `get_auth_db` di endpoint login dan refresh**

Ganti seluruh isi `app/routers/auth.py` dengan:

```python
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError
import redis.asyncio as aioredis
from app.database import get_db, get_auth_db
from app.models import User
from app.schemas.auth import (
    LoginRequest, TokenResponse, RefreshRequest,
    UpdateProfileRequest, ChangePasswordRequest, UserResponse,
)
from app.services.auth import (
    authenticate_user, create_tokens, decode_access_token,
    revoke_refresh_token, revoke_all_refresh_tokens,
    hash_password, verify_password, get_current_user, require_role,
)
from app.config import get_settings
from app.core.audit import create_audit_log

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
settings = get_settings()


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_auth_db),
):
    user = await authenticate_user(db, body.email, body.password)
    if not user:
        await create_audit_log(
            db,
            user_id=None,
            user_email=body.email,
            tenant_id=None,
            action="user.login_failed",
            resource_type="auth",
        )
        raise HTTPException(status_code=401, detail="Credensial tidak valid")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Akun dinonaktifkan")
    tokens = await create_tokens(user)
    await create_audit_log(
        db,
        user_id=str(user.id),
        user_email=user.email,
        tenant_id=str(user.tenant_id),
        action="user.login",
        resource_type="auth",
        resource_id=str(user.id),
    )
    return TokenResponse(**tokens, must_change_password=user.must_change_password)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_auth_db)):
    try:
        payload = decode_access_token(body.refresh_token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Refresh token tidak valid")
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    exists = await r.exists(f"refresh:{payload['sub']}:{payload['jti']}")
    await r.aclose()
    if not exists:
        raise HTTPException(status_code=401, detail="Refresh token tidak valid atau sudah digunakan")
    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User tidak ditemukan")
    await revoke_refresh_token(str(user.id), payload["jti"])
    tokens = await create_tokens(user)
    return TokenResponse(**tokens)


@router.post("/logout", status_code=204)
async def logout(
    body: RefreshRequest | None = Body(default=None),
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body and body.refresh_token:
        try:
            payload = decode_access_token(body.refresh_token)
            await revoke_refresh_token(payload["sub"], payload["jti"])
        except JWTError:
            pass
    await create_audit_log(
        db,
        user_id=current.get("sub"),
        user_email=current.get("email", "unknown"),
        tenant_id=current.get("tenant_id"),
        action="user.logout",
        resource_type="auth",
    )


@router.get("/me", response_model=UserResponse)
async def me(
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == current["sub"]))
    user = result.scalar_one()
    return UserResponse(
        id=str(user.id), email=user.email, full_name=user.full_name,
        role=user.role, must_change_password=user.must_change_password,
        notif_email=user.notif_email, notif_telegram=user.notif_telegram,
        telegram_chat_id=user.telegram_chat_id,
        telegram_username=user.telegram_username,
    )


@router.put("/me", response_model=UserResponse)
async def update_me(
    body: UpdateProfileRequest,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == current["sub"]))
    user = result.scalar_one()
    for field, val in body.model_dump(exclude_none=True).items():
        setattr(user, field, val)
    await db.commit()
    await db.refresh(user)
    return UserResponse(
        id=str(user.id), email=user.email, full_name=user.full_name,
        role=user.role, must_change_password=user.must_change_password,
        notif_email=user.notif_email, notif_telegram=user.notif_telegram,
        telegram_chat_id=user.telegram_chat_id,
        telegram_username=user.telegram_username,
    )


@router.put("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordRequest,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == current["sub"]))
    user = result.scalar_one()
    if not verify_password(body.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Password lama salah")
    user.hashed_password = hash_password(body.new_password)
    user.must_change_password = False
    await db.commit()
    await revoke_all_refresh_tokens(str(user.id))
    await create_audit_log(
        db,
        user_id=str(user.id),
        user_email=user.email,
        tenant_id=current.get("tenant_id"),
        action="user.password_changed",
        resource_type="auth",
        resource_id=str(user.id),
    )


@router.get("/telegram-link")
async def get_telegram_link(
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == current["sub"]))
    user = result.scalar_one()
    if user.telegram_chat_id:
        raise HTTPException(409, "Akun Telegram sudah terhubung")
    if not settings.telegram_bot_username:
        raise HTTPException(503, "Telegram bot belum dikonfigurasi")
    if user.telegram_link_token and user.telegram_link_token_expires:
        if user.telegram_link_token_expires > datetime.now(timezone.utc):
            deeplink = f"https://t.me/{settings.telegram_bot_username}?start={user.telegram_link_token}"
            return {"deeplink": deeplink, "expires_at": user.telegram_link_token_expires.isoformat()}
    link_token = secrets.token_urlsafe(32)
    link_expires = datetime.now(timezone.utc) + timedelta(days=7)
    user.telegram_link_token = link_token
    user.telegram_link_token_expires = link_expires
    await db.commit()
    deeplink = f"https://t.me/{settings.telegram_bot_username}?start={link_token}"
    return {"deeplink": deeplink, "expires_at": link_expires.isoformat()}
```

- [ ] **Step 2: Syntax check**

```bash
python -c "import ast; ast.parse(open('app/routers/auth.py').read()); print('OK')"
```
Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/routers/auth.py
git commit -m "fix(auth): login and refresh use get_auth_db (owner session, bypass RLS)"
```

---

### Task 5: `routers/targets.py`

**Files:**
- Modify: `app/routers/targets.py`

- [ ] **Step 1: Tambah explicit `tenant_id` filter di semua endpoint**

Ganti seluruh isi `app/routers/targets.py` dengan:

```python
import uuid
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import OJSTarget
from app.schemas.targets import (
    CreateTargetRequest, TargetResponse, VerifyResponse,
    PluginGuideResponse, FileMethodInfo, DnsMethodInfo,
)
from app.services.targets import (
    compute_plugin_status, create_target, verify_domain_file,
    verify_domain_dns, regenerate_api_key,
)
from app.services.crypto import decrypt_api_key
from app.services.auth import get_current_user
from app.core.audit import create_audit_log
from app.config import get_settings


def _compute_plugin_status_str(t: OJSTarget) -> str:
    if not t.plugin_last_seen:
        return "never_connected"
    threshold = datetime.now(timezone.utc) - timedelta(minutes=15)
    last_seen = t.plugin_last_seen
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    if last_seen >= threshold:
        return "connected"
    if t.connection_mode == "error":
        return "error"
    return "disconnected"


router = APIRouter(prefix="/api/v1/targets", tags=["targets"])


def _to_response(t: OJSTarget) -> TargetResponse:
    status_str = _compute_plugin_status_str(t)
    return TargetResponse(
        id=str(t.id),
        name=t.name,
        url=t.url,
        is_verified=t.is_verified,
        plugin_connected=(status_str == "connected"),
        plugin_status=status_str,
        connection_mode=t.connection_mode,
        last_heartbeat=t.plugin_last_seen,
        verification_token=t.verification_token,
        ojs_version=t.ojs_version,
        created_at=t.created_at,
    )


@router.get("", response_model=list[TargetResponse])
async def list_targets(
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tid = uuid.UUID(current["tenant_id"])
    result = await db.execute(
        select(OJSTarget).where(OJSTarget.tenant_id == tid)
    )
    return [_to_response(t) for t in result.scalars()]


@router.post("", response_model=TargetResponse, status_code=201)
async def add_target(
    body: CreateTargetRequest,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await create_target(db, uuid.UUID(current["tenant_id"]), body.name, body.url)
    await create_audit_log(
        db, user_id=current.get("sub"), user_email=current.get("email", "unknown"),
        tenant_id=current.get("tenant_id"), action="target.created",
        resource_type="target", resource_id=str(target.id),
        details={"name": target.name, "url": target.url},
    )
    return _to_response(target)


@router.get("/{target_id}", response_model=TargetResponse)
async def get_target(
    target_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OJSTarget).where(
            OJSTarget.id == target_id,
            OJSTarget.tenant_id == uuid.UUID(current["tenant_id"]),
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target tidak ditemukan")
    return _to_response(target)


@router.delete("/{target_id}", status_code=204)
async def delete_target(
    target_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OJSTarget).where(
            OJSTarget.id == target_id,
            OJSTarget.tenant_id == uuid.UUID(current["tenant_id"]),
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target tidak ditemukan")
    target_name, target_url = target.name, target.url
    await db.delete(target)
    await db.commit()
    await create_audit_log(
        db, user_id=current.get("sub"), user_email=current.get("email", "unknown"),
        tenant_id=current.get("tenant_id"), action="target.deleted",
        resource_type="target", resource_id=str(target_id),
        details={"name": target_name, "url": target_url},
    )


@router.post("/{target_id}/verify", response_model=VerifyResponse)
async def verify_target(
    target_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OJSTarget).where(
            OJSTarget.id == target_id,
            OJSTarget.tenant_id == uuid.UUID(current["tenant_id"]),
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target tidak ditemukan")

    token = target.verification_token
    domain = urlparse(target.url).hostname or target.url

    file_info = FileMethodInfo(
        filename=f"ojsdef-verify-{token}.txt",
        content=f"ojsdef-verification={token}",
        path=f"/.well-known/ojsdef-verify-{token}.txt",
    )
    dns_info = DnsMethodInfo(
        record_type="TXT",
        record_name=f"_ojsdef-verify.{domain}",
        record_value=f"ojsdef-verification={token}",
    )

    if await verify_domain_file(target.url, token):
        target.is_verified = True
        await db.commit()
        await create_audit_log(
            db, user_id=current.get("sub"), user_email=current.get("email", "unknown"),
            tenant_id=current.get("tenant_id"), action="target.verified",
            resource_type="target", resource_id=str(target_id), details={"method": "file"},
        )
        return VerifyResponse(
            verified=True, method="file", verification_token=token,
            file_method=file_info, dns_method=dns_info,
        )

    if await verify_domain_dns(domain, token):
        target.is_verified = True
        await db.commit()
        await create_audit_log(
            db, user_id=current.get("sub"), user_email=current.get("email", "unknown"),
            tenant_id=current.get("tenant_id"), action="target.verified",
            resource_type="target", resource_id=str(target_id), details={"method": "dns"},
        )
        return VerifyResponse(
            verified=True, method="dns", verification_token=token,
            file_method=file_info, dns_method=dns_info,
        )

    return VerifyResponse(
        verified=False, method=None, verification_token=token,
        file_method=file_info, dns_method=dns_info,
    )


@router.get("/{target_id}/plugin-guide", response_model=PluginGuideResponse)
async def plugin_guide(
    target_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OJSTarget).where(
            OJSTarget.id == target_id,
            OJSTarget.tenant_id == uuid.UUID(current["tenant_id"]),
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target tidak ditemukan")
    api_key = decrypt_api_key(target.plugin_api_key_encrypted)
    return PluginGuideResponse(
        target_id=str(target.id),
        api_key=api_key,
        backend_url=get_settings().app_base_url,
        endpoint="/plugin/v1/callback",
        instructions="Masukkan ketiga kredensial di bawah ke form Settings plugin OJSDef di OJS.",
    )


@router.post("/{target_id}/regenerate-key")
async def regen_key(
    target_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OJSTarget).where(
            OJSTarget.id == target_id,
            OJSTarget.tenant_id == uuid.UUID(current["tenant_id"]),
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target tidak ditemukan")
    new_key = await regenerate_api_key(db, target)
    await create_audit_log(
        db, user_id=current.get("sub"), user_email=current.get("email", "unknown"),
        tenant_id=current.get("tenant_id"), action="target.api_key_regenerated",
        resource_type="target", resource_id=str(target_id),
    )
    return {"api_key": new_key}
```

- [ ] **Step 2: Syntax check**

```bash
python -c "import ast; ast.parse(open('app/routers/targets.py').read()); print('OK')"
```
Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/routers/targets.py
git commit -m "fix(targets): explicit tenant_id filter on all queries — defense-in-depth"
```

---

### Task 6: `routers/scans.py`

**Files:**
- Modify: `app/routers/scans.py`

- [ ] **Step 1: Tambah explicit `tenant_id` filter + job ownership check sebelum findings**

Ganti seluruh isi `app/routers/scans.py` dengan:

```python
import uuid
import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import redis.asyncio as aioredis
from app.database import get_db
from app.models import OJSTarget, ScanJob, ScanFinding
from app.schemas.scans import StartScanRequest, ScanResponse, FindingResponse, ScanProgress
from app.services.auth import get_current_user, require_role
from app.core.audit import create_audit_log
from app.celery_app import celery_app
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/scans", tags=["scans"])
settings = get_settings()


def _redis():
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def _get_progress(job_id: str) -> dict | None:
    r = _redis()
    raw = await r.get(f"scan_progress:{job_id}")
    await r.aclose()
    return json.loads(raw) if raw else None


def _to_response(job: ScanJob, progress: dict | None = None) -> ScanResponse:
    parsed_progress: ScanProgress | None = None
    if progress:
        try:
            parsed_progress = ScanProgress(**progress)
        except Exception as exc:
            logger.warning("Malformed scan progress for job %s: %s", job.id, exc)
            parsed_progress = None
    return ScanResponse(
        id=str(job.id), target_id=str(job.target_id),
        scan_type=job.scan_type, status=job.status,
        overall_score=job.overall_score, risk_level=job.risk_level,
        critical_count=job.critical_count, high_count=job.high_count,
        medium_count=job.medium_count, low_count=job.low_count,
        diagnostic_code=job.diagnostic_code,
        diagnostic_detail=job.diagnostic_detail,
        progress=parsed_progress, created_at=job.created_at,
    )


@router.post("", response_model=ScanResponse, status_code=201)
async def start_scan(
    body: StartScanRequest,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tid = uuid.UUID(current["tenant_id"])
    result = await db.execute(
        select(OJSTarget).where(
            OJSTarget.id == body.target_id,
            OJSTarget.tenant_id == tid,
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target tidak ditemukan")
    if not target.is_verified:
        raise HTTPException(400, "Target belum diverifikasi")

    job = ScanJob(
        id=uuid.uuid4(),
        tenant_id=tid,
        target_id=target.id,
        scan_type=body.scan_type,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    job_id = str(job.id)
    target_id = str(target.id)
    target_url = target.url

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    await r.setex(f"scan_progress:{job_id}", 3600, json.dumps({
        "scan_type": body.scan_type,
        "external_done": False,
        "internal_done": False,
    }))
    await r.aclose()

    if body.scan_type in ("internal", "full"):
        celery_app.send_task(
            "app.workers.internal_bot.internal_scan_task",
            args=[job_id, target_id], queue="internal_scan",
        )
    if body.scan_type in ("external", "full"):
        celery_app.send_task(
            "app.workers.external_bot.external_scan_task",
            args=[job_id, target_url], queue="external_scan",
        )

    await create_audit_log(
        db, user_id=current.get("sub"), user_email=current.get("email", "unknown"),
        tenant_id=current.get("tenant_id"), action="scan.started",
        resource_type="scan", resource_id=str(job.id),
        details={"scan_type": body.scan_type, "target_id": str(body.target_id)},
    )
    return _to_response(job)


@router.get("", response_model=list[ScanResponse])
async def list_scans(
    target_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tid = uuid.UUID(current["tenant_id"])
    q = (
        select(ScanJob)
        .where(ScanJob.tenant_id == tid)
        .order_by(ScanJob.created_at.desc())
        .limit(limit)
    )
    if target_id:
        q = q.where(ScanJob.target_id == target_id)
    if status:
        q = q.where(ScanJob.status == status)
    result = await db.execute(q)
    return [_to_response(j) for j in result.scalars()]


@router.get("/{job_id}", response_model=ScanResponse)
async def get_scan(
    job_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ScanJob).where(
            ScanJob.id == job_id,
            ScanJob.tenant_id == uuid.UUID(current["tenant_id"]),
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Scan tidak ditemukan")
    progress = await _get_progress(str(job_id))
    return _to_response(job, progress)


@router.get("/{job_id}/findings", response_model=list[FindingResponse])
async def get_findings(
    job_id: uuid.UUID,
    severity: str | None = None,
    category: str | None = None,
    page: int = 1,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verifikasi job milik tenant ini sebelum query findings
    job_result = await db.execute(
        select(ScanJob).where(
            ScanJob.id == job_id,
            ScanJob.tenant_id == uuid.UUID(current["tenant_id"]),
        )
    )
    if not job_result.scalar_one_or_none():
        raise HTTPException(404, "Scan tidak ditemukan")

    q = select(ScanFinding).where(ScanFinding.job_id == job_id)
    if severity:
        q = q.where(ScanFinding.severity == severity)
    if category:
        q = q.where(ScanFinding.category == category)
    q = q.offset((page - 1) * 20).limit(20)
    result = await db.execute(q)
    findings = result.scalars().all()
    return [
        FindingResponse(
            id=str(f.id), finding_type=f.finding_type, category=f.category,
            title=f.title, description=f.description, affected_path=f.affected_path,
            evidence=f.evidence, remediation=f.remediation, severity=f.severity,
            cvss_score=f.cvss_score, cve_id=f.cve_id, owasp_category=f.owasp_category,
            is_false_positive=f.is_false_positive,
        )
        for f in findings
    ]


@router.patch("/{job_id}/findings/{finding_id}", response_model=FindingResponse)
async def mark_false_positive(
    job_id: uuid.UUID,
    finding_id: uuid.UUID,
    current: dict = Depends(require_role("admin_ojs", "saas_admin")),
    db: AsyncSession = Depends(get_db),
):
    # Verifikasi job milik tenant ini
    job_result = await db.execute(
        select(ScanJob).where(
            ScanJob.id == job_id,
            ScanJob.tenant_id == uuid.UUID(current["tenant_id"]),
        )
    )
    if not job_result.scalar_one_or_none():
        raise HTTPException(404, "Scan tidak ditemukan")

    result = await db.execute(
        select(ScanFinding).where(ScanFinding.id == finding_id, ScanFinding.job_id == job_id)
    )
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(404, "Finding tidak ditemukan")
    f.is_false_positive = not f.is_false_positive
    await db.commit()
    await db.refresh(f)
    await create_audit_log(
        db, user_id=current.get("sub"), user_email=current.get("email", "unknown"),
        tenant_id=current.get("tenant_id"), action="finding.false_positive_toggled",
        resource_type="scan", resource_id=str(finding_id),
        details={"is_false_positive": f.is_false_positive, "job_id": str(job_id)},
    )
    return FindingResponse(
        id=str(f.id), finding_type=f.finding_type, category=f.category,
        title=f.title, description=f.description, affected_path=f.affected_path,
        evidence=f.evidence, remediation=f.remediation, severity=f.severity,
        cvss_score=f.cvss_score, cve_id=f.cve_id, owasp_category=f.owasp_category,
        is_false_positive=f.is_false_positive,
    )


@router.post("/{job_id}/cancel", status_code=200)
async def cancel_scan(
    job_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = (await db.execute(
        select(ScanJob).where(
            ScanJob.id == job_id,
            ScanJob.tenant_id == uuid.UUID(current["tenant_id"]),
        )
    )).scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Scan tidak ditemukan")
    if job.status not in ("queued", "running"):
        raise HTTPException(400, "Scan tidak dapat dibatalkan — status: " + job.status)
    previous_status = job.status
    job.status = "cancelled"
    job.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await create_audit_log(
        db, user_id=current.get("sub"), user_email=current.get("email", "unknown"),
        tenant_id=current.get("tenant_id"), action="scan.cancelled",
        resource_type="scan", resource_id=str(job_id),
        details={"previous_status": previous_status},
    )
    return {"status": "cancelled"}
```

- [ ] **Step 2: Syntax check**

```bash
python -c "import ast; ast.parse(open('app/routers/scans.py').read()); print('OK')"
```
Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/routers/scans.py
git commit -m "fix(scans): explicit tenant_id filter + job ownership check before findings"
```

---

### Task 7: `routers/reports.py`

**Files:**
- Modify: `app/routers/reports.py`

- [ ] **Step 1: Tambah explicit `tenant_id` filter di semua endpoint**

Ganti seluruh isi `app/routers/reports.py` dengan:

```python
import io
import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import boto3
from app.database import get_db
from app.models import Report, ScanFinding, ScanJob
from app.schemas.reports import ReportResponse
from app.services.auth import get_current_user
from app.core.audit import create_audit_log
from app.config import get_settings

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])
settings = get_settings()


def _s3():
    return boto3.client(
        "s3",
        endpoint_url=f"{'https' if settings.minio_use_ssl else 'http'}://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )


@router.get("", response_model=list[ReportResponse])
async def list_reports(
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tid = uuid.UUID(current["tenant_id"])
    result = await db.execute(
        select(Report).where(Report.tenant_id == tid).order_by(Report.created_at.desc())
    )
    return [
        ReportResponse(id=str(r.id), job_id=str(r.job_id), format=r.format,
                       file_size_bytes=r.file_size_bytes, created_at=r.created_at)
        for r in result.scalars()
    ]


@router.get("/{report_id}/pdf")
async def download_pdf(
    report_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Report).where(
            Report.id == report_id,
            Report.format == "pdf",
            Report.tenant_id == uuid.UUID(current["tenant_id"]),
        )
    )
    report = result.scalar_one_or_none()
    if not report or not report.storage_path:
        raise HTTPException(404, "Laporan PDF tidak ditemukan")

    obj = _s3().get_object(Bucket=settings.minio_bucket, Key=report.storage_path)
    pdf_data = obj["Body"].read()

    await create_audit_log(
        db, user_id=current.get("sub"), user_email=current.get("email", "unknown"),
        tenant_id=current.get("tenant_id"), action="report.exported",
        resource_type="report", resource_id=str(report_id), details={"format": "pdf"},
    )
    filename = f"ojsdef-report-{str(report_id)[:8]}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_data),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{report_id}/json")
async def download_json(
    report_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Report).where(
            Report.id == report_id,
            Report.tenant_id == uuid.UUID(current["tenant_id"]),
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "Laporan tidak ditemukan")
    job_result = await db.execute(select(ScanJob).where(ScanJob.id == report.job_id))
    job = job_result.scalar_one()
    findings_result = await db.execute(
        select(ScanFinding).where(ScanFinding.job_id == report.job_id)
    )
    findings = findings_result.scalars().all()
    await create_audit_log(
        db, user_id=current.get("sub"), user_email=current.get("email", "unknown"),
        tenant_id=current.get("tenant_id"), action="report.exported",
        resource_type="report", resource_id=str(report_id), details={"format": "json"},
    )
    return {
        "job_id": str(job.id), "scan_type": job.scan_type,
        "status": job.status, "overall_score": job.overall_score, "risk_level": job.risk_level,
        "findings_summary": {
            "total": len(findings),
            "false_positives": sum(1 for f in findings if f.is_false_positive),
        },
        "findings": [
            {
                "title": f.title, "severity": f.severity, "cvss_score": f.cvss_score,
                "description": f.description, "remediation": f.remediation,
                "is_false_positive": f.is_false_positive,
                "false_positive_label": "False Positive" if f.is_false_positive else None,
            }
            for f in findings
        ],
    }
```

- [ ] **Step 2: Syntax check**

```bash
python -c "import ast; ast.parse(open('app/routers/reports.py').read()); print('OK')"
```
Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/routers/reports.py
git commit -m "fix(reports): explicit tenant_id filter on list and download endpoints"
```

---

### Task 8: `routers/dashboard.py`

**Files:**
- Modify: `app/routers/dashboard.py`

- [ ] **Step 1: Gunakan `tenant_id` di semua query dalam `_build_stats`**

Ganti seluruh isi `app/routers/dashboard.py` dengan:

```python
import uuid
import json
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import redis.asyncio as aioredis
from app.database import get_db
from app.models import ScanJob, OJSTarget, ScanFinding
from app.services.auth import get_current_user
from app.config import get_settings

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])
settings = get_settings()


async def _build_stats(db: AsyncSession, tenant_id: str) -> dict:
    tid = uuid.UUID(tenant_id)
    now = datetime.now(timezone.utc)
    month_ago = now - timedelta(days=30)

    targets_count = (await db.execute(
        select(func.count()).select_from(OJSTarget)
        .where(OJSTarget.tenant_id == tid)
    )).scalar()

    scans_result = await db.execute(
        select(ScanJob).where(
            ScanJob.tenant_id == tid,
            ScanJob.created_at >= month_ago,
        )
    )
    scans = scans_result.scalars().all()
    completed = [s for s in scans if s.status == "completed"]

    avg_score = (
        sum(s.overall_score for s in completed if s.overall_score) / len(completed)
        if completed else None
    )

    critical_count = sum(s.critical_count for s in completed)
    high_count = sum(s.high_count for s in completed)

    return {
        "targets": {"total": targets_count},
        "scans": {
            "last_30_days": len(scans),
            "completed": len(completed),
            "failed": sum(1 for s in scans if s.status == "failed"),
        },
        "security_posture": {
            "average_score": round(avg_score, 1) if avg_score else None,
        },
        "findings_summary": {
            "critical": critical_count,
            "high": high_count,
        },
    }


@router.get("/stats")
async def dashboard_stats(
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = current["tenant_id"]
    cache_key = f"dashboard_stats:{tenant_id}"
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    cached = await r.get(cache_key)
    if cached:
        await r.aclose()
        return json.loads(cached)

    stats = await _build_stats(db, tenant_id)
    await r.setex(cache_key, 60, json.dumps(stats))
    await r.aclose()
    return stats
```

- [ ] **Step 2: Syntax check**

```bash
python -c "import ast; ast.parse(open('app/routers/dashboard.py').read()); print('OK')"
```
Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/routers/dashboard.py
git commit -m "fix(dashboard): use tenant_id in all _build_stats queries — was silently ignored"
```

---

### Task 9: `routers/plugin_callback.py`

**Files:**
- Modify: `app/routers/plugin_callback.py`

- [ ] **Step 1: Set tenant context dari `plugin_target.tenant_id` di semua fungsi**

Ganti seluruh isi `app/routers/plugin_callback.py` dengan:

```python
import hmac
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from app.celery_app import celery_app
from app.database import AsyncSessionLocal, set_tenant_context
from app.models import OJSTarget, ScanJob
from app.services.crypto import decrypt_api_key

router = APIRouter(prefix="/plugin/v1", tags=["plugin"])

DEFAULT_MODULES = ["fingerprint", "config", "plugins", "rbac", "file_integrity", "content"]


def _sign_for_plugin(api_key: str, body: bytes) -> dict:
    """Build HMAC headers to authenticate backend→plugin requests.
    Mirrors PHP HmacSigner: sign(timestamp + '.' + body, api_key).
    """
    ts = int(time.time())
    message = str(ts).encode() + b"." + body
    sig = "sha256=" + hmac.new(api_key.encode(), message, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-OJSDef-Signature": sig,
        "X-OJSDef-Timestamp": str(ts),
    }


async def _probe_plugin(
    probe_endpoint: str,
    api_key: str,
    challenge: str,
    target_id: str,
    tenant_id: str,
) -> None:
    """Attempt to probe plugin's /probe endpoint to determine connection mode."""
    body = json.dumps({"challenge": challenge}).encode()
    headers = _sign_for_plugin(api_key, body)
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
            resp = await client.post(probe_endpoint, content=body, headers=headers)
        try:
            echoed = resp.json().get("challenge", "")
        except Exception:
            echoed = ""
        mode = "direct" if (resp.status_code == 200 and echoed == challenge) else "heartbeat"
    except Exception:
        mode = "heartbeat"

    async with AsyncSessionLocal() as session:
        await set_tenant_context(session, tenant_id, "plugin")
        try:
            result = await session.execute(
                select(OJSTarget).where(OJSTarget.id == target_id)
            )
            t = result.scalar_one_or_none()
            if t:
                t.connection_mode = mode
                await session.commit()
        finally:
            await session.execute(text("SET app.current_tenant_id = ''"))
            await session.execute(text("SET app.current_role = ''"))


@router.post("/heartbeat")
async def plugin_heartbeat(request: Request, bg: BackgroundTasks):
    """Receive periodic heartbeat from the OJSDef PHP plugin."""
    target: OJSTarget = request.state.plugin_target
    body: bytes = request.state.plugin_body
    tenant_id = str(target.tenant_id)

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    async with AsyncSessionLocal() as session:
        await set_tenant_context(session, tenant_id, "plugin")
        try:
            result = await session.execute(
                select(OJSTarget).where(OJSTarget.id == target.id)
            )
            t = result.scalar_one()

            t.plugin_last_seen = datetime.now(timezone.utc)
            if payload.get("ojs_version"):
                t.ojs_version = payload["ojs_version"]
            if payload.get("trigger_endpoint"):
                t.trigger_endpoint = payload["trigger_endpoint"]
            if payload.get("probe_endpoint"):
                t.probe_endpoint = payload["probe_endpoint"]
            if payload.get("connection_mode") in ("direct", "heartbeat"):
                t.connection_mode = payload["connection_mode"]

            pending_job_id = t.pending_scan_job_id
            pending_job = None
            if pending_job_id:
                job_result = await session.execute(
                    select(ScanJob).where(
                        ScanJob.id == pending_job_id, ScanJob.status == "running"
                    )
                )
                pending_job = job_result.scalar_one_or_none()
                if not pending_job:
                    t.pending_scan_job_id = None
                    pending_job_id = None

            await session.commit()
        finally:
            await session.execute(text("SET app.current_tenant_id = ''"))
            await session.execute(text("SET app.current_role = ''"))

    challenge = payload.get("reachability_challenge")
    probe_ep = payload.get("probe_endpoint") or target.probe_endpoint
    if challenge and probe_ep and target.plugin_api_key_encrypted:
        api_key = decrypt_api_key(target.plugin_api_key_encrypted)
        bg.add_task(_probe_plugin, probe_ep, api_key, challenge, str(target.id), tenant_id)

    response: dict = {"status": "ok"}
    if pending_job:
        response["scan_requested"] = True
        response["job_id"] = str(pending_job_id)
        response["scan_modules"] = DEFAULT_MODULES

    return response


@router.post("/callback")
async def plugin_callback(request: Request):
    """Receive audit_data from the OJSDef PHP plugin after a scan completes."""
    target: OJSTarget = request.state.plugin_target
    body: bytes = request.state.plugin_body
    tenant_id = str(target.tenant_id)

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    event = payload.get("event")
    if event != "audit_data":
        raise HTTPException(400, "Event tidak dikenal")

    job_id = payload.get("job_id")
    if not job_id:
        raise HTTPException(400, "job_id required")

    async with AsyncSessionLocal() as session:
        await set_tenant_context(session, tenant_id, "plugin")
        try:
            result = await session.execute(
                select(ScanJob).where(ScanJob.id == job_id, ScanJob.status == "running")
            )
            job = result.scalar_one_or_none()
            if not job:
                raise HTTPException(
                    404, "Scan job tidak ditemukan atau tidak dalam status running"
                )

            t_result = await session.execute(
                select(OJSTarget).where(OJSTarget.id == target.id)
            )
            t = t_result.scalar_one()
            if t.pending_scan_job_id == job.id:
                t.pending_scan_job_id = None
            await session.commit()
        finally:
            await session.execute(text("SET app.current_tenant_id = ''"))
            await session.execute(text("SET app.current_role = ''"))

    celery_app.send_task(
        "app.workers.internal_bot.process_plugin_data_task",
        args=[str(job.id), payload.get("data", {})],
        queue="internal_scan",
    )
    return JSONResponse({"status": "received", "queued": True}, status_code=202)


@router.get("/checksums")
async def get_checksums(request: Request, version: str = ""):
    """Return official SHA-256 checksums for core OJS files of a given version."""
    target: OJSTarget = request.state.plugin_target  # noqa: F841 — auth verified by middleware

    if not version:
        raise HTTPException(400, "version parameter required")

    norm = version.replace(".", "_").replace("-", "_")

    CHECKSUMS: dict[str, dict[str, str]] = {
        "3_3_0": {
            "index.php":               "376e1a51db860abaf952b0d4dcce48b7809a58d785648d30d2d38167672b13a2",
            "config.TEMPLATE.inc.php": "b5419455b25b79d303e907c060bbabb6c955fa72465bc04805c238b0226462ce",
        },
        "3_4_0": {
            "index.php":               "95d7797febd50ce9216081f08db80329332632db3383dbf4919748078d40e72f",
            "config.TEMPLATE.inc.php": "8036209f5cd730482367514f3680f503f12ef20625ba9587931445bcab5cb8d0",
        },
    }

    checksums = CHECKSUMS.get(norm)
    if not checksums:
        for key in CHECKSUMS:
            if norm.startswith(key):
                checksums = CHECKSUMS[key]
                break

    if not checksums:
        raise HTTPException(404, f"Checksums untuk versi {version} tidak tersedia")

    return checksums
```

- [ ] **Step 2: Syntax check**

```bash
python -c "import ast; ast.parse(open('app/routers/plugin_callback.py').read()); print('OK')"
```
Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/routers/plugin_callback.py
git commit -m "fix(plugin): set tenant context from plugin_target.tenant_id in all DB sessions"
```

---

## Wave 4 — Sequential (tunggu semua Wave 3 selesai)

### Task 10: Full Syntax Check + Deployment Checklist

**Files:** Semua file yang sudah dimodifikasi

- [ ] **Step 1: Syntax check semua file Python sekaligus**

Dari direktori `OJSDEF-BackEnd`:
```bash
python -c "import ast,os; errors=[]; [errors.append(p) or True for r,d,fs in os.walk('app') for f in fs if f.endswith('.py') for p in [os.path.join(r,f)] if not (lambda: ast.parse(open(p).read()) or True)()]; print('OK' if not errors else errors)"
```
Expected output: `OK`

Jika ada error, output akan menampilkan path file bermasalah. Fix syntax error lalu ulangi.

- [ ] **Step 2: Verifikasi migration 005 terdaftar di Alembic**

```bash
python -c "
from alembic.config import Config
from alembic.script import ScriptDirectory
cfg = Config('alembic.ini')
scripts = ScriptDirectory.from_config(cfg)
revs = [s.revision for s in scripts.walk_revisions()]
print('Revisions:', revs)
assert '005' in revs, 'Migration 005 tidak ditemukan!'
print('OK — migration 005 terdaftar')
"
```
Expected output mengandung `005` dan diakhiri `OK — migration 005 terdaftar`.

- [ ] **Step 3: Final commit**

```bash
git add .
git commit -m "chore: rbac tenancy fix complete — all layers ready for VPS deployment"
```

- [ ] **Step 4: Checklist deployment ke VPS**

Jalankan langkah-langkah berikut secara berurutan di server VPS:

```bash
# 1. Pull kode terbaru
git pull origin main

# 2. Jika role ojsdef_app belum ada ATAU migration user bukan superuser,
#    buat role manual dulu via psql (ganti PASSWORD dengan nilai aman):
psql -U postgres -d ojsdef -c "
  CREATE ROLE ojsdef_app WITH LOGIN PASSWORD 'PASSWORD_AMAN_DI_SINI';
  GRANT USAGE ON SCHEMA public TO ojsdef_app;
  GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ojsdef_app;
  GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ojsdef_app;
"

# 3. Update .env di VPS — tambahkan baris ini:
#    DATABASE_URL_APP=postgresql+asyncpg://ojsdef_app:PASSWORD_AMAN_DI_SINI@localhost:5432/ojsdef
#    (password harus sama dengan yang dipakai di step 2)

# 4. Jalankan migration
source venv/bin/activate
alembic upgrade head

# 5. Restart FastAPI service
systemctl restart ojsdef-api
# atau: supervisorctl restart ojsdef-api
# atau: pm2 restart ojsdef-api

# 6. Verifikasi manual
#    - Login sebagai admin_ojs tenant A → pastikan hanya lihat data tenant A
#    - Login sebagai admin_ojs tenant B → pastikan hanya lihat data tenant B
#    - Login sebagai saas_admin → pastikan masih bisa lihat semua data cross-tenant
```

**Catatan password**: Jika migration sudah jalan dan membuat role dengan password placeholder `changeme_set_via_psql`, ubah passwordnya sebelum restart service:
```bash
psql -U postgres -d ojsdef -c "ALTER ROLE ojsdef_app WITH PASSWORD 'PASSWORD_AMAN_BARU';"
```
Kemudian update `DATABASE_URL_APP` di `.env` dengan password yang sama, lalu restart service.
