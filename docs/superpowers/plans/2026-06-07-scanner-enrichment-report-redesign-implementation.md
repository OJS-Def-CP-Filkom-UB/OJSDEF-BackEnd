# Scanner Enrichment & Report Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Setiap finding scanner (internal & eksternal) memiliki `references` dan `remediation_steps` terstruktur, `scan_jobs` mencatat `module_errors` per modul yang gagal, `ojs_targets.ojs_version` ter-propagate otomatis dari hasil scan, dan halaman Laporan Keamanan menampilkan status semua modul scanner (ditemukan/bersih/gagal/info) plus detail temuan yang lebih kaya.

**Architecture:** Tambah migration 010 (kolom nullable baru — additive, non-breaking). Alih-alih mengedit ~29 `make_finding()` call sites tersebar di 15 file scanner (pendekatan literal di spec section 3.4), buat **satu sumber data terpusat** `app/scanners/enrichment.py` berisi `ENRICHMENT_DATA: dict[str, dict]` keyed by `finding_type`, lalu modifikasi `make_finding()` agar otomatis melakukan lookup dan merge `references`+`remediation_steps`. Ini functionally identik dengan spec (semua finding type dapat enrichment), tapi jauh lebih DRY, lebih kecil risiko ada call site yang terlewat, dan scanner module files (`ssl_analyzer.py`, `fingerprinter.py`, `vuln_prober.py`, dll.) **tidak perlu diubah sama sekali** untuk enrichment — lihat catatan "Deviasi dari Spec" di bawah. Worker (`internal_bot.py`, `external_bot.py`) dibungkus try/except per modul untuk mengisi `module_errors`, dan mem-propagate `ojs_version` ke `OJSTarget`. Frontend mendapat helper `lib/scanner-modules.ts` baru untuk menghitung status per modul, redesign `vulnerability-report/page.tsx` dengan grid status modul + paginasi, dan badge `ojs_version` di halaman detail target.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic (backend); Next.js 16 App Router + TanStack Query + TypeScript (frontend). Lihat `OJSDEF-BackEnd/CLAUDE.md` dan `OJSDEF-FrontEnd/CLAUDE.md`.

**Constraint penting:** Tidak ada database lokal aktif maupun Docker. Semua langkah verifikasi di plan ini HANYA berupa: (a) Python syntax/AST check, (b) `python -c "import ..."` static import check, (c) `npm run lint` / `npx tsc --noEmit` / `npm run build` untuk frontend, (d) review manual kode. **Tidak ada** `alembic upgrade`, tidak ada test yang menyentuh database/Redis/MinIO, tidak ada `docker compose up`.

---

## Deviasi dari Spec — Centralized Enrichment Architecture

Spec section 3.4 menyatakan *"Setiap `make_finding()` call yang sudah ada diperbarui dengan `references` dan `remediation_steps`"* — ini berarti mengedit ±29 call sites di 15 file scanner berbeda (`config_scanner.py`, `plugin_auditor.py`, `rbac_auditor.py`, `file_integrity.py`, `content_detector.py`, `ssl_analyzer.py`, `fingerprinter.py`, `vuln_prober.py`, `open_dir_detector.py`, `cve_matcher.py`, `endpoint_checker.py`, dll).

**Pendekatan plan ini:** Buat `app/scanners/enrichment.py` berisi dict tunggal `ENRICHMENT_DATA: dict[str, dict[str, list[str]]]` yang memetakan setiap `finding_type` ke `{"references": [...], "remediation_steps": [...]}`. Modifikasi `make_finding(finding_type, **kwargs)` di `app/scanners/models.py` agar — jika caller tidak secara eksplisit memberikan `references`/`remediation_steps` — melakukan lookup ke `ENRICHMENT_DATA` dan mengisi otomatis.

**Hasil:** Semua 42 finding type (17 internal + 25 eksternal, termasuk 5 baru) mendapat enrichment tanpa menyentuh satupun scanner module file existing — kecuali `header_checker.py` dan `cookie_analyzer.py` yang memang butuh **perubahan logika** (bukan sekadar enrichment) untuk mendeteksi 3 header baru dan 2 flag cookie baru. Untuk `cve_matcher.py`, finding `cve_ojs` butuh `references` dinamis (URL NVD per-CVE) — ditangani dengan parameter override eksplisit di call site (lihat Task 7), bukan lewat `ENRICHMENT_DATA` statis.

**Keuntungan:** (1) tidak ada risiko call site terlewat — cakupan 100% by construction; (2) satu file untuk maintenance konten enrichment ke depan; (3) lebih sedikit file diff → lebih mudah direview; (4) sejalan dengan prinsip DRY di `CLAUDE.md` workspace root.

---

## File Map

### Backend — dibuat/diubah
| File | Perubahan |
|---|---|
| `migrations/versions/010_scanner_enrichment.py` | BARU — migration additive (3 kolom nullable) |
| `app/models/scan_finding.py` | Tambah kolom `references`, `remediation_steps` |
| `app/models/scan_job.py` | Tambah kolom `module_errors` |
| `app/scanners/enrichment.py` | BARU — `ENRICHMENT_DATA` dict terpusat (42 entries) |
| `app/scanners/models.py` | Tambah field `references`/`remediation_steps` ke `FindingResult`; `make_finding()` auto-lookup; 5 entry CVSS baru |
| `app/scanners/external/header_checker.py` | Tambah 3 header: Referrer-Policy, Permissions-Policy, X-Content-Type-Options |
| `app/scanners/external/cookie_analyzer.py` | Tambah cek HttpOnly + SameSite |
| `app/schemas/scans.py` | `FindingResponse` + `ScanResponse` — tambah field baru |
| `app/routers/scans.py` | Update 3 lokasi konstruksi response (`_to_response`, 2× `FindingResponse`) |
| `app/workers/internal_bot.py` | try/except per modul → `module_errors`; propagate `ojs_version` |
| `app/workers/external_bot.py` | try/except per modul → `module_errors`; propagate `ojs_version`; import `OJSTarget` |

### Frontend — dibuat/diubah
| File | Perubahan |
|---|---|
| `types/api.ts` | `ScanFinding` + `ScanJob` — tambah field baru |
| `lib/scanner-modules.ts` | BARU — `INTERNAL_MODULES`, `EXTERNAL_MODULES`, `MODULE_FINDING_TYPES`, `getModuleStatus()` |
| `app/(dashboard)/vulnerability-report/page.tsx` | Tambah `ModuleStatusGrid`, enhanced `FindingCard` (langkah bernomor + referensi), filter per modul, paginasi |
| `app/(dashboard)/targets/[id]/page.tsx` | Badge `ojs_version` + fallback teks |

### Dokumentasi
| File | Perubahan |
|---|---|
| `OJSDEF-Plugin/docs/panduan-test-skenario-ojsdef.md` | Pisahkan skenario B-5 (header gabungan) jadi per-header; tambah skenario header/cookie baru |

---

## Task 1: Migration 010 — Tambah Kolom Enrichment & Module Errors

**Files:**
- Create: `OJSDEF-BackEnd/migrations/versions/010_scanner_enrichment.py`
- Reference (style): `OJSDEF-BackEnd/migrations/versions/004_internal_scan_diagnostics.py`

- [ ] **Step 1: Buat file migration 010**

```python
"""Tambah kolom enrichment (references, remediation_steps) ke scan_findings dan module_errors ke scan_jobs

Mendukung redesign laporan keamanan: setiap finding kini menyertakan referensi
standar (OWASP/CWE/CVE) dan langkah perbaikan terstruktur (numbered steps),
serta scan_jobs mencatat modul scanner mana yang gagal dijalankan.

Revision ID: 010
Revises: 009
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scan_findings", sa.Column("references", sa.Text(), nullable=True))
    op.add_column("scan_findings", sa.Column("remediation_steps", sa.Text(), nullable=True))
    op.add_column("scan_jobs", sa.Column("module_errors", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("scan_jobs", "module_errors")
    op.drop_column("scan_findings", "remediation_steps")
    op.drop_column("scan_findings", "references")
```

- [ ] **Step 2: Verifikasi sintaks (TIDAK menjalankan `alembic upgrade` — tidak ada DB aktif)**

Run: `cd OJSDEF-BackEnd; python -c "import ast; ast.parse(open('migrations/versions/010_scanner_enrichment.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Verifikasi revision chain**

Run (PowerShell): `Select-String -Path "OJSDEF-BackEnd\migrations\versions\010_scanner_enrichment.py" -Pattern 'revision = "010"|down_revision = "009"'`
Expected: kedua baris ditemukan — memastikan chain 009→010 tersambung benar (revision terakhir di repo adalah 009, bukan 006/007 seperti di CLAUDE.md/spec).

- [ ] **Step 4: Commit**

```bash
git add OJSDEF-BackEnd/migrations/versions/010_scanner_enrichment.py
git commit -m "feat: add migration 010 for finding enrichment and module_errors columns"
```

---

## Task 2: ORM Model Updates — `ScanFinding` & `ScanJob`

**Files:**
- Modify: `OJSDEF-BackEnd/app/models/scan_finding.py`
- Modify: `OJSDEF-BackEnd/app/models/scan_job.py`

- [ ] **Step 1: Tambah kolom ke `ScanFinding` — sisipkan baris baru tepat setelah `remediation: Mapped[str] = mapped_column(Text, nullable=False)`**

```python
    references: Mapped[str | None] = mapped_column(Text, nullable=True)
    remediation_steps: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 2: Tambah kolom ke `ScanJob` — sisipkan baris baru tepat setelah `diagnostic_detail: Mapped[str | None] = mapped_column(Text, nullable=True)`**

```python
    module_errors: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 3: Verifikasi sintaks kedua file**

Run: `cd OJSDEF-BackEnd; python -c "import ast; [ast.parse(open(f).read()) for f in ['app/models/scan_finding.py','app/models/scan_job.py']]; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add OJSDEF-BackEnd/app/models/scan_finding.py OJSDEF-BackEnd/app/models/scan_job.py
git commit -m "feat: add references, remediation_steps, module_errors columns to ORM models"
```

---

## Task 3: Buat `app/scanners/enrichment.py` — Centralized `ENRICHMENT_DATA` (Bagian 1: Internal Findings)

**Files:**
- Create: `OJSDEF-BackEnd/app/scanners/enrichment.py`

- [ ] **Step 1: Buat file dengan header modul + 17 entry internal findings**

```python
"""Data enrichment terpusat untuk semua finding type scanner.

Setiap entry memetakan finding_type ke daftar referensi standar (OWASP/CWE/
vendor) dan langkah perbaikan bernomor dalam Bahasa Indonesia. make_finding()
di scanners/models.py melakukan lookup otomatis ke dict ini — lihat Task 4.

Finding type yang butuh konten dinamis (mis. cve_ojs dengan {cve_id}) di-
override eksplisit oleh caller; lookup di sini hanya dipakai sebagai fallback
saat caller tidak memberikan references/remediation_steps secara eksplisit.
"""

ENRICHMENT_DATA: dict[str, dict[str, list[str]]] = {
    # ==================== INTERNAL FINDINGS ====================
    "debug_mode_active": {
        "remediation_steps": [
            "Buka file config.inc.php di direktori root instalasi OJS.",
            "Temukan section [debug] dan ubah semua flag menjadi Off: display_errors = Off, show_errors = Off, show_stacktrace = Off",
            "Simpan file config.inc.php.",
            "Reload web server: sudo systemctl reload nginx (atau apache2).",
            "Verifikasi: akses URL yang tidak valid di OJS dan pastikan tidak ada stack trace PHP yang tampil, hanya halaman error generik.",
        ],
        "references": [
            "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
            "https://cwe.mitre.org/data/definitions/209.html",
            "https://docs.pkp.sfu.ca/dev/documentation/en/getting-started",
            "https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html",
        ],
    },
    "force_ssl_disabled": {
        "remediation_steps": [
            "Buka file config.inc.php di direktori root OJS.",
            "Cari baris force_ssl = Off di section [security] dan ubah menjadi force_ssl = On.",
            "Pastikan sertifikat SSL/TLS sudah terpasang dan valid di web server sebelum mengaktifkan force_ssl.",
            "Tambahkan redirect HTTP→HTTPS di konfigurasi Nginx: return 301 https://$host$request_uri;",
            "Reload web server: sudo systemctl reload nginx",
            "Verifikasi: akses http://<domain> dan pastikan otomatis redirect ke https://<domain>.",
        ],
        "references": [
            "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
            "https://cwe.mitre.org/data/definitions/319.html",
            "https://docs.pkp.sfu.ca/dev/documentation/en/getting-started",
            "https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html",
        ],
    },
    "smtp_no_auth": {
        "remediation_steps": [
            "Buka file config.inc.php, temukan section [email].",
            "Set smtp_auth sesuai mekanisme autentikasi server SMTP (mis. smtp_auth = LOGIN atau PLAIN).",
            "Isi smtp_username dan smtp_password dengan kredensial akun SMTP yang valid.",
            "Pastikan koneksi SMTP menggunakan TLS: smtp_secure = tls atau ssl sesuai port (587/465).",
            "Kirim email uji dari OJS (mis. notifikasi pengguna baru) untuk memastikan autentikasi berhasil.",
        ],
        "references": [
            "https://owasp.org/Top10/A07_2021-Identification_and_Authentication_Failures/",
            "https://cwe.mitre.org/data/definitions/306.html",
            "https://docs.pkp.sfu.ca/dev/documentation/en/getting-started",
        ],
    },
    "db_password_empty": {
        "remediation_steps": [
            "Generate password database yang kuat (minimal 16 karakter campuran): openssl rand -base64 24",
            "Set password baru di PostgreSQL: ALTER USER ojsdef WITH PASSWORD '<password_baru>';",
            "Perbarui kredensial database di config.inc.php (parameter password di section [database]).",
            "Restart layanan agar konfigurasi baru terbaca: sudo systemctl restart php8.1-fpm nginx",
            "Hapus riwayat shell yang berisi password lama bila perlu: history -c",
        ],
        "references": [
            "https://owasp.org/Top10/A07_2021-Identification_and_Authentication_Failures/",
            "https://cwe.mitre.org/data/definitions/521.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html",
        ],
    },
    "api_key_too_short": {
        "remediation_steps": [
            "Generate API key baru dengan panjang minimal 32 karakter acak: openssl rand -hex 32",
            "Perbarui nilai API key di pengaturan plugin OJSDef pada panel admin OJS (Settings → Website → Plugins → OJSDef).",
            "Perbarui juga nilai yang sesuai di dashboard OJSDef agar pairing tetap valid.",
            "Simpan API key baru di tempat aman (password manager) — jangan commit ke version control.",
            "Lakukan rotasi API key secara berkala (mis. setiap 90 hari).",
        ],
        "references": [
            "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
            "https://cwe.mitre.org/data/definitions/326.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html",
        ],
    },
    "multiple_superadmin": {
        "remediation_steps": [
            "Login ke OJS sebagai Site Administrator.",
            "Buka menu Administration → Site Management → Users.",
            "Filter pengguna dengan role 'Site Administrator'.",
            "Identifikasi akun Site Administrator yang tidak diperlukan.",
            "Klik nama pengguna → Edit → ubah role menjadi 'Journal Manager' untuk jurnal yang relevan, atau nonaktifkan akun.",
            "Pertahankan hanya 1 akun Site Administrator aktif sebagai prinsip least privilege.",
            "Dokumentasikan akun yang diubah untuk audit trail.",
        ],
        "references": [
            "https://owasp.org/Top10/A01_2021-Broken_Access_Control/",
            "https://cwe.mitre.org/data/definitions/269.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Access_Control_Cheat_Sheet.html",
            "https://docs.pkp.sfu.ca/admin-guide/en/users-and-roles",
        ],
    },
    "inactive_high_priv_account": {
        "remediation_steps": [
            "Login sebagai Site Administrator → Administration → Site Management → Users.",
            "Filter pengguna dengan role tinggi (Site Administrator/Journal Manager) dan urutkan berdasarkan tanggal login terakhir.",
            "Identifikasi akun yang tidak aktif lebih dari 90 hari.",
            "Nonaktifkan akun tersebut (Disable User) atau hapus jika sudah tidak relevan.",
            "Terapkan kebijakan review akses berkala (mis. setiap kuartal) untuk mencegah akumulasi akun idle.",
        ],
        "references": [
            "https://owasp.org/Top10/A07_2021-Identification_and_Authentication_Failures/",
            "https://cwe.mitre.org/data/definitions/613.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Access_Control_Cheat_Sheet.html",
        ],
    },
    "modified_core_file": {
        "remediation_steps": [
            "SEGERA: Aktifkan maintenance mode dan isolasi server dari traffic publik jika dicurigai kompromi aktif.",
            "Bandingkan file yang termodifikasi dengan checksum resmi versi OJS terpasang (lihat 'affected_path' pada temuan).",
            "Backup file termodifikasi untuk forensik: cp <file> <file>.suspect.bak",
            "Timpa file core dengan versi resmi dari arsip rilis OJS: https://github.com/pkp/ojs/releases",
            "Audit log akses web server untuk mengidentifikasi waktu dan sumber modifikasi.",
            "Reset semua kredensial admin dan API key setelah pembersihan selesai.",
            "Jalankan ulang scan integritas file untuk memastikan tidak ada file lain yang termodifikasi.",
        ],
        "references": [
            "https://owasp.org/Top10/A08_2021-Software_and_Data_Integrity_Failures/",
            "https://cwe.mitre.org/data/definitions/494.html",
            "https://docs.pkp.sfu.ca/dev/documentation/en/getting-started",
        ],
    },
    "modified_plugin_file": {
        "remediation_steps": [
            "Identifikasi plugin yang file-nya termodifikasi dari 'affected_path' pada temuan.",
            "Backup file untuk forensik, lalu timpa dengan versi resmi dari repository/marketplace plugin OJS.",
            "Jika plugin pihak ketiga, unduh ulang dari sumber terpercaya dan verifikasi checksum jika tersedia.",
            "Audit log akses untuk mengidentifikasi kapan dan bagaimana modifikasi terjadi.",
            "Pertimbangkan menonaktifkan plugin sementara jika tidak yakin dengan integritasnya.",
            "Jalankan ulang scan file integrity setelah pembersihan untuk konfirmasi.",
        ],
        "references": [
            "https://owasp.org/Top10/A08_2021-Software_and_Data_Integrity_Failures/",
            "https://cwe.mitre.org/data/definitions/494.html",
            "https://docs.pkp.sfu.ca/admin-guide/en/plugins",
        ],
    },
    "missing_core_file": {
        "remediation_steps": [
            "Identifikasi file core yang hilang dari 'affected_path' pada temuan.",
            "Bandingkan dengan struktur direktori resmi versi OJS yang sama dari https://github.com/pkp/ojs/releases",
            "Salin ulang file yang hilang dari arsip rilis resmi (jangan dari sumber tidak terpercaya).",
            "Periksa permission file setelah penyalinan: chown -R www-data:www-data <path> && chmod 644 <file>",
            "Jalankan ulang scan file integrity untuk memastikan struktur file sudah lengkap dan utuh.",
        ],
        "references": [
            "https://owasp.org/Top10/A08_2021-Software_and_Data_Integrity_Failures/",
            "https://cwe.mitre.org/data/definitions/494.html",
            "https://docs.pkp.sfu.ca/dev/upgrade-guide/",
        ],
    },
    "gambling_content": {
        "remediation_steps": [
            "SEGERA: Identifikasi lokasi konten berjudi dari 'affected_path' (artikel, halaman, atau metadata jurnal).",
            "Hapus konten berjudi dari database melalui panel admin OJS atau langsung via psql.",
            "Audit seluruh artikel dan halaman statis untuk konten serupa (cari kata kunci terkait judi/taruhan).",
            "Periksa log akses dan log perubahan konten untuk mengidentifikasi akun yang melakukan injeksi.",
            "Reset password seluruh akun dengan hak edit konten (Editor, Section Editor, Journal Manager).",
            "Audit plugin pihak ketiga yang memungkinkan injeksi konten (rich text editor, file upload).",
            "Jalankan ulang scan content injection setelah pembersihan untuk konfirmasi.",
        ],
        "references": [
            "https://owasp.org/Top10/A03_2021-Injection/",
            "https://cwe.mitre.org/data/definitions/74.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html",
        ],
    },
    "eval_base64_injection": {
        "remediation_steps": [
            "SEGERA: Pertimbangkan mengisolasi server dari internet jika memungkinkan saat proses pembersihan.",
            "Identifikasi lokasi persis konten berbahaya dari field 'affected_path' di temuan ini.",
            "Hapus konten yang mengandung eval(base64_decode(...)) dari database OJS menggunakan phpMyAdmin atau psql.",
            "Audit seluruh file PHP di server: find /path/to/ojs -name \"*.php\" | xargs grep -l \"eval(base64\"",
            "Periksa log akses web server (access.log) untuk mengidentifikasi kapan dan bagaimana injeksi terjadi.",
            "Reset password semua akun admin OJS dan pastikan MFA aktif jika tersedia.",
            "Update OJS ke versi terbaru dan semua plugin ke versi terbaru.",
            "Jalankan full scan ulang setelah pembersihan untuk konfirmasi tidak ada sisa injeksi.",
        ],
        "references": [
            "https://owasp.org/Top10/A03_2021-Injection/",
            "https://cwe.mitre.org/data/definitions/94.html",
            "https://cwe.mitre.org/data/definitions/506.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html",
        ],
    },
    "hidden_iframe_injection": {
        "remediation_steps": [
            "Identifikasi lokasi iframe tersembunyi dari 'affected_path' dan 'evidence' pada temuan.",
            "Hapus tag <iframe> mencurigakan dari konten artikel/halaman melalui database atau panel admin.",
            "Audit seluruh konten yang dapat diedit pengguna untuk pola iframe serupa (display:none, width=0, height=0).",
            "Terapkan sanitasi HTML pada input konten menggunakan library seperti HTML Purifier.",
            "Tambahkan Content-Security-Policy dengan directive frame-src yang ketat untuk mencegah injeksi iframe eksternal.",
            "Jalankan ulang scan content injection untuk konfirmasi pembersihan.",
        ],
        "references": [
            "https://owasp.org/Top10/A03_2021-Injection/",
            "https://cwe.mitre.org/data/definitions/79.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html",
        ],
    },
    "phishing_tld_link": {
        "remediation_steps": [
            "Identifikasi tautan mencurigakan dari 'affected_path' dan 'evidence' pada temuan (domain dengan TLD tidak lazim).",
            "Hapus atau ganti tautan tersebut dari konten artikel/halaman jurnal.",
            "Audit seluruh konten yang mengandung tautan eksternal untuk pola serupa.",
            "Periksa akun yang menambahkan tautan tersebut dan reset kredensialnya jika dicurigai disusupi.",
            "Edukasi editor/penulis untuk selalu memverifikasi tautan eksternal sebelum dipublikasikan.",
        ],
        "references": [
            "https://owasp.org/Top10/A03_2021-Injection/",
            "https://cwe.mitre.org/data/definitions/601.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Unvalidated_Redirects_and_Forwards_Cheat_Sheet.html",
        ],
    },
    "js_redirect_injection": {
        "remediation_steps": [
            "Identifikasi lokasi script redirect dari 'affected_path' dan 'evidence' pada temuan.",
            "Hapus kode JavaScript injeksi (window.location, document.location, meta refresh mencurigakan) dari konten/template.",
            "Audit template tema dan plugin pihak ketiga untuk kode serupa yang disisipkan.",
            "Terapkan Content-Security-Policy dengan directive script-src yang membatasi sumber script.",
            "Reset kredensial akun yang memiliki akses edit template/tema.",
            "Jalankan ulang scan content injection untuk konfirmasi pembersihan.",
        ],
        "references": [
            "https://owasp.org/Top10/A03_2021-Injection/",
            "https://cwe.mitre.org/data/definitions/601.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html",
        ],
    },
    "disabled_plugins_installed": {
        "remediation_steps": [
            "Login sebagai Site/Journal Administrator → Settings → Website → Plugins.",
            "Tinjau daftar plugin yang terpasang namun nonaktif dari 'affected_path' pada temuan.",
            "Untuk plugin yang tidak akan dipakai: uninstall sepenuhnya untuk mengurangi attack surface (Plugin Gallery → Uninstall).",
            "Untuk plugin yang mungkin dipakai kembali: pastikan tetap diperbarui ke versi terbaru meski nonaktif.",
            "Dokumentasikan keputusan (uninstall/keep) untuk audit trail konfigurasi jurnal.",
        ],
        "references": [
            "https://owasp.org/Top10/A06_2021-Vulnerable_and_Outdated_Components/",
            "https://cwe.mitre.org/data/definitions/1104.html",
            "https://docs.pkp.sfu.ca/admin-guide/en/plugins",
        ],
    },
    "excessive_active_plugins": {
        "remediation_steps": [
            "Login sebagai Site/Journal Administrator → Settings → Website → Plugins.",
            "Tinjau daftar plugin aktif dan identifikasi mana yang benar-benar digunakan oleh jurnal.",
            "Nonaktifkan plugin yang tidak esensial untuk mengurangi permukaan serangan dan beban server.",
            "Pastikan seluruh plugin yang tetap aktif diperbarui ke versi terbaru secara berkala.",
            "Lakukan review plugin aktif setiap kali ada upgrade major OJS.",
        ],
        "references": [
            "https://owasp.org/Top10/A06_2021-Vulnerable_and_Outdated_Components/",
            "https://docs.pkp.sfu.ca/admin-guide/en/plugins",
        ],
    },
```

Catatan: dict belum ditutup — lanjutan entry eksternal ditambahkan di Task 4 (jangan tutup `}` dulu).

- [ ] **Step 2: Verifikasi sintaks parsial — pastikan tidak ada typo bracket sejauh ini**

Run: `cd OJSDEF-BackEnd; python -c "import ast; ast.parse(open('app/scanners/enrichment.py').read() + chr(10) + '}')" 2>$null; echo done`

Catatan: ini hanya cek kasar (menambah penutup sementara) karena dict belum lengkap di step ini — verifikasi penuh dilakukan di akhir Task 4 setelah file selesai.

---

## Task 4: Lanjutkan `enrichment.py` — Bagian 2 (External Findings) & Tutup Dict

**Files:**
- Modify: `OJSDEF-BackEnd/app/scanners/enrichment.py` (lanjutan dari Task 3 — append sebelum baris penutup)

- [ ] **Step 1: Tambahkan 25 entry external findings, lalu tutup dict `}`**

Tambahkan kode berikut tepat setelah entry `"excessive_active_plugins"` (baris terakhir Task 3, sebelum penutup dict):

```python
    # ==================== EXTERNAL FINDINGS ====================
    "ojs_version_exposed": {
        "remediation_steps": [
            "Buka file templates/frontend/components/header.tpl atau lib/pkp/templates/common/footer.tpl dan hapus tag generator/meta yang menampilkan versi OJS.",
            "Periksa juga file README, CHANGELOG, dan dokumen publik lain di webroot yang mungkin mengekspos versi.",
            "Tambahkan aturan Nginx untuk memblokir akses dokumen tersebut: location ~* (README|CHANGELOG)\\.(md|txt)$ { deny all; }",
            "Verifikasi dengan curl https://<domain> | grep -i \"ojs\" untuk memastikan versi tidak lagi terekspos di HTML.",
        ],
        "references": [
            "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
            "https://cwe.mitre.org/data/definitions/200.html",
            "https://docs.pkp.sfu.ca/dev/documentation/en/getting-started",
        ],
    },
    "outdated_ojs_version": {
        "remediation_steps": [
            "Cek versi OJS terbaru yang stabil di https://pkp.sfu.ca/ojs/ojs_download/",
            "Backup database dan seluruh file OJS sebelum upgrade: pg_dump ojsdb > backup.sql && tar -czf ojs-backup.tar.gz /path/to/ojs",
            "Baca catatan rilis (release notes) untuk perubahan breaking dan langkah migrasi khusus.",
            "Ikuti panduan upgrade resmi: https://docs.pkp.sfu.ca/dev/upgrade-guide/",
            "Jalankan php tools/upgrade.php upgrade setelah file baru di-deploy.",
            "Verifikasi fungsionalitas jurnal pasca-upgrade dan jalankan ulang scan untuk konfirmasi versi sudah terbaru.",
        ],
        "references": [
            "https://owasp.org/Top10/A06_2021-Vulnerable_and_Outdated_Components/",
            "https://cwe.mitre.org/data/definitions/1104.html",
            "https://docs.pkp.sfu.ca/dev/upgrade-guide/",
            "https://pkp.sfu.ca/category/news/announcements/releases/",
        ],
    },
    "ssl_expired": {
        "remediation_steps": [
            "Perbarui sertifikat SSL segera — sertifikat kedaluwarsa menyebabkan semua pengunjung melihat peringatan keamanan.",
            "Jika menggunakan Let's Encrypt: jalankan sudo certbot renew --force-renewal",
            "Jika menggunakan CA komersial: beli/renew sertifikat baru dari penyedia CA, lalu install di web server.",
            "Setelah install sertifikat baru, reload Nginx: sudo systemctl reload nginx",
            "Aktifkan auto-renewal untuk mencegah kedaluwarsa di masa depan: sudo systemctl enable certbot.timer",
            "Verifikasi sertifikat baru: openssl s_client -connect <domain>:443 | grep \"notAfter\"",
        ],
        "references": [
            "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
            "https://cwe.mitre.org/data/definitions/298.html",
            "https://letsencrypt.org/docs/certificate-compatibility/",
            "https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html",
        ],
    },
    "ssl_expiring_soon": {
        "remediation_steps": [
            "Cek tanggal kedaluwarsa pasti: openssl s_client -connect <domain>:443 | grep \"notAfter\"",
            "Jika menggunakan Let's Encrypt: pastikan certbot.timer aktif untuk auto-renewal: sudo systemctl status certbot.timer",
            "Jika auto-renewal tidak aktif, jalankan manual: sudo certbot renew",
            "Jika menggunakan CA komersial: ajukan renewal sebelum tanggal kedaluwarsa ke penyedia CA.",
            "Setelah sertifikat baru terpasang, reload web server: sudo systemctl reload nginx",
        ],
        "references": [
            "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
            "https://cwe.mitre.org/data/definitions/298.html",
            "https://letsencrypt.org/docs/certificate-compatibility/",
        ],
    },
    "weak_tls": {
        "remediation_steps": [
            "Buka konfigurasi Nginx (biasanya /etc/nginx/sites-available/<site>) dan temukan directive ssl_protocols.",
            "Nonaktifkan protokol lama: ssl_protocols TLSv1.2 TLSv1.3; (hapus SSLv3, TLSv1.0, TLSv1.1)",
            "Perbarui daftar cipher suite ke preset modern dari https://ssl-config.mozilla.org/ (pilih profil 'Intermediate').",
            "Reload Nginx: sudo systemctl reload nginx",
            "Verifikasi konfigurasi dengan https://www.ssllabs.com/ssltest/ atau testssl.sh — targetkan grade A.",
        ],
        "references": [
            "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
            "https://cwe.mitre.org/data/definitions/327.html",
            "https://ssl-config.mozilla.org/",
            "https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html",
        ],
    },
    "http_no_https_redirect": {
        "remediation_steps": [
            "Buka konfigurasi server block Nginx untuk port 80 (HTTP).",
            "Tambahkan redirect permanen ke HTTPS: server { listen 80; server_name <domain>; return 301 https://$host$request_uri; }",
            "Pastikan tidak ada konten yang disajikan langsung melalui blok HTTP tersebut.",
            "Reload konfigurasi: sudo systemctl reload nginx",
            "Verifikasi: curl -I http://<domain> — harus mengembalikan status 301 dengan header Location: https://...",
        ],
        "references": [
            "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
            "https://cwe.mitre.org/data/definitions/319.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html",
        ],
    },
    "missing_csp": {
        "remediation_steps": [
            "Tambahkan header Content-Security-Policy di blok server Nginx.",
            "Mulai dengan kebijakan moderat: add_header Content-Security-Policy \"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;\" always;",
            "Uji halaman jurnal dalam mode Report-Only (Content-Security-Policy-Report-Only) untuk mendeteksi resource yang terblokir.",
            "Sesuaikan whitelist sumber berdasarkan resource yang dibutuhkan tema/plugin OJS yang dipakai.",
            "Setelah stabil, terapkan sebagai kebijakan enforced (bukan report-only) dan reload Nginx.",
        ],
        "references": [
            "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
            "https://cwe.mitre.org/data/definitions/693.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html",
            "https://owasp.org/www-project-secure-headers/",
        ],
    },
    "missing_hsts": {
        "remediation_steps": [
            "Pastikan situs sudah sepenuhnya berjalan di HTTPS sebelum mengaktifkan HSTS.",
            "Tambahkan header di blok server HTTPS Nginx: add_header Strict-Transport-Security \"max-age=31536000; includeSubDomains\" always;",
            "Mulai dengan max-age kecil (mis. 300 detik) untuk pengujian, lalu naikkan ke 31536000 (1 tahun) setelah yakin tidak ada masalah.",
            "Reload Nginx: sudo systemctl reload nginx",
            "Verifikasi dengan curl -I https://<domain> dan cek header Strict-Transport-Security muncul.",
        ],
        "references": [
            "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
            "https://cwe.mitre.org/data/definitions/319.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Strict_Transport_Security_Cheat_Sheet.html",
        ],
    },
    "missing_x_frame": {
        "remediation_steps": [
            "Tambahkan header di blok server Nginx: add_header X-Frame-Options \"SAMEORIGIN\" always;",
            "Atau gunakan directive frame-ancestors di Content-Security-Policy sebagai pengganti modern: frame-ancestors 'self';",
            "Reload Nginx: sudo systemctl reload nginx",
            "Verifikasi dengan curl -I https://<domain> dan cek header X-Frame-Options atau frame-ancestors muncul.",
        ],
        "references": [
            "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
            "https://cwe.mitre.org/data/definitions/1021.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Clickjacking_Defense_Cheat_Sheet.html",
        ],
    },
    "missing_referrer_policy": {
        "remediation_steps": [
            "Tambahkan header Referrer-Policy di konfigurasi Nginx server block.",
            "Gunakan nilai: add_header Referrer-Policy \"strict-origin-when-cross-origin\" always;",
            "Nilai strict-origin-when-cross-origin aman untuk mayoritas jurnal — hanya kirim origin (bukan full URL) saat cross-origin, dan tidak kirim apapun saat downgrade HTTPS→HTTP.",
            "Reload konfigurasi Nginx: sudo systemctl reload nginx",
            "Verifikasi dengan curl -I https://<domain> dan cek header Referrer-Policy muncul di respons.",
        ],
        "references": [
            "https://owasp.org/www-project-secure-headers/",
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Referrer-Policy",
            "https://cwe.mitre.org/data/definitions/200.html",
        ],
    },
    "missing_permissions_policy": {
        "remediation_steps": [
            "Tambahkan header Permissions-Policy di blok server {} konfigurasi Nginx.",
            "Contoh minimal untuk OJS: add_header Permissions-Policy \"geolocation=(), microphone=(), camera=(), payment=()\" always;",
            "Sesuaikan daftar fitur dengan kebutuhan jurnal (hapus fitur yang memang tidak dipakai).",
            "Reload konfigurasi Nginx: sudo systemctl reload nginx",
            "Verifikasi dengan curl -I https://<domain> dan cek header Permissions-Policy muncul.",
        ],
        "references": [
            "https://owasp.org/www-project-secure-headers/",
            "https://www.w3.org/TR/permissions-policy-1/",
        ],
    },
    "missing_x_content_type_options": {
        "remediation_steps": [
            "Tambahkan header di konfigurasi Nginx: add_header X-Content-Type-Options \"nosniff\" always;",
            "Kata kunci 'always' penting agar header muncul juga di halaman error (bukan hanya respons 200).",
            "Reload konfigurasi Nginx: sudo systemctl reload nginx",
            "Verifikasi di browser DevTools → Network tab → pilih request → Response Headers, cek X-Content-Type-Options: nosniff.",
        ],
        "references": [
            "https://owasp.org/www-project-secure-headers/",
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Content-Type-Options",
            "https://cwe.mitre.org/data/definitions/693.html",
        ],
    },
    "reflected_xss": {
        "remediation_steps": [
            "Identifikasi semua parameter input yang direfleksikan ke halaman tanpa encoding (prioritaskan parameter search/query).",
            "Terapkan output encoding pada setiap nilai yang dirender ke HTML — gunakan htmlspecialchars() dengan ENT_QUOTES di PHP.",
            "Implementasikan Content-Security-Policy (CSP) yang ketat untuk membatasi sumber script yang diizinkan.",
            "Validasi dan whitelist input di sisi server — tolak atau encode karakter '<', '>', '\"', \"'\", '/'.",
            "Pertimbangkan menggunakan library sanitasi seperti HTML Purifier untuk konten yang memang boleh mengandung HTML.",
            "Jalankan ulang scan setelah perbaikan untuk konfirmasi XSS sudah tidak terdeteksi.",
        ],
        "references": [
            "https://owasp.org/Top10/A03_2021-Injection/",
            "https://cwe.mitre.org/data/definitions/79.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html",
            "https://portswigger.net/web-security/cross-site-scripting/reflected",
        ],
    },
    "sql_error_exposed": {
        "remediation_steps": [
            "Nonaktifkan display_errors di PHP production: edit php.ini, set display_errors = Off, log_errors = On.",
            "Di config.inc.php OJS, pastikan show_errors = Off dan show_stacktrace = Off.",
            "Konfigurasi halaman error generik di Nginx agar tidak menampilkan detail backend: error_page 500 502 503 504 /50x.html;",
            "Audit query yang menghasilkan error tersebut dan pastikan menggunakan parameterized query/prepared statement.",
            "Reload PHP-FPM dan Nginx: sudo systemctl restart php8.1-fpm nginx",
            "Jalankan ulang scan untuk memastikan pesan error SQL tidak lagi terekspos ke pengguna.",
        ],
        "references": [
            "https://owasp.org/Top10/A03_2021-Injection/",
            "https://cwe.mitre.org/data/definitions/209.html",
            "https://cwe.mitre.org/data/definitions/89.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html",
        ],
    },
    "path_traversal": {
        "remediation_steps": [
            "Identifikasi endpoint yang rentan dari 'affected_path' pada temuan.",
            "Pastikan OJS dan seluruh plugin/dependency dalam keadaan versi terbaru — kerentanan path traversal sering sudah dipatch di rilis terbaru.",
            "Tambahkan aturan Nginx untuk memblokir pola traversal pada URL: location ~ \\.\\./ { deny all; }",
            "Validasi dan normalisasi seluruh input path di sisi aplikasi — tolak karakter '../' dan path absolut.",
            "Batasi permission filesystem agar proses web server tidak dapat membaca file di luar webroot (open_basedir di php.ini).",
            "Jalankan ulang scan vulnerability prober setelah perbaikan untuk konfirmasi.",
        ],
        "references": [
            "https://owasp.org/Top10/A01_2021-Broken_Access_Control/",
            "https://cwe.mitre.org/data/definitions/22.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html",
        ],
    },
    "exposed_git": {
        "remediation_steps": [
            "SEGERA: Asumsikan seluruh riwayat kode dan kemungkinan kredensial di repository sudah bocor.",
            "Hapus direktori .git dari direktori produksi: rm -rf /path/to/ojs/.git (deploy tanpa menyertakan .git ke webroot).",
            "Blokir akses di Nginx sebagai mitigasi cepat: location ~ /\\.git { deny all; return 404; }",
            "Audit riwayat commit untuk kredensial/secret yang mungkin pernah ter-commit, dan rotasi semua yang ditemukan.",
            "Terapkan proses deployment yang memisahkan source control dari direktori webroot (CI/CD yang hanya menyalin artefak build).",
            "Verifikasi: akses https://<domain>/.git/config — harus mendapat HTTP 403 atau 404.",
        ],
        "references": [
            "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
            "https://cwe.mitre.org/data/definitions/538.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Infrastructure_as_Code_Security_Cheat_Sheet.html",
        ],
    },
    "exposed_env_file": {
        "remediation_steps": [
            "SEGERA: Asumsikan semua kredensial di .env sudah bocor — mulai rotasi semua password dan API key yang tersimpan di file tersebut.",
            "Periksa log akses web server (access.log) untuk mengetahui apakah .env sudah pernah diunduh oleh pihak lain.",
            "Pindahkan file .env ke direktori di luar webroot (satu level di atas direktori public/webroot OJS).",
            "Jika tidak bisa dipindahkan, blokir akses di Nginx: location ~ /\\.env { deny all; return 404; }",
            "Untuk Apache: tambahkan di .htaccess: <Files \".env\"> Order allow,deny Deny from all </Files>",
            "Update semua service yang menggunakan kredensial yang berpotensi terekspos (database, SMTP, API key pihak ketiga).",
            "Verifikasi perbaikan: akses https://<domain>/.env — harus mendapat HTTP 403 atau 404.",
        ],
        "references": [
            "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
            "https://cwe.mitre.org/data/definitions/538.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Infrastructure_as_Code_Security_Cheat_Sheet.html",
            "https://www.acunetix.com/vulnerabilities/web/env-file-publicly-accessible/",
        ],
    },
    "phpinfo_exposed": {
        "remediation_steps": [
            "Identifikasi lokasi file phpinfo() dari 'affected_path' pada temuan (mis. info.php, test.php, phpinfo.php).",
            "Hapus file tersebut dari server: rm /path/to/ojs/<file>.php",
            "Audit direktori webroot untuk file uji/debug serupa yang mungkin tertinggal dari proses development.",
            "Tambahkan aturan deployment yang mencegah file uji ikut ter-deploy ke production (.gitignore, build exclude list).",
            "Verifikasi: akses https://<domain>/<file>.php — harus mendapat HTTP 404.",
        ],
        "references": [
            "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
            "https://cwe.mitre.org/data/definitions/200.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html",
        ],
    },
    "open_directory": {
        "remediation_steps": [
            "Identifikasi direktori yang directory listing-nya aktif dari 'affected_path' pada temuan.",
            "Nonaktifkan directory listing di Nginx: pastikan tidak ada directive autoindex on; pada blok location terkait.",
            "Tambahkan index.html/index.php kosong di direktori yang tidak boleh menampilkan listing sebagai lapisan pertahanan tambahan.",
            "Batasi akses langsung ke direktori upload/cache: location /files/ { internal; } atau gunakan signed URL.",
            "Reload Nginx: sudo systemctl reload nginx",
            "Verifikasi: akses https://<domain>/<direktori>/ — harus mendapat HTTP 403 atau 404, bukan daftar file.",
        ],
        "references": [
            "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
            "https://cwe.mitre.org/data/definitions/548.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Securing_Cardholder_Data_Cheat_Sheet.html",
        ],
    },
    "ojs_admin_endpoint_exposed": {
        "remediation_steps": [
            "Pastikan halaman login admin (mis. /index.php/index/login) menggunakan HTTPS dan dilindungi rate limiting.",
            "Tambahkan rate limiting di Nginx: limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m; lalu terapkan di location terkait.",
            "Aktifkan CAPTCHA pada form login jika tersedia (plugin reCAPTCHA OJS).",
            "Pertimbangkan membatasi akses endpoint admin hanya dari IP tertentu (VPN/whitelist) menggunakan allow/deny di Nginx.",
            "Pastikan seluruh akun admin menggunakan password kuat dan, jika tersedia, aktifkan two-factor authentication.",
        ],
        "references": [
            "https://owasp.org/Top10/A07_2021-Identification_and_Authentication_Failures/",
            "https://cwe.mitre.org/data/definitions/307.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html",
        ],
    },
    "ojs_oai_accessible": {
        "remediation_steps": [
            "Endpoint OAI-PMH (/oai) bersifat publik by design untuk interoperabilitas metadata jurnal — temuan ini bersifat informatif, bukan kerentanan kritis.",
            "Tinjau apakah eksposur metadata via OAI-PMH sesuai kebijakan jurnal (beberapa jurnal sengaja mengaktifkan untuk indexing Google Scholar/DOAJ).",
            "Jika ingin membatasi, konfigurasi akses OAI di Settings → Distribution → Indexing pada panel admin OJS.",
            "Jika perlu dibatasi di level jaringan, tambahkan whitelist IP untuk harvester tepercaya di Nginx.",
        ],
        "references": [
            "https://docs.pkp.sfu.ca/admin-guide/en/distribution",
            "https://www.openarchives.org/pmh/",
        ],
    },
    "cookie_missing_secure_flag": {
        "remediation_steps": [
            "Set session.cookie_secure = 1 di konfigurasi PHP (php.ini atau .htaccess), agar cookie hanya dikirim melalui HTTPS.",
            "Untuk Apache .htaccess: php_value session.cookie_secure 1",
            "Untuk Nginx dengan PHP-FPM: fastcgi_param PHP_VALUE \"session.cookie_secure=1\"; di blok location ~ \\.php$",
            "Pastikan situs sepenuhnya berjalan di HTTPS sebelum mengaktifkan flag ini agar sesi tidak rusak.",
            "Verifikasi di browser DevTools → Application → Cookies → kolom Secure harus tercentang.",
        ],
        "references": [
            "https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html",
            "https://cwe.mitre.org/data/definitions/614.html",
            "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
        ],
    },
    "cookie_missing_httponly_flag": {
        "remediation_steps": [
            "Set session.cookie_httponly = 1 di konfigurasi PHP (php.ini atau per-directory .htaccess).",
            "Untuk Apache .htaccess: tambahkan php_value session.cookie_httponly 1",
            "Untuk Nginx dengan PHP-FPM: tambahkan fastcgi_param PHP_VALUE \"session.cookie_httponly=1\"; di blok location ~ \\.php$",
            "Verifikasi di browser DevTools → Application → Cookies → pastikan kolom HttpOnly tercentang untuk cookie OJS.",
        ],
        "references": [
            "https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html",
            "https://cwe.mitre.org/data/definitions/1004.html",
            "https://datatracker.ietf.org/doc/html/rfc6265#section-5.2.6",
        ],
    },
    "cookie_missing_samesite": {
        "remediation_steps": [
            "Set session.cookie_samesite = Strict di konfigurasi PHP jika jurnal tidak memerlukan cross-site navigation.",
            "Atau gunakan Lax jika jurnal menggunakan fitur deep-link dari situs eksternal (lebih umum dan aman untuk sebagian besar OJS).",
            "Untuk Apache .htaccess: php_value session.cookie_samesite \"Lax\"",
            "Untuk PHP 7.3+: dapat juga diset via ini_set('session.cookie_samesite', 'Lax'); di awal sesi.",
            "Verifikasi di DevTools → Application → Cookies → kolom SameSite harus menampilkan 'Strict' atau 'Lax'.",
        ],
        "references": [
            "https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html",
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Set-Cookie/SameSite",
            "https://cwe.mitre.org/data/definitions/352.html",
        ],
    },
    "cve_ojs": {
        "remediation_steps": [
            "Baca advisory keamanan resmi untuk CVE terkait di https://nvd.nist.gov/vuln/detail/ (lihat field cve_id pada temuan).",
            "Identifikasi versi OJS yang sudah memperbaiki kerentanan ini dari advisory PKP.",
            "Backup database dan semua file OJS sebelum upgrade: pg_dump ojsdb > backup.sql && tar -czf ojs-backup.tar.gz /path/to/ojs",
            "Download versi OJS terbaru dari https://pkp.sfu.ca/ojs/ojs_download/",
            "Ikuti panduan upgrade resmi PKP: https://docs.pkp.sfu.ca/dev/upgrade-guide/",
            "Setelah upgrade, jalankan php tools/upgrade.php upgrade dari direktori OJS.",
            "Verifikasi fungsionalitas jurnal setelah upgrade, lalu jalankan ulang scan untuk konfirmasi CVE sudah resolved.",
        ],
        "references": [
            "https://nvd.nist.gov/vuln/detail/",
            "https://pkp.sfu.ca/category/news/announcements/releases/",
            "https://forum.pkp.sfu.ca/c/questions-and-answers/security/",
            "https://docs.pkp.sfu.ca/dev/upgrade-guide/",
        ],
    },
}
```

**Catatan penting tentang `cve_ojs`:** entry di atas adalah fallback statis. Karena setiap temuan CVE punya `cve_id` berbeda, `cve_matcher.py` HARUS tetap meng-override `references` secara eksplisit per panggilan dengan URL NVD spesifik (`f"https://nvd.nist.gov/vuln/detail/{cve_id}"`) — lihat Task 7 Step 3. Lookup `ENRICHMENT_DATA["cve_ojs"]` hanya dipakai sebagai fallback `remediation_steps` (yang generik dan valid untuk semua CVE).

- [ ] **Step 2: Verifikasi sintaks penuh file `enrichment.py`**

Run: `cd OJSDEF-BackEnd; python -c "import ast; ast.parse(open('app/scanners/enrichment.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Verifikasi jumlah entry = 42 (17 internal + 25 external)**

Run: `cd OJSDEF-BackEnd; python -c "import ast; tree = ast.parse(open('app/scanners/enrichment.py').read()); d = [n for n in ast.walk(tree) if isinstance(n, ast.Dict) and len(n.keys) > 30][0]; print(len(d.keys))"`
Expected: `42`

- [ ] **Step 4: Commit**

```bash
git add OJSDEF-BackEnd/app/scanners/enrichment.py
git commit -m "feat: add centralized ENRICHMENT_DATA for all 42 finding types"
```

---

## Task 5: Modifikasi `make_finding()` — Auto-Lookup Enrichment

**Files:**
- Modify: `OJSDEF-BackEnd/app/scanners/models.py`

- [ ] **Step 1: Tambah import dan field baru ke `FindingResult`**

Tambahkan di bagian import paling atas file (setelah import `dataclass`):

```python
from dataclasses import dataclass, field
from app.scanners.enrichment import ENRICHMENT_DATA
```

Tambahkan dua field baru ke akhir dataclass `FindingResult` (setelah `owasp_category: str | None = None`):

```python
    references: list[str] = field(default_factory=list)
    remediation_steps: list[str] = field(default_factory=list)
```

- [ ] **Step 2: Tambah 5 entry CVSS baru ke dict `CVSS_SCORES`**

Sisipkan baris berikut ke dalam dict `CVSS_SCORES` (5 finding type baru dari spec section 3.2 dan 3.3):

```python
    "missing_referrer_policy": 3.1,
    "missing_permissions_policy": 3.1,
    "missing_x_content_type_options": 4.3,
    "cookie_missing_httponly_flag": 4.3,
    "cookie_missing_samesite": 4.3,
```

- [ ] **Step 3: Modifikasi `make_finding()` agar auto-lookup ke `ENRICHMENT_DATA`**

Ganti seluruh isi fungsi `make_finding()` dengan:

```python
def make_finding(finding_type: str, **kwargs) -> FindingResult:
    score = CVSS_SCORES.get(finding_type, 5.0)
    enrichment = ENRICHMENT_DATA.get(finding_type, {})
    kwargs.setdefault("references", list(enrichment.get("references", [])))
    kwargs.setdefault("remediation_steps", list(enrichment.get("remediation_steps", [])))
    return FindingResult(
        finding_type=finding_type,
        cvss_score=score,
        severity=severity_from_score(score),
        **kwargs,
    )
```

`kwargs.setdefault` memastikan caller yang secara eksplisit memberi `references`/`remediation_steps` (mis. `cve_matcher.py` untuk URL NVD dinamis) tidak akan ditimpa oleh data statis — sesuai catatan di Task 4.

- [ ] **Step 4: Verifikasi sintaks dan import**

Run: `cd OJSDEF-BackEnd; python -c "import ast; ast.parse(open('app/scanners/models.py').read()); print('OK')"`
Expected: `OK`

Run (cek tidak ada circular import — `enrichment.py` tidak mengimpor `models.py`):
`cd OJSDEF-BackEnd; python -c "import ast; tree = ast.parse(open('app/scanners/enrichment.py').read()); imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]; assert 'app.scanners.models' not in imports; print('no circular import')"`
Expected: `no circular import`

- [ ] **Step 5: Commit**

```bash
git add OJSDEF-BackEnd/app/scanners/models.py
git commit -m "feat: auto-enrich findings via ENRICHMENT_DATA lookup in make_finding()"
```

---

## Task 6: `header_checker.py` — Tambah 3 Header Baru

**Files:**
- Modify: `OJSDEF-BackEnd/app/scanners/external/header_checker.py` (61 baris saat ini)

Current `REQUIRED` adalah `dict[str, tuple[str, str, str, str]]` = `(finding_type, title, remediation, owasp_category)`, dengan `description` digenerate generik inline di loop. Spec section 3.2 minta description kustom per-header baru — maka tuple diperluas jadi 5 elemen dengan `description` eksplisit (description untuk 3 header lama tetap memakai pola generik agar tidak mengubah perilaku existing).

- [ ] **Step 1: Ganti seluruh isi file dengan versi berikut**

```python
import httpx
from app.scanners.models import FindingResult, make_finding

# Each entry: header_name -> (finding_type, title, description, remediation, owasp_category)
# description=None berarti pakai pola generik (header lama, perilaku tidak berubah)
REQUIRED: dict[str, tuple[str, str, str | None, str, str]] = {
    "Content-Security-Policy": (
        "missing_csp",
        "CSP (Content-Security-Policy) Tidak Ditemukan",
        None,
        "Tambahkan header Content-Security-Policy untuk mencegah serangan XSS dan injeksi konten.",
        "A03:2021-Injection",
    ),
    "Strict-Transport-Security": (
        "missing_hsts",
        "HSTS (Strict-Transport-Security) Tidak Ditemukan",
        None,
        (
            "Tambahkan header: Strict-Transport-Security: max-age=31536000; includeSubDomains "
            "untuk memaksa koneksi HTTPS."
        ),
        "A05:2021",
    ),
    "X-Frame-Options": (
        "missing_x_frame",
        "X-Frame-Options Tidak Ditemukan",
        None,
        "Tambahkan header X-Frame-Options: DENY untuk mencegah serangan clickjacking.",
        "A05:2021",
    ),
    "Referrer-Policy": (
        "missing_referrer_policy",
        "Referrer-Policy Tidak Dikonfigurasi",
        (
            "Header Referrer-Policy tidak ditemukan. Tanpa header ini, browser mengirim URL "
            "penuh (termasuk query string) ke situs eksternal sebagai Referer, berpotensi "
            "membocorkan informasi sesi atau parameter sensitif kepada pihak ketiga."
        ),
        "Tambahkan header Referrer-Policy: strict-origin-when-cross-origin di konfigurasi Nginx.",
        "A05:2021",
    ),
    "Permissions-Policy": (
        "missing_permissions_policy",
        "Permissions-Policy Tidak Dikonfigurasi",
        (
            "Header Permissions-Policy (pengganti Feature-Policy) tidak ditemukan. Header ini "
            "mengontrol akses browser ke fitur sensitif seperti kamera, mikrofon, geolokasi, "
            "dan payment API. Tanpa header ini, iframe pihak ketiga dapat mengakses fitur-fitur "
            "tersebut tanpa pembatasan."
        ),
        "Tambahkan header Permissions-Policy: geolocation=(), microphone=(), camera=(), payment=() di konfigurasi Nginx.",
        "A05:2021",
    ),
    "X-Content-Type-Options": (
        "missing_x_content_type_options",
        "X-Content-Type-Options Tidak Ditemukan",
        (
            "Header X-Content-Type-Options tidak ditemukan. Tanpa header ini, browser lama "
            "dapat melakukan MIME type sniffing — mengeksekusi file sebagai JavaScript meski "
            "Content-Type berbeda. Ini berpotensi dieksploitasi melalui file upload di jurnal "
            "jika ada konten berbahaya."
        ),
        "Tambahkan header X-Content-Type-Options: nosniff (dengan flag always) di konfigurasi Nginx.",
        "A05:2021",
    ),
}


async def scan_headers(url: str) -> list[FindingResult]:
    """
    Check for missing security HTTP headers.
    Never raises — returns empty list on network failure.
    """
    findings = []

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            resp = await c.head(url)
            present = {k.lower() for k in resp.headers}

            for header, (ftype, title, custom_desc, remediation, owasp) in REQUIRED.items():
                if header.lower() not in present:
                    description = custom_desc or (
                        f"Header keamanan {header} tidak ditemukan pada respons dari {url}. "
                        "Absennya header ini meningkatkan risiko serangan web."
                    )
                    findings.append(make_finding(
                        ftype,
                        category="external",
                        title=title,
                        description=description,
                        affected_path=url,
                        evidence=f"Header {header} tidak ada dalam respons HTTP",
                        remediation=remediation,
                        owasp_category=owasp,
                    ))
    except Exception:
        pass

    return findings
```

- [ ] **Step 2: Verifikasi sintaks**

Run: `cd OJSDEF-BackEnd; python -c "import ast; ast.parse(open('app/scanners/external/header_checker.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Verifikasi `REQUIRED` punya 6 entries (3 lama + 3 baru)**

Run: `cd OJSDEF-BackEnd; python -c "from app.scanners.external.header_checker import REQUIRED; assert len(REQUIRED) == 6; print('OK', list(REQUIRED.keys()))"`
Expected: `OK ['Content-Security-Policy', 'Strict-Transport-Security', 'X-Frame-Options', 'Referrer-Policy', 'Permissions-Policy', 'X-Content-Type-Options']`

- [ ] **Step 4: Commit**

```bash
git add OJSDEF-BackEnd/app/scanners/external/header_checker.py
git commit -m "feat: detect Referrer-Policy, Permissions-Policy, X-Content-Type-Options headers"
```

---

## Task 7: `cookie_analyzer.py` — Tambah Cek HttpOnly & SameSite

**Files:**
- Modify: `OJSDEF-BackEnd/app/scanners/external/cookie_analyzer.py` (46 baris saat ini — hanya cek `Secure`)

- [ ] **Step 1: Ganti seluruh isi file dengan versi berikut (menambahkan cek HttpOnly + SameSite per cookie, di dalam loop `for raw in set_cookies` yang sama)**

```python
import httpx
from app.scanners.models import FindingResult, make_finding


async def scan_cookies(url: str) -> list[FindingResult]:
    """
    Fetch halaman login OJS dan cek Set-Cookie headers untuk flag Secure, HttpOnly, SameSite.
    Tidak memerlukan login — cookies dikirim di response halaman login itu sendiri.
    Never raises — return [] on any error.
    """
    findings = []
    base = url.rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            resp = await c.get(f"{base}/index/login")

        set_cookies = [v for k, v in resp.headers.multi_items()
                       if k.lower() == "set-cookie"]

        for raw in set_cookies:
            parts_lower = raw.lower()
            name        = raw.split("=")[0].strip()
            login_path  = f"{base}/index/login"

            if "secure" not in parts_lower:
                findings.append(make_finding(
                    "cookie_missing_secure_flag",
                    category="external",
                    title=f"Cookie '{name}' Tidak Memiliki Flag Secure",
                    description=(
                        f"Cookie sesi '{name}' dikirim tanpa atribut Secure. "
                        "Cookie dapat terkirim lewat HTTP plaintext jika pengguna mengakses "
                        "sebelum redirect HTTPS aktif, memungkinkan session hijacking."
                    ),
                    affected_path=login_path,
                    evidence=f"Set-Cookie: {raw[:120]}",
                    remediation=(
                        "Aktifkan `force_ssl = On` di config.inc.php OJS, "
                        "atau set `session.cookie_secure = 1` di konfigurasi PHP."
                    ),
                ))

            if "httponly" not in parts_lower:
                findings.append(make_finding(
                    "cookie_missing_httponly_flag",
                    category="external",
                    title=f"Cookie '{name}' Tidak Memiliki Flag HttpOnly",
                    description=(
                        f"Cookie sesi '{name}' tidak memiliki atribut HttpOnly. Cookie tanpa "
                        "HttpOnly dapat diakses oleh JavaScript melalui document.cookie, "
                        "sehingga jika terjadi serangan XSS, penyerang dapat mencuri token "
                        "sesi pengguna dan mengambil alih akun."
                    ),
                    affected_path=login_path,
                    evidence=f"Set-Cookie: {raw[:120]}",
                    remediation=(
                        "Set `session.cookie_httponly = 1` di konfigurasi PHP "
                        "(php.ini atau .htaccess: `php_value session.cookie_httponly 1`)."
                    ),
                ))

            if "samesite" not in parts_lower:
                findings.append(make_finding(
                    "cookie_missing_samesite",
                    category="external",
                    title=f"Cookie '{name}' Tidak Memiliki Atribut SameSite",
                    description=(
                        f"Cookie '{name}' tidak memiliki atribut SameSite. Tanpa SameSite, "
                        "cookie dikirim pada setiap cross-site request, meningkatkan risiko "
                        "serangan CSRF (Cross-Site Request Forgery). Penyerang dapat memicu "
                        "aksi atas nama pengguna yang sedang login (submit form, upload file, "
                        "perubahan konfigurasi jurnal) dari situs lain."
                    ),
                    affected_path=login_path,
                    evidence=f"Set-Cookie: {raw[:120]}",
                    remediation=(
                        "Set `session.cookie_samesite = Lax` (atau `Strict`) di konfigurasi PHP "
                        "(.htaccess: `php_value session.cookie_samesite \"Lax\"`)."
                    ),
                ))
    except Exception:
        pass

    return findings
```

- [ ] **Step 2: Verifikasi sintaks**

Run: `cd OJSDEF-BackEnd; python -c "import ast; ast.parse(open('app/scanners/external/cookie_analyzer.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add OJSDEF-BackEnd/app/scanners/external/cookie_analyzer.py
git commit -m "feat: detect missing HttpOnly and SameSite cookie attributes"
```

---

## Task 8: `cve_matcher.py` — Override `references` Dinamis per CVE

**Files:**
- Modify: `OJSDEF-BackEnd/app/scanners/external/cve_matcher.py`

- [ ] **Step 1: Baca file untuk menemukan baris `make_finding("cve_ojs", ...)`**

Run: `Select-String -Path "OJSDEF-BackEnd\app\scanners\external\cve_matcher.py" -Pattern 'make_finding\("cve_ojs"' -Context 0,15`

- [ ] **Step 2: Tambahkan parameter `references=` eksplisit ke panggilan `make_finding("cve_ojs", ...)` yang ditemukan**

Sisipkan baris berikut di dalam argumen pemanggilan (sebelum tanda kurung penutup `)`), menggunakan variabel `cve_id` yang sudah tersedia di scope tersebut (cek nama variabel persis dari hasil Step 1 — biasanya `cve_id` atau `cve.get("id")`):

```python
                        references=[
                            f"https://nvd.nist.gov/vuln/detail/{cve_id}",
                            "https://pkp.sfu.ca/category/news/announcements/releases/",
                            "https://forum.pkp.sfu.ca/c/questions-and-answers/security/",
                            "https://docs.pkp.sfu.ca/dev/upgrade-guide/",
                        ],
```

Karena `make_finding()` memakai `kwargs.setdefault(...)` (Task 5 Step 3), memberikan `references` eksplisit di sini akan mengoverride fallback statis dari `ENRICHMENT_DATA["cve_ojs"]` — sehingga setiap finding CVE punya link NVD yang tepat ke CVE ID-nya masing-masing. `remediation_steps` TIDAK perlu di-override — fallback generik dari `ENRICHMENT_DATA` (Task 4) sudah valid untuk semua CVE.

- [ ] **Step 3: Verifikasi sintaks**

Run: `cd OJSDEF-BackEnd; python -c "import ast; ast.parse(open('app/scanners/external/cve_matcher.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add OJSDEF-BackEnd/app/scanners/external/cve_matcher.py
git commit -m "feat: link cve_ojs findings to per-CVE NVD advisory URL"
```

---

## Task 9: Pydantic Schemas — `FindingResponse` & `ScanResponse`

**Files:**
- Modify: `OJSDEF-BackEnd/app/schemas/scans.py`

Catatan: nama class aktual adalah `FindingResponse` dan `ScanResponse` (BUKAN `ScanFindingOut`/`ScanJobOut` seperti diasumsikan di spec section 2.4 — gunakan nama yang benar ini).

- [ ] **Step 1: Tambah field `module_errors` ke `ScanResponse` — sisipkan setelah baris `diagnostic_detail: str | None = None`**

```python
    module_errors: dict[str, str] = {}
```

- [ ] **Step 2: Tambah field `references` dan `remediation_steps` ke `FindingResponse` — sisipkan setelah baris `remediation: str`**

```python
    references: list[str] = []
    remediation_steps: list[str] = []
```

- [ ] **Step 3: Verifikasi sintaks dan import schema**

Run: `cd OJSDEF-BackEnd; python -c "from app.schemas.scans import ScanResponse, FindingResponse; print('module_errors' in ScanResponse.model_fields, 'references' in FindingResponse.model_fields, 'remediation_steps' in FindingResponse.model_fields)"`
Expected: `True True True`

- [ ] **Step 4: Commit**

```bash
git add OJSDEF-BackEnd/app/schemas/scans.py
git commit -m "feat: add references, remediation_steps, module_errors fields to scan schemas"
```

---

## Task 10: `routers/scans.py` — Update 3 Lokasi Konstruksi Response

**Files:**
- Modify: `OJSDEF-BackEnd/app/routers/scans.py`

File ini sudah meng-import `json` di bagian atas (terverifikasi sebelumnya). Tambahkan helper kecil untuk parse kolom JSON-as-Text yang nullable, lalu gunakan di 3 lokasi: `_to_response()` (baris ~35-52), dan dua konstruksi `FindingResponse(...)` di `get_findings` (baris ~181-187) dan `mark_false_positive` (baris ~224-230).

- [ ] **Step 1: Tambah helper `_parse_json_list` dan `_parse_json_dict` tepat sebelum fungsi `_to_response`**

```python
def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _parse_json_dict(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}
```

- [ ] **Step 2: Update `_to_response()` — tambahkan `module_errors=_parse_json_dict(job.module_errors)` ke konstruktor `ScanResponse`**

Ganti blok `return ScanResponse(...)` menjadi:

```python
    return ScanResponse(
        id=str(job.id), target_id=str(job.target_id),
        scan_type=job.scan_type, status=job.status,
        overall_score=job.overall_score, risk_level=job.risk_level,
        critical_count=job.critical_count, high_count=job.high_count,
        medium_count=job.medium_count, low_count=job.low_count,
        diagnostic_code=job.diagnostic_code,
        diagnostic_detail=job.diagnostic_detail,
        module_errors=_parse_json_dict(job.module_errors),
        progress=parsed_progress, created_at=job.created_at,
    )
```

- [ ] **Step 3: Update konstruksi `FindingResponse` di `get_findings` (sekitar baris 181-187)**

Ganti blok `return [FindingResponse(...) for f in findings]` menjadi:

```python
    return [
        FindingResponse(
            id=str(f.id), finding_type=f.finding_type, category=f.category,
            title=f.title, description=f.description, affected_path=f.affected_path,
            evidence=f.evidence, remediation=f.remediation, severity=f.severity,
            cvss_score=f.cvss_score, cve_id=f.cve_id, owasp_category=f.owasp_category,
            is_false_positive=f.is_false_positive,
            references=_parse_json_list(f.references),
            remediation_steps=_parse_json_list(f.remediation_steps),
        )
        for f in findings
    ]
```

- [ ] **Step 4: Update konstruksi `FindingResponse` di `mark_false_positive` (sekitar baris 224-230)**

Ganti blok `return FindingResponse(...)` menjadi:

```python
    return FindingResponse(
        id=str(f.id), finding_type=f.finding_type, category=f.category,
        title=f.title, description=f.description, affected_path=f.affected_path,
        evidence=f.evidence, remediation=f.remediation, severity=f.severity,
        cvss_score=f.cvss_score, cve_id=f.cve_id, owasp_category=f.owasp_category,
        is_false_positive=f.is_false_positive,
        references=_parse_json_list(f.references),
        remediation_steps=_parse_json_list(f.remediation_steps),
    )
```

- [ ] **Step 5: Verifikasi sintaks**

Run: `cd OJSDEF-BackEnd; python -c "import ast; ast.parse(open('app/routers/scans.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add OJSDEF-BackEnd/app/routers/scans.py
git commit -m "feat: serialize references, remediation_steps, module_errors in scan responses"
```

---

### Task 11: `app/workers/internal_bot.py` — module_errors + propagasi ojs_version

**Tujuan:** Bungkus tiap pemanggilan scanner module dalam try/except agar modul yang gagal tercatat di `job.module_errors` (bukan membuat seluruh scan gagal), tangani kasus `file_integrity` berstatus `"skipped"` (checksums tidak tersedia), simpan `references`/`remediation_steps` (list) sebagai JSON ke kolom `ScanFinding`, dan perbarui `ojs_targets.ojs_version` dari data fingerprint plugin.

**Files:**
- Modify: `OJSDEF-BackEnd/app/workers/internal_bot.py:196-253` (fungsi `_run_internal_scan`)

**Konteks penting (hasil pembacaan file saat ini):**
- `results = data.get("results", {})` — payload plugin per modul ada di `results["fingerprint"]`, `results["config"]`, dst. (lihat `DEFAULT_MODULES` baris 28: `["fingerprint", "config", "plugins", "rbac", "file_integrity", "content"]`)
- `FingerprintScanner` plugin mengembalikan dict dengan key `ojs_version` (lihat `OJSDEF-Plugin/ojsdef/classes/scanners/FingerprintScanner.php:26`) — sehingga path yang benar adalah `results.get("fingerprint", {}).get("ojs_version")`, BUKAN `data.get("fingerprint", {})` seperti contoh ringkas di spec (spec menulis `plugin_audit_data` secara longgar; struktur aktual menempatkannya di dalam `results`)
- `ScanFinding` ORM (setelah Task 2) punya kolom `references: Text | None` dan `remediation_steps: Text | None` — keduanya menyimpan **JSON-encoded list of strings**, bukan list Python langsung
- `FindingResult` dataclass (setelah Task 5) punya field `references: list[str]` dan `remediation_steps: list[str]` (default `[]` via `field(default_factory=list)`)
- Import `OJSTarget` SUDAH ADA di baris 14 (`from app.models import OJSTarget, ScanJob, ScanFinding`) — tidak perlu menambah import baru untuk model

- [ ] **Step 1: Ganti seluruh isi fungsi `_run_internal_scan` (baris 196-253)**

Ganti dari `async def _run_internal_scan(job_id: str, data: dict) -> None:` sampai akhir fungsi (baris `await _try_trigger_scoring(job_id)`) dengan kode berikut:

```python
async def _run_internal_scan(job_id: str, data: dict) -> None:
    """Process plugin-provided scan data and persist findings."""
    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 1, 7, "Plugin callback diterima, memproses data audit...", "INFO")

    results = data.get("results", {})
    module_errors: dict[str, str] = {}
    all_findings: list = []

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 2, 7, "Menganalisis konfigurasi OJS...", "TASK")
    try:
        all_findings += scan_config(results.get("config", {}))
    except Exception as e:
        module_errors["config"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 3, 7, "Memeriksa plugin yang terpasang...", "TASK")
    try:
        all_findings += scan_plugins(results.get("plugins", {}))
    except Exception as e:
        module_errors["plugins"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 4, 7, "Mengaudit RBAC dan pengguna...", "TASK")
    try:
        all_findings += scan_rbac(results.get("rbac", {}))
    except Exception as e:
        module_errors["rbac"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 5, 7, "Memeriksa integritas file...", "TASK")
    try:
        fi_data = results.get("file_integrity", {})
        if fi_data.get("status") == "skipped":
            module_errors["file_integrity"] = fi_data.get("reason", "checksums_unavailable")
        else:
            all_findings += scan_file_integrity(fi_data)
    except Exception as e:
        module_errors["file_integrity"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 6, 7, "Mendeteksi konten mencurigakan...", "TASK")
    try:
        all_findings += scan_content(results.get("content", {}))
    except Exception as e:
        module_errors["content"] = str(e)[:100]

    ojs_version = results.get("fingerprint", {}).get("ojs_version")

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
                references=json.dumps(f.references) if f.references else None,
                remediation_steps=json.dumps(f.remediation_steps) if f.remediation_steps else None,
            ))
        job.module_errors = json.dumps(module_errors) if module_errors else None

        if ojs_version and isinstance(ojs_version, str):
            target = await session.get(OJSTarget, job.target_id)
            if target and target.ojs_version != ojs_version:
                target.ojs_version = ojs_version

        await session.commit()

    if await _check_cancelled(job_id): return
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
```

**Catatan desain:**
- `module_errors["fingerprint"]` sengaja TIDAK pernah diisi di sini — modul fingerprint internal hanya menyumbang data (tidak ada findings, tidak bisa "gagal" secara terpisah dari keseluruhan callback). Frontend `getModuleStatus()` (Task 14) menampilkan modul `fingerprint`/`fingerprint_ext` selalu sebagai status `info`.
- Kasus `file_integrity` berstatus `"skipped"` BUKAN error sungguhan — itu kondisi normal saat checksums belum tersedia untuk versi OJS tersebut. Tetap dicatat ke `module_errors["file_integrity"]` (sesuai keputusan brainstorming "opsi C": status ditampilkan sebagai "Tidak Ditemukan/Tidak Tersedia", bukan "Gagal" — lihat catatan styling di Task 15) namun secara struktur data tetap masuk dict yang sama; frontend yang membedakan tampilan berdasarkan isi pesan.
- `job.target_id` SUDAH tersedia di objek `job` (kolom FK `ScanJob.target_id`) — tidak perlu query terpisah untuk mendapatkan target id.

- [ ] **Step 2: Verifikasi sintaks**

Run: `cd OJSDEF-BackEnd; python -c "import ast; ast.parse(open('app/workers/internal_bot.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add OJSDEF-BackEnd/app/workers/internal_bot.py
git commit -m "feat: catat module_errors dan propagasi ojs_version di internal scan worker"
```

---

### Task 12: `app/workers/external_bot.py` — module_errors + propagasi ojs_version

**Tujuan:** Sama seperti Task 11 tapi untuk worker eksternal — bungkus 8 pemanggilan scanner dalam try/except dengan key modul yang sesuai tabel mapping spec (`fingerprint_ext`, `ssl`, `headers`, `vulnerabilities`, `open_dirs`, `cve`, `cookies`, `endpoints`), simpan `references`/`remediation_steps` sebagai JSON, dan simpan `ojs_version` (sudah dikembalikan langsung oleh `scan_fingerprint()`) ke `ojs_targets.ojs_version`.

**Files:**
- Modify: `OJSDEF-BackEnd/app/workers/external_bot.py` (seluruh fungsi `_run_external_scan`, baris 24-90)

**Konteks penting (hasil pembacaan file saat ini):**
- `scan_fingerprint(target_url)` SUDAH mengembalikan tuple `(ojs_version, findings)` — baris 29: `ojs_version, fp = await scan_fingerprint(target_url)`. Tidak perlu parsing tambahan, tinggal simpan `ojs_version` ke target.
- `from app.models import ScanJob, ScanFinding` di baris 8 — perlu ditambah `OJSTarget` menjadi `from app.models import OJSTarget, ScanJob, ScanFinding`
- `ScanJob.target_id` adalah kolom FK (`Mapped[uuid.UUID]`, lihat `app/models/scan_job.py:14`) — gunakan `job.target_id` untuk lookup target, sama seperti pola di Task 11
- Mapping module key → variabel findings (mengikuti tabel modul di spec section 3.6, lines 438-446):
  - `fingerprint_ext` → `fp` (dari `scan_fingerprint`)
  - `ssl` → `ssl_findings` + `redirect_findings` (DUA pemanggilan scanner digabung jadi SATU module key `ssl` — keduanya termasuk kategori "SSL/TLS + HTTP redirect analyzer" per tabel spec baris 439)
  - `headers` → `header_findings`
  - `vulnerabilities` → `vuln_findings`
  - `open_dirs` → `dir_findings`
  - `cve` → `cve_findings`
  - `cookies` → `cookie_findings`
  - `endpoints` → `endpoint_findings`

- [ ] **Step 1: Tambah `OJSTarget` ke import (baris 8)**

Ganti:
```python
from app.models import ScanJob, ScanFinding
```
Menjadi:
```python
from app.models import OJSTarget, ScanJob, ScanFinding
```

- [ ] **Step 2: Ganti seluruh isi fungsi `_run_external_scan` (baris 24-90)**

Ganti dari `async def _run_external_scan(job_id: str, target_url: str):` sampai baris `await _try_trigger_scoring(job_id)` (akhir fungsi, sebelum dekorator `@celery_app.task`) dengan kode berikut:

```python
async def _run_external_scan(job_id: str, target_url: str):
    hostname = urlparse(target_url).hostname
    module_errors: dict[str, str] = {}
    all_findings: list = []
    ojs_version = None

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 1, 9, "Mendeteksi versi OJS dan fingerprint...", "TASK")
    try:
        ojs_version, fp = await scan_fingerprint(target_url)
        all_findings += fp
    except Exception as e:
        module_errors["fingerprint_ext"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 2, 9, "Memeriksa SSL/TLS dan redirect HTTP ke HTTPS...", "TASK")
    try:
        ssl_findings = scan_ssl(hostname) if hostname else []
        redirect_findings = await scan_http_redirect(hostname) if hostname else []
        all_findings += ssl_findings + redirect_findings
    except Exception as e:
        module_errors["ssl"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 3, 9, "Menganalisis HTTP security headers...", "TASK")
    try:
        all_findings += await scan_headers(target_url)
    except Exception as e:
        module_errors["headers"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 4, 9, "Menguji kerentanan yang diketahui...", "TASK")
    try:
        all_findings += await scan_vulnerabilities(target_url)
    except Exception as e:
        module_errors["vulnerabilities"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 5, 9, "Memeriksa direktori dan file sensitif...", "TASK")
    try:
        all_findings += await scan_open_dirs(target_url)
    except Exception as e:
        module_errors["open_dirs"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 6, 9, "Mencocokkan CVE dari NVD...", "TASK")
    try:
        all_findings += await scan_cve(ojs_version)
    except Exception as e:
        module_errors["cve"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 7, 9, "Memeriksa keamanan cookie sesi...", "TASK")
    try:
        all_findings += await scan_cookies(target_url)
    except Exception as e:
        module_errors["cookies"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 8, 9, "Memeriksa aksesibilitas endpoint OJS...", "TASK")
    try:
        all_findings += await scan_ojs_endpoints(target_url)
    except Exception as e:
        module_errors["endpoints"] = str(e)[:100]

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
                references=json.dumps(f.references) if f.references else None,
                remediation_steps=json.dumps(f.remediation_steps) if f.remediation_steps else None,
            ))
        job.module_errors = json.dumps(module_errors) if module_errors else None

        if ojs_version and isinstance(ojs_version, str):
            target = await session.get(OJSTarget, job.target_id)
            if target and target.ojs_version != ojs_version:
                target.ojs_version = ojs_version

        await session.commit()

    await write_progress(
        job_id, "external_scan", 9, 9,
        f"Pemindaian eksternal selesai — {len(all_findings)} temuan", "DONE",
    )
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    raw = await r.get(f"scan_progress:{job_id}")
    progress = json.loads(raw) if raw else {}
    progress["external_done"] = True
    await r.setex(f"scan_progress:{job_id}", 3600, json.dumps(progress))
    await r.aclose()
    if await _check_cancelled(job_id): return
    await _try_trigger_scoring(job_id)
```

**Catatan desain:**
- `scan_cve(ojs_version)` dipanggil dengan `ojs_version` yang mungkin `None` jika fingerprint gagal — perilaku ini SAMA dengan kode asli (tidak ada perubahan kontrak); `scan_cve` sudah menangani `None` secara internal (lihat implementasi existing, tidak diubah oleh plan ini).
- Jika `scan_fingerprint` melempar exception, `ojs_version` tetap `None` (diinisialisasi di awal fungsi) sehingga langkah CVE matching tidak crash karena `NameError`.
- `module_errors["fingerprint_ext"]` HANYA diisi jika `scan_fingerprint()` melempar exception — bukan jika versi tidak terdeteksi (`ojs_version is None` tapi tidak ada exception adalah kondisi normal "Belum terdeteksi", bukan error modul).

- [ ] **Step 3: Verifikasi sintaks**

Run: `cd OJSDEF-BackEnd; python -c "import ast; ast.parse(open('app/workers/external_bot.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add OJSDEF-BackEnd/app/workers/external_bot.py
git commit -m "feat: catat module_errors dan propagasi ojs_version di external scan worker"
```

---

### Task 13: `types/api.ts` — tambah field `references`, `remediation_steps`, `module_errors`

**Tujuan:** Selaraskan tipe TypeScript frontend dengan field baru yang sekarang dikirim backend di `FindingResponse` dan `ScanResponse` (lihat Task 9).

**Files:**
- Modify: `OJSDEF-FrontEnd/types/api.ts:97-111` (interface `ScanFinding`), `:81-96` (interface `ScanJob`)

**Konteks penting (hasil pembacaan file saat ini):**
- `ScanFinding` (baris 97-111) berakhir dengan field `is_false_positive: boolean` di baris 110
- `ScanJob` (baris 81-96) berakhir dengan field `created_at: string` di baris 95

- [ ] **Step 1: Tambah field ke interface `ScanFinding`**

Cari blok ini (baris 97-111):
```typescript
export interface ScanFinding {
  id: string
  finding_type: string
  category: string
  title: string
  description: string
  affected_path: string
  evidence: string
  remediation: string
  severity: SeverityLevel
  cvss_score: number
  cve_id: string | null
  owasp_category: string | null
  is_false_positive: boolean
}
```

Ganti menjadi (menambah `references` dan `remediation_steps` setelah `is_false_positive`):
```typescript
export interface ScanFinding {
  id: string
  finding_type: string
  category: string
  title: string
  description: string
  affected_path: string
  evidence: string
  remediation: string
  severity: SeverityLevel
  cvss_score: number
  cve_id: string | null
  owasp_category: string | null
  is_false_positive: boolean
  references: string[]
  remediation_steps: string[]
}
```

- [ ] **Step 2: Tambah field ke interface `ScanJob`**

Cari blok ini (baris 81-96):
```typescript
export interface ScanJob {
  id: string
  target_id: string
  scan_type: ScanType
  status: ScanStatus
  overall_score: number | null
  risk_level: SeverityLevel | null
  critical_count: number
  high_count: number
  medium_count: number
  low_count: number
  diagnostic_code: string | null
  diagnostic_detail: string | null
  progress: ScanProgress | null
  created_at: string
}
```

Ganti menjadi (menambah `module_errors` setelah `created_at`):
```typescript
export interface ScanJob {
  id: string
  target_id: string
  scan_type: ScanType
  status: ScanStatus
  overall_score: number | null
  risk_level: SeverityLevel | null
  critical_count: number
  high_count: number
  medium_count: number
  low_count: number
  diagnostic_code: string | null
  diagnostic_detail: string | null
  progress: ScanProgress | null
  created_at: string
  module_errors: Record<string, string>
}
```

- [ ] **Step 3: Verifikasi tipe**

Run: `cd OJSDEF-FrontEnd; npx tsc --noEmit`
Expected: tidak ada error baru terkait `ScanFinding`/`ScanJob` (error pra-existing yang tidak terkait boleh diabaikan — catat jika ada untuk laporan akhir)

- [ ] **Step 4: Commit**

```bash
git add OJSDEF-FrontEnd/types/api.ts
git commit -m "feat: tambah field references, remediation_steps, module_errors ke tipe ScanFinding dan ScanJob"
```

---

### Task 14: Buat `lib/scanner-modules.ts` (file baru)

**Tujuan:** Sediakan satu sumber kebenaran untuk daftar 14 modul scanner (6 internal + 8 eksternal), mapping `module key → finding_type[]`, dan fungsi `getModuleStatus()` yang menentukan status tampilan tiap modul (ditemukan/bersih/gagal/info/skip) berdasarkan `findings`, `module_errors`, dan `scan_type` aktif. Dipakai oleh `ModuleStatusGrid` di Task 15.

**Files:**
- Create: `OJSDEF-FrontEnd/lib/scanner-modules.ts`

**Konteks penting:**
- Kode berikut ditranskripsi LANGSUNG dari spec section 5.2 (sudah final, tidak perlu diubah) — termasuk seluruh 14 entri `MODULE_FINDING_TYPES` yang harus PERSIS cocok dengan key `module_errors` yang ditulis backend (`fingerprint`, `config`, `plugins`, `rbac`, `file_integrity`, `content`, `fingerprint_ext`, `ssl`, `headers`, `cookies`, `vulnerabilities`, `open_dirs`, `cve`, `endpoints` — lihat Task 11 & 12)
- Import `ScanFinding` dan `ScanType` dari `@/types/api` (sudah ada di `types/api.ts`, lihat baris 63 dan 97)

- [ ] **Step 1: Buat file `lib/scanner-modules.ts` dengan isi berikut**

```typescript
import type { ScanFinding, ScanType } from '@/types/api'

export interface ScannerModule {
  key: string
  label: string
  scan_types: ScanType[]
}

export const INTERNAL_MODULES: ScannerModule[] = [
  { key: 'fingerprint',    label: 'Fingerprint OJS',    scan_types: ['internal', 'full'] },
  { key: 'config',         label: 'Konfigurasi',        scan_types: ['internal', 'full'] },
  { key: 'plugins',        label: 'Audit Plugin',       scan_types: ['internal', 'full'] },
  { key: 'rbac',           label: 'Akses & Hak Akun',   scan_types: ['internal', 'full'] },
  { key: 'file_integrity', label: 'Integritas File',    scan_types: ['internal', 'full'] },
  { key: 'content',        label: 'Konten Injeksi',     scan_types: ['internal', 'full'] },
]

export const EXTERNAL_MODULES: ScannerModule[] = [
  { key: 'fingerprint_ext', label: 'Fingerprint Eksternal', scan_types: ['external', 'full'] },
  { key: 'ssl',             label: 'SSL / TLS',             scan_types: ['external', 'full'] },
  { key: 'headers',         label: 'HTTP Headers',          scan_types: ['external', 'full'] },
  { key: 'cookies',         label: 'Cookie Keamanan',       scan_types: ['external', 'full'] },
  { key: 'vulnerabilities', label: 'Kerentanan Aktif',      scan_types: ['external', 'full'] },
  { key: 'open_dirs',       label: 'Direktori Sensitif',    scan_types: ['external', 'full'] },
  { key: 'cve',             label: 'CVE Database',          scan_types: ['external', 'full'] },
  { key: 'endpoints',       label: 'Endpoint Publik',       scan_types: ['external', 'full'] },
]

export const MODULE_FINDING_TYPES: Record<string, string[]> = {
  fingerprint:     [],
  config:          ['debug_mode_active', 'force_ssl_disabled', 'smtp_no_auth', 'db_password_empty', 'api_key_too_short'],
  plugins:         ['disabled_plugins_installed', 'excessive_active_plugins'],
  rbac:            ['multiple_superadmin', 'inactive_high_priv_account'],
  file_integrity:  ['modified_core_file', 'modified_plugin_file', 'missing_core_file'],
  content:         ['gambling_content', 'eval_base64_injection', 'hidden_iframe_injection', 'phishing_tld_link', 'js_redirect_injection'],
  fingerprint_ext: ['ojs_version_exposed', 'outdated_ojs_version'],
  ssl:             ['ssl_expired', 'ssl_expiring_soon', 'weak_tls', 'http_no_https_redirect'],
  headers:         ['missing_csp', 'missing_hsts', 'missing_x_frame', 'missing_referrer_policy', 'missing_permissions_policy', 'missing_x_content_type_options'],
  cookies:         ['cookie_missing_secure_flag', 'cookie_missing_httponly_flag', 'cookie_missing_samesite'],
  vulnerabilities: ['reflected_xss', 'sql_error_exposed', 'path_traversal'],
  open_dirs:       ['exposed_git', 'exposed_env_file', 'phpinfo_exposed', 'open_directory'],
  cve:             ['cve_ojs'],
  endpoints:       ['ojs_admin_endpoint_exposed', 'ojs_oai_accessible'],
}

export type ModuleStatus = 'found_critical' | 'found_high' | 'found_medium' | 'found_low' | 'clean' | 'error' | 'info' | 'skipped'

export function getModuleStatus(
  moduleKey: string,
  findings: ScanFinding[],
  moduleErrors: Record<string, string>,
  scanType: ScanType,
  module: ScannerModule,
): ModuleStatus {
  if (!module.scan_types.includes(scanType)) return 'skipped'
  if (moduleErrors[moduleKey]) return 'error'
  // Modul fingerprint: selalu info (tidak ada finding, hanya data)
  if (moduleKey === 'fingerprint' || moduleKey === 'fingerprint_ext') return 'info'
  const relevantTypes = MODULE_FINDING_TYPES[moduleKey] ?? []
  const active = findings.filter(f => relevantTypes.includes(f.finding_type) && !f.is_false_positive)
  if (active.length === 0) return 'clean'
  const worst = active.reduce((a, b) => a.cvss_score >= b.cvss_score ? a : b)
  if (worst.severity === 'critical') return 'found_critical'
  if (worst.severity === 'high')     return 'found_high'
  if (worst.severity === 'medium')   return 'found_medium'
  return 'found_low'
}
```

**Catatan desain:**
- `findings.filter(... && !f.is_false_positive)` memastikan temuan yang sudah ditandai "Positif Palsu" tidak mempengaruhi status modul (modul tetap bisa tampil "Tidak Ditemukan" walau ada finding yang sudah di-false-positive-kan) — perilaku ini SUDAH eksplisit di kode spec, bukan tambahan.
- Status `error` diprioritaskan SEBELUM pengecekan `fingerprint`/`info` — jika modul fingerprint gagal (mis. exception saat `scan_fingerprint`), tetap tampil sebagai "Gagal", bukan "Info".
- `skipped` (modul tidak relevan untuk `scan_type` aktif) dicek PALING AWAL — modul internal tidak pernah tampil untuk scan eksternal dan sebaliknya.

- [ ] **Step 2: Verifikasi tipe**

Run: `cd OJSDEF-FrontEnd; npx tsc --noEmit`
Expected: tidak ada error pada `lib/scanner-modules.ts`

- [ ] **Step 3: Commit**

```bash
git add OJSDEF-FrontEnd/lib/scanner-modules.ts
git commit -m "feat: tambah lib/scanner-modules.ts untuk mapping modul scanner dan getModuleStatus"
```

---

### Task 15: Redesign `app/(dashboard)/vulnerability-report/page.tsx`

**Tujuan:** Tambahkan `ModuleStatusGrid` (status semua modul scanner relevan dengan `scan_type`), perkaya `FindingCard` (badge kategori, langkah perbaikan bernomor, referensi clickable), tambahkan filter-by-module yang terhubung dengan klik card status modul, dan paginasi (>20 temuan → 10/halaman).

**Files:**
- Modify: `OJSDEF-FrontEnd/app/(dashboard)/vulnerability-report/page.tsx` (seluruh file, 259 baris)

**Konteks penting (hasil pembacaan file saat ini):**
- Komponen yang ada: `ScanSummary` (28-73), `ScanSelector` (75-100), `FindingCard` (102-166), `FindingsList` (168-217), `VulnerabilityReportContent` (219-251), `VulnerabilityReportPage` (253-259)
- `category` field finding bernilai string literal `"internal"` atau `"external"` (lihat `app/scanners/external/*.py` — semua scanner eksternal pakai `category="external"`, scanner internal pakai `"internal"`)
- `useScanJob(jobId)` SUDAH dipakai di `ScanSummary` (baris 29) — `FindingsList` perlu memanggilnya juga untuk akses `job.scan_type` dan `job.module_errors` (TanStack Query men-cache by key, tidak ada request HTTP duplikat)
- Label severity proyek (`SEVERITY_LABELS` dari `lib/utils`): `critical→Kritis, high→Berbahaya, medium→Perhatian, low→Aman`. Untuk label status modul "N Ditemukan (...)" digunakan kata yang TIDAK kontradiktif dengan makna "ditemukan" — spec menulis "Sedang"/"Rendah" untuk severity medium/low pada grid (bukan "Perhatian"/"Aman", yang akan janggal dipasangkan dengan kata "Ditemukan"); plan ini mengikuti pilihan kata spec untuk grid SAJA, sementara badge severity pada `FindingCard` tetap pakai `SEVERITY_LABELS` proyek (Kritis/Berbahaya/Perhatian/Aman) — tidak berubah.
- Proyek mewajibkan ikon HANYA dari `lucide-react` (AGENTS.md poin 4) — plan ini mengganti ikon emoji pada tabel spec section 5.2 dengan ikon lucide yang setara (`AlertTriangle`, `CheckCircle2`, `AlertCircle`, `Info`) sebagai penyesuaian wajib terhadap standar proyek.

- [ ] **Step 1: Update import statement (baris 9-17)**

Ganti:
```tsx
import {
  SEVERITY_LABELS, SEVERITY_COLORS, SEVERITY_BG_COLORS, SCAN_TYPE_LABELS,
} from '@/lib/utils'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { ChevronDown, ChevronUp, AlertTriangle, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { ScanFinding, ScanJob, SeverityLevel } from '@/types/api'
```

Menjadi:
```tsx
import {
  SEVERITY_LABELS, SEVERITY_COLORS, SEVERITY_BG_COLORS, SCAN_TYPE_LABELS,
} from '@/lib/utils'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  ChevronDown, ChevronUp, ChevronLeft, ChevronRight,
  AlertTriangle, AlertCircle, CheckCircle2, Info,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { ScanFinding, ScanJob, SeverityLevel } from '@/types/api'
import {
  getModuleStatus, INTERNAL_MODULES, EXTERNAL_MODULES, MODULE_FINDING_TYPES,
  type ModuleStatus, type ScannerModule,
} from '@/lib/scanner-modules'
```

- [ ] **Step 2: Tambah konstanta `MODULE_STATUS_CONFIG` dan komponen `ModuleStatusGrid` setelah `ScanSelector` (setelah baris 100, sebelum `function FindingCard`)**

Sisipkan blok berikut tepat sebelum `function FindingCard(...)`:

```tsx
const MODULE_STATUS_CONFIG: Record<ModuleStatus, {
  icon: typeof Info
  label: (count: number) => string
  className: string
}> = {
  found_critical: { icon: AlertTriangle, label: (n) => `${n} Ditemukan (Kritis)`,     className: 'text-red-400 bg-red-500/10 border-red-500/20' },
  found_high:     { icon: AlertTriangle, label: (n) => `${n} Ditemukan (Berbahaya)`,  className: 'text-orange-400 bg-orange-500/10 border-orange-500/20' },
  found_medium:   { icon: AlertTriangle, label: (n) => `${n} Ditemukan (Sedang)`,     className: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/20' },
  found_low:      { icon: AlertTriangle, label: (n) => `${n} Ditemukan (Rendah)`,     className: 'text-blue-400 bg-blue-500/10 border-blue-500/20' },
  clean:          { icon: CheckCircle2,  label: () => 'Tidak Ditemukan',             className: 'text-green-400 bg-green-500/10 border-green-500/20' },
  error:          { icon: AlertCircle,   label: () => 'Gagal',                       className: 'text-slate-400 bg-slate-500/10 border-slate-500/20' },
  info:           { icon: Info,          label: () => 'Info',                        className: 'text-slate-300 bg-slate-500/10 border-slate-500/20' },
  skipped:        { icon: Info,          label: () => '',                            className: '' },
}

function ModuleStatusGrid({
  job, findings, modules, title, onSelectModule,
}: {
  job: ScanJob
  findings: ScanFinding[]
  modules: ScannerModule[]
  title: string
  onSelectModule: (key: string) => void
}) {
  const moduleErrors = job.module_errors ?? {}
  const rows = modules
    .map((module) => ({ module, status: getModuleStatus(module.key, findings, moduleErrors, job.scan_type, module) }))
    .filter((row) => row.status !== 'skipped')
  if (!rows.length) return null
  return (
    <div className="glass-dark rounded-xl border border-white/5 p-5 space-y-3">
      <p className="text-slate-400 text-xs font-semibold uppercase tracking-wide">{title}</p>
      <div className="space-y-2">
        {rows.map(({ module, status }) => {
          const config = MODULE_STATUS_CONFIG[status]
          const Icon = config.icon
          const relevantTypes = MODULE_FINDING_TYPES[module.key] ?? []
          const count = findings.filter((f) => relevantTypes.includes(f.finding_type) && !f.is_false_positive).length
          const clickable = status.startsWith('found_')
          return (
            <button
              key={module.key}
              type="button"
              disabled={!clickable}
              onClick={() => clickable && onSelectModule(module.key)}
              title={status === 'error' ? moduleErrors[module.key] : undefined}
              className={`w-full flex items-center justify-between gap-3 px-3 py-2 rounded-lg border text-sm transition-colors ${config.className} ${clickable ? 'cursor-pointer hover:opacity-80' : 'cursor-default'}`}
            >
              <span className="text-slate-300 font-medium">{module.label}</span>
              <span className="flex items-center gap-1.5 text-xs font-semibold">
                <Icon className="h-3.5 w-3.5" />
                {config.label(count)}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Tambah badge kategori di `FindingCard` (sisipkan setelah badge severity, di dalam blok `flex items-center gap-2 flex-wrap` baris 112-122)**

Cari:
```tsx
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${SEVERITY_BG_COLORS[finding.severity]} ${SEVERITY_COLORS[finding.severity]}`}>
              {SEVERITY_LABELS[finding.severity]}
            </span>
            {finding.is_false_positive && (
```

Ganti menjadi (menyisipkan badge kategori setelah badge severity):
```tsx
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${SEVERITY_BG_COLORS[finding.severity]} ${SEVERITY_COLORS[finding.severity]}`}>
              {SEVERITY_LABELS[finding.severity]}
            </span>
            <span className="text-xs px-2 py-0.5 rounded bg-slate-700/40 text-slate-400 border border-white/5 font-medium">
              {finding.category === 'internal' ? 'Internal' : 'Eksternal'}
            </span>
            {finding.is_false_positive && (
```

- [ ] **Step 4: Ganti blok "Langkah Perbaikan" dan tambah blok "Referensi" (baris 144-147)**

Cari:
```tsx
          <div>
            <p className="text-slate-500 text-xs uppercase tracking-wide mb-2">Langkah Perbaikan</p>
            <p className="text-slate-300 text-sm whitespace-pre-wrap">{finding.remediation}</p>
          </div>
```

Ganti menjadi:
```tsx
          <div>
            <p className="text-slate-500 text-xs uppercase tracking-wide mb-2">Langkah Perbaikan</p>
            {finding.remediation_steps.length > 0 ? (
              <ol className="space-y-1.5 list-decimal list-inside">
                {finding.remediation_steps.map((step, i) => (
                  <li key={i} className="text-slate-300 text-sm leading-relaxed">{step}</li>
                ))}
              </ol>
            ) : (
              <p className="text-slate-300 text-sm whitespace-pre-wrap">{finding.remediation}</p>
            )}
          </div>
          {finding.references.length > 0 && (
            <div>
              <p className="text-slate-500 text-xs uppercase tracking-wide mb-2">Referensi</p>
              <ul className="space-y-1">
                {finding.references.map((ref, i) => (
                  <li key={i}>
                    <a href={ref} target="_blank" rel="noopener noreferrer"
                       className="text-primary text-xs hover:underline break-all">
                      {ref}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
```

- [ ] **Step 5: Ganti seluruh fungsi `FindingsList` (baris 168-217)**

Ganti dari `function FindingsList({ jobId }: { jobId: string }) {` sampai penutup `}` fungsi tersebut (baris 217) dengan kode berikut:

```tsx
const PAGE_SIZE = 10

function FindingsList({ jobId }: { jobId: string }) {
  const { data: findings, isLoading } = useFindings(jobId)
  const { data: job } = useScanJob(jobId)
  const { user } = useAuth()
  const isSaasAdmin = user?.role === 'saas_admin'
  const [filterSeverity, setFilterSeverity] = useState<SeverityLevel | 'all'>('all')
  const [filterModule, setFilterModule] = useState<string | 'all'>('all')
  const [page, setPage] = useState(1)

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

  function handleSelectModule(moduleKey: string) {
    setFilterModule(moduleKey)
    setFilterSeverity('all')
    setPage(1)
  }

  const bySeverity = filterSeverity === 'all' ? findings : findings.filter((f) => f.severity === filterSeverity)
  const visible = filterModule === 'all'
    ? bySeverity
    : bySeverity.filter((f) => (MODULE_FINDING_TYPES[filterModule] ?? []).includes(f.finding_type))

  const totalPages = Math.ceil(visible.length / PAGE_SIZE)
  const paged = visible.length > 20 ? visible.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE) : visible

  return (
    <div className="space-y-4">
      {job && (
        <div className="space-y-4">
          <p className="text-slate-400 text-xs font-semibold uppercase tracking-wide">Status Per Modul Scanner</p>
          <div className="grid md:grid-cols-2 gap-4">
            {(job.scan_type === 'internal' || job.scan_type === 'full') && (
              <ModuleStatusGrid job={job} findings={findings} modules={INTERNAL_MODULES} title="Scan Internal" onSelectModule={handleSelectModule} />
            )}
            {(job.scan_type === 'external' || job.scan_type === 'full') && (
              <ModuleStatusGrid job={job} findings={findings} modules={EXTERNAL_MODULES} title="Scan Eksternal" onSelectModule={handleSelectModule} />
            )}
          </div>
        </div>
      )}

      <div>
        <p className="text-slate-400 text-xs font-semibold uppercase tracking-wide mb-2">Detail Temuan</p>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => { setFilterSeverity('all'); setFilterModule('all'); setPage(1) }}
            className={`px-3 py-1 rounded-full text-sm transition-colors ${filterSeverity === 'all' && filterModule === 'all' ? 'bg-primary text-white' : 'text-slate-400 hover:text-white'}`}
          >
            Semua ({findings.length})
          </button>
          {SEVERITY_ORDER.map((sev) => {
            const count = findings.filter((f) => f.severity === sev).length
            if (!count) return null
            return (
              <button
                key={sev}
                onClick={() => { setFilterSeverity(sev); setFilterModule('all'); setPage(1) }}
                className={`px-3 py-1 rounded-full text-sm transition-colors ${filterSeverity === sev && filterModule === 'all' ? 'bg-primary text-white' : `${SEVERITY_COLORS[sev]} hover:opacity-80`}`}
              >
                {SEVERITY_LABELS[sev]} ({count})
              </button>
            )
          })}
          {filterModule !== 'all' && (
            <button
              onClick={() => { setFilterModule('all'); setPage(1) }}
              className="px-3 py-1 rounded-full text-sm bg-primary text-white flex items-center gap-1.5"
            >
              Modul: {filterModule} ✕
            </button>
          )}
        </div>
      </div>

      <div className="space-y-3">
        {paged.map((finding) => <FindingCard key={finding.id} finding={finding} jobId={jobId} isSaasAdmin={isSaasAdmin} />)}
      </div>

      {visible.length > 20 && (
        <div className="flex items-center justify-center gap-4 pt-2">
          <Button
            variant="ghost" size="sm"
            className="text-slate-400 hover:text-white"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
          >
            <ChevronLeft className="h-4 w-4 mr-1" /> Sebelumnya
          </Button>
          <span className="text-slate-500 text-sm">Halaman {page} / {totalPages}</span>
          <Button
            variant="ghost" size="sm"
            className="text-slate-400 hover:text-white"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
          >
            Berikutnya <ChevronRight className="h-4 w-4 ml-1" />
          </Button>
        </div>
      )}
    </div>
  )
}
```

**Catatan desain:**
- Tombol "Modul: {filterModule} ✕" menampilkan key teknis modul (mis. `config`, `headers`) — alternatif menampilkan label manusiawi (`Konfigurasi`) memerlukan lookup tambahan; key teknis dianggap cukup jelas untuk konteks admin/viewer yang sedang menelusuri laporan teknis. Jika reviewer menginginkan label manusiawi, tambahkan helper `getModuleLabel(key)` yang mencari di `[...INTERNAL_MODULES, ...EXTERNAL_MODULES]`.
- Filter severity dan filter modul saling eksklusif (memilih salah satu me-reset yang lain) — menghindari kombinasi filter yang membingungkan (mis. "modul `config` + severity `low`" bisa menghasilkan 0 hasil tanpa penjelasan jelas ke pengguna).
- Paginasi HANYA muncul jika `visible.length > 20`, dan didasarkan pada `visible` (hasil setelah filter) — sesuai spec section 5.4. Mengubah filter me-reset `page` ke 1 agar tidak terjebak di halaman kosong.

- [ ] **Step 6: Jalankan dev server dan uji manual di browser**

Run: `cd OJSDEF-FrontEnd; npm run dev`

Buka `http://localhost:3000/vulnerability-report`, login sebagai `admin@ub.ac.id` / `admin123`, lalu verifikasi:
- `ModuleStatusGrid` tampil dengan baris status per modul (skip modul yang tidak relevan dengan `scan_type`)
- Klik baris modul berstatus "Ditemukan" → filter findings ke modul tersebut, badge filter muncul
- `FindingCard` menampilkan badge kategori (Internal/Eksternal), langkah perbaikan bernomor, dan daftar referensi yang bisa diklik
- Jika total temuan > 20 → kontrol paginasi muncul dan berfungsi

> **Catatan constraint lokal:** karena tidak ada database/Docker aktif, data API mungkin kosong atau gagal fetch — jika demikian, verifikasi minimal: halaman render tanpa runtime error, tidak ada warning React di console terkait props/key, dan TypeScript/lint bersih (lihat Step 7). Jika data mock/seed tersedia dari sesi sebelumnya, gunakan untuk uji visual penuh.

- [ ] **Step 7: Verifikasi tipe dan lint**

Run: `cd OJSDEF-FrontEnd; npx tsc --noEmit; npm run lint`
Expected: tidak ada error baru terkait file ini

- [ ] **Step 8: Commit**

```bash
git add "OJSDEF-FrontEnd/app/(dashboard)/vulnerability-report/page.tsx"
git commit -m "feat: redesign laporan keamanan dengan ModuleStatusGrid, referensi, dan paginasi"
```

---

### Task 16: Update badge `ojs_version` di `app/(dashboard)/targets/[id]/page.tsx`

**Tujuan:** Ganti tampilan teks polos `ojs_version` dengan badge berwarna jika terdeteksi, atau pesan ajakan scan jika belum (`null`/`unknown`) — sesuai keluhan user "setelah scan versi OJS masih unknown atau tidak terload" yang menjadi salah satu pemicu redesign ini (lihat brainstorming Q&A spec).

**Files:**
- Modify: `OJSDEF-FrontEnd/app/(dashboard)/targets/[id]/page.tsx:256-265`

**Konteks penting (hasil pembacaan file saat ini):**
- Card "Versi OJS" saat ini (baris 256-265) hanya menampilkan `{target.ojs_version ?? '—'}` sebagai teks polos berwarna putih — tidak ada badge maupun ajakan untuk menjalankan scan.
- `target.ojs_version` bertipe `string | null` (lihat `types/api.ts:33`)

- [ ] **Step 1: Ganti blok card "Versi OJS" (baris 256-265)**

Cari:
```tsx
        <Card className="glass-dark border-none">
          <CardContent className="p-4 space-y-1">
            <p className="text-[9px] font-black uppercase tracking-widest text-muted-foreground/50">
              Versi OJS
            </p>
            <p className="text-xs font-black text-white font-mono">
              {target.ojs_version ?? '—'}
            </p>
          </CardContent>
        </Card>
```

Ganti menjadi:
```tsx
        <Card className="glass-dark border-none">
          <CardContent className="p-4 space-y-1">
            <p className="text-[9px] font-black uppercase tracking-widest text-muted-foreground/50">
              Versi OJS
            </p>
            {target.ojs_version ? (
              <span className="inline-block text-xs font-mono font-bold bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2 py-0.5 rounded">
                {target.ojs_version}
              </span>
            ) : (
              <p className="text-muted-foreground/60 text-[10px] leading-snug">
                Belum terdeteksi — jalankan scan untuk mendeteksi versi OJS
              </p>
            )}
          </CardContent>
        </Card>
```

**Catatan desain:**
- Style badge (`bg-blue-500/10 text-blue-400 border-blue-500/20`) ditranskripsi langsung dari mockup spec section 4.3 (baris 479-490) agar konsisten dengan desain yang sudah disetujui user.
- Ukuran font pesan fallback (`text-[10px]`) disesuaikan agar muat dalam card kecil yang sama dengan card metrik lain di baris sekitarnya — bukan ukuran arbitrer, mengikuti pola `text-[9px]` pada label di atasnya.

- [ ] **Step 2: Jalankan dev server dan verifikasi visual**

Run: `cd OJSDEF-FrontEnd; npm run dev`

Buka halaman detail salah satu target OJS (`/targets/<id>`) dan verifikasi:
- Jika `ojs_version` terisi → tampil sebagai badge biru dengan font monospace
- Jika `ojs_version` adalah `null` → tampil pesan "Belum terdeteksi — jalankan scan untuk mendeteksi versi OJS"

> **Catatan constraint lokal:** tanpa database aktif, data target mungkin kosong/gagal fetch — jika demikian cukup verifikasi halaman render tanpa runtime error dan kedua cabang kondisional (`target.ojs_version` truthy/falsy) tervalidasi lewat pembacaan kode + `tsc`.

- [ ] **Step 3: Verifikasi tipe**

Run: `cd OJSDEF-FrontEnd; npx tsc --noEmit`
Expected: tidak ada error baru pada file ini

- [ ] **Step 4: Commit**

```bash
git add "OJSDEF-FrontEnd/app/(dashboard)/targets/[id]/page.tsx"
git commit -m "feat: tampilkan ojs_version sebagai badge dengan fallback ajakan scan"
```

---

### Task 17: Update `OJSDEF-Plugin/docs/panduan-test-skenario-ojsdef.md`

**Tujuan:** Selaraskan panduan demo dengan perilaku scanner baru — `header_checker.py` sekarang menghasilkan **6 finding terpisah** (bukan satu temuan gabungan `missing_security_headers` CVSS 7.4) dan `cookie_analyzer.py` sekarang mengecek 3 flag terpisah (`Secure`, `HttpOnly`, `SameSite`) — sesuai keputusan user *"Biarkan terpisah saja"* dari sesi brainstorming. Pastikan seluruh skenario yang relevan untuk demo MVP tetap dapat dijalankan dan deskripsinya akurat terhadap output scanner yang baru.

**Files:**
- Modify: `OJSDEF-Plugin/docs/panduan-test-skenario-ojsdef.md`

**Konteks penting (hasil pembacaan file saat ini):**
- B-5 (baris 457-506) saat ini mendeskripsikan SATU temuan gabungan `missing_security_headers` CVSS 7.4/Berbahaya. Setelah Task 6, `header_checker.py` menghasilkan finding individual dengan CVSS berbeda-beda — **TIDAK ADA satupun yang mencapai tier Berbahaya (≥7.0)**:
  | finding_type | CVSS | Severity |
  |---|---|---|
  | `missing_hsts` | 6.5 | Perhatian (medium) |
  | `missing_csp` | 6.0 | Perhatian (medium) |
  | `missing_x_frame` | 5.5 | Perhatian (medium) |
  | `missing_x_content_type_options` | 4.3 | Perhatian (medium) |
  | `missing_referrer_policy` | 3.1 | Aman (low) |
  | `missing_permissions_policy` | 3.1 | Aman (low) |
- A-2 (baris 859-893) saat ini HANYA membahas flag `Secure` (`cookie_missing_secure_flag`, CVSS 3.7/Aman — TIDAK BERUBAH oleh Task 7) tapi komentar curl di baris 873 sudah menyinggung "ada/tidaknya HttpOnly" tanpa skenario terpisah untuk itu. Setelah Task 7, `cookie_analyzer.py` juga menghasilkan `cookie_missing_httponly_flag` (CVSS 4.3/Perhatian) dan `cookie_missing_samesite` (CVSS 4.3/Perhatian) sebagai finding TERPISAH.
- TOC (baris 28-29), referensi silang di baris 999, 1336, dan 1356 menyebut `B-5`/`B-6` — mempertahankan ID `B-5` sebagai anchor menghindari cascading rename di seluruh dokumen.
- Section "PERHATIAN (4.0–6.9)" berakhir di P-6 (baris 785-824), sebelum heading `## Skenario AMAN/RENDAH` (baris 826) — tempat alami untuk menyisipkan skenario cookie baru tanpa renumbering.

- [ ] **Step 1: Ubah judul dan isi B-5 (baris 457-506) agar mencerminkan 6 finding terpisah**

Cari blok dari `### B-5 Missing Security Headers — [EKSTERNAL]` sampai baris `---` (baris 457-506) dan ganti seluruhnya dengan:

```markdown
### B-5 Header Keamanan HTTP Tidak Lengkap — [EKSTERNAL]

> **Catatan penomoran:** ID `B-5` dipertahankan untuk kontinuitas urutan pengujian (lihat referensi "Setup B-1 s/d B-6" di bagian Urutan Pengujian) — meskipun skenario ini sekarang menghasilkan **6 finding terpisah** dengan severity individual **Perhatian–Aman** (bukan satu temuan tunggal "Berbahaya" seperti versi panduan sebelumnya). `header_checker.py` kini mengevaluasi tiap header secara independen.

**CVSS per finding:** lihat tabel di bawah | **Modul:** External HTTP Header Analyzer (`headers`)

**Deskripsi:**
HTTP security headers melindungi pengguna dari XSS, clickjacking, MIME sniffing, dan information leakage di sisi browser. Ketiadaan masing-masing header punya dampak berbeda — sehingga sekarang dilaporkan sebagai temuan individual agar admin bisa memprioritaskan perbaikan per header.

**Langkah setup simulasi kondisi lemah (hapus SEMUA header sekaligus):**

```bash
# Edit nginx.conf — komentari semua baris add_header keamanan
nano ~/ojs-docker/nginx.conf
# Tambahkan # di depan baris-baris berikut (jika ada):
# add_header Strict-Transport-Security ...
# add_header X-Frame-Options ...
# add_header X-Content-Type-Options ...
# add_header Content-Security-Policy ...
# add_header Referrer-Policy ...
# add_header Permissions-Policy ...

docker exec ojs_nginx nginx -s reload
```

**Verifikasi kondisi vulnerable:**

```bash
curl -skI https://ojs.contoh.ac.id | grep -i 'strict-transport\|x-frame\|x-content\|content-security\|referrer-policy\|permissions-policy'
# Jika tidak ada output sama sekali → semua header hilang, scanner akan melaporkan 6 finding terpisah
```

**Output yang diharapkan dari OJSDef — 6 finding terpisah:**

```json
[
  { "finding_type": "missing_hsts",                    "cvss_score": 6.5, "severity": "medium" },
  { "finding_type": "missing_csp",                     "cvss_score": 6.0, "severity": "medium" },
  { "finding_type": "missing_x_frame",                 "cvss_score": 5.5, "severity": "medium" },
  { "finding_type": "missing_x_content_type_options",  "cvss_score": 4.3, "severity": "medium" },
  { "finding_type": "missing_referrer_policy",         "cvss_score": 3.1, "severity": "low" },
  { "finding_type": "missing_permissions_policy",      "cvss_score": 3.1, "severity": "low" }
]
```

> Untuk demo: hapus hanya SEBAGIAN header (mis. hanya HSTS dan CSP) untuk menunjukkan bahwa scanner melaporkan secara presisi header mana yang hilang — bukan satu flag generik "header kurang".

**Remediasi — tambahkan seluruh security headers ke `nginx.conf`:**

```nginx
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Content-Security-Policy "default-src 'self'" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
```

```bash
docker exec ojs_nginx nginx -s reload
```

---
```

- [ ] **Step 2: Tambah catatan rujukan di A-2 (setelah baris 891, sebelum `---` baris 893)**

Cari baris:
```markdown
**Remediasi:** Pastikan redirect HTTP→HTTPS di Nginx aktif. Untuk cookie Secure flag eksplisit, aktifkan `force_ssl = On` di config OJS.

---
```

(ini muncul di akhir section A-2, baris 891-893) Ganti menjadi:

```markdown
**Remediasi:** Pastikan redirect HTTP→HTTPS di Nginx aktif. Untuk cookie Secure flag eksplisit, aktifkan `force_ssl = On` di config OJS.

> **Lihat juga:** flag `HttpOnly` dan `SameSite` pada cookie sesi yang sama kini dilaporkan sebagai finding terpisah — lihat **P-7 Cookie Tanpa HttpOnly dan SameSite Flag**.

---
```

- [ ] **Step 3: Tambah skenario baru P-7 — sisipkan SEBELUM heading `## Skenario AMAN/RENDAH (0.1–3.9)` (baris 826)**

Sisipkan blok berikut tepat sebelum baris `## Skenario AMAN/RENDAH (0.1–3.9)`:

```markdown
### P-7 Cookie Tanpa HttpOnly dan SameSite Flag — [EKSTERNAL]

**CVSS:** 4.3 (masing-masing) | **Modul:** External Cookie Analyzer (`cookies`)

**Deskripsi:**
Atribut `HttpOnly` mencegah JavaScript sisi klien membaca cookie sesi (mitigasi pencurian sesi via XSS), sedangkan `SameSite` mencegah cookie terkirim pada request lintas situs (mitigasi CSRF). Ketiadaan masing-masing dilaporkan sebagai finding terpisah: `cookie_missing_httponly_flag` dan `cookie_missing_samesite`.

**Verifikasi kondisi:**

```bash
curl -skc /tmp/test_cookies.txt \
    https://ojs.contoh.ac.id/index/login -o /dev/null
cat -A /tmp/test_cookies.txt | head -5
# Periksa header Set-Cookie mentah untuk atribut HttpOnly dan SameSite:
curl -skI https://ojs.contoh.ac.id/index/login | grep -i 'set-cookie'
```

**Output yang diharapkan dari OJSDef — 2 finding terpisah (jika kedua flag hilang):**

```json
[
  { "finding_type": "cookie_missing_httponly_flag", "cvss_score": 4.3, "severity": "medium",
    "evidence": "Cookie 'OJSSID' tidak memiliki atribut HttpOnly" },
  { "finding_type": "cookie_missing_samesite",      "cvss_score": 4.3, "severity": "medium",
    "evidence": "Cookie 'OJSSID' tidak memiliki atribut SameSite" }
]
```

**Remediasi:**
1. OJS secara default mengatur `HttpOnly` melalui konfigurasi session PHP — pastikan `session.cookie_httponly = 1` di `php.ini`, atau set eksplisit di Nginx: `proxy_cookie_path / "/; HttpOnly; SameSite=Lax";`
2. Untuk `SameSite`, tambahkan `SameSite=Lax` (atau `Strict` jika tidak ada integrasi cross-site) pada cookie sesi via direktif Nginx di atas, atau via `session.cookie_samesite = "Lax"` di `php.ini` (PHP 7.3+).
3. Reload web server: `docker exec ojs_nginx nginx -s reload`
4. Verifikasi ulang dengan `curl -skI ... | grep -i set-cookie` — pastikan muncul `HttpOnly; SameSite=Lax`.

---
```

- [ ] **Step 4: Update baris checklist External Scanner untuk B-5 (baris 1336) dan tambah baris P-7**

Cari baris:
```markdown
| B-5 | Missing headers | Header Analyzer | `hsts_missing`, `xframe_missing` | Berbahaya |
```

Ganti menjadi (memecah jadi baris per finding + tambah baris P-7 setelahnya):
```markdown
| B-5 | Missing HSTS | Header Analyzer | `missing_hsts` | Perhatian |
| B-5 | Missing CSP | Header Analyzer | `missing_csp` | Perhatian |
| B-5 | Missing X-Frame-Options | Header Analyzer | `missing_x_frame` | Perhatian |
| B-5 | Missing X-Content-Type-Options | Header Analyzer | `missing_x_content_type_options` | Perhatian |
| B-5 | Missing Referrer-Policy | Header Analyzer | `missing_referrer_policy` | Aman |
| B-5 | Missing Permissions-Policy | Header Analyzer | `missing_permissions_policy` | Aman |
| P-7 | Cookie no HttpOnly | Cookie Analyzer | `cookie_missing_httponly_flag` | Perhatian |
| P-7 | Cookie no SameSite | Cookie Analyzer | `cookie_missing_samesite` | Perhatian |
```

- [ ] **Step 5: Tambah P-7 ke TOC (setelah baris 28, entri B-5)**

Cari baris (baris 28):
```markdown
  - [B-5 Missing Security Headers](#b-5-missing-security-headers--eksternal)
```

Ganti menjadi:
```markdown
  - [B-5 Header Keamanan HTTP Tidak Lengkap](#b-5-header-keamanan-http-tidak-lengkap--eksternal)
```

Lalu cari entri TOC untuk P-6 (cari baris yang memuat `[P-6` di daftar isi) dan tambahkan baris baru tepat setelahnya:
```markdown
  - [P-7 Cookie Tanpa HttpOnly dan SameSite Flag](#p-7-cookie-tanpa-httponly-dan-samesite-flag--eksternal)
```

- [ ] **Step 6: Review referensi silang yang tersisa**

Run: `cd OJSDEF-Plugin; grep -n "B-5\|P-7\|missing_security_headers\|hsts_missing\|xframe_missing" docs/panduan-test-skenario-ojsdef.md`

Verifikasi manual:
- Baris 999 (`# 3. Kembalikan nginx security headers (jika dihapus di B-5)`) — TETAP VALID, tidak perlu diubah (B-5 masih ada, hanya isinya berubah)
- Baris ~1356 (`5. Setup B-1 s/d B-6 → scan → verifikasi → remediasi masing-masing`) — TETAP VALID karena range B-1..B-6 masih utuh; opsional tambahkan klausa `, plus P-7 untuk cookie HttpOnly/SameSite` jika ingin eksplisit
- Tidak ada lagi referensi ke `missing_security_headers`, `hsts_missing`, atau `xframe_missing` (nama finding_type lama yang sudah tidak diproduksi scanner) di luar yang baru saja diganti pada Step 4

- [ ] **Step 7: Commit**

```bash
git add OJSDEF-Plugin/docs/panduan-test-skenario-ojsdef.md
git commit -m "docs: perbarui panduan test skenario untuk header dan cookie findings yang kini terpisah"
```

---

### Task 18: Verifikasi akhir — static check seluruh file yang diubah

**Tujuan:** Pastikan SEMUA file yang dimodifikasi/dibuat oleh Task 1-17 lolos pemeriksaan sintaks/tipe statis. **PENTING — KENDALA LOKAL:** Tidak ada database PostgreSQL ataupun Docker aktif di lingkungan ini. Tugas ini **DILARANG KERAS** menjalankan `alembic upgrade`, mengoneksi ke DB/Redis/MinIO, menjalankan worker Celery sungguhan, atau perintah apapun yang butuh service eksternal hidup. Verifikasi terbatas pada **review kode dan static check** (parsing AST Python, type-check TypeScript, lint).

**Files:** Tidak ada file yang dimodifikasi pada task ini — murni verifikasi.

- [ ] **Step 1: Syntax check semua file Python yang diubah/dibuat**

Run (dari root `OJSDEF-BackEnd`):
```bash
cd OJSDEF-BackEnd
python -c "
import ast
files = [
    'app/migrations/versions/010_scanner_enrichment.py',
    'app/models/scan_finding.py',
    'app/models/scan_job.py',
    'app/scanners/enrichment.py',
    'app/scanners/models.py',
    'app/scanners/external/header_checker.py',
    'app/scanners/external/cookie_analyzer.py',
    'app/scanners/external/cve_matcher.py',
    'app/schemas/scans.py',
    'app/routers/scans.py',
    'app/workers/internal_bot.py',
    'app/workers/external_bot.py',
]
errors = []
for f in files:
    try:
        ast.parse(open(f, encoding='utf-8').read())
        print(f'OK   {f}')
    except SyntaxError as e:
        errors.append((f, e))
        print(f'FAIL {f}: {e}')
print('--- SEMUA OK ---' if not errors else f'--- {len(errors)} FILE GAGAL ---')
"
```
Expected: setiap file mencetak `OK   <path>`, diakhiri `--- SEMUA OK ---`. Jika ada `FAIL`, perbaiki sintaks file tersebut sebelum lanjut (JANGAN skip).

- [ ] **Step 2: Verifikasi import resolution `enrichment.py` ↔ `models.py` (tanpa circular import)**

Run:
```bash
cd OJSDEF-BackEnd
python -c "import ast,sys
src = open('app/scanners/models.py', encoding='utf-8').read()
tree = ast.parse(src)
imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
for n in imports:
    print(ast.dump(n)[:120])
"
```
Expected: terlihat `ImportFrom(module='app.scanners.enrichment', names=[alias(name='ENRICHMENT_DATA')]...)` (atau bentuk setara) — pastikan TIDAK ADA `from app.scanners.models import` di dalam `app/scanners/enrichment.py` (cek dengan `grep -n "^from\|^import" app/scanners/enrichment.py` — harus tidak memuat referensi ke `models`).

- [ ] **Step 3: Hitung entri `ENRICHMENT_DATA` — pastikan 42 finding types**

Run:
```bash
cd OJSDEF-BackEnd
python -c "
import ast
tree = ast.parse(open('app/scanners/enrichment.py', encoding='utf-8').read())
for node in ast.walk(tree):
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'ENRICHMENT_DATA' for t in node.targets):
        print('Jumlah entri ENRICHMENT_DATA:', len(node.value.keys))
"
```
Expected: `Jumlah entri ENRICHMENT_DATA: 42`

- [ ] **Step 4: TypeScript type-check frontend**

Run:
```bash
cd OJSDEF-FrontEnd
npx tsc --noEmit
```
Expected: tidak ada error baru yang berasal dari file yang diubah pada plan ini (`types/api.ts`, `lib/scanner-modules.ts`, `app/(dashboard)/vulnerability-report/page.tsx`, `app/(dashboard)/targets/[id]/page.tsx`). Jika ada error pra-existing yang TIDAK terkait perubahan ini, catat untuk laporan akhir tapi jangan diperbaiki di luar scope.

- [ ] **Step 5: ESLint frontend**

Run:
```bash
cd OJSDEF-FrontEnd
npm run lint
```
Expected: tidak ada error baru pada file yang diubah.

- [ ] **Step 6: Review akhir — checklist manual**

Tinjau ulang (baca kode, BUKAN jalankan):
- [ ] Semua 42 `finding_type` di `ENRICHMENT_DATA` punya `references` (≥1 URL) dan `remediation_steps` (≥1 langkah)
- [ ] `make_finding()` tidak meng-override `references`/`remediation_steps` yang sudah eksplisit di-pass oleh caller (verifikasi pola `kwargs.setdefault`)
- [ ] `cve_matcher.py` meng-override `references` dengan URL NVD dinamis per CVE ID
- [ ] `header_checker.py` menghasilkan finding individual untuk 6 header (HSTS, X-Frame-Options, X-Content-Type-Options, CSP, Referrer-Policy, Permissions-Policy)
- [ ] `cookie_analyzer.py` menghasilkan finding individual untuk 3 flag cookie (Secure, HttpOnly, SameSite)
- [ ] `internal_bot.py` dan `external_bot.py` membungkus SETIAP pemanggilan scanner module dalam try/except dan mengisi `module_errors` dengan key yang PERSIS cocok dengan `MODULE_FINDING_TYPES` di `lib/scanner-modules.ts`
- [ ] `ojs_targets.ojs_version` ter-propagate dari kedua worker (internal via `results.fingerprint.ojs_version`, eksternal via return value `scan_fingerprint()`)
- [ ] Migration `010_scanner_enrichment.py` punya `down_revision = "009"` (BUKAN "007" seperti tertulis di spec awal — sudah dikoreksi di Task 1)

- [ ] **Step 7: Commit (jika ada perbaikan dari review Step 6)**

Jika Step 6 menemukan masalah dan sudah diperbaiki:
```bash
git add -A
git commit -m "fix: perbaikan hasil review akhir scanner enrichment & report redesign"
```

Jika tidak ada masalah, lewati commit ini — task selesai tanpa perubahan tambahan.

---

## Self-Review Plan (Checklist Penulis)

**1. Cakupan spec:**
- ✅ DB schema baru (`references`, `remediation_steps`, `module_errors`) — Task 1, 2
- ✅ Enrichment data utuh 42 finding types — Task 3, 4 (deviasi terdokumentasi: arsitektur tersentralisasi vs. per-call-site di spec, lihat bagian "Deviasi dari Spec")
- ✅ `make_finding()` modification — Task 5
- ✅ Header checker — 6 finding terpisah — Task 6
- ✅ Cookie analyzer — 3 flag terpisah — Task 7
- ✅ CVE matcher dynamic references override — Task 8
- ✅ Pydantic schema update — Task 9
- ✅ Router response serialization — Task 10
- ✅ Internal worker module_errors + ojs_version propagation — Task 11
- ✅ External worker module_errors + ojs_version propagation — Task 12
- ✅ Frontend types — Task 13
- ✅ `lib/scanner-modules.ts` baru — Task 14
- ✅ Vulnerability report redesign (ModuleStatusGrid, FindingCard, filter, paginasi) — Task 15
- ✅ Target detail ojs_version badge — Task 16
- ✅ Update panduan test skenario — Task 17
- ✅ Static verification end-to-end — Task 18

**2. Placeholder scan:** Tidak ditemukan "TBD"/"TODO"/"implement later" — seluruh task memuat kode lengkap atau instruksi cari-ganti dengan blok kode utuh.

**3. Konsistensi tipe:**
- `FindingResult.references: list[str]` (Task 5) ↔ `ScanFinding.references: Text | None` (Task 2, JSON-encoded) ↔ `FindingResponse.references: list[str]` (Task 9, di-deserialize via `_parse_json_list` Task 10) ↔ frontend `ScanFinding.references: string[]` (Task 13) — KONSISTEN.
- `module_errors` key set: backend menulis `fingerprint`/`config`/`plugins`/`rbac`/`file_integrity`/`content` (internal, Task 11) dan `fingerprint_ext`/`ssl`/`headers`/`vulnerabilities`/`open_dirs`/`cve`/`cookies`/`endpoints` (eksternal, Task 12) — PERSIS cocok dengan key `MODULE_FINDING_TYPES` di Task 14.
- Pydantic class names dikoreksi ke `FindingResponse`/`ScanResponse` (sesuai kode aktual, BUKAN `ScanFindingOut`/`ScanJobOut` yang disebut spec).
- Migration revision dikoreksi ke `revision="010", down_revision="009"` (BUKAN "007" seperti spec — chain aktual berakhir di 009).

---
