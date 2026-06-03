# Spec C-3 — UX Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Perbaiki 5 bug UX: plugin testConnection popup tidak menutup, external scan log melompat ke DONE, internal scan stuck tanpa timeout, PDF download "Not authenticated", dan logout saat refresh browser.

**Architecture:** Lima fix independen di tiga codebase. Plugin: hapus createTrivialNotification, kembalikan JSONMessage sederhana. Backend: append log ke Redis, tambah celery-beat, stream PDF. Frontend: useMemo log, refresh token lock, blob download.

**Tech Stack:** PHP 7.4+, Python/FastAPI, Next.js/TypeScript

**Catatan Testing:** TIDAK ADA test lokal. Python: `python -m py_compile`. PHP: `php -l`. TypeScript: `npx tsc --noEmit` dari FrontEnd dir. Test fungsional di VPS.

**Parallel Execution Note:**
- Plugin ZIP: plan ini mengubah `OjsdefPlugin.php`. Jika Plan C-1 juga berjalan paralel dan belum rebuild ZIP, subagent yang selesai **terakhir** harus rebuild ZIP ulang setelah semua PHP commits dari kedua plan.

---

## File Map

| File | Aksi | Repo |
|------|------|------|
| `ojsdef/OjsdefPlugin.php` | Edit — fix testConnection | Plugin |
| `ojsdef-plugin-1.0.1.zip` | Rebuild | Plugin |
| `app/workers/utils.py` | Edit — append log ke Redis | BackEnd |
| `app/schemas/scans.py` | Edit — tambah ScanProgressLog | BackEnd |
| `app/workers/tasks.py` | Edit — write_progress + completed_at | BackEnd |
| `app/routers/reports.py` | Edit — StreamingResponse PDF | BackEnd |
| `docker-compose.yml` | Edit — tambah celery-beat | BackEnd |
| `types/api.ts` | Edit — ScanProgressEntry + log field | FrontEnd |
| `app/(dashboard)/scan-management/[id]/page.tsx` | Edit — useMemo log | FrontEnd |
| `hooks/use-reports.ts` | Edit — blob download | FrontEnd |
| `lib/api.ts` | Edit — refresh token lock | FrontEnd |

Plugin: `D:\Kuliahku\Capstone\workspace\OJSDEF-Plugin\`
BackEnd: `D:\Kuliahku\Capstone\workspace\OJSDEF-BackEnd\`
FrontEnd: `D:\Kuliahku\Capstone\workspace\OJSDEF-FrontEnd\`

---

### Task 1: Fix Plugin testConnection — Hapus createTrivialNotification

**Context:** `createTrivialNotification($user->getId(), ...)` menyebabkan fatal error jika `$user` null di beberapa konteks AJAX OJS 3.4.x → modal tidak bisa menutup. `createTrivialNotification` dalam AJAX context pun butuh page reload untuk tampil. Fix: hapus seluruh notification logic, return `JSONMessage(true)` untuk sukses (modal menutup = sinyal sukses) dan `JSONMessage(false, $error)` untuk gagal (error tampil di dialog).

**Files:**
- Modify: `ojsdef/OjsdefPlugin.php`

- [ ] **Step 1: Hapus dua use statement dari OjsdefPlugin.php**

Buka `ojsdef/OjsdefPlugin.php`. Temukan dan hapus kedua baris ini dari bagian `use` statements:

```php
use PKP\notification\NotificationManager;
use PKP\notification\PKPNotification;
```

- [ ] **Step 2: Ganti seluruh case 'testConnection' di method manage()**

Temukan blok `case 'testConnection':` di method `manage()`. Ganti seluruh blok (dari `case 'testConnection':` sampai baris `return new JSONMessage(...)` yang menutup case ini) dengan:

```php
            case 'testConnection':
                $this->_requireClasses();
                $extra  = $this->_buildHeartbeatExtra();
                $result = (new \ApiClient($this))->sendHeartbeat($extra);

                if ($result['code'] === 200) {
                    return new JSONMessage(true);
                }

                $detail  = !empty($result['error']) ? $result['error'] : 'HTTP ' . $result['code'];
                $message = __('plugins.generic.ojsdef.testConnection.failed')
                           . ' — ' . htmlspecialchars($detail);
                return new JSONMessage(false, $message);
```

- [ ] **Step 3: PHP syntax check**

```bash
cd D:\Kuliahku\Capstone\workspace\OJSDEF-Plugin
php -l ojsdef/OjsdefPlugin.php
```

Expected: `No syntax errors detected in ojsdef/OjsdefPlugin.php`

- [ ] **Step 4: Commit**

```bash
git add ojsdef/OjsdefPlugin.php
git commit -m "fix(c3): testConnection returns JSONMessage, removes createTrivialNotification"
```

---

### Task 2: Rebuild Plugin ZIP

**PENTING — Parallel Execution:** Jika Plan C-1 berjalan paralel dan belum selesai commit PHP changes-nya, **tunggu C-1 selesai** sebelum rebuild di sini. ZIP harus mencakup semua PHP changes dari kedua plan (ConfigScanner.php, ContentInjectionDetector.php dari C-1 + OjsdefPlugin.php dari C-3).

**Files:**
- Rebuild: `ojsdef-plugin-1.0.1.zip`

- [ ] **Step 1: Rebuild ZIP**

```powershell
cd D:\Kuliahku\Capstone\workspace\OJSDEF-Plugin
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
Write-Host "ZIP rebuilt: $((Get-Item $out).Length) bytes"
```

Expected: Ukuran bytes > 0 ditampilkan.

- [ ] **Step 2: Commit ZIP**

```bash
git add ojsdef-plugin-1.0.1.zip
git commit -m "chore(c3): rebuild plugin ZIP with testConnection fix (and all C-1 PHP fixes)"
```

---

### Task 3: Backend — Update utils.py (Progress Log Accumulation)

**Context:** `write_progress` menimpa state Redis — frontend polling 3 detik melewatkan step yang cepat. Fix: append setiap update ke `log[]` array.

**Files:**
- Modify: `app/workers/utils.py`

- [ ] **Step 1: Tambah import time**

Buka `app/workers/utils.py`. Tambahkan `import time` setelah `import json`:

```python
import time
```

- [ ] **Step 2: Update fungsi write_progress**

Ganti seluruh fungsi `write_progress` dengan:

```python
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

- [ ] **Step 3: Syntax check**

```bash
cd D:\Kuliahku\Capstone\workspace\OJSDEF-BackEnd
python -m py_compile app/workers/utils.py && echo OK
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/workers/utils.py
git commit -m "fix(c3): write_progress appends to log[] array in Redis for complete history"
```

---

### Task 4: Backend — Update schemas/scans.py (ScanProgressLog)

**Context:** ScanProgress schema perlu field `log` agar backend serialize log array ke API response. Frontend akan membaca `job.progress.log`.

**Files:**
- Modify: `app/schemas/scans.py`

- [ ] **Step 1: Tambah ScanProgressLog dan field log**

Buka `app/schemas/scans.py`. Temukan class `ScanProgress`. Tambahkan class `ScanProgressLog` **tepat sebelum** class `ScanProgress`, dan tambahkan field `log` ke `ScanProgress`:

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

- [ ] **Step 2: Syntax check**

```bash
python -m py_compile app/schemas/scans.py && echo OK
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/schemas/scans.py
git commit -m "fix(c3): add ScanProgressLog model and log field to ScanProgress schema"
```

---

### Task 5: Backend — Update tasks.py (Stale Job Cleanup Fix)

**Context:** Cleanup task ada tapi tidak mengisi `completed_at` dan tidak menulis ke Redis log. Fix: tambah `import write_progress`, isi `completed_at`, tulis WARN ke Redis sebelum marking failed.

**Files:**
- Modify: `app/workers/tasks.py`

- [ ] **Step 1: Tambah import write_progress**

Buka `app/workers/tasks.py`. Tambahkan di bagian import:

```python
from app.workers.utils import write_progress
```

- [ ] **Step 2: Update loop stale jobs**

Temukan `for job in stale:` loop di dalam `async def _run()`. Ganti isi loop dengan:

```python
            for job in stale:
                await write_progress(
                    str(job.id), "scan", 0, 0,
                    "Scan timeout: plugin tidak merespons dalam 30 menit", "WARN",
                )
                job.status        = "failed"
                job.completed_at  = datetime.now(timezone.utc)
                job.error_message = "Scan timeout: tidak ada respons dalam 30 menit"
```

- [ ] **Step 3: Syntax check**

```bash
python -m py_compile app/workers/tasks.py && echo OK
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/workers/tasks.py
git commit -m "fix(c3): stale job cleanup sets completed_at and writes WARN to Redis log"
```

---

### Task 6: Backend — Update docker-compose.yml (Celery Beat)

**Context:** `cleanup_stale_pending_jobs` dijadwalkan di celery_app.py (`crontab */5`) tapi tidak berjalan karena tidak ada `celery-beat` service.

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Tambah service celery-beat**

Buka `docker-compose.yml`. Temukan blok service `worker-notify:`. Tambahkan service baru setelah blok tersebut:

```yaml
  celery-beat:
    <<: *app
    command: celery -A app.celery_app beat --loglevel=info
```

Pastikan indentasi 2 spasi konsisten dengan services lain.

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "fix(c3): add celery-beat service so cleanup_stale_pending_jobs runs every 5 min"
```

---

### Task 7: Backend — Update reports.py (Stream PDF)

**Context:** Endpoint saat ini return `RedirectResponse` ke presigned URL MinIO — URL internal Docker tidak accessible dari browser. Fix: download dari MinIO di backend, stream bytes ke client.

**Files:**
- Modify: `app/routers/reports.py`

- [ ] **Step 1: Tambah imports**

Buka `app/routers/reports.py`. Tambahkan di bagian import:

```python
import io
from fastapi.responses import StreamingResponse
```

- [ ] **Step 2: Ganti fungsi download_pdf**

Temukan dan ganti seluruh fungsi `download_pdf` (pertahankan decorator `@router.get`):

```python
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

- [ ] **Step 3: Syntax check**

```bash
python -m py_compile app/routers/reports.py && echo OK
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/routers/reports.py
git commit -m "fix(c3): stream PDF through FastAPI, fixes auth and MinIO internal URL issues"
```

---

### Task 8: Frontend — Update types/api.ts

**Context:** Tambah `ScanProgressEntry` interface dan field `log` ke `ScanProgress` agar TypeScript tidak error saat kode frontend membaca `job.progress.log`.

**Files:**
- Modify: `types/api.ts`

- [ ] **Step 1: Tambah ScanProgressEntry dan field log ke ScanProgress**

Buka `types/api.ts`. Temukan interface `ScanProgress`. Tambahkan interface `ScanProgressEntry` tepat sebelumnya, dan tambahkan field `log?` ke `ScanProgress`:

```typescript
export interface ScanProgressEntry {
  step:  number
  stage: string
  msg:   string
  type:  string
  ts:    number
}
```

Di dalam interface `ScanProgress` yang sudah ada, tambahkan satu field:
```typescript
  log?: ScanProgressEntry[]
```

- [ ] **Step 2: TypeScript check**

```bash
cd D:\Kuliahku\Capstone\workspace\OJSDEF-FrontEnd
npx tsc --noEmit 2>&1 | head -30
```

Expected: Tidak ada error TypeScript baru.

- [ ] **Step 3: Commit**

```bash
git add types/api.ts
git commit -m "fix(c3): add ScanProgressEntry type and log field to ScanProgress"
```

---

### Task 9: Frontend — Update scan-management/[id]/page.tsx (useMemo Log)

**Context:** useState + useEffect + prevMsgRef melewatkan step yang selesai < 3 detik. Ganti dengan useMemo yang baca `job.progress.log` langsung. Hapus juga `notifiedRef` dan useEffect "Scan selesai" — sudah tidak diperlukan karena scoring.py menulis "Scan selesai" ke Redis.

**Files:**
- Modify: `app/(dashboard)/scan-management/[id]/page.tsx`

- [ ] **Step 1: Tambah useMemo ke React import**

Buka file. Temukan baris import `{ useState, useEffect, useRef }` dari react. Tambahkan `useMemo`:

```typescript
import { useState, useEffect, useRef, useMemo } from 'react'
```

- [ ] **Step 2: Hapus logEntries state dan prevMsgRef**

Hapus baris-baris berikut:
```typescript
const [logEntries, setLogEntries] = useState<LogEntry[]>([])
const prevMsgRef = useRef<string | null>(null)
const notifiedRef = useRef(false)
```

- [ ] **Step 3: Hapus dua useEffect yang menggunakan prevMsgRef dan notifiedRef**

Hapus useEffect yang dimulai dengan `const msg = job?.progress?.message` dan mengandung `prevMsgRef.current`.

Hapus useEffect yang mengandung `job?.status === 'completed' && !notifiedRef.current`.

- [ ] **Step 4: Tambah useMemo untuk logEntries**

Tambahkan setelah deklarasi `const { data: targets } = useTargets()`:

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

- [ ] **Step 5: Pastikan auto-scroll useEffect masih ada**

Pastikan useEffect auto-scroll tetap ada (tidak terhapus di step 3):
```typescript
useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
}, [logEntries])
```

- [ ] **Step 6: TypeScript check**

```bash
cd D:\Kuliahku\Capstone\workspace\OJSDEF-FrontEnd
npx tsc --noEmit 2>&1 | head -30
```

Expected: Tidak ada error baru.

- [ ] **Step 7: Commit**

```bash
git add "app/(dashboard)/scan-management/[id]/page.tsx"
git commit -m "fix(c3): replace useState log accumulation with useMemo reading progress.log"
```

---

### Task 10: Frontend — Update hooks/use-reports.ts (Blob Download)

**Context:** `window.open(url)` tidak kirim Bearer token → 401. Ganti dengan `api.get(..., { responseType: 'blob' })` yang kirim token, trigger download dari blob.

**Files:**
- Modify: `hooks/use-reports.ts`

- [ ] **Step 1: Ganti mutationFn di useDownloadReport**

Buka `hooks/use-reports.ts`. Ganti seluruh fungsi `useDownloadReport`:

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

- [ ] **Step 2: TypeScript check**

```bash
cd D:\Kuliahku\Capstone\workspace\OJSDEF-FrontEnd
npx tsc --noEmit 2>&1 | head -30
```

Expected: Tidak ada error baru.

- [ ] **Step 3: Commit**

```bash
git add hooks/use-reports.ts
git commit -m "fix(c3): PDF download via api.get blob instead of window.open"
```

---

### Task 11: Frontend — Update lib/api.ts (Refresh Token Lock)

**Context:** Page refresh → banyak 401 paralel → banyak refresh calls bersamaan → rotating token: call pertama sukses, sisanya gagal → redirect `/login`. Fix: `_refreshPromise` shared lock.

**Files:**
- Modify: `lib/api.ts`

- [ ] **Step 1: Tambah _refreshPromise variable**

Buka `lib/api.ts`. Setelah `let _accessToken: string | null = null`, tambahkan:

```typescript
let _refreshPromise: Promise<string> | null = null
```

- [ ] **Step 2: Ganti isi blok 401 interceptor**

Temukan `if (error.response?.status === 401 && !config._retry)`. Ganti seluruh isi blok if (tidak termasuk kondisi dan outer `if`) dengan:

```typescript
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
```

- [ ] **Step 3: TypeScript check**

```bash
cd D:\Kuliahku\Capstone\workspace\OJSDEF-FrontEnd
npx tsc --noEmit 2>&1 | head -30
```

Expected: Tidak ada error baru.

- [ ] **Step 4: Commit**

```bash
git add lib/api.ts
git commit -m "fix(c3): add refresh token lock to prevent parallel 401 interceptors causing logout"
```

---

### Task 12: Final Syntax Check Semua File

- [ ] **Step 1: Syntax check BackEnd**

```bash
cd D:\Kuliahku\Capstone\workspace\OJSDEF-BackEnd
python -m py_compile app/workers/utils.py && echo "utils OK"
python -m py_compile app/schemas/scans.py && echo "schemas OK"
python -m py_compile app/workers/tasks.py && echo "tasks OK"
python -m py_compile app/routers/reports.py && echo "reports OK"
```

Expected: Semua baris mencetak `OK`.

- [ ] **Step 2: TypeScript check FrontEnd**

```bash
cd D:\Kuliahku\Capstone\workspace\OJSDEF-FrontEnd
npx tsc --noEmit 2>&1 | head -30
```

Expected: Tidak ada error TypeScript baru.

---

## Deployment

```bash
# BackEnd — docker-compose.yml berubah
git pull
docker compose down && docker compose up -d

# FrontEnd
git pull && npm run build

# Plugin — upload ojsdef-plugin-1.0.1.zip ke OJS admin panel
```
