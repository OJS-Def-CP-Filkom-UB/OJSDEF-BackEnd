import ssl
import socket
from datetime import datetime, timezone
from app.scanners.models import FindingResult, make_finding
import httpx


def scan_ssl(hostname: str) -> list[FindingResult]:
    """
    Analyze SSL/TLS configuration of the given hostname on port 443.
    Checks certificate expiry and TLS protocol version.
    Sync function — uses stdlib ssl module. Never raises.
    """
    findings = []

    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(
            socket.create_connection((hostname, 443), timeout=10),
            server_hostname=hostname,
        ) as s:
            cert = s.getpeercert()
            not_after = datetime.strptime(
                cert["notAfter"], "%b %d %H:%M:%S %Y %Z"
            ).replace(tzinfo=timezone.utc)
            days = (not_after - datetime.now(timezone.utc)).days

            if days < 0:
                findings.append(make_finding(
                    "ssl_expired",
                    category="external",
                    title="Sertifikat SSL Telah Kedaluwarsa",
                    description=(
                        f"Sertifikat SSL {hostname} telah kedaluwarsa. "
                        "Browser akan menampilkan peringatan keamanan kepada pengunjung."
                    ),
                    affected_path=f"https://{hostname}",
                    evidence=f"expired: {cert['notAfter']}",
                    remediation=(
                        "Perbarui sertifikat SSL segera. "
                        "Aktifkan auto-renewal via Let's Encrypt atau CA lainnya."
                    ),
                ))
            elif days < 30:
                findings.append(make_finding(
                    "ssl_expiring_soon",
                    category="external",
                    title=f"Sertifikat SSL Akan Kedaluwarsa dalam {days} Hari",
                    description=(
                        f"Sertifikat SSL {hostname} akan kedaluwarsa dalam {days} hari. "
                        "Jika tidak diperpanjang akan menyebabkan error keamanan."
                    ),
                    affected_path=f"https://{hostname}",
                    evidence=f"days_left={days}, expires={cert['notAfter']}",
                    remediation=(
                        "Perpanjang sertifikat SSL sebelum kedaluwarsa. "
                        "Pertimbangkan mengaktifkan auto-renewal."
                    ),
                ))

            tls = s.version()
            if tls in ("TLSv1", "TLSv1.1"):
                findings.append(make_finding(
                    "weak_tls",
                    category="external",
                    title=f"Protokol TLS Lemah Aktif: {tls}",
                    description=(
                        f"Server {hostname} menggunakan {tls} yang sudah tidak aman "
                        "dan rentan terhadap berbagai serangan kriptografi."
                    ),
                    affected_path=f"https://{hostname}",
                    evidence=f"tls_version={tls}",
                    remediation=(
                        "Konfigurasi server web untuk menggunakan TLS 1.2 minimum "
                        "(disarankan TLS 1.3). Nonaktifkan TLS 1.0 dan 1.1."
                    ),
                ))
    except Exception:
        pass

    return findings


async def scan_http_redirect(hostname: str) -> list[FindingResult]:
    """
    Cek apakah HTTP (port 80) redirect ke HTTPS.
    Return finding jika tidak ada redirect ke HTTPS.
    Return [] jika port 80 tidak reachable. Never raises.
    """
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as c:
            resp = await c.get(f"http://{hostname}")
        if resp.status_code in (301, 302, 307, 308):
            location = resp.headers.get("location", "")
            if location.startswith("https://"):
                return []  # redirect ke HTTPS sudah ada — aman
        return [make_finding(
            "http_no_https_redirect",
            category="external",
            title="HTTP Tidak Redirect ke HTTPS",
            description=(
                f"Server {hostname} merespons HTTP tanpa redirect ke HTTPS. "
                "Kredensial login dan data sesi dapat disadap via man-in-the-middle attack."
            ),
            affected_path=f"http://{hostname}",
            evidence=f"HTTP {resp.status_code} tanpa Location: https://",
            remediation=(
                "Tambahkan redirect 301 dari HTTP ke HTTPS di konfigurasi Nginx: "
                "`return 301 https://$host$request_uri;`"
            ),
            owasp_category="A02:2021-Cryptographic-Failures",
        )]
    except Exception:
        return []
