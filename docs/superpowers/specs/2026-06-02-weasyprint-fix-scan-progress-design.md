# WeasyPrint Fix & Scan Progress Monitoring — Design Spec

## Goal

Fix WeasyPrint 62.3 crash yang menyebabkan scoring task gagal (scan stuck `running`), dan tambahkan scan progress monitoring real-time sehingga user dapat melihat detail tahapan worker scanning di frontend.

## Architecture

**Bug fix**: Downgrade WeasyPrint + graceful fallback agar scan selalu selesai meski PDF gagal.

**Progress monitoring**: Workers menulis pesan tahap-per-tahap ke Redis. FastAPI endpoint yang sudah ada (`GET /api/v1/scans/{id}`) mengembalikan field `progress` yang sudah diparsing dari Redis. Frontend polling setiap 3 detik, mengakumulasi pesan menjadi log feed.

**Tech Stack**: FastAPI, Celery, Redis (progress store), WeasyPrint 60.2, Next.js, TanStack Query v5.

---

## Section 1: WeasyPrint Fix

### Root Cause

WeasyPrint 62.3 memanggil `super().transform()` di `pdf/stream.py:246` tapi parent class (`pydyf.Stream`) tidak punya method tersebut — regression yang tidak ada di versi 60.x.

### Perubahan File

**`requirements.txt`**
- `weasyprint==62.3` → `weasyprint==60.2`
- Docker image harus di-rebuild: `docker compose build`

**`app/services/report.py`**
- Tambah `import logging` dan `logger = logging.getLogger(__name__)`
- Return type: `Report | None`
- Wrap seluruh PDF generation + MinIO upload dalam `try/except Exception`
- On failure: `logger.warning(...)`, return `None`

```python
async def generate_pdf_report(session, job, findings) -> Report | None:
    try:
        target = ...
        html = _jinja.get_template("report.html").render(...)
        pdf = HTML(string=html).write_pdf()
        path = f"{job.tenant_id}/{job.id}/report.pdf"
        _s3().put_object(...)
        report = Report(...)
        session.add(report)
        return report
    except Exception as e:
        logger.warning(f"PDF generation failed for job {job.id}: {e}")
        return None
```

**`app/workers/scoring.py`**
- `generate_pdf_report()` return value tidak perlu di-handle — `None` diabaikan
- `job.status = "completed"` tetap dieksekusi meski PDF gagal
- Progress step 2 berubah: "Membuat laporan PDF..." → jika return `None`, lanjut ke step 3 tetap

**Frontend — halaman export/laporan**
- `vulnerability-report/page.tsx` dan `export/page.tsx`: jika `GET /api/v1/reports?job_id=xxx` return array kosong, tampilkan banner info: `"Laporan PDF tidak tersedia untuk scan ini — temuan tetap dapat dilihat di bawah."`
- Semua findings dari `GET /api/v1/scans/{id}/findings` tetap dirender normal

---

## Section 2: Backend Progress Writer

### Schema Change

**`app/schemas/scans.py`** — tambah field `log_type`:

```python
class ScanProgress(BaseModel):
    stage: Literal["external_scan", "internal_audit", "scoring", "report_gen"]
    current_step: int
    total_steps: int
    message: str
    log_type: Literal["INFO", "TASK", "DONE", "WARN"] = "INFO"
```

Pydantic v2 mengabaikan extra fields (`scan_type`, `external_done`, `internal_done`) saat parsing dari Redis — tidak perlu ubah key Redis yang ada.

### Helper `write_progress()`

**`app/workers/utils.py`** — fungsi baru, dipanggil dari semua worker:

```python
async def write_progress(
    job_id: str, stage: str, step: int, total: int,
    message: str, log_type: str = "INFO"
) -> None:
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        raw = await r.get(f"scan_progress:{job_id}")
        data = json.loads(raw) if raw else {}
        data.update({
            "stage": stage, "current_step": step,
            "total_steps": total, "message": message, "log_type": log_type,
        })
        await r.setex(f"scan_progress:{job_id}", 3600, json.dumps(data))
    finally:
        await r.aclose()
```

### Progress Steps per Worker

#### `app/workers/external_bot.py` — `_run_external_scan()`

Stage: `"external_scan"`, total: 7 langkah.

| Step | log_type | message | Dipanggil sebelum |
|------|----------|---------|-------------------|
| 1/7 | TASK | "Mendeteksi versi OJS dan fingerprint..." | `scan_fingerprint()` |
| 2/7 | TASK | "Memeriksa sertifikat SSL/TLS..." | `scan_ssl()` |
| 3/7 | TASK | "Menganalisis HTTP security headers..." | `scan_headers()` |
| 4/7 | TASK | "Menguji kerentanan yang diketahui..." | `scan_vulnerabilities()` |
| 5/7 | TASK | "Memeriksa direktori terbuka..." | `scan_open_dirs()` |
| 6/7 | TASK | "Mencocokkan CVE dari NVD..." | `scan_cve()` |
| 7/7 | DONE | "Pemindaian eksternal selesai — {n} temuan" | Setelah DB write |

#### `app/workers/internal_bot.py` — `_setup_internal_scan()`

Stage: `"internal_audit"`, total: 2 langkah.

| Step | log_type | message | Kondisi |
|------|----------|---------|---------|
| 1/2 | TASK | "Mengirim permintaan audit ke plugin OJS..." | Selalu |
| 2/2 | INFO | "Plugin merespons, menunggu callback..." | Direct mode berhasil |
| 2/2 | INFO | "Mode heartbeat — menunggu jadwal berikutnya..." | Heartbeat mode / Direct fallback |

#### `app/workers/internal_bot.py` — `_run_internal_scan()`

Stage: `"internal_audit"`, total: 7 langkah. Dipanggil dari `process_plugin_data_task`.

| Step | log_type | message | Dipanggil sebelum |
|------|----------|---------|-------------------|
| 1/7 | INFO | "Plugin callback diterima, memproses data audit..." | Awal fungsi |
| 2/7 | TASK | "Menganalisis konfigurasi OJS..." | `scan_config()` |
| 3/7 | TASK | "Memeriksa plugin yang terpasang..." | `scan_plugins()` |
| 4/7 | TASK | "Mengaudit RBAC dan pengguna..." | `scan_rbac()` |
| 5/7 | TASK | "Memeriksa integritas file..." | `scan_file_integrity()` |
| 6/7 | TASK | "Mendeteksi konten mencurigakan..." | `scan_content()` + `scan_db_security()` |
| 7/7 | DONE | "Pemindaian internal selesai — {n} temuan" | Setelah DB write |

#### `app/workers/scoring.py` — `_run_scoring()`

Stage: `"scoring"`, total: 3 langkah.

| Step | log_type | message | Dipanggil sebelum |
|------|----------|---------|-------------------|
| 1/3 | TASK | "Menghitung skor risiko CVSS..." | Awal fungsi |
| 2/3 | TASK | "Membuat laporan PDF..." | `generate_pdf_report()` |
| 3/3 | DONE | "Scan selesai" | Setelah commit |

### Catatan Full Scan

Untuk `scan_type=full`, external dan internal berjalan paralel. Redis key `scan_progress:{job_id}` ditulis oleh keduanya ("last writer wins"). Ini diterima untuk display — user melihat pesan terkini dari worker manapun yang aktif. Koordinasi `external_done`/`internal_done` tidak terpengaruh karena ditulis di akhir masing-masing worker dengan timing yang berbeda (~3s external vs ~0.04s internal process).

---

## Section 3: Frontend Log Feed

### File yang Diubah

| File | Perubahan |
|------|-----------|
| `hooks/use-scans.ts` | `refetchInterval` 4000 → 3000 |
| `types/api.ts` | Tambah `log_type` ke `ScanProgress` interface |
| `app/(dashboard)/scanning/page.tsx` | Enhance `ScanJobMonitor` dengan log feed |
| `components/scanning/ScanningPage.tsx` | **Hapus** — prototype tidak terpakai |
| `app/(dashboard)/vulnerability-report/page.tsx` | Banner "PDF tidak tersedia" |
| `app/(dashboard)/export/page.tsx` | Banner "PDF tidak tersedia" |

### TypeScript Type

**`types/api.ts`**:

```typescript
export interface ScanProgress {
  stage: 'external_scan' | 'internal_audit' | 'scoring' | 'report_gen'
  current_step: number
  total_steps: number
  message: string
  log_type: 'INFO' | 'TASK' | 'DONE' | 'WARN'
}
```

### Polling Interval

**`hooks/use-scans.ts`**:

```typescript
refetchInterval: (query) => {
  const status = query.state.data?.status
  return status === 'running' || status === 'queued' ? 3000 : false
},
```

### Persentase Overall

Progress bar tidak boleh "mundur" saat stage berganti. Persentase dihitung berdasarkan `stage` + `scan_type`:

```
scan_type=full:
  external_scan   → 0–40%
  internal_audit  → 40–70%
  scoring         → 70–100%

scan_type=external:
  external_scan   → 0–80%
  scoring         → 80–100%

scan_type=internal:
  internal_audit  → 0–80%
  scoring         → 80–100%
```

Rumus per stage: `basePercent + (current_step / total_steps) * rangePercent`

### Log Feed — Akumulasi State

`ScanJobMonitor` mendapat state baru `logEntries: LogEntry[]`. Setiap kali `progress.message` berubah (dideteksi via `useEffect` + `useRef`), entry baru ditambahkan.

```typescript
interface LogEntry {
  time: string      // "HH:MM:SS"
  type: string      // dari progress.log_type
  msg: string       // dari progress.message
}
```

Saat scan `completed`, entry final "Scan selesai" ditambahkan otomatis jika belum ada.

### Tampilan Log Feed

Panel terminal di dalam `ScanJobMonitor`, di bawah progress bar:

- Background: `#0a0f1a`
- Max height: `200px`, overflow scroll
- Auto-scroll ke entry terbaru
- Entry terakhir: border-left cyan `#00e5cc`, background `rgba(0,229,204,0.04)`
- Cursor blink di akhir log (saat `running`)
- Warna per `log_type`:
  - `INFO` → `#58a6ff` (biru)
  - `TASK` → `#e3b341` (kuning)
  - `DONE` → `#3fb950` (hijau)
  - `WARN` → `#f85149` (merah)
- Format tiap baris: `[HH:MM:SS] TYPE message`

### State yang Tidak Berubah

- `StartScanForm` — tidak berubah
- `RecentJobsList` — tidak berubah
- Routing `?jobId=` — tidak berubah
- Completed banner + "Lihat Laporan" CTA — tidak berubah
- `ScanJobMonitor` tetap menampilkan findings count dan risk score saat `completed`

---

## Data Flow Lengkap

```
Worker (external/internal/scoring)
  └─ write_progress(job_id, stage, step, total, msg, log_type)
       └─ SETEX scan_progress:{job_id} TTL=3600
              (merged dengan scan_type, external_done, internal_done)

Frontend (polling 3 detik)
  └─ GET /api/v1/scans/{job_id}
       └─ _get_progress(job_id) → Redis GET scan_progress:{job_id}
       └─ ScanProgress(**progress) → parsed (extra fields ignored)
       └─ ScanResponse { ..., progress: ScanProgress | None }

ScanJobMonitor
  └─ useEffect[progress.message] → append to logEntries[]
  └─ computeOverallPct(job) → progress bar %
  └─ render log feed dari logEntries[]
```

---

## Deployment

```bash
# Backend (VPS)
git pull
docker compose build   # wajib — WeasyPrint versi baru
docker compose down && docker compose up -d
```

Frontend tidak perlu build ulang di server jika pakai `npm run dev`. Jika production build, jalankan `npm run build` di direktori frontend.
