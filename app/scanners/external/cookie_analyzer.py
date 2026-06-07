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
