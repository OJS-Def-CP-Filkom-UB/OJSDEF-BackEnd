from app.scanners.models import FindingResult, make_finding

WEAK_PASSWORDS = {"", "password", "ojsdef", "admin", "123456", "ojs", "root"}


def scan_config(config: dict) -> list[FindingResult]:
    findings = []

    if config.get("debug", False):
        findings.append(make_finding(
            "debug_mode_enabled",
            category="internal",
            title="Mode Debug Aktif",
            description="OJS berjalan dalam mode debug, mengekspos informasi sensitif kepada pengguna.",
            affected_path="config.inc.php",
            evidence="debug = On",
            remediation="Set `debug = Off` di config.inc.php dan restart server web.",
        ))

    db_pass = config.get("database", {}).get("password", "")
    if db_pass.lower() in WEAK_PASSWORDS:
        findings.append(make_finding(
            "weak_db_password",
            category="internal",
            title="Password Database Lemah",
            description="Password koneksi database OJS terlalu mudah ditebak atau kosong.",
            affected_path="config.inc.php [database] password",
            evidence=f"password = {db_pass!r}",
            remediation="Ganti password database dengan minimal 16 karakter acak yang kuat.",
        ))

    return findings
