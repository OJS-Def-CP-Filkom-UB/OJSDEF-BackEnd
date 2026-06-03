from app.schemas.scans import ScanResponse


def test_scan_response_has_diagnostic_fields():
    fields = ScanResponse.model_fields
    assert "diagnostic_code" in fields
    assert "diagnostic_detail" in fields


def test_diagnostic_fields_default_none():
    r = ScanResponse(
        id="i", target_id="t", scan_type="internal", status="failed",
        overall_score=None, risk_level=None, critical_count=0, high_count=0,
        medium_count=0, low_count=0, created_at="2026-06-03T00:00:00Z",
    )
    assert r.diagnostic_code is None
    assert r.diagnostic_detail is None
