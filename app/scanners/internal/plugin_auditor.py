from app.scanners.models import FindingResult, make_finding

KNOWN_SECURITY_PLUGINS = {"orcidProfile", "acron", "dois"}


def scan_plugins(plugins: list[dict]) -> list[FindingResult]:
    findings = []

    for p in plugins:
        name = p.get("name", "unknown")
        version = p.get("version", "0")

        # Check for known CVEs first
        for cve in p.get("cve_ids", []):
            findings.append(make_finding(
                "cve_vulnerable_plugin",
                category="internal",
                title=f"Plugin {name} Rentan CVE",
                description=f"Plugin {name} v{version} memiliki kerentanan yang tercatat: {cve}.",
                affected_path=f"plugins/{name}",
                evidence=f"version={version}, cve={cve}",
                remediation=f"Update plugin {name} ke versi terbaru yang telah memperbaiki kerentanan ini.",
                cve_id=cve,
            ))

        # Outdated plugin (only if no CVEs reported)
        if not p.get("cve_ids") and p.get("outdated"):
            findings.append(make_finding(
                "outdated_plugin",
                category="internal",
                title=f"Plugin {name} Sudah Usang",
                description=f"Plugin {name} v{version} tidak diperbarui ke versi terbaru.",
                affected_path=f"plugins/{name}",
                evidence=f"version={version}",
                remediation=f"Update plugin {name} ke versi terbaru melalui panel admin OJS.",
            ))

        # Disabled security plugin
        if not p.get("enabled") and name in KNOWN_SECURITY_PLUGINS:
            findings.append(make_finding(
                "disabled_security_plugin",
                category="internal",
                title=f"Plugin Keamanan {name} Dinonaktifkan",
                description=f"Plugin penting untuk keamanan {name} tidak aktif.",
                affected_path=f"plugins/{name}",
                evidence="enabled=false",
                remediation=f"Aktifkan plugin {name} melalui panel admin OJS.",
            ))

    return findings
