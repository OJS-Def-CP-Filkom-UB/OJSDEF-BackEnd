# Spec A — PDF Fix + Plugin Fixes Design

## Goal

Perbaiki 3 bug yang ditemukan setelah deployment terbaru:
1. PDF generation masih gagal (pydyf API mismatch dengan WeasyPrint 60.2)
2. ConfigScanner tidak mendeteksi DB password yang di-set via env variable Docker
3. Plugin testConnection tidak menampilkan notifikasi saat berhasil

## Architecture

Tiga fix independen di dua codebase:
- **OJSDEF-BackEnd**: ganti WeasyPrint → xhtml2pdf di `app/services/report.py` + `requirements.txt`
- **OJSDEF-Plugin**: tambah env-var fallback di `ConfigScanner.php`, tambah NotificationManager di `OjsdefPlugin.php`

**Tech Stack:** FastAPI, xhtml2pdf 0.2.17, PHP 7.4+, PKP OJS Plugin API

---

## Section 1: PDF Library Switch (xhtml2pdf)

### Root Cause

WeasyPrint 60.2 memanggil `pydyf.PDF()` dengan positional arguments (API lama), tapi pydyf terbaru (≥0.6.0) mengubah signature `PDF.__init__` menjadi tidak menerima positional args. WeasyPrint tidak pin versi pydyf secara eksplisit, sehingga Docker build selalu install pydyf terbaru yang incompatible.

Error: `PDF.__init__() takes 1 positional argument but 3 were given`

### Solusi

Ganti WeasyPrint seluruhnya dengan **xhtml2pdf** — pure Python, zero system dependency (tidak perlu Pango, pydyf, atau binary sistem). Template `report.html` menggunakan basic table/color CSS yang kompatibel penuh dengan xhtml2pdf.

### Perubahan File

**`requirements.txt`**
- Hapus `weasyprint==60.2`
- Tambah `xhtml2pdf==0.2.17`

**`app/services/report.py`**
- Hapus `from weasyprint import HTML`
- Tambah `import io` dan `from xhtml2pdf import pisa`
- Ganti `pdf = HTML(string=html).write_pdf()` dengan:

```python
output = io.BytesIO()
result = pisa.CreatePDF(html, dest=output)
if result.err:
    raise RuntimeError(f"xhtml2pdf error code {result.err}")
pdf = output.getvalue()
```

- Wrapper `try/except Exception` yang sudah ada tetap dipertahankan — jika PDF gagal, scan tetap `completed`, hanya PDF tidak tersedia.
- Template `app/templates/report.html` tidak perlu diubah.

### Docker Notes

`docker compose build` wajib dijalankan setelah perubahan ini agar image rebuild dengan xhtml2pdf.

---

## Section 2: ConfigScanner Env-Variable Support

### Root Cause

`Config::getVar('database', 'password')` hanya membaca `config.inc.php`. Di Docker setup OJS, password sering di-inject via environment variable di docker-compose (bukan ditulis langsung ke config file). Akibatnya scanner selalu melaporkan `db_password_empty = true` meskipun password sebenarnya terset di env.

### Solusi

Tambah fallback `getenv()` scan di `ConfigScanner`. Jika `Config::getVar()` return kosong, cek daftar nama env var yang umum dipakai di berbagai OJS Docker setup. Tidak ada nilai password yang di-expose — hanya boolean empty/not-empty.

### Perubahan File

**`ojsdef/classes/scanners/ConfigScanner.php`**

Ubah field `db_password_empty` di method `scan()`:

```php
// Sebelum:
'db_password_empty' => empty($this->_cfg('database', 'password', '')),

// Sesudah:
'db_password_empty' => $this->_isDbPasswordEmpty(),
```

Tambah private method baru:

```php
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
```

**Env var yang dicek:**

| Env Var | Konvensi |
|---------|----------|
| `OJS_DB_PASSWORD` | PKP official Docker image |
| `DB_PASSWORD` | Generic Docker Compose |
| `DATABASE_PASSWORD` | Alternative generic |
| `MYSQL_PASSWORD` | MySQL-specific Docker |
| `POSTGRES_PASSWORD` | PostgreSQL-specific Docker |
| `PGPASSWORD` | PostgreSQL client standard |

---

## Section 3: Plugin testConnection Success Notification

### Root Cause

`testConnection` action menggunakan `RemoteActionConfirmationModal`. JS handler modal ini dirancang untuk aksi destruktif — saat `JSONMessage(true, $message)` diterima, modal ditutup secara silent tanpa menampilkan `$message`. Hanya `JSONMessage(false, $message)` yang ditampilkan sebagai error text. Hasilnya: user tidak tahu apakah test berhasil.

### Solusi

Gunakan `PKP\notification\NotificationManager::createTrivialNotification()` untuk menampilkan toast notification OJS-native (hijau untuk sukses, merah untuk gagal), lalu return `JSONMessage($success)` tanpa content. Ini konsisten dengan pola plugin OJS lainnya.

`RemoteActionConfirmationModal` tetap dipertahankan — dialog "Are you sure?" berguna mencegah accidental test spam.

### Perubahan File

**`ojsdef/OjsdefPlugin.php`** — case `testConnection` di method `manage()`:

```php
case 'testConnection':
    $this->_requireClasses();
    $extra  = $this->_buildHeartbeatExtra();
    $result = (new \ApiClient($this))->sendHeartbeat($extra);
    $success = ($result['code'] === 200);

    if ($success) {
        $message   = __('plugins.generic.ojsdef.testConnection.success');
        $notifType = \PKP\notification\PKPNotification::NOTIFICATION_TYPE_SUCCESS;
    } else {
        $detail    = !empty($result['error']) ? $result['error'] : 'HTTP ' . $result['code'];
        $message   = __('plugins.generic.ojsdef.testConnection.failed') . ' [' . $detail . ']';
        $notifType = \PKP\notification\PKPNotification::NOTIFICATION_TYPE_ERROR;
    }

    $user = $request->getUser();
    $notifMgr = new \PKP\notification\NotificationManager();
    $notifMgr->createTrivialNotification(
        $user->getId(),
        $notifType,
        ['contents' => $message]
    );
    return new JSONMessage($success);
```

**Hasil UX:**
- Sukses → toast hijau muncul di halaman OJS
- Gagal → toast merah dengan detail error

---

## Deployment

```bash
# Backend — wajib rebuild (library PDF berubah)
git pull
docker compose build
docker compose down && docker compose up -d

# Plugin — rebuild ZIP dan upload ke OJS admin panel
# (dari direktori OJSDEF-Plugin/)
Add-Type -AssemblyName System.IO.Compression; Add-Type -AssemblyName System.IO.Compression.FileSystem
$src = "ojsdef"; $out = "ojsdef-plugin-1.0.1.zip"
if (Test-Path $out) { Remove-Item $out -Force }
$zip = [System.IO.Compression.ZipFile]::Open($out, 'Create')
Get-ChildItem -Path $src -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring((Resolve-Path $src).Path.Length).TrimStart('\').Replace('\','/')
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, "ojsdef/$rel")
}
$zip.Dispose()
```
