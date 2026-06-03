# Internal Scanner Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Internal scan ter-trigger instan via pre-flight probe + fail-fast dengan diagnosa actionable, menghapus heartbeat-mode yang stuck selamanya.

**Architecture:** `internal_scan_task` melakukan probe sinkron real-time ke plugin; sukses → direct trigger, gagal → job `failed` dengan `diagnostic_code` yang dipetakan ke panduan perbaikan di frontend. Heartbeat jadi opt-in (`force_heartbeat`). Root cause probe 500 diperbaiki di `OjsdefHandler` (authorize + null guard).

**Tech Stack:** Python/FastAPI + Celery + SQLAlchemy/Alembic (BackEnd), PHP 7.4 (Plugin), Next.js/TypeScript (FrontEnd).

**Spec:** `docs/superpowers/specs/2026-06-03-internal-scanner-reliability-design.md`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `app/workers/diagnostics.py` (BackEnd, **baru**) | Konstanta `diagnostic_code` (sumber kebenaran tunggal) |
| `app/models/scan_job.py` (Edit) | Kolom `diagnostic_code`, `diagnostic_detail` |
| `app/models/ojs_target.py` (Edit) | Kolom `force_heartbeat` |
| `migrations/versions/004_internal_scan_diagnostics.py` (**baru**) | Tambah 3 kolom |
| `app/workers/internal_bot.py` (Edit) | Pre-flight probe + fail-fast + helper `_probe_for_scan`/`_fail_job` |
| `app/workers/tasks.py` (Edit) | `classify_stale_job` (5 mnt callback / 30 mnt umum) |
| `app/schemas/scans.py` (Edit) | Expose `diagnostic_code`/`diagnostic_detail` |
| `app/routers/scans.py` (Edit) | `_to_response` sertakan field diagnosa |
| `ojsdef/OjsdefHandler.php` (Plugin, Edit) | `authorize()` publik + guard plugin null (503) |
| `ojsdef/OjsdefPlugin.php` (Plugin, Edit) | Scan async di heartbeat path |
| `OJSDEF-FrontEnd/types/api.ts` (Edit) | Field diagnosa di `ScanJob` |
| `OJSDEF-FrontEnd/lib/diagnostics.ts` (**baru**) | Mapping `diagnostic_code` → panduan ID |
| `OJSDEF-FrontEnd/app/(dashboard)/scan-management/[id]/page.tsx` (Edit) | Kartu "Diagnosa & Cara Perbaiki" |

**Catatan lingkungan:** semua perintah `pytest`/`alembic` dijalankan dari `D:\Kuliahku\Capstone\workspace\OJSDEF-BackEnd` dengan venv aktif. Perintah `npm` dari `OJSDEF-FrontEnd`.

---

## Task 1: Konstanta diagnostic_code (sumber kebenaran)

**Files:**
- Create: `app/workers/diagnostics.py`
- Test: `tests/test_diagnostics.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diagnostics.py
from app.workers.diagnostics import DIAGNOSTIC_CODES, is_valid_code


def test_all_codes_present():
    expected = {
        "PLUGIN_UNREACHABLE", "PROBE_HTTP_500", "HMAC_MISMATCH",
        "CHALLENGE_MISMATCH", "TRIGGER_REJECTED", "CALLBACK_TIMEOUT",
    }
    assert set(DIAGNOSTIC_CODES) == expected


def test_is_valid_code():
    assert is_valid_code("PROBE_HTTP_500") is True
    assert is_valid_code("NOPE") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_diagnostics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.workers.diagnostics'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/workers/diagnostics.py
"""Kode diagnosa kegagalan internal scan. Mirror di FrontEnd lib/diagnostics.ts."""

DIAGNOSTIC_CODES: tuple[str, ...] = (
    "PLUGIN_UNREACHABLE",   # probe connect error / timeout / endpoint kosong
    "PROBE_HTTP_500",       # probe balas 5xx
    "HMAC_MISMATCH",        # probe/trigger balas 401
    "CHALLENGE_MISMATCH",   # 200 tapi challenge tidak cocok
    "TRIGGER_REJECTED",     # trigger non-202
    "CALLBACK_TIMEOUT",     # 202 diterima tapi tak ada callback dalam 5 menit
)


def is_valid_code(code: str) -> bool:
    return code in DIAGNOSTIC_CODES
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_diagnostics.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/workers/diagnostics.py tests/test_diagnostics.py
git commit -m "feat: tambah konstanta diagnostic_code internal scan"
```

---

## Task 2: Model + Migration (3 kolom baru)

**Files:**
- Modify: `app/models/scan_job.py`
- Modify: `app/models/ojs_target.py`
- Create: `migrations/versions/004_internal_scan_diagnostics.py`
- Test: `tests/test_migration_004.py`

- [ ] **Step 1: Tambah kolom di `app/models/scan_job.py`**

Setelah baris `error_message` (baris 23), tambahkan:

```python
    diagnostic_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    diagnostic_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 2: Tambah kolom di `app/models/ojs_target.py`**

Setelah baris `pending_scan_job_id` (baris 26), tambahkan:

```python
    # Opt-in: paksa mode heartbeat untuk OJS di balik firewall (lewati pre-flight probe)
    force_heartbeat: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa_false())
```

Dan di bagian import atas file, ganti baris import sqlalchemy agar menyertakan `false`:

```python
from sqlalchemy import DateTime, String, Boolean, Text, ForeignKey, false as sa_false
```

- [ ] **Step 3: Buat migration `migrations/versions/004_internal_scan_diagnostics.py`**

```python
"""internal scan diagnostics + force_heartbeat

Revision ID: 004
Revises: 003
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scan_jobs",
        sa.Column("diagnostic_code", sa.String(40), nullable=True))
    op.add_column("scan_jobs",
        sa.Column("diagnostic_detail", sa.Text(), nullable=True))
    op.add_column("ojs_targets",
        sa.Column("force_heartbeat", sa.Boolean(), nullable=False,
                  server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("ojs_targets", "force_heartbeat")
    op.drop_column("scan_jobs", "diagnostic_detail")
    op.drop_column("scan_jobs", "diagnostic_code")
```

- [ ] **Step 4: Write the failing test**

```python
# tests/test_migration_004.py
import app.models.scan_job as sj
import app.models.ojs_target as ot


def test_scan_job_has_diagnostic_columns():
    cols = sj.ScanJob.__table__.columns.keys()
    assert "diagnostic_code" in cols
    assert "diagnostic_detail" in cols


def test_target_has_force_heartbeat():
    cols = ot.OJSTarget.__table__.columns.keys()
    assert "force_heartbeat" in cols
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_migration_004.py -v`
Expected: PASS (2 passed). Jika FAIL, periksa Step 1-2 sudah tersimpan.

- [ ] **Step 6: Apply migration ke DB dev**

Run: `alembic upgrade head`
Expected: `Running upgrade 003 -> 004, internal scan diagnostics + force_heartbeat`

Verifikasi downgrade bersih lalu kembali:
Run: `alembic downgrade -1 && alembic upgrade head`
Expected: tidak ada error.

- [ ] **Step 7: Commit**

```bash
git add app/models/scan_job.py app/models/ojs_target.py migrations/versions/004_internal_scan_diagnostics.py tests/test_migration_004.py
git commit -m "feat: kolom diagnostic_code/detail + force_heartbeat (migration 004)"
```

---

## Task 3: Pre-flight probe + fail-fast di internal_bot

**Files:**
- Modify: `app/workers/internal_bot.py`
- Test: `tests/test_internal_bot_preflight.py`

Konteks: `_setup_internal_scan` saat ini (baris 54-95) selalu jatuh ke heartbeat saat `connection_mode != "direct"`. Diganti total dengan pre-flight probe + fail-fast.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_internal_bot_preflight.py
import json
import pytest
from unittest.mock import AsyncMock, patch
import httpx

from app.workers import internal_bot


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_probe_connect_error_returns_unreachable():
    with patch("app.workers.internal_bot.httpx.AsyncClient") as cli:
        cli.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=httpx.ConnectError("refused")
        )
        result, code, _ = await internal_bot._probe_for_scan("https://x/probe", "k")
    assert result == "FAIL"
    assert code == "PLUGIN_UNREACHABLE"


@pytest.mark.asyncio
async def test_probe_500_returns_probe_http_500():
    with patch("app.workers.internal_bot.httpx.AsyncClient") as cli:
        cli.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=_Resp(500)
        )
        result, code, _ = await internal_bot._probe_for_scan("https://x/probe", "k")
    assert (result, code) == ("FAIL", "PROBE_HTTP_500")


@pytest.mark.asyncio
async def test_probe_401_returns_hmac_mismatch():
    with patch("app.workers.internal_bot.httpx.AsyncClient") as cli:
        cli.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=_Resp(401)
        )
        result, code, _ = await internal_bot._probe_for_scan("https://x/probe", "k")
    assert (result, code) == ("FAIL", "HMAC_MISMATCH")


@pytest.mark.asyncio
async def test_probe_challenge_mismatch():
    with patch("app.workers.internal_bot.httpx.AsyncClient") as cli:
        cli.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=_Resp(200, {"challenge": "WRONG"})
        )
        result, code, _ = await internal_bot._probe_for_scan("https://x/probe", "k")
    assert (result, code) == ("FAIL", "CHALLENGE_MISMATCH")


@pytest.mark.asyncio
async def test_probe_success_returns_direct():
    async def _fake_post(url, content=None, headers=None):
        sent = json.loads(content)
        return _Resp(200, {"challenge": sent["challenge"]})
    with patch("app.workers.internal_bot.httpx.AsyncClient") as cli:
        cli.return_value.__aenter__.return_value.post = AsyncMock(side_effect=_fake_post)
        result, code, _ = await internal_bot._probe_for_scan("https://x/probe", "k")
    assert result == "DIRECT"
    assert code is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_internal_bot_preflight.py -v`
Expected: FAIL with `AttributeError: module 'app.workers.internal_bot' has no attribute '_probe_for_scan'`

- [ ] **Step 3: Tambah `_probe_for_scan` dan `_fail_job` di `internal_bot.py`**

Tambah import di bagian atas (setelah baris `from app.config import get_settings`):

```python
from app.workers.diagnostics import DIAGNOSTIC_CODES  # noqa: F401  (validasi kode tersedia)
```

Tambah dua helper baru (letakkan setelah `_trigger_plugin_direct`, sebelum `_setup_internal_scan`):

```python
async def _probe_for_scan(probe_endpoint: str, api_key: str) -> tuple[str, str | None, str | None]:
    """Probe sinkron untuk menentukan reachability saat scan dijalankan.

    Returns (result, diagnostic_code, detail):
      - ("DIRECT", None, None)         plugin reachable & challenge cocok
      - ("FAIL", <code>, <detail>)     gagal, dengan kode diagnosa
    """
    challenge = uuid.uuid4().hex
    body = json.dumps({"challenge": challenge}).encode()
    headers = _sign_for_plugin(api_key, body)
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
            resp = await client.post(probe_endpoint, content=body, headers=headers)
    except Exception as exc:
        return ("FAIL", "PLUGIN_UNREACHABLE", f"{type(exc).__name__}: {exc}")

    if resp.status_code == 401:
        return ("FAIL", "HMAC_MISMATCH", "HTTP 401 di /probe — API key tidak cocok")
    if resp.status_code >= 500:
        return ("FAIL", "PROBE_HTTP_500", f"HTTP {resp.status_code} di /probe")
    if resp.status_code != 200:
        return ("FAIL", "PLUGIN_UNREACHABLE", f"HTTP {resp.status_code} di /probe")
    try:
        echoed = resp.json().get("challenge", "")
    except Exception:
        echoed = ""
    if echoed != challenge:
        return ("FAIL", "CHALLENGE_MISMATCH", "Challenge tidak di-echo dengan benar")
    return ("DIRECT", None, None)


async def _fail_job(job_id: str, code: str, detail: str) -> None:
    """Tandai job failed + simpan diagnosa, lalu tulis WARN ke progress log."""
    async with make_worker_session() as session:
        job = (await session.execute(
            select(ScanJob).where(ScanJob.id == job_id)
        )).scalar_one_or_none()
        if job:
            job.status = "failed"
            job.completed_at = datetime.now(timezone.utc)
            job.diagnostic_code = code
            job.diagnostic_detail = detail
            job.error_message = detail
            await session.commit()
    await write_progress(
        job_id, "internal_audit", 0, 0,
        f"Scan gagal — {code}: {detail}", "WARN",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_internal_bot_preflight.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add app/workers/internal_bot.py tests/test_internal_bot_preflight.py
git commit -m "feat: _probe_for_scan + _fail_job helper internal scan"
```

---

## Task 4: Rewire _setup_internal_scan ke alur pre-flight

**Files:**
- Modify: `app/workers/internal_bot.py`
- Test: `tests/test_internal_bot_setup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_internal_bot_setup.py
import pytest
from unittest.mock import AsyncMock

from app.workers import internal_bot


class _Target:
    def __init__(self, **kw):
        self.id = "t1"
        self.plugin_api_key_encrypted = "enc"
        self.probe_endpoint = "https://x/probe"
        self.trigger_endpoint = "https://x/trigger"
        self.force_heartbeat = False
        self.pending_scan_job_id = None
        self.connection_mode = "unknown"
        self.__dict__.update(kw)


@pytest.mark.asyncio
async def test_fail_fast_when_probe_fails(monkeypatch):
    monkeypatch.setattr(internal_bot, "decrypt_api_key", lambda _: "k")
    monkeypatch.setattr(internal_bot, "_load_target_and_job",
                        AsyncMock(return_value=(_Target(), True)))
    monkeypatch.setattr(internal_bot, "_probe_for_scan",
                        AsyncMock(return_value=("FAIL", "PROBE_HTTP_500", "HTTP 500")))
    fail = AsyncMock()
    monkeypatch.setattr(internal_bot, "_fail_job", fail)
    monkeypatch.setattr(internal_bot, "write_progress", AsyncMock())
    trig = AsyncMock()
    monkeypatch.setattr(internal_bot, "_trigger_plugin_direct", trig)

    await internal_bot._setup_internal_scan("job1", "t1")

    fail.assert_awaited_once()
    assert fail.await_args.args[1] == "PROBE_HTTP_500"
    trig.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_trigger_on_probe_success(monkeypatch):
    monkeypatch.setattr(internal_bot, "decrypt_api_key", lambda _: "k")
    monkeypatch.setattr(internal_bot, "_load_target_and_job",
                        AsyncMock(return_value=(_Target(), True)))
    monkeypatch.setattr(internal_bot, "_probe_for_scan",
                        AsyncMock(return_value=("DIRECT", None, None)))
    monkeypatch.setattr(internal_bot, "_trigger_plugin_direct",
                        AsyncMock(return_value=True))
    monkeypatch.setattr(internal_bot, "write_progress", AsyncMock())
    monkeypatch.setattr(internal_bot, "_set_connection_mode", AsyncMock())
    fail = AsyncMock()
    monkeypatch.setattr(internal_bot, "_fail_job", fail)

    await internal_bot._setup_internal_scan("job1", "t1")
    fail.assert_not_awaited()


@pytest.mark.asyncio
async def test_force_heartbeat_skips_probe(monkeypatch):
    monkeypatch.setattr(internal_bot, "decrypt_api_key", lambda _: "k")
    monkeypatch.setattr(internal_bot, "_load_target_and_job",
                        AsyncMock(return_value=(_Target(force_heartbeat=True), True)))
    probe = AsyncMock()
    monkeypatch.setattr(internal_bot, "_probe_for_scan", probe)
    monkeypatch.setattr(internal_bot, "write_progress", AsyncMock())
    monkeypatch.setattr(internal_bot, "_queue_heartbeat_job", AsyncMock())

    await internal_bot._setup_internal_scan("job1", "t1")
    probe.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_internal_bot_setup.py -v`
Expected: FAIL with `AttributeError: ... has no attribute '_load_target_and_job'`

- [ ] **Step 3: Ganti `_setup_internal_scan` (baris 54-95) dan tambah 3 helper**

Hapus seluruh fungsi `_setup_internal_scan` lama, ganti dengan:

```python
async def _load_target_and_job(job_id: str, target_id: str):
    """Return (target, job_exists). target None jika tidak ditemukan."""
    async with make_worker_session() as session:
        target = (await session.execute(
            select(OJSTarget).where(OJSTarget.id == target_id)
        )).scalar_one_or_none()
        job = (await session.execute(
            select(ScanJob).where(ScanJob.id == job_id)
        )).scalar_one_or_none()
    return target, (job is not None)


async def _set_connection_mode(target_id: str, mode: str) -> None:
    async with make_worker_session() as session:
        t = (await session.execute(
            select(OJSTarget).where(OJSTarget.id == target_id)
        )).scalar_one_or_none()
        if t:
            t.connection_mode = mode
            await session.commit()


async def _queue_heartbeat_job(target_id: str, job_id: str) -> None:
    async with make_worker_session() as session:
        t = (await session.execute(
            select(OJSTarget).where(OJSTarget.id == target_id)
        )).scalar_one_or_none()
        if t:
            t.pending_scan_job_id = uuid.UUID(job_id)
            await session.commit()


async def _setup_internal_scan(job_id: str, target_id: str) -> None:
    """Pre-flight probe → direct trigger, atau fail-fast dengan diagnosa.

    force_heartbeat=True melewati probe dan masuk antrian heartbeat (opt-in firewall).
    """
    target, job_exists = await _load_target_and_job(job_id, target_id)
    if not target or not job_exists:
        return

    api_key = (
        decrypt_api_key(target.plugin_api_key_encrypted)
        if target.plugin_api_key_encrypted else None
    )

    await write_progress(
        job_id, "internal_audit", 1, 2,
        "Mengirim permintaan audit ke plugin OJS...", "TASK",
    )

    # Opt-in heartbeat (OJS di balik firewall) — perilaku lama, eksplisit
    if getattr(target, "force_heartbeat", False):
        await write_progress(
            job_id, "internal_audit", 2, 2,
            "Mode heartbeat — menunggu jadwal berikutnya...", "INFO",
        )
        await _queue_heartbeat_job(target_id, job_id)
        return

    if not api_key or not target.probe_endpoint:
        await _fail_job(
            job_id, "PLUGIN_UNREACHABLE",
            "Plugin belum mengirim endpoint atau API key belum diset. "
            "Pastikan plugin OJSDef aktif dan sudah mengirim heartbeat minimal sekali.",
        )
        return

    result, code, detail = await _probe_for_scan(target.probe_endpoint, api_key)
    if result != "DIRECT":
        await _fail_job(job_id, code, detail)
        return

    if not target.trigger_endpoint:
        await _fail_job(job_id, "TRIGGER_REJECTED", "trigger_endpoint kosong di target")
        return

    triggered = await _trigger_plugin_direct(target.trigger_endpoint, api_key, job_id)
    if triggered:
        await _set_connection_mode(target_id, "direct")
        await write_progress(
            job_id, "internal_audit", 2, 2,
            "Plugin merespons, menunggu callback...", "INFO",
        )
    else:
        await _fail_job(
            job_id, "TRIGGER_REJECTED",
            "Plugin tidak membalas HTTP 202 pada /trigger",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_internal_bot_setup.py tests/test_internal_bot_preflight.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Syntax check import**

Run: `python -c "import app.workers.internal_bot"`
Expected: tidak ada error import.

- [ ] **Step 6: Commit**

```bash
git add app/workers/internal_bot.py tests/test_internal_bot_setup.py
git commit -m "feat: internal scan pre-flight probe + fail-fast (ganti heartbeat default)"
```

---

## Task 5: Callback timeout 5 menit (classify_stale_job)

**Files:**
- Modify: `app/workers/tasks.py`
- Test: `tests/test_stale_jobs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stale_jobs.py
from datetime import datetime, timedelta, timezone
from app.workers.tasks import classify_stale_job

NOW = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)


def _ago(minutes):
    return NOW - timedelta(minutes=minutes)


def test_internal_running_6min_is_callback_timeout():
    assert classify_stale_job(
        status="running", scan_type="internal",
        started_at=_ago(6), created_at=_ago(6), now=NOW,
    ) == "CALLBACK_TIMEOUT"


def test_internal_running_3min_is_none():
    assert classify_stale_job(
        status="running", scan_type="internal",
        started_at=_ago(3), created_at=_ago(3), now=NOW,
    ) is None


def test_external_running_6min_not_callback_timeout():
    # external tidak kena 5-min callback cap; baru kena 30-min umum
    assert classify_stale_job(
        status="running", scan_type="external",
        started_at=_ago(6), created_at=_ago(6), now=NOW,
    ) is None


def test_any_queued_31min_is_stale():
    assert classify_stale_job(
        status="queued", scan_type="external",
        started_at=None, created_at=_ago(31), now=NOW,
    ) == "STALE"


def test_completed_is_none():
    assert classify_stale_job(
        status="completed", scan_type="internal",
        started_at=_ago(99), created_at=_ago(99), now=NOW,
    ) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stale_jobs.py -v`
Expected: FAIL with `ImportError: cannot import name 'classify_stale_job'`

- [ ] **Step 3: Tulis ulang `app/workers/tasks.py`**

```python
# NOTE: asyncio.run() in these tasks assumes Celery is using the prefork pool
# (default). Do NOT switch to gevent/eventlet pool without replacing asyncio.run()
# with the gevent-compatible async_to_sync() pattern.

import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models.scan_job import ScanJob
from app.workers.utils import write_progress

CALLBACK_TIMEOUT_MINUTES = 5
STALE_TIMEOUT_MINUTES = 30


def classify_stale_job(
    status: str,
    scan_type: str,
    started_at: datetime | None,
    created_at: datetime | None,
    now: datetime,
    callback_minutes: int = CALLBACK_TIMEOUT_MINUTES,
    general_minutes: int = STALE_TIMEOUT_MINUTES,
) -> str | None:
    """Klasifikasi job macet. Pure function — mudah diuji.

    - CALLBACK_TIMEOUT: internal/full running > 5 menit (nunggu callback plugin)
    - STALE:            queued/running > 30 menit (jaring umum)
    - None:             tidak macet
    """
    if status not in ("queued", "running"):
        return None
    if (
        status == "running"
        and scan_type in ("internal", "full")
        and started_at is not None
        and started_at < now - timedelta(minutes=callback_minutes)
    ):
        return "CALLBACK_TIMEOUT"
    if created_at is not None and created_at < now - timedelta(minutes=general_minutes):
        return "STALE"
    return None


@celery_app.task(name="app.workers.tasks.cleanup_stale_pending_jobs")
def cleanup_stale_pending_jobs() -> str:
    """Tandai job macet sebagai failed dengan diagnosa yang sesuai."""

    async def _run() -> int:
        now = datetime.now(timezone.utc)
        count = 0
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ScanJob).where(ScanJob.status.in_(["queued", "running"]))
            )
            for job in result.scalars().all():
                verdict = classify_stale_job(
                    status=job.status, scan_type=job.scan_type,
                    started_at=job.started_at, created_at=job.created_at, now=now,
                )
                if verdict is None:
                    continue
                if verdict == "CALLBACK_TIMEOUT":
                    msg = "Scan timeout: plugin menerima permintaan tapi tidak mengirim hasil dalam 5 menit"
                    job.diagnostic_code = "CALLBACK_TIMEOUT"
                else:
                    msg = "Scan timeout: tidak ada respons dalam 30 menit"
                    job.diagnostic_code = job.diagnostic_code or "PLUGIN_UNREACHABLE"
                await write_progress(str(job.id), "scan", 0, 0, msg, "WARN")
                job.status = "failed"
                job.completed_at = now
                job.error_message = msg
                job.diagnostic_detail = job.diagnostic_detail or msg
                count += 1
            if count:
                await session.commit()
            return count

    count = asyncio.run(_run())
    return f"Cleaned up {count} stale pending jobs"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_stale_jobs.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add app/workers/tasks.py tests/test_stale_jobs.py
git commit -m "feat: callback timeout 5 menit via classify_stale_job"
```

---

## Task 6: Expose diagnosa di API response

**Files:**
- Modify: `app/schemas/scans.py`
- Modify: `app/routers/scans.py`
- Test: `tests/test_scan_response_diagnostics.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scan_response_diagnostics.py
from app.schemas.scans import ScanResponse


def test_scan_response_has_diagnostic_fields():
    fields = ScanResponse.model_fields
    assert "diagnostic_code" in fields
    assert "diagnostic_detail" in fields


def test_diagnostic_fields_default_none():
    r = ScanResponse(
        id="i", target_id="t", scan_type="internal", status="failed",
        overall_score=None, risk_level=None, critical_count=0, high_count=0,
        medium_count=0, low_count=0, created_at="2026-06-03T00:00:00Z",
    )
    assert r.diagnostic_code is None
    assert r.diagnostic_detail is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scan_response_diagnostics.py -v`
Expected: FAIL — `AssertionError: assert 'diagnostic_code' in {...}`

- [ ] **Step 3: Tambah field di `ScanResponse` (`app/schemas/scans.py`)**

Di kelas `ScanResponse`, setelah baris `progress: ScanProgress | None = None` (baris 39), tambahkan:

```python
    diagnostic_code: str | None = None
    diagnostic_detail: str | None = None
```

- [ ] **Step 4: Sertakan field di `_to_response` (`app/routers/scans.py`)**

Ganti blok `return ScanResponse(...)` di fungsi `_to_response` (baris 42-49) menjadi:

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_scan_response_diagnostics.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Jalankan seluruh test suite backend**

Run: `pytest -q`
Expected: semua hijau (tidak ada regresi).

- [ ] **Step 7: Commit**

```bash
git add app/schemas/scans.py app/routers/scans.py tests/test_scan_response_diagnostics.py
git commit -m "feat: expose diagnostic_code/detail di ScanResponse"
```

---

## Task 7: Fix root cause probe 500 di plugin (OjsdefHandler)

**Files:**
- Modify: `ojsdef/OjsdefHandler.php` (dir `OJSDEF-Plugin/`)
- Rebuild: `ojsdef-plugin-1.0.1.zip`

> **Sub-skill wajib:** gunakan **superpowers:systematic-debugging**. Root cause 500 belum 100% terkonfirmasi — konfirmasi dari log dulu, baru patch.

- [ ] **Step 1: Konfirmasi root cause dari error log VPS**

SSH ke OJS test (kredensial dari sesi sebelumnya: `ssh -i "D:\ssh\alibaba-aftaza\ojs-test.ppk" ojs-test@147.139.195.136`). Picu probe dan tangkap fatal:

```bash
# Di VPS, tail PHP error log container OJS sambil curl probe
docker logs -f <ojs_php_container> --since 2m
# Dari mesin lain: panggil probe via curl
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://ojs-test.zentaza.online/index.php/index/ojsdef/probe
```

Catat pesan fatal (mis. `Call to ... on null`, `authorization`, `Fatal error: Uncaught`). **Ini menentukan patch final.** Hipotesis: `PKPHandler` menolak op tanpa role assignment / `authorize()`.

- [ ] **Step 2: Tambah `authorize()` + null guard di `OjsdefHandler.php`**

Tambahkan method `authorize()` di kelas `OjsdefHandler` (sesudah deklarasi kelas, sebelum `probe()`):

```php
    /**
     * Endpoint publik probe/trigger — autentikasi sesungguhnya via HMAC,
     * bukan sesi login OJS. Izinkan tanpa role assignment.
     */
    public function authorize($request, &$args, $roleAssignments)
    {
        return true;
    }
```

Ganti awal `probe()` dan `trigger()` (baris `$plugin = PluginRegistry::getPlugin(...); $plugin->_requireClasses();` di kedua method) dengan:

```php
        $plugin = PluginRegistry::getPlugin('generic', 'ojsdef');
        if (!$plugin) {
            $this->_json(503, ['error' => 'plugin_inactive']);
            return;
        }
        $plugin->_requireClasses();
```

> Jika Step 1 menunjukkan penyebab berbeda (mis. routing/CSRF), sesuaikan patch — target tetap: probe/trigger membalas non-5xx untuk request HMAC valid. Catat temuan di commit message.

- [ ] **Step 3: Rebuild ZIP distribusi**

Dari `OJSDEF-Plugin/` (PowerShell):

```powershell
Add-Type -AssemblyName System.IO.Compression; Add-Type -AssemblyName System.IO.Compression.FileSystem
$src = "ojsdef"; $out = "ojsdef-plugin-1.0.1.zip"
if (Test-Path $out) { Remove-Item $out -Force }
$zip = [System.IO.Compression.ZipFile]::Open($out, 'Create')
Get-ChildItem -Path $src -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring((Resolve-Path $src).Path.Length).TrimStart('\').Replace('\','/')
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, "ojsdef/$rel")
}
$zip.Dispose()
```

- [ ] **Step 4: Deploy & verifikasi di VPS**

Upload ZIP via OJS admin → Plugins → Upload (replace), aktifkan. Lalu:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://ojs-test.zentaza.online/index.php/index/ojsdef/probe
```

Expected: **bukan 500** (200 untuk HMAC valid; 401 untuk request tanpa signature — keduanya membuktikan fatal hilang).

- [ ] **Step 5: Commit**

```bash
# dari OJSDEF-Plugin/
git add ojsdef/OjsdefHandler.php ojsdef-plugin-1.0.1.zip
git commit -m "fix: probe/trigger 500 — tambah authorize() publik + guard plugin null

Root cause: <isi dari Step 1>"
```

---

## Task 8: Scan async di heartbeat path (plugin)

**Files:**
- Modify: `ojsdef/OjsdefPlugin.php`
- Rebuild: `ojsdef-plugin-1.0.1.zip`

- [ ] **Step 1: Tambah guard waktu di `_runScanFromHeartbeat`**

Di `OjsdefPlugin.php`, di awal method `_runScanFromHeartbeat` (sebelum `$this->_requireClasses();`), tambahkan:

```php
        @set_time_limit(0);
        ignore_user_abort(true);
```

- [ ] **Step 2: Rebuild ZIP**

Ulangi perintah rebuild ZIP dari Task 7 Step 3.

- [ ] **Step 3: Verifikasi unit test plugin tetap hijau**

Dari `OJSDEF-Plugin/`:
Run: `php vendor/bin/phpunit`
Expected: `OK` (19+ tests).

- [ ] **Step 4: Commit**

```bash
git add ojsdef/OjsdefPlugin.php ojsdef-plugin-1.0.1.zip
git commit -m "fix: scan heartbeat-mode async (set_time_limit + ignore_user_abort)"
```

---

## Task 9: Frontend — tipe + mapping diagnosa

**Files:**
- Modify: `OJSDEF-FrontEnd/types/api.ts`
- Create: `OJSDEF-FrontEnd/lib/diagnostics.ts`

- [ ] **Step 1: Tambah field diagnosa di `ScanJob` (`types/api.ts`)**

Di interface `ScanJob` (baris 79-92), sebelum `progress: ScanProgress | null`, tambahkan:

```typescript
  diagnostic_code: string | null
  diagnostic_detail: string | null
```

- [ ] **Step 2: Buat `lib/diagnostics.ts`**

```typescript
// lib/diagnostics.ts — mirror app/workers/diagnostics.py (BackEnd)
// Panduan perbaikan internal scan gagal, Bahasa Indonesia.

export interface DiagnosticGuide {
  title: string
  steps: string[]
}

export const DIAGNOSTIC_GUIDES: Record<string, DiagnosticGuide> = {
  PLUGIN_UNREACHABLE: {
    title: 'Plugin OJS tidak dapat dijangkau',
    steps: [
      'Pastikan instalasi OJS sedang online dan dapat diakses dari internet.',
      'Pastikan plugin OJSDef sudah diaktifkan di OJS (Website Settings → Plugins).',
      'Jika OJS berada di balik firewall, aktifkan Mode Heartbeat pada pengaturan target.',
      'Tunggu plugin mengirim heartbeat minimal sekali, lalu coba scan lagi.',
    ],
  },
  PROBE_HTTP_500: {
    title: 'Plugin OJS mengalami error internal',
    steps: [
      'Pastikan plugin OJSDef versi terbaru sudah ter-install dan aktif.',
      'Periksa PHP error log di server OJS untuk pesan fatal.',
      'Reinstall plugin OJSDef bila perlu, lalu coba scan lagi.',
    ],
  },
  HMAC_MISMATCH: {
    title: 'API Key tidak cocok',
    steps: [
      'Buka halaman Panduan Plugin target ini untuk menyalin ulang API Key.',
      'Tempel API Key ke Settings plugin OJSDef di OJS (Backend URL, API Key, Target ID).',
      'Simpan pengaturan, lalu coba scan lagi.',
    ],
  },
  CHALLENGE_MISMATCH: {
    title: 'Plugin tidak merespons dengan benar',
    steps: [
      'Plugin terpasang tetapi tidak meng-echo verifikasi dengan benar.',
      'Reinstall plugin OJSDef versi terbaru.',
      'Coba scan lagi setelah plugin aktif.',
    ],
  },
  TRIGGER_REJECTED: {
    title: 'Plugin menolak permintaan scan',
    steps: [
      'Pastikan Target ID di Settings plugin OJS sama persis dengan dashboard.',
      'Pastikan API Key benar dan plugin dalam keadaan aktif.',
      'Coba scan lagi.',
    ],
  },
  CALLBACK_TIMEOUT: {
    title: 'Scan dimulai tetapi tidak selesai',
    steps: [
      'Plugin menerima permintaan tetapi tidak mengirim hasil dalam 5 menit.',
      'Periksa max_execution_time dan memory_limit pada PHP server OJS.',
      'Untuk instalasi besar, naikkan batas tersebut, lalu coba scan lagi.',
    ],
  },
}

export function getDiagnosticGuide(code: string | null | undefined): DiagnosticGuide | null {
  if (!code) return null
  return DIAGNOSTIC_GUIDES[code] ?? null
}
```

- [ ] **Step 3: Verifikasi typecheck**

Dari `OJSDEF-FrontEnd/`:
Run: `npx tsc --noEmit`
Expected: tidak ada error baru terkait `diagnostics.ts` / `api.ts`.

- [ ] **Step 4: Commit**

```bash
git add types/api.ts lib/diagnostics.ts
git commit -m "feat: tipe diagnostic_code + mapping panduan diagnosa frontend"
```

---

## Task 10: Frontend — kartu "Diagnosa & Cara Perbaiki"

**Files:**
- Modify: `OJSDEF-FrontEnd/app/(dashboard)/scan-management/[id]/page.tsx`

- [ ] **Step 1: Import guide helper**

Di bagian import (setelah baris 11 `import type { ScanJob }`), tambahkan:

```typescript
import { getDiagnosticGuide } from '@/lib/diagnostics'
import { AlertTriangle } from 'lucide-react'
```

(Catatan: `ArrowLeft` sudah di-import dari `lucide-react` di baris 6 — gabungkan import bila perlu menjadi `import { ArrowLeft, AlertTriangle } from 'lucide-react'`.)

- [ ] **Step 2: Hitung guide sebelum `return`**

Setelah baris `const statusLabel = ...` (sekitar baris 108-110), tambahkan:

```typescript
  const diagnosticGuide =
    job.status === 'failed' ? getDiagnosticGuide(job.diagnostic_code) : null
```

- [ ] **Step 3: Render kartu diagnosa**

Tepat sebelum blok tombol (`<div className="flex flex-wrap gap-3 pt-2">`, baris 226), sisipkan:

```tsx
        {diagnosticGuide && (
          <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-4 space-y-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-red-400" />
              <span className="text-sm font-semibold text-red-300">
                Diagnosa &amp; Cara Perbaiki
              </span>
            </div>
            <p className="text-sm font-medium text-white">{diagnosticGuide.title}</p>
            <ol className="list-decimal list-inside space-y-1 text-sm text-slate-300">
              {diagnosticGuide.steps.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
            {job.diagnostic_detail && (
              <p className="text-xs text-slate-500 font-mono pt-1 border-t border-white/5">
                Detail: {job.diagnostic_detail}
              </p>
            )}
            <Link
              href={`/targets/${job.target_id}/plugin-guide`}
              className="inline-block text-sm text-cyan-400 hover:text-cyan-300"
            >
              Buka Panduan Plugin →
            </Link>
          </div>
        )}
```

(Tombol "Scan Ulang" sudah ada di blok tombol untuk status terminal — tidak perlu duplikat.)

- [ ] **Step 4: Verifikasi build**

Dari `OJSDEF-FrontEnd/`:
Run: `npm run lint && npx tsc --noEmit`
Expected: tidak ada error.

- [ ] **Step 5: Commit**

```bash
git add "app/(dashboard)/scan-management/[id]/page.tsx"
git commit -m "feat: kartu Diagnosa & Cara Perbaiki di detail scan gagal"
```

---

## Task 11: Verifikasi end-to-end (manual, VPS)

**Files:** tidak ada perubahan kode — verifikasi integrasi.

> **Sub-skill:** gunakan **superpowers:verification-before-completion** — jangan klaim selesai tanpa bukti output.

- [ ] **Step 1: Migrasi DB backend di VPS**

Di host backend: `alembic upgrade head` → konfirmasi revision `004`.

- [ ] **Step 2: Pastikan celery-beat jalan** (untuk callback timeout)

Konfirmasi service `celery-beat` aktif di docker-compose (sudah ditambahkan di Spec C-3).

- [ ] **Step 3: Skenario sukses (direct)**

Dengan plugin aktif & probe 200: buat internal scan dari dashboard.
Expected: status `completed` dalam < ~30 detik, ada temuan, log worker mengalir.

- [ ] **Step 4: Skenario gagal (fail-fast)**

Nonaktifkan plugin OJSDef di OJS, buat internal scan.
Expected: status `failed` dalam hitungan detik; kartu "Diagnosa & Cara Perbaiki" muncul dengan kode yang sesuai (mis. `PLUGIN_UNREACHABLE` / `PROBE_HTTP_500`).

- [ ] **Step 5: Tandai selesai**

Catat bukti (screenshot / HTTP code) di ringkasan. Jika semua lulus, lanjut ke `superpowers:finishing-a-development-branch`.

---

## Self-Review Notes

- **Spec coverage:** Pre-flight probe (T3-T4), fail-fast taxonomy (T1,T3), 5-min callback timeout (T5), diagnostic columns + force_heartbeat (T2), API expose (T6), plugin 500 fix (T7), plugin async (T8), frontend card (T9-T10), E2E (T11). Semua section spec tercakup.
- **Type consistency:** `diagnostic_code`/`diagnostic_detail` konsisten di model → schema → router → types/api.ts. Kode enum identik di `app/workers/diagnostics.py` dan `lib/diagnostics.ts`.
- **Reuse:** Retry memakai `useRetryScan`/tombol "Scan Ulang" yang sudah ada — tidak diduplikasi.
