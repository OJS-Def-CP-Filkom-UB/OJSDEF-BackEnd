from app.scanners.models import FindingResult, make_finding


def scan_file_integrity(data: dict) -> list[FindingResult]:
    findings = []

    for path in data.get("modified_core_files", []):
        findings.append(make_finding(
            "modified_core_file",
            category="internal",
            title="File Core OJS Dimodifikasi",
            description=(
                f"File inti OJS {path} telah diubah dari distribusi resmi. "
                "Ini dapat mengindikasikan injeksi kode berbahaya."
            ),
            affected_path=path,
            evidence=f"checksum mismatch: {path}",
            remediation=(
                "Bandingkan file dengan versi OJS resmi dari sumber resmi. "
                "Restore dari backup yang bersih jika perlu."
            ),
        ))

    for path in data.get("unknown_files", []):
        findings.append(make_finding(
            "unknown_file",
            category="internal",
            title="File Tidak Dikenal Ditemukan",
            description=(
                f"File {path} tidak termasuk dalam distribusi OJS standar. "
                "Keberadaan file ini dapat mengindikasikan backdoor atau malware."
            ),
            affected_path=path,
            evidence=f"tidak ada di manifest OJS: {path}",
            remediation=(
                "Identifikasi asal dan tujuan file ini. "
                "Hapus jika tidak diketahui asalnya atau tidak diperlukan."
            ),
        ))

    for path in data.get("missing_core_files", []):
        findings.append(make_finding(
            "missing_core_file",
            category="internal",
            title="File Core OJS Hilang",
            description=(
                f"File inti OJS {path} tidak ditemukan. "
                "File yang hilang dapat menyebabkan error atau kerentanan keamanan."
            ),
            affected_path=path,
            evidence=f"file tidak ada: {path}",
            remediation=(
                "Restore file dari paket OJS versi yang sesuai. "
                "Verifikasi integritas instalasi OJS."
            ),
        ))

    return findings
