# Spec B — Frontend Scan Management Enhancements Design

## Goal

Tambahkan kontrol penuh bagi user atas proses scanning: cancel/retry scan, navigasi ke detail per scan, dan laporan keamanan dengan ringkasan konteks yang jelas.

## Architecture

Perubahan di dua codebase:
- **OJSDEF-BackEnd**: endpoint cancel baru + cooperative cancellation di workers
- **OJSDEF-FrontEnd**: halaman detail baru + simplifikasi scanning page + enhancements vulnerability-report

**Tech Stack:** FastAPI, Celery, Next.js 16 App Router, TanStack Query v5, ShadCN UI

---

## Section 1: Backend — Cancel Endpoint + Cooperative Cancellation

### Pendekatan

Cancel menggunakan **cooperative cancellation** — backend menandai job sebagai `cancelled` di DB, dan worker mengecek status-nya sendiri di awal setiap step. Worker berhenti di checkpoint berikutnya (biasanya dalam hitungan detik). Pendekatan ini lebih aman dari Celery `revoke(terminate=True)` karena tidak memotong DB write di tengah jalan.

`status` field di `ScanJob` adalah `String(20)` — tidak perlu Alembic migration untuk menambah nilai `'cancelled'`.

### Perubahan File

**`app/schemas/scans.py`** — tambah `'cancelled'` ke Literal status:
```python
status: Literal['queued', 'running', 'completed', 'failed', 'cancelled']
```

**`app/routers/scans.py`** — endpoint baru:
```python
@router.post("/{job_id}/cancel", status_code=200)
async def cancel_scan(
    job_id: str,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = (await db.execute(
        select(ScanJob).where(ScanJob.id == job_id)
    )).scalar_one_or_none()
    if not job:
        raise HTTPException(404)
    if job.status not in ('queued', 'running'):
        raise HTTPException(400, "Scan tidak bisa dibatalkan")
    job.status = 'cancelled'
    job.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "cancelled"}
```

**`app/workers/utils.py`** — helper baru `_check_cancelled()`:
```python
async def _check_cancelled(job_id: str) -> bool:
    from app.models import ScanJob
    async with make_worker_session() as session:
        job = (await session.execute(
            select(ScanJob).where(ScanJob.id == job_id)
        )).scalar_one_or_none()
        return job is not None and job.status == 'cancelled'
```

**`app/workers/external_bot.py`**, **`internal_bot.py`**, **`scoring.py`** — tambah cek di awal setiap step:
```python
from app.workers.utils import _try_trigger_scoring, write_progress, _check_cancelled

# Di dalam setiap worker, sebelum setiap write_progress():
if await _check_cancelled(job_id): return
await write_progress(job_id, "external_scan", 1, 7, "Mendeteksi versi OJS...", "TASK")
# ... dst untuk setiap step
```

---

## Section 2: Frontend — Halaman Detail Scan `/scan-management/[id]`

### File Baru

`app/(dashboard)/scan-management/[id]/page.tsx`

### Layout

```
┌─────────────────────────────────────────────────────┐
│ ← Kembali ke Log Teknis                             │
│                                                     │
│ [Target Name]            Status: BERJALAN ●         │
│ Tipe: Audit Penuh · 2 Jun 2026 10:29                │
├─────────────────────────────────────────────────────┤
│ Progress bar  ████████░░░░  45%                     │
│                                                     │
│ [Worker Log feed — live]                            │
│   [10:29:41] TASK Mendeteksi versi OJS...           │
│   [10:29:42] TASK Memeriksa SSL/TLS...        ▊     │
├─────────────────────────────────────────────────────┤
│ [Batalkan Scan]   (merah, hanya saat running/queued) │
└─────────────────────────────────────────────────────┘

Setelah completed:
┌─────────────────────────────────────────────────────┐
│  3 Kritis · 2 Berbahaya · 5 Perhatian · 4 Aman      │
│  Risk Score: 47.5                                   │
│                                                     │
│  [Scan Ulang]       [Lihat Laporan Lengkap →]        │
└─────────────────────────────────────────────────────┘
```

### Hooks Baru di `hooks/use-scans.ts`

```typescript
export function useCancelScan() {
  return useMutation({
    mutationFn: (jobId: string) =>
      apiClient.post(`/api/v1/scans/${jobId}/cancel`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['scans'] }),
  })
}

export function useRetryScan() {
  return useMutation({
    mutationFn: ({ targetId, scanType }: { targetId: string; scanType: ScanType }) =>
      apiClient.post<ScanJob>('/api/v1/scans', { target_id: targetId, scan_type: scanType }),
  })
}
```

### Types & Utils

**`types/api.ts`**:
```typescript
status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
```

**`lib/utils.ts`**:
```typescript
SCAN_STATUS_LABELS = { ..., cancelled: 'Dibatalkan' }
SCAN_STATUS_COLORS = { ..., cancelled: 'text-slate-400' }
```

### Logic Halaman

- `useScanJob(id)` polling 3 detik saat `running/queued`
- `useTargets()` untuk resolve nama target dari `target_id`
- Progress bar + log feed: logika identik dengan `ScanJobMonitor` yang sudah ada di `scanning/page.tsx`
- **Batalkan Scan** (tombol merah): muncul saat `running` atau `queued` → `useCancelScan(id)`
- **Scan Ulang** (tombol cyan): muncul saat `completed`, `failed`, atau `cancelled` → `useRetryScan()` → `router.push('/scan-management/' + newJob.id)`
- **Lihat Laporan Lengkap**: muncul saat `completed` → link ke `/vulnerability-report?jobId={id}`

---

## Section 3: Scanning Page Simplification + Scan-Management List Navigation

### 3A — `app/(dashboard)/scanning/page.tsx`

Halaman disederhanakan menjadi hanya form. `ScanJobMonitor` dan `RecentJobsList` dihapus.

Perubahan di `StartScanForm`:
```typescript
// Sebelum:
await startScan.mutateAsync({ targetId, scanType })

// Sesudah:
const job = await startScan.mutateAsync({ targetId, scanType })
router.push(`/scan-management/${job.id}`)
```

`useStartScan()` di `hooks/use-scans.ts` harus dikembalikan return value `ScanJob` dari API response ke caller.

Komponen `ScanJobMonitor` dan `RecentJobsList` dihapus dari file ini.

### 3B — `app/(dashboard)/scan-management/page.tsx`

**Rows clickable:**
```tsx
<tr
  key={scan.id}
  className="hover:bg-white/5 transition-colors cursor-pointer"
  onClick={() => router.push(`/scan-management/${scan.id}`)}
>
```

**Kolom Target Name** — ganti UUID truncated dengan nama target:
```tsx
const { data: targets } = useTargets()

<td className="px-6 py-3 text-slate-300 text-sm">
  {targets?.find(t => t.id === scan.target_id)?.name ?? scan.target_id.slice(0, 8) + '…'}
</td>
```

**Status `cancelled`** — otomatis ter-handle via `SCAN_STATUS_LABELS` dan `SCAN_STATUS_COLORS`.

---

## Section 4: Vulnerability-Report — Summary Header + Scan Selector

### Perubahan di `app/(dashboard)/vulnerability-report/page.tsx`

**Komponen `ScanSummary`** (baru, di dalam file yang sama):
- Props: `jobId: string`
- Data: `useScanJob(jobId)` + `useTargets()`
- Tampilan:

```
┌──────────────────────────────────────────────────────┐
│ Universitas Brawijaya — OJS                          │
│ Audit Penuh · 2 Jun 2026 10:29 · Skor: 47.5 (TINGGI)│
│                                                      │
│  3 Kritis   2 Berbahaya   5 Perhatian   4 Aman       │
└──────────────────────────────────────────────────────┘
```

**Komponen `ScanSelector`** (baru, di dalam file yang sama):
- Props: `scans: ScanJob[]`, `selectedId: string | null`, `onSelect: (id: string) => void`
- ShadCN `Select` dengan option label: `"{targetName} — {SCAN_TYPE_LABELS[type]} — {date}"`
- `useTargets()` untuk resolve nama

**Perubahan `VulnerabilityReportContent`:**
```typescript
const { data: scans } = useScans({ limit: 20 })
const completedScans = scans?.filter(s => s.status === 'completed') ?? []
const jobIdFromUrl = searchParams.get('jobId')
const selectedJobId = jobIdFromUrl ?? completedScans[0]?.id ?? null

function handleSelect(id: string) {
  router.replace(`/vulnerability-report?jobId=${id}`)
}

// Render:
<ScanSelector scans={completedScans} selectedId={selectedJobId} onSelect={handleSelect} />
{selectedJobId && <ScanSummary jobId={selectedJobId} />}
{selectedJobId ? <FindingsList jobId={selectedJobId} /> : <EmptyState />}
```

`AutoSelectJob` dihapus — digantikan oleh logika di atas.

---

## File Summary

| File | Aksi | Codebase |
|------|------|----------|
| `app/schemas/scans.py` | Edit — tambah `'cancelled'` ke status Literal | BackEnd |
| `app/routers/scans.py` | Edit — tambah `POST /{id}/cancel` | BackEnd |
| `app/workers/utils.py` | Edit — tambah `_check_cancelled()` | BackEnd |
| `app/workers/external_bot.py` | Edit — cek cancelled setiap step | BackEnd |
| `app/workers/internal_bot.py` | Edit — cek cancelled setiap step | BackEnd |
| `app/workers/scoring.py` | Edit — cek cancelled di awal | BackEnd |
| `types/api.ts` | Edit — tambah `'cancelled'` ke status | FrontEnd |
| `lib/utils.ts` | Edit — label & warna `cancelled` | FrontEnd |
| `hooks/use-scans.ts` | Edit — `useCancelScan`, `useRetryScan`, fix `useStartScan` return | FrontEnd |
| `app/(dashboard)/scan-management/[id]/page.tsx` | **Buat baru** | FrontEnd |
| `app/(dashboard)/scan-management/page.tsx` | Edit — clickable rows + target name | FrontEnd |
| `app/(dashboard)/scanning/page.tsx` | Edit — redirect + hapus monitor | FrontEnd |
| `app/(dashboard)/vulnerability-report/page.tsx` | Edit — ScanSummary + ScanSelector | FrontEnd |

---

## Deployment

```bash
# Backend — tidak perlu rebuild image
git pull && docker compose down && docker compose up -d

# Frontend
git pull && npm run build
```
