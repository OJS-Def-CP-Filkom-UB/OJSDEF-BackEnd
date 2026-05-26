from app.scanners.models import severity_from_score, make_finding


def test_critical():
    assert severity_from_score(9.5) == "critical"


def test_high():
    assert severity_from_score(7.5) == "high"


def test_medium():
    assert severity_from_score(5.0) == "medium"


def test_low():
    assert severity_from_score(1.0) == "low"


def test_boundary_critical():
    assert severity_from_score(9.0) == "critical"


def test_boundary_high():
    assert severity_from_score(7.0) == "high"


def test_boundary_medium():
    assert severity_from_score(4.0) == "medium"


def test_make_finding_assigns_severity():
    f = make_finding(
        "weak_db_password",
        category="internal",
        title="T",
        description="D",
        affected_path="/",
        evidence="E",
        remediation="R",
    )
    assert f.severity == "high"
    assert f.cvss_score == 8.0


def test_make_finding_unknown_type_defaults_to_5():
    f = make_finding(
        "unknown_finding_type",
        category="internal",
        title="T",
        description="D",
        affected_path="/",
        evidence="E",
        remediation="R",
    )
    assert f.cvss_score == 5.0
    assert f.severity == "medium"


def test_make_finding_cve_ojs():
    f = make_finding(
        "cve_ojs",
        category="external",
        title="T",
        description="D",
        affected_path="/",
        evidence="E",
        remediation="R",
        cve_id="CVE-2024-1234",
    )
    assert f.severity == "critical"
    assert f.cvss_score == 9.0
    assert f.cve_id == "CVE-2024-1234"
