# Scan Flow Bugfix Design
**Tanggal**: 2026-06-02  
**Status**: Approved  
**Scope**: OJSDEF-BackEnd

---

## Latar Belakang

Saat menjalankan scan penuh (internal + eksternal) dengan semua syarat terpenuhi (domain terverifikasi, plugin terhubung), ditemukan 4 bug yang saling terkait menyebabkan scan tidak pernah selesai dan status job stuck selamanya.

---

## Bug yang Diperbaiki

| # | Bug | Lokasi | Dampak |
|---|-----|--------|--------|
| 1 | Migrations tidak otomatis dijalankan saat container start | `docker-compose.yml` | `relation "ojs_targets" does not exist` pada awal startup |
| 2 | Asyncio event loop conflict di Celery workers | `workers/*.py`, `database.py` | `RuntimeError: Future attached to a different loop` — semua workers gagal dan retry loop tanpa henti |
| 3 | Race condition chord: scoring dipicu sebelum plugin callback tiba | `routers/scans.py` | Scoring hanya menghitung external findings, internal findings tidak masuk |
| 4 | Scan status stuck selamanya | Konsekuensi bug #2 + #3 | UI polling selamanya, job tidak pernah `completed` |

---

## Desain Perbaikan

### Fix 1 — Auto-run Migrations + Seed saat Container Start

**File**: `docker-compose.yml`

Tambah `alembic upgrade head && python scripts/seed.py` ke entrypoint FastAPI sebelum uvicorn start:

```yaml
command: >
  sh -c "alembic upgrade head && python scripts/seed.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"
```

- Migration bersifat idempotent — Alembic skip jika sudah terapply
- Seed bersifat idempotent — `scripts/seed.py` cek keberadaan admin sebelum insert
- Overhead startup ~1-2 detik, acceptable untuk production restart

---

### Fix 2 — Async Engine Isolation per Celery Task

**Root cause**: `AsyncSessionLocal` dibuat satu kali di module level (`app/database.py`). Celery prefork worker membuat proses baru untuk setiap task. `asyncio.run()` membuat event loop baru per task call, tapi connection pool lama masih terikat ke event loop yang sudah closed.

**File**: `app/database.py`

Tambah context manager `make_worker_session()` yang membuat engine fresh dengan `pool_size=1` setiap dipanggil:

```python
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

@asynccontextmanager
async def make_worker_session():
    engine = create_async_engine(
        settings.database_url,
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
    )
    SessionLocal = async_sessionmaker(
        engine, class_=AsyncSession,
        expire_on_commit=False, autoflush=False,
    )
    try:
        async with SessionLocal() as session:
            yield session
    finally:
        await engine.dispose()
```

Semua worker files (`workers/scoring.py`, `workers/external_bot.py`, `workers/internal_bot.py`) ganti semua `async with AsyncSessionLocal()` menjadi `async with make_worker_session()`.

**Resource impact**: Dengan total concurrency 12 slots (4+2+2+4), maksimal 12 koneksi DB aktif. PostgreSQL default max_connections=100 — jauh di bawah batas. Memory overhead per engine dengan `pool_size=1` dapat diabaikan di VPS 2vCPU/4GB RAM.

---

### Fix 3 — Redesign Scan Orchestration (Race Condition)

**Root cause**: `chord([internal, external], scoring)` memicu scoring segera setelah `internal_scan_task` return (~0.08 detik — hanya trigger plugin). Data internal baru tiba menit kemudian via plugin callback. Scoring jalan dengan findings yang belum lengkap.

#### 3a — File baru: `app/workers/utils.py`

Helper `_try_trigger_scoring()` dipanggil oleh kedua workers setelah menyimpan findings. Menggunakan Redis `SET NX` untuk memastikan scoring hanya dipanggil tepat sekali:

```python
import json
import redis.asyncio as aioredis
from app.celery_app import celery_app
from app.config import get_settings

settings = get_settings()

async def _try_trigger_scoring(job_id: str) -> None:
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        progress = json.loads(await r.get(f"scan_progress:{job_id}") or "{}")
        scan_type = progress.get("scan_type", "external")
        ext = progress.get("external_done", False)
        itn = progress.get("internal_done", False)

        ready = (
            (scan_type == "external" and ext) or
            (scan_type == "internal" and itn) or
            (scan_type == "full" and ext and itn)
        )
        if ready:
            acquired = await r.set(
                f"scoring_triggered:{job_id}", "1", nx=True, ex=3600
            )
            if acquired:
                celery_app.send_task(
                    "app.workers.scoring.scoring_task",
                    args=[job_id], queue="scoring",
                )
    finally:
        await r.aclose()
```

#### 3b — `app/routers/scans.py`

Hapus `chain` / `chord`. Fire tasks secara independen. Set `job.status = "running"` langsung di endpoint. Inisialisasi Redis progress dengan `scan_type`:

```python
# Inisialisasi progress dengan scan_type
r = aioredis.from_url(settings.redis_url, decode_responses=True)
await r.setex(f"scan_progress:{job_id}", 3600, json.dumps({
    "scan_type": body.scan_type,
    "external_done": False,
    "internal_done": False,
}))
await r.aclose()

# Set status running segera
job.status = "running"
await db.commit()

# Fire tasks independen (tidak pakai chain/chord)
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
```

#### 3c — `app/workers/external_bot.py`

Setelah simpan findings dan update Redis:

```python
progress["external_done"] = True
await r.setex(f"scan_progress:{job_id}", 3600, json.dumps(progress))
await r.aclose()
await _try_trigger_scoring(job_id)
```

#### 3d — `app/workers/internal_bot.py` (fungsi `_run_internal_scan`)

Setelah simpan findings dari plugin callback:

```python
progress["internal_done"] = True
await r.setex(f"scan_progress:{job_id}", 3600, json.dumps(progress))
await r.aclose()
await _try_trigger_scoring(job_id)
```

`_setup_internal_scan` tidak diubah — tugasnya hanya trigger plugin, tidak menyimpan findings.

---

## Flow Akhir Setelah Fix

### Internal Scan
```
POST /api/v1/scans (internal)
  → ScanJob (status=running) + Redis{scan_type:"internal", internal_done:false}
  → internal_scan_task → trigger plugin (direct/heartbeat)
  → plugin POST /plugin/v1/callback
  → process_plugin_data_task → simpan findings → internal_done=true
  → _try_trigger_scoring → SET NX ok → scoring_task
  → scoring_task → hitung skor → job.status=completed
```

### External Scan
```
POST /api/v1/scans (external)
  → ScanJob (status=running) + Redis{scan_type:"external", external_done:false}
  → external_scan_task → jalankan scanner → simpan findings → external_done=true
  → _try_trigger_scoring → SET NX ok → scoring_task
  → scoring_task → hitung skor → job.status=completed
```

### Full Scan
```
POST /api/v1/scans (full)
  → ScanJob (status=running) + Redis{scan_type:"full", external_done:false, internal_done:false}
  → [parallel] internal_scan_task + external_scan_task

  external_scan_task selesai:
    → external_done=true → cek internal_done? false → skip

  plugin callback tiba → process_plugin_data_task:
    → internal_done=true → cek external_done? true → SET NX → scoring_task

  scoring_task → hitung skor dari ALL findings → job.status=completed
```

Redis `SET NX` menjamin scoring hanya dipanggil sekali meskipun kedua events hampir bersamaan.

---

## File yang Diubah

| File | Perubahan |
|------|-----------|
| `docker-compose.yml` | Tambah migration + seed ke entrypoint FastAPI |
| `scripts/seed.py` | Pastikan idempotent (cek sebelum insert) |
| `app/database.py` | Tambah `make_worker_session()` context manager |
| `app/workers/utils.py` | **Baru** — `_try_trigger_scoring()` helper |
| `app/workers/scoring.py` | Ganti `AsyncSessionLocal` → `make_worker_session()` |
| `app/workers/external_bot.py` | Ganti session, tambah `_try_trigger_scoring()` call |
| `app/workers/internal_bot.py` | Ganti session, tambah `_try_trigger_scoring()` call, hapus `job.status="running"` (dipindah ke router) |
| `app/routers/scans.py` | Hapus chain/chord, inisialisasi Redis progress, set `job.status="running"` |

---

## Yang Tidak Diubah

- Logika scanner (internal + eksternal)
- HMAC authentication middleware
- Schema database (tidak ada migration baru)
- Plugin callback handler (`plugin_callback.py`)
- API contract (semua endpoint tetap sama)
