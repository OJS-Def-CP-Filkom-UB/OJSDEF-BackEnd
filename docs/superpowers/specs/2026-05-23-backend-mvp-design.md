# OJSDef Backend MVP — Design Spec
**Date:** 2026-05-23  
**Status:** Approved  
**Scope:** FastAPI + Celery backend, MVP phase only  
**Reference:** SRS_OJSDEF.md, PRD v1.2

---

## Overview

OJSDef backend adalah FastAPI async API + Celery task queue untuk platform keamanan OJS. Backend menerima request dari Next.js dashboard dan callback dari plugin PHP OJS, menjalankan scan, menghitung risk score, dan mengirim notifikasi.

**Arsitektur:** Layered — Router → Service → Model. Router handle HTTP, Service berisi business logic + Celery dispatch, Model/DB hanya data access.

**Build order:**
1. Docker Compose (infra)
2. App skeleton (main, config, database, celery)
3. DB Models + Alembic migrations
4. Auth API
5. Targets API
6. Scans API + Celery tasks
7. Plugin callback
8. Scanner modules
9. Scoring Engine + PDF
10. Notifications + Dashboard stats

**MVP scope — tidak diimplementasikan:**
- Self-register user (akun dibuat oleh saas_admin)
- Scan scheduling / Celery Beat
- Multi-target subscription tiers
- HTML export format
- Forgot password mandiri (reset oleh saas_admin)

---

## Phase 1: Docker Compose (Infrastructure)

### Services

| Service | Image | Exposed Port | Notes |
|---|---|---|---|
| `fastapi` | Python 3.11-slim (build lokal) | internal :8000 | Uvicorn, reload=off |
| `worker-internal` | Same image | — | `-Q internal_scan --concurrency=4` |
| `worker-external` | Same image | — | `-Q external_scan --concurrency=2` |
| `worker-scoring` | Same image | — | `-Q scoring --concurrency=2` |
| `worker-notify` | Same image | — | `-Q notifications --concurrency=4` |
| `postgres` | postgres:16 | internal :5432 | Volume persist |
| `redis` | redis:7-alpine | internal :6379 | Broker + cache |
| `minio` | minio/minio | internal :9000, :9001 | Bucket `ojsdef-reports` |
| `flower` | Same image | internal :5555 | Celery monitoring |
| `nginx` | nginx:1.25-alpine | **:80, :443** | Reverse proxy |

Satu `Dockerfile` untuk semua Python services — `command` di-override per service di `docker-compose.yml`.

### Nginx Routing
```
/         → fastapi:8000
/flower   → flower:5555  (basic auth protected)
```

### File Structure Infra
```
OJSDEF-BackEnd/
├── Dockerfile
├── docker-compose.yml
├── nginx/
│   └── nginx.conf
├── .env.example
└── .env               (tidak di-commit)
```

### Secrets Management
Semua credentials via `.env` file. `.env.example` di-commit dengan nilai placeholder. `.env` masuk `.gitignore`.

---

## Phase 2: App Skeleton

### File Structure
```
app/
├── main.py
├── config.py
├── database.py
├── celery_app.py
└── middleware/
    ├── auth.py         — JWT decode + tenant injection
    └── plugin_auth.py  — HMAC validation (khusus /plugin/v1/*)
```

### `app/config.py`
Settings via `pydantic-settings`. Single `get_settings()` dengan `@lru_cache`.

Key settings:
```
DATABASE_URL                    — postgresql+asyncpg://...
REDIS_URL                       — redis://redis:6379/0
JWT_SECRET                      — random secret
JWT_ALGORITHM                   — HS256
ACCESS_TOKEN_EXPIRE_MINUTES     — 60
REFRESH_TOKEN_EXPIRE_DAYS       — 30
PLUGIN_HMAC_SECRET              — untuk validasi plugin callback
PLUGIN_API_KEY_SECRET           — AES-256-GCM key untuk encrypt api_key
MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET
SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
TELEGRAM_BOT_TOKEN
CVE_API_KEY
SENTRY_DSN
ENVIRONMENT                     — development | production
SEED_ADMIN_EMAIL                — email saas_admin seed
SEED_ADMIN_PASSWORD             — password saas_admin seed
```

### `app/database.py`
- `AsyncEngine` dengan `asyncpg` driver
- `AsyncSessionLocal` — async session factory
- `get_db()` — FastAPI dependency, inject + auto-close session
- `set_tenant_context(session, tenant_id)` — jalankan `SET app.current_tenant_id = '<uuid>'` agar RLS aktif per-request

### `app/celery_app.py`
- Broker + backend: Redis
- 4 queues: `internal_scan`, `external_scan`, `scoring`, `notifications`
- Task serializer: JSON
- Timezone: `Asia/Jakarta`
- `task_always_eager = False`

### `app/main.py`
- Lifespan handler: test DB connection + create MinIO bucket on startup
- CORS: allow origins dari `ALLOWED_ORIGINS` env (Next.js URL)
- Sentry middleware jika `SENTRY_DSN` tersedia
- Include routers:
  - `/api/v1/auth` — auth router
  - `/api/v1/targets` — targets router
  - `/api/v1/scans` — scans router
  - `/api/v1/reports` — reports router
  - `/api/v1/dashboard` — dashboard router
  - `/api/v1/admin` — admin router (saas_admin only)
  - `/plugin/v1` — plugin callback router
- `GET /health` — no auth, return `{"status": "ok", "db": "ok", "redis": "ok"}`

### `app/middleware/auth.py`
JWT middleware untuk semua request kecuali whitelist:
- Whitelist: `/api/v1/auth/login`, `/api/v1/auth/refresh`, `/plugin/v1/*`, `/health`, `/docs`, `/openapi.json`
- Decode JWT → inject `request.state.user` + `request.state.tenant_id`
- Jalankan `set_tenant_context()` agar RLS PostgreSQL aktif

---

## Phase 3: DB Models + Alembic Migrations

### File Structure
```
app/models/
├── __init__.py      — export semua model (Alembic autodiscover)
├── base.py          — Base declarative + TimestampMixin
├── tenant.py
├── user.py
├── ojs_target.py
├── scan_job.py
├── scan_finding.py
├── scan_schedule.py — ada di model, tidak dipakai MVP
├── report.py
├── notification.py
└── audit_log.py

migrations/
├── env.py           — async SQLAlchemy config
├── script.py.mako
└── versions/
    └── 001_initial.py — semua tabel + indexes + RLS policies
```

### Enums
Semua enum sebagai Python `enum.Enum` (bukan PostgreSQL enum type) — disimpan sebagai `String` di DB, lebih mudah dimigrasikan.

| Model | Enums |
|---|---|
| User | `Role: admin_ojs\|it_admin\|saas_admin` + field `must_change_password: bool` (default False, True saat saas_admin create user) |
| ScanJob | `ScanType: internal\|external\|full`, `ScanStatus: queued\|running\|completed\|failed`, `RiskLevel: low\|medium\|high\|critical` |
| ScanFinding | `FindingCategory: internal\|external`, `Severity: low\|medium\|high\|critical` |
| Report | `ReportFormat: pdf\|json` |
| Notification | `NotifChannel: email\|telegram`, `NotifType: critical_alert\|scan_summary` |

### RLS Tables
Tabel berikut di-enable RLS + create policy `tenant_isolation`:
`users`, `ojs_targets`, `scan_jobs`, `scan_findings`, `scan_schedules`, `reports`, `notifications`, `audit_logs`

Tabel `tenants` tidak di-RLS (saas_admin akses global).

RLS policy template:
```sql
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON {table}
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
```

### Indexes
```sql
idx_scan_jobs_target_id          — scan_jobs(target_id)
idx_scan_jobs_status             — scan_jobs(status)
idx_scan_findings_job_id         — scan_findings(job_id)
idx_scan_findings_severity       — scan_findings(severity)
idx_users_tenant_id              — users(tenant_id)
idx_ojs_targets_tenant_id        — ojs_targets(tenant_id)
idx_scan_jobs_active             — scan_jobs(target_id, created_at) WHERE status IN ('queued','running')
idx_findings_title_fts           — GIN(to_tsvector('english', title || ' ' || description))
```

### `app/services/crypto.py`
- `encrypt_api_key(plaintext: str) -> str` — AES-256-GCM, key dari `PLUGIN_API_KEY_SECRET`
- `decrypt_api_key(ciphertext: str) -> str`
- Dipakai oleh Target service untuk `plugin_api_key` column

### Seed Script
`scripts/seed.py`:
1. Create tenant default (`name: "OJSDef Default"`, `slug: "default"`)
2. Create user `saas_admin` dengan `SEED_ADMIN_EMAIL` + `SEED_ADMIN_PASSWORD` dari env
3. Idempotent — tidak error jika dijalankan ulang

---

## Phase 4: Auth API

### Endpoints

```
POST /api/v1/auth/login           — email + password → access_token + refresh_token
POST /api/v1/auth/refresh         — refresh_token → access_token baru
POST /api/v1/auth/logout          — blacklist refresh_token di Redis
GET  /api/v1/auth/me              — profile user yang sedang login
PUT  /api/v1/auth/me              — update full_name, notif_email, notif_telegram, telegram_chat_id
PUT  /api/v1/auth/change-password — verifikasi password lama, set password baru

# SaaS Admin only
POST   /api/v1/admin/users        — create user baru (email, password, role, tenant_id)
GET    /api/v1/admin/users        — list semua users lintas tenant
PATCH  /api/v1/admin/users/:id    — update user (active/inactive, role)
DELETE /api/v1/admin/users/:id    — delete user

POST   /api/v1/admin/tenants      — create tenant baru
GET    /api/v1/admin/tenants      — list semua tenants
PATCH  /api/v1/admin/tenants/:id  — update (suspend/activate)
DELETE /api/v1/admin/tenants/:id  — delete tenant + cascade semua data
```

Endpoint `/auth/register`, `/auth/verify-email`, `/auth/forgot-password`, `/auth/reset-password` **tidak diimplementasikan di MVP**.

### Token Strategy
- `access_token`: JWT HS256, TTL 60 menit, payload: `{sub: user_id, tenant_id, role, jti, exp}`
- `refresh_token`: JWT HS256, TTL 30 hari, disimpan di Redis sebagai `refresh:{user_id}:{jti}` dengan TTL sama
- `logout`: hapus key Redis `refresh:{user_id}:{jti}` (soft blacklist)
- `change-password`: hapus semua key `refresh:{user_id}:*` (invalidate semua session)

### RBAC Dependencies
```python
get_current_user()                        — any authenticated user
require_role("saas_admin")               — specific single role
require_any_role("it_admin", "saas_admin") — multiple roles
```

Dipakai di router sebagai `Depends(require_role("saas_admin"))`.

### Password Policy
- Saat saas_admin create user: generate random password 12 karakter → kirim via email
- User baru punya flag `must_change_password = True` → prompt ganti saat login pertama
- `change-password` set `must_change_password = False`

### `app/services/auth.py`
`authenticate_user()`, `create_tokens()`, `refresh_access_token()`, `revoke_refresh_token()`, `hash_password()`, `verify_password()`, `send_welcome_email()`

---

## Phase 5: Targets API

### Endpoints

```
GET    /api/v1/targets                   — list targets milik tenant
POST   /api/v1/targets                   — tambah target baru
GET    /api/v1/targets/:id               — detail target + plugin status
PUT    /api/v1/targets/:id               — update nama
DELETE /api/v1/targets/:id               — hapus target + cascade scan history

POST   /api/v1/targets/:id/verify        — trigger verifikasi domain
GET    /api/v1/targets/:id/verify-status — cek status verifikasi (polling)
GET    /api/v1/targets/:id/plugin-guide  — return API key + instruksi instalasi
POST   /api/v1/targets/:id/regenerate-key — regenerate plugin_api_key
```

### Domain Verification Flow
1. `POST /targets` → generate `verification_token` (random hex 16 byte) → simpan ke DB → return instruksi dua metode
2. **File method**: user upload `ojsdef-verify-{token}.txt` ke root OJS → isi: `ojsdef-verification={token}`
3. **DNS method**: user tambah TXT record `ojsdef-verify={token}` ke domain
4. `POST /targets/:id/verify` → coba file method (GET request, timeout 10s) → jika gagal, coba DNS TXT lookup via `dnspython` → jika berhasil → `is_verified = True`
5. Verifikasi dilakukan **synchronous** di request handler — tidak perlu Celery

### Plugin Status Tracking
- Plugin kirim heartbeat via `POST /plugin/v1/callback` dengan `event: "heartbeat"` setiap 5 menit
- Backend update `ojs_targets.plugin_last_seen = now()`
- Status dihitung **saat read** (bukan disimpan):
  - `plugin_last_seen < 15 menit` → `plugin_connected: true`
  - `plugin_last_seen ≥ 15 menit` atau `null` → `plugin_connected: false`

### `app/services/targets.py`
`create_target()`, `verify_domain_file()`, `verify_domain_dns()`, `get_plugin_guide()`, `regenerate_api_key()`, `compute_plugin_status()`

---

## Phase 6: Scans API + Celery Tasks

### Endpoints

```
POST   /api/v1/scans                     — jalankan scan baru
GET    /api/v1/scans                     — list scan history (?target_id, ?status, ?limit)
GET    /api/v1/scans/:id                 — detail scan + findings summary + progress
GET    /api/v1/scans/:id/findings        — findings dengan pagination (?severity, ?category, ?page)
PATCH  /api/v1/scans/:id/findings/:fid   — mark/unmark false positive
DELETE /api/v1/scans/:id                 — hapus scan record (it_admin, saas_admin only)

GET    /api/v1/dashboard/stats           — aggregated stats last 30 days
```

### Scan Dispatch Logic
`POST /api/v1/scans` validasi `target.is_verified == True` terlebih dahulu, lalu:

```python
"internal" → chain(internal_scan_task.si(job_id), scoring_task.si(job_id))
"external" → chain(external_scan_task.si(job_id), scoring_task.si(job_id))
"full"     → chord([internal_scan_task.si(job_id), external_scan_task.si(job_id)], scoring_task.si(job_id))
# Pakai .si() (immutable) bukan .s() agar scoring_task tidak menerima results list dari chord sebagai argument
```

### Celery Task Structure
```
app/workers/
├── internal_bot.py   — internal_scan_task(job_id, target_id)
├── external_bot.py   — external_scan_task(job_id, target_url)
├── scoring.py        — scoring_task(job_id)
└── notify.py         — send_critical_alert(job_id, finding_ids)
                        send_scan_summary(job_id)
```

### Task Error Handling
- `autoretry_for=(Exception,)`, `max_retries=3`, `countdown=60` (exponential di retry ke-N: 60s, 120s, 240s)
- Semua retry gagal → UPDATE `scan_jobs.status = "failed"` + `error_message`
- Scan `status=running` lebih dari 30 menit → ditandai `failed` oleh `/health` endpoint check

### Progress Tracking
Progress disimpan di Redis key `scan_progress:{job_id}` (TTL 1 jam):
```json
{ "internal_done": false, "external_done": true, "scoring_done": false }
```
Worker update Redis setiap fase selesai. `GET /scans/:id` include field `progress` dari Redis.

### Dashboard Stats
- Endpoint: `GET /api/v1/dashboard/stats`
- Di-cache Redis key `dashboard_stats:{tenant_id}` TTL 60 detik
- Cache invalidated saat scan baru selesai (scoring_task update cache)
- Response sesuai SRS Section 8.7: targets summary, scans summary, security_posture, findings_summary
- `score_trend`: selisih average score bulan ini vs bulan lalu (string `"+12.5"` atau `"-5.3"`)

---

## Phase 7: Plugin Callback

### Endpoint
```
POST /plugin/v1/callback
```
Tidak butuh JWT. Diautentikasi via HMAC-SHA256. Middleware `plugin_auth.py` aktif hanya untuk path `/plugin/v1/*`.

### Validasi Request (urutan wajib)
```
Headers:
  X-OJSDef-Signature : "sha256=<hmac_hex>"
  X-OJSDef-Target-ID : "<target_uuid>"
  X-OJSDef-Timestamp : "<unix_timestamp>"

Langkah validasi:
1. Timestamp ±5 menit dari server time (replay attack prevention)
2. Lookup target by X-OJSDef-Target-ID → ambil plugin_api_key (decrypt)
3. Hitung HMAC-SHA256(key=plugin_api_key, msg=raw_request_body)
4. Compare dengan X-OJSDef-Signature via hmac.compare_digest (constant-time)
5. Jika invalid → 401, tanpa detail pesan
```

### Event Types

| Event | Action |
|---|---|
| `heartbeat` | UPDATE `ojs_targets.plugin_last_seen = now()`. Return 200. |
| `audit_data` | Validasi `job_id` exists + status=`running`. Enqueue `process_plugin_data_task` ke queue `internal_scan`. Return 202. |

### Response
```json
// audit_data success
{ "status": "received", "queued": true }

// heartbeat success
{ "status": "ok" }

// auth failure
{ "detail": "Unauthorized" }   // HTTP 401
```

---

## Phase 8: Scanner Modules

### Architecture
Scanner modules adalah **pure Python functions** — tidak ada FastAPI dependency, tidak ada DB calls langsung. Setiap modul menerima input dari payload plugin atau HTTP target, return `list[FindingResult]`. Worker yang insert ke DB.

### Shared Data Model (`app/scanners/models.py`)
```python
@dataclass
class FindingResult:
    finding_type: str
    category: str          # "internal" | "external"
    title: str
    description: str
    affected_path: str
    evidence: str
    remediation: str       # Bahasa Indonesia
    cvss_score: float      # pre-assigned per finding_type
    cve_id: str | None
    owasp_category: str | None
```

CVSS scores **pre-assigned per `finding_type`** via dict konstanta — tidak dihitung dynamic dari formula CVSS. Trade-off disengaja untuk MVP: akurasi cukup, kompleksitas rendah.

### File Structure
```
app/scanners/
├── models.py
├── internal/
│   ├── config_scanner.py    — scan config.inc.php payload
│   ├── plugin_auditor.py    — outdated/CVE/disabled plugins
│   ├── rbac_auditor.py      — privilege excess, inactive admins
│   ├── file_integrity.py    — modified/unknown/missing files
│   ├── content_detector.py  — regex judi/iframe/redirect di articles
│   └── db_security.py       — weak DB credentials, exposed backup
└── external/
    ├── fingerprinter.py     — OJS version dari headers/meta tags
    ├── ssl_analyzer.py      — cert expiry, cipher, TLS version
    ├── header_checker.py    — CSP, X-Frame-Options, HSTS, dll
    ├── vuln_prober.py       — reflected XSS, SQL error, path traversal
    ├── open_dir_detector.py — /.git/, /.env, /backup/, phpinfo.php
    └── cve_matcher.py       — OJS + plugin version vs NVD CVE API
```

### Internal Scanner Inputs (dari plugin payload `data.*`)
| Modul | Input field |
|---|---|
| `config_scanner` | `data.config` dict |
| `plugin_auditor` | `data.plugins` list |
| `rbac_auditor` | `data.users` list |
| `file_integrity` | `data.file_integrity` dict |
| `content_detector` | `data.articles` list |
| `db_security` | `data.db_config` dict |

### External Scanner Notes
- Semua request via `httpx.AsyncClient` dengan timeout 10s
- Rate limiting: `asyncio.Semaphore` + `asyncio.sleep` untuk jaga ≤10 req/s ke target
- `cve_matcher`: cache hasil NVD lookup di Redis TTL 24 jam untuk menghindari rate limit NVD API

---

## Phase 9: Scoring Engine + PDF Report

### Scoring Logic (`app/workers/scoring.py`)
```
1. SELECT semua findings WHERE job_id = :job_id
2. Hitung overall_score:
   formula: max(0, 100 - Σ(weight × count))
   weight:  Critical=30, High=15, Medium=5, Low=1
3. Tentukan risk_level dari overall_score:
   0–25   → "critical"
   26–50  → "high"
   51–75  → "medium"
   76–100 → "low"
4. Hitung count per severity
5. UPDATE scan_jobs (status=completed, overall_score, risk_level, *_count)
6. Sort findings by cvss_score DESC → action plan order
7. Render PDF → upload MinIO → INSERT reports table
8. Jika critical_count > 0 → dispatch send_critical_alert ke queue notifications
```

### PDF Generation (`app/services/report.py`)
- WeasyPrint + Jinja2 template di `app/templates/report.html`
- CSS inline di HTML (WeasyPrint requirement)
- Upload ke MinIO: path `{tenant_id}/{job_id}/report.pdf`
- DB simpan path relatif, bukan presigned URL
- `GET /api/v1/reports/:id/pdf` → generate presigned URL MinIO TTL 1 jam → redirect

**Isi laporan PDF:**
- Cover: nama institusi, URL target, tanggal scan, overall score + label warna
- Executive summary: 1 paragraf dari template string (bukan AI-generated)
- Tabel findings dikelompokkan: Kritis → Berbahaya → Perhatian → Aman
- Per finding: judul, deskripsi, evidence, langkah remediasi (Bahasa Indonesia)
- Attack surface summary: endpoint count, plugin count, SSL status

### JSON Export
`GET /api/v1/reports/:id/json` → query langsung dari DB, return structured JSON. Tidak ada file yang di-generate.

### Template Files
```
app/templates/
├── report.html          — full PDF template
├── report_style.css     — embedded ke report.html saat render
└── email_critical.html  — template email critical alert
```

---

## Phase 10: Notifications + Dashboard Stats

### Notification Worker (`app/workers/notify.py`)

**`send_critical_alert(job_id, finding_ids)`** — queue `notifications`:
1. Fetch scan job + target + findings dari DB
2. Fetch semua users di tenant dengan `notif_email=True` atau `notif_telegram=True`
3. **Email** via `aiosmtplib`: render `email_critical.html` → send per user
4. **Telegram** via `httpx` POST ke `api.telegram.org/bot{token}/sendMessage`
5. INSERT `notifications` table (1 row per user per channel, `is_sent=True/False`)
6. Kirim gagal → catat `error_log`, retry 3x — worker tidak crash

**`send_scan_summary(job_id)`** — P2, hanya email, dispatch setelah scoring selesai

### Email Content (Critical Alert)
```
Subject : [OJSDef] Ancaman Kritis Terdeteksi — {target_name}
Body    :
  - Nama target + URL
  - Overall score + risk level label
  - List critical findings (max 5, sisanya "dan N temuan lainnya")
  - Langkah mitigasi segera (dari finding.remediation)
  - Link ke dashboard
```

### Telegram Content
Versi ringkas plain text dengan emoji severity, max 4096 karakter (Telegram API limit).

### Dashboard Stats Cache
- Redis key: `dashboard_stats:{tenant_id}`, TTL 60 detik
- Invalidated saat `scoring_task` selesai update scan_jobs
- Cold miss: query PostgreSQL, simpan ke Redis, return

---

## Keputusan Desain Penting

| Keputusan | Pilihan | Alasan |
|---|---|---|
| CVSS scoring | Pre-assigned per finding_type | Formula CVSS penuh terlalu kompleks untuk MVP tanpa akurasi yang jauh lebih baik |
| Plugin status | Dihitung saat read, tidak disimpan | Mencegah stale data; menghindari background job tambahan |
| Domain verification | Synchronous di request handler | Operasi sederhana ≤10s, tidak perlu queue overhead |
| Refresh token | Disimpan di Redis, bukan DB | Lebih cepat untuk lookup + invalidate; tidak perlu migration jika struktur berubah |
| Enum type | Python enum + String column | Lebih mudah dimigrasikan dibanding PostgreSQL native enum |
| PDF URL | Path relatif di DB, presigned saat request | Presigned URL punya TTL — tidak cocok disimpan permanen |
| NVD cache | Redis TTL 24 jam | NVD API punya rate limit; data CVE tidak berubah dalam hitungan jam |
