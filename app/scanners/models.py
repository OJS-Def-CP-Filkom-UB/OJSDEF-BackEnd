from dataclasses import dataclass


@dataclass
class FindingResult:
    finding_type: str
    category: str           # "internal" | "external"
    title: str
    description: str
    affected_path: str
    evidence: str
    remediation: str        # Bahasa Indonesia
    cvss_score: float
    severity: str           # low|medium|high|critical
    cve_id: str | None = None
    owasp_category: str | None = None


CVSS_SCORES: dict[str, float] = {
    "debug_mode_enabled": 7.5, "weak_db_password": 8.0, "exposed_db_backup": 9.0,
    "outdated_plugin": 6.5, "cve_vulnerable_plugin": 9.5, "disabled_security_plugin": 5.5,
    "privilege_excess": 7.0, "inactive_admin": 5.0, "modified_core_file": 8.5,
    "unknown_file": 6.0, "missing_core_file": 7.5, "injected_content": 9.0,
    "malicious_redirect": 9.5, "exposed_iframe": 8.0,
    "ojs_version_exposed": 4.0, "outdated_ojs_version": 7.0,
    "ssl_expired": 9.0, "ssl_expiring_soon": 5.0, "weak_tls": 7.5,
    "missing_csp": 6.0, "missing_hsts": 6.5, "missing_x_frame": 5.5,
    "reflected_xss": 8.5, "sql_error_exposed": 8.0, "path_traversal": 7.5,
    "open_directory": 7.0, "exposed_env_file": 9.5, "exposed_git": 9.0,
    "phpinfo_exposed": 7.0, "cve_ojs": 9.0,
}


def severity_from_score(score: float) -> str:
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    return "low"


def make_finding(finding_type: str, **kwargs) -> FindingResult:
    score = CVSS_SCORES.get(finding_type, 5.0)
    return FindingResult(
        finding_type=finding_type,
        cvss_score=score,
        severity=severity_from_score(score),
        **kwargs,
    )
