import asyncio
import httpx
from app.scanners.models import FindingResult, make_finding

XSS_PAYLOAD = "<script>alert(1)</script>"
SQL_PAYLOAD = "'"
SQL_ERROR_PATTERNS = ["SQL syntax", "mysql_fetch", "ORA-", "pg_query", "sqlite3"]


async def scan_vulnerabilities(url: str) -> list[FindingResult]:
    """
    Probe for reflected XSS and SQL error exposure.
    Uses asyncio.Semaphore(5) for rate limiting with 0.1s delay between requests.
    Never raises — returns empty list on any error.
    """
    findings = []
    base = url.rstrip("/")
    sem = asyncio.Semaphore(5)

    async def get(path: str, params: dict | None = None) -> httpx.Response | None:
        async with sem:
            try:
                async with httpx.AsyncClient(
                    timeout=10, follow_redirects=False
                ) as c:
                    await asyncio.sleep(0.1)
                    return await c.get(f"{base}{path}", params=params)
            except Exception:
                return None

    # Reflected XSS probe on search endpoint
    resp = await get("/index.php/search/search", {"query": XSS_PAYLOAD})
    if resp is not None and XSS_PAYLOAD in (resp.text or ""):
        findings.append(make_finding(
            "reflected_xss",
            category="external",
            title="Reflected XSS Terdeteksi di Halaman Pencarian",
            description=(
                "Parameter input direfleksikan ke halaman tanpa sanitasi yang memadai, "
                "memungkinkan serangan Cross-Site Scripting (XSS)."
            ),
            affected_path=f"{base}/index.php/search/search",
            evidence=f"payload={XSS_PAYLOAD!r} ditemukan di respons tanpa encoding",
            remediation=(
                "Terapkan output encoding pada semua parameter yang direfleksikan. "
                "Gunakan Content-Security-Policy dan validasi input."
            ),
            owasp_category="A03:2021-Injection",
        ))

    # SQL error exposure probe
    resp = await get("/index.php/index/search/search", {"query": SQL_PAYLOAD})
    if resp is not None and any(
        pattern in (resp.text or "") for pattern in SQL_ERROR_PATTERNS
    ):
        findings.append(make_finding(
            "sql_error_exposed",
            category="external",
            title="Pesan Error SQL Terekspos ke Publik",
            description=(
                "Server mengekspos pesan error database SQL dalam respons HTTP, "
                "mengungkap informasi tentang struktur database."
            ),
            affected_path=f"{base}/index.php/index/search/search",
            evidence=f"SQL error message terdeteksi dengan payload: {SQL_PAYLOAD!r}",
            remediation=(
                "Nonaktifkan display_errors di konfigurasi PHP. "
                "Implementasikan error handling yang aman — log error ke file, "
                "tampilkan pesan generik ke pengguna."
            ),
            owasp_category="A03:2021-Injection",
        ))

    # Path traversal probe on file download endpoint
    traversal_payload = "../../../../../../../../etc/passwd"
    resp = await get("/index.php/article/download/1", {"fileId": traversal_payload})
    if resp is not None and "root:" in (resp.text or ""):
        findings.append(make_finding(
            "path_traversal",
            category="external",
            title="Path Traversal Terdeteksi di Endpoint Download",
            description=(
                "Server merespons path traversal payload dengan konten file sistem, "
                "memungkinkan akses ke file di luar webroot."
            ),
            affected_path=f"{base}/index.php/article/download/1",
            evidence=f"payload={traversal_payload!r} menghasilkan respons dengan konten /etc/passwd",
            remediation=(
                "Validasi dan sanitasi semua parameter path di sisi server. "
                "Gunakan realpath() dan pastikan file berada dalam direktori yang diizinkan."
            ),
            owasp_category="A01:2021-Broken Access Control",
        ))

    return findings
