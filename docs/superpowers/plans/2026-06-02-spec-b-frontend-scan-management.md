# Spec B — Frontend Scan Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tambah cancel/retry scan, halaman detail scan baru, navigasi dari scan list, dan vulnerability-report dengan summary + scan selector.

**Architecture:** Backend menambah endpoint `POST /api/v1/scans/{id}/cancel` dan cooperative cancellation di workers. Frontend menambah halaman detail `/scan-management/[id]`, menyederhanakan `/scanning`, menambah navigasi di scan list, dan memperkaya `/vulnerability-report` dengan summary + selector.

**Tech Stack:** FastAPI, Celery, Next.js 16 App Router, TanStack Query v5, ShadCN UI, TypeScript

**Catatan Testing:** Backend tidak dapat di-test lokal. Verifikasi via Python syntax check. Frontend: `npx tsc --noEmit` untuk type check. Test manual di VPS/browser setelah deploy.

---

## File Map

| File | Aksi | Repo |
|------|------|------|
| `app/workers/utils.py` | Edit — tambah `_check_cancelled()` | BackEnd |
| `app/routers/scans.py` | Edit — tambah `POST /{id}/cancel` | BackEnd |
| `app/workers/external_bot.py` | Edit — cek cancelled setiap step | BackEnd |
| `app/workers/internal_bot.py` | Edit — cek cancelled setiap step | BackEnd |
| `app/workers/scoring.py` | Edit — cek cancelled di awal | BackEnd |
| `types/api.ts` | Edit — tambah `'cancelled'` ke ScanStatus | FrontEnd |
| `lib/utils.ts` | Edit — label & warna `cancelled` | FrontEnd |
| `hooks/use-scans.ts` | Edit — `useCancelScan`, `useRetryScan` | FrontEnd |
| `app/(dashboard)/scan-management/[id]/page.tsx` | **Buat baru** | FrontEnd |
| `app/(dashboard)/scanning/page.tsx` | Edit — redirect + hapus monitor | FrontEnd |
| `app/(dashboard)/scan-management/page.tsx` | Edit — clickable rows + target name | FrontEnd |
| `app/(dashboard)/vulnerability-report/page.tsx` | Edit — ScanSummary + ScanSelector | FrontEnd |

---

### Task 1: `_check_cancelled()` helper di workers/utils.py

**Context:** Helper ini dipanggil worker sebelum setiap step. Membaca status job dari DB — jika `cancelled`, worker return early. Cooperative cancellation: aman karena tidak memotong DB write di tengah jalan. Import dilakukan di dalam fungsi untuk menghindari masalah circular import order saat module di-load.

**Files:**
- Modify: `OJSDEF-BackEnd/app/workers/utils.py`

- [ ] **Step 1: Tambah `_check_cancelled()` di akhir utils.py**

Buka `OJSDEF-BackEnd/app/workers/utils.py`. Tambahkan fungsi baru di bawah `write_progress()`:

```python
async def _check_cancelled(job_id: str) -> bool:
    from app.models import ScanJob
    from app.database import make_worker_session
    from sqlalchemy import select
    async with make_worker_session() as session:
        job = (await session.execute(
            select(ScanJob).where(ScanJob.id == job_id)
        )).scalar_one_or_none()
        return job is not None and job.status == "cancelled"
```

- [ ] **Step 2: Syntax check**

Dari `OJSDEF-BackEnd/`:
```bash
python -c "import ast; ast.parse(open('app/workers/utils.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/workers/utils.py
git commit -m "feat: add _check_cancelled() helper for cooperative worker cancellation"
```

---

### Task 2: Cancel endpoint di routers/scans.py

**Context:** Endpoint baru `POST /api/v1/scans/{job_id}/cancel`. Hanya bisa membatalkan job `queued` atau `running`. Set `status='cancelled'` dan `completed_at`. Catat di audit log.

**Files:**
- Modify: `OJSDEF-BackEnd/app/routers/scans.py`

- [ ] **Step 1: Tambah cancel endpoint**

Buka `OJSDEF-BackEnd/app/routers/scans.py`. Tambahkan endpoint berikut setelah semua endpoint yang ada (di bagian akhir file, sebelum atau setelah endpoint findings):

```python
@router.post("/{job_id}/cancel", status_code=200)
async def cancel_scan(
    job_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = (await db.execute(
        select(ScanJob).where(ScanJob.id == job_id)
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
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/routers/scans.py
git commit -m "feat: add POST /api/v1/scans/{id}/cancel endpoint"
```

---

### Task 3: Cooperative cancellation di external_bot.py

**Context:** Tambah `_check_cancelled` sebelum setiap step di `_run_external_scan`. Jika job di-cancel, worker return early tanpa menyimpan findings.

**Files:**
- Modify: `OJSDEF-BackEnd/app/workers/external_bot.py`

- [ ] **Step 1: Tambah `_check_cancelled` ke import**

Ubah baris import utils di `external_bot.py`:
```python
# Sebelum:
from app.workers.utils import _try_trigger_scoring, write_progress

# Sesudah:
from app.workers.utils import _try_trigger_scoring, write_progress, _check_cancelled
```

- [ ] **Step 2: Tambah cek sebelum setiap write_progress di `_run_external_scan`**

Tambahkan `if await _check_cancelled(job_id): return` sebelum setiap `await write_progress(...)` call. Contoh pola:

```python
async def _run_external_scan(job_id: str, target_url: str):
    hostname = urlparse(target_url).hostname

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 1, 7, "Mendeteksi versi OJS dan fingerprint...", "TASK")
    ojs_version, fp = await scan_fingerprint(target_url)

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 2, 7, "Memeriksa sertifikat SSL/TLS...", "TASK")
    ssl_findings = scan_ssl(hostname) if hostname else []

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 3, 7, "Menganalisis HTTP security headers...", "TASK")
    header_findings = await scan_headers(target_url)

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 4, 7, "Menguji kerentanan yang diketahui...", "TASK")
    vuln_findings = await scan_vulnerabilities(target_url)

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 5, 7, "Memeriksa direktori terbuka...", "TASK")
    dir_findings = await scan_open_dirs(target_url)

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 6, 7, "Mencocokkan CVE dari NVD...", "TASK")
    cve_findings = await scan_cve(ojs_version)

    # sisa fungsi (DB write, redis, trigger scoring) tidak berubah
```

- [ ] **Step 3: Syntax check**

```bash
python -c "import ast; ast.parse(open('app/workers/external_bot.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/workers/external_bot.py
git commit -m "feat: cooperative cancellation checks in external_bot"
```

---

### Task 4: Cooperative cancellation di internal_bot.py dan scoring.py

**Context:** Pola sama dengan Task 3.

**Files:**
- Modify: `OJSDEF-BackEnd/app/workers/internal_bot.py`
- Modify: `OJSDEF-BackEnd/app/workers/scoring.py`

- [ ] **Step 1: Update import dan tambah cek di internal_bot.py**

Di `internal_bot.py`, ubah import utils:
```python
# Sebelum:
from app.workers.utils import _try_trigger_scoring, write_progress

# Sesudah:
from app.workers.utils import _try_trigger_scoring, write_progress, _check_cancelled
```

Di fungsi `_run_internal_scan`, tambahkan `if await _check_cancelled(job_id): return` sebelum setiap `await write_progress(...)`. Contoh untuk step pertama:
```python
async def _run_internal_scan(job_id: str, audit_data: dict):
    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 1, 7, "Plugin callback diterima...", "INFO")
    # ... setiap write_progress berikutnya juga ditambah cek serupa
```

- [ ] **Step 2: Update import dan tambah cek di scoring.py**

Di `scoring.py`, ubah import utils:
```python
# Sebelum:
from app.workers.utils import write_progress

# Sesudah:
from app.workers.utils import write_progress, _check_cancelled
```

Di awal fungsi `_run_scoring`:
```python
async def _run_scoring(job_id: str):
    if await _check_cancelled(job_id): return
    await write_progress(job_id, "scoring", 1, 3, "Menghitung skor risiko CVSS...", "TASK")
    # ... sisa fungsi tidak berubah
```

- [ ] **Step 3: Syntax check**

```bash
python -c "import ast; ast.parse(open('app/workers/internal_bot.py').read()); print('internal_bot OK')"
python -c "import ast; ast.parse(open('app/workers/scoring.py').read()); print('scoring OK')"
```
Expected: `internal_bot OK` dan `scoring OK`

- [ ] **Step 4: Commit**

```bash
git add app/workers/internal_bot.py app/workers/scoring.py
git commit -m "feat: cooperative cancellation checks in internal_bot and scoring workers"
```

---

### Task 5: Frontend types dan utils untuk status `cancelled`

**Context:** `ScanStatus` saat ini: `'queued' | 'running' | 'completed' | 'failed'`. `SCAN_STATUS_LABELS` dan `SCAN_STATUS_COLORS` pakai `Record<ScanStatus, string>` — TypeScript error jika `cancelled` ditambah ke type tapi tidak ke record.

**Files:**
- Modify: `OJSDEF-FrontEnd/types/api.ts`
- Modify: `OJSDEF-FrontEnd/lib/utils.ts`

- [ ] **Step 1: Tambah `'cancelled'` ke ScanStatus**

Di `types/api.ts`, ubah:
```typescript
// Sebelum:
export type ScanStatus = 'queued' | 'running' | 'completed' | 'failed'

// Sesudah:
export type ScanStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
```

- [ ] **Step 2: Tambah entry `cancelled` di lib/utils.ts**

Di `lib/utils.ts`, tambah `cancelled` ke kedua record:
```typescript
export const SCAN_STATUS_LABELS: Record<ScanStatus, string> = {
  queued: 'Menunggu',
  running: 'Berjalan',
  completed: 'Selesai',
  failed: 'Gagal',
  cancelled: 'Dibatalkan',
}

export const SCAN_STATUS_COLORS: Record<ScanStatus, string> = {
  queued: 'text-yellow-400',
  running: 'text-cyan-400',
  completed: 'text-green-400',
  failed: 'text-red-400',
  cancelled: 'text-slate-400',
}
```

- [ ] **Step 3: TypeScript check**

Dari `OJSDEF-FrontEnd/`:
```bash
npx tsc --noEmit 2>&1 | head -20
```
Expected: tidak ada error terkait `ScanStatus`.

- [ ] **Step 4: Commit**

```bash
git add types/api.ts lib/utils.ts
git commit -m "feat: add cancelled to ScanStatus type and status label/color maps"
```

---

### Task 6: Tambah `useCancelScan` dan `useRetryScan` di hooks/use-scans.ts

**Context:** `useCancelScan` memanggil `POST /api/v1/scans/{id}/cancel`. `useRetryScan` membuat scan baru dengan target + tipe yang sama. Keduanya invalidate `['scans']` setelah sukses.

**Files:**
- Modify: `OJSDEF-FrontEnd/hooks/use-scans.ts`

- [ ] **Step 1: Tambah dua mutation di use-scans.ts**

Tulis ulang `OJSDEF-FrontEnd/hooks/use-scans.ts`:

```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { ScanJob, ScanType } from '@/types/api'

export function useScans(params?: { limit?: number }) {
  const limit = params?.limit
  return useQuery({
    queryKey: ['scans', { limit }],
    queryFn: () => {
      const url = limit ? `/api/v1/scans?limit=${limit}` : '/api/v1/scans'
      return api.get<ScanJob[]>(url).then((r) => r.data)
    },
  })
}

export function useScanJob(jobId: string) {
  return useQuery({
    queryKey: ['scans', jobId],
    queryFn: () => api.get<ScanJob>(`/api/v1/scans/${jobId}`).then((r) => r.data),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'running' || status === 'queued' ? 3000 : false
    },
  })
}

export function useStartScan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ targetId, scanType }: { targetId: string; scanType: ScanType }) =>
      api
        .post<ScanJob>('/api/v1/scans', { target_id: targetId, scan_type: scanType })
        .then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scans'] }),
  })
}

export function useCancelScan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) =>
      api.post(`/api/v1/scans/${jobId}/cancel`).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scans'] }),
  })
}

export function useRetryScan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ targetId, scanType }: { targetId: string; scanType: ScanType }) =>
      api
        .post<ScanJob>('/api/v1/scans', { target_id: targetId, scan_type: scanType })
        .then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scans'] }),
  })
}
```

- [ ] **Step 2: TypeScript check**

```bash
npx tsc --noEmit 2>&1 | head -20
```
Expected: tidak ada error.

- [ ] **Step 3: Commit**

```bash
git add hooks/use-scans.ts
git commit -m "feat: add useCancelScan and useRetryScan hooks"
```

---

### Task 7: Halaman detail scan `/scan-management/[id]/page.tsx`

**Context:** Halaman baru dengan live progress monitor, tombol cancel/retry, dan link ke laporan. Logic progress bar dan log feed identik dengan `ScanJobMonitor` di `scanning/page.tsx` (copy dan adaptasi).

**Files:**
- Create: `OJSDEF-FrontEnd/app/(dashboard)/scan-management/[id]/page.tsx`

- [ ] **Step 1: Buat file baru**

Buat `OJSDEF-FrontEnd/app/(dashboard)/scan-management/[id]/page.tsx`:

```typescript
'use client'

import { useParams, useRouter } from 'next/navigation'
import { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'
import { useScanJob, useCancelScan, useRetryScan } from '@/hooks/use-scans'
import { useTargets } from '@/hooks/use-targets'
import { SCAN_STATUS_LABELS, SCAN_STATUS_COLORS, SCAN_TYPE_LABELS } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import type { ScanJob } from '@/types/api'

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

export default function ScanDetailPage() {
  const params = useParams()
  const router = useRouter()
  const jobId = params.id as string

  const { data: job, isLoading } = useScanJob(jobId)
  const { data: targets } = useTargets()
  const cancelScan = useCancelScan()
  const retryScan = useRetryScan()

  const [logEntries, setLogEntries] = useState<LogEntry[]>([])
  const prevMsgRef = useRef<string | null>(null)
  const notifiedRef = useRef(false)
  const logRef = useRef<HTMLDivElement>(null)

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

  async function handleCancel() {
    await cancelScan.mutateAsync(jobId)
  }

  async function handleRetry() {
    if (!job) return
    const newJob = await retryScan.mutateAsync({
      targetId: job.target_id,
      scanType: job.scan_type,
    })
    router.push(`/scan-management/${newJob.id}`)
  }

  if (isLoading) return <div className="h-64 bg-slate-800 rounded-xl animate-pulse" />
  if (!job) return <div className="p-8 text-center text-slate-500">Scan tidak ditemukan.</div>

  const targetName = targets?.find((t) => t.id === job.target_id)?.name ?? '—'
  const progressPct = computeOverallPct(job)
  const isRunning = job.status === 'running' || job.status === 'queued'
  const isTerminal =
    job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled'
  const statusLabel =
    job.progress?.message ??
    (job.status === 'completed' ? 'Selesai' : SCAN_STATUS_LABELS[job.status])

  return (
    <div className="space-y-6">
      <Link
        href="/scan-management"
        className="inline-flex items-center gap-2 text-slate-400 hover:text-white text-sm transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        Kembali ke Log Teknis
      </Link>

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">{targetName}</h1>
          <p className="text-slate-400 text-sm mt-1">
            {SCAN_TYPE_LABELS[job.scan_type]} ·{' '}
            {new Date(job.created_at).toLocaleString('id-ID')}
          </p>
        </div>
        <span className={`text-sm font-semibold whitespace-nowrap ${SCAN_STATUS_COLORS[job.status]}`}>
          {SCAN_STATUS_LABELS[job.status]}
        </span>
      </div>

      <div className="glass-dark rounded-xl border border-white/5 p-6 space-y-5">
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

        {logEntries.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              {isRunning && (
                <div
                  style={{
                    width: 7, height: 7, borderRadius: '50%',
                    background: '#00e5cc', animation: 'pulse-dot 1.5s infinite',
                  }}
                />
              )}
              <span style={{ fontSize: 11, color: '#8b949e', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600 }}>
                Worker Log
              </span>
            </div>
            <div
              ref={logRef}
              style={{
                background: '#0a0f1a', borderRadius: 8,
                border: '1px solid rgba(255,255,255,0.06)',
                padding: '10px 14px', overflowY: 'auto',
                fontFamily: 'var(--font-geist-mono, monospace)',
                fontSize: 11.5, lineHeight: 1.8, maxHeight: 200,
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
                    <span style={{ color: LOG_COLOR[entry.type] ?? '#8b949e', fontWeight: 700, marginRight: 4 }}>
                      {entry.type}
                    </span>
                    <span style={{ color: '#c9d1d9' }}>{entry.msg}</span>
                  </div>
                )
              })}
              {isRunning && (
                <span style={{
                  display: 'inline-block', width: 7, height: 13, background: '#00e5cc',
                  verticalAlign: 'text-bottom', animation: 'blink 1s infinite',
                  borderRadius: 1, marginLeft: 2,
                }} />
              )}
            </div>
          </div>
        )}

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

        <div className="flex flex-wrap gap-3 pt-2">
          {isRunning && (
            <Button variant="destructive" onClick={handleCancel} disabled={cancelScan.isPending}>
              {cancelScan.isPending ? 'Membatalkan...' : 'Batalkan Scan'}
            </Button>
          )}
          {isTerminal && (
            <Button
              variant="outline"
              onClick={handleRetry}
              disabled={retryScan.isPending}
              className="border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/10"
            >
              {retryScan.isPending ? 'Memulai...' : 'Scan Ulang'}
            </Button>
          )}
          {job.status === 'completed' && (
            <Link href={`/vulnerability-report?jobId=${job.id}`}>
              <Button className="bg-primary hover:bg-primary/90">Lihat Laporan Lengkap →</Button>
            </Link>
          )}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: TypeScript check**

```bash
npx tsc --noEmit 2>&1 | head -20
```
Expected: tidak ada error.

- [ ] **Step 3: Commit**

```bash
git add "app/(dashboard)/scan-management/[id]/page.tsx"
git commit -m "feat: new scan detail page with live monitor, cancel, retry, report link"
```

---

### Task 8: Sederhanakan scanning/page.tsx

**Context:** Setelah scan dibuat, redirect ke `/scan-management/{id}`. `ScanJobMonitor` dan `RecentJobsList` dihapus — fungsinya sudah di halaman detail.

**Files:**
- Modify: `OJSDEF-FrontEnd/app/(dashboard)/scanning/page.tsx`

- [ ] **Step 1: Tulis ulang scanning/page.tsx**

```typescript
'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useStartScan } from '@/hooks/use-scans'
import { useTargets } from '@/hooks/use-targets'
import { RoleGuard } from '@/components/shared/RoleGuard'
import { Button } from '@/components/ui/button'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import type { ScanType } from '@/types/api'

function StartScanForm() {
  const router = useRouter()
  const { data: targets } = useTargets()
  const startScan = useStartScan()
  const [targetId, setTargetId] = useState('')
  const [scanType, setScanType] = useState<ScanType>('external')
  const [error, setError] = useState<string | null>(null)

  async function handleStart() {
    if (!targetId) { setError('Pilih target terlebih dahulu'); return }
    setError(null)
    try {
      const job = await startScan.mutateAsync({ targetId, scanType })
      router.push(`/scan-management/${job.id}`)
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
      <Button onClick={handleStart} disabled={startScan.isPending} className="bg-primary hover:bg-primary/90">
        {startScan.isPending ? 'Memulai...' : 'Mulai Scan'}
      </Button>
    </div>
  )
}

export default function ScanningPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Mulai Scan</h1>
        <p className="text-slate-400 mt-1 text-sm">Jalankan pemindaian keamanan terhadap instalasi OJS Anda</p>
      </div>
      <RoleGuard allowedRoles={['saas_admin', 'admin_ojs']}>
        <StartScanForm />
      </RoleGuard>
    </div>
  )
}
```

- [ ] **Step 2: TypeScript check**

```bash
npx tsc --noEmit 2>&1 | head -20
```
Expected: tidak ada error.

- [ ] **Step 3: Commit**

```bash
git add "app/(dashboard)/scanning/page.tsx"
git commit -m "feat: scanning page redirects to detail page after scan creation"
```

---

### Task 9: Scan-management list — clickable rows + nama target

**Context:** Tambah `onClick` ke baris tabel dan resolve `target_id` ke nama target yang terbaca.

**Files:**
- Modify: `OJSDEF-FrontEnd/app/(dashboard)/scan-management/page.tsx`

- [ ] **Step 1: Tulis ulang scan-management/page.tsx**

```typescript
'use client'

import { useRouter } from 'next/navigation'
import { useScans } from '@/hooks/use-scans'
import { useTargets } from '@/hooks/use-targets'
import { RoleGuard } from '@/components/shared/RoleGuard'
import { SCAN_STATUS_LABELS, SCAN_STATUS_COLORS, SCAN_TYPE_LABELS } from '@/lib/utils'

function ScanManagementContent() {
  const router = useRouter()
  const { data: scans, isLoading } = useScans()
  const { data: targets } = useTargets()

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Log Teknis</h1>
        <p className="text-slate-400 mt-1 text-sm">Riwayat lengkap semua job scan</p>
      </div>

      <div className="glass-dark rounded-xl border border-white/5">
        <div className="overflow-x-auto">
          {isLoading ? (
            <div className="p-6 space-y-3">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="h-12 bg-slate-800 rounded animate-pulse" />
              ))}
            </div>
          ) : !scans?.length ? (
            <div className="p-8 text-center text-slate-500">Belum ada riwayat scan.</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-500 text-xs uppercase border-b border-white/5">
                  <th className="px-6 py-3 text-left">ID</th>
                  <th className="px-6 py-3 text-left">Target</th>
                  <th className="px-6 py-3 text-left">Tipe</th>
                  <th className="px-6 py-3 text-left">Status</th>
                  <th className="px-6 py-3 text-left">Skor</th>
                  <th className="px-6 py-3 text-left">Dibuat</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {scans.map((scan) => (
                  <tr
                    key={scan.id}
                    className="hover:bg-white/5 transition-colors cursor-pointer"
                    onClick={() => router.push(`/scan-management/${scan.id}`)}
                  >
                    <td className="px-6 py-3 text-slate-500 font-mono text-xs">
                      {scan.id.slice(0, 8)}…
                    </td>
                    <td className="px-6 py-3 text-slate-300 text-sm">
                      {targets?.find((t) => t.id === scan.target_id)?.name ??
                        scan.target_id.slice(0, 8) + '…'}
                    </td>
                    <td className="px-6 py-3 text-slate-400">
                      {SCAN_TYPE_LABELS[scan.scan_type]}
                    </td>
                    <td className="px-6 py-3">
                      <span className={`text-sm ${SCAN_STATUS_COLORS[scan.status]}`}>
                        {SCAN_STATUS_LABELS[scan.status]}
                      </span>
                    </td>
                    <td className="px-6 py-3 text-slate-400">
                      {scan.overall_score != null ? scan.overall_score.toFixed(1) : '—'}
                    </td>
                    <td className="px-6 py-3 text-slate-500 text-xs">
                      {new Date(scan.created_at).toLocaleDateString('id-ID')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

export default function ScanManagementPage() {
  return (
    <RoleGuard allowedRoles={['saas_admin', 'admin_ojs']}>
      <ScanManagementContent />
    </RoleGuard>
  )
}
```

- [ ] **Step 2: TypeScript check**

```bash
npx tsc --noEmit 2>&1 | head -20
```
Expected: tidak ada error.

- [ ] **Step 3: Commit**

```bash
git add "app/(dashboard)/scan-management/page.tsx"
git commit -m "feat: scan-management list has clickable rows and shows target names"
```

---

### Task 10: Vulnerability-report — ScanSummary + ScanSelector

**Context:** Tambah ringkasan scan di atas findings dan dropdown selector untuk memilih scan. `AutoSelectJob` dihapus — digantikan logika langsung di `VulnerabilityReportContent`.

**Files:**
- Modify: `OJSDEF-FrontEnd/app/(dashboard)/vulnerability-report/page.tsx`

- [ ] **Step 1: Tulis ulang vulnerability-report/page.tsx**

```typescript
'use client'

import { useSearchParams, useRouter } from 'next/navigation'
import { useState, Suspense } from 'react'
import { useScans, useScanJob } from '@/hooks/use-scans'
import { useTargets } from '@/hooks/use-targets'
import { useFindings, useToggleFalsePositive } from '@/hooks/use-findings'
import {
  SEVERITY_LABELS, SEVERITY_COLORS, SEVERITY_BG_COLORS, SCAN_TYPE_LABELS,
} from '@/lib/utils'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { ChevronDown, ChevronUp, AlertTriangle, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { ScanFinding, ScanJob, SeverityLevel } from '@/types/api'

const SEVERITY_ORDER: SeverityLevel[] = ['critical', 'high', 'medium', 'low']

const RISK_LABELS: Record<string, string> = {
  critical: 'KRITIS', high: 'TINGGI', medium: 'SEDANG', low: 'RENDAH',
}
const RISK_COLORS: Record<string, string> = {
  critical: 'text-red-400', high: 'text-orange-400', medium: 'text-yellow-400', low: 'text-green-400',
}

function ScanSummary({ jobId }: { jobId: string }) {
  const { data: job } = useScanJob(jobId)
  const { data: targets } = useTargets()
  if (!job) return null
  const targetName = targets?.find((t) => t.id === job.target_id)?.name ?? '—'
  return (
    <div className="glass-dark rounded-xl border border-white/5 p-5 space-y-3">
      <div className="flex items-start justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-white font-semibold">{targetName}</h2>
          <p className="text-slate-400 text-sm">
            {SCAN_TYPE_LABELS[job.scan_type]} · {new Date(job.created_at).toLocaleString('id-ID')}
          </p>
        </div>
        {job.overall_score != null && (
          <div className="text-right">
            <p className="text-white font-bold text-xl">{job.overall_score.toFixed(1)}</p>
            {job.risk_level && (
              <p className={`text-xs font-semibold ${RISK_COLORS[job.risk_level] ?? 'text-slate-400'}`}>
                {RISK_LABELS[job.risk_level] ?? job.risk_level.toUpperCase()}
              </p>
            )}
          </div>
        )}
      </div>
      <div className="grid grid-cols-4 gap-3 pt-2 border-t border-white/5">
        <div className="text-center">
          <p className="text-red-400 text-lg font-bold">{job.critical_count}</p>
          <p className="text-slate-500 text-xs">Kritis</p>
        </div>
        <div className="text-center">
          <p className="text-orange-400 text-lg font-bold">{job.high_count}</p>
          <p className="text-slate-500 text-xs">Berbahaya</p>
        </div>
        <div className="text-center">
          <p className="text-yellow-400 text-lg font-bold">{job.medium_count}</p>
          <p className="text-slate-500 text-xs">Perhatian</p>
        </div>
        <div className="text-center">
          <p className="text-green-400 text-lg font-bold">{job.low_count}</p>
          <p className="text-slate-500 text-xs">Aman</p>
        </div>
      </div>
    </div>
  )
}

function ScanSelector({
  scans, selectedId, onSelect,
}: { scans: ScanJob[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const { data: targets } = useTargets()
  if (!scans.length) return null
  function getLabel(scan: ScanJob): string {
    const name = targets?.find((t) => t.id === scan.target_id)?.name ?? scan.target_id.slice(0, 8)
    const date = new Date(scan.created_at).toLocaleDateString('id-ID')
    return `${name} — ${SCAN_TYPE_LABELS[scan.scan_type]} — ${date}`
  }
  return (
    <div className="flex items-center gap-3 flex-wrap">
      <label className="text-slate-400 text-sm whitespace-nowrap">Pilih Scan:</label>
      <Select value={selectedId ?? ''} onValueChange={onSelect}>
        <SelectTrigger className="bg-slate-900/60 border-white/10 text-white max-w-md">
          <SelectValue placeholder="Pilih scan..." />
        </SelectTrigger>
        <SelectContent>
          {scans.map((scan) => (
            <SelectItem key={scan.id} value={scan.id}>{getLabel(scan)}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

function FindingCard({ finding, jobId }: { finding: ScanFinding; jobId: string }) {
  const [expanded, setExpanded] = useState(false)
  const toggleFP = useToggleFalsePositive(jobId)
  return (
    <div className={`glass-dark rounded-xl border ${SEVERITY_BG_COLORS[finding.severity]} transition-all ${finding.is_false_positive ? 'opacity-60' : ''}`}>
      <button className="w-full flex items-start gap-4 p-5 text-left" onClick={() => setExpanded(!expanded)}>
        <div className={`mt-0.5 flex-shrink-0 ${SEVERITY_COLORS[finding.severity]}`}>
          <AlertTriangle className="h-5 w-5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${SEVERITY_BG_COLORS[finding.severity]} ${SEVERITY_COLORS[finding.severity]}`}>
              {SEVERITY_LABELS[finding.severity]}
            </span>
            {finding.is_false_positive && (
              <span className="text-xs px-2 py-0.5 rounded bg-slate-500/20 text-slate-400 border border-slate-500/20 font-medium ml-1.5">
                Positif Palsu
              </span>
            )}
            {finding.cve_id && <span className="text-xs text-slate-500">{finding.cve_id}</span>}
          </div>
          <p className="text-white font-medium mt-1">{finding.title}</p>
          <p className="text-slate-400 text-sm mt-1 truncate">{finding.description}</p>
        </div>
        <div className="flex-shrink-0 text-slate-500">
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </div>
      </button>
      {expanded && (
        <div className="px-5 pb-5 space-y-4 border-t border-white/5 pt-4">
          {finding.affected_path && (
            <div>
              <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">Path Terpengaruh</p>
              <p className="text-slate-300 text-sm font-mono bg-slate-900/60 px-3 py-2 rounded-lg">{finding.affected_path}</p>
            </div>
          )}
          {finding.evidence && (
            <div>
              <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">Bukti</p>
              <p className="text-slate-300 text-sm">{finding.evidence}</p>
            </div>
          )}
          <div>
            <p className="text-slate-500 text-xs uppercase tracking-wide mb-2">Langkah Perbaikan</p>
            <p className="text-slate-300 text-sm whitespace-pre-wrap">{finding.remediation}</p>
          </div>
          <div className="flex items-center gap-3 pt-2">
            <span className="text-slate-500 text-xs">CVSS: {finding.cvss_score.toFixed(1)}</span>
            {finding.owasp_category && <span className="text-slate-500 text-xs">OWASP: {finding.owasp_category}</span>}
            <Button
              variant="ghost" size="sm"
              className="ml-auto text-xs text-slate-500 hover:text-slate-300"
              onClick={() => toggleFP.mutate(finding.id)}
              disabled={toggleFP.isPending}
            >
              {finding.is_false_positive ? 'Tandai Aktif' : 'Tandai False Positive'}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function FindingsList({ jobId }: { jobId: string }) {
  const { data: findings, isLoading } = useFindings(jobId)
  const [filterSeverity, setFilterSeverity] = useState<SeverityLevel | 'all'>('all')
  if (isLoading) {
    return (
      <div className="space-y-3">
        {[...Array(4)].map((_, i) => <div key={i} className="h-20 bg-slate-800 rounded-xl animate-pulse" />)}
      </div>
    )
  }
  if (!findings?.length) {
    return (
      <div className="glass-dark rounded-xl border border-white/5 p-8 text-center text-slate-500">
        <Info className="h-8 w-8 mx-auto mb-2 opacity-50" />
        <p>Tidak ada temuan untuk scan ini.</p>
      </div>
    )
  }
  const visible = filterSeverity === 'all' ? findings : findings.filter((f) => f.severity === filterSeverity)
  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap">
        <button
          onClick={() => setFilterSeverity('all')}
          className={`px-3 py-1 rounded-full text-sm transition-colors ${filterSeverity === 'all' ? 'bg-primary text-white' : 'text-slate-400 hover:text-white'}`}
        >
          Semua ({findings.length})
        </button>
        {SEVERITY_ORDER.map((sev) => {
          const count = findings.filter((f) => f.severity === sev).length
          if (!count) return null
          return (
            <button
              key={sev}
              onClick={() => setFilterSeverity(sev)}
              className={`px-3 py-1 rounded-full text-sm transition-colors ${filterSeverity === sev ? 'bg-primary text-white' : `${SEVERITY_COLORS[sev]} hover:opacity-80`}`}
            >
              {SEVERITY_LABELS[sev]} ({count})
            </button>
          )
        })}
      </div>
      <div className="space-y-3">
        {visible.map((finding) => <FindingCard key={finding.id} finding={finding} jobId={jobId} />)}
      </div>
    </div>
  )
}

function VulnerabilityReportContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const { data: scans } = useScans({ limit: 20 })
  const completedScans = scans?.filter((s) => s.status === 'completed') ?? []
  const jobIdFromUrl = searchParams.get('jobId')
  const selectedJobId = jobIdFromUrl ?? completedScans[0]?.id ?? null

  function handleSelect(id: string) {
    router.replace(`/vulnerability-report?jobId=${id}`)
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Laporan Keamanan</h1>
        <p className="text-slate-400 mt-1 text-sm">Temuan kerentanan dan rencana perbaikan</p>
      </div>
      {scans === undefined ? null : completedScans.length === 0 ? (
        <div className="glass-dark rounded-xl border border-white/5 p-8 text-center text-slate-500">
          <Info className="h-8 w-8 mx-auto mb-2 opacity-50" />
          <p>Belum ada scan selesai. Jalankan scan terlebih dahulu.</p>
        </div>
      ) : (
        <>
          <ScanSelector scans={completedScans} selectedId={selectedJobId} onSelect={handleSelect} />
          {selectedJobId && <ScanSummary jobId={selectedJobId} />}
          {selectedJobId && <FindingsList jobId={selectedJobId} />}
        </>
      )}
    </div>
  )
}

export default function VulnerabilityReportPage() {
  return (
    <Suspense fallback={<div className="h-64 bg-slate-800 rounded-xl animate-pulse" />}>
      <VulnerabilityReportContent />
    </Suspense>
  )
}
```

- [ ] **Step 2: TypeScript check**

```bash
npx tsc --noEmit 2>&1 | head -20
```
Expected: tidak ada error.

- [ ] **Step 3: Commit**

```bash
git add "app/(dashboard)/vulnerability-report/page.tsx"
git commit -m "feat: vulnerability-report adds scan summary and scan selector"
```

---

## Deployment

```bash
# Backend — tidak perlu rebuild image
git pull
docker compose down && docker compose up -d

# Frontend
git pull && npm run build
```
