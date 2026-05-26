import re
from packaging.version import Version
import httpx
from app.scanners.models import FindingResult, make_finding

VERSION_RE = re.compile(r'content="OJS/(\d+\.\d+[\.\d]*)"')
MINIMUM_SAFE_VERSION = "3.3.0.12"


async def scan_fingerprint(url: str) -> tuple[str | None, list[FindingResult]]:
    """
    Fingerprint OJS installation by detecting version from meta generator tag.
    Returns (version_string|None, list_of_findings).
    Never raises exceptions — returns (None, []) on any network error.
    """
    findings = []
    version = None

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            resp = await c.get(url)
            m = VERSION_RE.search(resp.text)
            if m:
                version = m.group(1)
                findings.append(make_finding(
                    "ojs_version_exposed",
                    category="external",
                    title="Versi OJS Terekspos di Source Halaman",
                    description=(
                        f"Versi OJS {version} terdeteksi dari tag meta generator di HTML source. "
                        "Informasi versi membantu penyerang menargetkan kerentanan spesifik."
                    ),
                    affected_path=url,
                    evidence=f'<meta name="generator" content="OJS/{version}">',
                    remediation=(
                        "Gunakan plugin atau konfigurasi untuk menyembunyikan "
                        "tag meta generator OJS dari halaman publik."
                    ),
                ))
                try:
                    if Version(version) < Version(MINIMUM_SAFE_VERSION):
                        findings.append(make_finding(
                            "outdated_ojs_version",
                            category="external",
                            title=f"Versi OJS {version} Sudah Usang",
                            description=(
                                f"OJS versi {version} lebih lama dari versi aman minimum "
                                f"{MINIMUM_SAFE_VERSION} dan mungkin memiliki kerentanan yang belum ditambal."
                            ),
                            affected_path=url,
                            evidence=f"detected_version={version}, minimum_safe={MINIMUM_SAFE_VERSION}",
                            remediation=(
                                f"Perbarui OJS ke versi {MINIMUM_SAFE_VERSION} atau lebih baru. "
                                "Backup database dan files sebelum upgrade."
                            ),
                        ))
                except Exception:
                    pass
    except Exception:
        pass

    return version, findings
