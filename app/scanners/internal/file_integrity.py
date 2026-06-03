from app.scanners.models import FindingResult, make_finding


def scan_file_integrity(fi: dict) -> list[FindingResult]:
    """
    Analisis output PHP FileIntegrityChecker. Format input:
    {status: "completed"|"skipped", total_checked, modified, missing,
     findings: [{path, status: "modified"|"missing", local_hash}]}
    Jika status != "completed" (checksums tidak tersedia), return [].
    """
    findings = []

    if fi.get("status") != "completed":
        return findings

    for f in fi.get("findings", []):
        path   = f.get("path", "")
        status = f.get("status", "")

        if status == "modified":
            is_plugin = path.startswith("plugins/")
            ftype     = "modified_plugin_file" if is_plugin else "modified_core_file"
            label     = "Plugin" if is_plugin else "File Core OJS"
            findings.append(make_finding(
                ftype,
                category="internal",
                title=f"{label} Dimodifikasi: {path}",
                description=(
                    f"File {path} telah dimodifikasi dari distribusi resmi PKP. "
                    "Ini dapat mengindikasikan injeksi kode berbahaya atau kompromi sistem."
                ),
                affected_path=path,
                evidence=f"checksum mismatch: {path}",
                remediation=(
                    "Bandingkan file dengan versi resmi OJS dari PKP GitHub releases. "
                    "Restore dari backup instalasi yang bersih jika perlu."
                ),
            ))

        elif status == "missing":
            findings.append(make_finding(
                "missing_core_file",
                category="internal",
                title=f"File Core OJS Hilang: {path}",
                description=(
                    f"File inti OJS {path} tidak ditemukan di server. "
                    "File yang hilang dapat menyebabkan error atau kerentanan keamanan."
                ),
                affected_path=path,
                evidence=f"file tidak ada: {path}",
                remediation=(
                    "Restore file dari paket OJS versi yang sesuai di PKP GitHub releases."
                ),
            ))

    return findings
