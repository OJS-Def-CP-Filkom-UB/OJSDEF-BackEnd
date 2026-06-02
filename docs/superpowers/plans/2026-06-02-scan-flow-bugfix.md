# Scan Flow Bugfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Perbaiki 4 bug pada scan flow backend OJSDef sehingga scan internal, eksternal, dan full dapat selesai dengan status `completed` secara konsisten.

**Architecture:** (1) Tambah `make_worker_session()` di `app/database.py` yang membuat fresh async engine per Celery task untuk menghindari event loop conflict. (2) Buat `app/workers/utils.py` dengan `_try_trigger_scoring()` yang menggunakan Redis SET NX sebagai exactly-once gate. (3) Hapus `chain`/`chord` di `scans.py` — ganti dengan fire tasks independen + Redis progress tracking sebagai koordinator scoring.

**Tech Stack:** FastAPI 0.110, SQLAlchemy 2.0 async + asyncpg, Celery 5.3.6, Redis 7, pytest 8.1.1 + pytest-asyncio 0.23.5

**Spec:** `docs/superpowers/specs/2026-06-02-scan-flow-bugfix-design.md`

---

## File Map

| File | Status | Perubahan |
|------|--------|-----------|
| `app/database.py` | Modify | Tambah `make_worker_session()` context manager |
| `app/workers/utils.py` | **Create** | `_try_trigger_scoring()` helper baru |
| `app/workers/scoring.py` | Modify | Ganti `AsyncSessionLocal` → `make_worker_session()` |
| `app/workers/external_bot.py` | Modify | Ganti session + tambah `_try_trigger_scoring()` call |
| `app/workers/internal_bot.py` | Modify | Ganti session + tambah trigger + hapus `job.status="running"` |
| `app/routers/scans.py` | Modify | Hapus chain/chord + init Redis progress + set status running |
| `docker-compose.yml` | Modify | Tambah migration + seed ke entrypoint FastAPI |
| `tests/test_database.py` | **Create** | Unit test `make_worker_session` |
| `tests/test_worker_utils.py` | **Create** | Unit test `_try_trigger_scoring` (5 kasus) |

---

## Task 1: `app/database.py` — Tambah `make_worker_session()`

**Files:**
- Modify: `app/database.py`
- Create: `tests/test_database.py`

- [ ] **Step 1.1: Tulis failing test**

  Buat file `tests/test_database.py`:

  ```python
  import pytest
  from unittest.mock import AsyncMock, MagicMock, patch


  @pytest.mark.asyncio
  async def test_make_worker_session_yields_session_and_disposes_engine():
      """make_worker_session harus yield session dan panggil engine.dispose() setelah blok selesai."""
      mock_engine = MagicMock()
      mock_engine.dispose = AsyncMock()

      mock_session = AsyncMock()
      mock_cm = AsyncMock()
      mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
      mock_cm.__aexit__ = AsyncMock(return_value=False)
      mock_session_local = MagicMock(return_value=mock_cm)

      with patch("app.database.create_async_engine", return_value=mock_engine), \
           patch("app.database.async_sessionmaker", return_value=mock_session_local):
          from app.database import make_worker_session
          async with make_worker_session() as s:
              assert s is mock_session

      mock_engine.dispose.assert_called_once()


  @pytest.mark.asyncio
  async def test_make_worker_session_disposes_on_exception():
      """engine.dispose() harus tetap dipanggil meskipun blok raise exception."""
      mock_engine = MagicMock()
      mock_engine.dispose = AsyncMock()

      mock_session = AsyncMock()
      mock_cm = AsyncMock()
      mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
      mock_cm.__aexit__ = AsyncMock(return_value=False)
      mock_session_local = MagicMock(return_value=mock_cm)

      with patch("app.database.create_async_engine", return_value=mock_engine), \
           patch("app.database.async_sessionmaker", return_value=mock_session_local):
          from app.database import make_worker_session
          with pytest.raises(RuntimeError):
              async with make_worker_session() as s:
                  raise RuntimeError("simulasi error di dalam task")

      mock_engine.dispose.assert_called_once()
  ```

- [ ] **Step 1.2: Jalankan test — pastikan FAIL**

  ```bash
  cd ~/OJSDEF-BackEnd && python -m pytest tests/test_database.py -v
  ```

  Expected: `ImportError: cannot import name 'make_worker_session' from 'app.database'`

- [ ] **Step 1.3: Implementasi `make_worker_session()` di `app/database.py`**

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

  engine = create_async_engine(
      settings.database_url,
      echo=settings.environment == "development",
      pool_pre_ping=True,
  )

  AsyncSessionLocal = async_sessionmaker(
      engine, class_=AsyncSession,
      expire_on_commit=False, autoflush=False,
  )


  @asynccontextmanager
  async def make_worker_session():
      """Buat fresh async engine + session untuk Celery task.

      Mencegah RuntimeError 'Future attached to a different loop' yang terjadi
      saat engine module-level dipakai ulang lintas asyncio.run() calls di
      Celery prefork workers.
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


  async def set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
      import uuid as _uuid
      _uuid.UUID(tenant_id)
      await session.execute(
          text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'")
      )


  async def get_db(request: Request):
      """Yield a DB session with RLS tenant context already applied."""
      async with AsyncSessionLocal() as session:
          tenant_id = getattr(request.state, "tenant_id", None)
          if tenant_id:
              await set_tenant_context(session, tenant_id)
          yield session
  ```

- [ ] **Step 1.4: Jalankan test — pastikan PASS**

  ```bash
  python -m pytest tests/test_database.py -v
  ```

  Expected:
  ```
  PASSED tests/test_database.py::test_make_worker_session_yields_session_and_disposes_engine
  PASSED tests/test_database.py::test_make_worker_session_disposes_on_exception
  ```

- [ ] **Step 1.5: Pastikan test lain tidak rusak**

  ```bash
  python -m pytest tests/ -v --ignore=tests/test_database.py
  ```

  Expected: semua test existing PASS.

- [ ] **Step 1.6: Commit**

  ```bash
  git add app/database.py tests/test_database.py
  git commit -m "feat: add make_worker_session() for Celery async engine isolation"
  ```

---

## Task 2: `app/workers/utils.py` — `_try_trigger_scoring()`

**Files:**
- Create: `app/workers/utils.py`
- Create: `tests/test_worker_utils.py`

- [ ] **Step 2.1: Tulis failing tests**

  Buat file `tests/test_worker_utils.py`:

  ```python
  import json
  import pytest
  from unittest.mock import AsyncMock, patch


  def _make_redis_mock(progress: dict, set_nx_result=True):
      r = AsyncMock()
      r.get = AsyncMock(return_value=json.dumps(progress))
      r.set = AsyncMock(return_value=set_nx_result)
      r.aclose = AsyncMock()
      return r


  @pytest.mark.asyncio
  async def test_triggers_scoring_when_external_done():
      """scan_type=external + external_done=True → kirim scoring_task."""
      progress = {"scan_type": "external", "external_done": True, "internal_done": False}
      mock_r = _make_redis_mock(progress)

      with patch("app.workers.utils.aioredis.from_url", return_value=mock_r), \
           patch("app.workers.utils.celery_app") as mock_celery:
          from app.workers.utils import _try_trigger_scoring
          await _try_trigger_scoring("job-ext-123")

      mock_celery.send_task.assert_called_once_with(
          "app.workers.scoring.scoring_task",
          args=["job-ext-123"], queue="scoring",
      )


  @pytest.mark.asyncio
  async def test_triggers_scoring_when_internal_done():
      """scan_type=internal + internal_done=True → kirim scoring_task."""
      progress = {"scan_type": "internal", "external_done": False, "internal_done": True}
      mock_r = _make_redis_mock(progress)

      with patch("app.workers.utils.aioredis.from_url", return_value=mock_r), \
           patch("app.workers.utils.celery_app") as mock_celery:
          from app.workers.utils import _try_trigger_scoring
          await _try_trigger_scoring("job-int-456")

      mock_celery.send_task.assert_called_once_with(
          "app.workers.scoring.scoring_task",
          args=["job-int-456"], queue="scoring",
      )


  @pytest.mark.asyncio
  async def test_triggers_scoring_when_full_both_done():
      """scan_type=full + kedua done=True → kirim scoring_task."""
      progress = {"scan_type": "full", "external_done": True, "internal_done": True}
      mock_r = _make_redis_mock(progress)

      with patch("app.workers.utils.aioredis.from_url", return_value=mock_r), \
           patch("app.workers.utils.celery_app") as mock_celery:
          from app.workers.utils import _try_trigger_scoring
          await _try_trigger_scoring("job-full-789")

      mock_celery.send_task.assert_called_once_with(
          "app.workers.scoring.scoring_task",
          args=["job-full-789"], queue="scoring",
      )


  @pytest.mark.asyncio
  async def test_no_scoring_when_full_only_one_done():
      """scan_type=full + hanya external_done=True → scoring TIDAK dipanggil."""
      progress = {"scan_type": "full", "external_done": True, "internal_done": False}
      mock_r = _make_redis_mock(progress)

      with patch("app.workers.utils.aioredis.from_url", return_value=mock_r), \
           patch("app.workers.utils.celery_app") as mock_celery:
          from app.workers.utils import _try_trigger_scoring
          await _try_trigger_scoring("job-full-partial")

      mock_celery.send_task.assert_not_called()


  @pytest.mark.asyncio
  async def test_no_scoring_when_already_triggered():
      """SET NX gagal (key sudah ada) → scoring TIDAK dipanggil lagi."""
      progress = {"scan_type": "external", "external_done": True, "internal_done": False}
      mock_r = _make_redis_mock(progress, set_nx_result=None)  # None = key sudah ada

      with patch("app.workers.utils.aioredis.from_url", return_value=mock_r), \
           patch("app.workers.utils.celery_app") as mock_celery:
          from app.workers.utils import _try_trigger_scoring
          await _try_trigger_scoring("job-dup-999")

      mock_celery.send_task.assert_not_called()
  ```

- [ ] **Step 2.2: Jalankan test — pastikan FAIL**

  ```bash
  python -m pytest tests/test_worker_utils.py -v
  ```

  Expected: `ModuleNotFoundError: No module named 'app.workers.utils'`

- [ ] **Step 2.3: Buat `app/workers/utils.py`**

  ```python
  import json

  import redis.asyncio as aioredis

  from app.celery_app import celery_app
  from app.config import get_settings

  settings = get_settings()


  async def _try_trigger_scoring(job_id: str) -> None:
      """Trigger scoring_task tepat sekali ketika semua komponen scan selesai.

      Membaca scan_type dari Redis progress untuk menentukan kondisi 'ready'.
      Menggunakan Redis SET NX sebagai distributed lock agar scoring tidak
      dipanggil dua kali meskipun external dan internal selesai hampir bersamaan.
      """
      r = aioredis.from_url(settings.redis_url, decode_responses=True)
      try:
          progress = json.loads(await r.get(f"scan_progress:{job_id}") or "{}")
          scan_type = progress.get("scan_type", "external")
          ext = progress.get("external_done", False)
          itn = progress.get("internal_done", False)

          ready = (
              (scan_type == "external" and ext)
              or (scan_type == "internal" and itn)
              or (scan_type == "full" and ext and itn)
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

- [ ] **Step 2.4: Jalankan test — pastikan PASS**

  ```bash
  python -m pytest tests/test_worker_utils.py -v
  ```

  Expected:
  ```
  PASSED tests/test_worker_utils.py::test_triggers_scoring_when_external_done
  PASSED tests/test_worker_utils.py::test_triggers_scoring_when_internal_done
  PASSED tests/test_worker_utils.py::test_triggers_scoring_when_full_both_done
  PASSED tests/test_worker_utils.py::test_no_scoring_when_full_only_one_done
  PASSED tests/test_worker_utils.py::test_no_scoring_when_already_triggered
  ```

- [ ] **Step 2.5: Commit**

  ```bash
  git add app/workers/utils.py tests/test_worker_utils.py
  git commit -m "feat: add _try_trigger_scoring() with Redis SET NX exactly-once gate"
  ```

---

## Task 3: `app/workers/scoring.py` — Ganti `AsyncSessionLocal`

**Files:**
- Modify: `app/workers/scoring.py`
- Test: `tests/test_scoring.py` (existing — harus tetap PASS)

- [ ] **Step 3.1: Verifikasi test existing PASS sebelum perubahan**

  ```bash
  python -m pytest tests/test_scoring.py -v
  ```

  Expected:
  ```
  PASSED tests/test_scoring.py::test_perfect_score
  PASSED tests/test_scoring.py::test_one_critical
  PASSED tests/test_scoring.py::test_critical_risk
  PASSED tests/test_scoring.py::test_low_risk
  ```

- [ ] **Step 3.2: Update `app/workers/scoring.py`**

  Ganti seluruh isi file:

  ```python
  import asyncio
  import json
  from datetime import datetime, timezone

  from sqlalchemy import select

  from app.celery_app import celery_app
  from app.database import make_worker_session
  from app.models import ScanJob, ScanFinding
  from app.services.report import generate_pdf_report
  import redis.asyncio as aioredis
  from app.config import get_settings

  settings = get_settings()


  def _compute_score(crit: int, high: int, med: int, low: int) -> float:
      return max(0.0, 100.0 - (crit * 30 + high * 15 + med * 5 + low * 1))


  def _risk_level(score: float) -> str:
      if score <= 25:
          return "critical"
      if score <= 50:
          return "high"
      if score <= 75:
          return "medium"
      return "low"


  async def _run_scoring(job_id: str):
      async with make_worker_session() as session:
          job = (await session.execute(
              select(ScanJob).where(ScanJob.id == job_id)
          )).scalar_one()
          findings = (await session.execute(
              select(ScanFinding).where(
                  ScanFinding.job_id == job_id,
                  ScanFinding.is_false_positive == False,
              )
          )).scalars().all()

          counts = {s: sum(1 for f in findings if f.severity == s)
                    for s in ("critical", "high", "medium", "low")}
          score = _compute_score(counts["critical"], counts["high"],
                                 counts["medium"], counts["low"])

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

- [ ] **Step 3.3: Jalankan test — pastikan PASS**

  ```bash
  python -m pytest tests/test_scoring.py -v
  ```

  Expected: 4 tests PASS.

- [ ] **Step 3.4: Commit**

  ```bash
  git add app/workers/scoring.py
  git commit -m "fix: replace AsyncSessionLocal with make_worker_session in scoring worker"
  ```

---

## Task 4: `app/workers/external_bot.py` — Ganti Session + Tambah Trigger

**Files:**
- Modify: `app/workers/external_bot.py`

- [ ] **Step 4.1: Update `app/workers/external_bot.py`**

  Ganti seluruh isi file:

  ```python
  import asyncio
  import uuid
  import json

  from sqlalchemy import select
  from urllib.parse import urlparse

  from app.celery_app import celery_app
  from app.database import make_worker_session
  from app.models import ScanJob, ScanFinding
  from app.scanners.external.fingerprinter import scan_fingerprint
  from app.scanners.external.ssl_analyzer import scan_ssl
  from app.scanners.external.header_checker import scan_headers
  from app.scanners.external.vuln_prober import scan_vulnerabilities
  from app.scanners.external.open_dir_detector import scan_open_dirs
  from app.scanners.external.cve_matcher import scan_cve
  from app.workers.utils import _try_trigger_scoring
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
      async with make_worker_session() as session:
          job = (await session.execute(
              select(ScanJob).where(ScanJob.id == job_id)
          )).scalar_one()
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
      await _try_trigger_scoring(job_id)


  @celery_app.task(name="app.workers.external_bot.external_scan_task",
                   bind=True, max_retries=3, autoretry_for=(Exception,), default_retry_delay=60)
  def external_scan_task(self, job_id: str, target_url: str):
      asyncio.run(_run_external_scan(job_id, target_url))
  ```

- [ ] **Step 4.2: Verifikasi semua test PASS**

  ```bash
  python -m pytest tests/ -v
  ```

  Expected: semua test PASS, tidak ada `ImportError`.

- [ ] **Step 4.3: Commit**

  ```bash
  git add app/workers/external_bot.py
  git commit -m "fix: replace AsyncSessionLocal and add _try_trigger_scoring in external worker"
  ```

---

## Task 5: `app/workers/internal_bot.py` — Ganti Session + Tambah Trigger + Hapus Status Setting

**Files:**
- Modify: `app/workers/internal_bot.py`

Tiga perubahan sekaligus:
1. Ganti semua `AsyncSessionLocal` → `make_worker_session()` (3 tempat: 2 di `_setup_internal_scan`, 1 di `_run_internal_scan`)
2. Hapus `job.status = "running"` dan `await session.commit()` dari blok pertama `_setup_internal_scan` — status kini di-set di router sebelum tasks di-fire
3. Tambah `await _try_trigger_scoring(job_id)` di akhir `_run_internal_scan`

- [ ] **Step 5.1: Update `app/workers/internal_bot.py`**

  Ganti seluruh isi file:

  ```python
  import asyncio
  import hmac
  import hashlib
  import json
  import time
  import uuid
  from datetime import datetime, timezone

  import httpx
  from sqlalchemy import select

  from app.celery_app import celery_app
  from app.database import make_worker_session
  from app.models import OJSTarget, ScanJob, ScanFinding
  from app.scanners.internal.config_scanner import scan_config
  from app.scanners.internal.plugin_auditor import scan_plugins
  from app.scanners.internal.rbac_auditor import scan_rbac
  from app.scanners.internal.file_integrity import scan_file_integrity
  from app.scanners.internal.content_detector import scan_content
  from app.scanners.internal.db_security import scan_db_security
  from app.services.crypto import decrypt_api_key
  from app.workers.utils import _try_trigger_scoring
  import redis.asyncio as aioredis
  from app.config import get_settings

  settings = get_settings()

  DEFAULT_MODULES = ["fingerprint", "config", "plugins", "rbac", "file_integrity", "content"]


  def _sign_for_plugin(api_key: str, body: bytes) -> dict:
      """Mirrors PHP HmacSigner.sign(): timestamp + '.' + body."""
      ts = int(time.time())
      message = str(ts).encode() + b"." + body
      sig = "sha256=" + hmac.new(api_key.encode(), message, hashlib.sha256).hexdigest()
      return {
          "Content-Type": "application/json",
          "X-OJSDef-Signature": sig,
          "X-OJSDef-Timestamp": str(ts),
      }


  async def _trigger_plugin_direct(trigger_endpoint: str, api_key: str, job_id: str) -> bool:
      """POST ke plugin /trigger endpoint (Direct Mode). Return True jika HTTP 202."""
      body = json.dumps({"job_id": job_id, "scan_modules": DEFAULT_MODULES}).encode()
      headers = _sign_for_plugin(api_key, body)
      try:
          async with httpx.AsyncClient(timeout=15.0, verify=True) as client:
              resp = await client.post(trigger_endpoint, content=body, headers=headers)
          return resp.status_code == 202
      except Exception:
          return False


  async def _setup_internal_scan(job_id: str, target_id: str) -> None:
      """Trigger OJSDef plugin untuk menjalankan internal scan.

      Membaca target config dari DB untuk menentukan mode koneksi.
      job.status sudah di-set ke 'running' oleh start_scan router sebelum task ini dijalankan.
      """
      async with make_worker_session() as session:
          target = (await session.execute(
              select(OJSTarget).where(OJSTarget.id == target_id)
          )).scalar_one_or_none()
          if not target:
              return

          job = (await session.execute(
              select(ScanJob).where(ScanJob.id == job_id)
          )).scalar_one_or_none()
          if not job:
              return

          api_key = (
              decrypt_api_key(target.plugin_api_key_encrypted)
              if target.plugin_api_key_encrypted
              else None
          )
          connection_mode = target.connection_mode or "unknown"
          trigger_ep = target.trigger_endpoint

      # Direct Mode: POST ke plugin trigger endpoint
      if connection_mode == "direct" and trigger_ep and api_key:
          success = await _trigger_plugin_direct(trigger_ep, api_key, job_id)
          if success:
              return

      # Heartbeat Mode (atau fallback): simpan pending job; plugin ambil saat heartbeat
      async with make_worker_session() as session:
          result = await session.execute(
              select(OJSTarget).where(OJSTarget.id == target_id)
          )
          t = result.scalar_one_or_none()
          if t:
              t.pending_scan_job_id = uuid.UUID(job_id)
              if connection_mode == "direct":
                  t.connection_mode = "heartbeat"
              await session.commit()


  async def _run_internal_scan(job_id: str, data: dict) -> None:
      """Proses data scan dari plugin callback dan simpan findings ke DB."""
      all_findings = (
          scan_config(data.get("config", {}))
          + scan_plugins(data.get("plugins", []))
          + scan_rbac(data.get("users", []))
          + scan_file_integrity(data.get("file_integrity", {}))
          + scan_content(data.get("articles", []))
          + scan_db_security(data.get("db_config", {}))
      )
      async with make_worker_session() as session:
          job = (await session.execute(
              select(ScanJob).where(ScanJob.id == job_id)
          )).scalar_one()
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
      await _try_trigger_scoring(job_id)


  @celery_app.task(
      name="app.workers.internal_bot.internal_scan_task",
      bind=True, max_retries=3, autoretry_for=(Exception,), default_retry_delay=60,
  )
  def internal_scan_task(self, job_id: str, target_id: str):
      """Trigger OJSDef plugin untuk internal scan (Direct atau Heartbeat mode)."""
      asyncio.run(_setup_internal_scan(job_id, target_id))


  @celery_app.task(
      name="app.workers.internal_bot.process_plugin_data_task",
      bind=True, max_retries=3,
      autoretry_for=(Exception,), default_retry_delay=60,
  )
  def process_plugin_data_task(self, job_id: str, data: dict):
      """Proses data scan dari plugin callback dan trigger scoring setelah selesai."""
      asyncio.run(_run_internal_scan(job_id, data))
  ```

- [ ] **Step 5.2: Verifikasi semua test PASS**

  ```bash
  python -m pytest tests/ -v
  ```

  Expected: semua test PASS.

- [ ] **Step 5.3: Commit**

  ```bash
  git add app/workers/internal_bot.py
  git commit -m "fix: replace AsyncSessionLocal, remove job.status setting, add _try_trigger_scoring in internal worker"
  ```

---

## Task 6: `app/routers/scans.py` — Hapus chain/chord + Orchestration Baru

**Files:**
- Modify: `app/routers/scans.py`
- Modify: `tests/test_scoring.py` (tambah 1 test struktural)

- [ ] **Step 6.1: Tambah test struktural ke `tests/test_scoring.py`**

  Tambahkan di akhir file `tests/test_scoring.py`:

  ```python
  def test_scans_router_does_not_import_chord_or_chain():
      """scans.py tidak boleh lagi menggunakan celery chord/chain setelah refactor."""
      import app.routers.scans as scans_module
      assert not hasattr(scans_module, "chord"), "chord masih diimport di scans.py"
      assert not hasattr(scans_module, "chain"), "chain masih diimport di scans.py"
  ```

- [ ] **Step 6.2: Jalankan test — pastikan FAIL**

  ```bash
  python -m pytest tests/test_scoring.py::test_scans_router_does_not_import_chord_or_chain -v
  ```

  Expected: `FAILED — AssertionError: chord masih diimport di scans.py`

- [ ] **Step 6.3: Update `app/routers/scans.py`**

  Ganti seluruh isi file:

  ```python
  import uuid
  import json
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
          except Exception:
              parsed_progress = None
      return ScanResponse(
          id=str(job.id), target_id=str(job.target_id),
          scan_type=job.scan_type, status=job.status,
          overall_score=job.overall_score, risk_level=job.risk_level,
          critical_count=job.critical_count, high_count=job.high_count,
          medium_count=job.medium_count, low_count=job.low_count,
          progress=parsed_progress, created_at=job.created_at,
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
          status="running",
          started_at=datetime.now(timezone.utc),
      )
      db.add(job)
      await db.commit()
      await db.refresh(job)

      job_id = str(job.id)
      target_id = str(target.id)
      target_url = target.url

      # Inisialisasi Redis progress sebelum fire tasks
      r = _redis()
      await r.setex(f"scan_progress:{job_id}", 3600, json.dumps({
          "scan_type": body.scan_type,
          "external_done": False,
          "internal_done": False,
      }))
      await r.aclose()

      # Fire tasks independen — scoring dikoordinasi oleh _try_trigger_scoring via Redis
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
      current: dict = Depends(require_role("admin_ojs", "saas_admin")),
      db: AsyncSession = Depends(get_db),
  ):
      result = await db.execute(
          select(ScanFinding).where(
              ScanFinding.id == finding_id, ScanFinding.job_id == job_id
          )
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
  ```

- [ ] **Step 6.4: Jalankan semua test — pastikan PASS**

  ```bash
  python -m pytest tests/ -v
  ```

  Expected: semua test PASS termasuk `test_scans_router_does_not_import_chord_or_chain`.

- [ ] **Step 6.5: Commit**

  ```bash
  git add app/routers/scans.py tests/test_scoring.py
  git commit -m "fix: replace chord/chain with independent tasks and Redis progress orchestration in start_scan"
  ```

---

## Task 7: `docker-compose.yml` — Auto-run Migration + Seed

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 7.1: Update command FastAPI di `docker-compose.yml`**

  Ganti baris 13:
  ```yaml
  command: uvicorn app.main:app --host 0.0.0.0 --port 8000
  ```

  Dengan:
  ```yaml
  command: >
    sh -c "alembic upgrade head && python scripts/seed.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"
  ```

  `scripts/seed.py` sudah idempotent (cek sebelum insert). `alembic upgrade head` idempotent (skip revision yang sudah ada). Aman untuk container restart.

- [ ] **Step 7.2: Validasi syntax docker-compose**

  ```bash
  docker compose config --quiet && echo "OK: syntax valid"
  ```

  Expected: `OK: syntax valid`

- [ ] **Step 7.3: Commit**

  ```bash
  git add docker-compose.yml
  git commit -m "fix: auto-run alembic migrations and seed on FastAPI container startup"
  ```

---

## Task 8: Verifikasi Akhir

- [ ] **Step 8.1: Full test suite**

  ```bash
  python -m pytest tests/ -v
  ```

  Expected output minimal:
  ```
  PASSED tests/test_database.py::test_make_worker_session_yields_session_and_disposes_engine
  PASSED tests/test_database.py::test_make_worker_session_disposes_on_exception
  PASSED tests/test_worker_utils.py::test_triggers_scoring_when_external_done
  PASSED tests/test_worker_utils.py::test_triggers_scoring_when_internal_done
  PASSED tests/test_worker_utils.py::test_triggers_scoring_when_full_both_done
  PASSED tests/test_worker_utils.py::test_no_scoring_when_full_only_one_done
  PASSED tests/test_worker_utils.py::test_no_scoring_when_already_triggered
  PASSED tests/test_scoring.py::test_perfect_score
  PASSED tests/test_scoring.py::test_one_critical
  PASSED tests/test_scoring.py::test_critical_risk
  PASSED tests/test_scoring.py::test_low_risk
  PASSED tests/test_scoring.py::test_scans_router_does_not_import_chord_or_chain
  ```

- [ ] **Step 8.2: Deploy ke VPS dan smoke test**

  ```bash
  # Di VPS
  git pull
  docker compose down
  docker compose up -d
  # Tunggu ~10 detik lalu cek log
  docker compose logs fastapi --tail=20
  ```

  Expected di log fastapi:
  ```
  INFO  [alembic.runtime.migration] Running upgrade ...
  [seed] tenant exists: ...
  [seed] saas_admin exists: ...
  INFO:     Application startup complete.
  ```

  ```bash
  docker compose logs worker-scoring --tail=20
  docker compose logs worker-internal --tail=20
  ```

  Expected: tidak ada `RuntimeError: Future attached to a different loop`.

  Jalankan scan dari UI → status harus berubah `running` → `completed` dalam beberapa menit.
