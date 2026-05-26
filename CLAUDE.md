# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OJSDef Backend — FastAPI async API + Celery task queue untuk platform keamanan OJS. Backend menerima request dari Next.js dashboard dan callback dari plugin PHP OJS, menjalankan scan, menghitung risk score, dan mengirim notifikasi.

Baca `docs/SRS_OJSDEF.md` untuk arsitektur lengkap, DB schema, dan API spec.

## Commands

```bash
# Setup (pertama kali)
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt

# Development
uvicorn app.main:app --reload --port 8000

# Celery workers (run di terminal terpisah)
celery -A app.celery_app worker -Q internal_scan --concurrency=4 --loglevel=info
celery -A app.celery_app worker -Q external_scan --concurrency=2 --loglevel=info
celery -A app.celery_app worker -Q scoring --concurrency=2 --loglevel=info
celery -A app.celery_app worker -Q notifications --concurrency=4 --loglevel=info

# Database migrations (Alembic)
alembic upgrade head
alembic revision --autogenerate -m "description"

# Celery monitoring
celery -A app.celery_app flower --port=5555
```

## Planned Directory Structure

```
app/
├── main.py                    — FastAPI app entry point
├── celery_app.py              — Celery instance + config
├── config.py                  — Settings via pydantic-settings
├── database.py                — SQLAlchemy async engine + session
├── models/                    — SQLAlchemy ORM models
│   ├── user.py
│   ├── tenant.py
│   ├── ojs_target.py
│   ├── scan_job.py
│   └── scan_finding.py
├── schemas/                   — Pydantic v2 request/response schemas
├── routers/                   — FastAPI route handlers
│   ├── auth.py
│   ├── targets.py
│   ├── scans.py
│   ├── reports.py
│   ├── schedules.py
│   └── plugin_callback.py
├── workers/                   — Celery task definitions
│   ├── internal_bot.py        — Plugin data processor (6 scanner modules)
│   ├── external_bot.py        — Offensive scanner (8 scanner modules)
│   ├── scoring.py             — CVSS calc + PDF generation
│   └── notify.py              — Email + Telegram alerts
├── services/                  — Business logic (auth, RBAC, CVE match)
├── middleware/                — JWT auth + tenant injection
└── migrations/                — Alembic migration files
```

## Tech Stack

- **FastAPI 0.110** + **Uvicorn** (ASGI)
- **SQLAlchemy 2.0 async** + **asyncpg** — ORM dengan PostgreSQL 16
- **Alembic** — database migrations
- **Pydantic v2** — request/response validation di semua endpoint
- **Celery 5** + **Redis 7** — 4 task queues: `internal_scan`, `external_scan`, `scoring`, `notifications`
- **python-jose** — JWT (access token 1h, refresh token 30d)
- **passlib[bcrypt]** — password hashing
- **WeasyPrint + Jinja2** — PDF report generation
- **boto3** — MinIO S3-compatible storage (PDF uploads)
- **aiosmtplib + httpx** — email + Telegram notifications
- **nvdlib** — CVE lookup dari NVD API

## Database

**PostgreSQL 16** dengan Row-Level Security (RLS) untuk multi-tenancy:
- Setiap tabel utama punya `tenant_id`
- FastAPI middleware inject `SET app.current_tenant_id = '<uuid>'` ke setiap session
- RLS policy otomatis memfilter query per tenant

**Redis 7** dual-use: Celery task broker + cache plugin status (TTL 900s).

**MinIO** — object storage S3-compatible untuk PDF reports.

## API Security

Semua endpoint (kecuali auth dan `/plugin/v1/callback`) butuh `Authorization: Bearer <JWT>`.

Plugin callback diautentikasi via HMAC-SHA256 — header `X-OJSDef-Signature: sha256=<hmac_hex>`.

## Celery Workers

| Worker | Queue | Concurrency | Fungsi |
|--------|-------|-------------|--------|
| `worker-internal` | `internal_scan` | 4 | Proses audit data dari plugin PHP |
| `worker-external` | `external_scan` | 2 | Passive offensive scan (max 10 req/s ke target) |
| `worker-scoring` | `scoring` | 2 | CVSS calculation + PDF generation |
| `worker-notify` | `notifications` | 4 | Email + Telegram dispatch |

Scoring worker jalan setelah kedua scan selesai. Temuan Critical otomatis trigger `notifications` queue.

## Environment Variables

```env
DATABASE_URL=postgresql+asyncpg://ojsdef:<password>@localhost:5432/ojsdef
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=<secret>
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=<key>
MINIO_SECRET_KEY=<secret>
CVE_API_KEY=<nvd-api-key>
SENTRY_DSN=<dsn>
SMTP_HOST=<host>
TELEGRAM_BOT_TOKEN=<token>
```

## Current Status

Backend baru diinisialisasi — hanya ada `requirements.txt` dan `venv`. Semua direktori dan file di atas belum dibuat. Mulai dari `app/main.py` dan `app/config.py`.
