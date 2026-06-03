# Spec C-3 — UX Fixes: testConnection, Progress Log, Scan Timeout, PDF Download, Auth Refresh

## Goal

Perbaiki 5 bug UX yang ditemukan saat testing VPS: plugin testConnection popup tidak menutup, external scan worker log melompat ke DONE, internal scan stuck tanpa timeout, PDF download "Not authenticated", dan logout saat refresh browser.

## Architecture

Lima fix independen di tiga codebase. Tidak ada perubahan skema database. Tidak ada library baru.

**Tech Stack:** PHP 7.4+ (OJSDef Plugin), Python/FastAPI (BackEnd), Next.js/TypeScript (FrontEnd)

---

## File Map

| File | Aksi | Codebase |
|------|------|----------|
| `ojsdef/OjsdefPlugin.php` | Edit — fix testConnection case | Plugin |
| `ojsdef-plugin-1.0.1.zip` | Rebuild | Plugin |
| `app/workers/utils.py` | Edit — append log ke Redis | BackEnd |
| `app/schemas/scans.py` | Edit — tambah ScanProgressLog model | BackEnd |
| `app/workers/tasks.py` | Edit — write_progress + completed_at | BackEnd |
| `app/routers/reports.py` | Edit — StreamingResponse PDF | BackEnd |
| `docker-compose.yml` | Edit — tambah celery-beat service | BackEnd |
| `types/api.ts` | Edit — tambah ScanProgressEntry + log field | FrontEnd |
| `app/(dashboard)/scan-management/[id]/page.tsx` | Edit — useMemo log dari progress.log | FrontEnd |
| `hooks/use-reports.ts` | Edit — blob download via api.get | FrontEnd |
| `lib/api.ts` | Edit — refresh token lock | FrontEnd |

---

## Section 1: Plugin testConnection Fix

### Root Cause

`createTrivialNotification($user->getId(), ...)` — jika `$request->getUser()` return null di beberapa konteks AJAX OJS 3.4.x, fatal error terjadi sebelum `return new JSONMessage(...)`. Response menjadi HTML error page — modal tidak bisa parse → tidak menutup. Selain itu, `createTrivialNotification` dalam AJAX context butuh page reload untuk tampil.

### Fix di `ojsdef/OjsdefPlugin.php`

**Hapus** dua `use` statement berikut dari bagian atas file:
```php
use PKP\notification\NotificationManager;
use PKP\notification\PKPNotification;
```

**Ganti seluruh `case 'testConnection':` block** dengan:

```php
case 'testConnection':
    $this->_requireClasses();
    $extra  = $this->_buildHeartbeatExtra();
    $result = (new \ApiClient($this))->sendHeartbeat($extra);

    if ($result['code'] === 200) {
        return new JSONMessage(true);  // modal menutup = sinyal sukses
    }

    $detail  = !empty($result['error']) ? $result['error'] : 'HTTP ' . $result['code'];
    $message = __('plugins.generic.ojsdef.testConnection.failed')
               . ' — ' . htmlspecialchars($detail);
    return new JSONMessage(false, $message);
```

**UX result:**
- Sukses → modal menutup (sinyal sukses tanpa notifikasi tambahan)
- Gagal → modal tetap terbuka menampilkan pesan error detail

Plugin ZIP perlu di-rebuild setelah perubahan ini.

---

## Section 2: Progress Log Accumulation

### Root Cause

`write_progress` menimpa state Redis setiap call — hanya state terkini tersimpan. Frontend polling tiap 3 detik hanya membaca snapshot terakhir; step yang selesai dalam <3 detik tidak pernah tertangkap oleh frontend.

### Fix 1: `app/workers/utils.py`

Tambah `import time` dan modifikasi `write_progress` untuk append ke `log[]` array:

```python
import json
import time   # tambah import
import redis.asyncio as aioredis
from app.celery_app import celery_app
from app.config import get_settings

settings = get_settings()


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
        raw  = await r.get(f"scan_progress:{job_id}")
        data = json.loads(raw) if raw else {}
        data.update({
            "stage": stage, "current_step": step,
            "total_steps": total, "message": message, "log_type": log_type,
        })
        log = data.get("log", [])
        log.append({
            "step": step, "stage": stage,
            "msg": message, "type": log_type,
            "ts": int(time.time()),
        })
        data["log"] = log
        await r.setex(f"scan_progress:{job_id}", 3600, json.dumps(data))
    finally:
        await r.aclose()
```

Fungsi `_try_trigger_scoring` dan `_check_cancelled` tidak berubah.

### Fix 2: `app/schemas/scans.py`

Tambah model `ScanProgressLog` dan field `log` ke `ScanProgress`:

```python
class ScanProgressLog(BaseModel):
    step:  int
    stage: str
    msg:   str
    type:  str
    ts:    int


class ScanProgress(BaseModel):
    stage:        str
    current_step: int
    total_steps:  int
    message:      str
    log_type:     str | None = None
    log:          list[ScanProgressLog] = []
```

### Fix 3: `types/api.ts`

Tambah interface `ScanProgressEntry` dan field `log` ke `ScanProgress`:

```typescript
export interface ScanProgressEntry {
  step:  number
  stage: string
  msg:   string
  type:  string
  ts:    number
}

// Di interface ScanProgress yang sudah ada, tambah field log:
export interface ScanProgress {
  stage:        string
  current_step: number
  total_steps:  number
  message:      string
  log_type?:    string
  log?:         ScanProgressEntry[]
}
```

### Fix 4: `app/(dashboard)/scan-management/[id]/page.tsx`

**Hapus:**
- `const [logEntries, setLogEntries] = useState<LogEntry[]>([])`
- `const prevMsgRef = useRef<string | null>(null)`
- `useEffect` yang append log berdasarkan `job?.progress?.message` comparison

**Tambah `useMemo` ke React import, ganti dengan:**

```typescript
const logEntries = useMemo<LogEntry[]>(() => {
  const log = job?.progress?.log ?? []
  return log.map((entry) => ({
    time: new Date(entry.ts * 1000).toLocaleTimeString('id-ID', {
      hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
    }),
    type: (entry.type ?? 'INFO') as LogEntry['type'],
    msg:  entry.msg,
  }))
}, [job?.progress?.log])
```

`useEffect` untuk auto-scroll (`logRef.current.scrollTop`) tetap dipertahankan.

**Juga hapus:** `notifiedRef` dan useEffect yang memanggil `setLogEntries` ketika `job.status === 'completed'` — tidak dibutuhkan lagi karena entry "Scan selesai" sudah ditulis ke Redis oleh `scoring.py` dan muncul otomatis di `job.progress.log`.

---

## Section 3: Internal Scan Timeout

### Root Cause

Cleanup task `cleanup_stale_pending_jobs` sudah ada dengan logic benar (mark stale jobs → failed setelah 30 menit), tapi **Celery Beat tidak dijalankan** — tidak ada service `celery-beat` di `docker-compose.yml`. Task tidak pernah berjalan → stale jobs stuck selamanya.

### Fix 1: `docker-compose.yml`

Tambahkan service `celery-beat` setelah block `worker-notify`:

```yaml
  celery-beat:
    <<: *app
    command: celery -A app.celery_app beat --loglevel=info
```

### Fix 2: `app/workers/tasks.py`

Dua perbaikan: tambah `write_progress` ke log Redis sebelum marking failed, dan set `completed_at`:

```python
import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models.scan_job import ScanJob
from app.workers.utils import write_progress   # ← tambah import


@celery_app.task(name="app.workers.tasks.cleanup_stale_pending_jobs")
def cleanup_stale_pending_jobs() -> str:
    """Mark queued/running scan jobs > 30 menit tanpa callback sebagai failed."""

    async def _run() -> int:
        threshold = datetime.now(timezone.utc) - timedelta(minutes=30)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ScanJob).where(
                    ScanJob.status.in_(["queued", "running"]),
                    ScanJob.created_at < threshold,
                )
            )
            stale = result.scalars().all()
            for job in stale:
                await write_progress(
                    str(job.id), "scan", 0, 0,
                    "Scan timeout: plugin tidak merespons dalam 30 menit", "WARN",
                )
                job.status        = "failed"
                job.completed_at  = datetime.now(timezone.utc)
                job.error_message = "Scan timeout: tidak ada respons dalam 30 menit"
            if stale:
                await session.commit()
        return len(stale)

    count = asyncio.run(_run())
    return f"Cleaned up {count} stale pending jobs"
```

---

## Section 4: PDF Download Fix

### Root Cause

**Masalah 1:** `window.open('/api/v1/reports/{id}/pdf', '_blank')` membuka URL langsung di browser tanpa `Authorization: Bearer` header → backend tolak 401.

**Masalah 2:** MinIO presigned URL menggunakan hostname internal Docker (`minio:9000`) tidak accessible dari browser.

### Solusi: Stream PDF melalui FastAPI

Backend download dari MinIO secara server-side (internal URL berfungsi), lalu stream bytes ke client. Tidak ada perubahan konfigurasi MinIO.

### Fix 1: `app/routers/reports.py`

Tambah import `io` dan `StreamingResponse`. Ganti endpoint `download_pdf`:

```python
import io
from fastapi.responses import StreamingResponse


@router.get("/{report_id}/pdf")
async def download_pdf(
    report_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Report).where(Report.id == report_id, Report.format == "pdf")
    )
    report = result.scalar_one_or_none()
    if not report or not report.storage_path:
        raise HTTPException(404, "Laporan PDF tidak ditemukan")

    obj      = _s3().get_object(Bucket=settings.minio_bucket, Key=report.storage_path)
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
```

### Fix 2: `hooks/use-reports.ts`

Ganti `window.open` dengan `api.get(..., { responseType: 'blob' })`:

```typescript
export function useDownloadReport() {
  return useMutation({
    mutationFn: async (reportId: string) => {
      const response = await api.get<Blob>(`/api/v1/reports/${reportId}/pdf`, {
        responseType: 'blob',
      })
      if (typeof window === 'undefined') return
      const url = URL.createObjectURL(response.data)
      const a   = document.createElement('a')
      a.href     = url
      a.download = `ojsdef-report-${reportId.slice(0, 8)}.pdf`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    },
  })
}
```

---

## Section 5: Logout on Browser Refresh Fix

### Root Cause

Page refresh → `_accessToken = null`. TanStack Query fire semua queries paralel → semua dapat 401. Setiap request punya interceptor sendiri yang memanggil `/api/auth/refresh` bersamaan. Backend rotating refresh tokens: hanya call pertama sukses, sisanya gagal → `window.location.href = '/login'`.

### Fix: `lib/api.ts` — Refresh Token Lock

Tambah `_refreshPromise` shared variable. Semua request 401 paralel menunggu Promise yang sama:

```typescript
import axios from 'axios'
import type { InternalAxiosRequestConfig } from 'axios'

let _accessToken:    string | null          = null
let _refreshPromise: Promise<string> | null = null   // ← lock baru

export function setAccessToken(token: string | null): void {
  _accessToken = token
}

export function getAccessToken(): string | null {
  return _accessToken
}

export const api = axios.create({
  baseURL: '',
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  if (_accessToken) config.headers.Authorization = `Bearer ${_accessToken}`
  return config
})

interface RetryConfig extends InternalAxiosRequestConfig {
  _retry?: boolean
}

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const config = error.config as RetryConfig
    if (error.response?.status === 401 && !config._retry) {
      config._retry = true
      try {
        if (!_refreshPromise) {
          _refreshPromise = axios
            .post<{ access_token: string }>('/api/auth/refresh')
            .then(({ data }) => {
              setAccessToken(data.access_token)
              return data.access_token
            })
            .finally(() => { _refreshPromise = null })
        }
        const token = await _refreshPromise
        config.headers.Authorization = `Bearer ${token}`
        return api(config)
      } catch {
        setAccessToken(null)
        _refreshPromise = null
        if (typeof window !== 'undefined') window.location.href = '/login'
      }
    }
    const detail = error.response?.data?.detail
    return Promise.reject(new Error(detail ?? 'Terjadi kesalahan'))
  }
)
```

---

## Deployment

```bash
# BackEnd — docker-compose.yml berubah (celery-beat ditambah)
git pull
docker compose down && docker compose up -d

# FrontEnd
git pull && npm run build

# Plugin — rebuild ZIP dan upload ke OJS admin panel
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$src = "ojsdef"; $out = "ojsdef-plugin-1.0.1.zip"
if (Test-Path $out) { Remove-Item $out -Force }
$zip = [System.IO.Compression.ZipFile]::Open($out, 'Create')
Get-ChildItem -Path $src -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring((Resolve-Path $src).Path.Length).TrimStart('\').Replace('\','/')
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, "ojsdef/$rel")
}
$zip.Dispose()
```
