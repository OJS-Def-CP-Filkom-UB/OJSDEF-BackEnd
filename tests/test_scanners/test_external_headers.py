from app.scanners.external.header_checker import REQUIRED


def test_required_headers_defined():
    assert "Content-Security-Policy" in REQUIRED
    assert "Strict-Transport-Security" in REQUIRED
    assert "X-Frame-Options" in REQUIRED


def test_csp_finding_type():
    ftype, _, _, _ = REQUIRED["Content-Security-Policy"]
    assert ftype == "missing_csp"


def test_hsts_finding_type():
    ftype, _, _, _ = REQUIRED["Strict-Transport-Security"]
    assert ftype == "missing_hsts"


def test_x_frame_finding_type():
    ftype, _, _, _ = REQUIRED["X-Frame-Options"]
    assert ftype == "missing_x_frame"


def test_required_values_are_4_tuples():
    for header, value in REQUIRED.items():
        assert len(value) == 4, f"{header} entry must be a 4-tuple"


def test_csp_owasp_category():
    _, _, _, owasp = REQUIRED["Content-Security-Policy"]
    assert "Injection" in owasp or "A03" in owasp
