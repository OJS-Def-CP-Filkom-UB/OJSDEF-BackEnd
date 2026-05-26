import asyncio
import httpx
from app.scanners.models import FindingResult, make_finding

# (path, finding_type, title, description, remediation)
DIR_PATHS = [
    "/uploads/",
    "/files/",
    "/backup/",
    "/data/",
]

PATHS: list[tuple[str, str, str, str, str]] = [
    (
        "/.git/config",
        "exposed_git",
        "Repositori Git Terekspos Secara Publik",
        (
            "File .git/config dapat diakses publik, mengekspos konfigurasi repositori "
            "termasuk URL remote dan informasi sensitif lainnya."
        ),
        (
            "Blokir akses ke direktori .git melalui konfigurasi web server. "
            "Untuk Nginx: `location ~ /\\.git { deny all; }`. "
            "Untuk Apache: tambahkan `Deny from all` di .htaccess."
        ),
    ),
    (
        "/.env",
        "exposed_env_file",
        "File .env Terekspos Secara Publik",
        (
            "File .env yang berisi variabel lingkungan sensitif (password, API key, secret) "
            "dapat diakses tanpa autentikasi."
        ),
        (
            "Pindahkan file .env ke luar webroot atau blokir aksesnya via konfigurasi web server. "
            "Segera rotasi semua kredensial yang terekspos."
        ),
    ),
    (
        "/phpinfo.php",
        "phpinfo_exposed",
        "Halaman phpinfo() Terekspos",
        (
            "File phpinfo.php mengekspos konfigurasi PHP, variabel server, "
            "path sistem, dan informasi sensitif lainnya."
        ),
        (
            "Hapus file phpinfo.php dari server produksi segera. "
            "File ini tidak boleh ada di lingkungan production."
        ),
    ),
]


async def scan_open_dirs(url: str) -> list[FindingResult]:
    """
    Check for publicly accessible sensitive paths.
    Uses asyncio.Semaphore(3) for rate limiting with 0.1s delay.
    Never raises — returns empty list on any error.
    """
    findings = []
    base = url.rstrip("/")
    sem = asyncio.Semaphore(3)

    async def check(path: str) -> int | None:
        async with sem:
            try:
                async with httpx.AsyncClient(
                    timeout=10, follow_redirects=False
                ) as c:
                    await asyncio.sleep(0.1)
                    resp = await c.get(f"{base}{path}")
                    return resp.status_code
            except Exception:
                return None

    for path, ftype, title, description, remediation in PATHS:
        status = await check(path)
        if status == 200:
            findings.append(make_finding(
                ftype,
                category="external",
                title=title,
                description=description,
                affected_path=f"{base}{path}",
                evidence=f"HTTP 200 OK pada {path}",
                remediation=remediation,
            ))

    # Directory listing detection on common upload/backup directories
    for dir_path in DIR_PATHS:
        async with sem:
            try:
                async with httpx.AsyncClient(timeout=10, follow_redirects=False) as c:
                    await asyncio.sleep(0.1)
                    resp = await c.get(f"{base}{dir_path}")
                    if resp.status_code == 200 and "Index of" in resp.text:
                        findings.append(make_finding(
                            "open_directory",
                            category="external",
                            title=f"Directory Listing Terbuka: {dir_path}",
                            description=(
                                f"Direktori {dir_path} memiliki directory listing aktif, "
                                "mengekspos daftar file kepada publik."
                            ),
                            affected_path=f"{base}{dir_path}",
                            evidence=f"HTTP 200 dengan 'Index of' pada {dir_path}",
                            remediation=(
                                "Nonaktifkan directory listing di konfigurasi web server. "
                                "Untuk Nginx: tambahkan `autoindex off;`. "
                                "Untuk Apache: tambahkan `Options -Indexes`."
                            ),
                        ))
            except Exception:
                pass

    return findings
