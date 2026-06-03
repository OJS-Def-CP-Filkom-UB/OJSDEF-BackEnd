from app.scanners.models import FindingResult, make_finding


def scan_plugins(plugins_data: dict) -> list[FindingResult]:
    """
    Analisis output PHP PluginAuditor. Format input:
    {total_installed, total_enabled,
     disabled_but_installed: [{name, category, version, enabled, path}],
     plugins: [...]}
    """
    findings = []

    total_enabled = plugins_data.get("total_enabled", 0)
    disabled      = plugins_data.get("disabled_but_installed", [])

    # P-4: Plugin terinstall tapi dinonaktifkan (CVSS 4.3 — Medium)
    if len(disabled) > 0:
        names = ", ".join(p.get("name", "?") for p in disabled[:5])
        if len(disabled) > 5:
            names += f" (+{len(disabled) - 5} lainnya)"
        findings.append(make_finding(
            "disabled_plugins_installed",
            category="internal",
            title=f"{len(disabled)} Plugin Terinstall tapi Dinonaktifkan",
            description=(
                f"Ada {len(disabled)} plugin yang masih ada di filesystem tapi tidak aktif: {names}. "
                "Plugin tidak aktif tetap mengandung kode yang bisa dieksploitasi "
                "jika memiliki kerentanan."
            ),
            affected_path="plugins/",
            evidence=f"disabled_but_installed count = {len(disabled)}: {names}",
            remediation=(
                "Uninstall plugin yang tidak diperlukan melalui OJS Plugin Gallery "
                "(Website Settings → Plugins → Plugin Gallery → Uninstall)."
            ),
        ))

    # A-4: Terlalu banyak plugin aktif — informatif (CVSS 2.0 — Low)
    if total_enabled > 20:
        findings.append(make_finding(
            "excessive_active_plugins",
            category="internal",
            title=f"{total_enabled} Plugin Aktif — Audit Disarankan",
            description=(
                f"Terdapat {total_enabled} plugin aktif. "
                "Setiap plugin menambah attack surface secara proporsional. "
                "Lakukan audit berkala untuk memastikan semua plugin benar-benar diperlukan."
            ),
            affected_path="plugins/",
            evidence=f"total_enabled = {total_enabled}",
            remediation=(
                "Nonaktifkan atau uninstall plugin yang tidak digunakan "
                "melalui OJS Plugin Gallery."
            ),
        ))

    return findings
