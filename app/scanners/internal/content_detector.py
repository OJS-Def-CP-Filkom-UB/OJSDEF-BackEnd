import re
from app.scanners.models import FindingResult, make_finding

GAMBLING = re.compile(
    r"(slot\s*online|togel|judi\s*bola|casino|poker\s*online)", re.I
)
IFRAME = re.compile(r"<iframe[^>]+src=[\"'][^\"']+[\"']", re.I)
META_REDIRECT = re.compile(
    r'<meta[^>]+http-equiv=["\']refresh["\'][^>]*url=', re.I
)


def scan_content(articles: list[dict]) -> list[FindingResult]:
    findings = []

    for a in articles:
        aid = a.get("id", "unknown")
        title = a.get("title", "")
        content = a.get("content", "")
        path = f"articles/{aid}"

        # Check for gambling/spam content in title or body
        if GAMBLING.search(title) or GAMBLING.search(content):
            findings.append(make_finding(
                "injected_content",
                category="internal",
                title="Konten Judi/Spam Ditemukan di Artikel",
                description=(
                    f"Artikel #{aid} mengandung kata kunci judi online atau spam "
                    "yang mengindikasikan kompromi konten."
                ),
                affected_path=path,
                evidence=f"title: {title[:80]}",
                remediation=(
                    "Hapus atau nonpublikasikan artikel yang terinfeksi. "
                    "Audit akses akun editor dan penulis."
                ),
            ))

        # Check for meta refresh redirects
        if META_REDIRECT.search(content):
            findings.append(make_finding(
                "malicious_redirect",
                category="internal",
                title="Meta Redirect Mencurigakan di Artikel",
                description=(
                    f"Artikel #{aid} mengandung meta refresh redirect yang "
                    "dapat mengarahkan pengunjung ke situs berbahaya."
                ),
                affected_path=path,
                evidence="meta refresh redirect ditemukan di konten artikel",
                remediation=(
                    "Hapus tag meta redirect dari konten. "
                    "Audit semua artikel lainnya untuk pola serupa."
                ),
            ))

        # Check for external iframes
        m = IFRAME.search(content)
        if m:
            findings.append(make_finding(
                "exposed_iframe",
                category="internal",
                title="iFrame Eksternal di Artikel",
                description=(
                    f"Artikel #{aid} menyematkan iframe dari sumber eksternal yang "
                    "dapat digunakan untuk clickjacking atau konten berbahaya."
                ),
                affected_path=path,
                evidence=m.group(0)[:200],
                remediation=(
                    "Hapus iframe yang tidak dikenal sumbernya. "
                    "Audit seluruh konten artikel untuk iframe mencurigakan."
                ),
            ))

    return findings
