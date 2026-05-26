# OJSDef Backend MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Subagent type:** `voltagent-core-dev:fullstack-developer`

**Goal:** Build the complete OJSDef FastAPI + Celery backend — Docker Compose infra through scanner modules, scoring engine, notification delivery, and seeded saas_admin account.

**Architecture:** Layered Router → Service → Model. Routers handle HTTP + Pydantic validation, Services contain business logic + Celery dispatch, Models are pure data access. Scanner modules are side-effect-free Python functions called by Celery workers. PostgreSQL 16 RLS enforces multi-tenancy via `SET app.current_tenant_id`.

**Tech Stack:** FastAPI 0.110, SQLAlchemy 2.0 async + asyncpg, Alembic, Pydantic v2, Celery 5 + Redis 7, PostgreSQL 16 RLS, MinIO, WeasyPrint + Jinja2, python-jose HS256, passlib[bcrypt], httpx, aiosmtplib, dnspython, nvdlib

---

## Execution Model: 2-Subagent Strategy

```
Tasks 0–4  [Sequential] ──► SYNC POINT
                                 │
              ┌──────────────────┴──────────────────┐
              ▼                                     ▼
     Subagent A [API Layer]              Subagent B [Scanners]
     A1: Crypto + Auth service           B1: FindingResult dataclass
     A2: Auth router + JWT middleware    B2: Internal: config + plugins
     A3: Targets service + router        B3: Internal: rbac + file_integrity
     A4: Plugin callback                 B4: Internal: content + db_security
     A5: Scans router + Celery stubs    B5: External: finger + ssl + headers
     A6: Reports + Dashboard + Admin    B6: External: vuln + opendir + cve
              │                                     │
              └──────────────────┬──────────────────┘
                                 ▼
                       Tasks 9–13 [Sequential]
                       9:  Wire workers (internal_bot, external_bot)
                       10: Scoring worker + PDF generation
                       11: Notification worker
                       12: Seed + integration smoke test
```

**Sync contract:** `app/scanners/models.py` (Task B1) defines `FindingResult` — workers import it. B1 must complete before Tasks 9–10 start. Subagent A and B can otherwise work fully independently after the sync point.

---

## File Map

```
OJSDEF-BackEnd/
├── Dockerfile
├── docker-compose.yml
├── nginx/nginx.conf
├── .env.example / .gitignore / alembic.ini
├── requirements.txt
├── scripts/seed.py
├── tests/conftest.py, test_auth.py, test_targets.py,
│         test_plugin_callback.py, test_scoring.py
│         test_scanners/test_internal_config.py
│         test_scanners/test_external_headers.py
└── app/
    ├── main.py / config.py / database.py / celery_app.py
    ├── middleware/auth.py, plugin_auth.py
    ├── models/ (base, tenant, user, ojs_target, scan_job,
    │            scan_finding, scan_schedule, report,
    │            notification, audit_log)
    ├── schemas/ (auth, targets, scans, reports, admin)
    ├── routers/ (auth, targets, scans, reports,
    │            dashboard, admin, plugin_callback)
    ├── services/ (crypto, auth, targets, report)
    ├── workers/ (internal_bot, external_bot, scoring, notify)
    ├── scanners/models.py
    │   scanners/internal/ (config_scanner, plugin_auditor,
    │                       rbac_auditor, file_integrity,
    │                       content_detector, db_security)
    │   scanners/external/ (fingerprinter, ssl_analyzer,
    │                       header_checker, vuln_prober,
    │                       open_dir_detector, cve_matcher)
    ├── migrations/env.py, versions/001_initial.py
    └── templates/report.html, report_style.css, email_critical.html
```

---

## Task 0: Project Files + Requirements

**Files:** `requirements.txt`, `.gitignore`, `.env.example`

- [ ] **Step 1: Replace requirements.txt**

```text
# Core
fastapi==0.110.0
uvicorn[standard]==0.29.0
pydantic==2.6.4
pydantic-settings==2.2.1

# Database
sqlalchemy==2.0.29
asyncpg==0.29.0
alembic==1.13.1
redis==5.0.3

# Auth
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
bcrypt==4.0.1

# Task Queue
celery==5.3.6
flower==2.0.1

# Scanner
httpx==0.27.0
beautifulsoup4==4.12.3
lxml==5.1.0
pyopenssl==24.1.0
cryptography==42.0.5
dnspython==2.6.1
nvdlib==0.7.6

# PDF & Storage
weasyprint==62.3
jinja2==3.1.3
boto3==1.34.0

# Notifications
aiosmtplib==3.0.1

# Utils
python-multipart==0.0.9
python-dotenv==1.0.1
sentry-sdk[fastapi]==1.44.0

# Testing
pytest==8.1.1
pytest-asyncio==0.23.5
```

- [ ] **Step 2: Create .gitignore**

```gitignore
venv/
__pycache__/
*.pyc
.env
*.egg-info/
.pytest_cache/
```

- [ ] **Step 3: Create .env.example**

```env
DATABASE_URL=postgresql+asyncpg://ojsdef:ojsdef_pass@postgres:5432/ojsdef
REDIS_URL=redis://redis:6379/0
JWT_SECRET=change-me-32-chars-minimum-secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=30
PLUGIN_HMAC_SECRET=change-me-plugin-hmac-secret-32chars
PLUGIN_API_KEY_SECRET=0123456789abcdef0123456789abcdef
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=ojsdef_minio
MINIO_SECRET_KEY=ojsdef_minio_secret
MINIO_BUCKET=ojsdef-reports
MINIO_USE_SSL=false
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=noreply@ojsdef.com
SMTP_PASS=smtp_password
SMTP_FROM=noreply@ojsdef.com
TELEGRAM_BOT_TOKEN=
CVE_API_KEY=
SENTRY_DSN=
ENVIRONMENT=development
ALLOWED_ORIGINS=http://localhost:3000
SEED_ADMIN_EMAIL=admin@ojsdef.com
SEED_ADMIN_PASSWORD=Admin@OJSDef2026!
FLOWER_BASIC_AUTH=flower:flower_pass
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt .gitignore .env.example
git commit -m "chore: project files + requirements (add dnspython, pytest, bcrypt)"
```

---

## Task 1: Docker Compose Infrastructure

**Files:** `Dockerfile`, `docker-compose.yml`, `nginx/nginx.conf`

- [ ] **Step 1: Write Dockerfile**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y \
    gcc libpq-dev libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 libffi-dev shared-mime-info \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
```

- [ ] **Step 2: Write docker-compose.yml**

```yaml
version: "3.9"

x-app: &app
  build: .
  env_file: .env
  depends_on:
    postgres:
      condition: service_healthy
    redis:
      condition: service_healthy

services:
  fastapi:
    <<: *app
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    expose: ["8000"]

  worker-internal:
    <<: *app
    command: celery -A app.celery_app worker -Q internal_scan --concurrency=4 --loglevel=info

  worker-external:
    <<: *app
    command: celery -A app.celery_app worker -Q external_scan --concurrency=2 --loglevel=info

  worker-scoring:
    <<: *app
    command: celery -A app.celery_app worker -Q scoring --concurrency=2 --loglevel=info

  worker-notify:
    <<: *app
    command: celery -A app.celery_app worker -Q notifications --concurrency=4 --loglevel=info

  flower:
    <<: *app
    command: celery -A app.celery_app flower --port=5555 --basic_auth=${FLOWER_BASIC_AUTH}
    expose: ["5555"]

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: ojsdef
      POSTGRES_USER: ojsdef
      POSTGRES_PASSWORD: ojsdef_pass
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ojsdef"]
      interval: 5s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY}
    volumes:
      - minio_data:/data
    expose: ["9000", "9001"]

  nginx:
    image: nginx:1.25-alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - fastapi
      - flower

volumes:
  postgres_data:
  minio_data:
```

- [ ] **Step 3: Write nginx/nginx.conf**

```nginx
events { worker_connections 1024; }
http {
    upstream fastapi { server fastapi:8000; }
    upstream flower  { server flower:5555;  }
    server {
        listen 80;
        client_max_body_size 10m;
        location /flower/ {
            proxy_pass http://flower/;
            proxy_set_header Host $host;
        }
        location / {
            proxy_pass http://fastapi;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }
    }
}
```

- [ ] **Step 4: Verify syntax**

```bash
docker compose config --quiet && echo "compose OK"
```

Expected: `compose OK`

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml nginx/
git commit -m "feat: docker compose infra (postgres, redis, minio, nginx, flower)"
```

---

## Task 2: App Skeleton

**Files:** `app/__init__.py`, `app/config.py`, `app/database.py`, `app/celery_app.py`, `app/main.py`

- [ ] **Step 1: Create all __init__.py files**

```bash
mkdir -p app/middleware app/models app/schemas app/routers app/services \
         app/workers app/scanners/internal app/scanners/external \
         app/templates migrations/versions scripts tests/test_scanners
touch app/__init__.py app/middleware/__init__.py app/models/__init__.py \
      app/schemas/__init__.py app/routers/__init__.py app/services/__init__.py \
      app/workers/__init__.py app/scanners/__init__.py \
      app/scanners/internal/__init__.py app/scanners/external/__init__.py \
      scripts/__init__.py tests/__init__.py tests/test_scanners/__init__.py
```

- [ ] **Step 2: Write app/config.py**

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
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
    cve_api_key: str = ""
    sentry_dsn: str = ""

    environment: str = "development"
    allowed_origins: str = "http://localhost:3000"

    seed_admin_email: str = "admin@ojsdef.com"
    seed_admin_password: str = ""

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 3: Write app/database.py**

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker,
)
from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.environment == "development",
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession,
    expire_on_commit=False, autoflush=False,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    await session.execute(
        text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'")
    )
```

- [ ] **Step 4: Write app/celery_app.py**

```python
from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery("ojsdef", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Jakarta",
    enable_utc=True,
    task_always_eager=False,
    task_routes={
        "app.workers.internal_bot.*": {"queue": "internal_scan"},
        "app.workers.external_bot.*": {"queue": "external_scan"},
        "app.workers.scoring.*":      {"queue": "scoring"},
        "app.workers.notify.*":       {"queue": "notifications"},
    },
)
```

- [ ] **Step 5: Write app/main.py**

```python
from contextlib import asynccontextmanager
import redis.asyncio as aioredis
import boto3
from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.database import engine
from sqlalchemy import text

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    r = aioredis.from_url(settings.redis_url)
    await r.ping()
    await r.aclose()
    s3 = boto3.client(
        "s3",
        endpoint_url=f"{'https' if settings.minio_use_ssl else 'http'}://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )
    try:
        s3.head_bucket(Bucket=settings.minio_bucket)
    except ClientError:
        s3.create_bucket(Bucket=settings.minio_bucket)
    yield


app = FastAPI(
    title="OJSDef API", version="1.0.0", lifespan=lifespan,
    docs_url="/docs" if settings.environment == "development" else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)
if settings.sentry_dsn:
    import sentry_sdk
    sentry_sdk.init(dsn=settings.sentry_dsn)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
```

- [ ] **Step 6: Verify**

```bash
python -c "from app.config import get_settings; from app.celery_app import celery_app; print('skeleton OK')"
```

Expected: `skeleton OK`

- [ ] **Step 7: Commit**

```bash
git add app/
git commit -m "feat: app skeleton (config, database, celery, main, lifespan)"
```

---

## Task 3: Database Models

**Files:** All files under `app/models/`

- [ ] **Step 1: Write app/models/base.py**

```python
import uuid
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 2: Write app/models/tenant.py**

```python
import uuid
from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from app.models.base import Base, TimestampMixin


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
```

- [ ] **Step 3: Write app/models/user.py**

```python
import uuid
from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    notif_email: Mapped[bool] = mapped_column(Boolean, default=True)
    notif_telegram: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
```

- [ ] **Step 4: Write app/models/ojs_target.py**

```python
import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from app.models.base import Base, TimestampMixin


class OJSTarget(Base, TimestampMixin):
    __tablename__ = "ojs_targets"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plugin_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    plugin_last_seen: Mapped[datetime | None] = mapped_column(nullable=True)
    ojs_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
```

- [ ] **Step 5: Write app/models/scan_job.py**

```python
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from app.models.base import Base, TimestampMixin


class ScanJob(Base, TimestampMixin):
    __tablename__ = "scan_jobs"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ojs_targets.id"), nullable=False)
    scan_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    critical_count: Mapped[int] = mapped_column(Integer, default=0)
    high_count: Mapped[int] = mapped_column(Integer, default=0)
    medium_count: Mapped[int] = mapped_column(Integer, default=0)
    low_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
```

- [ ] **Step 6: Write app/models/scan_finding.py**

```python
import uuid
from sqlalchemy import String, Float, Boolean, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from app.models.base import Base, TimestampMixin


class ScanFinding(Base, TimestampMixin):
    __tablename__ = "scan_findings"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("scan_jobs.id"), nullable=False)
    finding_type: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    affected_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    remediation: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    cvss_score: Mapped[float] = mapped_column(Float, nullable=False)
    cve_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    owasp_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_false_positive: Mapped[bool] = mapped_column(Boolean, default=False)
```

- [ ] **Step 7: Write remaining models (scan_schedule, report, notification, audit_log)**

`app/models/scan_schedule.py`:
```python
import uuid
from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from app.models.base import Base, TimestampMixin

class ScanSchedule(Base, TimestampMixin):
    __tablename__ = "scan_schedules"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ojs_targets.id"), nullable=False)
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False)
    scan_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
```

`app/models/report.py`:
```python
import uuid
from sqlalchemy import String, Text, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from app.models.base import Base, TimestampMixin

class Report(Base, TimestampMixin):
    __tablename__ = "reports"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("scan_jobs.id"), nullable=False)
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

`app/models/notification.py`:
```python
import uuid
from sqlalchemy import String, Boolean, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from app.models.base import Base, TimestampMixin

class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("scan_jobs.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    notif_type: Mapped[str] = mapped_column(String(30), nullable=False)
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
```

`app/models/audit_log.py`:
```python
import uuid
from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from app.models.base import Base, TimestampMixin

class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

- [ ] **Step 8: Write app/models/__init__.py**

```python
from app.models.base import Base
from app.models.tenant import Tenant
from app.models.user import User
from app.models.ojs_target import OJSTarget
from app.models.scan_job import ScanJob
from app.models.scan_finding import ScanFinding
from app.models.scan_schedule import ScanSchedule
from app.models.report import Report
from app.models.notification import Notification
from app.models.audit_log import AuditLog

__all__ = [
    "Base", "Tenant", "User", "OJSTarget", "ScanJob",
    "ScanFinding", "ScanSchedule", "Report", "Notification", "AuditLog",
]
```

- [ ] **Step 9: Verify**

```bash
python -c "from app.models import Base, User, ScanJob, ScanFinding; print('models OK')"
```

Expected: `models OK`

- [ ] **Step 10: Commit**

```bash
git add app/models/
git commit -m "feat: SQLAlchemy 2.0 models (9 tables, TimestampMixin)"
```

---

## Task 4: Alembic Migration + Seed (SYNC POINT)

**Files:** `alembic.ini`, `migrations/env.py`, `migrations/versions/001_initial.py`, `scripts/seed.py`

- [ ] **Step 1: Initialize Alembic**

```bash
alembic init migrations
```

- [ ] **Step 2: Write migrations/env.py** (replace generated file)

```python
import asyncio
from logging.config import fileConfig
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context
from app.config import get_settings
from app.models import Base

config = context.config
fileConfig(config.config_file_name)
target_metadata = Base.metadata
settings = get_settings()


def run_migrations_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        await connection.run_sync(
            lambda conn: context.configure(conn=conn, target_metadata=target_metadata) or
                         context.begin_transaction() or context.run_migrations()
        )
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Step 3: Write migrations/versions/001_initial.py**

```python
"""initial schema

Revision ID: 001
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

RLS_TABLES = [
    "users", "ojs_targets", "scan_jobs", "scan_findings",
    "scan_schedules", "reports", "notifications", "audit_logs",
]

_TS = dict(type_=sa.DateTime(timezone=True), server_default=sa.func.now())


def _uuid_col(name="id", **kw):
    return sa.Column(name, UUID(as_uuid=True), **kw)


def upgrade() -> None:
    op.create_table("tenants",
        _uuid_col(primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), unique=True, nullable=False),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )
    op.create_table("users",
        _uuid_col(primary_key=True),
        _uuid_col("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("must_change_password", sa.Boolean, default=False),
        sa.Column("notif_email", sa.Boolean, default=True),
        sa.Column("notif_telegram", sa.Boolean, default=False),
        sa.Column("telegram_chat_id", sa.String(50)),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )
    op.create_table("ojs_targets",
        _uuid_col(primary_key=True),
        _uuid_col("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("is_verified", sa.Boolean, default=False),
        sa.Column("verification_token", sa.String(64)),
        sa.Column("plugin_api_key_encrypted", sa.Text),
        sa.Column("plugin_last_seen", sa.DateTime(timezone=True)),
        sa.Column("ojs_version", sa.String(20)),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )
    op.create_table("scan_jobs",
        _uuid_col(primary_key=True),
        _uuid_col("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
        _uuid_col("target_id", sa.ForeignKey("ojs_targets.id"), nullable=False),
        sa.Column("scan_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), default="queued"),
        sa.Column("overall_score", sa.Float),
        sa.Column("risk_level", sa.String(20)),
        sa.Column("critical_count", sa.Integer, default=0),
        sa.Column("high_count", sa.Integer, default=0),
        sa.Column("medium_count", sa.Integer, default=0),
        sa.Column("low_count", sa.Integer, default=0),
        sa.Column("error_message", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )
    op.create_table("scan_findings",
        _uuid_col(primary_key=True),
        _uuid_col("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
        _uuid_col("job_id", sa.ForeignKey("scan_jobs.id"), nullable=False),
        sa.Column("finding_type", sa.String(100), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("affected_path", sa.String(1000), nullable=False),
        sa.Column("evidence", sa.Text, nullable=False),
        sa.Column("remediation", sa.Text, nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("cvss_score", sa.Float, nullable=False),
        sa.Column("cve_id", sa.String(30)),
        sa.Column("owasp_category", sa.String(100)),
        sa.Column("is_false_positive", sa.Boolean, default=False),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )
    op.create_table("scan_schedules",
        _uuid_col(primary_key=True),
        _uuid_col("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
        _uuid_col("target_id", sa.ForeignKey("ojs_targets.id"), nullable=False),
        sa.Column("cron_expression", sa.String(100), nullable=False),
        sa.Column("scan_type", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )
    op.create_table("reports",
        _uuid_col(primary_key=True),
        _uuid_col("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
        _uuid_col("job_id", sa.ForeignKey("scan_jobs.id"), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("storage_path", sa.Text),
        sa.Column("file_size_bytes", sa.Integer),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )
    op.create_table("notifications",
        _uuid_col(primary_key=True),
        _uuid_col("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
        _uuid_col("job_id", sa.ForeignKey("scan_jobs.id"), nullable=False),
        _uuid_col("user_id", sa.ForeignKey("users.id"), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("notif_type", sa.String(30), nullable=False),
        sa.Column("is_sent", sa.Boolean, default=False),
        sa.Column("error_log", sa.Text),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )
    op.create_table("audit_logs",
        _uuid_col(primary_key=True),
        _uuid_col("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
        _uuid_col("user_id", sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(100)),
        sa.Column("details", JSONB),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )

    # Indexes
    op.create_index("idx_scan_jobs_target_id", "scan_jobs", ["target_id"])
    op.create_index("idx_scan_jobs_status", "scan_jobs", ["status"])
    op.create_index("idx_scan_findings_job_id", "scan_findings", ["job_id"])
    op.create_index("idx_scan_findings_severity", "scan_findings", ["severity"])
    op.create_index("idx_users_tenant_id", "users", ["tenant_id"])
    op.create_index("idx_ojs_targets_tenant_id", "ojs_targets", ["tenant_id"])

    # RLS — use true() fallback so saas_admin seed (without tenant context) still works
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                tenant_id = current_setting('app.current_tenant_id', true)::uuid
                OR current_setting('app.current_tenant_id', true) = ''
            )
        """)


def downgrade() -> None:
    for table in reversed(RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    for t in ["audit_logs","notifications","reports","scan_schedules",
              "scan_findings","scan_jobs","ojs_targets","users","tenants"]:
        op.drop_table(t)
```

- [ ] **Step 4: Write scripts/seed.py**

```python
"""Idempotent seed: default tenant + saas_admin user."""
import asyncio
import uuid
from passlib.context import CryptContext
from sqlalchemy import select
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Tenant, User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        # Tenant
        row = await session.execute(select(Tenant).where(Tenant.slug == "default"))
        tenant = row.scalar_one_or_none()
        if not tenant:
            tenant = Tenant(id=uuid.uuid4(), name="OJSDef Default", slug="default")
            session.add(tenant)
            await session.flush()
            print(f"[seed] tenant created: {tenant.id}")
        else:
            print(f"[seed] tenant exists: {tenant.id}")

        # saas_admin
        row = await session.execute(select(User).where(User.email == settings.seed_admin_email))
        user = row.scalar_one_or_none()
        if not user:
            user = User(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                email=settings.seed_admin_email,
                hashed_password=pwd_context.hash(settings.seed_admin_password),
                full_name="SaaS Administrator",
                role="saas_admin",
            )
            session.add(user)
            print(f"[seed] saas_admin created: {settings.seed_admin_email}")
        else:
            print(f"[seed] saas_admin exists: {settings.seed_admin_email}")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
```

- [ ] **Step 5: Run migration (requires postgres running)**

```bash
alembic upgrade head
```

Expected: `Running upgrade  -> 001, initial schema`

- [ ] **Step 6: Commit — SYNC POINT**

```bash
git add alembic.ini migrations/ scripts/
git commit -m "feat: alembic 001 migration (RLS + indexes) + idempotent seed"
```

**► Subagent A and Subagent B can now start in parallel.**

---

## SUBAGENT A — API Layer

---

## Task A1: Crypto Service + Auth Service + JWT Middleware

**Files:** `app/services/crypto.py`, `app/services/auth.py`, `app/middleware/auth.py`, `tests/conftest.py`

- [ ] **Step 1: Write app/services/crypto.py**

```python
import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.config import get_settings

settings = get_settings()


def _key() -> bytes:
    return bytes.fromhex(settings.plugin_api_key_secret)


def encrypt_api_key(plaintext: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt_api_key(ciphertext: str) -> str:
    raw = base64.b64decode(ciphertext)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(_key()).decrypt(nonce, ct, None).decode()
```

- [ ] **Step 2: Write test for crypto — tests/test_crypto.py**

```python
from app.services.crypto import encrypt_api_key, decrypt_api_key


def test_encrypt_decrypt_roundtrip():
    plaintext = "my-secret-api-key-1234"
    ct = encrypt_api_key(plaintext)
    assert ct != plaintext
    assert decrypt_api_key(ct) == plaintext


def test_each_encrypt_produces_unique_ciphertext():
    ct1 = encrypt_api_key("same")
    ct2 = encrypt_api_key("same")
    assert ct1 != ct2  # different nonces
```

- [ ] **Step 3: Run crypto tests**

```bash
pytest tests/test_crypto.py -v
```

Expected: 2 PASSED

- [ ] **Step 4: Write app/services/auth.py**

```python
import uuid
import secrets
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from jose import jwt, JWTError
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import get_settings
from app.models import User

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _redis():
    return aioredis.from_url(settings.redis_url, decode_responses=True)


def _make_token(payload: dict, expire_delta: timedelta) -> tuple[str, str]:
    jti = str(uuid.uuid4())
    exp = datetime.now(timezone.utc) + expire_delta
    data = {**payload, "jti": jti, "exp": exp}
    token = jwt.encode(data, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti


async def create_tokens(user: User) -> dict:
    payload = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "role": user.role,
    }
    access_token, _ = _make_token(
        payload, timedelta(minutes=settings.access_token_expire_minutes)
    )
    refresh_token, jti = _make_token(
        {"sub": str(user.id)},
        timedelta(days=settings.refresh_token_expire_days),
    )
    r = _redis()
    ttl = settings.refresh_token_expire_days * 86400
    await r.setex(f"refresh:{user.id}:{jti}", ttl, "1")
    await r.aclose()
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


async def revoke_refresh_token(user_id: str, jti: str) -> None:
    r = _redis()
    await r.delete(f"refresh:{user_id}:{jti}")
    await r.aclose()


async def revoke_all_refresh_tokens(user_id: str) -> None:
    r = _redis()
    keys = await r.keys(f"refresh:{user_id}:*")
    if keys:
        await r.delete(*keys)
    await r.aclose()


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
```

- [ ] **Step 5: Write app/middleware/auth.py**

```python
from fastapi import Request, HTTPException, status
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
```

- [ ] **Step 6: Register middleware + add RBAC deps in app/main.py**

Add after the CORS middleware block:

```python
from starlette.middleware.base import BaseHTTPMiddleware
from app.middleware.auth import jwt_middleware

app.add_middleware(BaseHTTPMiddleware, dispatch=jwt_middleware)
```

- [ ] **Step 7: Write RBAC FastAPI dependencies in app/services/auth.py** (append)

```python
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        return decode_access_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_role(*roles: str):
    async def dependency(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user
    return dependency
```

- [ ] **Step 8: Commit**

```bash
git add app/services/crypto.py app/services/auth.py app/middleware/auth.py app/main.py tests/
git commit -m "feat: crypto service (AES-GCM), auth service (JWT/bcrypt), JWT middleware, RBAC deps"
```

---

## Task A2: Auth Router

**Files:** `app/schemas/auth.py`, `app/routers/auth.py`, `tests/test_auth.py`

- [ ] **Step 1: Write app/schemas/auth.py**

```python
from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    must_change_password: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class UpdateProfileRequest(BaseModel):
    full_name: str | None = None
    notif_email: bool | None = None
    notif_telegram: bool | None = None
    telegram_chat_id: str | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    must_change_password: bool
    notif_email: bool
    notif_telegram: bool
    telegram_chat_id: str | None
```

- [ ] **Step 2: Write app/routers/auth.py**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError
from app.database import get_db
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

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
settings = get_settings()


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await authenticate_user(db, body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Credensial tidak valid")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Akun dinonaktifkan")
    tokens = await create_tokens(user)
    return TokenResponse(**tokens, must_change_password=user.must_change_password)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_access_token(body.refresh_token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Refresh token tidak valid")
    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User tidak ditemukan")
    await revoke_refresh_token(str(user.id), payload["jti"])
    tokens = await create_tokens(user)
    return TokenResponse(**tokens)


@router.post("/logout", status_code=204)
async def logout(
    body: RefreshRequest,
    current: dict = Depends(get_current_user),
):
    try:
        payload = decode_access_token(body.refresh_token)
        await revoke_refresh_token(payload["sub"], payload["jti"])
    except JWTError:
        pass


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
```

- [ ] **Step 3: Register auth router in app/main.py** (append after health endpoint)

```python
from app.routers import auth as auth_router
app.include_router(auth_router.router)
```

- [ ] **Step 4: Write tests/conftest.py**

```python
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
```

- [ ] **Step 5: Write tests/test_auth.py**

```python
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
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_auth.py -v
```

Expected: 2 PASSED

- [ ] **Step 7: Commit**

```bash
git add app/schemas/auth.py app/routers/auth.py tests/
git commit -m "feat: auth router (login, refresh, logout, me, change-password)"
```

---

## Task A3: Targets Service + Router

**Files:** `app/services/targets.py`, `app/schemas/targets.py`, `app/routers/targets.py`, `tests/test_targets.py`

- [ ] **Step 1: Write app/services/targets.py**

```python
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
    verify_url = f"{url.rstrip('/')}/ojsdef-verify-{token}.txt"
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
                if txt_string.decode() == f"ojsdef-verify={token}":
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
```

- [ ] **Step 2: Write unit test for plugin status computation**

```python
# tests/test_targets.py
from datetime import datetime, timezone, timedelta
from app.models import OJSTarget
from app.services.targets import compute_plugin_status


def _target(last_seen):
    t = OJSTarget.__new__(OJSTarget)
    t.plugin_last_seen = last_seen
    return t


def test_plugin_connected_within_15_min():
    t = _target(datetime.now(timezone.utc) - timedelta(minutes=5))
    assert compute_plugin_status(t) is True


def test_plugin_disconnected_after_15_min():
    t = _target(datetime.now(timezone.utc) - timedelta(minutes=20))
    assert compute_plugin_status(t) is False


def test_plugin_never_connected():
    t = _target(None)
    assert compute_plugin_status(t) is False
```

- [ ] **Step 3: Run target unit tests**

```bash
pytest tests/test_targets.py -v
```

Expected: 3 PASSED

- [ ] **Step 4: Write app/schemas/targets.py**

```python
from pydantic import BaseModel, HttpUrl
from datetime import datetime


class CreateTargetRequest(BaseModel):
    name: str
    url: str


class TargetResponse(BaseModel):
    id: str
    name: str
    url: str
    is_verified: bool
    plugin_connected: bool
    ojs_version: str | None
    created_at: datetime


class VerifyResponse(BaseModel):
    verified: bool
    method: str | None = None


class PluginGuideResponse(BaseModel):
    target_id: str
    api_key: str
    endpoint: str
    instructions: str
```

- [ ] **Step 5: Write app/routers/targets.py**

```python
import uuid
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import OJSTarget
from app.schemas.targets import (
    CreateTargetRequest, TargetResponse, VerifyResponse, PluginGuideResponse,
)
from app.services.targets import (
    compute_plugin_status, create_target, verify_domain_file,
    verify_domain_dns, regenerate_api_key,
)
from app.services.crypto import decrypt_api_key
from app.services.auth import get_current_user

router = APIRouter(prefix="/api/v1/targets", tags=["targets"])


def _to_response(t: OJSTarget) -> TargetResponse:
    return TargetResponse(
        id=str(t.id), name=t.name, url=t.url,
        is_verified=t.is_verified,
        plugin_connected=compute_plugin_status(t),
        ojs_version=t.ojs_version,
        created_at=t.created_at,
    )


@router.get("", response_model=list[TargetResponse])
async def list_targets(
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(OJSTarget))
    return [_to_response(t) for t in result.scalars()]


@router.post("", response_model=TargetResponse, status_code=201)
async def add_target(
    body: CreateTargetRequest,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await create_target(db, uuid.UUID(current["tenant_id"]), body.name, body.url)
    return _to_response(target)


@router.get("/{target_id}", response_model=TargetResponse)
async def get_target(
    target_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(OJSTarget).where(OJSTarget.id == target_id))
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
    result = await db.execute(select(OJSTarget).where(OJSTarget.id == target_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target tidak ditemukan")
    await db.delete(target)
    await db.commit()


@router.post("/{target_id}/verify", response_model=VerifyResponse)
async def verify_target(
    target_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(OJSTarget).where(OJSTarget.id == target_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target tidak ditemukan")
    token = target.verification_token
    if await verify_domain_file(target.url, token):
        target.is_verified = True
        await db.commit()
        return VerifyResponse(verified=True, method="file")
    domain = urlparse(target.url).hostname
    if await verify_domain_dns(domain, token):
        target.is_verified = True
        await db.commit()
        return VerifyResponse(verified=True, method="dns")
    return VerifyResponse(verified=False)


@router.get("/{target_id}/plugin-guide", response_model=PluginGuideResponse)
async def plugin_guide(
    target_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(OJSTarget).where(OJSTarget.id == target_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target tidak ditemukan")
    api_key = decrypt_api_key(target.plugin_api_key_encrypted)
    return PluginGuideResponse(
        target_id=str(target.id),
        api_key=api_key,
        endpoint="/plugin/v1/callback",
        instructions="Install plugin OJSDef di OJS, masukkan API Key dan endpoint di atas.",
    )


@router.post("/{target_id}/regenerate-key")
async def regen_key(
    target_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(OJSTarget).where(OJSTarget.id == target_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target tidak ditemukan")
    new_key = await regenerate_api_key(db, target)
    return {"api_key": new_key}
```

- [ ] **Step 6: Register targets router in app/main.py**

```python
from app.routers import targets as targets_router
app.include_router(targets_router.router)
```

- [ ] **Step 7: Commit**

```bash
git add app/services/targets.py app/schemas/targets.py app/routers/targets.py
git commit -m "feat: targets API (CRUD, domain verify, plugin guide, regen key)"
```

---

## Task A4: Plugin Callback Middleware + Router

**Files:** `app/middleware/plugin_auth.py`, `app/routers/plugin_callback.py`

- [ ] **Step 1: Write app/middleware/plugin_auth.py**

```python
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
```

- [ ] **Step 2: Write tests/test_plugin_callback.py**

```python
import hmac, hashlib, time, json
import pytest


def _make_headers(body: bytes, api_key: str, target_id: str) -> dict:
    ts = str(int(time.time()))
    sig = "sha256=" + hmac.new(api_key.encode(), body, hashlib.sha256).hexdigest()
    return {
        "X-OJSDef-Target-ID": target_id,
        "X-OJSDef-Signature": sig,
        "X-OJSDef-Timestamp": ts,
        "Content-Type": "application/json",
    }


@pytest.mark.asyncio
async def test_callback_missing_headers_returns_401(client):
    resp = await client.post("/plugin/v1/callback", content=b"{}")
    assert resp.status_code == 401
```

- [ ] **Step 3: Write app/routers/plugin_callback.py**

```python
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select
from datetime import datetime, timezone
from app.database import AsyncSessionLocal
from app.models import OJSTarget, ScanJob
from app.celery_app import celery_app

router = APIRouter(prefix="/plugin/v1", tags=["plugin"])


@router.post("/callback")
async def plugin_callback(request: Request):
    target: OJSTarget = request.state.plugin_target
    body: bytes = request.state.plugin_body

    import json
    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    event = payload.get("event")

    async with AsyncSessionLocal() as session:
        # Re-fetch target in this session
        result = await session.execute(
            select(OJSTarget).where(OJSTarget.id == target.id)
        )
        t = result.scalar_one()

        if event == "heartbeat":
            t.plugin_last_seen = datetime.now(timezone.utc)
            await session.commit()
            return {"status": "ok"}

        if event == "audit_data":
            job_id = payload.get("job_id")
            if not job_id:
                raise HTTPException(400, "job_id required")
            result = await session.execute(
                select(ScanJob).where(ScanJob.id == job_id, ScanJob.status == "running")
            )
            job = result.scalar_one_or_none()
            if not job:
                raise HTTPException(404, "Scan job tidak ditemukan atau tidak dalam status running")

            celery_app.send_task(
                "app.workers.internal_bot.process_plugin_data_task",
                args=[str(job.id), payload.get("data", {})],
                queue="internal_scan",
            )
            return {"status": "received", "queued": True}

    raise HTTPException(400, "Event tidak dikenal")
```

- [ ] **Step 4: Register plugin_auth middleware + router in app/main.py**

```python
from app.middleware.plugin_auth import plugin_auth_middleware
from app.routers import plugin_callback as plugin_router

app.add_middleware(BaseHTTPMiddleware, dispatch=plugin_auth_middleware)
app.include_router(plugin_router.router)
```

- [ ] **Step 5: Run plugin callback tests**

```bash
pytest tests/test_plugin_callback.py -v
```

Expected: 1 PASSED

- [ ] **Step 6: Commit**

```bash
git add app/middleware/plugin_auth.py app/routers/plugin_callback.py
git commit -m "feat: plugin callback (HMAC auth, heartbeat, audit_data dispatch)"
```

---

## Task A5: Scans Router + Celery Task Stubs

**Files:** `app/schemas/scans.py`, `app/routers/scans.py`, `app/workers/internal_bot.py` (stub), `app/workers/external_bot.py` (stub)

- [ ] **Step 1: Write app/schemas/scans.py**

```python
from pydantic import BaseModel
from datetime import datetime


class StartScanRequest(BaseModel):
    target_id: str
    scan_type: str  # internal|external|full


class ScanResponse(BaseModel):
    id: str
    target_id: str
    scan_type: str
    status: str
    overall_score: float | None
    risk_level: str | None
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    progress: dict | None = None
    created_at: datetime


class FindingResponse(BaseModel):
    id: str
    finding_type: str
    category: str
    title: str
    description: str
    affected_path: str
    evidence: str
    remediation: str
    severity: str
    cvss_score: float
    cve_id: str | None
    owasp_category: str | None
    is_false_positive: bool
```

- [ ] **Step 2: Write app/routers/scans.py**

```python
import uuid
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import redis.asyncio as aioredis
from celery import chain, chord
from app.database import get_db
from app.models import OJSTarget, ScanJob, ScanFinding
from app.schemas.scans import StartScanRequest, ScanResponse, FindingResponse
from app.services.auth import get_current_user, require_role
from app.celery_app import celery_app
from app.config import get_settings

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
    return ScanResponse(
        id=str(job.id), target_id=str(job.target_id),
        scan_type=job.scan_type, status=job.status,
        overall_score=job.overall_score, risk_level=job.risk_level,
        critical_count=job.critical_count, high_count=job.high_count,
        medium_count=job.medium_count, low_count=job.low_count,
        progress=progress, created_at=job.created_at,
    )


@router.post("", response_model=ScanResponse, status_code=201)
async def start_scan(
    body: StartScanRequest,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OJSTarget).where(OJSTarget.id == body.target_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target tidak ditemukan")
    if not target.is_verified:
        raise HTTPException(400, "Target belum diverifikasi")

    job = ScanJob(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(current["tenant_id"]),
        target_id=target.id,
        scan_type=body.scan_type,
        status="queued",
        started_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    job_id = str(job.id)
    target_id = str(target.id)
    target_url = target.url

    internal = celery_app.signature(
        "app.workers.internal_bot.internal_scan_task",
        args=[job_id, target_id], immutable=True, queue="internal_scan",
    )
    external = celery_app.signature(
        "app.workers.external_bot.external_scan_task",
        args=[job_id, target_url], immutable=True, queue="external_scan",
    )
    scoring = celery_app.signature(
        "app.workers.scoring.scoring_task",
        args=[job_id], immutable=True, queue="scoring",
    )

    if body.scan_type == "internal":
        chain(internal, scoring).delay()
    elif body.scan_type == "external":
        chain(external, scoring).delay()
    else:
        chord([internal, external], scoring).delay()

    return _to_response(job)


@router.get("", response_model=list[ScanResponse])
async def list_scans(
    target_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(ScanJob).order_by(ScanJob.created_at.desc()).limit(limit)
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
    result = await db.execute(select(ScanJob).where(ScanJob.id == job_id))
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
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ScanFinding).where(ScanFinding.id == finding_id, ScanFinding.job_id == job_id)
    )
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(404, "Finding tidak ditemukan")
    f.is_false_positive = not f.is_false_positive
    await db.commit()
    await db.refresh(f)
    return FindingResponse(
        id=str(f.id), finding_type=f.finding_type, category=f.category,
        title=f.title, description=f.description, affected_path=f.affected_path,
        evidence=f.evidence, remediation=f.remediation, severity=f.severity,
        cvss_score=f.cvss_score, cve_id=f.cve_id, owasp_category=f.owasp_category,
        is_false_positive=f.is_false_positive,
    )
```

- [ ] **Step 3: Write Celery task stubs (workers will be wired in Tasks 9–11)**

`app/workers/internal_bot.py` (stub):
```python
from app.celery_app import celery_app


@celery_app.task(
    name="app.workers.internal_bot.internal_scan_task",
    bind=True, max_retries=3,
    autoretry_for=(Exception,), default_retry_delay=60,
)
def internal_scan_task(self, job_id: str, target_id: str):
    # Implemented in Task 9
    pass


@celery_app.task(name="app.workers.internal_bot.process_plugin_data_task")
def process_plugin_data_task(job_id: str, data: dict):
    # Implemented in Task 9
    pass
```

`app/workers/external_bot.py` (stub):
```python
from app.celery_app import celery_app


@celery_app.task(
    name="app.workers.external_bot.external_scan_task",
    bind=True, max_retries=3,
    autoretry_for=(Exception,), default_retry_delay=60,
)
def external_scan_task(self, job_id: str, target_url: str):
    # Implemented in Task 10
    pass
```

`app/workers/scoring.py` (stub):
```python
from app.celery_app import celery_app


@celery_app.task(
    name="app.workers.scoring.scoring_task",
    bind=True, max_retries=3,
    autoretry_for=(Exception,), default_retry_delay=60,
)
def scoring_task(self, job_id: str):
    # Implemented in Task 11
    pass
```

- [ ] **Step 4: Register scans router in app/main.py**

```python
from app.routers import scans as scans_router
app.include_router(scans_router.router)
```

- [ ] **Step 5: Commit**

```bash
git add app/schemas/scans.py app/routers/scans.py app/workers/
git commit -m "feat: scans router (start, list, findings, false-positive) + worker stubs"
```

---

## Task A6: Reports + Dashboard + Admin Routers

**Files:** `app/schemas/reports.py`, `app/schemas/admin.py`, `app/routers/reports.py`, `app/routers/dashboard.py`, `app/routers/admin.py`

- [ ] **Step 1: Write app/schemas/reports.py**

```python
from pydantic import BaseModel
from datetime import datetime


class ReportResponse(BaseModel):
    id: str
    job_id: str
    format: str
    file_size_bytes: int | None
    created_at: datetime
```

- [ ] **Step 2: Write app/routers/reports.py**

```python
import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import boto3
from app.database import get_db
from app.models import Report, ScanFinding, ScanJob
from app.schemas.reports import ReportResponse
from app.services.auth import get_current_user
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
    result = await db.execute(select(Report).order_by(Report.created_at.desc()))
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
    result = await db.execute(select(Report).where(Report.id == report_id, Report.format == "pdf"))
    report = result.scalar_one_or_none()
    if not report or not report.storage_path:
        raise HTTPException(404, "Laporan PDF tidak ditemukan")
    url = _s3().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.minio_bucket, "Key": report.storage_path},
        ExpiresIn=3600,
    )
    return RedirectResponse(url)


@router.get("/{report_id}/json")
async def download_json(
    report_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "Laporan tidak ditemukan")
    job_result = await db.execute(select(ScanJob).where(ScanJob.id == report.job_id))
    job = job_result.scalar_one()
    findings_result = await db.execute(
        select(ScanFinding).where(ScanFinding.job_id == report.job_id)
    )
    findings = findings_result.scalars().all()
    return {
        "job_id": str(job.id), "scan_type": job.scan_type, "status": job.status,
        "overall_score": job.overall_score, "risk_level": job.risk_level,
        "findings": [
            {"title": f.title, "severity": f.severity, "cvss_score": f.cvss_score,
             "description": f.description, "remediation": f.remediation}
            for f in findings
        ],
    }
```

- [ ] **Step 3: Write app/routers/dashboard.py**

```python
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
    now = datetime.now(timezone.utc)
    month_ago = now - timedelta(days=30)

    targets_count = (await db.execute(
        select(func.count()).select_from(OJSTarget)
    )).scalar()

    scans_result = await db.execute(
        select(ScanJob).where(ScanJob.created_at >= month_ago)
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

- [ ] **Step 4: Write app/schemas/admin.py**

```python
from pydantic import BaseModel, EmailStr


class CreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str
    role: str
    tenant_id: str | None = None


class PatchUserRequest(BaseModel):
    is_active: bool | None = None
    role: str | None = None


class CreateTenantRequest(BaseModel):
    name: str
    slug: str


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    is_active: bool
```

- [ ] **Step 5: Write app/routers/admin.py**

```python
import uuid
import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import User, Tenant
from app.schemas.admin import (
    CreateUserRequest, PatchUserRequest,
    CreateTenantRequest, TenantResponse,
)
from app.schemas.auth import UserResponse
from app.services.auth import require_role, hash_password

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
_saas = Depends(require_role("saas_admin"))


@router.post("/users", response_model=UserResponse, status_code=201, dependencies=[_saas])
async def create_user(body: CreateUserRequest, db: AsyncSession = Depends(get_db)):
    temp_password = secrets.token_urlsafe(12)
    tid = uuid.UUID(body.tenant_id) if body.tenant_id else None
    if not tid:
        result = await db.execute(select(Tenant).where(Tenant.slug == "default"))
        tenant = result.scalar_one_or_none()
        tid = tenant.id if tenant else None
    user = User(
        id=uuid.uuid4(), tenant_id=tid,
        email=body.email, full_name=body.full_name, role=body.role,
        hashed_password=hash_password(temp_password),
        must_change_password=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserResponse(
        id=str(user.id), email=user.email, full_name=user.full_name,
        role=user.role, must_change_password=user.must_change_password,
        notif_email=user.notif_email, notif_telegram=user.notif_telegram,
        telegram_chat_id=user.telegram_chat_id,
    )


@router.get("/users", dependencies=[_saas])
async def list_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User))
    users = result.scalars().all()
    return [
        {"id": str(u.id), "email": u.email, "role": u.role, "is_active": u.is_active}
        for u in users
    ]


@router.patch("/users/{user_id}", dependencies=[_saas])
async def patch_user(
    user_id: uuid.UUID,
    body: PatchUserRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User tidak ditemukan")
    for field, val in body.model_dump(exclude_none=True).items():
        setattr(user, field, val)
    await db.commit()
    return {"id": str(user.id), "is_active": user.is_active, "role": user.role}


@router.delete("/users/{user_id}", status_code=204, dependencies=[_saas])
async def delete_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User tidak ditemukan")
    await db.delete(user)
    await db.commit()


@router.post("/tenants", response_model=TenantResponse, status_code=201, dependencies=[_saas])
async def create_tenant(body: CreateTenantRequest, db: AsyncSession = Depends(get_db)):
    tenant = Tenant(id=uuid.uuid4(), name=body.name, slug=body.slug)
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return TenantResponse(id=str(tenant.id), name=tenant.name, slug=tenant.slug, is_active=tenant.is_active)


@router.get("/tenants", dependencies=[_saas])
async def list_tenants(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tenant))
    return [
        {"id": str(t.id), "name": t.name, "slug": t.slug, "is_active": t.is_active}
        for t in result.scalars()
    ]
```

- [ ] **Step 6: Register remaining routers in app/main.py**

```python
from app.routers import reports as reports_router
from app.routers import dashboard as dashboard_router
from app.routers import admin as admin_router

app.include_router(reports_router.router)
app.include_router(dashboard_router.router)
app.include_router(admin_router.router)
```

- [ ] **Step 7: Commit — Subagent A complete**

```bash
git add app/schemas/ app/routers/ app/workers/scoring.py
git commit -m "feat: reports, dashboard, admin routers — Subagent A complete"
```

---

## SUBAGENT B — Scanner Modules

---

## Task B1: FindingResult Dataclass (Sync Contract)

**Files:** `app/scanners/models.py`

- [ ] **Step 1: Write app/scanners/models.py**

```python
from dataclasses import dataclass


@dataclass
class FindingResult:
    finding_type: str
    category: str           # "internal" | "external"
    title: str
    description: str
    affected_path: str
    evidence: str
    remediation: str        # Bahasa Indonesia
    cvss_score: float
    severity: str           # low|medium|high|critical
    cve_id: str | None = None
    owasp_category: str | None = None


CVSS_SCORES: dict[str, float] = {
    "debug_mode_enabled": 7.5, "weak_db_password": 8.0, "exposed_db_backup": 9.0,
    "outdated_plugin": 6.5, "cve_vulnerable_plugin": 9.5, "disabled_security_plugin": 5.5,
    "privilege_excess": 7.0, "inactive_admin": 5.0, "modified_core_file": 8.5,
    "unknown_file": 6.0, "missing_core_file": 7.5, "injected_content": 9.0,
    "malicious_redirect": 9.5, "exposed_iframe": 8.0,
    "ojs_version_exposed": 4.0, "outdated_ojs_version": 7.0,
    "ssl_expired": 9.0, "ssl_expiring_soon": 5.0, "weak_tls": 7.5,
    "missing_csp": 6.0, "missing_hsts": 6.5, "missing_x_frame": 5.5,
    "reflected_xss": 8.5, "sql_error_exposed": 8.0, "path_traversal": 7.5,
    "open_directory": 7.0, "exposed_env_file": 9.5, "exposed_git": 9.0,
    "phpinfo_exposed": 7.0, "cve_ojs": 9.0,
}


def severity_from_score(score: float) -> str:
    if score >= 9.0: return "critical"
    if score >= 7.0: return "high"
    if score >= 4.0: return "medium"
    return "low"


def make_finding(finding_type: str, **kwargs) -> FindingResult:
    score = CVSS_SCORES.get(finding_type, 5.0)
    return FindingResult(
        finding_type=finding_type,
        cvss_score=score,
        severity=severity_from_score(score),
        **kwargs,
    )
```

- [ ] **Step 2: Write tests/test_scanners/test_models.py**

```python
from app.scanners.models import severity_from_score, make_finding

def test_critical():
    assert severity_from_score(9.5) == "critical"

def test_high():
    assert severity_from_score(7.5) == "high"

def test_medium():
    assert severity_from_score(5.0) == "medium"

def test_make_finding_assigns_severity():
    f = make_finding("weak_db_password", category="internal",
        title="T", description="D", affected_path="/", evidence="E", remediation="R")
    assert f.severity == "high"
    assert f.cvss_score == 8.0
```

- [ ] **Step 3: Run**

```bash
pytest tests/test_scanners/test_models.py -v
```

Expected: 4 PASSED

- [ ] **Step 4: Commit**

```bash
git add app/scanners/models.py tests/test_scanners/test_models.py
git commit -m "feat: FindingResult dataclass + CVSS_SCORES (scanner sync contract)"
```

---

## Task B2: Internal — Config + Plugin Auditor

- [ ] **Step 1: Write app/scanners/internal/config_scanner.py**

```python
from app.scanners.models import FindingResult, make_finding

WEAK_PASSWORDS = {"", "password", "ojsdef", "admin", "123456", "ojs", "root"}


def scan_config(config: dict) -> list[FindingResult]:
    findings = []
    if config.get("debug", False):
        findings.append(make_finding(
            "debug_mode_enabled", category="internal",
            title="Mode Debug Aktif",
            description="OJS berjalan dalam mode debug, mengekspos informasi sensitif.",
            affected_path="config.inc.php",
            evidence="debug = On",
            remediation="Set `debug = Off` di config.inc.php dan restart server.",
        ))
    db_pass = config.get("database", {}).get("password", "")
    if db_pass.lower() in WEAK_PASSWORDS:
        findings.append(make_finding(
            "weak_db_password", category="internal",
            title="Password Database Lemah",
            description="Password koneksi database OJS terlalu mudah ditebak.",
            affected_path="config.inc.php [database] password",
            evidence=f"password = {db_pass!r}",
            remediation="Ganti password database dengan minimal 16 karakter acak.",
        ))
    return findings
```

- [ ] **Step 2: Write app/scanners/internal/plugin_auditor.py**

```python
from app.scanners.models import FindingResult, make_finding

KNOWN_SECURITY_PLUGINS = {"orcidProfile", "acron", "dois"}


def scan_plugins(plugins: list[dict]) -> list[FindingResult]:
    findings = []
    for p in plugins:
        name = p.get("name", "unknown")
        version = p.get("version", "0")
        for cve in p.get("cve_ids", []):
            findings.append(make_finding(
                "cve_vulnerable_plugin", category="internal",
                title=f"Plugin {name} Rentan CVE",
                description=f"Plugin {name} v{version} memiliki kerentanan: {cve}.",
                affected_path=f"plugins/{name}",
                evidence=f"version={version}, cve={cve}",
                remediation=f"Update plugin {name} ke versi terbaru.",
                cve_id=cve,
            ))
        if not p.get("cve_ids") and p.get("outdated"):
            findings.append(make_finding(
                "outdated_plugin", category="internal",
                title=f"Plugin {name} Sudah Usang",
                description=f"Plugin {name} v{version} tidak diperbarui.",
                affected_path=f"plugins/{name}",
                evidence=f"version={version}",
                remediation=f"Update plugin {name} ke versi terbaru.",
            ))
        if not p.get("enabled") and name in KNOWN_SECURITY_PLUGINS:
            findings.append(make_finding(
                "disabled_security_plugin", category="internal",
                title=f"Plugin Keamanan {name} Dinonaktifkan",
                description=f"Plugin penting {name} tidak aktif.",
                affected_path=f"plugins/{name}",
                evidence="enabled=false",
                remediation=f"Aktifkan plugin {name} melalui panel admin OJS.",
            ))
    return findings
```

- [ ] **Step 3: Write tests/test_scanners/test_internal_config.py**

```python
from app.scanners.internal.config_scanner import scan_config
from app.scanners.internal.plugin_auditor import scan_plugins

def test_debug_flagged():
    f = scan_config({"debug": True, "database": {"password": "strong!Pass99"}})
    assert any(x.finding_type == "debug_mode_enabled" for x in f)

def test_clean_config_no_findings():
    f = scan_config({"debug": False, "database": {"password": "Str0ng!Pass#2026"}})
    assert f == []

def test_cve_plugin():
    f = scan_plugins([{"name": "p", "version": "1.0", "cve_ids": ["CVE-2024-1"]}])
    assert f[0].finding_type == "cve_vulnerable_plugin"

def test_outdated_plugin():
    f = scan_plugins([{"name": "p", "version": "0.9", "outdated": True, "cve_ids": []}])
    assert f[0].finding_type == "outdated_plugin"
```

- [ ] **Step 4: Run**

```bash
pytest tests/test_scanners/test_internal_config.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add app/scanners/internal/config_scanner.py app/scanners/internal/plugin_auditor.py tests/
git commit -m "feat: internal scanners - config + plugin auditor"
```

---

## Task B3: Internal — RBAC + File Integrity

- [ ] **Step 1: Write app/scanners/internal/rbac_auditor.py**

```python
from datetime import datetime, timezone, timedelta
from app.scanners.models import FindingResult, make_finding


def scan_rbac(users: list[dict]) -> list[FindingResult]:
    findings = []
    stale = datetime.now(timezone.utc) - timedelta(days=180)
    for u in users:
        name = u.get("username", "unknown")
        roles = set(u.get("roles", []))
        if {"Site Administrator", "Journal Manager"}.issubset(roles) and len(roles) > 2:
            findings.append(make_finding(
                "privilege_excess", category="internal",
                title=f"Pengguna {name} Kelebihan Hak Akses",
                description="Kombinasi peran tinggi berlebihan.",
                affected_path=f"users/{name}",
                evidence=f"roles={list(roles)}",
                remediation="Terapkan prinsip least privilege — satu peran per pengguna.",
            ))
        last_str = u.get("last_login")
        if last_str and "Administrator" in roles:
            try:
                last = datetime.fromisoformat(last_str.replace("Z", "+00:00"))
                if last < stale:
                    findings.append(make_finding(
                        "inactive_admin", category="internal",
                        title=f"Admin {name} Tidak Aktif >6 Bulan",
                        description="Akun admin tidak aktif merupakan risiko.",
                        affected_path=f"users/{name}",
                        evidence=f"last_login={last_str}",
                        remediation=f"Nonaktifkan akun admin {name} yang tidak aktif.",
                    ))
            except ValueError:
                pass
    return findings
```

- [ ] **Step 2: Write app/scanners/internal/file_integrity.py**

```python
from app.scanners.models import FindingResult, make_finding


def scan_file_integrity(data: dict) -> list[FindingResult]:
    findings = []
    for path in data.get("modified_core_files", []):
        findings.append(make_finding(
            "modified_core_file", category="internal",
            title="File Core OJS Dimodifikasi",
            description=f"File {path} telah diubah, kemungkinan injeksi kode.",
            affected_path=path, evidence=f"checksum mismatch: {path}",
            remediation="Bandingkan dengan versi OJS resmi. Restore dari backup jika perlu.",
        ))
    for path in data.get("unknown_files", []):
        findings.append(make_finding(
            "unknown_file", category="internal",
            title="File Tidak Dikenal Ditemukan",
            description=f"File {path} bukan bagian distribusi OJS standar.",
            affected_path=path, evidence=f"tidak ada di manifest OJS: {path}",
            remediation="Identifikasi asal file. Hapus jika tidak diketahui.",
        ))
    for path in data.get("missing_core_files", []):
        findings.append(make_finding(
            "missing_core_file", category="internal",
            title="File Core OJS Hilang",
            description=f"File {path} tidak ditemukan.",
            affected_path=path, evidence=f"file tidak ada: {path}",
            remediation="Restore file dari paket OJS versi yang sesuai.",
        ))
    return findings
```

- [ ] **Step 3: Commit**

```bash
git add app/scanners/internal/rbac_auditor.py app/scanners/internal/file_integrity.py
git commit -m "feat: internal scanners - rbac auditor + file integrity"
```

---

## Task B4: Internal — Content Detector + DB Security

- [ ] **Step 1: Write app/scanners/internal/content_detector.py**

```python
import re
from app.scanners.models import FindingResult, make_finding

GAMBLING = re.compile(r"(slot\s*online|togel|judi\s*bola|casino|poker\s*online)", re.I)
IFRAME = re.compile(r"<iframe[^>]+src=[\"'][^\"']+[\"']", re.I)
META_REDIRECT = re.compile(r'<meta[^>]+http-equiv=["\']refresh["\'][^>]*url=', re.I)


def scan_content(articles: list[dict]) -> list[FindingResult]:
    findings = []
    for a in articles:
        aid = a.get("id", "unknown")
        title, content = a.get("title", ""), a.get("content", "")
        path = f"articles/{aid}"
        if GAMBLING.search(title) or GAMBLING.search(content):
            findings.append(make_finding(
                "injected_content", category="internal",
                title="Konten Judi/Spam di Artikel",
                description=f"Artikel #{aid} mengandung konten judi atau spam.",
                affected_path=path, evidence=f"title: {title[:80]}",
                remediation="Hapus atau nonpublikasikan artikel. Audit akses editor.",
            ))
        if META_REDIRECT.search(content):
            findings.append(make_finding(
                "malicious_redirect", category="internal",
                title="Meta Redirect Mencurigakan",
                description=f"Artikel #{aid} mengandung meta redirect.",
                affected_path=path, evidence="meta refresh redirect ditemukan",
                remediation="Hapus meta redirect. Audit konten artikel lainnya.",
            ))
        m = IFRAME.search(content)
        if m:
            findings.append(make_finding(
                "exposed_iframe", category="internal",
                title="iFrame Eksternal di Artikel",
                description=f"Artikel #{aid} menyematkan iframe eksternal.",
                affected_path=path, evidence=m.group(0)[:200],
                remediation="Hapus iframe tidak dikenal. Audit sumber konten.",
            ))
    return findings
```

- [ ] **Step 2: Write app/scanners/internal/db_security.py**

```python
from app.scanners.models import FindingResult, make_finding

WEAK = {"root", "toor", "password", "admin", "ojs", "", "123456"}
BACKUP_EXT = {".sql", ".sql.gz", ".dump", ".bak"}


def scan_db_security(db_config: dict) -> list[FindingResult]:
    findings = []
    pw = db_config.get("password", "")
    if pw.lower() in WEAK:
        findings.append(make_finding(
            "weak_db_password", category="internal",
            title="Password Database Lemah",
            description="Password database sangat mudah ditebak.",
            affected_path="config.inc.php [database]",
            evidence=f"password = {pw!r}",
            remediation="Ganti password database dengan nilai acak minimal 16 karakter.",
        ))
    for f in db_config.get("exposed_backup_files", []):
        if any(f.endswith(ext) for ext in BACKUP_EXT):
            findings.append(make_finding(
                "exposed_db_backup", category="internal",
                title="Backup Database Dapat Diakses Publik",
                description=f"File backup {f} dapat diakses tanpa autentikasi.",
                affected_path=f, evidence=f"accessible: {f}",
                remediation="Pindahkan backup ke luar webroot atau proteksi dengan auth.",
            ))
    return findings
```

- [ ] **Step 3: Commit**

```bash
git add app/scanners/internal/content_detector.py app/scanners/internal/db_security.py
git commit -m "feat: internal scanners - content detector + db security"
```

---

## Task B5: External — Fingerprinter + SSL + Headers

- [ ] **Step 1: Write app/scanners/external/fingerprinter.py**

```python
import re
import httpx
from app.scanners.models import FindingResult, make_finding

VERSION_RE = re.compile(r'content="OJS/(\d+\.\d+[\.\d]*)"')


async def scan_fingerprint(url: str) -> tuple[str | None, list[FindingResult]]:
    findings = []
    version = None
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            resp = await c.get(url)
            m = VERSION_RE.search(resp.text)
            if m:
                version = m.group(1)
                findings.append(make_finding(
                    "ojs_version_exposed", category="external",
                    title="Versi OJS Terekspos di Source",
                    description=f"Versi OJS {version} terdeteksi dari HTML source.",
                    affected_path=url,
                    evidence=f'<meta name="generator" content="OJS/{version}">',
                    remediation="Gunakan plugin untuk menyembunyikan tag meta generator OJS.",
                ))
    except Exception:
        pass
    return version, findings
```

- [ ] **Step 2: Write app/scanners/external/ssl_analyzer.py**

```python
import ssl, socket
from datetime import datetime, timezone
from app.scanners.models import FindingResult, make_finding


def scan_ssl(hostname: str) -> list[FindingResult]:
    findings = []
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.create_connection((hostname, 443), timeout=10),
                              server_hostname=hostname) as s:
            cert = s.getpeercert()
            not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            days = (not_after - datetime.now(timezone.utc)).days
            if days < 0:
                findings.append(make_finding(
                    "ssl_expired", category="external",
                    title="Sertifikat SSL Kedaluwarsa",
                    description=f"SSL {hostname} telah kedaluwarsa.",
                    affected_path=f"https://{hostname}",
                    evidence=f"expired: {cert['notAfter']}",
                    remediation="Perbarui sertifikat SSL segera.",
                ))
            elif days < 30:
                findings.append(make_finding(
                    "ssl_expiring_soon", category="external",
                    title=f"SSL Akan Kedaluwarsa dalam {days} Hari",
                    description="Sertifikat SSL akan segera kedaluwarsa.",
                    affected_path=f"https://{hostname}",
                    evidence=f"days_left={days}",
                    remediation="Perpanjang sertifikat SSL sebelum kedaluwarsa.",
                ))
            tls = s.version()
            if tls in ("TLSv1", "TLSv1.1"):
                findings.append(make_finding(
                    "weak_tls", category="external",
                    title=f"Protokol TLS Lemah: {tls}",
                    description="TLS 1.0/1.1 sudah tidak aman.",
                    affected_path=f"https://{hostname}",
                    evidence=f"tls_version={tls}",
                    remediation="Konfigurasi server untuk TLS 1.2 minimum.",
                ))
    except Exception:
        pass
    return findings
```

- [ ] **Step 3: Write app/scanners/external/header_checker.py**

```python
import httpx
from app.scanners.models import FindingResult, make_finding

REQUIRED = {
    "Content-Security-Policy": (
        "missing_csp", "CSP Tidak Ditemukan",
        "Tambahkan header Content-Security-Policy untuk mencegah XSS.",
        "A03:2021-Injection",
    ),
    "Strict-Transport-Security": (
        "missing_hsts", "HSTS Tidak Ditemukan",
        "Tambahkan: Strict-Transport-Security: max-age=31536000; includeSubDomains",
        "A05:2021",
    ),
    "X-Frame-Options": (
        "missing_x_frame", "X-Frame-Options Tidak Ditemukan",
        "Tambahkan X-Frame-Options: DENY untuk mencegah clickjacking.",
        "A05:2021",
    ),
}


async def scan_headers(url: str) -> list[FindingResult]:
    findings = []
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            resp = await c.head(url)
            present = {k.lower() for k in resp.headers}
            for header, (ftype, title, remediation, owasp) in REQUIRED.items():
                if header.lower() not in present:
                    findings.append(make_finding(
                        ftype, category="external",
                        title=title,
                        description=f"Header {header} tidak ditemukan pada {url}.",
                        affected_path=url,
                        evidence=f"Header {header} tidak ada dalam respons",
                        remediation=remediation,
                        owasp_category=owasp,
                    ))
    except Exception:
        pass
    return findings
```

- [ ] **Step 4: Write tests/test_scanners/test_external_headers.py**

```python
from app.scanners.external.header_checker import REQUIRED

def test_required_headers_defined():
    assert "Content-Security-Policy" in REQUIRED
    assert "Strict-Transport-Security" in REQUIRED

def test_csp_finding_type():
    ftype, _, _, _ = REQUIRED["Content-Security-Policy"]
    assert ftype == "missing_csp"
```

- [ ] **Step 5: Run**

```bash
pytest tests/test_scanners/test_external_headers.py -v
```

Expected: 2 PASSED

- [ ] **Step 6: Commit**

```bash
git add app/scanners/external/fingerprinter.py app/scanners/external/ssl_analyzer.py \
        app/scanners/external/header_checker.py tests/
git commit -m "feat: external scanners - fingerprinter + SSL + headers"
```

---

## Task B6: External — Vuln Prober + Open Dir + CVE Matcher

- [ ] **Step 1: Write app/scanners/external/vuln_prober.py**

```python
import asyncio
import httpx
from app.scanners.models import FindingResult, make_finding

XSS_PAYLOAD = "<script>alert(1)</script>"
SQL_PAYLOAD = "'"


async def scan_vulnerabilities(url: str) -> list[FindingResult]:
    findings = []
    base = url.rstrip("/")
    sem = asyncio.Semaphore(5)

    async def get(path: str, params: dict = None):
        async with sem:
            try:
                async with httpx.AsyncClient(timeout=10, follow_redirects=False) as c:
                    await asyncio.sleep(0.1)
                    return await c.get(f"{base}{path}", params=params)
            except Exception:
                return None

    resp = await get("/index.php/search/search", {"query": XSS_PAYLOAD})
    if resp and XSS_PAYLOAD in (resp.text or ""):
        findings.append(make_finding(
            "reflected_xss", category="external",
            title="Reflected XSS di Halaman Pencarian",
            description="Input direfleksikan tanpa sanitasi.",
            affected_path=f"{base}/index.php/search/search",
            evidence=f"payload={XSS_PAYLOAD!r} ditemukan di respons",
            remediation="Terapkan output encoding pada semua parameter yang direfleksikan.",
            owasp_category="A03:2021-Injection",
        ))

    resp = await get("/index.php/index/search/search", {"query": SQL_PAYLOAD})
    if resp and any(e in (resp.text or "") for e in ["SQL syntax", "mysql_fetch", "ORA-"]):
        findings.append(make_finding(
            "sql_error_exposed", category="external",
            title="Error SQL Terekspos",
            description="Pesan error database terekspos di respons.",
            affected_path=f"{base}/index.php/index/search/search",
            evidence=f"SQL error dengan payload: {SQL_PAYLOAD!r}",
            remediation="Nonaktifkan display_errors di PHP. Implementasi error handling aman.",
            owasp_category="A03:2021-Injection",
        ))

    return findings
```

- [ ] **Step 2: Write app/scanners/external/open_dir_detector.py**

```python
import asyncio
import httpx
from app.scanners.models import FindingResult, make_finding

PATHS = [
    ("/.git/config", "exposed_git", "Repositori Git Terekspos",
     "File .git/config publik mengekspos konfigurasi repositori.",
     "Blokir akses ke .git melalui konfigurasi web server."),
    ("/.env", "exposed_env_file", "File .env Terekspos",
     "File .env berisi variabel sensitif dan publik.",
     "Pindahkan .env ke luar webroot atau blokir via web server."),
    ("/phpinfo.php", "phpinfo_exposed", "phpinfo() Terekspos",
     "phpinfo mengekspos konfigurasi PHP dan server.",
     "Hapus phpinfo.php dari server produksi."),
]


async def scan_open_dirs(url: str) -> list[FindingResult]:
    findings = []
    base = url.rstrip("/")
    sem = asyncio.Semaphore(3)

    async def check(path):
        async with sem:
            try:
                async with httpx.AsyncClient(timeout=10, follow_redirects=False) as c:
                    await asyncio.sleep(0.1)
                    return (await c.get(f"{base}{path}")).status_code
            except Exception:
                return None

    for path, ftype, title, desc, remediation in PATHS:
        if await check(path) == 200:
            findings.append(make_finding(
                ftype, category="external",
                title=title, description=desc,
                affected_path=f"{base}{path}",
                evidence=f"HTTP 200 pada {path}",
                remediation=remediation,
            ))

    return findings
```

- [ ] **Step 3: Write app/scanners/external/cve_matcher.py**

```python
import json
import nvdlib
import redis.asyncio as aioredis
from app.config import get_settings
from app.scanners.models import FindingResult, make_finding

settings = get_settings()


async def lookup_cves(software: str, version: str) -> list[str]:
    key = f"cve_cache:{software}:{version}"
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    cached = await r.get(key)
    if cached:
        await r.aclose()
        return json.loads(cached)
    cve_ids = []
    try:
        results = nvdlib.searchCVE(
            keywordSearch=f"{software} {version}",
            apiKey=settings.cve_api_key or None,
        )
        cve_ids = [r.id for r in results[:10]]
    except Exception:
        pass
    await r.setex(key, 86400, json.dumps(cve_ids))
    await r.aclose()
    return cve_ids


async def scan_cve(ojs_version: str | None) -> list[FindingResult]:
    if not ojs_version:
        return []
    cve_ids = await lookup_cves("OJS Open Journal Systems", ojs_version)
    return [
        make_finding(
            "cve_ojs", category="external",
            title=f"OJS {ojs_version} Rentan {cve_id}",
            description=f"Versi OJS {ojs_version} memiliki kerentanan tercatat di NVD.",
            affected_path="/",
            evidence=f"ojs_version={ojs_version}, cve={cve_id}",
            remediation=f"Update OJS ke versi terbaru. Lihat advisory {cve_id}.",
            cve_id=cve_id,
        )
        for cve_id in cve_ids
    ]
```

- [ ] **Step 4: Commit — Subagent B complete**

```bash
git add app/scanners/external/
git commit -m "feat: external scanners - vuln prober + open dir + CVE matcher — Subagent B complete"
```

---

## POST-PARALLEL TASKS (Sequential)

---

## Task 9: Wire Internal + External Workers

**Files:** `app/workers/internal_bot.py` (replace stub), `app/workers/external_bot.py` (replace stub)

- [ ] **Step 1: Replace app/workers/internal_bot.py**

```python
import asyncio, uuid, json
from datetime import datetime, timezone
from sqlalchemy import select
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models import ScanJob, ScanFinding
from app.scanners.internal.config_scanner import scan_config
from app.scanners.internal.plugin_auditor import scan_plugins
from app.scanners.internal.rbac_auditor import scan_rbac
from app.scanners.internal.file_integrity import scan_file_integrity
from app.scanners.internal.content_detector import scan_content
from app.scanners.internal.db_security import scan_db_security
import redis.asyncio as aioredis
from app.config import get_settings

settings = get_settings()


async def _run_internal_scan(job_id: str, data: dict):
    all_findings = (
        scan_config(data.get("config", {}))
        + scan_plugins(data.get("plugins", []))
        + scan_rbac(data.get("users", []))
        + scan_file_integrity(data.get("file_integrity", {}))
        + scan_content(data.get("articles", []))
        + scan_db_security(data.get("db_config", {}))
    )
    async with AsyncSessionLocal() as session:
        job = (await session.execute(select(ScanJob).where(ScanJob.id == job_id))).scalar_one()
        for f in all_findings:
            session.add(ScanFinding(
                id=uuid.uuid4(), tenant_id=job.tenant_id, job_id=job.id,
                finding_type=f.finding_type, category=f.category, title=f.title,
                description=f.description, affected_path=f.affected_path,
                evidence=f.evidence, remediation=f.remediation,
                severity=f.severity, cvss_score=f.cvss_score,
                cve_id=f.cve_id, owasp_category=f.owasp_category,
            ))
        await session.commit()
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    raw = await r.get(f"scan_progress:{job_id}")
    progress = json.loads(raw) if raw else {}
    progress["internal_done"] = True
    await r.setex(f"scan_progress:{job_id}", 3600, json.dumps(progress))
    await r.aclose()


@celery_app.task(name="app.workers.internal_bot.internal_scan_task",
                 bind=True, max_retries=3, autoretry_for=(Exception,), default_retry_delay=60)
def internal_scan_task(self, job_id: str, target_id: str):
    asyncio.run(_run_internal_scan(job_id, {}))


@celery_app.task(name="app.workers.internal_bot.process_plugin_data_task")
def process_plugin_data_task(job_id: str, data: dict):
    asyncio.run(_run_internal_scan(job_id, data))
```

- [ ] **Step 2: Replace app/workers/external_bot.py**

```python
import asyncio, uuid, json
from sqlalchemy import select
from urllib.parse import urlparse
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models import ScanJob, ScanFinding
from app.scanners.external.fingerprinter import scan_fingerprint
from app.scanners.external.ssl_analyzer import scan_ssl
from app.scanners.external.header_checker import scan_headers
from app.scanners.external.vuln_prober import scan_vulnerabilities
from app.scanners.external.open_dir_detector import scan_open_dirs
from app.scanners.external.cve_matcher import scan_cve
import redis.asyncio as aioredis
from app.config import get_settings

settings = get_settings()


async def _run_external_scan(job_id: str, target_url: str):
    hostname = urlparse(target_url).hostname
    ojs_version, fp = await scan_fingerprint(target_url)
    all_findings = (
        fp
        + (scan_ssl(hostname) if hostname else [])
        + await scan_headers(target_url)
        + await scan_vulnerabilities(target_url)
        + await scan_open_dirs(target_url)
        + await scan_cve(ojs_version)
    )
    async with AsyncSessionLocal() as session:
        job = (await session.execute(select(ScanJob).where(ScanJob.id == job_id))).scalar_one()
        for f in all_findings:
            session.add(ScanFinding(
                id=uuid.uuid4(), tenant_id=job.tenant_id, job_id=job.id,
                finding_type=f.finding_type, category=f.category, title=f.title,
                description=f.description, affected_path=f.affected_path,
                evidence=f.evidence, remediation=f.remediation,
                severity=f.severity, cvss_score=f.cvss_score,
                cve_id=f.cve_id, owasp_category=f.owasp_category,
            ))
        await session.commit()
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    raw = await r.get(f"scan_progress:{job_id}")
    progress = json.loads(raw) if raw else {}
    progress["external_done"] = True
    await r.setex(f"scan_progress:{job_id}", 3600, json.dumps(progress))
    await r.aclose()


@celery_app.task(name="app.workers.external_bot.external_scan_task",
                 bind=True, max_retries=3, autoretry_for=(Exception,), default_retry_delay=60)
def external_scan_task(self, job_id: str, target_url: str):
    asyncio.run(_run_external_scan(job_id, target_url))
```

- [ ] **Step 3: Commit**

```bash
git add app/workers/internal_bot.py app/workers/external_bot.py
git commit -m "feat: wire internal + external Celery workers with scanner modules"
```

---

## Task 10: Scoring Worker + PDF Report

**Files:** `app/workers/scoring.py`, `app/services/report.py`, `app/templates/report.html`, `app/templates/email_critical.html`, `tests/test_scoring.py`

- [ ] **Step 1: Write tests/test_scoring.py (failing)**

```python
from app.workers.scoring import _compute_score, _risk_level

def test_perfect_score(): assert _compute_score(0,0,0,0) == 100.0
def test_one_critical():  assert _compute_score(1,0,0,0) == 70.0
def test_critical_risk():  assert _risk_level(20) == "critical"
def test_low_risk():       assert _risk_level(90) == "low"
```

- [ ] **Step 2: Run (expect FAIL)**

```bash
pytest tests/test_scoring.py -v
```

Expected: FAIL

- [ ] **Step 3: Replace app/workers/scoring.py**

```python
import asyncio, json
from datetime import datetime, timezone
from sqlalchemy import select
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models import ScanJob, ScanFinding
from app.services.report import generate_pdf_report
import redis.asyncio as aioredis
from app.config import get_settings

settings = get_settings()


def _compute_score(crit: int, high: int, med: int, low: int) -> float:
    return max(0.0, 100.0 - (crit*30 + high*15 + med*5 + low*1))


def _risk_level(score: float) -> str:
    if score <= 25: return "critical"
    if score <= 50: return "high"
    if score <= 75: return "medium"
    return "low"


async def _run_scoring(job_id: str):
    async with AsyncSessionLocal() as session:
        job = (await session.execute(select(ScanJob).where(ScanJob.id == job_id))).scalar_one()
        findings = (await session.execute(
            select(ScanFinding).where(ScanFinding.job_id == job_id,
                                      ScanFinding.is_false_positive == False)
        )).scalars().all()

        counts = {s: sum(1 for f in findings if f.severity == s)
                  for s in ("critical","high","medium","low")}
        score = _compute_score(counts["critical"], counts["high"], counts["medium"], counts["low"])

        job.overall_score = score
        job.risk_level = _risk_level(score)
        job.critical_count = counts["critical"]
        job.high_count = counts["high"]
        job.medium_count = counts["medium"]
        job.low_count = counts["low"]
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)

        sorted_findings = sorted(findings, key=lambda f: f.cvss_score, reverse=True)
        await generate_pdf_report(session, job, sorted_findings)
        await session.commit()

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    await r.delete(f"dashboard_stats:{str(job.tenant_id)}")
    raw = await r.get(f"scan_progress:{job_id}")
    progress = json.loads(raw) if raw else {}
    progress["scoring_done"] = True
    await r.setex(f"scan_progress:{job_id}", 3600, json.dumps(progress))
    await r.aclose()

    if counts["critical"] > 0:
        crit_ids = [str(f.id) for f in findings if f.severity == "critical"]
        celery_app.send_task("app.workers.notify.send_critical_alert",
                             args=[job_id, crit_ids], queue="notifications")


@celery_app.task(name="app.workers.scoring.scoring_task",
                 bind=True, max_retries=3, autoretry_for=(Exception,), default_retry_delay=60)
def scoring_task(self, job_id: str):
    asyncio.run(_run_scoring(job_id))
```

- [ ] **Step 4: Run scoring tests**

```bash
pytest tests/test_scoring.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: Write app/services/report.py**

```python
import uuid, os
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
import boto3
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import ScanJob, ScanFinding, OJSTarget, Report
from app.config import get_settings

settings = get_settings()
_jinja = Environment(loader=FileSystemLoader(
    os.path.join(os.path.dirname(__file__), "..", "templates")
))
SEVERITY_LABEL = {"critical": "Kritis", "high": "Berbahaya", "medium": "Perhatian", "low": "Aman"}


def _s3():
    return boto3.client("s3",
        endpoint_url=f"{'https' if settings.minio_use_ssl else 'http'}://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )


async def generate_pdf_report(session: AsyncSession, job: ScanJob, findings: list) -> Report:
    target = (await session.execute(
        select(OJSTarget).where(OJSTarget.id == job.target_id)
    )).scalar_one()
    html = _jinja.get_template("report.html").render(
        job=job, target=target, findings=findings, severity_label=SEVERITY_LABEL,
    )
    pdf = HTML(string=html).write_pdf()
    path = f"{job.tenant_id}/{job.id}/report.pdf"
    _s3().put_object(Bucket=settings.minio_bucket, Key=path,
                     Body=pdf, ContentType="application/pdf")
    report = Report(id=uuid.uuid4(), tenant_id=job.tenant_id, job_id=job.id,
                    format="pdf", storage_path=path, file_size_bytes=len(pdf))
    session.add(report)
    return report
```

- [ ] **Step 6: Write app/templates/report.html**

```html
<!DOCTYPE html>
<html lang="id"><head><meta charset="UTF-8">
<style>
  body{font-family:Arial,sans-serif;font-size:12pt;color:#333}
  h1{color:#1a237e}
  table{width:100%;border-collapse:collapse;margin:1em 0}
  th{background:#1a237e;color:#fff;padding:8px;text-align:left}
  td{padding:6px 8px;border-bottom:1px solid #ddd}
  .critical{color:#d32f2f;font-weight:bold}
  .high{color:#e64a19;font-weight:bold}
  .medium{color:#f57c00}
  .low{color:#388e3c}
</style></head>
<body>
<h1>Laporan Keamanan OJS — {{ target.name }}</h1>
<p><strong>URL:</strong> {{ target.url }} | <strong>Scan:</strong> {{ job.scan_type }}</p>
<p><strong>Skor:</strong> {{ "%.1f"|format(job.overall_score or 0) }}/100 &nbsp;|&nbsp;
   <strong>Risiko:</strong> {{ job.risk_level | upper if job.risk_level else "-" }}</p>
<table><tr><th>Tingkat</th><th>Jumlah</th></tr>
<tr><td class="critical">Kritis</td><td>{{ job.critical_count }}</td></tr>
<tr><td class="high">Berbahaya</td><td>{{ job.high_count }}</td></tr>
<tr><td class="medium">Perhatian</td><td>{{ job.medium_count }}</td></tr>
<tr><td class="low">Aman</td><td>{{ job.low_count }}</td></tr>
</table>
<h2>Detail Temuan</h2>
{% for f in findings %}
<div style="margin-bottom:1.5em;padding:1em;border-left:4px solid
{% if f.severity=='critical' %}#d32f2f{% elif f.severity=='high' %}#e64a19
{% elif f.severity=='medium' %}#f57c00{% else %}#388e3c{% endif %}">
<h3 class="{{ f.severity }}">
  [{{ severity_label[f.severity] }}] {{ f.title }}
</h3>
<p><strong>Deskripsi:</strong> {{ f.description }}</p>
<p><strong>Path:</strong> <code>{{ f.affected_path }}</code></p>
<p><strong>Bukti:</strong> {{ f.evidence }}</p>
<p><strong>Remediasi:</strong> {{ f.remediation }}</p>
{% if f.cve_id %}<p><strong>CVE:</strong> {{ f.cve_id }}</p>{% endif %}
</div>
{% endfor %}
</body></html>
```

- [ ] **Step 7: Write app/templates/email_critical.html**

```html
<!DOCTYPE html>
<html lang="id"><body style="font-family:Arial,sans-serif">
<h2 style="color:#d32f2f">[OJSDef] Ancaman Kritis — {{ target_name }}</h2>
<p><strong>Target:</strong> {{ target_url }}</p>
<p><strong>Skor:</strong> {{ overall_score }}/100 ({{ risk_level | upper }})</p>
<h3>Temuan Kritis:</h3>
<ul>
{% for f in findings[:5] %}<li><strong>{{ f.title }}</strong> — {{ f.remediation }}</li>{% endfor %}
{% if findings|length > 5 %}<li>... dan {{ findings|length - 5 }} temuan lainnya</li>{% endif %}
</ul>
<p><a href="{{ dashboard_url }}">Lihat di Dashboard OJSDef</a></p>
</body></html>
```

- [ ] **Step 8: Commit**

```bash
git add app/workers/scoring.py app/services/report.py app/templates/ tests/test_scoring.py
git commit -m "feat: scoring worker + PDF report (WeasyPrint + MinIO)"
```

---

## Task 11: Notification Worker

**Files:** `app/workers/notify.py`

- [ ] **Step 1: Write app/workers/notify.py**

```python
import asyncio, uuid, os
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
import httpx, aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models import ScanJob, ScanFinding, OJSTarget, User, Notification
from app.config import get_settings

settings = get_settings()
_jinja = Environment(loader=FileSystemLoader(
    os.path.join(os.path.dirname(__file__), "..", "templates")
))


async def _email(to: str, subject: str, html: str) -> bool:
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, settings.smtp_from, to
    msg.attach(MIMEText(html, "html"))
    try:
        await aiosmtplib.send(msg, hostname=settings.smtp_host, port=settings.smtp_port,
                               username=settings.smtp_user, password=settings.smtp_pass,
                               start_tls=True)
        return True
    except Exception:
        return False


async def _telegram(chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(url, json={"chat_id": chat_id, "text": text[:4096]})
            return r.status_code == 200
    except Exception:
        return False


async def _run_critical_alert(job_id: str, finding_ids: list[str]):
    async with AsyncSessionLocal() as session:
        job = (await session.execute(select(ScanJob).where(ScanJob.id == job_id))).scalar_one()
        target = (await session.execute(select(OJSTarget).where(OJSTarget.id == job.target_id))).scalar_one()
        findings = (await session.execute(
            select(ScanFinding).where(ScanFinding.id.in_(finding_ids))
        )).scalars().all()
        users = [u for u in (await session.execute(
            select(User).where(User.tenant_id == job.tenant_id, User.is_active == True)
        )).scalars() if u.notif_email or u.notif_telegram]

        subject = f"[OJSDef] Ancaman Kritis Terdeteksi — {target.name}"
        html_body = _jinja.get_template("email_critical.html").render(
            target_name=target.name, target_url=target.url,
            overall_score=job.overall_score, risk_level=job.risk_level,
            findings=findings,
            dashboard_url=settings.allowed_origins_list[0] + "/dashboard",
        )
        tg_text = (
            f"Ancaman Kritis — {target.name}\n"
            f"Skor: {job.overall_score}/100 ({job.risk_level})\n"
            + "\n".join(f"- {f.title}" for f in findings[:5])
        )

        for user in users:
            if user.notif_email:
                sent = await _email(user.email, subject, html_body)
                session.add(Notification(
                    id=uuid.uuid4(), tenant_id=job.tenant_id, job_id=job.id,
                    user_id=user.id, channel="email", notif_type="critical_alert",
                    is_sent=sent, error_log=None if sent else "SMTP failed",
                ))
            if user.notif_telegram and user.telegram_chat_id:
                sent = await _telegram(user.telegram_chat_id, tg_text)
                session.add(Notification(
                    id=uuid.uuid4(), tenant_id=job.tenant_id, job_id=job.id,
                    user_id=user.id, channel="telegram", notif_type="critical_alert",
                    is_sent=sent, error_log=None if sent else "Telegram API failed",
                ))
        await session.commit()


@celery_app.task(name="app.workers.notify.send_critical_alert",
                 bind=True, max_retries=3, autoretry_for=(Exception,), default_retry_delay=60)
def send_critical_alert(self, job_id: str, finding_ids: list[str]):
    asyncio.run(_run_critical_alert(job_id, finding_ids))
```

- [ ] **Step 2: Commit**

```bash
git add app/workers/notify.py
git commit -m "feat: notification worker (email + telegram, critical alerts)"
```

---

## Task 12: Integration Smoke Test + Seed Verify

- [ ] **Step 1: Build**

```bash
docker compose build --no-cache fastapi
```

Expected: Build completes without error.

- [ ] **Step 2: Start infra**

```bash
docker compose up -d postgres redis minio
```

- [ ] **Step 3: Run migration**

```bash
docker compose run --rm fastapi alembic upgrade head
```

Expected: `Running upgrade  -> 001, initial schema`

- [ ] **Step 4: Run seed**

```bash
docker compose run --rm fastapi python scripts/seed.py
```

Expected:
```
[seed] tenant created: <uuid>
[seed] saas_admin created: admin@ojsdef.com
```

- [ ] **Step 5: Start all services**

```bash
docker compose up -d
```

- [ ] **Step 6: Health check**

```bash
curl http://localhost/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 7: Login smoke test**

```bash
curl -X POST http://localhost/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@ojsdef.com","password":"Admin@OJSDef2026!"}'
```

Expected: JSON with `access_token` and `refresh_token`.

- [ ] **Step 8: Run unit tests**

```bash
docker compose run --rm fastapi pytest tests/ -v --tb=short
```

Expected: All PASSED

- [ ] **Step 9: Final commit**

```bash
git add .
git commit -m "feat: OJSDef backend MVP complete — all phases implemented and verified"
```

---

## Self-Review

**Spec coverage:**
- [x] Phase 1 Docker Compose — Task 1
- [x] Phase 2 App Skeleton — Task 2
- [x] Phase 3 DB Models + Alembic + RLS + indexes — Tasks 3–4
- [x] Phase 4 Auth API (login, refresh, logout, me, change-password) + RBAC — A1–A2
- [x] Phase 5 Targets API (CRUD, verify file+DNS, plugin-guide, regen-key) — A3
- [x] Phase 6 Scans API (start with chain/chord/.si(), list, findings, progress) — A5
- [x] Phase 7 Plugin callback (HMAC + timestamp replay prevention, heartbeat, audit_data) — A4
- [x] Phase 8 Internal scanners (6 modules: config, plugins, rbac, integrity, content, db) — B2–B4
- [x] Phase 8 External scanners (fingerprinter, ssl, headers, vuln, opendir, cve) — B5–B6
- [x] Phase 9 Scoring (formula, risk_level thresholds) + PDF (WeasyPrint/MinIO) — Task 10
- [x] Phase 10 Notifications (email + Telegram, critical alert, notification table) — Task 11
- [x] Dashboard stats + Redis cache (60s TTL, invalidate on scoring) — A6
- [x] Admin router (users + tenants, saas_admin only) — A6
- [x] Seed script (idempotent, saas_admin + default tenant) — Task 4
- [x] `must_change_password` in User model + login response — Task 3, A2
- [x] `.si()` immutable signatures in chord dispatch — Task A5
- [x] NVD CVE cache Redis TTL 24h — Task B6

**Type consistency confirmed:** `FindingResult` fields (finding_type, category, title, description, affected_path, evidence, remediation, cvss_score, severity, cve_id, owasp_category) used consistently in B1–B6 and Tasks 9–10. `ScanFinding` model fields match `FindingResult` field names in worker insert loops.
