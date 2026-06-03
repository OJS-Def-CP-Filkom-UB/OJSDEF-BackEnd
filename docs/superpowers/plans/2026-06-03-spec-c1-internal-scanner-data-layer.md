# Spec C-1 — Internal Scanner Data Layer Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Perbaiki pipeline data internal scanner yang sepenuhnya broken — data path mismatch, format mismatch semua modul, OJS config key salah, ContentInjectionDetector tidak scan settings, dan checksums palsu.

**Architecture:** Python adapts to PHP. Rewrite 5 Python scanner functions agar native menerima format PHP output. Fix OJS config key names di PHP. Extend ContentInjectionDetector untuk scan journal/site settings. Ganti checksums placeholder dengan real SHA-256 dari PKP GitHub.

**Tech Stack:** Python/FastAPI, Celery, PHP 7.4+, OJS 3.3.x/3.4.x

**Catatan Testing:** TIDAK ADA test lokal. Gunakan `python -m py_compile` untuk syntax check Python, `php -l` untuk PHP. Test fungsional dilakukan manual di VPS setelah deploy.

**Parallel Execution Note:**
- `app/scanners/models.py` juga dimodifikasi oleh Plan C-2. Keduanya menambah key berbeda ke `CVSS_SCORES` dict — tidak ada conflict jika dikerjakan paralel, tapi akan ada merge conflict di git. Resolve dengan menggabungkan kedua blok entry.
- Plugin ZIP: plan ini rebuild ZIP setelah PHP changes. Jika berjalan paralel dengan C-3 (yang juga mengubah OjsdefPlugin.php), subagent yang selesai **terakhir** harus rebuild ZIP ulang setelah semua commits.

---

## File Map

| File | Aksi | Repo |
|------|------|------|
| `app/scanners/internal/db_security.py` | DELETE | BackEnd |
| `app/workers/internal_bot.py` | Edit — fix data path | BackEnd |
| `app/scanners/models.py` | Edit — tambah CVSS entries | BackEnd |
| `app/scanners/internal/config_scanner.py` | Rewrite | BackEnd |
| `app/scanners/internal/rbac_auditor.py` | Rewrite | BackEnd |
| `app/scanners/internal/file_integrity.py` | Rewrite | BackEnd |
| `app/scanners/internal/content_detector.py` | Rewrite | BackEnd |
| `app/scanners/internal/plugin_auditor.py` | Rewrite | BackEnd |
| `app/routers/plugin_callback.py` | Edit — real checksums | BackEnd |
| `ojsdef/classes/scanners/ConfigScanner.php` | Edit — fix OJS keys | Plugin |
| `ojsdef/classes/scanners/ContentInjectionDetector.php` | Edit — settings scan | Plugin |
| `ojsdef-plugin-1.0.1.zip` | Rebuild | Plugin |

BackEnd path: `D:\Kuliahku\Capstone\workspace\OJSDEF-BackEnd\`
Plugin path: `D:\Kuliahku\Capstone\workspace\OJSDEF-Plugin\`

---

### Task 1: Hapus db_security.py + Fix Data Path di internal_bot.py

**Context:** `db_security.py` adalah orphaned scanner — PHP tidak pernah mengirim `db_config` key. Fungsionalitasnya (DB password check) sudah dipindah ke `config_scanner.py`. `internal_bot.py` membaca data dari path yang salah: `data.get("config")` padahal data ada di `data["results"]["config"]`.

**Files:**
- Delete: `app/scanners/internal/db_security.py`
- Modify: `app/workers/internal_bot.py`

- [ ] **Step 1: Hapus db_security.py**

Hapus file `app/scanners/internal/db_security.py`.

- [ ] **Step 2: Hapus import scan_db_security dari internal_bot.py**

Buka `app/workers/internal_bot.py`. Temukan dan hapus baris:
```python
from app.scanners.internal.db_security import scan_db_security
```

- [ ] **Step 3: Fix data path di _run_internal_scan**

Dalam fungsi `_run_internal_scan`, temukan blok scanner calls. Ganti dari:

```python
    config_findings    = scan_config(data.get("config", {}))
    plugin_findings    = scan_plugins(data.get("plugins", []))
    rbac_findings      = scan_rbac(data.get("users", []))
    file_findings      = scan_file_integrity(data.get("file_integrity", {}))
    content_findings   = scan_content(data.get("articles", []))
    db_findings        = scan_db_security(data.get("db_config", {}))

    all_findings = (
        config_findings + plugin_findings + rbac_findings
        + file_findings + content_findings + db_findings
    )
```

Menjadi:

```python
    results = data.get("results", {})

    config_findings  = scan_config(results.get("config", {}))
    plugin_findings  = scan_plugins(results.get("plugins", {}))
    rbac_findings    = scan_rbac(results.get("rbac", {}))
    file_findings    = scan_file_integrity(results.get("file_integrity", {}))
    content_findings = scan_content(results.get("content", {}))

    all_findings = (
        config_findings + plugin_findings + rbac_findings
        + file_findings + content_findings
    )
```

- [ ] **Step 4: Syntax check**

```bash
cd D:\Kuliahku\Capstone\workspace\OJSDEF-BackEnd
python -m py_compile app/workers/internal_bot.py && echo OK
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add app/workers/internal_bot.py
git rm app/scanners/internal/db_security.py
git commit -m "fix(c1): fix internal_bot data path, remove orphaned db_security scanner"
```

---

### Task 2: Update models.py — Tambah CVSS Entries

**Context:** `make_finding(finding_type, ...)` lookup `cvss_score` dari `CVSS_SCORES` dict. Semua finding type baru di Tasks 3-7 harus ada di dict ini. Juga update `modified_core_file` dari 8.5 → 9.1 sesuai spec K-4.

**Files:**
- Modify: `app/scanners/models.py`

- [ ] **Step 1: Update modified_core_file dan tambah entries baru**

Buka `app/scanners/models.py`. Temukan dict `CVSS_SCORES`. Lakukan dua perubahan:

**Perubahan 1:** Update nilai `modified_core_file` dari `8.5` menjadi `9.1`.

**Perubahan 2:** Tambahkan blok entry baru di akhir dict (sebelum kurung kurawal `}`):

```python
    # New internal scanner finding types (C-1)
    "debug_mode_active":           9.8,
    "force_ssl_disabled":          8.1,
    "smtp_no_auth":                5.3,
    "db_password_empty":           8.0,
    "api_key_too_short":           5.0,
    "multiple_superadmin":         7.2,
    "inactive_high_priv_account":  5.0,
    "modified_plugin_file":        7.8,
    "gambling_content":            9.5,
    "eval_base64_injection":       9.8,
    "hidden_iframe_injection":     8.3,
    "phishing_tld_link":           7.5,
    "js_redirect_injection":       6.1,
    "disabled_plugins_installed":  4.3,
    "excessive_active_plugins":    2.0,
```

- [ ] **Step 2: Syntax check**

```bash
python -m py_compile app/scanners/models.py && echo OK
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/scanners/models.py
git commit -m "fix(c1): add internal scanner CVSS entries, update modified_core_file to 9.1"
```

---

### Task 3: Rewrite config_scanner.py

**Context:** Versi lama cek `config.get("debug")` (key salah) dan `config.get("database", {}).get("password")` (format salah). PHP ConfigScanner mengirim flat dict dengan 13 fields. Deteksi: K-1 (debug), B-1 (force_ssl), P-2 (smtp), db_password_empty, api_key_too_short.

**Files:**
- Rewrite: `app/scanners/internal/config_scanner.py`

- [ ] **Step 1: Tulis ulang seluruh config_scanner.py**

```python
from app.scanners.models import FindingResult, make_finding


def scan_config(config: dict) -> list[FindingResult]:
    """
    Analisis output PHP ConfigScanner. Format input (flat dict):
    {display_errors, show_errors, show_stacktrace, api_key_secret_length,
     force_ssl, allowed_hosts_set, installed, smtp_enabled, smtp_auth_enabled,
     smtp_password_set, db_driver, db_host, db_password_empty}
    """
    findings = []

    # K-1: Debug mode aktif (CVSS 9.8 — Critical)
    if (config.get("display_errors")
            or config.get("show_errors")
            or config.get("show_stacktrace")):
        findings.append(make_finding(
            "debug_mode_active",
            category="internal",
            title="Mode Debug OJS Aktif",
            description=(
                "OJS berjalan dalam mode debug, mengekspos stack trace PHP, "
                "query SQL, dan path internal kepada semua pengunjung saat terjadi error."
            ),
            affected_path="config.inc.php [debug]",
            evidence="display_errors=On atau show_errors=On atau show_stacktrace=On",
            remediation=(
                "Set `display_errors = Off` dan `show_stacktrace = Off` di config.inc.php. "
                "Restart web server setelah perubahan."
            ),
        ))

    # B-1: Force SSL dimatikan (CVSS 8.1 — High)
    if not config.get("force_ssl", True):
        findings.append(make_finding(
            "force_ssl_disabled",
            category="internal",
            title="Force SSL Dimatikan di Konfigurasi OJS",
            description=(
                "OJS tidak memaksa HTTPS secara native. "
                "Kredensial login dapat disadap jika HTTPS redirect tidak dikonfigurasi di web server."
            ),
            affected_path="config.inc.php [security]",
            evidence="force_ssl = Off",
            remediation=(
                "Set `force_login_ssl = On` di config.inc.php, "
                "atau pastikan Nginx sudah mengkonfigurasi redirect HTTP ke HTTPS."
            ),
        ))

    # P-2: SMTP aktif tanpa autentikasi (CVSS 5.3 — Medium)
    if (config.get("smtp_enabled")
            and not config.get("smtp_auth_enabled")
            and not config.get("smtp_password_set")):
        findings.append(make_finding(
            "smtp_no_auth",
            category="internal",
            title="SMTP Aktif Tanpa Autentikasi",
            description=(
                "Server email dikonfigurasi tanpa autentikasi. "
                "Server SMTP terbuka dapat disalahgunakan untuk relay spam "
                "atau intercept email sistem (password reset, notifikasi review)."
            ),
            affected_path="config.inc.php [email]",
            evidence="smtp = On, smtp_auth tidak dikonfigurasi",
            remediation=(
                "Tambahkan smtp_auth, smtp_username, dan smtp_password "
                "di konfigurasi email config.inc.php."
            ),
        ))

    # DB password kosong (CVSS 8.0 — High)
    if config.get("db_password_empty"):
        findings.append(make_finding(
            "db_password_empty",
            category="internal",
            title="Password Database OJS Kosong",
            description=(
                "Koneksi database OJS tidak menggunakan password. "
                "Database dapat diakses tanpa autentikasi dari proses lokal."
            ),
            affected_path="config.inc.php [database]",
            evidence="database.password = (kosong)",
            remediation=(
                "Set password database yang kuat di config.inc.php "
                "atau via environment variable OJS_DB_PASSWORD."
            ),
        ))

    # API key secret terlalu pendek (CVSS 5.0 — Medium)
    key_len = config.get("api_key_secret_length", 32)
    if isinstance(key_len, int) and 0 < key_len < 32:
        findings.append(make_finding(
            "api_key_too_short",
            category="internal",
            title="API Key Secret OJS Terlalu Pendek",
            description=(
                f"api_key_secret di config OJS hanya {key_len} karakter "
                "(minimum yang disarankan adalah 32 karakter)."
            ),
            affected_path="config.inc.php [general]",
            evidence=f"api_key_secret length = {key_len}",
            remediation="Set api_key_secret minimal 32 karakter acak di config.inc.php.",
        ))

    return findings
```

- [ ] **Step 2: Syntax check**

```bash
python -m py_compile app/scanners/internal/config_scanner.py && echo OK
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/scanners/internal/config_scanner.py
git commit -m "fix(c1): rewrite config_scanner to match PHP ConfigScanner flat dict format"
```

---

### Task 4: Rewrite rbac_auditor.py

**Context:** Versi lama mengekspektasi list user objects dengan `username` dan `roles[]`. PHP RbacAuditor mengirim summary dict: `{superadmin_count, multiple_superadmin, inactive_high_priv_users: [{user_id, last_login}]}`. Deteksi B-4 (multiple superadmin) dan P-3 (inactive admin).

**Files:**
- Rewrite: `app/scanners/internal/rbac_auditor.py`

- [ ] **Step 1: Tulis ulang seluruh rbac_auditor.py**

```python
from app.scanners.models import FindingResult, make_finding


def scan_rbac(rbac: dict) -> list[FindingResult]:
    """
    Analisis output PHP RbacAuditor. Format input:
    {total_users, superadmin_count, multiple_superadmin: bool,
     inactive_high_priv_count, inactive_high_priv_users: [{user_id, last_login}]}
    """
    findings = []

    # B-4: Multiple superadmin (CVSS 7.2 — High)
    if rbac.get("multiple_superadmin"):
        count = rbac.get("superadmin_count", 0)
        findings.append(make_finding(
            "multiple_superadmin",
            category="internal",
            title=f"Terdapat {count} Akun Site Administrator",
            description=(
                f"Ada {count} akun Site Administrator aktif. "
                "Setiap akun superadmin yang tidak diperlukan memperluas attack surface. "
                "Prinsip least privilege dilanggar."
            ),
            affected_path="users/site_administrators",
            evidence=f"superadmin_count = {count}",
            remediation=(
                "Pertahankan hanya 1 akun Site Administrator aktif. "
                "Hapus atau downgrade role akun lainnya ke Journal Manager."
            ),
        ))

    # P-3: Akun high-privilege tidak aktif > 1 tahun (CVSS 5.0 — Medium)
    for user in rbac.get("inactive_high_priv_users", []):
        uid  = user.get("user_id", "unknown")
        last = user.get("last_login", "tidak diketahui")
        findings.append(make_finding(
            "inactive_high_priv_account",
            category="internal",
            title=f"Akun Admin Tidak Aktif > 1 Tahun (ID: {uid})",
            description=(
                f"Akun dengan hak akses tinggi (user ID: {uid}) "
                f"terakhir login pada {last}. "
                "Akun tidak aktif dapat menjadi target credential stuffing "
                "tanpa diketahui pemiliknya."
            ),
            affected_path=f"users/{uid}",
            evidence=f"user_id={uid}, last_login={last}",
            remediation=(
                f"Nonaktifkan atau hapus akun admin (ID: {uid}) "
                "yang tidak digunakan lebih dari 1 tahun."
            ),
        ))

    return findings
```

- [ ] **Step 2: Syntax check**

```bash
python -m py_compile app/scanners/internal/rbac_auditor.py && echo OK
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/scanners/internal/rbac_auditor.py
git commit -m "fix(c1): rewrite rbac_auditor to match PHP RbacAuditor summary dict format"
```

---

### Task 5: Rewrite file_integrity.py

**Context:** Versi lama mengekspektasi key `modified_core_files[]`, `unknown_files[]`, `missing_core_files[]`. PHP FileIntegrityChecker mengirim `{status, findings: [{path, status: "modified"|"missing", local_hash}]}`. Deteksi K-4 (core file, path tidak dimulai `plugins/`) dan B-6 (plugin file, path dimulai `plugins/`).

**Files:**
- Rewrite: `app/scanners/internal/file_integrity.py`

- [ ] **Step 1: Tulis ulang seluruh file_integrity.py**

```python
from app.scanners.models import FindingResult, make_finding


def scan_file_integrity(fi: dict) -> list[FindingResult]:
    """
    Analisis output PHP FileIntegrityChecker. Format input:
    {status: "completed"|"skipped", total_checked, modified, missing,
     findings: [{path, status: "modified"|"missing", local_hash}]}
    Jika status != "completed" (checksums tidak tersedia), return [].
    """
    findings = []

    if fi.get("status") != "completed":
        return findings

    for f in fi.get("findings", []):
        path   = f.get("path", "")
        status = f.get("status", "")

        if status == "modified":
            is_plugin = path.startswith("plugins/")
            ftype     = "modified_plugin_file" if is_plugin else "modified_core_file"
            label     = "Plugin" if is_plugin else "File Core OJS"
            findings.append(make_finding(
                ftype,
                category="internal",
                title=f"{label} Dimodifikasi: {path}",
                description=(
                    f"File {path} telah dimodifikasi dari distribusi resmi PKP. "
                    "Ini dapat mengindikasikan injeksi kode berbahaya atau kompromi sistem."
                ),
                affected_path=path,
                evidence=f"checksum mismatch: {path}",
                remediation=(
                    "Bandingkan file dengan versi resmi OJS dari PKP GitHub releases. "
                    "Restore dari backup instalasi yang bersih jika perlu."
                ),
            ))

        elif status == "missing":
            findings.append(make_finding(
                "missing_core_file",
                category="internal",
                title=f"File Core OJS Hilang: {path}",
                description=(
                    f"File inti OJS {path} tidak ditemukan di server. "
                    "File yang hilang dapat menyebabkan error atau kerentanan keamanan."
                ),
                affected_path=path,
                evidence=f"file tidak ada: {path}",
                remediation=(
                    "Restore file dari paket OJS versi yang sesuai di PKP GitHub releases."
                ),
            ))

    return findings
```

- [ ] **Step 2: Syntax check**

```bash
python -m py_compile app/scanners/internal/file_integrity.py && echo OK
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/scanners/internal/file_integrity.py
git commit -m "fix(c1): rewrite file_integrity to consume PHP FileIntegrityChecker findings array"
```

---

### Task 6: Rewrite content_detector.py

**Context:** Versi lama mencoba re-scan raw artikel text. PHP ContentInjectionDetector sudah scan dan mengirim hasil `{detections: [{submission_id, field, pattern, excerpt}]}`. Pattern values: `gambling_keyword`, `base64_eval`, `hidden_iframe`, `phishing_tld`, `js_redirect`. Field untuk settings: `journal.about`, `journal.footer`, `journal.for_authors`.

**Files:**
- Rewrite: `app/scanners/internal/content_detector.py`

- [ ] **Step 1: Tulis ulang seluruh content_detector.py**

```python
from app.scanners.models import FindingResult, make_finding

PATTERN_FINDINGS: dict[str, tuple[str, str, str]] = {
    "gambling_keyword": (
        "gambling_content",
        "Konten Judi/Spam Ditemukan",
        "Hapus konten yang mengandung kata kunci judi online. "
        "Audit akses akun editor dan tinjau seluruh konten jurnal.",
    ),
    "base64_eval": (
        "eval_base64_injection",
        "Injeksi eval(base64) Ditemukan — Indikator Kompromi",
        "Hapus segera script berbahaya dari konten. "
        "Lakukan audit menyeluruh pada seluruh file server dan database.",
    ),
    "hidden_iframe": (
        "hidden_iframe_injection",
        "iFrame Tersembunyi Ditemukan",
        "Hapus tag iframe dari konten. "
        "Aktifkan Content-Security-Policy untuk memblokir iframe eksternal.",
    ),
    "phishing_tld": (
        "phishing_tld_link",
        "Link dengan TLD Berisiko Tinggi Ditemukan",
        "Hapus atau ganti link dengan domain yang legitimate (.com, .ac.id, .edu). "
        "Verifikasi semua link eksternal di konten jurnal.",
    ),
    "js_redirect": (
        "js_redirect_injection",
        "JavaScript Redirect Tersembunyi Ditemukan",
        "Hapus script redirect dari konten. "
        "Audit semua custom HTML di settings OJS.",
    ),
}


def scan_content(content: dict) -> list[FindingResult]:
    """
    Analisis output PHP ContentInjectionDetector. Format input:
    {total_scanned, affected_count,
     detections: [{submission_id: int|null, field: str, pattern: str, excerpt: str}]}
    submission_id=null berarti deteksi dari settings (journal.about, journal.footer, dll.)
    """
    findings = []

    for detection in content.get("detections", []):
        pattern = detection.get("pattern", "")
        field   = detection.get("field", "unknown")
        excerpt = detection.get("excerpt", "")
        sub_id  = detection.get("submission_id")

        if pattern not in PATTERN_FINDINGS:
            continue

        ftype, title, remediation = PATTERN_FINDINGS[pattern]
        location = f"article/{sub_id}" if sub_id is not None else f"settings/{field}"

        findings.append(make_finding(
            ftype,
            category="internal",
            title=title,
            description=f"Pattern berbahaya '{pattern}' ditemukan di {location}.",
            affected_path=location,
            evidence=excerpt[:200] if excerpt else f"pattern={pattern}",
            remediation=remediation,
        ))

    return findings
```

- [ ] **Step 2: Syntax check**

```bash
python -m py_compile app/scanners/internal/content_detector.py && echo OK
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/scanners/internal/content_detector.py
git commit -m "fix(c1): rewrite content_detector to consume PHP detection results, support settings fields"
```

---

### Task 7: Rewrite plugin_auditor.py

**Context:** Versi lama iterasi dict sebagai list (salah tipe). PHP PluginAuditor mengirim `{total_installed, total_enabled, disabled_but_installed: [{name,...}], plugins: [...]}`. Deteksi P-4 (disabled_but_installed > 0) dan A-4 (total_enabled > 20).

**Files:**
- Rewrite: `app/scanners/internal/plugin_auditor.py`

- [ ] **Step 1: Tulis ulang seluruh plugin_auditor.py**

```python
from app.scanners.models import FindingResult, make_finding


def scan_plugins(plugins_data: dict) -> list[FindingResult]:
    """
    Analisis output PHP PluginAuditor. Format input:
    {total_installed, total_enabled,
     disabled_but_installed: [{name, category, version, enabled, path}],
     plugins: [...]}
    """
    findings = []

    total_enabled = plugins_data.get("total_enabled", 0)
    disabled      = plugins_data.get("disabled_but_installed", [])

    # P-4: Plugin terinstall tapi dinonaktifkan (CVSS 4.3 — Medium)
    if len(disabled) > 0:
        names = ", ".join(p.get("name", "?") for p in disabled[:5])
        if len(disabled) > 5:
            names += f" (+{len(disabled) - 5} lainnya)"
        findings.append(make_finding(
            "disabled_plugins_installed",
            category="internal",
            title=f"{len(disabled)} Plugin Terinstall tapi Dinonaktifkan",
            description=(
                f"Ada {len(disabled)} plugin yang masih ada di filesystem tapi tidak aktif: {names}. "
                "Plugin tidak aktif tetap mengandung kode yang bisa dieksploitasi "
                "jika memiliki kerentanan."
            ),
            affected_path="plugins/",
            evidence=f"disabled_but_installed count = {len(disabled)}: {names}",
            remediation=(
                "Uninstall plugin yang tidak diperlukan melalui OJS Plugin Gallery "
                "(Website Settings → Plugins → Plugin Gallery → Uninstall)."
            ),
        ))

    # A-4: Terlalu banyak plugin aktif — informatif (CVSS 2.0 — Low)
    if total_enabled > 20:
        findings.append(make_finding(
            "excessive_active_plugins",
            category="internal",
            title=f"{total_enabled} Plugin Aktif — Audit Disarankan",
            description=(
                f"Terdapat {total_enabled} plugin aktif. "
                "Setiap plugin menambah attack surface secara proporsional. "
                "Lakukan audit berkala untuk memastikan semua plugin benar-benar diperlukan."
            ),
            affected_path="plugins/",
            evidence=f"total_enabled = {total_enabled}",
            remediation=(
                "Nonaktifkan atau uninstall plugin yang tidak digunakan "
                "melalui OJS Plugin Gallery."
            ),
        ))

    return findings
```

- [ ] **Step 2: Syntax check**

```bash
python -m py_compile app/scanners/internal/plugin_auditor.py && echo OK
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/scanners/internal/plugin_auditor.py
git commit -m "fix(c1): rewrite plugin_auditor to match PHP PluginAuditor dict format"
```

---

### Task 8: Fix plugin_callback.py — Real Checksums

**Context:** Checksums saat ini berisi SHA-256 dari string kosong — false positive permanen di baseline. Ganti dengan real hashes dari PKP GitHub untuk `index.php` dan `config.TEMPLATE.inc.php`.

**Files:**
- Modify: `app/routers/plugin_callback.py`

- [ ] **Step 1: Dapatkan real SHA-256 hashes dari PKP GitHub**

Jalankan di terminal (tidak butuh Docker/VPS):

```bash
# OJS 3.4.0 — sesuaikan tag dengan versi yang digunakan di VPS
curl -sL "https://raw.githubusercontent.com/pkp/ojs/3_4_0-7/index.php" | sha256sum
curl -sL "https://raw.githubusercontent.com/pkp/ojs/3_4_0-7/config.TEMPLATE.inc.php" | sha256sum

# OJS 3.3.0
curl -sL "https://raw.githubusercontent.com/pkp/ojs/3_3_0-17/index.php" | sha256sum
curl -sL "https://raw.githubusercontent.com/pkp/ojs/3_3_0-17/config.TEMPLATE.inc.php" | sha256sum
```

Catat 4 nilai hash (64-character hex string sebelum spasi di output).

- [ ] **Step 2: Update CHECKSUMS dict di plugin_callback.py**

Buka `app/routers/plugin_callback.py`. Temukan dict `CHECKSUMS`. Ganti value placeholder dengan real hashes dari Step 1:

```python
CHECKSUMS: dict[str, dict[str, str]] = {
    "3_3_0": {
        "index.php":               "HASH_DARI_STEP1_3_3_0_INDEX",
        "config.TEMPLATE.inc.php": "HASH_DARI_STEP1_3_3_0_CONFIG",
    },
    "3_4_0": {
        "index.php":               "HASH_DARI_STEP1_3_4_0_INDEX",
        "config.TEMPLATE.inc.php": "HASH_DARI_STEP1_3_4_0_CONFIG",
    },
}
```

Ganti `HASH_DARI_STEP1_*` dengan 64-char hex string aktual dari Step 1.

- [ ] **Step 3: Syntax check**

```bash
python -m py_compile app/routers/plugin_callback.py && echo OK
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/routers/plugin_callback.py
git commit -m "fix(c1): replace placeholder checksums with real SHA-256 from PKP GitHub"
```

---

### Task 9: Fix ConfigScanner.php — OJS Key Names + New Fields

**Context:** PHP membaca `debug_mode` (tidak ada di OJS config.inc.php) dan tidak membaca `display_errors`, `show_stacktrace`, `smtp_enabled`. K-1 tidak bisa dideteksi tanpa fix ini. OJS config keys yang benar: `[debug] display_errors`, `[debug] show_stacktrace`, `[email] smtp`.

**Files:**
- Modify: `D:\Kuliahku\Capstone\workspace\OJSDEF-Plugin\ojsdef\classes\scanners\ConfigScanner.php`

- [ ] **Step 1: Ganti return array di method scan()**

Buka `ojsdef/classes/scanners/ConfigScanner.php`. Temukan method `scan()`. Ganti seluruh isi `return [...]` dengan:

```php
        return [
            'display_errors'        => (bool) $this->_cfg('debug',    'display_errors',  false),
            'show_errors'           => (bool) $this->_cfg('debug',    'show_errors',     false),
            'show_stacktrace'       => (bool) $this->_cfg('debug',    'show_stacktrace', false),
            'api_key_secret_length' => strlen((string) $this->_cfg('general',  'api_key_secret', '')),
            'force_ssl'             => (bool) $this->_cfg('security', 'force_ssl',       false),
            'allowed_hosts_set'     => !empty($this->_cfg('security', 'allowed_hosts',   '')),
            'installed'             => (bool) $this->_cfg('general',  'installed',       false),
            'smtp_enabled'          => (bool) $this->_cfg('email',    'smtp',            false),
            'smtp_auth_enabled'     => !empty($this->_cfg('email',    'smtp_auth',       '')),
            'smtp_password_set'     => !empty($this->_cfg('email',    'smtp_password',   '')),
            'db_driver'             => (string) $this->_cfg('database', 'driver',        ''),
            'db_host'               => (string) $this->_cfg('database', 'host',          ''),
            'db_password_empty'     => $this->_isDbPasswordEmpty(),
        ];
```

Perubahan: hapus `'debug_mode'`, tambah `'display_errors'`, `'show_stacktrace'`, `'smtp_enabled'`.

- [ ] **Step 2: PHP syntax check**

```bash
cd D:\Kuliahku\Capstone\workspace\OJSDEF-Plugin
php -l ojsdef/classes/scanners/ConfigScanner.php
```

Expected: `No syntax errors detected in ojsdef/classes/scanners/ConfigScanner.php`

- [ ] **Step 3: Commit**

```bash
git add ojsdef/classes/scanners/ConfigScanner.php
git commit -m "fix(c1): ConfigScanner reads correct OJS keys (display_errors, show_stacktrace, smtp_enabled)"
```

---

### Task 10: Extend ContentInjectionDetector.php — Settings Fields Scan

**Context:** Saat ini hanya scan article submissions via SubmissionDAO. K-2, K-3, B-2, B-3, P-1 inject ke OJS settings (About Journal, Footer, For Authors) yang tidak pernah di-scan. Tambah method `_scanContextSettings()` yang query JournalDAO untuk 3 fields tersebut.

**Files:**
- Modify: `D:\Kuliahku\Capstone\workspace\OJSDEF-Plugin\ojsdef\classes\scanners\ContentInjectionDetector.php`

- [ ] **Step 1: Tambah method _scanContextSettings()**

Buka `ojsdef/classes/scanners/ContentInjectionDetector.php`. Temukan kurung kurawal penutup class (baris `}`  terakhir). Tambahkan method berikut **sebelum** kurung penutup class:

```php
    private function _scanContextSettings(): array
    {
        $detections = [];
        if (!class_exists('DAORegistry')) return $detections;

        try {
            $journalDao = \DAORegistry::getDAO('JournalDAO');
            if (!$journalDao) return $detections;

            $journals = $journalDao->getAll();
            while ($journal = $journals->next()) {
                // OJS 3.3.x/3.4.x compatible — dua nama key per field untuk fallback versi
                $fieldsToScan = [
                    'description'       => 'journal.about',
                    'pageFooter'        => 'journal.footer',      // OJS 3.4.x key
                    'footer'            => 'journal.footer',      // OJS 3.3.x fallback
                    'authorInformation' => 'journal.for_authors', // OJS 3.3.x key
                    'forAuthors'        => 'journal.for_authors', // OJS 3.4.x key
                ];
                $scannedLabels = [];

                foreach ($fieldsToScan as $dataKey => $label) {
                    if (in_array($label, $scannedLabels, true)) continue; // cegah duplikat
                    $value = $journal->getLocalizedData($dataKey);
                    if (empty($value)) continue;

                    $scannedLabels[] = $label;
                    foreach ($this->patterns as $patternName => $regex) {
                        if (preg_match($regex, $value, $matches)) {
                            $detections[] = [
                                'submission_id' => null,
                                'field'         => $label,
                                'pattern'       => $patternName,
                                'excerpt'       => substr($matches[0], 0, 100),
                            ];
                        }
                    }
                }
            }
        } catch (\Throwable $e) {
            // silent — settings scan gagal tidak hentikan modul lain
        }

        return $detections;
    }
```

- [ ] **Step 2: Update method scan() untuk merge hasil settings**

Temukan method `scan()`. Cari bagian akhirnya yang mengandung:

```php
        $affectedIds = array_unique(array_column($detections, 'submission_id'));

        return [
            'total_scanned'  => $totalScanned,
            'affected_count' => count($affectedIds),
            'detections'     => $detections,
        ];
```

Ganti dengan:

```php
        // Gabungkan dengan hasil scan settings fields
        $detections = array_merge($detections, $this->_scanContextSettings());

        // affected_count: unik per lokasi (submission_id atau settings field)
        $affectedLocations = array_unique(array_map(
            function ($d) { return $d['submission_id'] ?? $d['field']; },
            $detections
        ));

        return [
            'total_scanned'  => $totalScanned,
            'affected_count' => count($affectedLocations),
            'detections'     => $detections,
        ];
```

- [ ] **Step 3: PHP syntax check**

```bash
php -l ojsdef/classes/scanners/ContentInjectionDetector.php
```

Expected: `No syntax errors detected in ojsdef/classes/scanners/ContentInjectionDetector.php`

- [ ] **Step 4: Commit PHP source**

```bash
git add ojsdef/classes/scanners/ContentInjectionDetector.php
git commit -m "fix(c1): ContentInjectionDetector scans journal.about, journal.footer, journal.for_authors"
```

---

### Task 11: Rebuild Plugin ZIP

**Context:** Semua PHP source changes sudah committed. Rebuild ZIP agar instalasi OJS mendapat versi terbaru.

**PENTING — Parallel Execution:** Jika Plan C-3 sedang berjalan paralel dan belum commit `OjsdefPlugin.php`, **tunggu C-3 selesai commit** sebelum rebuild ZIP di sini. ZIP harus mencakup semua PHP changes dari kedua plan.

**Files:**
- Rebuild: `ojsdef-plugin-1.0.1.zip`

- [ ] **Step 1: Rebuild ZIP menggunakan .NET ZipFile API**

Dari direktori `D:\Kuliahku\Capstone\workspace\OJSDEF-Plugin\` di PowerShell:

```powershell
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

Expected: Output menampilkan ukuran bytes > 0.

- [ ] **Step 2: Commit ZIP**

```bash
git add ojsdef-plugin-1.0.1.zip
git commit -m "chore(c1): rebuild plugin ZIP with ConfigScanner + ContentInjectionDetector fixes"
```

---

### Task 12: Final Syntax Check Semua File

- [ ] **Step 1: Syntax check batch**

```bash
cd D:\Kuliahku\Capstone\workspace\OJSDEF-BackEnd
python -m py_compile app/workers/internal_bot.py && echo "internal_bot OK"
python -m py_compile app/scanners/models.py && echo "models OK"
python -m py_compile app/scanners/internal/config_scanner.py && echo "config_scanner OK"
python -m py_compile app/scanners/internal/rbac_auditor.py && echo "rbac_auditor OK"
python -m py_compile app/scanners/internal/file_integrity.py && echo "file_integrity OK"
python -m py_compile app/scanners/internal/content_detector.py && echo "content_detector OK"
python -m py_compile app/scanners/internal/plugin_auditor.py && echo "plugin_auditor OK"
python -m py_compile app/routers/plugin_callback.py && echo "plugin_callback OK"
```

Expected: Semua baris mencetak `OK`.

---

## Deployment

```bash
# BackEnd VPS — tidak perlu rebuild image (tidak ada library baru)
git pull
docker compose down && docker compose up -d

# Plugin — upload ojsdef-plugin-1.0.1.zip ke OJS admin panel
# Login OJS → Website Settings → Plugins → Upload New Plugin → pilih ZIP
```
