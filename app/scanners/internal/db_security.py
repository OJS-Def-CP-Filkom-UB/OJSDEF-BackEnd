from app.scanners.models import FindingResult, make_finding

WEAK_PASSWORDS = {"root", "toor", "password", "admin", "ojs", "", "123456"}
BACKUP_EXTENSIONS = {".sql", ".sql.gz", ".dump", ".bak"}


def scan_db_security(db_config: dict) -> list[FindingResult]:
    findings = []

    # Check for weak database password
    pw = db_config.get("password", "")
    if pw.lower() in WEAK_PASSWORDS:
        findings.append(make_finding(
            "weak_db_password",
            category="internal",
            title="Password Database Sangat Lemah",
            description=(
                "Password database OJS sangat mudah ditebak atau kosong, "
                "mengekspos database ke risiko akses tidak sah."
            ),
            affected_path="config.inc.php [database]",
            evidence=f"password = {pw!r}",
            remediation=(
                "Ganti password database dengan nilai acak minimal 16 karakter "
                "yang mengandung huruf besar, kecil, angka, dan simbol."
            ),
        ))

    # Check for exposed database backup files
    for f in db_config.get("exposed_backup_files", []):
        if any(f.endswith(ext) for ext in BACKUP_EXTENSIONS):
            findings.append(make_finding(
                "exposed_db_backup",
                category="internal",
                title="Backup Database Dapat Diakses Publik",
                description=(
                    f"File backup database {f} dapat diakses tanpa autentikasi. "
                    "Backup yang terekspos dapat mengandung data sensitif pengguna."
                ),
                affected_path=f,
                evidence=f"accessible: {f}",
                remediation=(
                    "Pindahkan file backup ke luar webroot atau lindungi dengan "
                    "autentikasi server web. Jangan simpan backup di direktori publik."
                ),
            ))

    return findings
