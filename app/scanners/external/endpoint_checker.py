import httpx
from app.scanners.models import FindingResult, make_finding


async def scan_ojs_endpoints(url: str) -> list[FindingResult]:
    """
    Cek aksesibilitas endpoint OJS dari internet:
    - /index/login dan /index/admin → P-5 (risiko brute force)
    - /index/index/oai              → A-3 (informatif, bukan kerentanan)
    Never raises — return [] on any error.
    """
    findings = []
    base     = url.rstrip("/")

    async def check(path: str) -> int | None:
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=False) as c:
                return (await c.get(f"{base}{path}")).status_code
        except Exception:
            return None

    # P-5: Endpoint admin/login terbuka dari internet (CVSS 5.8 — Medium)
    admin_paths = ["/index/login", "/index/admin"]
    accessible  = []
    for path in admin_paths:
        status = await check(path)
        if status is not None and status < 500:
            accessible.append(f"{path} (HTTP {status})")

    if accessible:
        findings.append(make_finding(
            "ojs_admin_endpoint_exposed",
            category="external",
            title="Endpoint Administrasi OJS Terbuka dari Internet",
            description=(
                "Halaman login dan admin OJS dapat diakses dari internet tanpa pembatasan IP. "
                "Endpoint yang terbuka meningkatkan risiko serangan brute force "
                "pada akun administrator."
            ),
            affected_path=", ".join(accessible),
            evidence="; ".join(accessible),
            remediation=(
                "Tambahkan rate limiting di Nginx: "
                "`limit_req_zone $binary_remote_addr zone=ojs_login:10m rate=5r/m;` "
                "dan `limit_req zone=ojs_login burst=10 nodelay;` di location /index/login."
            ),
            owasp_category="A07:2021-Identification-and-Authentication-Failures",
        ))

    # A-3: OAI endpoint accessible (CVSS 2.6 — Low, informatif)
    for path in ("/index/index/oai", "/index/oai"):
        status = await check(path)
        if status == 200:
            findings.append(make_finding(
                "ojs_oai_accessible",
                category="external",
                title="OAI-PMH Endpoint Aktif (Informatif)",
                description=(
                    "Endpoint OAI-PMH dapat diakses publik. "
                    "Ini adalah fitur standar interoperabilitas jurnal open access — "
                    "bukan kerentanan keamanan."
                ),
                affected_path=f"{base}{path}",
                evidence=f"HTTP 200 pada {path}",
                remediation="Tidak diperlukan tindakan. OAI-PMH adalah fitur standar.",
            ))
            break  # cukup satu endpoint yang match

    return findings
