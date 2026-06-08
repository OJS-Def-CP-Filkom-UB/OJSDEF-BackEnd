# Design Spec: Scanner Enrichment + Vulnerability Report Redesign

**Tanggal:** 2026-06-07
**Status:** Draft — Menunggu Review
**Scope:** Backend (scanner enrichment, data model, OJS version propagation) + Frontend (vulnerability report redesign, targets page fix)

---

## 1. Latar Belakang & Tujuan

### Masalah yang Diselesaikan

1. **Scanner gap** — `header_checker.py` hanya mengecek 3 dari 5 header yang disebut di PRD F-23 (Referrer-Policy dan Permissions-Policy belum ada). `cookie_analyzer.py` hanya mengecek flag `Secure`, belum `HttpOnly` dan `SameSite`.
2. **Finding kurang detail** — Semua findings hanya punya `remediation` sebagai satu paragraf string dan tidak punya `references` ke standar OWASP/CWE. Tidak ada langkah perbaikan terstruktur (numbered steps).
3. **Vulnerability report hanya tampilkan masalah** — Tidak ada status "Tidak Ditemukan" per modul, tidak ada informasi modul yang gagal jalan (error), sulit membaca postur keamanan secara holistik.
4. **OJS version tidak tersimpan** — Setelah scan selesai, `ojs_targets.ojs_version` tidak diperbarui dari hasil fingerprint, sehingga halaman detail target selalu menampilkan "unknown".

### Tujuan

- Lengkapi coverage scanner sesuai PRD F-23 (headers) dan standar OWASP A02 (cookie flags).
- Semua findings punya `references`, `remediation_steps` (array langkah bernomor), dan CVSS score yang tepat.
- Vulnerability report menampilkan status per modul scanner: **Ditemukan / Tidak Ditemukan / Gagal**.
- OJS version tersimpan ke `ojs_targets` dan tampil di halaman detail target.

---

## 2. Perubahan Data Model — Migration 007

### 2.1 Tabel `scan_findings`

Tambah 2 kolom:

| Kolom | Tipe | Default | Keterangan |
|---|---|---|---|
| `references` | `Text` nullable | `NULL` | JSON array string URL referensi (OWASP, CWE, CVE advisory) |
| `remediation_steps` | `Text` nullable | `NULL` | JSON array string langkah perbaikan bernomor |

Contoh nilai `references`:
```json
["https://owasp.org/www-project-top-ten/2021/A03_2021-Injection/",
 "https://cwe.mitre.org/data/definitions/79.html",
 "https://portswigger.net/web-security/cross-site-scripting/reflected"]
```

Contoh nilai `remediation_steps`:
```json
[
  "Identifikasi semua parameter input yang direfleksikan ke halaman (search query, error messages, dll.)",
  "Terapkan output encoding (htmlspecialchars() di PHP) pada setiap nilai sebelum dirender ke HTML.",
  "Tambahkan header Content-Security-Policy untuk membatasi sumber script yang diizinkan.",
  "Validasi dan whitelist input di sisi server — tolak karakter '<', '>', '\"', '\\'.",
  "Jalankan ulang scan setelah perbaikan untuk konfirmasi."
]
```

### 2.2 Tabel `scan_jobs`

Tambah 1 kolom:

| Kolom | Tipe | Default | Keterangan |
|---|---|---|---|
| `module_errors` | `Text` nullable | `NULL` | JSON dict keyed by module name, hanya berisi modul yang GAGAL |

Contoh nilai `module_errors`:
```json
{
  "file_integrity": "checksums_unavailable",
  "ssl": "connection_timeout"
}
```

Modul yang **tidak ada** di dict ini dianggap berhasil dijalankan (bersih atau ada findings). Error state hanya dicatat untuk modul yang tidak bisa menyelesaikan pemeriksaan sama sekali.

### 2.3 Tabel `ojs_targets` — Tidak Ada Perubahan Schema

Field `ojs_version` sudah ada — hanya perlu diperbarui oleh worker saat scan selesai (lihat Section 5).

### 2.4 Pydantic Schema (`schemas/scans.py`)

```python
class ScanFindingOut(BaseModel):
    # ... existing fields ...
    references: list[str] = []
    remediation_steps: list[str] = []

class ScanJobOut(BaseModel):
    # ... existing fields ...
    module_errors: dict[str, str] = {}
```

### 2.5 TypeScript Type (`types/api.ts`)

```typescript
export interface ScanFinding {
  // ... existing fields ...
  references: string[]
  remediation_steps: string[]
}

export interface ScanJob {
  // ... existing fields ...
  module_errors: Record<string, string>
}
```

---

## 3. Scanner Enrichment — Backend

### 3.1 Model Perubahan (`scanners/models.py`)

Tambah field ke `FindingResult` dataclass:

```python
@dataclass
class FindingResult:
    # ... existing fields ...
    references: list[str] = field(default_factory=list)
    remediation_steps: list[str] = field(default_factory=list)
```

Fungsi `make_finding()` menerima dua parameter opsional baru: `references` dan `remediation_steps`. Semua panggilan `make_finding()` yang ada tetap valid (backward compatible — default kosong).

---

### 3.2 Scanner Baru — External Headers (`scanners/external/header_checker.py`)

Tambah 3 header ke dict `REQUIRED`:

| Header | Finding Type | CVSS | Severity | OWASP |
|---|---|---|---|---|
| `Referrer-Policy` | `missing_referrer_policy` | 3.1 | low | A05:2021 |
| `Permissions-Policy` | `missing_permissions_policy` | 3.1 | low | A05:2021 |
| `X-Content-Type-Options` | `missing_x_content_type_options` | 4.3 | medium | A05:2021 |

**Detail finding `missing_referrer_policy`:**
- **Title:** "Referrer-Policy Tidak Dikonfigurasi"
- **Description:** "Header Referrer-Policy tidak ditemukan. Tanpa header ini, browser mengirim URL penuh (termasuk query string) ke situs eksternal sebagai Referer, berpotensi membocorkan informasi sesi atau parameter sensitif kepada pihak ketiga."
- **Evidence:** `"Header Referrer-Policy tidak ada dalam respons HTTP"`
- **Remediation steps:**
  1. Tambahkan header `Referrer-Policy` di konfigurasi Nginx server block.
  2. Gunakan nilai: `add_header Referrer-Policy "strict-origin-when-cross-origin" always;`
  3. Nilai `strict-origin-when-cross-origin` aman untuk mayoritas jurnal — hanya kirim origin (bukan full URL) saat cross-origin, dan tidak kirim apapun saat downgrade HTTPS→HTTP.
  4. Reload konfigurasi Nginx: `sudo systemctl reload nginx`
  5. Verifikasi dengan: `curl -I https://<domain-ojs>` dan cek header `Referrer-Policy` muncul di respons.
- **References:** OWASP Secure Headers Project, MDN Referrer-Policy

**Detail finding `missing_permissions_policy`:**
- **Title:** "Permissions-Policy Tidak Dikonfigurasi"
- **Description:** "Header Permissions-Policy (pengganti Feature-Policy) tidak ditemukan. Header ini mengontrol akses browser ke fitur sensitif seperti kamera, mikrofon, geolokasi, dan payment API. Tanpa header ini, iframe pihak ketiga dapat mengakses fitur-fitur tersebut tanpa pembatasan."
- **Evidence:** `"Header Permissions-Policy tidak ada dalam respons HTTP"`
- **Remediation steps:**
  1. Tambahkan header `Permissions-Policy` di blok `server {}` konfigurasi Nginx.
  2. Contoh minimal untuk OJS: `add_header Permissions-Policy "geolocation=(), microphone=(), camera=(), payment=()" always;`
  3. Sesuaikan daftar fitur dengan kebutuhan jurnal (hapus fitur yang memang tidak dipakai).
  4. Reload konfigurasi Nginx: `sudo systemctl reload nginx`
  5. Verifikasi dengan: `curl -I https://<domain-ojs>` dan cek header `Permissions-Policy` muncul.
- **References:** OWASP Secure Headers Project, W3C Permissions Policy Spec

**Detail finding `missing_x_content_type_options`:**
- **Title:** "X-Content-Type-Options Tidak Ditemukan"
- **Description:** "Header X-Content-Type-Options tidak ditemukan. Tanpa header ini, browser lama dapat melakukan MIME type sniffing — mengeksekusi file sebagai JavaScript meski Content-Type berbeda. Ini berpotensi dieksploitasi melalui file upload di jurnal jika ada konten berbahaya."
- **Evidence:** `"Header X-Content-Type-Options tidak ada dalam respons HTTP"`
- **Remediation steps:**
  1. Tambahkan header di konfigurasi Nginx: `add_header X-Content-Type-Options "nosniff" always;`
  2. Kata kunci `always` penting agar header muncul juga di halaman error (bukan hanya respons 200).
  3. Reload konfigurasi Nginx: `sudo systemctl reload nginx`
  4. Verifikasi di browser DevTools → Network tab → pilih request → Response Headers, cek `X-Content-Type-Options: nosniff`.
- **References:** OWASP Secure Headers Project, MDN X-Content-Type-Options, CWE-693

---

### 3.3 Scanner Baru — Cookie Flags (`scanners/external/cookie_analyzer.py`)

Perbarui `scan_cookies()` untuk mengecek 3 flag per cookie: `Secure`, `HttpOnly`, `SameSite`.

Tambah 2 finding type baru ke `CVSS_SCORES` di `models.py`:

| Finding Type | CVSS | Severity |
|---|---|---|
| `cookie_missing_httponly_flag` | 4.3 | medium |
| `cookie_missing_samesite` | 4.3 | medium |

**Detail finding `cookie_missing_httponly_flag`:**
- **Title:** "Cookie '{name}' Tidak Memiliki Flag HttpOnly"
- **Description:** "Cookie sesi '{name}' tidak memiliki atribut HttpOnly. Cookie tanpa HttpOnly dapat diakses oleh JavaScript melalui `document.cookie`, sehingga jika terjadi serangan XSS, penyerang dapat mencuri token sesi pengguna dan mengambil alih akun."
- **Evidence:** `Set-Cookie: {raw[:120]}`
- **Remediation steps:**
  1. Set `session.cookie_httponly = 1` di konfigurasi PHP (`php.ini` atau per-directory `.htaccess`).
  2. Untuk Apache `.htaccess`: tambahkan `php_value session.cookie_httponly 1`
  3. Untuk Nginx dengan PHP-FPM: tambahkan `fastcgi_param PHP_VALUE "session.cookie_httponly=1";` di blok `location ~ \.php$`.
  4. Verifikasi di browser DevTools → Application → Cookies → pastikan kolom HttpOnly tercentang untuk cookie OJS.
- **References:** OWASP Session Management Cheat Sheet, CWE-1004, RFC 6265 §5.2.6

**Detail finding `cookie_missing_samesite`:**
- **Title:** "Cookie '{name}' Tidak Memiliki Atribut SameSite"
- **Description:** "Cookie '{name}' tidak memiliki atribut SameSite. Tanpa SameSite, cookie dikirim pada setiap cross-site request, meningkatkan risiko serangan CSRF (Cross-Site Request Forgery). Penyerang dapat memicu aksi atas nama pengguna yang sedang login (submit form, upload file, perubahan konfigurasi jurnal) dari situs lain."
- **Evidence:** `Set-Cookie: {raw[:120]}`
- **Remediation steps:**
  1. Set `session.cookie_samesite = Strict` di konfigurasi PHP jika jurnal tidak memerlukan cross-site navigation.
  2. Atau gunakan `Lax` jika jurnal menggunakan fitur deep-link dari situs eksternal (lebih umum dan aman untuk sebagian besar OJS).
  3. Untuk Apache `.htaccess`: `php_value session.cookie_samesite "Lax"`
  4. Untuk PHP 7.3+: dapat juga diset via `ini_set('session.cookie_samesite', 'Lax');` di awal sesi.
  5. Verifikasi di DevTools → Application → Cookies → kolom SameSite harus menampilkan "Strict" atau "Lax".
- **References:** OWASP CSRF Prevention Cheat Sheet, MDN SameSite attribute, CWE-352, RFC 6265bis

---

### 3.4 Enrichment Semua Finding Existing

Setiap `make_finding()` call yang sudah ada diperbarui dengan `references` dan `remediation_steps`. Berikut tabel lengkap seluruh finding types:

#### Internal Findings

| Finding Type | CVSS | Severity | OWASP | CWE Utama |
|---|---|---|---|---|
| `debug_mode_active` | 9.8 | critical | A05:2021 | CWE-94, CWE-209 |
| `force_ssl_disabled` | 8.1 | high | A02:2021 | CWE-319 |
| `smtp_no_auth` | 5.3 | medium | A07:2021 | CWE-306 |
| `db_password_empty` | 8.0 | high | A07:2021 | CWE-521 |
| `api_key_too_short` | 5.0 | medium | A02:2021 | CWE-326 |
| `multiple_superadmin` | 7.2 | high | A01:2021 | CWE-269 |
| `inactive_high_priv_account` | 5.0 | medium | A07:2021 | CWE-613 |
| `modified_core_file` | 9.1 | critical | A08:2021 | CWE-494 |
| `modified_plugin_file` | 7.8 | high | A08:2021 | CWE-494 |
| `missing_core_file` | 7.5 | high | A08:2021 | CWE-494 |
| `gambling_content` | 9.5 | critical | A03:2021 | CWE-74 |
| `eval_base64_injection` | 9.8 | critical | A03:2021 | CWE-94, CWE-506 |
| `hidden_iframe_injection` | 8.3 | high | A03:2021 | CWE-79 |
| `phishing_tld_link` | 7.5 | high | A03:2021 | CWE-601 |
| `js_redirect_injection` | 6.1 | medium | A03:2021 | CWE-601 |
| `disabled_plugins_installed` | 4.3 | medium | A06:2021 | CWE-1104 |
| `excessive_active_plugins` | 2.0 | low | A06:2021 | — |

**Contoh enrichment `debug_mode_active`:**
```
remediation_steps:
1. Buka file config.inc.php di direktori root instalasi OJS.
2. Temukan section [debug] dan ubah semua flag menjadi Off:
   display_errors = Off
   show_errors = Off
   show_stacktrace = Off
3. Simpan file config.inc.php.
4. Reload web server: sudo systemctl reload nginx (atau apache2).
5. Verifikasi: akses URL yang tidak valid di OJS dan pastikan tidak ada stack trace PHP yang tampil, hanya halaman error generik.

references:
- https://owasp.org/Top10/A05_2021-Security_Misconfiguration/
- https://cwe.mitre.org/data/definitions/209.html  (Information Exposure Through Error Message)
- https://docs.pkp.sfu.ca/dev/documentation/en/getting-started (OJS config.inc.php reference)
- https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html
```

**Contoh enrichment `eval_base64_injection`:**
```
remediation_steps:
1. SEGERA: Pertimbangkan mengisolasi server dari internet jika memungkinkan saat proses pembersihan.
2. Identifikasi lokasi persis konten berbahaya dari field 'affected_path' di temuan ini.
3. Hapus konten yang mengandung eval(base64_decode(...)) dari database OJS menggunakan phpMyAdmin atau psql.
4. Audit seluruh file PHP di server: find /path/to/ojs -name "*.php" | xargs grep -l "eval(base64"
5. Periksa log akses web server (access.log) untuk mengidentifikasi kapan dan bagaimana injeksi terjadi.
6. Reset password semua akun admin OJS dan pastikan MFA aktif jika tersedia.
7. Update OJS ke versi terbaru dan semua plugin ke versi terbaru.
8. Jalankan full scan ulang setelah pembersihan untuk konfirmasi tidak ada sisa injeksi.

references:
- https://owasp.org/Top10/A03_2021-Injection/
- https://cwe.mitre.org/data/definitions/94.html  (Code Injection)
- https://cwe.mitre.org/data/definitions/506.html (Embedded Malicious Code)
- https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html
```

**Contoh enrichment `multiple_superadmin`:**
```
remediation_steps:
1. Login ke OJS sebagai Site Administrator.
2. Buka menu Administration → Site Management → Users.
3. Filter pengguna dengan role "Site Administrator".
4. Identifikasi akun Site Administrator yang tidak diperlukan.
5. Klik nama pengguna → Edit → ubah role menjadi "Journal Manager" untuk jurnal yang relevan, atau nonaktifkan akun.
6. Pertahankan hanya 1 akun Site Administrator aktif sebagai prinsip least privilege.
7. Dokumentasikan akun yang diubah untuk audit trail.

references:
- https://owasp.org/Top10/A01_2021-Broken_Access_Control/
- https://cwe.mitre.org/data/definitions/269.html (Improper Privilege Management)
- https://cheatsheetseries.owasp.org/cheatsheets/Access_Control_Cheat_Sheet.html
- https://docs.pkp.sfu.ca/admin-guide/en/users-and-roles (OJS role management)
```

#### External Findings

| Finding Type | CVSS | Severity | OWASP | CWE Utama |
|---|---|---|---|---|
| `ojs_version_exposed` | 4.0 | medium | A05:2021 | CWE-200 |
| `outdated_ojs_version` | 7.0 | high | A06:2021 | CWE-1104 |
| `ssl_expired` | 9.0 | critical | A02:2021 | CWE-298 |
| `ssl_expiring_soon` | 5.0 | medium | A02:2021 | CWE-298 |
| `weak_tls` | 7.5 | high | A02:2021 | CWE-326, CWE-327 |
| `http_no_https_redirect` | 8.1 | high | A02:2021 | CWE-319 |
| `missing_csp` | 6.0 | medium | A05:2021 | CWE-693 |
| `missing_hsts` | 6.5 | medium | A02:2021 | CWE-319 |
| `missing_x_frame` | 5.5 | medium | A05:2021 | CWE-1021 |
| `missing_referrer_policy` | 3.1 | low | A05:2021 | CWE-200 |
| `missing_permissions_policy` | 3.1 | low | A05:2021 | — |
| `missing_x_content_type_options` | 4.3 | medium | A05:2021 | CWE-693 |
| `reflected_xss` | 8.5 | high | A03:2021 | CWE-79 |
| `sql_error_exposed` | 8.0 | high | A03:2021 | CWE-209, CWE-89 |
| `path_traversal` | 7.5 | high | A01:2021 | CWE-22 |
| `exposed_git` | 9.0 | critical | A05:2021 | CWE-538 |
| `exposed_env_file` | 9.5 | critical | A05:2021 | CWE-538 |
| `phpinfo_exposed` | 7.0 | high | A05:2021 | CWE-200 |
| `open_directory` | 7.0 | high | A05:2021 | CWE-548 |
| `cve_ojs` | 9.0 | critical | A06:2021 | (per CVE) |
| `ojs_admin_endpoint_exposed` | 5.8 | medium | A07:2021 | CWE-307 |
| `ojs_oai_accessible` | 2.6 | low | — | — (informatif) |
| `cookie_missing_secure_flag` | 3.7 | low | A02:2021 | CWE-614 |
| `cookie_missing_httponly_flag` | 4.3 | medium | A02:2021 | CWE-1004 |
| `cookie_missing_samesite` | 4.3 | medium | A01:2021 | CWE-352 |

**Contoh enrichment `exposed_env_file`:**
```
remediation_steps:
1. SEGERA: Asumsikan semua kredensial di .env sudah bocor — mulai rotasi semua password dan API key yang tersimpan di file tersebut.
2. Periksa log akses web server (access.log) untuk mengetahui apakah .env sudah pernah diunduh oleh pihak lain.
3. Pindahkan file .env ke direktori di luar webroot (satu level di atas direktori public/webroot OJS).
4. Jika tidak bisa dipindahkan, blokir akses di Nginx: location ~ /\.env { deny all; return 404; }
5. Untuk Apache: tambahkan di .htaccess: <Files ".env"> Order allow,deny Deny from all </Files>
6. Update semua service yang menggunakan kredensial yang berpotensi terekspos (database, SMTP, API key pihak ketiga).
7. Verifikasi perbaikan: akses https://<domain>/.env — harus mendapat HTTP 403 atau 404.

references:
- https://owasp.org/Top10/A05_2021-Security_Misconfiguration/
- https://cwe.mitre.org/data/definitions/538.html  (Inclusion of Sensitive Info in Log File / Exposed File)
- https://cheatsheetseries.owasp.org/cheatsheets/Infrastructure_as_Code_Security_Cheat_Sheet.html
- https://www.acunetix.com/vulnerabilities/web/env-file-publicly-accessible/
```

**Contoh enrichment `reflected_xss`:**
```
remediation_steps:
1. Identifikasi semua parameter input yang direfleksikan ke halaman tanpa encoding (prioritaskan parameter search/query).
2. Terapkan output encoding pada setiap nilai yang dirender ke HTML — gunakan htmlspecialchars() dengan ENT_QUOTES di PHP.
3. Implementasikan Content-Security-Policy (CSP) yang ketat untuk membatasi sumber script yang diizinkan.
4. Validasi dan whitelist input di sisi server — tolak atau encode karakter '<', '>', '"', "'", '/'.
5. Pertimbangkan menggunakan library sanitasi seperti HTML Purifier untuk konten yang memang boleh mengandung HTML.
6. Jalankan ulang scan setelah perbaikan untuk konfirmasi XSS sudah tidak terdeteksi.

references:
- https://owasp.org/Top10/A03_2021-Injection/
- https://cwe.mitre.org/data/definitions/79.html  (XSS)
- https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html
- https://portswigger.net/web-security/cross-site-scripting/reflected
```

**Contoh enrichment `ssl_expired`:**
```
remediation_steps:
1. Perbarui sertifikat SSL segera — sertifikat kedaluwarsa menyebabkan semua pengunjung melihat peringatan keamanan.
2. Jika menggunakan Let's Encrypt: jalankan sudo certbot renew --force-renewal
3. Jika menggunakan CA komersial: beli/renew sertifikat baru dari penyedia CA, lalu install di web server.
4. Setelah install sertifikat baru, reload Nginx: sudo systemctl reload nginx
5. Aktifkan auto-renewal untuk mencegah kedaluwarsa di masa depan: sudo systemctl enable certbot.timer (untuk Let's Encrypt)
6. Verifikasi sertifikat baru: openssl s_client -connect <domain>:443 | grep "notAfter"

references:
- https://owasp.org/Top10/A02_2021-Cryptographic_Failures/
- https://cwe.mitre.org/data/definitions/298.html  (Improper Validation of Certificate Expiration)
- https://letsencrypt.org/docs/certificate-compatibility/
- https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html
```

**Contoh enrichment `cve_ojs`:**
```
remediation_steps:
1. Baca advisory keamanan resmi untuk {cve_id} di https://nvd.nist.gov/vuln/detail/{cve_id}
2. Identifikasi versi OJS yang sudah memperbaiki kerentanan ini dari advisory PKP.
3. Backup database dan semua file OJS sebelum upgrade: pg_dump ojsdb > backup.sql && tar -czf ojs-backup.tar.gz /path/to/ojs
4. Download versi OJS terbaru dari https://pkp.sfu.ca/ojs/ojs_download/
5. Ikuti panduan upgrade resmi PKP: https://docs.pkp.sfu.ca/dev/upgrade-guide/
6. Setelah upgrade, jalankan php tools/upgrade.php upgrade dari direktori OJS.
7. Verifikasi fungsionalitas jurnal setelah upgrade, lalu jalankan ulang scan untuk konfirmasi CVE sudah resolved.

references:
- https://nvd.nist.gov/vuln/detail/{cve_id}  (NVD Advisory)
- https://pkp.sfu.ca/category/news/announcements/releases/ (PKP Security Releases)
- https://forum.pkp.sfu.ca/c/questions-and-answers/security/  (PKP Security Forum)
- https://docs.pkp.sfu.ca/dev/upgrade-guide/ (OJS Upgrade Guide)
```

---

### 3.5 Propagasi `module_errors` ke `scan_jobs`

**Di `workers/internal_bot.py`:**

Setiap modul internal scanner dijalankan dalam try-except. Jika modul gagal, error dicatat ke dict `module_errors` yang disimpan ke DB setelah semua modul selesai.

```python
module_errors = {}

# Contoh per modul (file_integrity):
try:
    fi_data = plugin_audit_data.get("file_integrity", {})
    if fi_data.get("status") == "skipped":
        module_errors["file_integrity"] = fi_data.get("reason", "checksums_unavailable")
    else:
        findings += scan_file_integrity(fi_data)
except Exception as e:
    module_errors["file_integrity"] = str(e)[:100]

# Simpan setelah semua modul:
job.module_errors = json.dumps(module_errors) if module_errors else None
```

**Di `workers/external_bot.py`:**

Sama — setiap scanner function di-wrap try-except, error dicatat ke `module_errors` dengan key nama modul. Contoh:

```python
try:
    ssl_findings = await run_in_executor(scan_ssl, hostname)
    findings += ssl_findings
except Exception as e:
    module_errors["ssl"] = str(e)[:100]
```

**Module key names (harus konsisten antara backend dan frontend):**

| Key | Scanner |
|---|---|
| `fingerprint` | FingerprintScanner (internal) |
| `config` | ConfigScanner |
| `plugins` | PluginAuditor |
| `rbac` | RbacAuditor |
| `file_integrity` | FileIntegrityChecker |
| `content` | ContentInjectionDetector |
| `fingerprint_ext` | External fingerprinter |
| `ssl` | SSL/TLS + HTTP redirect analyzer |
| `headers` | Header checker |
| `cookies` | Cookie analyzer |
| `vulnerabilities` | Vuln prober (XSS, SQLi, path traversal) |
| `open_dirs` | Open directory detector |
| `cve` | CVE matcher |
| `endpoints` | Endpoint checker |

---

## 4. OJS Version Propagation

### 4.1 Internal Scan — `workers/internal_bot.py`

Setelah `process_plugin_data_task` menerima callback dari plugin, fingerprint data sudah ada di payload (`fingerprint.ojs_version`). Worker perbarui `ojs_targets.ojs_version`:

```python
ojs_version = plugin_audit_data.get("fingerprint", {}).get("ojs_version")
if ojs_version and isinstance(ojs_version, str):
    target = await session.get(OJSTarget, target_id)
    if target and target.ojs_version != ojs_version:
        target.ojs_version = ojs_version
```

### 4.2 External Scan — `workers/external_bot.py`

`scan_fingerprint()` sudah return `(version, findings)`. Simpan version ke `ojs_targets.ojs_version` setelah fingerprint selesai:

```python
version, fp_findings = await scan_fingerprint(target.url)
if version:
    target.ojs_version = version
    await session.flush()
findings += fp_findings
```

### 4.3 Frontend — Targets Detail Page (`app/(dashboard)/targets/[id]/page.tsx`)

Tampilkan `ojs_version` dari `OJSTarget` API response. Jika `null`, tampilkan pesan ajakan scan.

```tsx
<div className="flex items-center gap-2">
  <span className="text-slate-500 text-sm">Versi OJS:</span>
  {target.ojs_version ? (
    <span className="text-xs font-mono bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2 py-0.5 rounded">
      {target.ojs_version}
    </span>
  ) : (
    <span className="text-slate-500 text-xs">Belum terdeteksi — jalankan scan untuk mendeteksi</span>
  )}
</div>
```

---

## 5. Redesign Halaman Vulnerability Report

### 5.1 Struktur Halaman Baru

```
┌─────────────────────────────────────────────────────────────────┐
│  Laporan Keamanan                                               │
│  Temuan kerentanan dan rencana perbaikan                        │
├─────────────────────────────────────────────────────────────────┤
│  [Scan Selector — tidak berubah]                                │
├─────────────────────────────────────────────────────────────────┤
│  [Scan Summary Card — tidak berubah]                            │
├─────────────────────────────────────────────────────────────────┤
│  STATUS PER MODUL SCANNER                                       │
│                                                                 │
│  ┌── SCAN INTERNAL ──────────────────────────────────────────┐  │
│  │  Fingerprint OJS  ℹ️ Info (versi terdeteksi)              │  │
│  │  Konfigurasi      🔴 2 Ditemukan (Kritis)                 │  │
│  │  Audit Plugin     🟡 1 Ditemukan (Sedang)                 │  │
│  │  Akses & Hak Akun ✅ Tidak Ditemukan                      │  │
│  │  Integritas File  🔴 3 Ditemukan (Kritis)                 │  │
│  │  Konten Injeksi   ✅ Tidak Ditemukan                      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌── SCAN EKSTERNAL ─────────────────────────────────────────┐  │
│  │  Fingerprint Ext  🟡 1 Ditemukan (Sedang)                 │  │
│  │  SSL/TLS          🔴 1 Ditemukan (Kritis)                 │  │
│  │  HTTP Headers     🟡 2 Ditemukan (Sedang)                 │  │
│  │  Cookie Keamanan  ✅ Tidak Ditemukan                      │  │
│  │  Kerentanan Aktif ✅ Tidak Ditemukan                      │  │
│  │  Direktori Sensitif 🔴 1 Ditemukan (Kritis)              │  │
│  │  CVE Database     ✅ Tidak Ditemukan                      │  │
│  │  Endpoint Publik  ℹ️ Info (OAI-PMH aktif)                │  │
│  └───────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│  DETAIL TEMUAN                                                  │
│  [Filter: Semua(10) | Kritis(4) | Berbahaya(3) | Sedang(3)]    │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 🔴 KRITIS  CVSS 9.8                     [Internal] [▼]   │   │
│  │ eval(base64) Injection — Indikator Kompromi              │   │
│  │ content · OWASP A03:2021                                 │   │
│  ├──────────────────────────────────────────────────────────┤   │
│  │ (expanded)                                               │   │
│  │ Deskripsi: ...                                           │   │
│  │                                                          │   │
│  │ Path Terpengaruh: article/142                            │   │
│  │                                                          │   │
│  │ Bukti: pattern=eval(base64... ditemukan di field abstract│   │
│  │                                                          │   │
│  │ Langkah Perbaikan:                                       │   │
│  │  1. SEGERA: Pertimbangkan mengisolasi server...          │   │
│  │  2. Identifikasi lokasi persis dari field affected_path  │   │
│  │  3. Hapus konten berbahaya dari database OJS...          │   │
│  │  4. Audit seluruh file PHP di server: find ...           │   │
│  │  5. Periksa log akses web server...                      │   │
│  │                                                          │   │
│  │ Referensi:                                               │   │
│  │  • https://owasp.org/Top10/A03_2021-Injection/          │   │
│  │  • https://cwe.mitre.org/data/definitions/94.html       │   │
│  │  • https://cwe.mitre.org/data/definitions/506.html      │   │
│  │                                                          │   │
│  │ CVSS: 9.8 · OWASP: A03:2021-Injection                   │   │
│  │                          [Tandai False Positive]         │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  [< Prev]  Halaman 1 / 3  [Next >]                             │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Logika Status Per Modul — File Baru `lib/scanner-modules.ts`

```typescript
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
```

**Logika status per modul:**

```typescript
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

**Visual per status di ModuleStatusGrid:**

| Status | Icon | Label | Style |
|---|---|---|---|
| `found_critical` | 🔴 | "N Ditemukan (Kritis)" | `text-red-400 bg-red-500/10 border-red-500/20` |
| `found_high` | 🟠 | "N Ditemukan (Berbahaya)" | `text-orange-400 bg-orange-500/10 border-orange-500/20` |
| `found_medium` | 🟡 | "N Ditemukan (Sedang)" | `text-yellow-400 bg-yellow-500/10 border-yellow-500/20` |
| `found_low` | 🔵 | "N Ditemukan (Rendah)" | `text-blue-400 bg-blue-500/10 border-blue-500/20` |
| `clean` | ✅ | "Tidak Ditemukan" | `text-green-400 bg-green-500/10 border-green-500/20` |
| `error` | ⚠️ | "Gagal" (+ tooltip error) | `text-slate-400 bg-slate-500/10 border-slate-500/20` |
| `info` | ℹ️ | "Info" | `text-slate-300 bg-slate-500/10 border-slate-500/20` |
| `skipped` | — | (tidak dirender) | hidden |

**Interaksi:** klik module card → auto-filter findings section ke modul tersebut (set `filterModule` state).

### 5.3 Enhanced `FindingCard`

Perubahan pada component `FindingCard`:

1. **Remediation:** jika `remediation_steps.length > 0` → render `<ol>` bernomor; fallback ke `remediation` string lama jika kosong.
2. **References:** section baru di bawah remediation, render sebagai daftar link clickable dengan `target="_blank" rel="noopener noreferrer"`.
3. **Category badge:** chip "Internal" / "Eksternal" di header card (dari field `category`).
4. **CVSS badge:** tetap ada, tidak berubah.

```tsx
{/* Remediation — numbered steps jika tersedia */}
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

{/* References */}
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

### 5.4 Paginasi Findings

Jika total visible findings > 20 → tampilkan 10 per halaman dengan tombol Prev/Next. State `page` dan `filterModule` disimpan bersama `filterSeverity`.

---

## 6. Daftar File yang Dimodifikasi

### Backend

| File | Jenis Perubahan |
|---|---|
| `migrations/versions/007_scanner_enrichment.py` | BARU — tambah 2 kolom ke `scan_findings`, 1 kolom ke `scan_jobs` |
| `app/scanners/models.py` | Tambah `references`, `remediation_steps` ke `FindingResult`; 5 entry CVSS baru |
| `app/scanners/external/header_checker.py` | Tambah 3 header baru + enrichment semua finding |
| `app/scanners/external/cookie_analyzer.py` | Tambah cek HttpOnly + SameSite; enrichment semua finding |
| `app/scanners/external/ssl_analyzer.py` | Enrichment semua finding |
| `app/scanners/external/fingerprinter.py` | Enrichment semua finding |
| `app/scanners/external/vuln_prober.py` | Enrichment semua finding |
| `app/scanners/external/open_dir_detector.py` | Enrichment semua finding |
| `app/scanners/external/cve_matcher.py` | Enrichment + references ke NVD per CVE ID |
| `app/scanners/external/endpoint_checker.py` | Enrichment semua finding |
| `app/scanners/internal/config_scanner.py` | Enrichment semua finding |
| `app/scanners/internal/plugin_auditor.py` | Enrichment semua finding |
| `app/scanners/internal/rbac_auditor.py` | Enrichment semua finding |
| `app/scanners/internal/file_integrity.py` | Enrichment semua finding |
| `app/scanners/internal/content_detector.py` | Enrichment semua finding |
| `app/workers/internal_bot.py` | Propagate `ojs_version`; catat `module_errors` ke job |
| `app/workers/external_bot.py` | Propagate `ojs_version`; catat `module_errors` ke job |
| `app/models/scan_job.py` | Tambah kolom `module_errors` |
| `app/models/scan_finding.py` | Tambah kolom `references`, `remediation_steps` |
| `app/schemas/scans.py` | Update `ScanFindingOut` dan `ScanJobOut` |

### Frontend

| File | Jenis Perubahan |
|---|---|
| `types/api.ts` | Tambah field ke `ScanFinding` dan `ScanJob` |
| `lib/scanner-modules.ts` | BARU — mapping modul, finding types, label, helper `getModuleStatus` |
| `app/(dashboard)/vulnerability-report/page.tsx` | Redesign: ModuleStatusGrid, enhanced FindingCard, filter per modul, paginasi |
| `app/(dashboard)/targets/[id]/page.tsx` | Tampilkan `ojs_version` dengan badge dan fallback |

---

## 7. Error Handling & Edge Cases

| Skenario | Perilaku |
|---|---|
| Scan type `internal` | Modul external (`fingerprint_ext`, `ssl`, dll.) tidak tampil di grid |
| Scan type `external` | Modul internal (`config`, `rbac`, dll.) tidak tampil di grid |
| Plugin unreachable — semua internal modul gagal | `module_errors` berisi semua internal keys; grid tampilkan semua baris "Gagal" dengan tooltip error message |
| `module_errors` null (scan lama sebelum migration 007) | Frontend treat sebagai `{}` — tidak ada error state, modul dianggap berjalan normal |
| `remediation_steps` kosong (finding lama) | Fallback ke `remediation` string — tidak ada perubahan tampilan |
| `references` kosong (finding lama) | Section referensi tidak dirender |
| CVE scan: NVD API rate limit | `module_errors["cve"] = "nvd_rate_limited"` — tampil "Gagal (Rate Limited)" di grid |
| File integrity skipped (checksums tidak tersedia) | Plugin return `{status: "skipped", reason: "..."}` → `module_errors["file_integrity"] = reason` |
| OJS version tidak terdeteksi di fingerprint | `ojs_version` tetap null di target → tampil "Belum terdeteksi" |
| `scan_type = 'full'` | Semua 14 modul tampil di grid |

---

## 8. Kriteria Penerimaan

- [ ] Semua 29 finding types (24 existing + 5 baru) punya `references` minimal 2 URL dan `remediation_steps` minimal 3 langkah
- [ ] Header checker mengecek 6 header: CSP, HSTS, X-Frame-Options, Referrer-Policy, Permissions-Policy, X-Content-Type-Options
- [ ] Cookie analyzer mengecek 3 flag per cookie: Secure, HttpOnly, SameSite
- [ ] Migration 007 berhasil diapply tanpa downtime (kolom nullable, tidak breaking)
- [ ] `module_errors` tersimpan ke `scan_jobs` setelah scan selesai — hanya berisi modul yang gagal
- [ ] `ojs_targets.ojs_version` terperbarui setelah scan yang berhasil mendeteksi versi
- [ ] Halaman targets detail menampilkan versi OJS dengan badge atau teks "Belum terdeteksi"
- [ ] Vulnerability report menampilkan ModuleStatusGrid di atas findings list
- [ ] ModuleStatusGrid hanya menampilkan modul yang relevan dengan `scan_type` aktif
- [ ] Status per modul: Ditemukan (warna sesuai severity tertinggi) / Tidak Ditemukan / Gagal / Info tampil benar
- [ ] Klik module card di grid → auto-filter findings section ke modul tersebut
- [ ] FindingCard expanded menampilkan langkah perbaikan bernomor (jika `remediation_steps` tersedia)
- [ ] FindingCard expanded menampilkan referensi sebagai link clickable (jika `references` tersedia)
- [ ] Paginasi aktif dan berfungsi jika visible findings > 20
- [ ] Scan lama (tanpa `references`/`remediation_steps`) tetap tampil dengan fallback ke string lama

---

*Spec ini mencakup semua perubahan yang disetujui dalam sesi brainstorming 2026-06-07.*
