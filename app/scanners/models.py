from dataclasses import dataclass, field

from app.scanners.enrichment import ENRICHMENT_DATA


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
    references: list[str] = field(default_factory=list)
    remediation_steps: list[str] = field(default_factory=list)


CVSS_SCORES: dict[str, float] = {
    "debug_mode_enabled": 7.5, "weak_db_password": 8.0, "exposed_db_backup": 9.0,
    "outdated_plugin": 6.5, "cve_vulnerable_plugin": 9.5, "disabled_security_plugin": 5.5,
    "privilege_excess": 7.0, "inactive_admin": 5.0, "modified_core_file": 9.1,
    "unknown_file": 6.0, "missing_core_file": 7.5, "injected_content": 9.0,
    "malicious_redirect": 9.5, "exposed_iframe": 8.0,
    "ojs_version_exposed": 4.0, "outdated_ojs_version": 7.0,
    "ssl_expired": 9.0, "ssl_expiring_soon": 5.0, "weak_tls": 7.5,
    "missing_csp": 6.0, "missing_hsts": 6.5, "missing_x_frame": 5.5,
    "missing_referrer_policy": 3.1, "missing_permissions_policy": 3.1,
    "missing_x_content_type_options": 4.3,
    "reflected_xss": 8.5, "sql_error_exposed": 8.0, "path_traversal": 7.5,
    "open_directory": 7.0, "exposed_env_file": 9.5, "exposed_git": 9.0,
    "phpinfo_exposed": 7.0, "cve_ojs": 9.0,
    # New external scanner finding types (C-2)
    "http_no_https_redirect":     8.1,
    "cookie_missing_secure_flag": 3.7,
    "cookie_missing_httponly_flag": 4.3,
    "cookie_missing_samesite": 4.3,
    "ojs_admin_endpoint_exposed": 5.8,
    "ojs_oai_accessible":         2.6,
    # New internal scanner finding types (C-1)
    "debug_mode_active":           9.8,
    "force_ssl_disabled":          8.1,
    "smtp_no_auth":                5.3,
    "db_password_empty":           8.0,
    "api_key_too_short":           5.0,
    "multiple_superadmin":         7.2,
    "inactive_high_priv_account":  5.0,
    "modified_plugin_file":        7.8,
    "gambling_content":            9.5,
    "eval_base64_injection":       9.8,
    "hidden_iframe_injection":     8.3,
    "phishing_tld_link":           7.5,
    "js_redirect_injection":       6.1,
    "disabled_plugins_installed":  4.3,
    "excessive_active_plugins":    2.0,
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
    enrichment = ENRICHMENT_DATA.get(finding_type, {})
    kwargs.setdefault("references", list(enrichment.get("references", [])))
    kwargs.setdefault("remediation_steps", list(enrichment.get("remediation_steps", [])))
    return FindingResult(
        finding_type=finding_type,
        cvss_score=score,
        severity=severity_from_score(score),
        **kwargs,
    )
