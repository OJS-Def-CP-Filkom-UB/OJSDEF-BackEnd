# Spec A — PDF Fix + Plugin Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ganti WeasyPrint dengan xhtml2pdf, tambah env-var fallback di ConfigScanner, dan perbaiki testConnection notification di plugin OJS.

**Architecture:** Tiga bug fix independen di dua codebase. Backend: ganti library PDF di `report.py`. Plugin: dua patch PHP kecil + rebuild ZIP distribusi.

**Tech Stack:** Python/FastAPI, xhtml2pdf 0.2.x, PHP 7.4+, PKP OJS Plugin API

**Catatan Testing:** Backend tidak dapat di-test lokal (tidak ada Docker/database). Verifikasi via syntax check Python. Test manual di VPS setelah deploy.

---

## File Map

| File | Aksi |
|------|------|
| `OJSDEF-BackEnd/requirements.txt` | Edit — hapus weasyprint, tambah xhtml2pdf |
| `OJSDEF-BackEnd/app/services/report.py` | Edit — ganti WeasyPrint dengan xhtml2pdf API |
| `OJSDEF-Plugin/ojsdef/classes/scanners/ConfigScanner.php` | Edit — tambah `_isDbPasswordEmpty()` |
| `OJSDEF-Plugin/ojsdef/OjsdefPlugin.php` | Edit — perbaiki testConnection notification |
| `OJSDEF-Plugin/ojsdef-plugin-1.0.1.zip` | Rebuild dari source |

---

### Task 1: Ganti WeasyPrint dengan xhtml2pdf

**Context:** WeasyPrint 60.2 memanggil `pydyf.PDF()` dengan positional args yang sudah dihapus di pydyf terbaru. Error: `PDF.__init__() takes 1 positional argument but 3 were given`. xhtml2pdf adalah pure Python, zero system dependency, API stabil. Template `report.html` menggunakan basic CSS yang kompatibel penuh dengan xhtml2pdf.

**Files:**
- Modify: `OJSDEF-BackEnd/requirements.txt`
- Modify: `OJSDEF-BackEnd/app/services/report.py`

- [ ] **Step 1: Update requirements.txt**

Buka `OJSDEF-BackEnd/requirements.txt`. Di section `# PDF & Storage`, hapus `weasyprint==60.2` dan tambah `xhtml2pdf>=0.2.16`. Section tersebut menjadi:

```
# PDF & Storage
xhtml2pdf>=0.2.16
jinja2==3.1.3
boto3==1.34.0
```

- [ ] **Step 2: Tulis ulang app/services/report.py**

Tulis ulang seluruh `OJSDEF-BackEnd/app/services/report.py`:

```python
import uuid
import io
import os
import logging
from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa
import boto3
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import ScanJob, OJSTarget, Report
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)
_jinja = Environment(loader=FileSystemLoader(
    os.path.join(os.path.dirname(__file__), "..", "templates")
))
SEVERITY_LABEL = {"critical": "Kritis", "high": "Berbahaya", "medium": "Perhatian", "low": "Aman"}


def _s3():
    return boto3.client(
        "s3",
        endpoint_url=f"{'https' if settings.minio_use_ssl else 'http'}://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )


async def generate_pdf_report(session: AsyncSession, job: ScanJob, findings: list) -> Report | None:
    try:
        target = (await session.execute(
            select(OJSTarget).where(OJSTarget.id == job.target_id)
        )).scalar_one()
        html = _jinja.get_template("report.html").render(
            job=job, target=target, findings=findings, severity_label=SEVERITY_LABEL,
        )
        output = io.BytesIO()
        result = pisa.CreatePDF(html, dest=output)
        if result.err:
            raise RuntimeError(f"xhtml2pdf error code {result.err}")
        pdf = output.getvalue()
        path = f"{job.tenant_id}/{job.id}/report.pdf"
        _s3().put_object(
            Bucket=settings.minio_bucket, Key=path,
            Body=pdf, ContentType="application/pdf",
        )
        report = Report(
            id=uuid.uuid4(), tenant_id=job.tenant_id, job_id=job.id,
            format="pdf", storage_path=path, file_size_bytes=len(pdf),
        )
        session.add(report)
        return report
    except Exception as e:
        logger.warning("PDF generation failed for job %s: %s", job.id, e)
        return None
```

- [ ] **Step 3: Syntax check**

Dari direktori `OJSDEF-BackEnd/`:
```bash
python -c "import ast; ast.parse(open('app/services/report.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt app/services/report.py
git commit -m "fix: replace WeasyPrint with xhtml2pdf — eliminates pydyf API mismatch"
```

---

### Task 2: ConfigScanner Env-Variable Fallback

**Context:** `Config::getVar('database', 'password')` hanya membaca `config.inc.php`. Di OJS Docker, password sering di-inject via env variable (`DB_PASSWORD`, `OJS_DB_PASSWORD`, dll.) yang tidak tercermin di config file. Scanner selalu melaporkan `db_password_empty = true` padahal password ada. Fix: tambah fallback `getenv()` scan untuk nama-nama env var umum.

**Files:**
- Modify: `OJSDEF-Plugin/ojsdef/classes/scanners/ConfigScanner.php`

- [ ] **Step 1: Tulis ulang ConfigScanner.php**

Tulis ulang seluruh `OJSDEF-Plugin/ojsdef/classes/scanners/ConfigScanner.php`:

```php
<?php

class ConfigScanner
{
    /** @var object */
    private $plugin;

    public function __construct($plugin)
    {
        $this->plugin = $plugin;
    }

    /**
     * @return array Audit config.inc.php — tidak expose nilai password/secret
     */
    public function scan(): array
    {
        return [
            'debug_mode'            => (bool) $this->_cfg('debug',    'debug_mode',    false),
            'show_errors'           => (bool) $this->_cfg('debug',    'show_errors',   false),
            'api_key_secret_length' => strlen((string) $this->_cfg('general',  'api_key_secret', '')),
            'force_ssl'             => (bool) $this->_cfg('security', 'force_ssl',     false),
            'allowed_hosts_set'     => !empty($this->_cfg('security', 'allowed_hosts', '')),
            'installed'             => (bool) $this->_cfg('general',  'installed',     false),
            'smtp_auth_enabled'     => !empty($this->_cfg('email',    'smtp_auth',     '')),
            'smtp_password_set'     => !empty($this->_cfg('email',    'smtp_password', '')),
            'db_driver'             => (string) $this->_cfg('database', 'driver',      ''),
            'db_host'               => (string) $this->_cfg('database', 'host',        ''),
            'db_password_empty'     => $this->_isDbPasswordEmpty(),
        ];
    }

    private function _isDbPasswordEmpty(): bool
    {
        $cfgVal = (string) $this->_cfg('database', 'password', '');
        if (!empty($cfgVal)) return false;

        $candidates = [
            'OJS_DB_PASSWORD', 'DB_PASSWORD', 'DATABASE_PASSWORD',
            'MYSQL_PASSWORD', 'POSTGRES_PASSWORD', 'PGPASSWORD',
        ];
        foreach ($candidates as $name) {
            $val = getenv($name);
            if ($val !== false && $val !== '') return false;
        }
        return true;
    }

    private function _cfg(string $section, string $key, $default)
    {
        if (!class_exists('Config')) return $default;
        return \Config::getVar($section, $key, $default);
    }
}
```

- [ ] **Step 2: Commit**

Dari direktori `OJSDEF-Plugin/`:
```bash
git add ojsdef/classes/scanners/ConfigScanner.php
git commit -m "fix: ConfigScanner reads DB password from env var fallback for Docker deployments"
```

---

### Task 3: testConnection Success Notification + Rebuild ZIP

**Context:** `RemoteActionConfirmationModal` menutup modal silent saat `JSONMessage(true, $message)` — user tidak tahu test berhasil. Fix: gunakan `NotificationManager::createTrivialNotification()` yang menampilkan toast OJS-native (hijau sukses, merah gagal).

**Files:**
- Modify: `OJSDEF-Plugin/ojsdef/OjsdefPlugin.php`
- Rebuild: `OJSDEF-Plugin/ojsdef-plugin-1.0.1.zip`

- [ ] **Step 1: Tambah dua use-statement di OjsdefPlugin.php**

Buka `OJSDEF-Plugin/ojsdef/OjsdefPlugin.php`. Temukan blok `use` di bagian atas (setelah baris `namespace APP\plugins\generic\ojsdef;`). Tambahkan dua baris setelah `use PKP\linkAction\request\RemoteActionConfirmationModal;`:

```php
use PKP\notification\NotificationManager;
use PKP\notification\PKPNotification;
```

Blok `use` lengkap menjadi:
```php
use PKP\plugins\GenericPlugin;
use PKP\plugins\Hook;
use PKP\core\JSONMessage;
use PKP\linkAction\LinkAction;
use PKP\linkAction\request\AjaxModal;
use PKP\linkAction\request\RemoteActionConfirmationModal;
use PKP\notification\NotificationManager;
use PKP\notification\PKPNotification;
```

- [ ] **Step 2: Ganti case testConnection di method manage()**

Dalam method `manage($args, $request)`, cari dan ganti seluruh blok `case 'testConnection':` (mulai dari `case 'testConnection':` sampai baris `return new JSONMessage($success, $message);`). Ganti dengan:

```php
            case 'testConnection':
                $this->_requireClasses();
                $extra   = $this->_buildHeartbeatExtra();
                $result  = (new \ApiClient($this))->sendHeartbeat($extra);
                $success = ($result['code'] === 200);

                if ($success) {
                    $message   = __('plugins.generic.ojsdef.testConnection.success');
                    $notifType = PKPNotification::NOTIFICATION_TYPE_SUCCESS;
                } else {
                    $detail    = !empty($result['error']) ? $result['error'] : 'HTTP ' . $result['code'];
                    $message   = __('plugins.generic.ojsdef.testConnection.failed') . ' [' . $detail . ']';
                    $notifType = PKPNotification::NOTIFICATION_TYPE_ERROR;
                }

                $user = $request->getUser();
                $notifMgr = new NotificationManager();
                $notifMgr->createTrivialNotification(
                    $user->getId(),
                    $notifType,
                    ['contents' => $message]
                );
                return new JSONMessage($success);
```

- [ ] **Step 3: Commit perubahan PHP**

Dari direktori `OJSDEF-Plugin/`:
```bash
git add ojsdef/OjsdefPlugin.php
git commit -m "fix: testConnection shows OJS toast notification on success and failure"
```

- [ ] **Step 4: Rebuild ZIP distribusi**

Dari direktori `OJSDEF-Plugin/` di PowerShell:
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

- [ ] **Step 5: Commit ZIP**

```bash
git add ojsdef-plugin-1.0.1.zip
git commit -m "chore: rebuild plugin ZIP v1.0.1 with ConfigScanner + notification fixes"
```

---

## Deployment

```bash
# Backend VPS — wajib rebuild image (library PDF berubah)
git pull
docker compose build
docker compose down && docker compose up -d

# Plugin — upload ZIP ke OJS admin panel
# Login OJS → Website Settings → Plugins → Upload New Plugin → pilih ojsdef-plugin-1.0.1.zip
# Atau: replace file ZIP di server OJS dan reload plugin
```
