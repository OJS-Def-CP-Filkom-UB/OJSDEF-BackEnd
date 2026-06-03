# Spec — Internal Scanner Reliability (Approach A)

## Goal

Hilangkan internal scan yang stuck di "Mode heartbeat — menunggu jadwal berikutnya..." selamanya. Buat internal scan berperilaku seperti external scan: **ter-trigger instan, tidak bergantung lalu lintas halaman OJS, dan kalau gagal langsung gagal (fail-fast) dengan diagnosa + panduan perbaikan di frontend**.

Lingkup spec ini **hanya reliability**. Pendalaman cakupan keamanan (OWASP Top 10, CVE curated, file integrity) adalah fase berikutnya dengan spec terpisah.

## Background — Root Cause (hasil analisa log)

Internal scan stuck karena **rantai 3 kegagalan**:

1. **Probe selalu HTTP 500.** Di `ojs-test-run.log`, setiap `POST /index.php/index/ojsdef/probe` balas `500`. Akibatnya `plugin_callback.py:_probe_plugin` selalu set `connection_mode = "heartbeat"` — mode `direct` (trigger instan) tidak pernah aktif. Hipotesis: `OjsdefHandler` (OJS 3.4) tidak punya `authorize()`/role policy → `PKPHandler` melempar fatal untuk op publik tanpa login.
2. **Heartbeat hanya menyala saat ada lalu lintas halaman.** `OjsdefPlugin.php` meng-hook heartbeat ke `TemplateManager::display` + throttle 5 menit. OJS test idle tanpa pengunjung → hook tak pernah menyala → scan menggantung. Tidak ada cron sungguhan.
3. **`testConnection` mengabaikan `scan_requested`.** Hanya `maybeSendHeartbeat` (hook display) yang memproses `scan_requested`; klik manual tidak men-trigger scan.

Kontras: `external_scan_task` murni Celery task — jalan instan, mandiri. Itu sebabnya external "cepat sekali".

Bukti log:
- `service-run-test.log:679-680` — `internal_scan_task` sukses dalam 0.099s (langsung ke heartbeat mode, tak ada scan).
- `ojs-test-run.log:4230,4236,4252` — `POST /index.php/index/ojsdef/probe` → `500` berulang.
- `service-run-test.log:217` — heartbeat balas 169 byte (mengandung `scan_requested`) tapi tak diproses oleh jalur `testConnection`.

## Architecture

Perubahan di tiga codebase, terkoordinasi lewat protokol HMAC yang sudah ada. Satu migration Alembic (3 kolom). Tidak ada library baru.

**Tech Stack:** PHP 7.4+ (OJSDef Plugin), Python/FastAPI + Celery (BackEnd), Next.js/TypeScript (FrontEnd).

**Prinsip alur baru:** keputusan reachability dibuat **real-time saat scan dijalankan** (pre-flight probe sinkron di dalam Celery task), bukan mengandalkan probe latar belakang dari heartbeat sebelumnya. Tidak ada lagi auto-fallback diam ke heartbeat yang menggantung.

---

## File Map

| File | Aksi | Codebase |
|------|------|----------|
| `ojsdef/OjsdefHandler.php` | Edit — tambah `authorize()`, guard plugin null (503 bukan fatal) | Plugin |
| `ojsdef/OjsdefPlugin.php` | Edit — scan async (`set_time_limit`/`ignore_user_abort`) di heartbeat path; rapikan `testConnection` | Plugin |
| `ojsdef-plugin-1.0.1.zip` | Rebuild (.NET ZipFile API) | Plugin |
| `app/workers/internal_bot.py` | Edit — pre-flight probe sinkron + fail-fast + diagnostic_code | BackEnd |
| `app/workers/tasks.py` | Edit — deadline callback 5 menit (parametrisasi threshold) | BackEnd |
| `app/models/scan_job.py` | Edit — kolom `diagnostic_code`, `diagnostic_detail` | BackEnd |
| `app/schemas/scans.py` | Edit — expose `diagnostic_code`/`diagnostic_detail` di response | BackEnd |
| `app/models/ojs_target.py` | Edit — kolom `force_heartbeat` (opt-in heartbeat) | BackEnd |
| `migrations/versions/004_*.py` | Baru — tambah 3 kolom | BackEnd |
| `types/api.ts` | Edit — tambah field diagnosa di tipe scan | FrontEnd |
| `app/(dashboard)/scan-management/[id]/page.tsx` | Edit — kartu "Diagnosa & Cara Perbaiki" + tombol Coba Lagi | FrontEnd |
| `lib/diagnostics.ts` | Baru — mapping `diagnostic_code` → judul/langkah (Bahasa Indonesia) | FrontEnd |

---

## Section 1 — Alur Trigger Baru (BackEnd, inti)

### `internal_bot.py` — `_setup_internal_scan` diganti menjadi pre-flight + fail-fast

```
internal_scan_task(job_id, target_id):
  1. Muat target + job. Set job.status = "running".
  2. PRE-FLIGHT PROBE (sinkron, timeout 10s) ke probe_endpoint (HMAC):
       - 200 + challenge echo cocok  → DIRECT
       - connect error / timeout     → FAIL  (PLUGIN_UNREACHABLE)
       - HTTP 500                    → FAIL  (PROBE_HTTP_500)
       - HTTP 401                    → FAIL  (HMAC_MISMATCH)
       - 200 tapi challenge beda     → FAIL  (CHALLENGE_MISMATCH)
  3a. DIRECT → POST trigger_endpoint (HMAC):
        - 202    → job tetap running; tunggu callback (deadline 5 menit)
        - non-202→ FAIL (TRIGGER_REJECTED)
  3b. FAIL → fail_job(job, diagnostic_code, detail):
        - job.status="failed", completed_at=now()
        - job.diagnostic_code, job.diagnostic_detail diisi
        - write_progress(..., "WARN")
  Exception khusus: jika target.force_heartbeat == True → lewati probe,
  set pending_scan_job_id (perilaku lama heartbeat), tanpa fail-fast.
```

- Probe memakai challenge acak (mis. `uuid4().hex`) yang dikirim di body; plugin meng-echo balik. Mengganti ketergantungan pada challenge yang dulu datang dari heartbeat.
- Helper `_sign_for_plugin` yang sudah ada dipakai ulang.
- `fail_job` helper baru menulis kolom diagnosa + progress WARN dalam satu transaksi.

### `tasks.py` — deadline callback 5 menit

`cleanup_stale_pending_jobs` saat ini threshold 30 menit. Tambah threshold khusus internal callback **5 menit** untuk job yang sudah `running` (sudah terima 202 tapi belum callback) → tandai `failed` dengan `diagnostic_code = CALLBACK_TIMEOUT`. Threshold dibuat parameter agar mudah diuji. Periodic task tetap jalan tiap 5 menit (butuh celery-beat — sudah ada di docker-compose).

---

## Section 2 — Perubahan Sisi Plugin (PHP)

### 2a. Fix root cause 500 di `OjsdefHandler.php`

- Override `authorize($request, $args, $roleAssignments)` agar op `probe` & `trigger` diizinkan **tanpa login** (return `true` / policy publik yang tepat untuk OJS 3.4). HMAC (`_verifyHmacFromBody`) tetap gerbang keamanan sesungguhnya.
- Guard `PluginRegistry::getPlugin('generic','ojsdef')`: jika null → balas JSON `503 {error: plugin_inactive}`, bukan fatal 500.
- **Root cause persis dikonfirmasi dari PHP-FPM/OJS error log VPS sebelum patch** (systematic-debugging). Jika penyebabnya berbeda dari hipotesis authorization, patch disesuaikan — tujuan tetap: probe/trigger balas non-5xx untuk request HMAC valid.

### 2b. Scan async di heartbeat path

`_runScanFromHeartbeat` saat ini sinkron di page request → berisiko mati di `max_execution_time`. Tambah di awal: `@set_time_limit(0); ignore_user_abort(true);` dan tutup koneksi sebelum scan berat bila memungkinkan. (`trigger` sudah benar pakai `fastcgi_finish_request()`.) Hanya relevan untuk mode opt-in heartbeat.

### 2c. `testConnection` dirapikan

Tetap lapor reachability + mode terdeteksi (direct/heartbeat) ke admin OJS. Tidak lagi diandalkan untuk men-trigger scan (jalur trigger sudah ditangani pre-flight backend).

---

## Section 3 — Taksonomi Diagnosa + Panduan Frontend

### Kolom baru `scan_jobs`

| Kolom | Tipe | Keterangan |
|-------|------|-----------|
| `diagnostic_code` | String, nullable | Kode enum diagnosa saat `failed` |
| `diagnostic_detail` | Text, nullable | Detail teknis (mis. "HTTP 500 di /probe", pesan curl) |

Kolom baru `ojs_targets`: `force_heartbeat` (Boolean, default `false`) — opt-in mode heartbeat untuk OJS di balik firewall.

### Enum `diagnostic_code` → panduan frontend

| `diagnostic_code` | Pemicu | Panduan (Bahasa Indonesia) |
|---|---|---|
| `PLUGIN_UNREACHABLE` | Probe connect error/timeout | Backend tak bisa menjangkau OJS. Cek OJS online & dapat diakses publik. Jika di balik firewall, aktifkan Mode Heartbeat. |
| `PROBE_HTTP_500` | Probe balas 500 | Plugin error di sisi OJS. Pastikan plugin OJSDef aktif & versi terbaru. Cek PHP error log OJS. |
| `HMAC_MISMATCH` | Probe/trigger balas 401 | API Key tidak cocok. Salin ulang API Key dari halaman Plugin Guide ke Settings plugin OJS. |
| `CHALLENGE_MISMATCH` | 200 tapi challenge beda | Plugin terinstal tapi tidak merespons benar. Reinstall plugin OJSDef versi terbaru. |
| `TRIGGER_REJECTED` | Trigger non-202 | Plugin menolak permintaan scan. Cek Target ID di Settings plugin cocok dengan dashboard. |
| `CALLBACK_TIMEOUT` | 202 diterima, tak ada callback dalam 5 menit | Scan dimulai tapi tak selesai (mungkin timeout PHP). Cek `max_execution_time` & `memory_limit` OJS. |

### Frontend

`lib/diagnostics.ts` memetakan kode → `{ title, steps[], showRetry }`. Di `scan-management/[id]/page.tsx`, saat status `failed` dengan `diagnostic_code`, render kartu **"Diagnosa & Cara Perbaiki"**: judul ramah, langkah bernomor, tombol **"Coba Lagi"** (memicu scan baru via `POST /api/v1/scans`) + link ke Plugin Guide target. Bukan sekadar "Scan gagal".

---

## Section 4 — Testing

### Backend (pytest)
- `internal_scan_task`: mock httpx untuk tiap skenario → assert trigger dipanggil saat probe OK; assert `job.status=="failed"` + `diagnostic_code` benar untuk connect-error / 500 / 401 / challenge-mismatch / trigger non-202.
- `force_heartbeat=True` → probe dilewati, `pending_scan_job_id` diset, tidak fail-fast.
- Callback timeout: job `running` > 5 menit → `failed` dengan `CALLBACK_TIMEOUT` (uji threshold terparametrisasi).
- Migration 004 `upgrade`/`downgrade` bersih.

### Plugin (PHPUnit)
- `OjsdefHandler::authorize()` mengizinkan op `probe`/`trigger`, menolak op lain.
- Probe HMAC valid → 200 echo challenge; HMAC invalid → 401; plugin tidak terdaftar → 503 (bukan fatal).

### End-to-end di VPS (manual, saat implementasi)
- `curl` probe dari backend → 200 (bukan 500).
- Internal scan dari dashboard → selesai < ~30 detik (tidak stuck).
- Plugin dimatikan → scan `failed` + kartu diagnosa muncul di frontend.

---

## Out of Scope

- Pendalaman cakupan keamanan: file integrity (saat ini cuma 2 file/versi), CVE matcher curated (CVE-2022-24181 Host-Header XSS, CVE-2024-56525 User-XML, dll), tambahan security headers, vuln prober multi-payload, RBAC password policy/2FA. → **Spec terpisah, fase berikutnya.**
- Arsitektur pull/cron asli untuk OJS firewall (Approach C). `force_heartbeat` cukup sebagai jembatan sementara.

## References

- OJS known CVEs: CVE-2022-24181 (XSS via Host Header), CVE-2024-56525 (User-XML, < 3.3.0-21). Versi aman: 3.3.0-18 / 3.4.0-6 ke atas.
