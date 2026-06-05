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

# Syntax check semua file Python
python -c "import ast,os; errors=[]; [errors.append(p) or True for r,d,fs in os.walk('app') for f in fs if f.endswith('.py') for p in [os.path.join(r,f)] if not (lambda: ast.parse(open(p).read()) or True)()]; print('OK' if not errors else errors)"
```

## Directory Structure

```
app/
├── main.py                    — FastAPI app entry point
├── celery_app.py              — Celery instance + config
├── config.py                  — Settings via pydantic-settings
├── database.py                — SQLAlchemy async engine + session
├── core/                      — Cross-cutting utilities
│   └── audit.py               — create_audit_log() helper (savepoint-based, silent fail)
├── models/                    — SQLAlchemy ORM models
│   ├── base.py                — Base + TimestampMixin
│   ├── user.py
│   ├── tenant.py
│   ├── ojs_target.py          — OJSTarget (incl. trigger/probe/connection_mode fields)
│   ├── scan_job.py
│   ├── scan_finding.py
│   ├── scan_schedule.py       — Model ada, tapi Celery Beat auto-scan DEFERRED ke Fase 2
│   ├── report.py
│   ├── notification.py
│   └── audit_log.py
├── schemas/                   — Pydantic v2 request/response schemas
│   ├── auth.py, targets.py, scans.py, reports.py, admin.py, user.py
├── routers/                   — FastAPI route handlers
│   ├── auth.py
│   ├── targets.py
│   ├── scans.py
│   ├── reports.py
│   ├── dashboard.py
│   ├── admin.py
│   ├── audit_logs.py          — GET /api/v1/audit-logs (saas_admin only)
│   └── plugin_callback.py     — /plugin/v1/* endpoints (heartbeat, callback, checksums)
├── workers/                   — Celery task definitions
│   ├── internal_bot.py        — Trigger plugin + proses audit data (6 scanner modules)
│   ├── external_bot.py        — Offensive scanner (8 scanner modules)
│   ├── scoring.py             — CVSS calc + PDF generation
│   ├── notify.py              — Email + Telegram alerts
│   ├── tasks.py               — cleanup_stale_pending_jobs periodic task (setiap 5 menit)
│   ├── utils.py               — Shared worker utilities
│   └── diagnostics.py         — Diagnostic helpers untuk internal scan
├── scanners/
│   ├── internal/              — Python-side analysis: config, plugins, rbac, file_integrity, content (5 modul; db_security DEFERRED Fase 2)
│   └── external/              — Passive external scan: ssl, headers, endpoint, open_dir, cve, vuln_prober, fingerprinter, cookie_analyzer (8 modul)
├── services/
│   ├── auth.py, crypto.py, targets.py, report.py
├── middleware/
│   ├── auth.py                — JWT middleware
│   └── plugin_auth.py         — HMAC-SHA256 middleware untuk semua /plugin/v1/* routes
└── migrations/versions/
    ├── 001_initial.py         — Schema awal
    ├── 002_plugin_connection_fields.py — Tambah trigger/probe/connection_mode/pending_scan ke ojs_targets
    ├── 003_audit_log_user_email_nullable_tenant.py — Tambah user_email, buat tenant_id nullable di audit_logs
    └── 004_internal_scan_diagnostics.py — Tambah diagnostic_code/diagnostic_detail ke scan_jobs, force_heartbeat ke ojs_targets
```

## Tech Stack

- **FastAPI 0.110** + **Uvicorn** (ASGI)
- **SQLAlchemy 2.0 async** + **asyncpg** — ORM dengan PostgreSQL 16
- **Alembic** — database migrations
- **Pydantic v2** — request/response validation di semua endpoint
- **Celery 5** + **Redis 7** — 4 task queues: `internal_scan`, `external_scan`, `scoring`, `notifications`
- **python-jose** — JWT (access token 1h, refresh token 30d)
- **passlib[bcrypt]** — password hashing
- **httpx 0.27** — HTTP client async (trigger plugin Direct Mode, probe)
- **WeasyPrint + Jinja2** — PDF report generation
- **boto3** — MinIO S3-compatible storage (PDF uploads)
- **aiosmtplib + httpx** — email + Telegram notifications
- **nvdlib** — CVE lookup dari NVD API

## Database

**PostgreSQL 16** dengan Row-Level Security (RLS) untuk multi-tenancy:
- Setiap tabel utama punya `tenant_id`
- FastAPI middleware inject `SET app.current_tenant_id = '<uuid>'` ke setiap session
- RLS policy otomatis memfilter query per tenant

**Redis 7** dual-use: Celery task broker + cache scan progress (TTL 3600s).

**MinIO** — object storage S3-compatible untuk PDF reports.

### OJSTarget model fields (tabel `ojs_targets`)

| Kolom | Tipe | Keterangan |
|-------|------|-----------|
| `id` | UUID PK | |
| `tenant_id` | UUID FK | |
| `name`, `url` | String | |
| `is_verified` | Boolean | Domain ownership verification |
| `verification_token` | String | Untuk file/DNS verification |
| `plugin_api_key_encrypted` | Text | AES-256-GCM encrypted via `services/crypto.py` |
| `plugin_last_seen` | DateTime TZ | Di-update setiap heartbeat |
| `ojs_version` | String | Di-update dari payload heartbeat |
| `trigger_endpoint` | String | URL plugin `/ojsdef/trigger` (Direct Mode) |
| `probe_endpoint` | String | URL plugin `/ojsdef/probe` (test reachability) |
| `connection_mode` | String | `direct` / `heartbeat` / `unknown` (default) |
| `pending_scan_job_id` | UUID | Job menunggu trigger via heartbeat mode; dikosongkan setelah callback diterima |
| `force_heartbeat` | Boolean | Override connection detection — paksa mode heartbeat |

### ScanJob fields tambahan (dari migration 004)

| Kolom | Tipe | Keterangan |
|-------|------|-----------|
| `diagnostic_code` | String(40) | Kode error singkat jika scan gagal (mis. `plugin_unreachable`, `hmac_error`) |
| `diagnostic_detail` | Text | Pesan error detail untuk debugging |

## Plugin Integration Protocol

### Endpoint `/plugin/v1/*` (semua wajib HMAC-signed)

| Method | Path | Fungsi |
|--------|------|--------|
| `POST` | `/plugin/v1/heartbeat` | Plugin kirim heartbeat tiap 5 menit |
| `POST` | `/plugin/v1/callback` | Plugin kirim hasil scan (`event: audit_data`) → return **202** |
| `GET`  | `/plugin/v1/checksums?version=` | Plugin ambil SHA-256 checksums per OJS version |

### HMAC Authentication (`plugin_auth_middleware`)

```python
# Format pesan yang di-sign — PHP dan Python HARUS identik:
message = timestamp_str.encode() + b"." + body   # contoh: b"1748563200.{...json...}"

# Header yang wajib ada di setiap request:
X-OJSDef-Signature: sha256=<64-char-hex>
X-OJSDef-Timestamp: <unix_timestamp>
X-OJSDef-Target-ID: <target_uuid>
```

- Anti-replay: tolak jika `|now - timestamp| > 300` detik
- API key per-target, dienkripsi AES-256-GCM di DB
- **GET request**: body = `b""` → pesan = `b"<timestamp>."`
- Berlaku dua arah: plugin→backend DAN backend→plugin (trigger/probe request)

### Helper untuk sign request ke plugin (internal_bot.py & plugin_callback.py)

```python
def _sign_for_plugin(api_key: str, body: bytes) -> dict:
    ts = int(time.time())
    message = str(ts).encode() + b"." + body
    sig = "sha256=" + hmac.new(api_key.encode(), message, hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json",
            "X-OJSDef-Signature": sig,
            "X-OJSDef-Timestamp": str(ts)}
```

### Internal Scan Flow

```
POST /api/v1/scans (scan_type=internal/full)
  → ScanJob dibuat (status=queued)
  → Celery: internal_scan_task(job_id, target_id)
      → Set job.status = "running"
      → connection_mode == "direct":
            POST trigger_endpoint (HMAC signed) → plugin respond 202
      → connection_mode == "heartbeat"/"unknown":
            target.pending_scan_job_id = job.id
  → Plugin menerima trigger atau heartbeat scan_requested=true
  → Plugin jalankan 6 scanner → POST /plugin/v1/callback
  → Backend return 202 → Celery: process_plugin_data_task(job_id, data)
  → Findings disimpan → Celery: scoring_task → notifications jika Critical
```

### Heartbeat Response Format (Heartbeat Mode)

```json
{ "status": "ok" }
```
atau, jika ada pending scan:
```json
{ "status": "ok", "scan_requested": true, "job_id": "<uuid>",
  "scan_modules": ["fingerprint","config","plugins","rbac","file_integrity","content"] }
```

## API Security

- Semua endpoint kecuali `/health`, `/docs`, dan `/plugin/v1/*` butuh `Authorization: Bearer <JWT>`
- Plugin endpoints diautentikasi via HMAC-SHA256 (`plugin_auth_middleware`)
- JWT: access token 1h, refresh token 30d
- JWT access token payload sekarang include field `email` untuk audit logging

## Celery Workers

| Worker | Queue | Concurrency | Fungsi |
|--------|-------|-------------|--------|
| `worker-internal` | `internal_scan` | 4 | Trigger plugin + proses audit data |
| `worker-external` | `external_scan` | 2 | Passive offensive scan (max 10 req/s) |
| `worker-scoring` | `scoring` | 2 | CVSS calculation + PDF generation |
| `worker-notify` | `notifications` | 4 | Email + Telegram dispatch |

Scoring worker jalan setelah scan selesai. Temuan Critical otomatis trigger `notifications` queue.

## Deployment Notes (WAJIB baca sebelum deploy)

### Migration setelah update terbaru

```bash
alembic upgrade head
```

Migration terbaru (004): menambah `diagnostic_code`, `diagnostic_detail` di `scan_jobs`, dan `force_heartbeat` di `ojs_targets`.

### Celery Beat

Aktifkan Celery beat scheduler untuk jalankan periodic tasks (cleanup_stale_pending_jobs setiap 5 menit):

```bash
celery -A app.celery_app beat --loglevel=info
```

Atau tambahkan ke docker-compose sebagai service terpisah dengan restart policy.

### UserRole Values

Role yang valid dalam JWT token dan RBAC:
- `admin_ojs` — Pengelola jurnal OJS
- `saas_admin` — Administrator platform OJSDef
- `viewer` — Hanya akses baca-saja

Role lama `it_admin` sudah dihapus; gunakan `admin_ojs` untuk IT teams.

## Environment Variables

```env
DATABASE_URL=postgresql+asyncpg://ojsdef:<password>@localhost:5432/ojsdef
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=<secret-min-32-chars>
JWT_ALGORITHM=HS256
PLUGIN_HMAC_SECRET=<unused-legacy>
PLUGIN_API_KEY_SECRET=<32-byte-hex-for-aes256>
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=<key>
MINIO_SECRET_KEY=<secret>
MINIO_BUCKET=ojsdef-reports
MINIO_USE_SSL=false
SMTP_HOST=<host>
SMTP_PORT=587
SMTP_USER=<user>
SMTP_PASS=<pass>
SMTP_FROM=noreply@ojsdef.com
TELEGRAM_BOT_TOKEN=<token>
CVE_API_KEY=<nvd-api-key>
SENTRY_DSN=<dsn>
ENVIRONMENT=development
ALLOWED_ORIGINS=http://localhost:3000
SEED_ADMIN_EMAIL=admin@ojsdef.com
SEED_ADMIN_PASSWORD=<password>
```
