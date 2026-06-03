# Spec C-2 — External Scanner Completeness

## Goal

Tambahkan 3 modul eksternal yang hilang sehingga scanner eksternal dapat mendeteksi: cookie tanpa Secure flag (A-2), endpoint admin OJS terbuka dari internet (P-5), OAI endpoint accessible (A-3), dan HTTP tidak redirect ke HTTPS (B-1 external). Step eksternal naik dari 7 ke 9.

## Architecture

Dua file baru + dua file yang diedit, semua di `app/scanners/external/`. Integrasi ke `external_bot.py` menambah 2 step baru (HTTP redirect digabung ke step SSL). Frontend tidak perlu diubah — `computeOverallPct` sudah pakai `ratio = current_step / total_steps` sehingga otomatis menyesuaikan.

**Tech Stack:** Python/FastAPI, Celery, httpx

---

## File Map

| File | Aksi |
|------|------|
| `app/scanners/external/ssl_analyzer.py` | Edit — tambah `scan_http_redirect()` async |
| `app/scanners/external/cookie_analyzer.py` | **Baru** |
| `app/scanners/external/endpoint_checker.py` | **Baru** |
| `app/scanners/models.py` | Edit — tambah 4 CVSS entries |
| `app/workers/external_bot.py` | Edit — integrasi scanner baru, step 7→9 |

---

## Section 1: `models.py` — Tambah CVSS Entries

Tambah ke dict `CVSS_SCORES`:

```python
"http_no_https_redirect":     8.1,   # B-1 external
"cookie_missing_secure_flag": 3.7,   # A-2
"ojs_admin_endpoint_exposed": 5.8,   # P-5
"ojs_oai_accessible":         2.6,   # A-3
```

---

## Section 2: `ssl_analyzer.py` — Tambah `scan_http_redirect()`

Tambah import `httpx` dan fungsi baru setelah `scan_ssl`. `scan_ssl` tidak diubah sama sekali.

```python
import httpx  # tambah di bagian import atas


async def scan_http_redirect(hostname: str) -> list[FindingResult]:
    """
    Cek apakah HTTP (port 80) redirect ke HTTPS.
    Return finding jika tidak ada redirect. Return [] jika port 80 tidak reachable.
    Never raises.
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
                "Kredensial dan data sesi dapat disadap via man-in-the-middle attack."
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
```

---

## Section 3: `cookie_analyzer.py` — File Baru

```python
import httpx
from app.scanners.models import FindingResult, make_finding


async def scan_cookies(url: str) -> list[FindingResult]:
    """
    Fetch halaman login OJS dan cek Set-Cookie headers untuk Secure flag.
    Tidak memerlukan login — cookies dikirim di halaman login itu sendiri.
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
                        "sebelum redirect HTTPS aktif."
                    ),
                    affected_path=f"{base}/index/login",
                    evidence=f"Set-Cookie: {raw[:120]}",
                    remediation=(
                        "Aktifkan `force_ssl = On` di config OJS atau set "
                        "`session.cookie_secure = 1` di konfigurasi PHP."
                    ),
                ))
    except Exception:
        pass

    return findings
```

---

## Section 4: `endpoint_checker.py` — File Baru

```python
import httpx
from app.scanners.models import FindingResult, make_finding


async def scan_ojs_endpoints(url: str) -> list[FindingResult]:
    """
    Cek aksesibilitas endpoint OJS dari internet:
    - /index/login dan /index/admin  → P-5 (risiko brute force)
    - /index/index/oai               → A-3 (informatif)
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

    # P-5: Endpoint admin/login terbuka dari internet
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
                "Halaman login dan admin OJS dapat diakses dari internet tanpa pembatasan IP, "
                "meningkatkan risiko serangan brute force pada akun administrator."
            ),
            affected_path=", ".join(accessible),
            evidence="; ".join(accessible),
            remediation=(
                "Tambahkan rate limiting di Nginx: "
                "`limit_req_zone $binary_remote_addr zone=ojs_login:10m rate=5r/m;` "
                "Pertimbangkan pembatasan akses IP untuk endpoint /admin."
            ),
            owasp_category="A07:2021-Identification-and-Authentication-Failures",
        ))

    # A-3: OAI endpoint accessible (informatif — bukan kerentanan)
    for path in ("/index/index/oai", "/index/oai"):
        status = await check(path)
        if status == 200:
            findings.append(make_finding(
                "ojs_oai_accessible",
                category="external",
                title="OAI-PMH Endpoint Aktif (Informatif)",
                description=(
                    "Endpoint OAI-PMH dapat diakses publik. "
                    "Ini adalah fitur standar interoperabilitas jurnal open access — bukan kerentanan."
                ),
                affected_path=f"{base}{path}",
                evidence=f"HTTP 200 pada {path}",
                remediation="Tidak diperlukan tindakan. OAI-PMH adalah fitur standar.",
            ))
            break  # cukup satu endpoint yang match

    return findings
```

---

## Section 5: `external_bot.py` — Integrasi + Step 7→9

### Import Baru

```python
from app.scanners.external.ssl_analyzer import scan_ssl, scan_http_redirect
from app.scanners.external.cookie_analyzer import scan_cookies
from app.scanners.external.endpoint_checker import scan_ojs_endpoints
```

### Urutan Step Baru (total_steps = 9)

| Step | Progress Message | Scanner(s) |
|------|-----------------|------------|
| 1/9 | Mendeteksi versi OJS dan fingerprint... | `scan_fingerprint` |
| 2/9 | Memeriksa SSL/TLS dan redirect HTTP ke HTTPS... | `scan_ssl` + `scan_http_redirect` |
| 3/9 | Menganalisis HTTP security headers... | `scan_headers` |
| 4/9 | Menguji kerentanan yang diketahui... | `scan_vulnerabilities` |
| 5/9 | Memeriksa direktori dan file sensitif... | `scan_open_dirs` |
| 6/9 | Mencocokkan CVE dari NVD... | `scan_cve` |
| 7/9 | Memeriksa keamanan cookie sesi... | `scan_cookies` |
| 8/9 | Memeriksa aksesibilitas endpoint OJS... | `scan_ojs_endpoints` |
| 9/9 | Pemindaian eksternal selesai — N temuan | DONE |

### `_run_external_scan` Lengkap (ganti seluruh fungsi)

```python
async def _run_external_scan(job_id: str, target_url: str):
    hostname = urlparse(target_url).hostname

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 1, 9, "Mendeteksi versi OJS dan fingerprint...", "TASK")
    ojs_version, fp = await scan_fingerprint(target_url)

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 2, 9, "Memeriksa SSL/TLS dan redirect HTTP ke HTTPS...", "TASK")
    ssl_findings      = scan_ssl(hostname) if hostname else []
    redirect_findings = await scan_http_redirect(hostname) if hostname else []

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 3, 9, "Menganalisis HTTP security headers...", "TASK")
    header_findings = await scan_headers(target_url)

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 4, 9, "Menguji kerentanan yang diketahui...", "TASK")
    vuln_findings = await scan_vulnerabilities(target_url)

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 5, 9, "Memeriksa direktori dan file sensitif...", "TASK")
    dir_findings = await scan_open_dirs(target_url)

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 6, 9, "Mencocokkan CVE dari NVD...", "TASK")
    cve_findings = await scan_cve(ojs_version)

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 7, 9, "Memeriksa keamanan cookie sesi...", "TASK")
    cookie_findings = await scan_cookies(target_url)

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 8, 9, "Memeriksa aksesibilitas endpoint OJS...", "TASK")
    endpoint_findings = await scan_ojs_endpoints(target_url)

    all_findings = (
        fp + ssl_findings + redirect_findings + header_findings
        + vuln_findings + dir_findings + cve_findings
        + cookie_findings + endpoint_findings
    )

    async with make_worker_session() as session:
        job = (await session.execute(select(ScanJob).where(ScanJob.id == job_id))).scalar_one()
        for f in all_findings:
            session.add(ScanFinding(
                id=uuid.uuid4(), tenant_id=job.tenant_id, job_id=job.id,
                finding_type=f.finding_type, category=f.category, title=f.title,
                description=f.description, affected_path=f.affected_path,
                evidence=f.evidence, remediation=f.remediation,
                severity=f.severity, cvss_score=f.cvss_score,
                cve_id=f.cve_id, owasp_category=f.owasp_category,
            ))
        await session.commit()

    await write_progress(
        job_id, "external_scan", 9, 9,
        f"Pemindaian eksternal selesai — {len(all_findings)} temuan", "DONE",
    )
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    raw = await r.get(f"scan_progress:{job_id}")
    progress = json.loads(raw) if raw else {}
    progress["external_done"] = True
    await r.setex(f"scan_progress:{job_id}", 3600, json.dumps(progress))
    await r.aclose()
    if await _check_cancelled(job_id): return
    await _try_trigger_scoring(job_id)
```

---

## Test Coverage After This Spec

| ID | Skenario | Status |
|----|----------|--------|
| B-1 ext | HTTP tanpa redirect ke HTTPS | ✅ `scan_http_redirect` |
| A-2 | Cookie sesi tanpa Secure flag | ✅ `scan_cookies` |
| P-5 | Admin/login endpoint terbuka | ✅ `scan_ojs_endpoints` |
| A-3 | OAI endpoint accessible | ✅ `scan_ojs_endpoints` |

---

## Deployment

```bash
# BackEnd — tidak perlu rebuild image (httpx sudah ada di requirements)
git pull
docker compose down && docker compose up -d
```
