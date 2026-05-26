import httpx
from app.scanners.models import FindingResult, make_finding

# Each entry: header_name -> (finding_type, title, remediation, owasp_category)
REQUIRED: dict[str, tuple[str, str, str, str]] = {
    "Content-Security-Policy": (
        "missing_csp",
        "CSP (Content-Security-Policy) Tidak Ditemukan",
        "Tambahkan header Content-Security-Policy untuk mencegah serangan XSS dan injeksi konten.",
        "A03:2021-Injection",
    ),
    "Strict-Transport-Security": (
        "missing_hsts",
        "HSTS (Strict-Transport-Security) Tidak Ditemukan",
        (
            "Tambahkan header: Strict-Transport-Security: max-age=31536000; includeSubDomains "
            "untuk memaksa koneksi HTTPS."
        ),
        "A05:2021",
    ),
    "X-Frame-Options": (
        "missing_x_frame",
        "X-Frame-Options Tidak Ditemukan",
        "Tambahkan header X-Frame-Options: DENY untuk mencegah serangan clickjacking.",
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

            for header, (ftype, title, remediation, owasp) in REQUIRED.items():
                if header.lower() not in present:
                    findings.append(make_finding(
                        ftype,
                        category="external",
                        title=title,
                        description=(
                            f"Header keamanan {header} tidak ditemukan pada respons dari {url}. "
                            "Absennya header ini meningkatkan risiko serangan web."
                        ),
                        affected_path=url,
                        evidence=f"Header {header} tidak ada dalam respons HTTP",
                        remediation=remediation,
                        owasp_category=owasp,
                    ))
    except Exception:
        pass

    return findings
