from datetime import datetime, timezone, timedelta
from app.scanners.models import FindingResult, make_finding


def scan_rbac(users: list[dict]) -> list[FindingResult]:
    findings = []
    stale_threshold = datetime.now(timezone.utc) - timedelta(days=180)

    for u in users:
        name = u.get("username", "unknown")
        roles = set(u.get("roles", []))

        # Check for excessive privileges: Site Administrator + Journal Manager + extra roles
        if {"Site Administrator", "Journal Manager"}.issubset(roles) and len(roles) > 2:
            findings.append(make_finding(
                "privilege_excess",
                category="internal",
                title=f"Pengguna {name} Kelebihan Hak Akses",
                description=(
                    f"Pengguna {name} memiliki kombinasi peran tinggi yang berlebihan: "
                    f"{', '.join(sorted(roles))}."
                ),
                affected_path=f"users/{name}",
                evidence=f"roles={sorted(list(roles))}",
                remediation=(
                    "Terapkan prinsip least privilege — berikan satu peran per pengguna "
                    "sesuai kebutuhannya."
                ),
            ))

        # Check for inactive admins (>180 days since last login)
        last_str = u.get("last_login")
        if last_str and "Administrator" in str(roles):
            try:
                last = datetime.fromisoformat(last_str.replace("Z", "+00:00"))
                if last < stale_threshold:
                    findings.append(make_finding(
                        "inactive_admin",
                        category="internal",
                        title=f"Admin {name} Tidak Aktif Lebih dari 6 Bulan",
                        description=(
                            f"Akun admin {name} terakhir login pada {last_str}. "
                            "Akun admin tidak aktif meningkatkan risiko keamanan."
                        ),
                        affected_path=f"users/{name}",
                        evidence=f"last_login={last_str}",
                        remediation=(
                            f"Nonaktifkan atau hapus akun admin {name} yang tidak aktif, "
                            "atau konfirmasi keperluan akun tersebut."
                        ),
                    ))
            except ValueError:
                pass

    return findings
