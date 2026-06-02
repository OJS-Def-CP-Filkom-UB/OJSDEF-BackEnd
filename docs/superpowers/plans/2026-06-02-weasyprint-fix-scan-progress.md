# WeasyPrint Fix & Scan Progress Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix WeasyPrint 62.3 crash yang membuat scan stuck `running`, dan tambahkan step-level progress monitoring sehingga frontend menampilkan log feed real-time dari worker.

**Architecture:** Backend workers memanggil `write_progress()` di setiap tahap scan; data tersimpan di Redis key `scan_progress:{job_id}` yang sudah ada; FastAPI endpoint `GET /api/v1/scans/{id}` sudah mengembalikan field `progress` — tinggal diisi data nyata. Frontend polling TanStack Query 3 detik, mengakumulasi pesan menjadi log feed bergulir.

**Tech Stack:** FastAPI, Celery 5, Redis (asyncio), WeasyPrint 60.2, Next.js 16, TanStack Query v5, TypeScript.

> **PENTING:** Jangan jalankan test lokal (pytest, npm test, dll). User akan test manual di VPS. Cukup tulis kode + commit.

---

## File Map

**Backend — `OJSDEF-BackEnd/`**

| File | Aksi | Keterangan |
|------|------|------------|
| `requirements.txt` | Modify | `weasyprint==62.3` → `60.2` |
| `app/services/report.py` | Modify | Wrap PDF generation dalam try/except, return `None` on failure |
| `app/schemas/scans.py` | Modify | Tambah `log_type` ke `ScanProgress` |
| `app/workers/utils.py` | Modify | Tambah `write_progress()` |
| `app/workers/external_bot.py` | Modify | Tambah 7 `write_progress()` calls |
| `app/workers/internal_bot.py` | Modify | Tambah progress calls di `_setup` dan `_run` |
| `app/workers/scoring.py` | Modify | Tambah 3 `write_progress()` calls |

**Frontend — `OJSDEF-FrontEnd/`**

| File | Aksi | Keterangan |
|------|------|------------|
| `types/api.ts` | Modify | Tambah `log_type` ke `ScanProgress` interface |
| `hooks/use-scans.ts` | Modify | `refetchInterval` 4000 → 3000 |
| `app/(dashboard)/scanning/page.tsx` | Modify | Enhance `ScanJobMonitor` dengan log feed + `computeOverallPct` |
| `components/scanning/ScanningPage.tsx` | Delete | Prototype lama, tidak digunakan |
| `app/(dashboard)/export/page.tsx` | Modify | Update pesan empty state untuk cover kasus PDF gagal |

---

## Task 1: Fix WeasyPrint — downgrade versi + graceful fallback

**Files:**
- Modify: `requirements.txt:33`
- Modify: `app/services/report.py`

- [ ] **Step 1: Downgrade WeasyPrint di requirements.txt**

Ganti baris 33:

```
weasyprint==60.2
```

- [ ] **Step 2: Tulis ulang app/services/report.py selengkapnya**

```python
import uuid
import os
import logging
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
import boto3
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import ScanJob, OJSTarget, Report
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)
_jinja = Environment(loader=FileSystemLoader(
    os.path.join(os.path.dirname(__file__), "..", "templates")
))
SEVERITY_LABEL = {"critical": "Kritis", "high": "Berbahaya", "medium": "Perhatian", "low": "Aman"}


def _s3():
    return boto3.client(
        "s3",
        endpoint_url=f"{'https' if settings.minio_use_ssl else 'http'}://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )


async def generate_pdf_report(session: AsyncSession, job: ScanJob, findings: list) -> Report | None:
    try:
        target = (await session.execute(
            select(OJSTarget).where(OJSTarget.id == job.target_id)
        )).scalar_one()
        html = _jinja.get_template("report.html").render(
            job=job, target=target, findings=findings, severity_label=SEVERITY_LABEL,
        )
        pdf = HTML(string=html).write_pdf()
        path = f"{job.tenant_id}/{job.id}/report.pdf"
        _s3().put_object(
            Bucket=settings.minio_bucket, Key=path,
            Body=pdf, ContentType="application/pdf",
        )
        report = Report(
            id=uuid.uuid4(), tenant_id=job.tenant_id, job_id=job.id,
            format="pdf", storage_path=path, file_size_bytes=len(pdf),
        )
        session.add(report)
        return report
    except Exception as e:
        logger.warning("PDF generation failed for job %s: %s", job.id, e)
        return None
```

- [ ] **Step 3: Commit**

```bash
git add requirements.txt app/services/report.py
git commit -m "fix: downgrade weasyprint to 60.2, add graceful PDF fallback"
```

---

## Task 2: Tambah `write_progress()` ke utils.py

**Files:**
- Modify: `app/workers/utils.py`

- [ ] **Step 1: Tulis ulang app/workers/utils.py selengkapnya**

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


async def write_progress(
    job_id: str,
    stage: str,
    step: int,
    total: int,
    message: str,
    log_type: str = "INFO",
) -> None:
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        raw = await r.get(f"scan_progress:{job_id}")
        data = json.loads(raw) if raw else {}
        data.update({
            "stage": stage,
            "current_step": step,
            "total_steps": total,
            "message": message,
            "log_type": log_type,
        })
        await r.setex(f"scan_progress:{job_id}", 3600, json.dumps(data))
    finally:
        await r.aclose()
```

- [ ] **Step 2: Commit**

```bash
git add app/workers/utils.py
git commit -m "feat: add write_progress() helper to workers/utils"
```

---

## Task 3: Tambah `log_type` ke ScanProgress schema

**Files:**
- Modify: `app/schemas/scans.py`

- [ ] **Step 1: Tulis ulang app/schemas/scans.py selengkapnya**

```python
from typing import Literal
from pydantic import BaseModel
from datetime import datetime


class StartScanRequest(BaseModel):
    target_id: str
    scan_type: str  # internal|external|full


class ScanProgress(BaseModel):
    stage: Literal["external_scan", "internal_audit", "scoring", "report_gen"]
    current_step: int
    total_steps: int
    message: str
    log_type: Literal["INFO", "TASK", "DONE", "WARN"] = "INFO"


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
    progress: ScanProgress | None = None
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

- [ ] **Step 2: Commit**

```bash
git add app/schemas/scans.py
git commit -m "feat: add log_type field to ScanProgress schema"
```

---

## Task 4: Wire progress ke external_bot.py

**Files:**
- Modify: `app/workers/external_bot.py`

- [ ] **Step 1: Tulis ulang app/workers/external_bot.py selengkapnya**

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
from app.workers.utils import _try_trigger_scoring, write_progress
import redis.asyncio as aioredis
from app.config import get_settings

settings = get_settings()


async def _run_external_scan(job_id: str, target_url: str):
    hostname = urlparse(target_url).hostname

    await write_progress(job_id, "external_scan", 1, 7, "Mendeteksi versi OJS dan fingerprint...", "TASK")
    ojs_version, fp = await scan_fingerprint(target_url)

    await write_progress(job_id, "external_scan", 2, 7, "Memeriksa sertifikat SSL/TLS...", "TASK")
    ssl_findings = scan_ssl(hostname) if hostname else []

    await write_progress(job_id, "external_scan", 3, 7, "Menganalisis HTTP security headers...", "TASK")
    header_findings = await scan_headers(target_url)

    await write_progress(job_id, "external_scan", 4, 7, "Menguji kerentanan yang diketahui...", "TASK")
    vuln_findings = await scan_vulnerabilities(target_url)

    await write_progress(job_id, "external_scan", 5, 7, "Memeriksa direktori terbuka...", "TASK")
    dir_findings = await scan_open_dirs(target_url)

    await write_progress(job_id, "external_scan", 6, 7, "Mencocokkan CVE dari NVD...", "TASK")
    cve_findings = await scan_cve(ojs_version)

    all_findings = fp + ssl_findings + header_findings + vuln_findings + dir_findings + cve_findings

    async with make_worker_session() as session:
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

    await write_progress(
        job_id, "external_scan", 7, 7,
        f"Pemindaian eksternal selesai — {len(all_findings)} temuan", "DONE",
    )
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

- [ ] **Step 2: Commit**

```bash
git add app/workers/external_bot.py
git commit -m "feat: add step-level progress to external scanner"
```

---

## Task 5: Wire progress ke internal_bot.py

**Files:**
- Modify: `app/workers/internal_bot.py`

- [ ] **Step 1: Tulis ulang app/workers/internal_bot.py selengkapnya**

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
from app.workers.utils import _try_trigger_scoring, write_progress
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
    """POST to plugin's /trigger endpoint (Direct Mode). Returns True on HTTP 202."""
    body = json.dumps({"job_id": job_id, "scan_modules": DEFAULT_MODULES}).encode()
    headers = _sign_for_plugin(api_key, body)
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=True) as client:
            resp = await client.post(trigger_endpoint, content=body, headers=headers)
        return resp.status_code == 202
    except Exception:
        return False


async def _setup_internal_scan(job_id: str, target_id: str) -> None:
    """Trigger the plugin via Direct or Heartbeat mode."""
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

    await write_progress(job_id, "internal_audit", 1, 2, "Mengirim permintaan audit ke plugin OJS...", "TASK")

    if connection_mode == "direct" and trigger_ep and api_key:
        success = await _trigger_plugin_direct(trigger_ep, api_key, job_id)
        if success:
            await write_progress(job_id, "internal_audit", 2, 2, "Plugin merespons, menunggu callback...", "INFO")
            return

    await write_progress(job_id, "internal_audit", 2, 2, "Mode heartbeat — menunggu jadwal berikutnya...", "INFO")
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
    """Process plugin-provided scan data and persist findings."""
    await write_progress(job_id, "internal_audit", 1, 7, "Plugin callback diterima, memproses data audit...", "INFO")

    await write_progress(job_id, "internal_audit", 2, 7, "Menganalisis konfigurasi OJS...", "TASK")
    config_findings = scan_config(data.get("config", {}))

    await write_progress(job_id, "internal_audit", 3, 7, "Memeriksa plugin yang terpasang...", "TASK")
    plugin_findings = scan_plugins(data.get("plugins", []))

    await write_progress(job_id, "internal_audit", 4, 7, "Mengaudit RBAC dan pengguna...", "TASK")
    rbac_findings = scan_rbac(data.get("users", []))

    await write_progress(job_id, "internal_audit", 5, 7, "Memeriksa integritas file...", "TASK")
    file_findings = scan_file_integrity(data.get("file_integrity", {}))

    await write_progress(job_id, "internal_audit", 6, 7, "Mendeteksi konten mencurigakan...", "TASK")
    content_findings = scan_content(data.get("articles", []))
    db_findings = scan_db_security(data.get("db_config", {}))

    all_findings = (
        config_findings + plugin_findings + rbac_findings
        + file_findings + content_findings + db_findings
    )

    async with make_worker_session() as session:
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

    await write_progress(
        job_id, "internal_audit", 7, 7,
        f"Pemindaian internal selesai — {len(all_findings)} temuan", "DONE",
    )

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
    asyncio.run(_setup_internal_scan(job_id, target_id))


@celery_app.task(
    name="app.workers.internal_bot.process_plugin_data_task",
    bind=True, max_retries=3,
    autoretry_for=(Exception,), default_retry_delay=60,
)
def process_plugin_data_task(self, job_id: str, data: dict):
    asyncio.run(_run_internal_scan(job_id, data))
```

- [ ] **Step 2: Commit**

```bash
git add app/workers/internal_bot.py
git commit -m "feat: add step-level progress to internal scanner"
```

---

## Task 6: Wire progress ke scoring.py

**Files:**
- Modify: `app/workers/scoring.py`

- [ ] **Step 1: Tulis ulang app/workers/scoring.py selengkapnya**

```python
import asyncio
import json
from datetime import datetime, timezone
from sqlalchemy import select
from app.celery_app import celery_app
from app.database import make_worker_session
from app.models import ScanJob, ScanFinding
from app.services.report import generate_pdf_report
from app.workers.utils import write_progress
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
    await write_progress(job_id, "scoring", 1, 3, "Menghitung skor risiko CVSS...", "TASK")

    async with make_worker_session() as session:
        job = (await session.execute(select(ScanJob).where(ScanJob.id == job_id))).scalar_one()
        findings = (await session.execute(
            select(ScanFinding).where(
                ScanFinding.job_id == job_id,
                ScanFinding.is_false_positive == False,
            )
        )).scalars().all()

        counts = {s: sum(1 for f in findings if f.severity == s)
                  for s in ("critical", "high", "medium", "low")}
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

        await write_progress(job_id, "scoring", 2, 3, "Membuat laporan PDF...", "TASK")
        await generate_pdf_report(session, job, sorted_findings)
        await session.commit()

    await write_progress(job_id, "scoring", 3, 3, "Scan selesai", "DONE")

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    await r.delete(f"dashboard_stats:{str(job.tenant_id)}")
    raw = await r.get(f"scan_progress:{job_id}")
    progress = json.loads(raw) if raw else {}
    progress["scoring_done"] = True
    await r.setex(f"scan_progress:{job_id}", 3600, json.dumps(progress))
    await r.aclose()

    if counts["critical"] > 0:
        crit_ids = [str(f.id) for f in findings if f.severity == "critical"]
        celery_app.send_task(
            "app.workers.notify.send_critical_alert",
            args=[job_id, crit_ids], queue="notifications",
        )


@celery_app.task(name="app.workers.scoring.scoring_task",
                 bind=True, max_retries=3, autoretry_for=(Exception,), default_retry_delay=60)
def scoring_task(self, job_id: str):
    asyncio.run(_run_scoring(job_id))
```

- [ ] **Step 2: Commit**

```bash
git add app/workers/scoring.py
git commit -m "feat: add step-level progress to scoring worker"
```

---

## Task 7: Frontend — tambah `log_type` ke types + turunkan polling interval

**Repo:** `OJSDEF-FrontEnd/`

**Files:**
- Modify: `types/api.ts:64-69`
- Modify: `hooks/use-scans.ts:21-24`

- [ ] **Step 1: Ganti blok ScanProgress di types/api.ts (baris 64–69)**

```typescript
export interface ScanProgress {
  stage: 'external_scan' | 'internal_audit' | 'scoring' | 'report_gen'
  current_step: number
  total_steps: number
  message: string
  log_type: 'INFO' | 'TASK' | 'DONE' | 'WARN'
}
```

- [ ] **Step 2: Ganti refetchInterval di hooks/use-scans.ts (baris 21–24)**

```typescript
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'running' || status === 'queued' ? 3000 : false
    },
```

- [ ] **Step 3: Commit**

```bash
git add types/api.ts hooks/use-scans.ts
git commit -m "feat: add log_type to ScanProgress type, reduce poll interval to 3s"
```

---

## Task 8: Frontend — enhance ScanJobMonitor dengan log feed

**Repo:** `OJSDEF-FrontEnd/`

**Files:**
- Modify: `app/(dashboard)/scanning/page.tsx`

- [ ] **Step 1: Tulis ulang app/(dashboard)/scanning/page.tsx selengkapnya**

```typescript
'use client'

import { useSearchParams } from 'next/navigation'
import { Suspense, useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import { useScans, useScanJob, useStartScan } from '@/hooks/use-scans'
import { useTargets } from '@/hooks/use-targets'
import { SCAN_STATUS_LABELS, SCAN_STATUS_COLORS, SCAN_TYPE_LABELS } from '@/lib/utils'
import { RoleGuard } from '@/components/shared/RoleGuard'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { ScanJob, ScanType } from '@/types/api'

interface LogEntry {
  time: string
  type: 'INFO' | 'TASK' | 'DONE' | 'WARN'
  msg: string
}

const LOG_COLOR: Record<string, string> = {
  INFO: '#58a6ff',
  TASK: '#e3b341',
  DONE: '#3fb950',
  WARN: '#f85149',
}

function getTime(): string {
  const now = new Date()
  return [now.getHours(), now.getMinutes(), now.getSeconds()]
    .map((n) => String(n).padStart(2, '0'))
    .join(':')
}

function computeOverallPct(job: ScanJob): number {
  if (job.status === 'completed') return 100
  if (!job.progress) return 0
  const { stage, current_step, total_steps } = job.progress
  const ratio = current_step / total_steps
  const type = job.scan_type
  if (type === 'full') {
    if (stage === 'external_scan') return Math.round(ratio * 40)
    if (stage === 'internal_audit') return Math.round(40 + ratio * 30)
    if (stage === 'scoring') return Math.round(70 + ratio * 30)
  } else if (type === 'external') {
    if (stage === 'external_scan') return Math.round(ratio * 80)
    if (stage === 'scoring') return Math.round(80 + ratio * 20)
  } else {
    if (stage === 'internal_audit') return Math.round(ratio * 80)
    if (stage === 'scoring') return Math.round(80 + ratio * 20)
  }
  return 0
}

function StartScanForm() {
  const { data: targets } = useTargets()
  const startScan = useStartScan()
  const [targetId, setTargetId] = useState('')
  const [scanType, setScanType] = useState<ScanType>('external')
  const [error, setError] = useState<string | null>(null)

  async function handleStart() {
    if (!targetId) { setError('Pilih target terlebih dahulu'); return }
    setError(null)
    try {
      await startScan.mutateAsync({ targetId, scanType })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Gagal memulai scan')
    }
  }

  return (
    <div className="glass-dark rounded-xl border border-white/5 p-6 space-y-4">
      <h2 className="text-white font-semibold">Mulai Scan Baru</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="space-y-2">
          <label className="text-slate-400 text-sm">Target OJS</label>
          <Select value={targetId} onValueChange={setTargetId}>
            <SelectTrigger className="bg-slate-900/60 border-white/10 text-white">
              <SelectValue placeholder="Pilih target..." />
            </SelectTrigger>
            <SelectContent>
              {targets?.map((t) => (
                <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <label className="text-slate-400 text-sm">Tipe Scan</label>
          <Select value={scanType} onValueChange={(v: string) => setScanType(v as ScanType)}>
            <SelectTrigger className="bg-slate-900/60 border-white/10 text-white">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="internal">Internal</SelectItem>
              <SelectItem value="external">Eksternal</SelectItem>
              <SelectItem value="full">Audit Penuh</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
      {error && <p className="text-red-400 text-sm">{error}</p>}
      <Button
        onClick={handleStart}
        disabled={startScan.isPending}
        className="bg-primary hover:bg-primary/90"
      >
        {startScan.isPending ? 'Memulai...' : 'Mulai Scan'}
      </Button>
    </div>
  )
}

function ScanJobMonitor({ jobId }: { jobId: string }) {
  const { data: job, isLoading } = useScanJob(jobId)
  const notifiedRef = useRef(false)
  const prevMsgRef = useRef<string | null>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const [showCompletedBanner, setShowCompletedBanner] = useState(false)
  const [logEntries, setLogEntries] = useState<LogEntry[]>([])

  useEffect(() => {
    const msg = job?.progress?.message
    if (msg && msg !== prevMsgRef.current) {
      prevMsgRef.current = msg
      setLogEntries((prev) => [
        ...prev,
        {
          time: getTime(),
          type: (job!.progress!.log_type ?? 'INFO') as LogEntry['type'],
          msg,
        },
      ])
    }
  }, [job?.progress?.message])

  useEffect(() => {
    if (job?.status === 'completed' && !notifiedRef.current) {
      notifiedRef.current = true
      setShowCompletedBanner(true)
      setLogEntries((prev) => {
        const last = prev[prev.length - 1]
        if (!last || last.msg !== 'Scan selesai') {
          return [...prev, { time: getTime(), type: 'DONE', msg: 'Scan selesai' }]
        }
        return prev
      })
    }
  }, [job?.status])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logEntries])

  if (isLoading) return <div className="glass-dark rounded-xl border border-white/5 p-6 animate-pulse h-40" />
  if (!job) return null

  const progressPct = computeOverallPct(job)
  const statusLabel = job.progress?.message ?? (job.status === 'completed' ? 'Selesai' : 'Menunggu')
  const isRunning = job.status === 'running' || job.status === 'queued'

  return (
    <div className="space-y-4">
      <div className="glass-dark rounded-xl border border-white/5 p-6 space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-white font-semibold">Scan ID: {job.id.slice(0, 8)}…</h2>
            <p className="text-slate-400 text-sm">{SCAN_TYPE_LABELS[job.scan_type]}</p>
          </div>
          <span className={`text-sm font-medium ${SCAN_STATUS_COLORS[job.status]}`}>
            {SCAN_STATUS_LABELS[job.status]}
          </span>
        </div>

        {/* Progress bar */}
        <div className="space-y-2">
          <div className="flex justify-between text-xs text-slate-500">
            <span>{statusLabel}</span>
            <span>{progressPct}%</span>
          </div>
          <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-primary rounded-full transition-all duration-500"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {/* Log feed */}
        {logEntries.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              {isRunning && (
                <div style={{
                  width: 7, height: 7, borderRadius: '50%',
                  background: '#00e5cc', animation: 'pulse-dot 1.5s infinite',
                }} />
              )}
              <span style={{
                fontSize: 11, color: '#8b949e',
                textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600,
              }}>
                Worker Log
              </span>
            </div>
            <div
              ref={logRef}
              style={{
                background: '#0a0f1a',
                borderRadius: 8,
                border: '1px solid rgba(255,255,255,0.06)',
                padding: '10px 14px',
                overflowY: 'auto',
                fontFamily: 'var(--font-geist-mono, monospace)',
                fontSize: 11.5,
                lineHeight: 1.8,
                maxHeight: 200,
              }}
            >
              {logEntries.map((entry, i) => {
                const isLast = i === logEntries.length - 1
                return (
                  <div
                    key={i}
                    style={{
                      padding: '1px 0 1px 8px',
                      borderLeft: isLast && isRunning ? '2px solid #00e5cc' : '2px solid transparent',
                      background: isLast && isRunning ? 'rgba(0,229,204,0.04)' : 'transparent',
                      borderRadius: 2,
                    }}
                  >
                    <span style={{ color: '#4a5568', marginRight: 6 }}>[{entry.time}]</span>
                    <span style={{
                      color: LOG_COLOR[entry.type] ?? '#8b949e',
                      fontWeight: 700, marginRight: 4,
                    }}>
                      {entry.type}
                    </span>
                    <span style={{ color: '#c9d1d9' }}>{entry.msg}</span>
                  </div>
                )
              })}
              {isRunning && (
                <span style={{
                  display: 'inline-block', width: 7, height: 13,
                  background: '#00e5cc', verticalAlign: 'text-bottom',
                  animation: 'blink 1s infinite', borderRadius: 1, marginLeft: 2,
                }} />
              )}
            </div>
          </div>
        )}

        {/* Counts — shown when completed */}
        {job.status === 'completed' && (
          <div className="grid grid-cols-4 gap-3 pt-2 border-t border-white/5">
            <div className="text-center">
              <p className="text-red-400 text-xl font-bold">{job.critical_count}</p>
              <p className="text-slate-500 text-xs">Kritis</p>
            </div>
            <div className="text-center">
              <p className="text-orange-400 text-xl font-bold">{job.high_count}</p>
              <p className="text-slate-500 text-xs">Berbahaya</p>
            </div>
            <div className="text-center">
              <p className="text-yellow-400 text-xl font-bold">{job.medium_count}</p>
              <p className="text-slate-500 text-xs">Perhatian</p>
            </div>
            <div className="text-center">
              <p className="text-green-400 text-xl font-bold">{job.low_count}</p>
              <p className="text-slate-500 text-xs">Aman</p>
            </div>
          </div>
        )}
      </div>

      {/* CTA Lihat Laporan */}
      {(job.status === 'completed' || showCompletedBanner) && (
        <div className="glass-dark rounded-xl border border-green-500/20 p-6 text-center space-y-4">
          <p className="text-white font-semibold">Scan selesai</p>
          <p className="text-slate-400 text-sm">
            {(job.critical_count ?? 0) + (job.high_count ?? 0) + (job.medium_count ?? 0) + (job.low_count ?? 0)} temuan
            · Risk score: {job.overall_score ?? '—'}
          </p>
          <Link href={`/vulnerability-report?jobId=${job.id}`}>
            <Button className="bg-primary hover:bg-primary/90">Lihat Laporan</Button>
          </Link>
        </div>
      )}
    </div>
  )
}

function RecentJobsList() {
  const { data: scans } = useScans({ limit: 10 })
  const activeJob = scans?.find((s) => s.status === 'running' || s.status === 'queued')
  if (!activeJob) return null
  return <ScanJobMonitor jobId={activeJob.id} />
}

function ScanningContent() {
  const searchParams = useSearchParams()
  const jobId = searchParams.get('jobId')

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Mulai Scan</h1>
        <p className="text-slate-400 mt-1 text-sm">Jalankan pemindaian keamanan terhadap instalasi OJS Anda</p>
      </div>
      <RoleGuard allowedRoles={['saas_admin', 'admin_ojs']}>
        <StartScanForm />
      </RoleGuard>
      {jobId ? <ScanJobMonitor jobId={jobId} /> : <RecentJobsList />}
    </div>
  )
}

export default function ScanningPage() {
  return (
    <Suspense fallback={<div className="h-64 bg-slate-800 rounded-xl animate-pulse" />}>
      <ScanningContent />
    </Suspense>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add "app/(dashboard)/scanning/page.tsx"
git commit -m "feat: add real-time worker log feed to ScanJobMonitor"
```

---

## Task 9: Frontend — hapus prototype lama + update export empty state

**Repo:** `OJSDEF-FrontEnd/`

**Files:**
- Delete: `components/scanning/ScanningPage.tsx`
- Modify: `app/(dashboard)/export/page.tsx:34-38`

- [ ] **Step 1: Hapus ScanningPage.tsx prototype**

Hapus file `components/scanning/ScanningPage.tsx`.

- [ ] **Step 2: Ganti baris 34–38 di export/page.tsx**

```typescript
        ) : !reports?.length ? (
          <div className="p-8 text-center text-slate-500">
            <FileText className="h-8 w-8 mx-auto mb-2 opacity-40" />
            <p>Belum ada laporan PDF. Jika scan sudah selesai namun laporan tidak muncul, coba jalankan scan ulang.</p>
          </div>
```

- [ ] **Step 3: Commit**

```bash
git rm components/scanning/ScanningPage.tsx
git add "app/(dashboard)/export/page.tsx"
git commit -m "chore: remove unused ScanningPage mock, update export empty state message"
```

---

## Self-Review Checklist

- [x] **Spec coverage**: WeasyPrint downgrade ✅ graceful fallback ✅ `write_progress()` ✅ `log_type` schema ✅ external 7 steps ✅ internal setup 2 steps ✅ internal run 7 steps ✅ scoring 3 steps ✅ frontend types ✅ poll interval ✅ log feed UI ✅ `computeOverallPct` ✅ delete prototype ✅ export empty state ✅
- [x] **No placeholders**: Semua langkah berisi kode lengkap — tidak ada TBD/TODO
- [x] **Type consistency**: `write_progress(job_id, stage, step, total, message, log_type)` signature sama di semua 3 worker. `LogEntry['type']` union `'INFO'|'TASK'|'DONE'|'WARN'` sama dengan `log_type` backend. `computeOverallPct(job: ScanJob)` menggunakan `job.scan_type` (type `ScanType`) dan `job.progress.stage` (dari `ScanProgress.stage`) — keduanya sudah defined di `types/api.ts`.
