from app.scanners.models import FindingResult, make_finding


def scan_rbac(rbac: dict) -> list[FindingResult]:
    """
    Analisis output PHP RbacAuditor. Format input:
    {total_users, superadmin_count, multiple_superadmin: bool,
     inactive_high_priv_count, inactive_high_priv_users: [{user_id, last_login}]}
    """
    findings = []

    # B-4: Multiple superadmin (CVSS 7.2 — High)
    if rbac.get("multiple_superadmin"):
        count = rbac.get("superadmin_count", 0)
        findings.append(make_finding(
            "multiple_superadmin",
            category="internal",
            title=f"Terdapat {count} Akun Site Administrator",
            description=(
                f"Ada {count} akun Site Administrator aktif. "
                "Setiap akun superadmin yang tidak diperlukan memperluas attack surface. "
                "Prinsip least privilege dilanggar."
            ),
            affected_path="users/site_administrators",
            evidence=f"superadmin_count = {count}",
            remediation=(
                "Pertahankan hanya 1 akun Site Administrator aktif. "
                "Hapus atau downgrade role akun lainnya ke Journal Manager."
            ),
        ))

    # P-3: Akun high-privilege tidak aktif > 1 tahun (CVSS 5.0 — Medium)
    for user in rbac.get("inactive_high_priv_users", []):
        uid  = user.get("user_id", "unknown")
        last = user.get("last_login", "tidak diketahui")
        findings.append(make_finding(
            "inactive_high_priv_account",
            category="internal",
            title=f"Akun Admin Tidak Aktif > 1 Tahun (ID: {uid})",
            description=(
                f"Akun dengan hak akses tinggi (user ID: {uid}) "
                f"terakhir login pada {last}. "
                "Akun tidak aktif dapat menjadi target credential stuffing "
                "tanpa diketahui pemiliknya."
            ),
            affected_path=f"users/{uid}",
            evidence=f"user_id={uid}, last_login={last}",
            remediation=(
                f"Nonaktifkan atau hapus akun admin (ID: {uid}) "
                "yang tidak digunakan lebih dari 1 tahun."
            ),
        ))

    return findings
