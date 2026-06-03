import httpx
from app.scanners.models import FindingResult, make_finding


async def scan_cookies(url: str) -> list[FindingResult]:
    """
    Fetch halaman login OJS dan cek Set-Cookie headers untuk Secure flag.
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
                    affected_path=f"{base}/index/login",
                    evidence=f"Set-Cookie: {raw[:120]}",
                    remediation=(
                        "Aktifkan `force_ssl = On` di config.inc.php OJS, "
                        "atau set `session.cookie_secure = 1` di konfigurasi PHP."
                    ),
                ))
    except Exception:
        pass

    return findings
