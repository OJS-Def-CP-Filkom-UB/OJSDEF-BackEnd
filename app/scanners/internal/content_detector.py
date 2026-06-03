from app.scanners.models import FindingResult, make_finding

PATTERN_FINDINGS: dict[str, tuple[str, str, str]] = {
    "gambling_keyword": (
        "gambling_content",
        "Konten Judi/Spam Ditemukan",
        "Hapus konten yang mengandung kata kunci judi online. "
        "Audit akses akun editor dan tinjau seluruh konten jurnal.",
    ),
    "base64_eval": (
        "eval_base64_injection",
        "Injeksi eval(base64) Ditemukan — Indikator Kompromi",
        "Hapus segera script berbahaya dari konten. "
        "Lakukan audit menyeluruh pada seluruh file server dan database.",
    ),
    "hidden_iframe": (
        "hidden_iframe_injection",
        "iFrame Tersembunyi Ditemukan",
        "Hapus tag iframe dari konten. "
        "Aktifkan Content-Security-Policy untuk memblokir iframe eksternal.",
    ),
    "phishing_tld": (
        "phishing_tld_link",
        "Link dengan TLD Berisiko Tinggi Ditemukan",
        "Hapus atau ganti link dengan domain yang legitimate (.com, .ac.id, .edu). "
        "Verifikasi semua link eksternal di konten jurnal.",
    ),
    "js_redirect": (
        "js_redirect_injection",
        "JavaScript Redirect Tersembunyi Ditemukan",
        "Hapus script redirect dari konten. "
        "Audit semua custom HTML di settings OJS.",
    ),
}


def scan_content(content: dict) -> list[FindingResult]:
    """
    Analisis output PHP ContentInjectionDetector. Format input:
    {total_scanned, affected_count,
     detections: [{submission_id: int|null, field: str, pattern: str, excerpt: str}]}
    submission_id=null berarti deteksi dari settings (journal.about, journal.footer, dll.)
    """
    findings = []

    for detection in content.get("detections", []):
        pattern = detection.get("pattern", "")
        field   = detection.get("field", "unknown")
        excerpt = detection.get("excerpt", "")
        sub_id  = detection.get("submission_id")

        if pattern not in PATTERN_FINDINGS:
            continue

        ftype, title, remediation = PATTERN_FINDINGS[pattern]
        location = f"article/{sub_id}" if sub_id is not None else f"settings/{field}"

        findings.append(make_finding(
            ftype,
            category="internal",
            title=title,
            description=f"Pattern berbahaya '{pattern}' ditemukan di {location}.",
            affected_path=location,
            evidence=excerpt[:200] if excerpt else f"pattern={pattern}",
            remediation=remediation,
        ))

    return findings
