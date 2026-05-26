from app.scanners.internal.config_scanner import scan_config
from app.scanners.internal.plugin_auditor import scan_plugins


def test_debug_flagged():
    findings = scan_config({"debug": True, "database": {"password": "strong!Pass99"}})
    assert any(x.finding_type == "debug_mode_enabled" for x in findings)


def test_clean_config_no_findings():
    findings = scan_config({"debug": False, "database": {"password": "Str0ng!Pass#2026"}})
    assert findings == []


def test_weak_password_flagged():
    findings = scan_config({"debug": False, "database": {"password": "admin"}})
    assert any(x.finding_type == "weak_db_password" for x in findings)


def test_debug_and_weak_password():
    findings = scan_config({"debug": True, "database": {"password": "password"}})
    types = [f.finding_type for f in findings]
    assert "debug_mode_enabled" in types
    assert "weak_db_password" in types


def test_cve_plugin():
    findings = scan_plugins([{"name": "p", "version": "1.0", "cve_ids": ["CVE-2024-1"]}])
    assert findings[0].finding_type == "cve_vulnerable_plugin"
    assert findings[0].cve_id == "CVE-2024-1"


def test_outdated_plugin():
    findings = scan_plugins([{"name": "p", "version": "0.9", "outdated": True, "cve_ids": []}])
    assert findings[0].finding_type == "outdated_plugin"


def test_disabled_security_plugin():
    findings = scan_plugins([{
        "name": "orcidProfile", "version": "1.0",
        "enabled": False, "cve_ids": [], "outdated": False
    }])
    assert any(f.finding_type == "disabled_security_plugin" for f in findings)


def test_non_security_disabled_plugin_not_flagged():
    findings = scan_plugins([{
        "name": "customPlugin", "version": "1.0",
        "enabled": False, "cve_ids": [], "outdated": False
    }])
    assert not any(f.finding_type == "disabled_security_plugin" for f in findings)


def test_clean_plugin_no_findings():
    findings = scan_plugins([{
        "name": "myPlugin", "version": "2.0",
        "enabled": True, "cve_ids": [], "outdated": False
    }])
    assert findings == []
