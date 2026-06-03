# Spec C-1 — Internal Scanner Data Layer Fix

## Goal

Perbaiki semua bug sistemik di pipeline data internal scanner: data path mismatch di `internal_bot.py`, format mismatch antara PHP scanner output dan Python analyzer input untuk semua modul, OJS config key yang salah di `ConfigScanner.php`, `ContentInjectionDetector.php` yang tidak scan OJS settings fields, dan checksums palsu di endpoint.

## Architecture

Tiga area perubahan yang membentuk satu pipeline data:

1. **Plugin PHP** (`ConfigScanner.php`, `ContentInjectionDetector.php`) — sumber data OJS
2. **Backend Python scanners** (5 file rewrite + 1 delete) — analisis data
3. **Data path + checksums** (`internal_bot.py`, `plugin_callback.py`) — plumbing

**Prinsip:** Python adapts to PHP. PHP adalah source of truth — Python rewrite agar native menerima format PHP. Tidak ada adapter layer.

**Tech Stack:** Python/FastAPI, Celery, PHP 7.4+, OJS 3.3.x/3.4.x

---

## Data Contract Resmi (PHP → Python)

### `config` (ConfigScanner.php → config_scanner.py)
```json
{
  "display_errors":        "bool",
  "show_errors":           "bool",
  "show_stacktrace":       "bool",
  "api_key_secret_length": "int",
  "force_ssl":             "bool",
  "allowed_hosts_set":     "bool",
  "installed":             "bool",
  "smtp_enabled":          "bool",
  "smtp_auth_enabled":     "bool",
  "smtp_password_set":     "bool",
  "db_driver":             "string",
  "db_host":               "string",
  "db_password_empty":     "bool"
}
```

### `rbac` (RbacAuditor.php → rbac_auditor.py)
```json
{
  "total_users":               "int",
  "superadmin_count":          "int",
  "multiple_superadmin":       "bool",
  "inactive_high_priv_count":  "int",
  "inactive_high_priv_users":  [{"user_id": "int", "last_login": "ISO-datetime-string"}]
}
```

### `file_integrity` (FileIntegrityChecker.php → file_integrity.py)
```json
{
  "status":        "completed|skipped",
  "total_checked": "int",
  "modified":      "int",
  "missing":       "int",
  "findings":      [{"path": "string", "status": "modified|missing", "local_hash": "string"}]
}
```

### `content` (ContentInjectionDetector.php → content_detector.py)
```json
{
  "total_scanned":  "int",
  "affected_count": "int",
  "detections": [
    {
      "submission_id": "int|null",
      "field":         "string (e.g. abstract, journal.about, journal.footer)",
      "pattern":       "gambling_keyword|hidden_iframe|js_redirect|base64_eval|phishing_tld",
      "excerpt":       "string (max 100 chars)"
    }
  ]
}
```

### `plugins` (PluginAuditor.php → plugin_auditor.py)
```json
{
  "total_installed":        "int",
  "total_enabled":          "int",
  "disabled_but_installed": [{"name": "string", "category": "string", "version": "string|null", "enabled": false}],
  "plugins":                "array"
}
```

---

## File Map

| File | Aksi | Codebase |
|------|------|----------|
| `app/workers/internal_bot.py` | Edit — fix data path | BackEnd |
| `app/scanners/models.py` | Edit — tambah CVSS_SCORES entries baru | BackEnd |
| `app/scanners/internal/config_scanner.py` | Rewrite | BackEnd |
| `app/scanners/internal/rbac_auditor.py` | Rewrite | BackEnd |
| `app/scanners/internal/file_integrity.py` | Rewrite | BackEnd |
| `app/scanners/internal/content_detector.py` | Rewrite | BackEnd |
| `app/scanners/internal/plugin_auditor.py` | Rewrite | BackEnd |
| `app/scanners/internal/db_security.py` | **DELETE** | BackEnd |
| `app/routers/plugin_callback.py` | Edit — real checksums | BackEnd |
| `ojsdef/classes/scanners/ConfigScanner.php` | Edit — fix keys + new fields | Plugin |
| `ojsdef/classes/scanners/ContentInjectionDetector.php` | Edit — tambah settings scan | Plugin |
| `ojsdef-plugin-1.0.1.zip` | Rebuild | Plugin |

---

## Section 1: Data Path Fix (`internal_bot.py`)

### Root Cause

`plugin_callback.py` meneruskan `payload["data"]` (output `ScanOrchestrator.runAll()`) ke worker. Struktur actual:

```json
{
  "modules_completed": [...],
  "results": {
    "config": {...},
    "plugins": {...},
    "rbac": {...},
    "file_integrity": {...},
    "content": {...}
  },
  "status": "completed"
}
```

`_run_internal_scan` mengakses `data.get("config")` — key tidak ada di top level, semua dapat `{}` / `[]`.

### Fix

```python
async def _run_internal_scan(job_id: str, data: dict) -> None:
    results = data.get("results", {})   # ← tambah ini

    config_findings  = scan_config(results.get("config", {}))
    plugin_findings  = scan_plugins(results.get("plugins", {}))
    rbac_findings    = scan_rbac(results.get("rbac", {}))
    file_findings    = scan_file_integrity(results.get("file_integrity", {}))
    content_findings = scan_content(results.get("content", {}))
    # scan_db_security dihapus

    all_findings = config_findings + plugin_findings + rbac_findings + file_findings + content_findings
```

Key mapping yang berubah:

| Sebelum | Sesudah |
|---------|---------|
| `data.get("config", {})` | `results.get("config", {})` |
| `data.get("plugins", [])` | `results.get("plugins", {})` — dict bukan list |
| `data.get("users", [])` | `results.get("rbac", {})` — key berbeda |
| `data.get("file_integrity", {})` | `results.get("file_integrity", {})` |
| `data.get("articles", [])` | `results.get("content", {})` — key berbeda |
| `data.get("db_config", {})` | *dihapus* |

---

## Section 2: Python Scanner Rewrites

### 2.1 `models.py` — Tambah CVSS_SCORES Entries

Tambah ke dict `CVSS_SCORES` (dan update `modified_core_file` dari 8.5 → 9.1):

```python
# New finding types untuk internal scanner
"debug_mode_active":           9.8,   # K-1
"force_ssl_disabled":          8.1,   # B-1
"smtp_no_auth":                5.3,   # P-2
"db_password_empty":           8.0,
"api_key_too_short":           5.0,
"multiple_superadmin":         7.2,   # B-4
"inactive_high_priv_account":  5.0,   # P-3
"modified_core_file":          9.1,   # K-4 (update dari 8.5)
"modified_plugin_file":        7.8,   # B-6
"gambling_content":            9.5,   # K-2
"eval_base64_injection":       9.8,   # K-3
"hidden_iframe_injection":     8.3,   # B-2
"phishing_tld_link":           7.5,   # B-3
"js_redirect_injection":       6.1,   # P-1
"disabled_plugins_installed":  4.3,   # P-4
"excessive_active_plugins":    2.0,   # A-4
```

### 2.2 `config_scanner.py` — Rewrite

```python
from app.scanners.models import FindingResult, make_finding


def scan_config(config: dict) -> list[FindingResult]:
    findings = []

    # K-1: Debug mode aktif
    if config.get("display_errors") or config.get("show_errors") or config.get("show_stacktrace"):
        findings.append(make_finding(
            "debug_mode_active",
            category="internal",
            title="Mode Debug OJS Aktif",
            description="OJS berjalan dalam mode debug, mengekspos stack trace dan informasi sistem kepada semua pengguna.",
            affected_path="config.inc.php [debug]",
            evidence="display_errors=On atau show_errors=On atau show_stacktrace=On",
            remediation="Set `display_errors = Off` dan `show_stacktrace = Off` di config.inc.php.",
        ))

    # B-1: Force SSL dimatikan
    if not config.get("force_ssl", True):
        findings.append(make_finding(
            "force_ssl_disabled",
            category="internal",
            title="Force SSL Dimatikan di Konfigurasi OJS",
            description="OJS tidak memaksa HTTPS secara native. Pastikan redirect HTTPS dikonfigurasi di web server.",
            affected_path="config.inc.php [security]",
            evidence="force_ssl = Off",
            remediation="Set `force_login_ssl = On` di config.inc.php atau pastikan Nginx redirect HTTP ke HTTPS.",
        ))

    # P-2: SMTP aktif tanpa autentikasi
    if (config.get("smtp_enabled")
            and not config.get("smtp_auth_enabled")
            and not config.get("smtp_password_set")):
        findings.append(make_finding(
            "smtp_no_auth",
            category="internal",
            title="SMTP Aktif Tanpa Autentikasi",
            description="Server email dikonfigurasi tanpa autentikasi, membuka risiko relay spam atau intercept email.",
            affected_path="config.inc.php [email]",
            evidence="smtp = On, smtp_auth tidak dikonfigurasi",
            remediation="Tambahkan smtp_auth, smtp_username, dan smtp_password di konfigurasi email OJS.",
        ))

    # DB password kosong
    if config.get("db_password_empty"):
        findings.append(make_finding(
            "db_password_empty",
            category="internal",
            title="Password Database OJS Kosong",
            description="Koneksi database OJS tidak menggunakan password.",
            affected_path="config.inc.php [database]",
            evidence="database.password = (kosong)",
            remediation="Set password database yang kuat di config.inc.php atau environment variable.",
        ))

    # API key secret terlalu pendek
    key_len = config.get("api_key_secret_length", 32)
    if 0 < key_len < 32:
        findings.append(make_finding(
            "api_key_too_short",
            category="internal",
            title="API Key Secret OJS Terlalu Pendek",
            description=f"api_key_secret di config OJS kurang dari 32 karakter ({key_len} karakter).",
            affected_path="config.inc.php [general]",
            evidence=f"api_key_secret length = {key_len}",
            remediation="Set api_key_secret minimal 32 karakter acak di config.inc.php.",
        ))

    return findings
```

### 2.3 `rbac_auditor.py` — Rewrite

```python
from app.scanners.models import FindingResult, make_finding


def scan_rbac(rbac: dict) -> list[FindingResult]:
    findings = []

    # B-4: Multiple superadmin
    if rbac.get("multiple_superadmin"):
        count = rbac.get("superadmin_count", 0)
        findings.append(make_finding(
            "multiple_superadmin",
            category="internal",
            title=f"Terdapat {count} Akun Site Administrator",
            description=f"Ada {count} akun Site Administrator aktif. Prinsip least privilege dilanggar.",
            affected_path="users/site_administrators",
            evidence=f"superadmin_count = {count}",
            remediation="Pertahankan hanya 1 akun Site Administrator aktif. Hapus atau downgrade akun lainnya.",
        ))

    # P-3: Akun high-privilege tidak aktif
    for user in rbac.get("inactive_high_priv_users", []):
        uid  = user.get("user_id", "unknown")
        last = user.get("last_login", "tidak diketahui")
        findings.append(make_finding(
            "inactive_high_priv_account",
            category="internal",
            title=f"Akun Admin Tidak Aktif Lebih dari 1 Tahun (ID: {uid})",
            description=f"Akun dengan hak tinggi (ID: {uid}) terakhir login pada {last}.",
            affected_path=f"users/{uid}",
            evidence=f"user_id={uid}, last_login={last}",
            remediation="Nonaktifkan atau hapus akun admin yang tidak digunakan lebih dari 1 tahun.",
        ))

    return findings
```

### 2.4 `file_integrity.py` — Rewrite

```python
from app.scanners.models import FindingResult, make_finding


def scan_file_integrity(fi: dict) -> list[FindingResult]:
    findings = []

    if fi.get("status") != "completed":
        return findings  # checksums tidak tersedia — skip tanpa error

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
                remediation="Bandingkan file dengan versi resmi OJS. Restore dari backup bersih jika perlu.",
            ))

        elif status == "missing":
            findings.append(make_finding(
                "missing_core_file",
                category="internal",
                title=f"File Core OJS Hilang: {path}",
                description=f"File inti OJS {path} tidak ditemukan.",
                affected_path=path,
                evidence=f"file tidak ada: {path}",
                remediation="Restore file dari paket OJS versi yang sesuai dari PKP.",
            ))

    return findings
```

### 2.5 `content_detector.py` — Rewrite

```python
from app.scanners.models import FindingResult, make_finding

PATTERN_FINDINGS: dict[str, tuple[str, str, str]] = {
    "gambling_keyword": (
        "gambling_content",
        "Konten Judi/Spam Ditemukan",
        "Hapus konten yang mengandung kata kunci judi online. Audit akses akun editor.",
    ),
    "base64_eval": (
        "eval_base64_injection",
        "Injeksi eval(base64) Ditemukan — Indikator Kompromi",
        "Hapus segera script berbahaya. Lakukan audit menyeluruh pada konten dan file server.",
    ),
    "hidden_iframe": (
        "hidden_iframe_injection",
        "iFrame Tersembunyi Ditemukan",
        "Hapus tag iframe dari konten. Aktifkan Content-Security-Policy untuk blokir iframe eksternal.",
    ),
    "phishing_tld": (
        "phishing_tld_link",
        "Link dengan TLD Berisiko Tinggi Ditemukan",
        "Hapus atau ganti link dengan domain legitimate (.com, .ac.id, .edu).",
    ),
    "js_redirect": (
        "js_redirect_injection",
        "JavaScript Redirect Tersembunyi Ditemukan",
        "Hapus script redirect dari konten. Audit semua custom HTML di settings OJS.",
    ),
}


def scan_content(content: dict) -> list[FindingResult]:
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

### 2.6 `plugin_auditor.py` — Rewrite

```python
from app.scanners.models import FindingResult, make_finding


def scan_plugins(plugins_data: dict) -> list[FindingResult]:
    findings = []

    total_enabled = plugins_data.get("total_enabled", 0)
    disabled      = plugins_data.get("disabled_but_installed", [])

    # P-4: Plugin terinstall tapi dinonaktifkan
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
                "Plugin tidak aktif tetap memperluas attack surface."
            ),
            affected_path="plugins/",
            evidence=f"disabled_but_installed count = {len(disabled)}",
            remediation="Uninstall plugin yang tidak diperlukan melalui OJS Plugin Gallery.",
        ))

    # A-4: Terlalu banyak plugin aktif (informatif, threshold > 20)
    if total_enabled > 20:
        findings.append(make_finding(
            "excessive_active_plugins",
            category="internal",
            title=f"{total_enabled} Plugin Aktif — Audit Disarankan",
            description=(
                f"Terdapat {total_enabled} plugin aktif. Setiap plugin menambah attack surface. "
                "Lakukan audit berkala untuk memastikan semua plugin diperlukan."
            ),
            affected_path="plugins/",
            evidence=f"total_enabled = {total_enabled}",
            remediation="Nonaktifkan atau uninstall plugin yang tidak digunakan.",
        ))

    return findings
```

### 2.7 `db_security.py` — DELETE

Hapus file ini. Fungsionalitas deteksi DB password kosong sudah dipindah ke `config_scanner.py` via flag `db_password_empty` dari PHP.

---

## Section 3: PHP ConfigScanner.php — Fix Keys + New Fields

### Output Final Method `scan()`

```php
public function scan(): array
{
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
}
```

Perubahan dari versi sebelumnya:
- **Dihapus:** `debug_mode` (key tidak ada di OJS config)
- **Ditambah:** `display_errors`, `show_stacktrace`, `smtp_enabled`
- `_isDbPasswordEmpty()` tidak berubah

---

## Section 4: PHP ContentInjectionDetector.php — Settings Extension

### Method Baru `_scanContextSettings()`

Tambahkan setelah method `_getField()`:

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

### Perubahan di Method `scan()`

Merge hasil settings dan perbaiki `affected_count`:

```php
public function scan(): array
{
    $detections   = [];
    $totalScanned = 0;

    // [existing article scanning code — tidak berubah]
    if (class_exists('DAORegistry')) {
        try {
            $daoName     = class_exists('SubmissionDAO') ? 'SubmissionDAO' : 'ArticleDAO';
            $dao         = \DAORegistry::getDAO($daoName);
            if ($dao) {
                $submissions = $dao->getAll(true);
                while ($submission = $submissions->next()) {
                    $totalScanned++;
                    $detections = array_merge($detections, $this->_scanSubmission($submission));
                }
            }
        } catch (\Throwable $e) {
            // silent
        }
    }

    // Tambahkan settings fields scan
    $detections = array_merge($detections, $this->_scanContextSettings());

    // affected_count: unik per lokasi (submission atau settings field)
    $affectedLocations = array_unique(array_map(
        function ($d) { return $d['submission_id'] ?? $d['field']; },
        $detections
    ));

    return [
        'total_scanned'  => $totalScanned,
        'affected_count' => count($affectedLocations),
        'detections'     => $detections,
    ];
}
```

### Coverage Baru

| OJS Field | Data Key Dicek | Test Scenarios |
|-----------|---------------|----------------|
| About the Journal | `description` | K-2, B-2 |
| Website Footer | `pageFooter`, `footer` | K-3, P-1 |
| Information for Authors | `forAuthors`, `authorInformation` | B-3 |

---

## Section 5: Checksums Fix (`plugin_callback.py`)

### Cara Mendapatkan Real Hashes (saat implementasi)

```bash
# Dari VPS dalam kondisi BERSIH — SEBELUM test setup K-4
docker exec ojs_app sha256sum /var/www/html/index.php
docker exec ojs_app sha256sum /var/www/html/config.TEMPLATE.inc.php

# Alternatif dari GitHub PKP (ganti tag sesuai versi OJS):
curl -sL https://raw.githubusercontent.com/pkp/ojs/3_4_0-7/index.php | sha256sum
curl -sL https://raw.githubusercontent.com/pkp/ojs/3_4_0-7/config.TEMPLATE.inc.php | sha256sum
```

### Struktur CHECKSUMS yang Diperbarui

```python
# Nilai hash diisi saat implementasi dari source resmi PKP
CHECKSUMS: dict[str, dict[str, str]] = {
    "3_3_0": {
        "index.php":               "<sha256-dari-pkp-github-3.3.0>",
        "config.TEMPLATE.inc.php": "<sha256-dari-pkp-github-3.3.0>",
    },
    "3_4_0": {
        "index.php":               "<sha256-dari-pkp-github-3.4.0>",
        "config.TEMPLATE.inc.php": "<sha256-dari-pkp-github-3.4.0>",
    },
}
```

Prefix match sudah ada (`norm.startswith(key)`) — sub-versi seperti `3.4.0-7` otomatis match ke `3_4_0`.

### Limitasi yang Diakui

| Skenario | Status |
|----------|--------|
| K-4 (core file modified) | ✅ Terdeteksi |
| K-4 baseline (bersih) | ✅ Tidak false positive |
| B-6 (plugin file modified) | ❌ Out of scope versi ini |

---

## Test Coverage After This Spec

| ID | Skenario | Status Setelah Fix |
|----|----------|--------------------|
| K-1 | Debug mode aktif | ✅ |
| K-2 | Gambling di About Journal | ✅ |
| K-3 | eval(base64) di Footer | ✅ |
| K-4 | Core file modified | ✅ (tanpa false positive) |
| B-1 internal | Force SSL off | ✅ |
| B-2 | Hidden iframe di About | ✅ |
| B-3 | Phishing TLD di For Authors | ✅ |
| B-4 | Multiple superadmin | ✅ |
| B-5 | Missing HTTP headers | ✅ (sudah berfungsi) |
| B-6 | Plugin file modified | ❌ Out of scope |
| P-1 | JS redirect di Footer | ✅ |
| P-2 | SMTP tanpa autentikasi | ✅ |
| P-3 | Inactive admin | ✅ |
| P-4 | Disabled plugins | ✅ |
| P-6 | Versi OJS di header | ✅ (sudah berfungsi) |
| A-1 | Version meta tag | ✅ (sudah berfungsi) |
| A-4 | Many plugins | ✅ |

---

## Deployment

```bash
# BackEnd — tidak perlu rebuild image (tidak ada library baru)
git pull
docker compose down && docker compose up -d

# Plugin — rebuild ZIP dan upload ke OJS admin panel
# (dari direktori OJSDEF-Plugin/ di PowerShell)
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
