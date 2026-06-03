from app.scanners.models import FindingResult, make_finding


def scan_config(config: dict) -> list[FindingResult]:
    """
    Analisis output PHP ConfigScanner. Format input (flat dict):
    {display_errors, show_errors, show_stacktrace, api_key_secret_length,
     force_ssl, allowed_hosts_set, installed, smtp_enabled, smtp_auth_enabled,
     smtp_password_set, db_driver, db_host, db_password_empty}
    """
    findings = []

    # K-1: Debug mode aktif (CVSS 9.8 — Critical)
    if (config.get("display_errors")
            or config.get("show_errors")
            or config.get("show_stacktrace")):
        findings.append(make_finding(
            "debug_mode_active",
            category="internal",
            title="Mode Debug OJS Aktif",
            description=(
                "OJS berjalan dalam mode debug, mengekspos stack trace PHP, "
                "query SQL, dan path internal kepada semua pengunjung saat terjadi error."
            ),
            affected_path="config.inc.php [debug]",
            evidence="display_errors=On atau show_errors=On atau show_stacktrace=On",
            remediation=(
                "Set `display_errors = Off` dan `show_stacktrace = Off` di config.inc.php. "
                "Restart web server setelah perubahan."
            ),
        ))

    # B-1: Force SSL dimatikan (CVSS 8.1 — High)
    if not config.get("force_ssl", True):
        findings.append(make_finding(
            "force_ssl_disabled",
            category="internal",
            title="Force SSL Dimatikan di Konfigurasi OJS",
            description=(
                "OJS tidak memaksa HTTPS secara native. "
                "Kredensial login dapat disadap jika HTTPS redirect tidak dikonfigurasi di web server."
            ),
            affected_path="config.inc.php [security]",
            evidence="force_ssl = Off",
            remediation=(
                "Set `force_login_ssl = On` di config.inc.php, "
                "atau pastikan Nginx sudah mengkonfigurasi redirect HTTP ke HTTPS."
            ),
        ))

    # P-2: SMTP aktif tanpa autentikasi (CVSS 5.3 — Medium)
    if (config.get("smtp_enabled")
            and not config.get("smtp_auth_enabled")
            and not config.get("smtp_password_set")):
        findings.append(make_finding(
            "smtp_no_auth",
            category="internal",
            title="SMTP Aktif Tanpa Autentikasi",
            description=(
                "Server email dikonfigurasi tanpa autentikasi. "
                "Server SMTP terbuka dapat disalahgunakan untuk relay spam "
                "atau intercept email sistem (password reset, notifikasi review)."
            ),
            affected_path="config.inc.php [email]",
            evidence="smtp = On, smtp_auth tidak dikonfigurasi",
            remediation=(
                "Tambahkan smtp_auth, smtp_username, dan smtp_password "
                "di konfigurasi email config.inc.php."
            ),
        ))

    # DB password kosong (CVSS 8.0 — High)
    if config.get("db_password_empty"):
        findings.append(make_finding(
            "db_password_empty",
            category="internal",
            title="Password Database OJS Kosong",
            description=(
                "Koneksi database OJS tidak menggunakan password. "
                "Database dapat diakses tanpa autentikasi dari proses lokal."
            ),
            affected_path="config.inc.php [database]",
            evidence="database.password = (kosong)",
            remediation=(
                "Set password database yang kuat di config.inc.php "
                "atau via environment variable OJS_DB_PASSWORD."
            ),
        ))

    # API key secret terlalu pendek (CVSS 5.0 — Medium)
    key_len = config.get("api_key_secret_length", 32)
    if isinstance(key_len, int) and 0 < key_len < 32:
        findings.append(make_finding(
            "api_key_too_short",
            category="internal",
            title="API Key Secret OJS Terlalu Pendek",
            description=(
                f"api_key_secret di config OJS hanya {key_len} karakter "
                "(minimum yang disarankan adalah 32 karakter)."
            ),
            affected_path="config.inc.php [general]",
            evidence=f"api_key_secret length = {key_len}",
            remediation="Set api_key_secret minimal 32 karakter acak di config.inc.php.",
        ))

    return findings
