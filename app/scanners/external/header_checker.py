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
